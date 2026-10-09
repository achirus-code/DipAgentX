"""AI day trader: Claude's plan (take-profit, stop) runs between two checks, orders are limit-only, and the checks are
paced by the monthly API budget."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.exchange import Ticker
from app.i18n import Problem, render
from app.strategies import STRATEGIES, Context, MarketView
from app.strategies.ai import AiDecision, AiStrategy, call_cost
from tests.test_core import HOUR, FakeExchange, make_engine, pos
from tests.test_momentum import NOW, LimitExchange, steady

MIN = 60_000


def decision(action: str, confidence: int = 80, **kw) -> AiDecision:
    return AiDecision(action=action, confidence=confidence, reason_en="test", reason_de="Test", **kw)


@pytest.fixture
def claude(monkeypatch):
    """A scripted Claude: append decisions to ``answers``; every call costs ``cost`` $ and records its brief."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    script = SimpleNamespace(answers=[], briefs=[], models=[], efforts=[], cost=0.05)

    async def fake_ask(brief, news, model, effort):
        script.briefs.append(brief)
        script.models.append(model)
        script.efforts.append(effort)
        return script.answers.pop(0), script.cost

    monkeypatch.setattr(STRATEGIES["ai"], "ask", fake_ask)
    return script


def ai_state(db, bot_id) -> dict:
    return db.get_bot(bot_id)["state"]["ai"]


async def test_buy_sets_the_plan_and_the_take_profit_sells_without_asking(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "ai_interval": 5}, True, True)

    claude.answers.append(decision("buy", take_profit=2030, stop_loss=1980))
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert pos(bot) and claude.models == ["claude-fable-5-1"] and claude.efforts == ["low"]
    await engine.tick()  # the next tick sees the position and turns the plan into prices around the real entry
    plan = ai_state(db, bot_id)["plan"]
    entry = float(pos(db.get_bot(bot_id))["cost"]) / float(pos(db.get_bot(bot_id))["qty"])
    assert plan["target"] == pytest.approx(entry * 1.015, rel=1e-4) and plan["stop"] == pytest.approx(entry * 0.99, rel=1e-4)
    assert db.get_bot(bot_id)["state"]["targets"]["sell_price"] == plan["target"]
    assert len(claude.briefs) == 1  # within the gap Claude is not asked again

    ex.price = Decimal("2040")  # the take-profit is reached: sold by the bot, no Claude call
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None and len(claude.briefs) == 1
    assert "take-profit" in render(db.list_trades(bot_id)[0]["reason"], "en")
    await engine.tick()
    trades = ai_state(db, bot_id)["trades"]
    assert len(trades) == 1 and trades[0]["exit"] == "take_profit" and trades[0]["result_pct"] > 1

    ex.now += 2 * HOUR  # the next brief shows Claude its own result
    claude.answers.append(decision("wait"))
    await engine.tick()
    assert claude.briefs[-1].recent_trades[0]["exit"] == "take_profit"
    assert claude.briefs[-1].previous_decision["action"] == "buy"


async def test_the_stop_sells_at_a_loss(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50}, True, True)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1970))
    await engine.tick()
    await engine.tick()
    ex.price = Decimal("1960")
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None  # the engine's "never at a loss" does not hold back a stop
    sell = db.list_trades(bot_id)[0]
    assert sell["side"] == "sell" and float(sell["pnl"]) < 0 and "stop" in render(sell["reason"], "en")
    await engine.tick()
    assert ai_state(db, bot_id)["trades"][-1]["exit"] == "stop"


async def test_a_buy_without_stop_gets_the_max_stop_or_is_refused(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    capped = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "stop_loss": 2}, True, True)
    unprotected = db.create_bot("AI 2", "ai", "BTC-EUR", {"amount": 50, "stop_loss": 0}, True, True)
    claude.answers += [decision("buy", take_profit=2050), decision("buy", take_profit=2050)]
    await engine.tick()
    assert pos(db.get_bot(capped)) and pos(db.get_bot(unprotected)) is None
    assert "without a stop" in render(db.get_bot(unprotected)["status"], "en")
    await engine.tick()
    entry = float(pos(db.get_bot(capped))["cost"]) / float(pos(db.get_bot(capped))["qty"])
    assert ai_state(db, capped)["plan"]["stop"] == pytest.approx(entry * 0.98, rel=1e-4)


async def test_a_stop_is_never_lowered_and_never_beyond_the_max(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "stop_loss": 3, "ai_interval": 1}, True, True)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1980, next_check_minutes=1))
    await engine.tick()
    await engine.tick()
    stop = ai_state(db, bot_id)["plan"]["stop"]
    ex.now += 60 * MIN
    claude.answers.append(decision("hold", take_profit=2100, stop_loss=1900))  # wider: ignored
    await engine.tick()
    assert ai_state(db, bot_id)["plan"]["stop"] == stop
    ex.now += 60 * MIN
    ex.price = Decimal("2020")
    claude.answers.append(decision("hold", take_profit=2100, stop_loss=2005))  # raised: taken
    await engine.tick()
    assert ai_state(db, bot_id)["plan"] == {"target": 2100, "stop": 2005}
    assert "Claude: hold" in render(db.get_bot(bot_id)["status"], "en")


@pytest.mark.parametrize("cut_losses", [True, False])
async def test_claude_may_close_at_a_loss_only_when_allowed(tmp_path: Path, claude, cut_losses):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "cut_losses": cut_losses, "ai_interval": 1}, True, True)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1950))
    await engine.tick()
    ex.now += 60 * MIN
    ex.price = Decimal("1980")
    claude.answers.append(decision("sell"))
    await engine.tick()
    bot = db.get_bot(bot_id)
    if cut_losses:
        assert pos(bot) is None and float(db.list_trades(bot_id)[0]["pnl"]) < 0
    else:
        assert pos(bot) and "never sells at a loss" in render(bot["status"], "en")


async def test_minimum_confidence_holds_back_a_buy(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "min_confidence": 80}, True, True)
    claude.answers.append(decision("buy", confidence=62, take_profit=2050, stop_loss=1980))
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert pos(bot) is None and "unter der Schwelle von 80 %" in render(bot["status"], "de")
    await engine.tick()  # still visible until the next check
    assert "unter der Schwelle" in render(db.get_bot(bot_id)["status"], "de")
    assert db.list_ai_decisions(bot_id)[0]["action"] == "buy"  # the opinion is journaled as given


async def test_checks_are_paced_by_the_monthly_budget(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "budget": 30, "ai_interval": 1}, True, True)
    claude.cost = 0.10
    claude.answers.append(decision("wait"))
    await engine.tick()
    state = ai_state(db, bot_id)
    assert state["spend"]["usd"] == pytest.approx(0.10) and state["spend"]["calls"] == 1
    # the rest of the budget spread over the rest of January 1970 at 0.10 $ per check
    left_ms = (31 * 24 - 100) * HOUR
    pace = left_ms * 0.10 / (30 - 0.10)
    assert state["next_at"] - ex.now == pytest.approx(pace, rel=0.01)
    status = render(db.get_bot(bot_id)["status"], "en")
    assert "Claude: wait" in status and "API 0.10 USD of 30.00 USD this month" in status

    ex.now = state["next_at"]
    claude.answers.append(decision("wait", next_check_minutes=600))  # Claude may stretch the gap …
    await engine.tick()
    assert ai_state(db, bot_id)["next_at"] - ex.now == 4 * HOUR  # … up to 4 h

    ex.now += 4 * HOUR  # the budget is used up: no call, but a clear status
    db_bot = db.get_bot(bot_id)
    db_bot["state"]["ai"]["spend"]["usd"] = 29.95
    db.update_bot(bot_id, state=db_bot["state"])
    await engine.tick()
    assert len(claude.briefs) == 2 and "budget used up" in render(db.get_bot(bot_id)["status"], "en")

    ex.now = (31 * 24) * HOUR + MIN  # a new month, a new budget
    claude.answers.append(decision("wait"))
    await engine.tick()
    assert len(claude.briefs) == 3 and ai_state(db, bot_id)["spend"]["month"] == "1970-02"


async def test_a_price_alert_wakes_claude_early(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "ai_interval": 5}, True, True)
    claude.answers.append(decision("wait", wake_above=2010, next_check_minutes=120))
    await engine.tick()
    ex.price = Decimal("2015")
    ex.now += 2 * MIN
    await engine.tick()  # crossed, but too soon after the last check
    assert len(claude.briefs) == 1
    ex.now += ai_state(db, bot_id)["wake_after"] - ex.now
    claude.answers.append(decision("wait"))
    await engine.tick()
    assert len(claude.briefs) == 2 and claude.briefs[-1].previous_decision["price_then"] == 2000


async def test_ask_now_skips_the_wait(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "ai_interval": 30}, True, True)
    claude.answers += [decision("wait", confidence=55), decision("wait", confidence=55)]
    await engine.tick()
    await engine.tick()
    assert len(claude.briefs) == 1
    status = await engine.ask_now(bot_id)
    assert len(claude.briefs) == 2 and "Claude: wait (55 % sure)" in render(status, "en")
    assert ai_state(db, bot_id)["next_at"] > ex.now
    dip_id = db.create_bot("Dip", "dip", "ETH-EUR", {}, True, True)
    with pytest.raises(Problem):
        await engine.ask_now(dip_id)


async def test_live_orders_are_limit_only_and_never_go_to_the_market(tmp_path: Path, claude, monkeypatch):
    from app import engine as engine_module
    clock = [NOW]
    monkeypatch.setattr(engine_module, "now_ms", lambda: clock[0])
    monkeypatch.setattr(engine_module, "ORDER_POLL_DELAYS", (0,) * 7)
    ex = LimitExchange(steady(0.0))
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 100, "maker_wait": 10, "ai_interval": 5}, True, False)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1950))
    await engine.tick()
    assert ex.kinds[0][:2] == ("limit", "buy") and ex.kinds[0][2] == ex.price - 1 - Decimal("0.01")
    assert "cancelled if not filled" in render(db.get_bot(bot_id)["status"], "en")
    clock[0] += 11 * MIN
    ex.now = clock[0]
    await engine.tick()  # not filled in time: cancelled – and no market order follows
    assert ex.cancelled and all(k[0] == "limit" for k in ex.kinds)
    assert any("no market order" in render(e["message"], "en") for e in db.list_events(bot_id))
    assert pos(db.get_bot(bot_id)) is None

    clock[0] += 30 * MIN  # Claude buys again: a new limit order with a fresh waiting time, then the stop
    ex.now = clock[0]
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1990))
    await engine.tick()
    assert ex.kinds[-1][:2] == ("limit", "buy")
    ex.fill()
    clock[0] += MIN
    ex.now = clock[0]
    await engine.tick()
    assert pos(db.get_bot(bot_id))
    ex.move = Decimal(-20)  # through the stop: the sale is a limit order a cent above the ask, too
    clock[0] += MIN
    ex.now = clock[0]
    await engine.tick()
    assert ex.kinds[-1][:2] == ("limit", "sell") and ex.kinds[-1][2] == ex.price + 1 - 20 + Decimal("0.01")
    clock[0] += 11 * MIN
    ex.now = clock[0]
    await engine.tick()  # unfilled after the wait: cancelled and placed anew – still no market order
    assert all(k[0] == "limit" for k in ex.kinds) and ex.kinds[-1][:2] == ("limit", "sell")


async def test_brief_has_intraday_data():
    calls = []

    class CountingExchange(FakeExchange):
        async def candles(self, symbol, interval, since, until):
            calls.append(interval)
            return await super().candles(symbol, interval, since, until)

    ex = CountingExchange("2000", "1990")
    view = MarketView(ex, "ETH-EUR", Ticker(Decimal("1989"), Decimal("1991"), ex.price), ex.now)
    strategy = STRATEGIES["ai"]
    assert isinstance(strategy, AiStrategy)
    brief = await strategy.brief(Context(strategy.normalize({}), None, {}, view), {})
    assert set(brief.changes_pct) == {"15m", "1h", "4h", "24h", "72h"}
    assert sorted(calls) == [5, 15, 60] and len(brief.candles_5m) == 36
    assert brief.spread_pct == pytest.approx(0.1005, rel=1e-3)
    assert brief.rules["maker_fee_pct"] == 0 and brief.rules["limit_wait_minutes"] == 10
    assert {"rsi14_5m", "ema21_5m_vs_price_pct", "atr14_5m_pct"} <= set(brief.indicators)
    assert '"candles_5m":[[' in brief.to_text()


async def test_brief_includes_fear_greed_when_enabled(tmp_path: Path, claude, monkeypatch):
    from app.strategies import ai as ai_module

    async def fake_index():
        return {"fear_greed_index": 18, "classification": "Extreme Fear", "last_7_days": [18, 22, 25, 30, 28, 31, 35]}

    monkeypatch.setattr(ai_module, "fetch_fear_greed", fake_index)
    db, engine = make_engine(tmp_path, FakeExchange("2000", "1970"))
    db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "sentiment": "contrarian"}, True, True)
    db.create_bot("AI off", "ai", "BTC-EUR", {"amount": 50}, True, True)
    claude.answers += [decision("wait"), decision("wait")]
    await engine.tick()
    with_index = next(b for b in claude.briefs if b.symbol == "ETH-EUR")
    without = next(b for b in claude.briefs if b.symbol == "BTC-EUR")
    assert with_index.sentiment["mode"] == "contrarian" and '"fear_greed_index":18' in with_index.to_text()
    assert without.sentiment is None and "fear_greed" not in without.to_text()


def test_model_defaults_to_fable_and_rejects_unknown():
    normalize = STRATEGIES["ai"].normalize
    assert normalize({})["model"] == "claude-fable-5-1"
    assert normalize({"model": "claude-sonnet-5"})["model"] == "claude-fable-5-1"  # no longer offered
    assert normalize({"model": "claude-opus-5-5"})["model"] == "claude-opus-5-5"
    assert normalize({})["budget"] == 100 and normalize({})["effort"] == "low"


def test_call_cost_from_usage():
    usage = SimpleNamespace(input_tokens=3000, output_tokens=1000, cache_creation_input_tokens=0,
                            cache_read_input_tokens=1000, server_tool_use=SimpleNamespace(web_search_requests=2))
    assert call_cost(usage, "claude-fable-5-1") == pytest.approx(0.03 + 0.05 + 0.00025 + 0.02)
    assert call_cost(usage, "claude-opus-5-5") == pytest.approx(0.012 + 0.02 + 0.0002 + 0.02)


async def test_an_older_position_beyond_the_max_stop_is_not_sold_blindly(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "stop_loss": 3}, True, True)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1990))
    await engine.tick()
    bot = db.get_bot(bot_id)
    bot["state"]["ai"] = {}  # as if bought by the previous "AI decides" version
    db.update_bot(bot_id, state=bot["state"])
    ex.price = Decimal("1900")  # −5 %, beyond the max. stop-loss of 3 %
    claude.answers.append(decision("hold", take_profit=2000, stop_loss=1880))
    await engine.tick()
    assert pos(db.get_bot(bot_id)) and len(claude.briefs) == 2  # not sold – Claude was asked and set the plan
    assert ai_state(db, bot_id)["plan"]["stop"] == 1880
