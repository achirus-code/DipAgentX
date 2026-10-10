import calendar
import math
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app import cryptodata
from app.exchange import Candle, OrderResult, Ticker
from app.i18n import message_key, render
from app.strategies import STRATEGIES, Buy, Context, MarketView, Sell, open_positions
from tests.test_core import FakeExchange, make_engine

real_funding = cryptodata.funding  # the conftest replaces it with "not available" for every test

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
    assert "6 of 6 lookbacks up" in render(d.action.reason, "en") and "to 100 % invested" in render(d.action.reason, "en")
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
    assert status.startswith("⚠ Seit 2 h keine Funding-Rate von Binance oder Bybit – die Untergrenze ist aus")
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
    target = int(re.search(r"(?:target|to) (\d+) %", text).group(1))
    assert 0 < target < 100
    d = await s.evaluate(ctx(PathExchange(choppy(0.003, 0.12)), vol_target=0))
    assert "to 100 % invested" in render(d.action.reason, "en")


async def test_inflow_brake_halves_only_when_switched_on(monkeypatch):
    s = STRATEGIES["momentum"]
    set_data(monkeypatch, inflow=1.5)
    d = await s.evaluate(ctx(PathExchange(steady(0.003)), inflow_brake=True))
    assert "to 50 % invested" in render(d.action.reason, "en") and "halved" in render(d.action.reason, "en")
    d = await s.evaluate(ctx(PathExchange(steady(0.003))))
    assert "to 100 % invested" in render(d.action.reason, "en")
    set_data(monkeypatch, inflow=None)  # without fresh data the brake does nothing
    d = await s.evaluate(ctx(PathExchange(steady(0.003)), inflow_brake=True))
    assert "to 100 % invested" in render(d.action.reason, "en") and "no brake" in render(d.action.reason, "en")


async def test_waits_for_enough_price_history():
    s = STRATEGIES["momentum"]
    young = PathExchange(lambda t: 2000.0 if t > NOW - 30 * DAY else float("nan"))

    async def candles(symbol, interval, since, until):
        return [c for c in await PathExchange.candles(young, symbol, interval, since, until) if c.start > NOW - 30 * DAY]

    young.candles = candles
    d = await s.evaluate(ctx(young))
    assert d.action is None and message_key(d.status) == "momentum.no_history"
    assert "Waiting for price history (29 of 74 days)" == render(d.status, "en")


async def test_funding_falls_back_to_bybit_and_says_so(monkeypatch):
    prints = [(NOW - k * 8 * HOUR, -0.0001) for k in range(30, -1, -1)]  # −0.01 % every 8 hours: panic
    calls = []

    async def binance_down(client, symbol):
        calls.append(("binance", symbol))
        raise cryptodata.httpx.ConnectError("unreachable")

    async def bybit(client, symbol):
        calls.append(("bybit", symbol))
        return prints

    monkeypatch.setattr(cryptodata, "funding", real_funding)
    monkeypatch.setattr(cryptodata.FUNDING, "load", binance_down)
    monkeypatch.setattr(cryptodata.BYBIT_FUNDING, "load", bybit)
    assert round(await cryptodata.funding("eth", NOW), 2) == -10.95
    assert calls == [("binance", "ETHUSDT"), ("bybit", "ETHUSDT")] and cryptodata.funding_source("ETH") == "Bybit"
    d = await STRATEGIES["momentum"].evaluate(ctx(PathExchange(steady(-0.003))))
    assert isinstance(d.action, Buy) and "at least 50 % (Bybit)" in render(d.action.reason, "en")

    async def binance(client, symbol):  # Binance back: Bybit is no longer asked
        return [(t, 0.0001) for t, _ in prints]

    monkeypatch.setattr(cryptodata.FUNDING, "load", binance)
    cryptodata.FUNDING.reset()
    calls.clear()
    assert round(await cryptodata.funding("ETH", NOW), 2) == 10.95
    assert not calls and cryptodata.funding_source("ETH") == "Binance"
    d = await STRATEGIES["momentum"].evaluate(ctx(PathExchange(steady(0.003))))
    reason = render(d.action.reason, "en")
    assert "(Bybit)" not in reason and "funding +10.95% p.a." in reason


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
    assert "to 50 % invested" in render(sold[0].action.reason, "en")
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
        self.move = Decimal(0)  # shifts bid, ask and last – the market moving while an order waits

    async def ticker(self, symbol):
        return Ticker(self.price - 1 + self.move, self.price + 1 + self.move, self.price + self.move)

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
    from app import db as db_module, engine as engine_module
    from tests.test_core import make_engine
    clock = [NOW]
    monkeypatch.setattr(engine_module, "now_ms", lambda: clock[0])
    monkeypatch.setattr(db_module, "now_ms", lambda: clock[0])  # trades are stamped on the same clock
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
    first, second = (ex.orders[k] for k in list(ex.orders)[:2])
    state = db.get_bot(bot_id)["state"]
    # both slices share the waiting time of the rebalancing – it counts from its first order
    assert state["pending_order"]["limit"]["until"] == state["maker_until"] == NOW + 10 * 60_000


async def test_a_waiting_limit_order_follows_the_price(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    await engine.tick()
    first_price = ex.kinds[-1][2]
    ex.fill("0.4", status="partially_filled")
    ex.move = Decimal(-5)  # the price falls: the order stays where it is (it is the best bid now)
    clock[0] += 30_000
    await engine.tick()
    assert not ex.cancelled and len(ex.placed) == 1
    ex.move = Decimal(5)  # the price rises: the order follows it
    clock[0] += 30_000
    await engine.tick()
    assert ex.cancelled == ["order-1"] and len(ex.placed) == 2
    kind, side, price, size = ex.kinds[-1]
    assert (kind, side) == ("limit", "buy") and price == ex.price + 5 - 1 - Decimal("0.01") > first_price
    state = db.get_bot(bot_id)["state"]
    trades = db.list_trades(bot_id)
    assert len(trades) == 1 and trades[0]["order_type"] == "limit" and Decimal(trades[0]["fee"]) == 0  # the 40 %
    assert Decimal(state["pending_order"]["quote_size"]) == pytest.approx(Decimal(100) - Decimal(trades[0]["quote_amount"]))
    assert size * price <= Decimal(state["pending_order"]["quote_size"])  # never more than the rest of the amount
    assert state["pending_order"]["limit"]["until"] == NOW + 10 * 60_000  # the waiting time keeps running
    assert "Limit order at" in render(db.get_bot(bot_id)["status"], "en")
    ex.fill()
    clock[0] += 30_000
    await engine.tick()  # the rest is booked into the same trade – one slice, not two
    positions = open_positions(db.get_bot(bot_id)["state"])
    assert len(db.list_trades(bot_id)) == 2 and len(positions) == 1
    assert positions[0].cost == pytest.approx(Decimal(100), abs=Decimal("0.05"))
    assert not [e for e in db.list_events(bot_id) if e["level"] == "error"]


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
    clock[0] += 30_000
    await engine.tick()  # the waiting time of this rebalancing is used up: the next slice goes out at market too
    assert ex.kinds[-1] == ("market", "buy")


async def test_a_limit_order_never_filled_is_no_error_and_goes_out_at_market(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_wait=10)
    await engine.tick()
    clock[0] += 11 * 60_000
    await engine.tick()
    bot = db.get_bot(bot_id)
    events = db.list_events(bot_id)
    assert not [e for e in events if e["level"] == "error"]
    assert any("not filled within the waiting time – the rest goes out as a market order" in render(e["message"], "en")
               for e in events)
    assert ex.kinds[-1] == ("market", "buy") and len(db.list_trades(bot_id)) == 1
    assert not bot["state"].get("retry_after")
    for _ in range(12):  # the rest of the rebalancing at market, until the bot holds its target
        clock[0] += 30_000
        await engine.tick()
    bot = db.get_bot(bot_id)
    assert [k[0] for k in ex.kinds] == ["limit"] + ["market"] * 10 and "maker_until" not in bot["state"]
    await engine.discard_position(bot_id, open_positions(bot["state"])[0].id)
    clock[0] += 30_000
    await engine.tick()  # a new rebalancing waits as a limit order again
    assert ex.kinds[-1][0] == "limit"


async def test_sells_with_a_limit_order_a_cent_above_the_ask(tmp_path: Path, monkeypatch):
    from app.strategies import Position
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    bot = db.get_bot(bot_id)
    state = bot["state"]
    state["positions"] = [Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), paper=False, id="p1").to_state()]
    view = await engine.market_view("ETH-EUR")
    status = await engine._sell(bot, state, view, {"k": "x", "a": {}}, open_positions(state)[0], NOW + 10 * 60_000)
    assert ex.kinds[-1] == ("limit", "sell", ex.price + 1 + Decimal("0.01"), Decimal("0.05"))
    assert "Limit order at" in render(status, "en") and open_positions(state)
    ex.fill("0.5", status="partially_filled")
    ex.move = Decimal(-3)  # the price falls: the rest follows it down
    await engine._reconcile(bot, state, await engine.market_view("ETH-EUR"))
    assert ex.cancelled == ["order-1"] and ex.kinds[-1] == ("limit", "sell", ex.price + 1 - 3 + Decimal("0.01"),
                                                             Decimal("0.025"))
    assert open_positions(state)[0].qty == Decimal("0.025")  # half sold, the rest waits
    ex.fill()
    await engine._reconcile(bot, state)
    assert not open_positions(state) and not state.get("pending_order")
    sells = db.list_trades(bot_id)
    assert [t["order_type"] for t in sells] == ["limit", "limit"] and all(Decimal(t["fee"]) == 0 for t in sells)
    assert not await engine._complete_fill(bot, state) if state.get("fill_check") else True
    assert not engine._sold_but_still_open(bot, state)


async def test_sells_by_hand_go_out_at_market(tmp_path: Path, monkeypatch):
    from app.strategies import Position
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    db.update_bot(bot_id, enabled=False, state={"positions": [
        Position(Decimal("0.05"), Decimal("100"), 0, Decimal(2000), paper=False, id="p1").to_state()]})
    await engine.close_position(bot_id)
    assert ex.kinds[-1] == ("market", "sell") and not open_positions(db.get_bot(bot_id)["state"])
    assert db.list_trades(bot_id)[0]["order_type"] == "market"


async def test_market_orders_when_switched_off(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_orders=False)
    await engine.tick()
    assert ex.kinds == [("market", "buy")] and len(db.list_trades(bot_id)) == 1


async def test_a_refused_limit_order_is_no_error_and_tried_again(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch)
    ex.reject_limit = True
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert not bot["state"].get("pending_order") and not bot["state"].get("retry_after") and not ex.kinds
    assert "refused by the exchange" in render(bot["status"], "en")
    assert not [e for e in db.list_events(bot_id) if e["level"] == "error"]
    clock[0] += 30_000
    await engine.tick()  # refused again – still within the waiting time
    assert not ex.kinds
    ex.reject_limit = False
    clock[0] += 30_000
    await engine.tick()
    assert ex.kinds[-1][:2] == ("limit", "buy")
    ex.reject_limit = True
    db.update_bot(bot_id, state={**db.get_bot(bot_id)["state"], "pending_order": None})
    clock[0] += 10 * 60_000  # the waiting time is used up: market
    await engine.tick()
    assert ex.kinds[-1] == ("market", "buy")


async def test_the_bot_compares_itself_with_holding_since_its_start(tmp_path: Path, monkeypatch):
    ex, db, engine, bot_id, clock = limit_engine(tmp_path, monkeypatch, maker_orders=False)
    await engine.tick()
    hodl = engine.describe_bot(db.get_bot(bot_id), db.trade_stats())["hodl"]
    assert hodl["start_capital"] == 1000 and hodl["since"] == clock[0]
    assert hodl["hodl_value"] == pytest.approx(1000 * float(engine.snapshots["ETH-EUR"]["bid"]) / hodl["start_price"])
    assert 0 < hodl["value"] <= 1000.01

    history = engine.hodl_history(db.get_bot(bot_id))
    assert history[0] == {"t": hodl["since"], "value": 0, "bot": history[0]["bot"]}  # starts at nothing
    assert history[-1]["value"] == pytest.approx(hodl["hodl_value"] - 1000)
    # the bot's own line ends where its comparison does: what its capital is worth now minus what was put in
    assert history[-1]["bot"] == pytest.approx(hodl["value"] - hodl["start_capital"])

    bot = db.get_bot(bot_id)  # a higher amount is money put in: holding "buys" the same at the price of then
    db.update_bot(bot_id, params={**bot["params"], "amount": 2000})
    clock[0] += 60_000
    await engine.tick()
    after = engine.describe_bot(db.get_bot(bot_id), db.trade_stats())["hodl"]
    assert after["start_capital"] == pytest.approx(2000, abs=0.01) and after["deposits"] == 2
    assert after["since"] == hodl["since"]


def test_the_history_shows_the_bots_own_result_next_to_holding():
    class Exchange:  # the closes are kept per exchange object
        pass

    exchange, start = Exchange(), NOW - 9 * HOUR
    momentum_module = __import__("app.strategies.momentum", fromlist=["_closes"])
    momentum_module._closes[exchange] = {"ETH-EUR": {start - HOUR: Decimal(2100), start + 3 * HOUR: Decimal(2200)}}
    state = {"momentum": {"hodl": {"deposits": [{"at": start, "capital": "1000", "price": "2000"}]}}}
    trades = [
        {"side": "buy", "base_qty": "0.25", "quote_amount": "500.5", "created_at": start},
        {"side": "buy", "base_qty": "0.2", "quote_amount": "420", "created_at": start + 4 * HOUR},
        {"side": "sell", "base_qty": "0.25", "quote_amount": "549", "created_at": start + 5 * HOUR},
    ]
    history = momentum_module.hodl_history(state, exchange, "ETH-EUR", Decimal(2300), NOW, trades)
    assert [p["t"] for p in history] == [start, start + 3 * HOUR, start + 7 * HOUR, NOW]
    assert [p["value"] for p in history] == pytest.approx([0, 50, 100, 150])  # 0.5 ETH held from 2000 on
    # 0.25 ETH bought for 500.50 (fee included); then 0.2 more for 420 and the first 0.25 sold for 549
    assert [p["bot"] for p in history] == pytest.approx([-0.5, 24.5, 68.5, 88.5])


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


class PairExchange(PathExchange):
    """Like PathExchange, with its own price path per symbol (e.g. ETH rising while BTC falls)."""

    def __init__(self, paths: dict, now: int = NOW):
        self.paths = paths
        super().__init__(paths["ETH-EUR"], now)

    async def candles(self, symbol, interval, since, until):
        if symbol not in self.paths:
            raise RuntimeError(f"no candles for {symbol}")
        self.path = self.paths[symbol]
        try:
            return await super().candles(symbol, interval, since, until)
        finally:
            self.path = self.paths["ETH-EUR"]


def set_funding_by_coin(monkeypatch, rates: dict):
    async def fund(base, now, days=7):
        return rates.get(base.upper())

    monkeypatch.setattr(cryptodata, "funding", fund)


async def test_btc_brake_caps_eth_by_btcs_trend():
    s = STRATEGIES["momentum"]
    paths = {"ETH-EUR": steady(0.003), "BTC-EUR": steady(-0.003)}
    d = await s.evaluate(ctx(PairExchange(paths)))
    assert isinstance(d.action, Buy) and "to 100 % invested" in render(d.action.reason, "en")  # off by default
    state: dict = {}
    d = await s.evaluate(ctx(PairExchange(paths), state=state, btc_brake=True))
    text = render(d.status, "en")
    assert d.action is None and "target 0 %" in text and "BTC trend 0 of 6 up – at most 0 %" in text
    assert state["momentum"]["btc_brake"] == {"up": 0, "cap": 0, "active": True}
    rising = {"ETH-EUR": steady(0.003), "BTC-EUR": steady(0.003)}
    d = await s.evaluate(ctx(PairExchange(rising), btc_brake=True))
    assert "to 100 % invested" in render(d.action.reason, "en") and "BTC trend 6 of 6 up – no brake" in render(d.action.reason, "en")


async def test_btc_brake_drops_an_eth_only_funding_floor(monkeypatch):
    s = STRATEGIES["momentum"]
    falling = {"ETH-EUR": steady(-0.003), "BTC-EUR": steady(-0.003)}
    set_funding_by_coin(monkeypatch, {"ETH": -5.0, "BTC": 8.0})  # panic only in ETH
    d = await s.evaluate(ctx(PairExchange(falling)))
    assert isinstance(d.action, Buy) and "at least 50 %" in render(d.action.reason, "en")  # without the brake: floor
    d = await s.evaluate(ctx(PairExchange(falling), btc_brake=True))
    assert d.action is None and "target 0 %" in render(d.status, "en")
    set_funding_by_coin(monkeypatch, {"ETH": -5.0, "BTC": -3.0})  # BTC panics too: the floor stays
    d = await s.evaluate(ctx(PairExchange(falling), btc_brake=True))
    reason = render(d.action.reason, "en")
    assert isinstance(d.action, Buy) and "to 50 % invested" in reason and "floor stays" in reason


async def test_btc_brake_is_off_for_btc_and_without_btc_prices():
    s = STRATEGIES["momentum"]
    view = MarketView(PathExchange(steady(0.003)), "BTC-EUR", Ticker(Decimal("2000"), Decimal("2000"), Decimal("2000")), NOW)
    d = await s.evaluate(Context(s.normalize({"btc_brake": True}), None, {}, view))
    assert "to 100 % invested" in render(d.action.reason, "en") and "BTC trend" not in render(d.action.reason, "en")
    d = await s.evaluate(ctx(PairExchange({"ETH-EUR": steady(0.003)}), btc_brake=True))
    reason = render(d.action.reason, "en")
    assert "to 100 % invested" in reason and "BTC prices not available – no BTC brake" in reason
