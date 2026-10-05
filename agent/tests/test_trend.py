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
