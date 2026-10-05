import calendar
import time
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app import macro
from app.exchange import TRADEREPUBLIC, Candle, Fees, Ticker
from app.i18n import render
from app.strategies import STRATEGIES, Buy, Context, MarketView, Position, Sell, open_positions
from app.strategies.trend import month_end_closes, month_of, next_month_start
from tests.test_core import FakeExchange
from tests.test_traderepublic import ms, two_brokers

DAY = 86_400_000
EUNL = "IE00B4L5Y983-EUR"  # iShares Core MSCI World


def utc(*args: int) -> int:
    return calendar.timegm((*args, *[0] * (6 - len(args)))) * 1000


NOW = utc(2026, 10, 5, 12)  # Monday – the last completed month is September 2026


def months_back(values: list[float], last: str = "2026-09") -> dict[str, float]:
    """{"2026-09": values[-1], "2026-08": values[-2], …}"""
    year, mon = map(int, last.split("-"))
    out = {}
    for v in reversed(values):
        out[f"{year:04d}-{mon:02d}"] = v
        year, mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    return out


class MonthlyExchange(FakeExchange):
    """Daily candles on weekdays, closing at the value of their month in ``closes``; the price now is ``price``."""

    def __init__(self, closes: dict[str, float], price: float, now: int = NOW):
        super().__init__(str(price), str(price))
        self.closes = {k: Decimal(str(v)) for k, v in closes.items()}
        self.now = now
        self.daily_requests = 0

    async def candles(self, symbol, interval, since, until):
        if interval != 1440:
            return await super().candles(symbol, interval, since, until)
        self.daily_requests += 1
        out = []
        for t in range(since - since % DAY, until + 1, DAY):
            v = self.closes.get(month_of(t))
            if v is not None and time.gmtime(t / 1000).tm_wday < 5:
                out.append(Candle(t, v, v, v, v))
        return out


def ctx(ex, position=None, state=None, **params):
    s = STRATEGIES["trend"]
    view = MarketView(ex, "ETH-EUR", Ticker(ex.price, ex.price, ex.price), ex.now)
    return Context(s.normalize(params), position, {} if state is None else state, view)


RISING = months_back([90, 92, 94, 96, 98, 100, 102, 104, 106, 112])  # average 99.4, last 112: clearly up
FALLING = months_back([110, 110, 110, 110, 108, 106, 104, 102, 100, 90])  # average 106, last 90: clearly down


def bought_at(price: str, amount: str = "1000") -> Position:
    return Position(Decimal(amount) / Decimal(price), Decimal(amount), 0, Decimal(price))


def test_month_end_closes_take_the_last_trading_day_and_stop_at_a_gap():
    candles = [Candle(utc(2026, 9, 29), 1, 1, 1, Decimal("1")), Candle(utc(2026, 9, 30), 1, 1, 1, Decimal("2")),
               Candle(utc(2026, 8, 31), 1, 1, 1, Decimal("3")), Candle(utc(2026, 6, 30), 1, 1, 1, Decimal("4")),
               Candle(utc(2026, 10, 2), 1, 1, 1, Decimal("5"))]  # the running month doesn't count
    assert month_end_closes(candles, NOW) == [("2026-09", Decimal("2")), ("2026-08", Decimal("3"))]
    assert month_of(utc(2026, 12, 31, 23)) == "2026-12" and next_month_start(utc(2026, 12, 15)) == utc(2027, 1, 1)


async def test_buys_the_whole_amount_above_the_average():
    s = STRATEGIES["trend"]
    state: dict = {}
    d = await s.evaluate(ctx(MonthlyExchange(RISING, 113), state=state, amount=4000))
    assert isinstance(d.action, Buy) and d.action.quote_amount == Decimal("4000")
    assert "10-month average" in render(d.action.reason, "en") and "Sep 2026" in render(d.action.reason, "en")
    assert state["targets"]["note"]["k"] == "targets.trend_check"
    assert "Nov 1" in render(state["targets"]["note"], "en")
    # invested: the decision holds for the month
    d = await s.evaluate(ctx(MonthlyExchange(RISING, 113), bought_at("112"), state=state, amount=4000))
    assert d.action is None and render(d.status, "en").startswith("Invested")


async def test_sells_below_the_average_also_at_a_loss():
    s = STRATEGIES["trend"]
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110")))
    assert isinstance(d.action, Sell) and d.action.stop  # the engine sells it although it is a loss
    assert "result −" in render(d.action.reason, "en")
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89)))
    assert d.action is None and render(d.status, "en").startswith("In cash")


async def test_inside_the_buffer_nothing_changes():
    s = STRATEGIES["trend"]
    flat = months_back([100] * 9 + [101])  # 0.9 % above the average: inside ±2 %
    st = {"monthly": {"month": "2026-09", "trend_on": True}}
    d = await s.evaluate(ctx(MonthlyExchange(flat, 101), state=st))
    assert isinstance(d.action, Buy) and "buffer" in render(d.action.reason, "en")  # still an uptrend from last month
    st = {"monthly": {"month": "2026-09", "trend_on": False}}
    assert (await s.evaluate(ctx(MonthlyExchange(flat, 101), state=st))).action is None
    # a new bot waits for a clear uptrend
    assert (await s.evaluate(ctx(MonthlyExchange(flat, 101)))).action is None
    # without a buffer the same close is an uptrend
    assert isinstance((await s.evaluate(ctx(MonthlyExchange(flat, 101), sma_buffer=0))).action, Buy)


async def test_momentum_has_to_beat_the_cash_rate():
    s = STRATEGIES["trend"]
    p = dict(signal="momentum", momentum_months=12, cash_rate=2)
    weak = months_back([100] + [100] * 11 + [101.5])  # +1.5 % in 12 months < 2 %
    strong = months_back([100] + [100] * 11 + [102.5])
    d = await s.evaluate(ctx(MonthlyExchange(weak, 101), **p))
    assert d.action is None and "12-month return +1.50% vs. cash rate +2.00%" in render(d.status, "en")
    assert isinstance((await s.evaluate(ctx(MonthlyExchange(strong, 103), **p))).action, Buy)
    # 13 month-end closes are needed – 12 aren't enough
    d = await s.evaluate(ctx(MonthlyExchange(months_back([100] * 11 + [102.5]), 103), **p))
    assert d.action is None and "12 of 13 month-end closes" in render(d.status, "en")


async def test_unemployment_decides_whether_a_falling_trend_sells(monkeypatch):
    s = STRATEGIES["trend"]
    calls = []

    def feed(u):
        async def unemployment():
            calls.append(1)
            return u
        return unemployment

    monkeypatch.setattr(macro, "unemployment", feed(macro.Unemployment("2026-08", 4.0, 4.2)))
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), unemployment=True))
    assert d.action is None and "stays invested" in render(d.status, "en")

    monkeypatch.setattr(macro, "unemployment", feed(macro.Unemployment("2026-08", 4.4, 4.2)))
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), unemployment=True))
    assert isinstance(d.action, Sell) and "above its 12-month average" in render(d.action.reason, "en")
    assert "über ihrem 12-Monats-Schnitt" in render(d.action.reason, "de")

    monkeypatch.setattr(macro, "unemployment", feed(None))
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), unemployment=True))
    assert isinstance(d.action, Sell) and "trend alone decides" in render(d.action.reason, "en")

    # a rising trend never asks
    calls.clear()
    assert isinstance((await s.evaluate(ctx(MonthlyExchange(RISING, 113), unemployment=True))).action, Buy)
    assert not calls


async def test_decides_once_a_month_and_again_when_the_rules_change():
    s = STRATEGIES["trend"]
    state: dict = {}
    ex = MonthlyExchange(RISING, 113)
    assert isinstance((await s.evaluate(ctx(ex, state=state))).action, Buy)
    requests = ex.daily_requests
    # a crash during the month: the decision stands until the next month
    crash = MonthlyExchange(FALLING, 80)
    d = await s.evaluate(ctx(crash, bought_at("112"), state=state))
    assert d.action is None and crash.daily_requests == 0 and ex.daily_requests == requests
    # the next month decides anew
    crash.now = utc(2026, 11, 2, 9)
    crash.closes = {**FALLING, "2026-10": Decimal("80")}
    assert isinstance((await s.evaluate(ctx(crash, bought_at("112"), state=state))).action, Sell)
    # new rules decide right away, also within the month
    state = {}
    assert isinstance((await s.evaluate(ctx(MonthlyExchange(RISING, 113), state=state))).action, Buy)
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("112"), state=state))
    assert d.action is None  # same rules, same month
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("112"), state=state, sma_months=8))
    assert isinstance(d.action, Sell)


async def test_reinvests_the_proceeds_of_the_last_sale():
    s = STRATEGIES["trend"]
    state: dict = {}
    position = bought_at("100", "1000")  # 10 units
    ex = MonthlyExchange(FALLING, 120)  # sold at 120: 1,200 € minus the 1 € fee set below
    c = ctx(ex, position, state=state)
    c.fees = Fees(0.0, 1.0)
    assert isinstance((await s.evaluate(c)).action, Sell)
    assert state["monthly"]["capital"] == pytest.approx(1199.0)
    # the next month the trend is up again: the proceeds are invested, not the amount
    ex = MonthlyExchange(months_back([92, 94, 96, 98, 100, 102, 104, 106, 112, 114], "2026-10"), 114,
                         now=utc(2026, 11, 2, 9))
    d = await s.evaluate(ctx(ex, state=state))
    assert isinstance(d.action, Buy) and d.action.quote_amount == Decimal("1199.0")
    # without reinvesting: the amount
    state["monthly"]["sig"] = "changed"
    assert (await s.evaluate(ctx(ex, state=state, reinvest=False))).action.quote_amount == Decimal("1000")
    # a new amount starts afresh (rebalancing the bots)
    st2 = {"monthly": {**state["monthly"], "capital": 1199.0, "amount": 1000.0, "sig": "x"}}
    assert (await s.evaluate(ctx(ex, state=st2, amount=3000))).action.quote_amount == Decimal("3000")


async def test_waits_without_enough_history():
    s = STRATEGIES["trend"]
    state: dict = {}
    d = await s.evaluate(ctx(MonthlyExchange(months_back([100, 101, 102, 103, 104]), 105), state=state))
    assert d.action is None and "5 of 10 month-end closes" in render(d.status, "en")
    assert "Zu wenig Kursverlauf: 5 von 10" in render(d.status, "de")
    assert "month" not in state["monthly"]  # tries again on the next tick


# --- US unemployment from the BLS --------------------------------------------------------------


BLS_ANSWER = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {"series": [{"seriesID": "LNS14000000", "data": [
        {"year": "2026", "period": "M08", "value": "4.4"},
        {"year": "2026", "period": "M07", "value": "4.2"},
        {"year": "2026", "period": "M13", "value": "4.1"},  # annual average – not a month
        {"year": "2025", "period": "M10", "value": "-"},  # no figure (shutdown)
        *[{"year": "2026", "period": f"M{m:02d}", "value": "4.0"} for m in range(1, 7)],
        *[{"year": "2025", "period": f"M{m:02d}", "value": "4.1"} for m in (8, 9, 11, 12)],
    ]}]},
}


def test_bls_answer_is_parsed_and_summarized():
    values = macro.parse_bls(BLS_ANSWER)
    assert values["2026-08"] == 4.4 and "2025-10" not in values and len(values) == 12
    u = macro.summarize(values)
    # 12 months up to Aug 2026, the missing October skipped: 11 values
    assert u.month == "2026-08" and u.rising and u.average == pytest.approx((4.4 + 4.2 + 6 * 4.0 + 3 * 4.1) / 11)
    assert macro.summarize({"2026-08": 4.4, "2026-07": 4.2}) is None  # too few months
    with pytest.raises(ValueError):
        macro.parse_bls({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]})


async def test_unemployment_is_cached_and_survives_an_outage(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=BLS_ANSWER) if len(requests) == 1 else httpx.Response(503)

    real = httpx.AsyncClient
    monkeypatch.setattr(macro.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(macro, "_cache", (0.0, None))
    monkeypatch.setattr(macro, "_failed_at", 0.0)
    clock = [1_000_000.0]
    monkeypatch.setattr(macro.time, "time", lambda: clock[0])

    assert (await macro.unemployment()).rate == 4.4
    assert (await macro.unemployment()).rate == 4.4 and len(requests) == 1  # cached
    clock[0] += macro.CACHE_S + 1
    assert (await macro.unemployment()).rate == 4.4 and len(requests) == 2  # BLS down: the last figures stay
    assert (await macro.unemployment()).rate == 4.4 and len(requests) == 2  # no new request right after a failure
    clock[0] += macro.MAX_AGE_S
    assert await macro.unemployment() is None  # too old to use


# --- in the engine, on Trade Republic ----------------------------------------------------------


async def test_monthly_trend_follower_on_trade_republic(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    start = ms(2025, 1, 1, 0, 0)
    crash = ms(2026, 10, 10, 0, 0)
    # rising for almost two years, then a crash in October
    tr._price = lambda symbol, t: 100 + (t - start) / DAY * 0.1 if t < crash else 80.0
    bot_id = db.create_bot("World", "trend", EUNL, {"amount": 4000}, True, True, exchange=TRADEREPUBLIC)

    await engine.tick()  # Monday, 5 October: September closed far above the 10-month average
    position = open_positions(db.get_bot(bot_id)["state"])[0]
    assert abs(position.cost - Decimal("4000")) < 1  # the quantity is rounded down to the instrument's step

    tr.now_ms = lambda: ms(2026, 10, 20, 12, 0)  # the crash: the decision holds for October
    await engine.tick()
    assert open_positions(db.get_bot(bot_id)["state"])

    tr.now_ms = lambda: ms(2026, 11, 1, 12, 0)  # Sunday: the stock exchange is closed, nothing happens
    await engine.tick()
    assert open_positions(db.get_bot(bot_id)["state"])

    tr.now_ms = lambda: ms(2026, 11, 2, 9, 0)  # Monday: October closed below the average – sold at a loss
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert not open_positions(bot["state"])
    assert Decimal(db.list_trades(bot_id)[0]["pnl"]) < 0
    assert render(bot["status"], "en").startswith("Sold")

    tr.now_ms = lambda: ms(2026, 11, 9, 12, 0)  # stays in cash for the month
    await engine.tick()
    bot = db.get_bot(bot_id)
    assert not open_positions(bot["state"]) and render(bot["status"], "en").startswith("In cash")


# --- C7: combined signal, more recession signs, Euribor, currency-hedged share class, parking in bonds ----------

HEDGED = "IE00BF1B7389-EUR"
BONDS = "LU0290355717-EUR"
TREASURIES = "LU1407888137-EUR"


class Instruments(MonthlyExchange):
    """MonthlyExchange with month-end closes per instrument (the bot's own one is "ETH-EUR")."""

    def __init__(self, closes: dict[str, float], price: float, others: dict[str, dict[str, float]] | None = None,
                 now: int = NOW):
        super().__init__(closes, price, now)
        self.others = {s: {k: Decimal(str(v)) for k, v in c.items()} for s, c in (others or {}).items()}

    async def candles(self, symbol, interval, since, until):
        if symbol in self.others:
            own, self.closes = self.closes, self.others[symbol]
            try:
                return await super().candles(symbol, interval, since, until)
            finally:
                self.closes = own
        return await super().candles(symbol, interval, since, until)

    def instrument(self, symbol):
        return {"short": {HEDGED: "ACWE", BONDS: "XGLE", TREASURIES: "UST"}.get(symbol), "name": symbol}


def ctx_multi(ex, position=None, state=None, held_price=None, **params):
    c = ctx(ex, position, state, **params)

    async def view_of(symbol):
        price = Decimal(str(held_price or ex.price))
        return MarketView(ex, symbol, Ticker(price, price, price), ex.now)

    c.view_of = view_of
    if position is not None and position.symbol:
        price = Decimal(str(held_price or ex.price))
        c.held = MarketView(ex, position.symbol, Ticker(price, price, price), ex.now)
    return c


def test_instrument_symbols_accept_plain_isins():
    from app.strategies.trend import instrument_symbols
    assert instrument_symbols("lu0290355717, LU1407888137-EUR;IE00BF1B7389 X Y Z", "EUR") == [
        BONDS, TREASURIES, HEDGED]
    assert instrument_symbols("", "EUR") == []


async def test_either_signal_needs_both_trends_down_to_sell():
    s = STRATEGIES["trend"]
    p = dict(signal="either", momentum_months=12, cash_rate=2)
    # below the 10-month average, but +10 % in 12 months: still invested
    dip = months_back([90] + [100] * 7 + [104, 106, 104, 100, 99])
    d = await s.evaluate(ctx(MonthlyExchange(dip, 99), bought_at("90"), **p))
    assert d.action is None and "12-month return +10.00%" in render(d.status, "en")
    # both down: sells
    d = await s.evaluate(ctx(MonthlyExchange(FALLING | months_back([95] * 3, "2025-11"), 89), bought_at("110"), **p))
    assert isinstance(d.action, Sell)


async def test_the_euribor_sets_the_hurdle(monkeypatch):
    s = STRATEGIES["trend"]

    async def euro_cash(months):
        return macro.CashReturn(months, 0.03, "2026-09", 3.1)

    monkeypatch.setattr(macro, "euro_cash", euro_cash)
    p = dict(signal="momentum", momentum_months=12, cash_rate=2)
    plus_2_5 = months_back([100] + [100] * 11 + [102.5])  # beats 2 %, not the 3 % cash earned
    d = await s.evaluate(ctx(MonthlyExchange(plus_2_5, 103), **p))
    assert d.action is None and "vs. cash +3.00% (Euribor" in render(d.status, "en")
    assert isinstance((await s.evaluate(ctx(MonthlyExchange(plus_2_5, 103), cash_rate_auto=False, **p))).action, Buy)


async def test_any_switched_on_recession_sign_lets_a_falling_trend_sell(monkeypatch):
    s = STRATEGIES["trend"]

    async def calm_unemployment():
        return macro.Unemployment("2026-08", 4.0, 4.2)

    async def claims_up():
        return macro.Claims("2026-08", 230_000, 200_000)

    async def claims_down():
        return macro.Claims("2026-08", 190_000, 200_000)

    async def curve_inverted():
        return macro.Curve("2026-09", 0.4, "2025-07")

    monkeypatch.setattr(macro, "unemployment", calm_unemployment)
    monkeypatch.setattr(macro, "claims", claims_down)
    p = dict(unemployment=True, claims=True)
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), **p))
    assert d.action is None and "no recession sign" in render(d.status, "en") and "−5.00% vs. a year earlier" in render(d.status, "en")

    monkeypatch.setattr(macro, "claims", claims_up)
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), **p))
    assert isinstance(d.action, Sell) and "recession sign: US jobless claims +15.00%" in render(d.action.reason, "en")
    assert "Rezessionszeichen: US-Erstanträge +15,00 %" in render(d.action.reason, "de")

    monkeypatch.setattr(macro, "claims", claims_down)
    monkeypatch.setattr(macro, "yield_curve", curve_inverted)
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), yield_curve=True, **p))
    assert isinstance(d.action, Sell) and "US yield curve inverted in Jul 2025" in render(d.action.reason, "en")

    # nothing switched on is available: the trend alone decides (claims and curve are "unavailable" in tests)
    monkeypatch.setattr(macro, "claims", macro.claims.__class__ and (lambda: _none()))
    d = await s.evaluate(ctx(MonthlyExchange(FALLING, 89), bought_at("110"), claims=True))
    assert isinstance(d.action, Sell) and "the trend alone decides" in render(d.action.reason, "en")


async def _none():
    return None


async def test_holds_the_currency_hedged_share_class_while_the_euro_rises(monkeypatch):
    s = STRATEGIES["trend"]

    async def euro_up():
        return macro.EuroTrend("2026-09", 1.20, 1.15)

    async def euro_down():
        return macro.EuroTrend("2026-09", 1.10, 1.15)

    monkeypatch.setattr(macro, "eurusd", euro_up)
    state: dict = {}
    ex = Instruments(RISING, 113)
    d = await s.evaluate(ctx_multi(ex, state=state, hedged_symbol="IE00BF1B7389"))
    assert isinstance(d.action, Buy) and d.action.symbol == HEDGED
    assert render(d.status, "en") == "Trend up – buying the currency-hedged ACWE"
    assert "dollar falling: euro 1.2000 $ above its 12-month average 1.1500 $" in render(d.action.reason, "en")
    held = bought_at("50")
    held.symbol = HEDGED
    d = await s.evaluate(ctx_multi(ex, held, state=state, held_price=55, hedged_symbol="IE00BF1B7389"))
    assert d.action is None and render(d.status, "en").startswith("Invested in ACWE +10.00%")

    # next month the euro falls: switch back to the bot's own instrument
    monkeypatch.setattr(macro, "eurusd", euro_down)
    ex.now = utc(2026, 11, 2, 9)
    ex.closes = {**RISING, "2026-10": Decimal("114")}
    d = await s.evaluate(ctx_multi(ex, held, state=state, held_price=55, hedged_symbol="IE00BF1B7389"))
    assert isinstance(d.action, Sell) and d.action.stop and render(d.status, "en") == "Switching to ETH-EUR"
    assert state["monthly"]["capital"] == pytest.approx(1100 * (1 - 0.0009))  # minus the default sell fee
    d = await s.evaluate(ctx_multi(ex, state=state, hedged_symbol="IE00BF1B7389"))
    assert isinstance(d.action, Buy) and d.action.symbol is None and d.action.quote_amount == pytest.approx(Decimal("1099.01"))

    # without EUR/USD data the share class stays as it is
    monkeypatch.setattr(macro, "eurusd", _none)
    state["monthly"].update(sig="changed", target=HEDGED)
    d = await s.evaluate(ctx_multi(ex, held, state=state, held_price=55, hedged_symbol="IE00BF1B7389"))
    assert d.action is None and "EUR/USD not available" in render(d.status, "en")


async def test_parks_in_the_best_bonds_while_the_trend_is_down():
    s = STRATEGIES["trend"]
    up_4 = months_back([100] * 12 + [104])  # +4 % in 12 months
    up_3 = months_back([100] * 12 + [103])
    down = months_back([100] * 12 + [97])
    p = dict(fallback_symbols=f"{BONDS}, {TREASURIES}")
    state: dict = {}
    ex = Instruments(FALLING, 89, {BONDS: up_3, TREASURIES: up_4})
    d = await s.evaluate(ctx_multi(ex, state=state, **p))
    assert isinstance(d.action, Buy) and d.action.symbol == TREASURIES
    assert render(d.status, "en") == "Trend down – parking in UST"
    assert "12-month returns XGLE +3.00%; UST +4.00% vs. cash +2.00%" in render(d.action.reason, "en")
    parked = bought_at("10")
    parked.symbol = TREASURIES
    d = await s.evaluate(ctx_multi(ex, parked, state=state, held_price=10, **p))
    assert d.action is None and render(d.status, "en").startswith("Parked in UST")

    # nothing beats cash: cash
    d = await s.evaluate(ctx_multi(Instruments(FALLING, 89, {BONDS: down, TREASURIES: down}), **p))
    assert d.action is None and "don't beat cash" in render(d.status, "en")
    # an instrument without data is skipped
    d = await s.evaluate(ctx_multi(Instruments(FALLING, 89, {TREASURIES: up_4}), **p))
    assert d.action.symbol == TREASURIES and "XGLE without data" in render(d.action.reason, "en")

    # the trend turns up: the parked bonds are sold, then the bot's own instrument is bought
    ex = Instruments(months_back([90, 92, 94, 96, 98, 100, 102, 104, 106, 112], "2026-10"), 113,
                     {BONDS: up_3, TREASURIES: up_4}, now=utc(2026, 11, 2, 9))
    d = await s.evaluate(ctx_multi(ex, parked, state=state, held_price=10.5, **p))
    assert isinstance(d.action, Sell) and render(d.status, "en") == "Switching to ETH-EUR"
    d = await s.evaluate(ctx_multi(ex, state=state, **p))
    assert isinstance(d.action, Buy) and d.action.symbol is None


# --- the data sources --------------------------------------------------------------------------------------------

ECB_CSV = """KEY,FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE
FM.M,M,U2,2026-07,2.4253913
FM.M,M,U2,2026-08,2.5131429
FM.M,M,U2,2026-09,2.6350455
"""


def test_ecb_rates_give_the_cash_return_and_the_euro_trend():
    rates = macro.parse_ecb_csv(ECB_CSV)
    assert rates == {"2026-07": 2.4253913, "2026-08": 2.5131429, "2026-09": 2.6350455}
    c = macro.cash_return(rates, 3)
    assert c.latest_month == "2026-09" and c.total == pytest.approx(
        (1 + 0.024253913 / 12) * (1 + 0.025131429 / 12) * (1 + 0.026350455 / 12) - 1)
    assert macro.cash_return(rates, 4) is None  # a month missing
    fx = {f"2025-{m:02d}": 1.10 for m in range(10, 13)} | {f"2026-{m:02d}": 1.10 for m in range(1, 9)} | {"2026-09": 1.22}
    e = macro.euro_trend(fx)
    assert e.month == "2026-09" and e.euro_rising and e.average == pytest.approx((11 * 1.10 + 1.22) / 12)
    assert macro.euro_trend({"2026-09": 1.2}) is None


DOL_XML = "<r539cyNational>" + "".join(
    f"<week><weekEnded>{d}</weekEnded><InitialClaims><NSA>{v}</NSA><SA>1</SA></InitialClaims>"
    f"<ContinuedClaims><NSA>9,999,999</NSA></ContinuedClaims></week>"
    for d, v in [("08/02/2025", "200,000"), ("08/09/2025", "200,000"), ("08/16/2025", "200,000"),
                 ("08/23/2025", "200,000"), ("08/30/2025", "200,000"),
                 ("08/01/2026", "230,000"), ("08/08/2026", "230,000"), ("08/15/2026", "230,000"),
                 ("08/22/2026", "230,000"), ("08/29/2026", "230,000"), ("09/05/2026", "300,000")]) + "</r539cyNational>"


def test_jobless_claims_compare_complete_months_with_a_year_earlier():
    weekly = macro.parse_dol_xml(DOL_XML)
    assert weekly["2026-08-29"] == 230_000 and len(weekly) == 11
    assert set(macro.monthly_claims(weekly)) == {"2025-08", "2026-08"}  # September 2026 isn't complete
    c = macro.claims_summary(weekly)
    assert c.month == "2026-08" and c.change == pytest.approx(0.15) and c.rising
    with pytest.raises(ValueError):
        macro.parse_dol_xml("<html>maintenance</html>")


def test_yield_curve_warns_for_two_years_after_an_inversion():
    daily = {}
    for k in range(30):  # month ends Apr 2024 .. Sep 2026, the 10-year yield above the 3-month one ...
        y, mo = divmod(2024 * 12 + 3 + k, 12)
        daily[f"{y:04d}-{mo + 1:02d}-28"] = (4.0, 4.5)
    daily["2025-07-28"] = (4.5, 4.2)  # ... except July 2025
    daily["2026-10-02"] = (5.0, 4.0)  # the running month doesn't count
    now = utc(2026, 10, 5) / 1000
    c = macro.curve_summary(daily, now)
    assert c.month == "2026-09" and c.spread == pytest.approx(0.5) and c.last_inverted == "2025-07" and c.warning
    del daily["2025-07-28"]
    daily["2025-07-28"] = (4.0, 4.5)
    assert not macro.curve_summary(daily, now).warning
    csv_text = 'Date,"1 Mo","3 Mo","10 Yr"\n10/02/2026,4.04,4.19,5.28\n'
    assert macro.parse_treasury_csv(csv_text) == {"2026-10-02": (4.19, 5.28)}


async def test_feeds_are_cached_daily_and_survive_an_outage(monkeypatch):
    calls = []

    async def load(client):
        calls.append(1)
        if len(calls) > 1:
            raise httpx.ConnectError("down")
        return {"2026-09": 2.6}

    feed = macro.Feed("test", load)
    clock = [1_000_000.0]
    monkeypatch.setattr(macro.time, "time", lambda: clock[0])
    assert await feed.get() == {"2026-09": 2.6}
    assert await feed.get() == {"2026-09": 2.6} and len(calls) == 1
    clock[0] += macro.CACHE_S + 1
    assert await feed.get() == {"2026-09": 2.6} and len(calls) == 2  # down: the last answer stays
    assert await feed.get() == {"2026-09": 2.6} and len(calls) == 2  # no new request right after a failure
    clock[0] += macro.MAX_AGE_S
    assert await feed.get() is None


VWCE = "IE00BK5BQT80-EUR"  # stands in for the currency-hedged share class
SXR8 = "IE00B5BMR087-EUR"  # stands in for the bonds to park in


async def test_switches_share_class_and_parks_live_on_trade_republic(tmp_path: Path, monkeypatch):
    db, engine, tr = two_brokers(tmp_path)
    db.set_setting("live_trading.traderepublic", True)
    start = ms(2025, 1, 1, 0, 0)
    crash = ms(2026, 11, 10, 0, 0)

    def price(symbol, t):
        if symbol == SXR8:
            return 50 + (t - start) / DAY * 0.02  # steadily rising
        if symbol == VWCE:
            return 60.0
        return 100 + (t - start) / DAY * 0.1 if t < crash else 70.0

    tr._price = price
    euro = [macro.EuroTrend("2026-09", 1.20, 1.15)]

    async def eurusd():
        return euro[0]

    async def claims_up():
        return macro.Claims("2026-10", 230_000, 200_000)

    monkeypatch.setattr(macro, "eurusd", eurusd)
    monkeypatch.setattr(macro, "claims", claims_up)
    params = {"amount": 4000, "signal": "either", "claims": True, "hedged_symbol": "IE00BK5BQT80",
              "fallback_symbols": "IE00B5BMR087"}
    bot_id = db.create_bot("World", "trend", EUNL, params, True, False, exchange=TRADEREPUBLIC)

    def held():
        return [(p.symbol or EUNL, p.paper) for p in open_positions(db.get_bot(bot_id)["state"])]

    await engine.tick()  # Monday 5 October: trend up, the euro rising – the hedged share class is bought, live
    assert held() == [(VWCE, False)]
    assert (await tr.balances())["IE00BK5BQT80"][1] > 0
    await engine._verify_holdings(TRADEREPUBLIC, db.list_bots(), force=True)
    assert not db.get_bot(bot_id)["state"].get("holdings_mismatch")
    card = engine.describe_bot(db.get_bot(bot_id), db.trade_stats())
    assert card["symbol"] == EUNL and card["positions"][0]["symbol"] == VWCE and card["positions"][0]["base_currency"] == "VWCE"
    assert abs(card["positions"][0]["value"] - 4000) < 10

    euro[0] = macro.EuroTrend("2026-10", 1.10, 1.15)
    tr.now_ms = lambda: ms(2026, 11, 2, 9, 0)  # the euro fell: back to the bot's own instrument
    await engine.tick()
    assert held() == []
    await engine.tick()
    assert held() == [(EUNL, False)]

    tr.now_ms = lambda: ms(2026, 12, 1, 9, 0)  # November crashed, jobless claims rise: sold, parked in "bonds"
    await engine.tick()
    assert held() == []
    await engine.tick()
    assert held() == [(SXR8, False)]
    trades = [(t["side"], t["symbol"]) for t in reversed(db.list_trades(bot_id))]
    assert trades == [("buy", VWCE), ("sell", VWCE), ("buy", EUNL), ("sell", EUNL), ("buy", SXR8)]
    await engine._verify_holdings(TRADEREPUBLIC, db.list_bots(), force=True)
    assert not db.get_bot(bot_id)["state"].get("holdings_mismatch")
    assert render(db.get_bot(bot_id)["status"], "en").startswith("Bought")

    tr.now_ms = lambda: ms(2026, 12, 2, 12, 0)
    await engine.tick()
    assert render(db.get_bot(bot_id)["status"], "en").startswith("Parked in SXR8")
    await engine.close_position(bot_id)  # a manual sale sells what the trade holds
    assert held() == [] and db.list_trades(bot_id)[0]["symbol"] == SXR8
