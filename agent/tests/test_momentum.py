import calendar
import math
from decimal import Decimal
from pathlib import Path

from app import cryptodata
from app.exchange import Candle, Ticker
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


async def test_a_strong_uptrend_turns_lookbacks_up_sooner():
    s = STRATEGIES["momentum"]
    # +50 % until 30 days ago, −8 % until 10 days ago, +6 % since: 14 days ago the price was 4 % lower – up from the
    # +2 % of a strong uptrend (90 days: +28 %), not from the usual +5 %
    days, prices = [-200, -120, -30, -10, 0], [1000, 1000, 1500, 1380, 1462.8]

    def path(t):  # linear in the log price between the points
        x = min(max((t - NOW) / DAY, days[0]), days[-1])
        i = max(k for k in range(len(days) - 1) if days[k] <= x)
        f = (x - days[i]) / (days[i + 1] - days[i])
        return math.exp(math.log(prices[i]) * (1 - f) + math.log(prices[i + 1]) * f)

    fast, slow = {}, {}
    await s.evaluate(ctx(PathExchange(path), state=fast))
    await s.evaluate(ctx(PathExchange(path), state=slow, fast_entry=5))
    assert fast["momentum"]["on"]["14"] == 1 and slow["momentum"]["on"]["14"] == 0


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


class BookExchange(PathExchange):
    """Live orders: market orders fill at once, limit orders rest in the book until the test fills them."""

    supports_limit = True

    def __init__(self, path):
        super().__init__(path)
        self.placed, self.limits, self.cancelled = [], {}, []

    async def ticker(self, symbol):
        return Ticker(self.price - Decimal("1"), self.price + Decimal("1"), self.price)  # bid / ask one euro apart

    async def place_limit_order(self, symbol, side, *, client_order_id, base_size, price):
        oid = f"limit-{len(self.limits) + 1}"
        self.limits[oid] = {"side": side, "qty": base_size, "price": price, "filled": Decimal(0), "status": "new"}
        return oid

    def fill(self, oid, share=Decimal(1)):
        o = self.limits[oid]
        o["filled"] = o["qty"] * share
        o["status"] = "filled" if share == 1 else "partially_filled"

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        self.limits[order_id]["status"] = "cancelled"

    async def get_order(self, order_id):
        if o := self.limits.get(order_id):
            from app.exchange import OrderResult
            return OrderResult(order_id, o["status"], o["filled"], o["filled"] * o["price"], o["price"], Decimal(0), "EUR")
        return await super().get_order(order_id)


def clock(monkeypatch, start=NOW):
    import app.engine as engine_module
    now = {"t": start}
    monkeypatch.setattr(engine_module, "now_ms", lambda: now["t"])
    return now


async def test_live_orders_go_out_as_limit_orders_at_the_bid_and_cost_no_fee(tmp_path: Path, monkeypatch):
    now = clock(monkeypatch)
    ex = BookExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, False)
    await engine.tick()
    order = ex.limits["limit-1"]
    assert order["side"] == "buy" and order["price"] == ex.price - 1 and not ex.placed  # at the bid, no market order
    assert order["qty"] == Decimal("100") / order["price"] // Decimal("0.0000001") * Decimal("0.0000001")
    bot = db.get_bot(bot_id)
    assert bot["state"]["pending_order"]["limit"] and "Limit order at" in render(bot["status"], "en")
    await engine.tick()  # still resting: nothing booked, no second order
    assert len(ex.limits) == 1 and not open_positions(db.get_bot(bot_id)["state"])
    ex.fill("limit-1")
    await engine.tick()
    [position] = open_positions(db.get_bot(bot_id)["state"])
    assert position.qty == order["qty"] and position.cost == order["qty"] * order["price"]  # no fee
    await engine.tick()
    assert "limit-2" in ex.limits  # the next slice again as a limit order


async def test_an_unfilled_limit_order_is_cancelled_and_the_rest_goes_out_at_market(tmp_path: Path, monkeypatch):
    now = clock(monkeypatch)
    ex = BookExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000, "maker_wait": 10}, True, False)
    await engine.tick()
    ex.fill("limit-1", Decimal("0.4"))  # 40 % filled within the wait
    now["t"] += 9 * 60_000
    await engine.tick()
    assert not ex.cancelled
    now["t"] += 2 * 60_000  # the wait is over: cancelled, the filled part booked – the rest at market right away
    await engine.tick()
    assert ex.cancelled == ["limit-1"]
    state = db.get_bot(bot_id)["state"]
    part, rest = open_positions(state)
    assert part.qty == ex.limits["limit-1"]["qty"] * Decimal("0.4") and "pending_order" not in state
    assert len(ex.placed) == 1 and len(ex.limits) == 1  # the rest of the slice at market: it surely executes
    assert rest.order_id == "order-1" and rest.cost == 100  # the next slice towards the target, at market
    now["t"] += 31 * 60_000  # later orders try the limit order again
    await engine.tick()
    assert len(ex.limits) == 2


async def test_a_limit_order_that_never_fills_costs_no_error(tmp_path: Path, monkeypatch):
    now = clock(monkeypatch)
    ex = BookExchange(steady(0.003))
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, False)
    await engine.tick()
    now["t"] += 11 * 60_000
    await engine.tick()
    bot = db.get_bot(bot_id)
    events = [render(e["message"], "en") for e in db.list_events(bot_id)]
    assert any("not filled – the next order goes out at market" in e for e in events)
    assert not bot["state"].get("retry_after") and not any(e["level"] == "error" for e in db.list_events(bot_id))
    assert len(ex.placed) == 1 and len(open_positions(bot["state"])) == 1  # bought at market instead


async def test_limit_sells_at_the_ask_and_market_when_switched_off(tmp_path: Path, monkeypatch):
    from app.strategies import Position
    clock(monkeypatch)
    ex = BookExchange(steady(-0.003))  # downtrend: the target is 0 %
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, False)
    state = {"positions": [Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), paper=False, id="p1").to_state()],
             "momentum": {"level": 10}}
    db.update_bot(bot_id, state=state)
    await engine.tick()
    order = ex.limits["limit-1"]
    assert order["side"] == "sell" and order["price"] == ex.price + 1 and order["qty"] == Decimal("0.05")
    ex.fill("limit-1")
    await engine.tick()
    assert not open_positions(db.get_bot(bot_id)["state"])
    # switched off: market orders
    bot2 = db.create_bot("Momentum 2", "momentum", "ETH-EUR", {"amount": 1000, "maker_orders": False}, True, False)
    db.update_bot(bot2, state={"positions": [Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), paper=False,
                                                      id="p2").to_state()], "momentum": {"level": 10}})
    await engine.tick()
    assert len(ex.placed) == 1 and len(ex.limits) == 1


async def test_a_refused_limit_order_is_retried_at_market(tmp_path: Path, monkeypatch):
    from app.errors import ExchangeError
    clock(monkeypatch)
    ex = BookExchange(steady(0.003))

    async def refuse(*args, **kwargs):
        raise ExchangeError(400, "post-only order would take liquidity")

    ex.place_limit_order = refuse
    db, engine = make_engine(tmp_path, ex, live=True)
    bot_id = db.create_bot("Momentum", "momentum", "ETH-EUR", {"amount": 1000}, True, False)
    await engine.tick()
    state = db.get_bot(bot_id)["state"]
    assert state.get("taker_from") and not ex.placed
    state.pop("retry_after", None)
    db.update_bot(bot_id, state=state)
    await engine.tick()
    assert len(ex.placed) == 1 and len(open_positions(db.get_bot(bot_id)["state"])) == 1
