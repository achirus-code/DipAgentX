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
    performance = claude.briefs[-1].data["performance"]
    assert performance["recent_trades"][0]["exit"] == "take_profit"
    assert performance["stats_last_30"]["all"]["win_rate_pct"] == 100
    assert claude.briefs[-1].data["previous_decision"]["action"] == "buy"


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
    plan = ai_state(db, bot_id)["plan"]
    assert (plan["target"], plan["stop"]) == (2100, 2005)
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
    assert len(claude.briefs) == 2 and claude.briefs[-1].data["previous_decision"]["price_then"] == 2000
    assert any("price alert" in r for r in claude.briefs[-1].data["woken_by"])


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
    data = brief.data
    assert set(data["changes_pct"]) == {"15m", "1h", "4h", "24h", "72h"}
    assert sorted(calls) == [5, 15, 15, 60, 240] and len(data["last_12_candles_5m_ohlcv"]) == 12
    assert set(data["timeframes"]) == {"4h", "1h", "15m", "5m"}
    assert data["spread_pct"] == pytest.approx(0.1005, rel=1e-3)
    assert data["rules"]["maker_fee_pct"] == 0 and data["rules"]["limit_wait_minutes"] == 10
    assert {"trend", "structure", "rsi14", "adx14", "atr14_pct", "last_candles"} <= set(data["timeframes"]["15m"])
    assert brief.chart_png and brief.chart_png.startswith(b"\x89PNG")  # the chart goes along as an image
    assert data["market_leader"]["symbol"] == "BTC-EUR"


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
    assert normalize({})["budget"] == 100 and normalize({})["effort"] == "auto"


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


# --- market analysis ----------------------------------------------------------------------------------------------

from app.exchange import Candle  # noqa: E402
from app.strategies import ai_analysis as ta  # noqa: E402
from app.strategies import ai_chart  # noqa: E402


def zigzag(n: int, start: float, drift: float, swing: float, minutes: int = 15, volume: float = 5.0) -> list[Candle]:
    """Candles that rise by ``drift`` per candle with a wave of ``swing`` – higher highs and higher lows for drift > 0."""
    import math
    out, t0 = [], 1_760_000_000_000
    prev = start
    for i in range(n):
        close = start * (1 + drift * i) * (1 + swing * math.sin(i / 3))
        high, low = max(prev, close) * 1.001, min(prev, close) * 0.999
        out.append(Candle(t0 + i * minutes * 60_000, Decimal(str(round(prev, 2))), Decimal(str(round(high, 2))),
                          Decimal(str(round(low, 2))), Decimal(str(round(close, 2))), Decimal(str(volume))))
        prev = close
    return out


def test_analysis_recognises_an_uptrend_and_a_downtrend():
    up = zigzag(96, 2000, 0.002, 0.015)
    tf = ta.timeframe(up, "15m", float(up[-1].close))
    assert tf["trend"].startswith("up") and tf["structure"] == "higher highs and higher lows"
    assert tf["ema20_vs_price_pct"] < 0 < tf["ema20_slope_5_candles_pct"]
    down = zigzag(96, 2000, -0.002, 0.015)
    tf = ta.timeframe(down, "15m", float(down[-1].close))
    assert tf["trend"].startswith("down") and tf["structure"] == "lower highs and lower lows"
    assert ta.regime({"15m": tf, "1h": tf}).startswith("downtrend")
    flat = zigzag(96, 2000, 0.0, 0.004)
    assert ta.efficiency_ratio([float(c.close) for c in flat]) < 0.3


def test_levels_cluster_swing_points_around_the_price():
    candles = zigzag(96, 2000, 0.0, 0.01)
    price = float(candles[-1].close)
    lv = ta.levels(candles, price, ta.atr(candles))
    assert lv["support"] and lv["resistance"]
    assert all(z["price"] < price for z in lv["support"]) and all(z["price"] > price for z in lv["resistance"])
    assert max(z["touches"] for z in lv["support"] + lv["resistance"]) >= 2  # the same swing level, several times


def test_candle_patterns_and_scanner_breakout():
    candles = zigzag(60, 2000, 0.0, 0.002, minutes=5)
    last = candles[-1]
    # a wide bullish candle closing above the 2 h high on 4x volume
    candles[-1] = Candle(last.start, Decimal("2000"), Decimal("2060"), Decimal("1999"), Decimal("2058"), Decimal("20"))
    names = ta.candle_patterns(candles, ta.atr(candles))
    assert "wide-range" in names[-1] and "1 ago" in names[-1]
    signals = ta.scan(candles, {}, {}, 2058.0)
    assert [s.key for s in signals] == ["breakout"] and "volume" in signals[0].text
    hammer = Candle(0, Decimal("100"), Decimal("100.6"), Decimal("97"), Decimal("100.5"))
    assert "hammer" in ta.candle_patterns([hammer, hammer], None)[-1]


def test_order_book_summary_shows_the_imbalance():
    bids = [(Decimal("1999"), Decimal("2")), (Decimal("1995"), Decimal("1"))]
    asks = [(Decimal("2001"), Decimal("0.5")), (Decimal("2030"), Decimal("1"))]
    book = ta.order_book_summary((bids, asks), 2000.0)
    assert book["imbalance_0.25pct"] > 0.5 and book["largest_order_within_1pct"]["side"] == "bid"
    assert ta.order_book_summary(None, 2000.0) is None


def test_chart_is_a_valid_png():
    import struct
    import zlib
    png = ai_chart.render([("15M 24H", zigzag(96, 2000, 0.001, 0.004), True)], 2190.0, [2100.0], 2150.0, 2120.0, 2250.0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (ai_chart.W, ai_chart.PANEL_H)
    idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
    assert len(zlib.decompress(idat)) == height * (1 + width * 3)


# --- trade management and discipline ------------------------------------------------------------------------------


async def test_stop_moves_to_break_even_at_1r_and_trails(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50}, True, True)
    claude.answers.append(decision("buy", take_profit=2200, stop_loss=1980, trail_pct=1, size_pct=50))
    await engine.tick()
    assert float(pos(db.get_bot(bot_id))["cost"]) == pytest.approx(25)  # half the amount for a B setup
    await engine.tick()
    entry = float(pos(db.get_bot(bot_id))["cost"]) / float(pos(db.get_bot(bot_id))["qty"])
    ex.price = Decimal("2015")  # less than +1R: the stop stays
    await engine.tick()
    assert ai_state(db, bot_id)["plan"]["stop"] == pytest.approx(entry * 0.99, rel=1e-4)
    ex.price = Decimal("2030")  # +1.5R: break-even, trailing 1 % below the high
    await engine.tick()
    assert ai_state(db, bot_id)["plan"]["stop"] == pytest.approx(max(entry, 2030 * 0.99), rel=1e-4)
    ex.price = Decimal("2050")
    await engine.tick()
    assert ai_state(db, bot_id)["plan"]["stop"] == pytest.approx(2050 * 0.99, rel=1e-4)
    ex.price = Decimal("2025")  # falls back through the trailing stop: sold with a profit
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None and float(db.list_trades(bot_id)[0]["pnl"]) > 0
    await engine.tick()
    trade = ai_state(db, bot_id)["trades"][-1]
    assert trade["exit"] == "trailing/break-even stop" and trade["result_r"] > 1 and trade["size_pct"] == 50


async def test_daily_loss_limit_and_losing_streak_stop_new_trades(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "daily_loss_limit": 2, "loss_streak": 0}, True, True)
    claude.answers.append(decision("buy", take_profit=2100, stop_loss=1960))
    await engine.tick()
    ex.price = Decimal("1950")  # −2.5 %: stopped out
    await engine.tick()
    await engine.tick()
    status = render(db.get_bot(bot_id)["status"], "en")
    assert "Daily loss limit reached" in status and len(claude.briefs) == 1  # Claude isn't even asked
    ex.now += 24 * HOUR  # a new day
    claude.answers.append(decision("wait"))
    await engine.tick()
    assert len(claude.briefs) == 2

    bot = db.get_bot(bot_id)
    bot["state"]["ai"]["trades"] = [{"closed_at": ex.now, "result_pct": -1.0, "result_of_amount_pct": -1.0}] * 3
    db.update_bot(bot_id, params={**bot["params"], "loss_streak": 3, "daily_loss_limit": 0}, state=bot["state"])
    await engine.tick()
    assert "3 losing trades in a row" in render(db.get_bot(bot_id)["status"], "en")


async def test_the_scanner_wakes_claude_with_more_thinking(tmp_path: Path, claude, monkeypatch):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50, "ai_interval": 5}, True, True)
    claude.answers.append(decision("wait", next_check_minutes=180))
    await engine.tick()
    assert claude.efforts == ["low"]  # a routine look

    def fake_scan(c5, tf, sess, price):
        return [ta.Signal("breakout", "5m close above the 2 h high on 3.0x volume")]

    monkeypatch.setattr(ta, "scan", fake_scan)
    ex.now += 6 * MIN  # after the minimum gap, on a new 5-minute candle
    claude.answers.append(decision("wait"))
    await engine.tick()
    assert len(claude.briefs) == 2 and claude.efforts[-1] == "medium"
    assert claude.briefs[-1].data["woken_by"] == ["scanner: 5m close above the 2 h high on 3.0x volume"]
    ex.now += MIN
    await engine.tick()  # the same signal doesn't wake Claude twice
    assert len(claude.briefs) == 2


async def test_notes_are_kept_for_the_next_check(tmp_path: Path, claude):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("AI", "ai", "ETH-EUR", {"amount": 50}, True, True)
    claude.answers += [decision("wait", notes="range 1985-2010, wait for a reclaim of 2010 on volume"), decision("wait")]
    await engine.tick()
    await engine.ask_now(bot_id)
    assert claude.briefs[-1].data["your_notes"].startswith("range 1985-2010")


async def test_ask_sends_the_chart_and_the_brief_to_fable(monkeypatch):
    """The real request (against a mock transport): image + brief, effort, fallback beta, streaming."""
    import json as jsonlib

    import anthropic
    import httpx2

    captured = {}
    answer = {"action": "wait", "confidence": 55, "reason_en": "a", "reason_de": "b", "setup": "none",
              "take_profit": 0, "stop_loss": 0, "size_pct": 0, "trail_pct": 0, "max_hold_minutes": 0,
              "wake_above": 2050, "wake_below": 0, "next_check_minutes": 30, "notes": "x"}

    def handler(request):
        captured["body"] = jsonlib.loads(request.content)
        captured["beta"] = request.headers.get("anthropic-beta")
        text = jsonlib.dumps(answer)
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "m", "type": "message", "role": "assistant", "model": "claude-fable-5-1", "content": [],
                "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 6000, "output_tokens": 1}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 1500}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        body = "".join(f"event: {e}\ndata: {jsonlib.dumps(d)}\n\n" for e, d in events)
        return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})

    strategy = STRATEGIES["ai"]
    monkeypatch.setattr(strategy, "_client", anthropic.AsyncAnthropic(
        api_key="x", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    ex = FakeExchange("2000", "1990")
    view = MarketView(ex, "ETH-EUR", Ticker(Decimal("1989"), Decimal("1991"), ex.price), ex.now)
    brief = await strategy.brief(Context(strategy.normalize({}), None, {}, view), {})
    result, cost = await strategy.ask(brief, False, "claude-fable-5-1", "medium")
    body = captured["body"]
    assert result.action == "wait" and result.wake_above == 2050
    assert cost == pytest.approx(6000 * 10 / 1e6 + 1500 * 50 / 1e6)
    assert body["model"] == "claude-fable-5-1" and body["output_config"]["effort"] == "medium"
    assert body["fallbacks"] == "default" and captured["beta"] == "server-side-fallback-2026-07-01" and body["stream"]
    image, text = body["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert text["text"].startswith("Market brief:") and '"market_phase"' in text["text"]
    assert "thinking" not in body  # Fable thinks adaptively by itself
