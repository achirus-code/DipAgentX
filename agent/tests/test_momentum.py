import calendar
import math
from decimal import Decimal
from pathlib import Path

import pytest

from app import cryptodata
from app.exchange import Candle, OrderResult, Ticker
from app.i18n import message_key, render
from app.strategies import STRATEGIES, Buy, Context, MarketView, Sell, open_positions
from tests.test_core import FakeExchange, make_engine

HOUR = 3_600_000
DAY = 24 * HOUR
STEP = 4 * HOUR
NOW = calendar.timegm((2026, 10, 5, 12, 0, 0)) * 1000


def steady(per_candle: float):
    """A price that changes by ``per_candle`` every 4 hours and is 2000 now."""
    return lambda t: 2000 * (1 + per_candle) ** ((t - NOW) / STEP)


def choppy(per_candle: float, swing: float):
    """Like steady, but every other day ``swing`` higher – a very volatile market."""
    return lambda t: steady(per_candle)(t) * (1 + swing * ((t // DAY) % 2))


class PathExchange(FakeExchange):
    """4-hour candles closing on ``path(start + 4 h)``; the price now is ``path(now)``."""

    def __init__(self, path, now: int = NOW):
        self.path = path
        super().__init__("2000", "2000")
        self.now = now
        self.requests = 0

    @property
    def price(self):
        return Decimal(str(round(self.path(self.now), 2)))

    @price.setter
    def price(self, value):
        pass

    async def ticker(self, symbol):
        return Ticker(self.price, self.price, self.price)

    async def candles(self, symbol, interval, since, until):
        self.requests += 1
        step = interval * 60_000
        out = []
        for t in range(since - since % step, min(until, self.now), step):
            close = Decimal(str(round(self.path(t + step), 2)))
            out.append(Candle(t, close, close, close, close))
        return out


def ctx(ex, state=None, position=None, **params):
    s = STRATEGIES["momentum"]
    view = MarketView(ex, "ETH-EUR", Ticker(ex.price, ex.price, ex.price), ex.now)
    return Context(s.normalize(params), position, {} if state is None else state, view)


def set_data(monkeypatch, funding=None, inflow=None):
    async def fund(base, now, days=7):
        return funding

    async def flow(base, now):
        return inflow

    monkeypatch.setattr(cryptodata, "funding", fund)
    monkeypatch.setattr(cryptodata, "exchange_inflow", flow)


async def test_an_uptrend_buys_the_first_slice():
    s = STRATEGIES["momentum"]
    d = await s.evaluate(ctx(PathExchange(steady(0.003)), amount=1000))
    assert isinstance(d.action, Buy) and d.action.quote_amount == Decimal("100.00")  # 10 % of the capital per trade
    assert "6 of 6 lookbacks up" in render(d.action.reason, "en") and "target 100 %" in render(d.action.reason, "en")
    assert "funding rate not available" in render(d.action.reason, "en")  # no data: the floor does nothing


async def test_missing_funding_data_is_shown_first_and_as_the_hint(tmp_path: Path, monkeypatch):
    ex = PathExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, True)
    for _ in range(12):
        await engine.tick()
    ex.now += 2 * HOUR
    await engine.tick()
    bot = db.get_bot(bot_id)
    status = render(bot["status"], "de")
    assert status.startswith("⚠ Seit 2 h keine Funding-Rate von Binance – die Untergrenze ist aus")
    assert "Untergrenze ist aus" in engine.describe_bot(bot, {}, "de")["hint"]
    set_data(monkeypatch, funding=8.0)  # back: no warning any more
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert not render(bot["status"], "en").startswith("⚠") and not engine.describe_bot(bot, {}, "en")["hint"]
    assert "funding_missing_since" not in bot["state"]["momentum"]


async def test_a_downtrend_stays_in_cash_unless_funding_shows_panic(monkeypatch):
    s = STRATEGIES["momentum"]
    falling = PathExchange(steady(-0.003))
    d = await s.evaluate(ctx(falling))
    assert d.action is None and "target 0 %" in render(d.status, "en")
    set_data(monkeypatch, funding=-5.0)
    d = await s.evaluate(ctx(PathExchange(steady(-0.003))))
    assert isinstance(d.action, Buy) and "at least 50 %" in render(d.action.reason, "en")
    set_data(monkeypatch, funding=8.0)  # normal funding: no floor
    assert (await s.evaluate(ctx(PathExchange(steady(-0.003))))).action is None
    assert (await s.evaluate(ctx(PathExchange(steady(-0.003)), funding_floor=0))).action is None


async def test_high_volatility_means_less():
    s = STRATEGIES["momentum"]
    state: dict = {}
    d = await s.evaluate(ctx(PathExchange(choppy(0.003, 0.12)), state=state))
    text = render(d.status if d.action is None else d.action.reason, "en")
    assert "– less" in text
    target = int(text.split("target ")[1].split(" %")[0])
    assert 0 < target < 100
    d = await s.evaluate(ctx(PathExchange(choppy(0.003, 0.12)), vol_target=0))
    assert "target 100 %" in render(d.action.reason, "en")


async def test_inflow_brake_halves_only_when_switched_on(monkeypatch):
    s = STRATEGIES["momentum"]
    set_data(monkeypatch, inflow=1.5)
    d = await s.evaluate(ctx(PathExchange(steady(0.003)), inflow_brake=True))
    assert "target 50 %" in render(d.action.reason, "en") and "halved" in render(d.action.reason, "en")
    d = await s.evaluate(ctx(PathExchange(steady(0.003))))
    assert "target 100 %" in render(d.action.reason, "en")
    set_data(monkeypatch, inflow=None)  # without fresh data the brake does nothing
    d = await s.evaluate(ctx(PathExchange(steady(0.003)), inflow_brake=True))
    assert "target 100 %" in render(d.action.reason, "en") and "no brake" in render(d.action.reason, "en")


async def test_waits_for_enough_price_history():
    s = STRATEGIES["momentum"]
    young = PathExchange(lambda t: 2000.0 if t > NOW - 30 * DAY else float("nan"))

    async def candles(symbol, interval, since, until):
        return [c for c in await PathExchange.candles(young, symbol, interval, since, until) if c.start > NOW - 30 * DAY]

    young.candles = candles
    d = await s.evaluate(ctx(young))
    assert d.action is None and message_key(d.status) == "momentum.no_history"
    assert "Waiting for price history (29 of 74 days)" == render(d.status, "en")


def test_funding_and_inflow_figures():
    prints = [(NOW - k * 8 * HOUR, 0.0001) for k in range(30, -1, -1)]  # 0.01 % every 8 hours
    assert round(cryptodata.average_funding(prints, NOW), 2) == 10.95  # = 0.0001 · 3 · 365 · 100
    assert cryptodata.average_funding(prints, NOW + 3 * DAY) is None  # stale
    days = [(NOW // DAY * DAY - k * DAY, 120.0, 100.0, 10_000.0) for k in range(10, 0, -1)]
    assert round(cryptodata.net_inflow(days, NOW), 3) == 1.4  # 7 days · 20 net / 10,000 held
    assert cryptodata.net_inflow(days[:5], NOW) is None  # too few days


async def test_engine_holds_the_target_in_slices_and_sells_at_a_loss_when_the_trend_breaks(tmp_path: Path):
    peak = NOW + 2 * DAY

    def path(t):  # up until two days from now, then down 1 % every 4 hours
        return steady(0.003)(min(t, peak)) * (0.99 ** ((t - peak) / STEP) if t > peak else 1)

    ex = PathExchange(path)
    db, engine = make_engine(tmp_path, ex)
    db.set_limits({"max_open_positions": 1})  # the sliced position counts as one
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, True)
    for _ in range(12):
        await engine.tick()
    state = db.get_bot(bot_id)["state"]
    positions = open_positions(state)
    assert len(positions) == 10 and abs(sum(p.cost for p in positions) - 1000) < 1
    trades = db.list_trades(bot_id)
    for _ in range(5):  # nothing changes: no more trades
        await engine.tick()
    assert len(db.list_trades(bot_id)) == len(trades)
    assert "100 % invested, target 100 %" in render(db.get_bot(bot_id)["status"], "en")

    ex.now = peak + 25 * DAY  # −78 % since the peak: every lookback turns down
    for _ in range(15):
        await engine.tick()
    state = db.get_bot(bot_id)["state"]
    sells = [t for t in db.list_trades(bot_id) if t["side"] == "sell"]
    assert sells and all(Decimal(t["pnl"]) < 0 for t in sells)  # sold although at a loss
    assert not open_positions(state)
    assert Decimal(state["realized"]) < -300
    assert "0 % invested, target 0 %" in render(db.get_bot(bot_id)["status"], "en")


async def test_sells_one_slice_when_the_target_drops_a_step(monkeypatch):
    from app.strategies import Position
    s = STRATEGIES["momentum"]
    slices = [Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), id=f"p{i}") for i in range(10)]
    state = {"momentum": {"level": 10}, "positions": [p.to_state() for p in slices]}
    set_data(monkeypatch, funding=-5.0)  # trend down, but panic: the target falls to the 50 % floor
    falling = PathExchange(steady(-0.003))
    decisions = [await s.evaluate(ctx(falling, state=state, position=p, amount=1000)) for p in slices]
    sold = [d for d in decisions if isinstance(d.action, Sell)]
    assert len(sold) == 1 and sold[0].action.stop  # one trade per check – also at a loss
    assert "target 50 %" in render(sold[0].action.reason, "en")
    # the target step didn't change: the position drifts with the price, nothing is traded
    state = {"momentum": {"level": 5}, "positions": [p.to_state() for p in slices]}
    decisions = [await s.evaluate(ctx(falling, state=state, position=p, amount=1000)) for p in slices]
    assert all(d.action is None for d in decisions)


async def test_live_mode_buys_and_sells_real_orders_in_slices(tmp_path: Path):
    peak = NOW + 2 * DAY

    def path(t):
        return steady(0.003)(min(t, peak)) * (0.99 ** ((t - peak) / STEP) if t > peak else 1)

    ex = PathExchange(path)
    ex.placed = []
    db, engine = make_engine(tmp_path, ex, live=True)
    db.set_limits({"max_open_positions": 1})
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, False)
    for _ in range(25):  # an order per check, then its fill is booked
        await engine.tick()
    state = db.get_bot(bot_id)["state"]
    positions = open_positions(state)
    assert len(positions) == 10 and not any(p.paper for p in positions)
    assert len(ex.placed) == 10 and abs(sum(p.cost for p in positions) - 1000) < 1
    ex.now = peak + 25 * DAY
    for _ in range(30):
        await engine.tick()
    state = db.get_bot(bot_id)["state"]
    assert not open_positions(state) and len(ex.placed) == 20  # ten live sells
    assert not state.get("pending_order") and not state.get("holdings_mismatch")


async def test_switching_to_live_closes_the_paper_slices_and_starts_afresh(tmp_path: Path):
    ex = PathExchange(steady(0.003))
    ex.placed = []
    db, engine = make_engine(tmp_path, ex, live=True)
    db.set_limits({"max_open_positions": 1})
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, True)
    for _ in range(12):
        await engine.tick()
    assert len(open_positions(db.get_bot(bot_id)["state"])) == 10 and not ex.placed  # paper
    db.update_bot(bot_id, paper=False)
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert not open_positions(bot["state"]) and "realized" not in bot["state"]
    assert "starts afresh" in render(bot["status"], "en")
    for _ in range(25):
        await engine.tick()
    positions = open_positions(db.get_bot(bot_id)["state"])
    assert len(positions) == 10 and not any(p.paper for p in positions) and len(ex.placed) == 10


async def test_trades_sold_by_hand_are_bought_back_to_the_target(tmp_path: Path):
    ex = PathExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, True)
    for _ in range(12):
        await engine.tick()
    assert len(open_positions(db.get_bot(bot_id)["state"])) == 10
    await engine.close_position(bot_id)  # "Sell position now": all slices
    assert not open_positions(db.get_bot(bot_id)["state"])
    for _ in range(12):
        await engine.tick()
    assert len(open_positions(db.get_bot(bot_id)["state"])) == 10  # the target is still 100 %


async def test_the_newest_candle_is_fetched_again():
    from app.strategies.momentum import four_hour_closes
    ex = PathExchange(steady(0.003))
    view = MarketView(ex, "ETH-EUR", Ticker(ex.price, ex.price, ex.price), ex.now)
    store = await four_hour_closes(view)
    last = max(store)
    store[last] = Decimal("1")  # not final yet when it was fetched
    view = MarketView(ex, "ETH-EUR", Ticker(ex.price, ex.price, ex.price), ex.now + 60_000)
    assert (await four_hour_closes(view))[last] != Decimal("1")


async def test_final_candles_are_not_fetched_on_every_check():
    from app.strategies.momentum import four_hour_closes
    ex = PathExchange(steady(0.003))

    async def check(at: int) -> dict:
        ex.now = at
        return await four_hour_closes(MarketView(ex, "ETH-EUR", Ticker(ex.price, ex.price, ex.price), at))

    await check(NOW + 10 * 60_000)  # the newest candle closed 10 minutes ago – final
    before = ex.requests
    for minute in range(11, 240, 1):
        await check(NOW + minute * 60_000)
    assert ex.requests == before  # nothing new until the next candle closes
    store = await check(NOW + STEP + 60_000)
    assert ex.requests == before + 1 and max(store) == NOW


# --- limit orders (maker, live on Revolut X) ---------------------------------------------------------------------


class LimitExchange(PathExchange):
    """Bid 1 below and ask 1 above the price; limit orders wait until a test fills them."""

    supports_limit = True

    def __init__(self, path):
        super().__init__(path)
        self.placed, self.kinds, self.cancelled = [], [], []
        self.reject_limit = False

    async def ticker(self, symbol):
        return Ticker(self.price - 1, self.price + 1, self.price)

    async def place_market_order(self, symbol, side, *, client_order_id, base_size=None, quote_size=None):
        self.kinds = [*self.kinds, ("market", side)]
        return await super().place_market_order(symbol, side, client_order_id=client_order_id,
                                                base_size=base_size, quote_size=quote_size)

    async def place_limit_order(self, symbol, side, *, client_order_id, base_size, price):
        from app.revolutx import RevolutXError
        if self.reject_limit:
            raise RevolutXError(400, "post only order would cross")
        self.placed = [*self.placed, client_order_id]
        self.kinds = [*self.kinds, ("limit", side, price, base_size)]
        oid = f"order-{len(self.placed)}"
        self.orders = {**getattr(self, "orders", {}),
                       client_order_id: OrderResult(oid, "new", Decimal(0), Decimal(0), price, Decimal(0), "EUR")}
        return oid

    def fill(self, share: str = "1", status: str = "filled"):
        """Fill the newest limit order (``share`` of it) at its price, without a fee."""
        key, order = list(self.orders.items())[-1]
        kind = self.kinds[-1]
        filled = (kind[3] * Decimal(share)).quantize(Decimal("0.0000001"))
        self.orders[key] = OrderResult(order.order_id, status, filled, filled * kind[2], kind[2], Decimal(0), "EUR")

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        for key, o in self.orders.items():
            if o.order_id == order_id and not o.terminal:
                self.orders[key] = OrderResult(o.order_id, "cancelled", o.filled_qty, o.filled_amount, o.avg_price,
                                               o.fee, o.fee_currency)


def limit_engine(tmp_path, monkeypatch, **params):
    from app import engine as engine_module
    from tests.test_core import make_engine
    clock = [NOW]
    monkeypatch.setattr(engine_module, "now_ms", lambda: clock[0])
    monkeypatch.setattr(engine_module, "ORDER_POLL_DELAYS", (0,) * 7)
    ex = LimitExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000, **params}, True, False)
    return ex, db, engine, bot_id, clock


async def test_buys_with_a_fee_free_limit_order_at_the_bid(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert ex.kinds[0][:2] == ("limit", "buy") and ex.kinds[0][2] == ex.price - 1 - Decimal("0.01")  # a cent below the best bid
    assert bot["state"]["pending_order"]["limit"] and not db.list_trades(bot_id)
    assert "Limit order at" in render(bot["status"], "en") and "no fee" in render(bot["status"], "en")
    await engine.tick()  # still waiting: nothing is booked, nothing new placed
    assert not db.list_trades(bot_id) and len(ex.placed) == 1
    ex.fill()
    clock[0] += 60_000
    await engine.tick()  # booked – and the next slice goes out in the same check
    trades = db.list_trades(bot_id)
    assert len(trades) == 1 and Decimal(trades[0]["fee"]) == 0 and Decimal(trades[0]["price"]) == ex.price - 1 - Decimal("0.01")
    assert trades[0]["order_type"] == "limit"
    assert len(ex.placed) == 2 and ex.kinds[-1][0] == "limit"


async def test_a_partial_fill_is_booked_after_the_wait_and_the_rest_bought_at_market(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_wait=10)
    await engine.tick()
    ex.fill("0.5", status="partially_filled")
    clock[0] += 5 * 60_000
    await engine.tick()  # within the waiting time: nothing booked yet
    assert not db.list_trades(bot_id) and not ex.cancelled
    clock[0] += 6 * 60_000
    await engine.tick()
    trades = db.list_trades(bot_id)
    assert ex.cancelled and len(trades) == 2  # half of the limit order, then the rest at market
    assert ex.kinds[-1] == ("market", "buy")
    assert [t["order_type"] for t in trades] == ["market", "limit"]  # newest first
    assert engine.describe_bot(db.get_bot(bot_id), db.trade_stats())["fees"] == sum(float(t["fee"]) for t in trades)
    assert not [e for e in db.list_events(bot_id) if e["level"] == "error"]
    assert db.get_bot(bot_id)["state"]["taker_from"] == clock[0]


async def test_a_limit_order_never_filled_is_no_error_and_goes_out_at_market(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_wait=10)
    await engine.tick()
    clock[0] += 11 * 60_000
    await engine.tick()
    bot = db.get_bot(bot_id)
    events = db.list_events(bot_id)
    assert not [e for e in events if e["level"] == "error"]
    assert any("not filled – the next order goes out as a market order" in render(e["message"], "en") for e in events)
    assert ex.kinds[-1] == ("market", "buy") and len(db.list_trades(bot_id)) == 1
    assert not bot["state"].get("retry_after")
    clock[0] += 31 * 60_000  # 30 minutes later limit orders again
    await engine.tick()
    assert ex.kinds[-1][0] == "limit"


async def test_sells_right_away_at_market(tmp_path: Path, monkeypatch):
    from app.strategies import Position
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    bot = db.get_bot(bot_id)
    state = bot["state"]
    state["positions"] = [Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), paper=False, id="p1").to_state()]
    view = await engine.market_view("ETH-EUR")
    await engine._sell(bot, state, view, {"k": "x", "a": {}}, open_positions(state)[0])
    assert ex.kinds[-1] == ("market", "sell") and not open_positions(state)
    assert db.list_trades(bot_id)[0]["order_type"] == "market"


async def test_market_orders_when_switched_off(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_orders=False)
    await engine.tick()
    assert ex.kinds == [("market", "buy")] and len(db.list_trades(bot_id)) == 1


async def test_a_rejected_limit_order_is_retried_at_market(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    ex.reject_limit = True
    await engine.tick()
    state = db.get_bot(bot_id)["state"]
    assert not state.get("pending_order") and state["taker_from"] == clock[0] and not ex.kinds
    clock[0] += 6 * 60_000  # after the error pause
    await engine.tick()
    assert ex.kinds == [("market", "buy")] and len(db.list_trades(bot_id)) == 1


async def test_the_bot_compares_itself_with_holding_since_its_start(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_orders=False)
    await engine.tick()
    hodl = engine.describe_bot(db.get_bot(bot_id), db.trade_stats())["hodl"]
    assert hodl["start_capital"] == 1000 and hodl["since"] == clock[0]
    assert hodl["hodl_value"] == pytest.approx(1000 * float(engine.snapshots["ETH-EUR"]["bid"]) / hodl["start_price"])
    assert 0 < hodl["value"] <= 1000.01

    history = engine.hodl_history(db.get_bot(bot_id))
    assert history and history[-1]["value"] == pytest.approx(hodl["hodl_value"] - 1000)

    bot = db.get_bot(bot_id)  # a higher amount is money put in: holding "buys" the same at the price of then
    db.update_bot(bot_id, params={**bot["params"], "amount": 2000})
    clock[0] += 60_000
    await engine.tick()
    after = engine.describe_bot(db.get_bot(bot_id), db.trade_stats())["hodl"]
    assert after["start_capital"] == pytest.approx(2000, abs=0.01) and after["deposits"] == 2
    assert after["since"] == hodl["since"]


async def test_the_indicators_come_with_what_they_mean_for_the_decision(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_orders=False)
    await engine.tick()
    signals = engine.describe_bot(db.get_bot(bot_id), db.trade_stats(), "en")["signals"]
    assert signals[0]["text"].startswith("trend:") and signals[0]["tone"] == "good"
    assert all(s["tone"] in {"good", "warn", "bad"} for s in signals) and len(signals) >= 2
    lookbacks = engine.describe_bot(db.get_bot(bot_id), db.trade_stats(), "en")["lookbacks"]
    assert [x["days"] for x in lookbacks["items"]] == [14, 21, 30, 40, 50, 60] and lookbacks["entry"] == 5
    assert sum(x["up"] for x in lookbacks["items"]) == int(signals[0]["text"].split()[1])
    decision = engine.describe_bot(db.get_bot(bot_id), db.trade_stats(), "en")["decision"]
    assert decision.startswith("Target ") and ("buys the rest" in decision or "holds" in decision)
