"""Trade Republic: protocol, login, trading hours and the engine with a second broker."""

import asyncio
import base64
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from websockets.asyncio.server import serve

from app.config import Settings
from app.db import Database
from app.engine import Engine
from app.exchange import REVOLUTX, TRADEREPUBLIC, MockExchange
from app.i18n import Problem, render
from app.strategies import open_positions
from app.traderepublic import (
    MockTradeRepublicExchange, TradeRepublicExchange, TradeRepublicSession, TRSocket, apply_delta, market_closed_at,
    normalize_phone,
)
from app.strategies.base import fetch_daily_candles
from tests.test_core import FakeExchange

BERLIN = ZoneInfo("Europe/Berlin")
SAP = "DE0007164600-EUR"
BTC = "XF000BTC0017-EUR"


def ms(*args) -> int:
    return int(datetime(*args, tzinfo=BERLIN).timestamp() * 1000)


def jwt(exp: float) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': int(exp)})}.sig"


# --- protocol -----------------------------------------------------------------------------


def test_delta_answers_are_applied():
    previous = '{"bid":{"price":"185.62"},"ask":{"price":"185.70"}}'
    start = previous.index("185.62")
    # keep everything up to the bid, drop its 6 characters, insert the new bid, keep the rest
    delta = f"={start}\t-6\t+185.80\t={len(previous) - start - 6}"
    assert apply_delta(previous, delta) == '{"bid":{"price":"185.80"},"ask":{"price":"185.70"}}'
    assert apply_delta("abc", "=1\t+X%20Y\t-1\t=1") == "aX Yc"


def test_phone_numbers_are_normalized():
    assert normalize_phone("0171 1234567") == "+491711234567"
    assert normalize_phone("+49 (171) 123-4567") == "+491711234567"
    assert normalize_phone("0043 660 1234567") == "+436601234567"
    with pytest.raises(Problem):
        normalize_phone("12")


# --- trading hours ------------------------------------------------------------------------

STOCK = {"open_ms": 27_000_000, "close_ms": 82_800_000, "tz": "Europe/Berlin", "weekdays": True}
CRYPTO = {"open_ms": 0, "close_ms": 86_399_000, "tz": "Europe/Berlin", "weekdays": False}


def test_stocks_trade_on_weekdays_from_7_30_to_23():
    assert market_closed_at(STOCK, ms(2026, 10, 5, 10, 0)) is None  # Monday
    closed = market_closed_at(STOCK, ms(2026, 10, 5, 7, 0))
    assert render(closed, "en") == "Market closed · opens Mon 07:30"
    friday_night = market_closed_at(STOCK, ms(2026, 10, 9, 23, 30))
    assert render(friday_night, "de") == "Börse geschlossen · öffnet Mo 07:30"
    assert render(market_closed_at(STOCK, ms(2026, 10, 10, 12, 0)), "en") == "Market closed · opens Mon 07:30"


def test_crypto_trades_around_the_clock():
    assert market_closed_at(CRYPTO, ms(2026, 10, 10, 3, 0)) is None


def test_stale_quotes_during_trading_hours_mean_a_closed_venue():
    now = ms(2026, 12, 24, 15, 0)
    assert market_closed_at(STOCK, now, now - 60_000) is None
    closed = market_closed_at(STOCK, now, ms(2026, 12, 23, 22, 59))
    assert "No current quotes since Wed 22:59" in render(closed, "en")


# --- a fake Trade Republic WebSocket ------------------------------------------------------


class FakeTR:
    """Answers like Trade Republic's WebSocket: market data for everybody, the account only with cookies."""

    def __init__(self):
        self.orders: list[dict] = []
        self.terminated: list[dict] = []
        self.sent_orders: list[dict] = []
        self.cookies_seen: list[str] = []
        self.refuse_next_order: str | None = None
        self.history_requests: list[dict] = []
        self.server = None
        self.port = 0

    async def __aenter__(self):
        self.server = await serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    async def handler(self, ws):
        cookie = ws.request.headers.get("Cookie", "")
        self.cookies_seen.append(cookie)
        hello = await ws.recv()
        assert hello.startswith("connect 31 ")
        await ws.send("connected")
        async for frame in ws:
            if frame.startswith("echo"):
                await ws.send(frame)
                continue
            if frame.startswith("unsub"):
                continue
            _, sid, payload = frame.split(" ", 2)
            await self.answer(ws, sid, json.loads(payload), cookie)

    async def answer(self, ws, sid: str, p: dict, cookie: str):
        kind = p["type"]
        account = {"availableCash", "cash", "compactPortfolioByType", "orders", "simpleCreateOrder", "timelineTransactions"}
        if kind in account and "tr_session=" not in cookie:
            await ws.send(f'{sid} E {{"errors":[{{"errorCode":"AUTHENTICATION_ERROR","errorMessage":"No auth token"}}]}}')
            return
        if kind == "instrument":
            await ws.send(f"{sid} A " + json.dumps({
                "isin": p["id"], "typeId": "stock", "shortName": "SAP", "name": "SAP SE", "homeSymbol": "SAP",
                "exchangeIds": ["LSX"], "fractionalTradingAllowed": True, "tradable": True,
                "exchanges": [{"slug": "LSX", "fractionalTrading": {"minOrderSize": "0.000001", "stepSize": "0.000001",
                                                                    "minOrderAmount": "1"}}],
            }))
            await ws.send(f"{sid} C")
        elif kind == "homeInstrumentExchange":
            await ws.send(f"{sid} A " + json.dumps({
                "exchangeId": "LSX", "exchange": {"timeZoneId": "Europe/Berlin"}, "open": True,
                "orderModes": ["limit", "market"], "openTimeOffsetMillis": 27_000_000, "closeTimeOffsetMillis": 82_800_000,
            }))
            await ws.send(f"{sid} C")
        elif kind == "ticker":
            now = int(time.time() * 1000)
            first = json.dumps({"bid": {"price": "100.00", "time": now}, "ask": {"price": "100.10", "time": now},
                                "last": {"price": "100.05", "time": now}})
            await ws.send(f"{sid} A {first}")
            second = first.replace('"100.00"', '"101.00"')
            # a delta: everything up to the bid price, the new price, the rest
            start = first.index("100.00")
            await ws.send(f"{sid} D =" + str(start) + "\t-6\t+101.00\t=" + str(len(first) - start - 6))
            assert apply_delta(first, f"={start}\t-6\t+101.00\t={len(first) - start - 6}") == second
        elif kind == "aggregateHistoryLight":
            self.history_requests.append(p)
            now = int(time.time() * 1000)
            if p.get("resolution") == 86_400_000:  # daily: stamped at UTC midnight of the trading day, weekdays only
                days = 1830 if p["range"] == "max" else 365
                today = now - now % 86_400_000
                aggregates = [{"time": t, "open": "100", "high": "101", "low": "99", "close": "100.5"}
                              for t in range(today - days * 86_400_000, today + 1, 86_400_000)
                              if time.gmtime(t / 1000).tm_wday < 5]
            else:
                assert p.get("resolution") in (600_000, 3_600_000)
                start = now - now % 600_000 - 30 * 600_000
                aggregates = [{"time": start + i * 600_000, "open": str(100 + i), "high": str(101 + i),
                               "low": str(99 + i), "close": str(100.5 + i)} for i in range(30)]
            await ws.send(f"{sid} A " + json.dumps({"aggregates": aggregates, "resolution": p["resolution"]}))
        elif kind == "neonSearch":
            await ws.send(f"{sid} A " + json.dumps({"results": [
                {"isin": "US0378331005", "name": "Apple", "instrumentType": "stock"},
                {"isin": "not an isin", "name": "?"},
            ]}))
            await ws.send(f"{sid} C")
        elif kind == "availableCash":
            await ws.send(f'{sid} A [{{"accountNumber":"1","currencyId":"EUR","amount":900.5}}]')
        elif kind == "cash":
            await ws.send(f'{sid} A [{{"accountNumber":"1","currencyId":"EUR","amount":1000}}]')
        elif kind == "compactPortfolioByType":
            assert p["secAccNo"] == "SEC1"
            await ws.send(f"{sid} A " + json.dumps({"categories": [{"categoryType": "stocks", "positions": [
                {"isin": "DE0007164600", "netSize": "0.5", "averageBuyIn": "180"}]}]}))
        elif kind == "simpleCreateOrder":
            self.sent_orders.append(p)
            await ws.send(f'{sid} A {{"status":"received"}}')
            if self.refuse_next_order:
                code, self.refuse_next_order = self.refuse_next_order, None
                await ws.send(f"{sid} A " + json.dumps({"status": "failed", "message": "refused", "error": {"code": code}}))
                return
            order_id = f"o-{len(self.sent_orders)}"
            params = p["parameters"]
            self.terminated.append({
                "id": order_id, "createdTime": int(time.time() * 1000), "instrumentId": params["instrumentId"],
                "type": params["type"], "mode": "market", "size": params["size"], "status": "executed",
                "executions": [{"size": params["size"], "price": 101.0}],
            })
            await ws.send(f"{sid} A " + json.dumps({"status": "succeeded", "orderId": order_id}))
        elif kind == "orders":
            orders = self.terminated if p.get("terminated") else self.orders
            await ws.send(f"{sid} A " + json.dumps({"orders": orders, "unsupportedOrderCount": 0}))
        else:
            await ws.send(f'{sid} E {{"errors":[{{"errorCode":"BAD_SUBSCRIPTION_TYPE"}}]}}')


def logged_in_session(tmp_path: Path) -> TradeRepublicSession:
    session = TradeRepublicSession(tmp_path)
    session.cookies = {"tr_session": "s1", "tr_refresh": jwt(time.time() + 3600)}
    session.refresh_expires_at = int(time.time() + 3600)
    session.refreshed_at = time.monotonic()
    session.account = {"securitiesAccountNumber": "SEC1"}
    return session


async def test_market_data_and_orders_over_the_websocket(tmp_path: Path):
    async with FakeTR() as tr:
        db = Database(tmp_path / "t.db")
        session = logged_in_session(tmp_path)
        ex = TradeRepublicExchange(session, db, TRSocket(url=tr.url), TRSocket(cookies=session.cookie_header, url=tr.url))
        try:
            meta = await ex.resolve(SAP)
            assert meta["venue"] == "LSX" and meta["short"] == "SAP" and meta["step"] == "0.000001"
            assert db.instruments(TRADEREPUBLIC)[SAP]["name"] == "SAP"  # remembered for the next start
            assert ex.instrument(SAP) == {"name": "SAP", "short": "SAP", "type": "stock", "isin": "DE0007164600"}

            ticker = await ex.ticker(SAP)
            assert ticker.ask == Decimal("100.10")
            await asyncio.sleep(0.05)  # the delta follows
            assert (await ex.ticker(SAP)).bid == Decimal("101.00")

            now = int(time.time() * 1000)
            candles = await ex.candles(SAP, 30, now - 3 * 3_600_000, now)
            assert candles and all(c.start % 1_800_000 == 0 for c in candles)
            # long daily series: daily resolution (hourly candles only go back three months), "max" beyond a year,
            # and one request for the whole window
            assert tr.history_requests[-1]["range"] == "5d"
            daily = await fetch_daily_candles(ex.candles, SAP, 434, now, ex.max_candles)
            assert tr.history_requests[-1] == {"type": "aggregateHistoryLight", "range": "max",
                                               "id": "DE0007164600.LSX", "resolution": 86_400_000}
            assert len(daily) > 300 and all(c.start % 86_400_000 == 0 for c in daily)
            assert daily[-1].start < now - now % 86_400_000  # not today's forming candle
            requests = len(tr.history_requests)
            await fetch_daily_candles(ex.candles, SAP, 200, now, ex.max_candles)
            assert len(tr.history_requests) == requests + 1 and tr.history_requests[-1]["range"] == "1y"

            assert [r["symbol"] for r in await ex.search("apple")] == ["US0378331005-EUR"]

            # market data needs no login, the account does – with the session cookies on the handshake
            balances = await ex.balances()
            assert balances["EUR"] == (Decimal("900.5"), Decimal("1000"))
            assert balances["DE0007164600"] == (Decimal("0.5"), Decimal("0.5"))
            assert any("tr_session=s1" in c for c in tr.cookies_seen)

            order_id = await ex.place_market_order(SAP, "buy", client_order_id="c1", quote_size=Decimal("51"))
            params = tr.sent_orders[-1]["parameters"]
            assert params["mode"] == "market" and params["exchangeId"] == "LSX" and params["expiry"] == {"type": "gfd"}
            # 51 € minus the 1 € fee at the ask (with a small buffer), in steps of 0.000001
            assert 0.49 < params["size"] < 50 / 100.10 and tr.sent_orders[-1]["clientProcessId"] == "c1"
            result = await ex.get_order(order_id)
            assert result.status == "filled" and result.fee == Decimal("1") and result.avg_price == Decimal("101.0")
            assert (await ex.find_order(SAP, "c1", now - 60_000)).order_id == order_id

            tr.refuse_next_order = "cashMissing"
            with pytest.raises(Exception) as refused:
                await ex.place_market_order(SAP, "buy", client_order_id="c2", quote_size=Decimal("51"))
            from app.engine import definitely_not_placed
            assert definitely_not_placed(refused.value)  # a refused order is never looked up or sent again
        finally:
            await ex.close()


async def test_account_needs_a_login(tmp_path: Path):
    async with FakeTR() as tr:
        session = TradeRepublicSession(tmp_path)
        ex = TradeRepublicExchange(session, None, TRSocket(url=tr.url), TRSocket(cookies=session.cookie_header, url=tr.url))
        try:
            assert (await ex.ticker(SAP)).last  # prices work without a login
            with pytest.raises(Problem) as missing:
                await ex.balances()
            assert missing.value.msg["k"] == "tr.login_required"
        finally:
            await ex.close()


# --- login ----------------------------------------------------------------------------------


class FakeLogin:
    """Trade Republic's v2 web login: the process stays pending until the app confirms it."""

    def __init__(self):
        self.polls = 0
        self.confirm_after = 2
        self.requests: list[httpx.Request] = []
        self.refresh_ok = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v2/auth/web/login":
            body = json.loads(request.content)
            assert request.headers["X-Tr-Platform"] == "web-pro" and request.headers["X-TR-Device-Info"]
            if body["pin"] != "1234":
                return httpx.Response(401, json={"errors": [{"errorCode": "AUTHENTICATION_ERROR"}]})
            return httpx.Response(200, json={"processId": "p1", "countdownInSeconds": 120},
                                  headers={"set-cookie": "JSESSIONID=j; Domain=.traderepublic.com; Path=/"})
        if path == "/api/v2/auth/web/login/processes/p1":
            self.polls += 1
            if self.polls < self.confirm_after:
                return httpx.Response(200, json={"status": "PENDING"})
            headers = [("set-cookie", f"tr_session=s2; Domain=.traderepublic.com; Path=/"),
                       ("set-cookie", f"tr_refresh={jwt(time.time() + 86400)}; Domain=.traderepublic.com; Path=/")]
            return httpx.Response(200, json={"status": "CONFIRMED"}, headers=headers)
        if path == "/api/v2/auth/account":
            return httpx.Response(200, json={"securitiesAccountNumber": "SEC1", "jurisdiction": "DE"})
        if path == "/api/v1/auth/web/session":
            if not self.refresh_ok:
                return httpx.Response(401)
            return httpx.Response(200, headers={"set-cookie": "tr_session=s3; Domain=.traderepublic.com; Path=/"})
        return httpx.Response(404)


async def test_login_waits_for_the_confirmation_in_the_app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.traderepublic.asyncio.sleep", _fast_sleep)
    fake = FakeLogin()
    session = TradeRepublicSession(tmp_path, transport=httpx.MockTransport(fake))
    with pytest.raises(Problem) as wrong:
        await session.start_login("0171 1234567", "9999")
    assert wrong.value.msg["k"] == "tr.wrong_credentials"

    await session.start_login("0171 1234567", "1234", remember_pin=True)
    assert session.state == "waiting" and session.describe()["phone_masked"] == "+49…567"
    await session.process.task
    assert session.state == "logged_in" and session.account["securitiesAccountNumber"] == "SEC1"
    assert session.cookies["tr_session"] == "s2" and session.refresh_expires_at > time.time() + 80000
    assert (tmp_path / "tr_session.json").stat().st_mode & 0o777 == 0o600

    # the session survives a restart of the agent
    again = TradeRepublicSession(tmp_path, transport=httpx.MockTransport(fake))
    assert again.logged_in and again.pin == "1234"
    again.refreshed_at = float("-inf")
    await again.ensure_fresh()
    assert again.cookies["tr_session"] == "s3"

    # the 24 h refresh token is gone: logged out, phone and PIN are kept for the next login
    fake.refresh_ok = False
    again.refreshed_at = float("-inf")
    with pytest.raises(Problem):
        await again.ensure_fresh()
    assert again.state == "logged_out" and again.phone and render(again.error, "en").startswith("The Trade Republic session has expired")
    await session.close()
    await again.close()


async def test_daily_login_starts_itself_only_while_the_account_is_needed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.traderepublic.asyncio.sleep", _fast_sleep)
    needed = False
    session = TradeRepublicSession(tmp_path, transport=httpx.MockTransport(FakeLogin()), needs_account=lambda: needed)
    session.phone, session.pin = "+491711234567", "1234"
    await session.maintain_once()
    assert session.process is None  # nobody trades live – no push to the phone
    needed = True
    await session.maintain_once()
    assert session.process is not None and session.process.automatic
    await session.process.task
    assert session.logged_in
    # not again while the session is young
    await session.maintain_once()
    assert session.process is None
    await session.close()


_real_sleep = asyncio.sleep


async def _fast_sleep(_seconds: float) -> None:
    await _real_sleep(0)


# --- the engine with two brokers ------------------------------------------------------------


def two_brokers(tmp_path: Path) -> tuple[Database, Engine, MockTradeRepublicExchange]:
    settings = Settings(tmp_path, "t", "mock", "", tmp_path / "x", "", 30, Decimal("0.0009"), 1)
    db = Database(settings.db_path)
    tr = MockTradeRepublicExchange()
    tr.now_ms = lambda: ms(2026, 10, 5, 12, 0)  # Monday noon: the stock exchange trades
    revx = FakeExchange("2000", "1970")
    return db, Engine(db, {REVOLUTX: revx, TRADEREPUBLIC: tr}, settings), tr


async def test_paper_trading_on_trade_republic_charges_one_euro_per_order(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    tr._price = lambda symbol, t: 100.0
    bot_id = db.create_bot("SAP", "zones", SAP, {"amount": 51, "buy_below": 1000, "sell_above": 100.5}, True, True,
                           exchange=TRADEREPUBLIC)
    await engine.tick()
    trade = db.list_trades(bot_id)[0]
    # 51 € = 1 € fee + 50 € of shares at the ask
    assert Decimal(trade["fee"]) == 1 and trade["exchange"] == TRADEREPUBLIC
    assert Decimal(trade["quote_amount"]) == pytest.approx(Decimal("51"), abs=Decimal("0.01"))
    position = open_positions(db.get_bot(bot_id)["state"])[0]
    assert position.qty == pytest.approx(Decimal("50") / Decimal("100.02"), abs=Decimal("0.000002"))
    # the sell rule waits until the 1 € fees on both sides are covered – 100.5 is not enough
    tr._price = lambda symbol, t: 101.0
    await engine.tick()
    assert open_positions(db.get_bot(bot_id)["state"])
    tr._price = lambda symbol, t: 105.0
    await engine.tick()
    assert not open_positions(db.get_bot(bot_id)["state"])
    sell = db.list_trades(bot_id)[0]
    assert sell["side"] == "sell" and Decimal(sell["fee"]) == 1 and Decimal(sell["pnl"]) > 0


async def test_no_orders_while_the_stock_exchange_is_closed(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    tr.now_ms = lambda: ms(2026, 10, 10, 12, 0)  # Saturday
    bot_id = db.create_bot("SAP", "zones", SAP, {"amount": 51, "buy_below": 1000}, True, True, exchange=TRADEREPUBLIC)
    crypto = db.create_bot("BTC", "zones", BTC, {"amount": 51, "buy_below": 10**9}, True, True, exchange=TRADEREPUBLIC)
    await engine.tick()
    assert not db.list_trades(bot_id)
    assert render(db.get_bot(bot_id)["status"], "en") == "Market closed · opens Mon 07:30"
    assert db.list_trades(crypto)  # crypto trades on weekends
    tr.now_ms = lambda: ms(2026, 10, 12, 9, 0)  # Monday: the stock is bought …
    await engine.tick()
    assert db.list_trades(bot_id)
    tr.now_ms = lambda: ms(2026, 10, 12, 23, 30)  # … and can't be sold by hand at night
    with pytest.raises(Problem) as closed:
        await engine.close_position(bot_id)
    assert closed.value.msg["k"] == "err.market_closed"
    stats = db.trade_stats()
    described = engine.describe_bot(db.get_bot(bot_id), stats, "de")
    assert described["market"]["closed"].startswith("Börse geschlossen")
    assert described["display_symbol"] == "SAP" and described["base_currency"] == "SAP"


async def test_brokers_keep_their_own_mode_limits_and_results(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    db.set_setting("live_trading", True)  # Revolut X live, Trade Republic still on paper
    db.set_limits({"max_open_positions": 1}, TRADEREPUBLIC)
    revx_bot = db.create_bot("ETH", "dip", "ETH-EUR", {}, True, False)
    a = db.create_bot("A", "zones", BTC, {"amount": 20, "buy_below": 10**9}, True, False, exchange=TRADEREPUBLIC)
    b = db.create_bot("B", "zones", "XF000ETH0019-EUR", {"amount": 20, "buy_below": 10**9}, True, False,
                      exchange=TRADEREPUBLIC)
    await engine.tick()
    assert not db.list_trades(revx_bot)[0]["paper"]  # live on Revolut X
    assert db.list_trades(a)[0]["paper"]  # the bot asked for live, but Trade Republic is in paper mode
    assert not db.list_trades(b)  # Trade Republic's own limit: one position
    revx, trs = engine.summary(REVOLUTX), engine.summary(TRADEREPUBLIC)
    assert revx["mode"] == "live" and trs["mode"] == "paper"
    assert revx["bots_total"] == 1 and trs["bots_total"] == 2 and trs["open_positions"] == 1
    assert trs["trades_count"] == 1 and revx["trades_count"] == 1


def test_simulation_fees_with_a_fixed_part_are_rebooked_per_broker(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    tr_bot = db.create_bot("t", "zones", SAP, {}, True, True, exchange=TRADEREPUBLIC)
    revx_bot = db.create_bot("r", "zones", "BTC-EUR", {}, True, True)
    db.update_bot(tr_bot, state={"positions": [{"qty": "0.49", "cost": "50", "opened_at": 1, "peak": "100", "paper": True, "id": "a"}]})
    db.add_trade(bot_id=tr_bot, bot_name="t", symbol=SAP, side="buy", price="100", base_qty="0.49", quote_amount="50",
                 fee="1", pnl=None, paper=1, reason="", position_id="a", exchange=TRADEREPUBLIC)
    db.add_trade(bot_id=revx_bot, bot_name="r", symbol="BTC-EUR", side="buy", price="100", base_qty="0.5",
                 quote_amount="50", fee="0", pnl=None, paper=1, reason="", position_id="b")
    old = {"buy": 0.0, "sell": 0.0, "fixed": 1.0}
    new = {"buy": 0.0, "sell": 0.0, "fixed": 2.0}
    assert db.reprice_paper(old, new, TRADEREPUBLIC) == 1
    trades = {t["bot_id"]: t for t in db.list_trades()}
    assert Decimal(trades[tr_bot]["base_qty"]) == Decimal("0.48") and Decimal(trades[tr_bot]["fee"]) == 2
    assert Decimal(trades[revx_bot]["base_qty"]) == Decimal("0.5")  # the other broker is untouched
    assert Decimal(db.get_bot(tr_bot)["state"]["positions"][0]["qty"]) == Decimal("0.48")
    assert db.get_paper_fees(TRADEREPUBLIC) == {"buy": 0.0, "sell": 0.0, "fixed": 1.0}  # the defaults


async def test_mock_trade_republic_trades_live_like_the_real_one(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    db.set_setting("live_trading.traderepublic", True)
    bot_id = db.create_bot("BTC", "dca", BTC, {"amount": 51}, True, False, exchange=TRADEREPUBLIC)
    await engine.tick()
    trade = db.list_trades(bot_id)[0]
    assert not trade["paper"] and Decimal(trade["fee"]) == 1 and trade["order_id"]
    assert (await tr.balances())["XF000BTC0017"][0] > 0
    await engine.close_position(bot_id)
    assert not open_positions(db.get_bot(bot_id)["state"])
    assert isinstance(engine.exchange_for(REVOLUTX), FakeExchange) and not isinstance(engine.exchange, MockExchange)


# --- REST API -------------------------------------------------------------------------------


def _api(tmp_path, monkeypatch, exchange: str):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("EXCHANGE", exchange)
    monkeypatch.setenv("REVX_API_KEY", "")
    monkeypatch.setenv("REVX_PRIVATE_KEY_PATH", str(tmp_path / "none.pem"))
    import app.main as main

    main = importlib.reload(main)
    client = TestClient(main.app)
    client.headers["Authorization"] = "Bearer t"
    return client, main


def test_api_keeps_the_brokers_apart(tmp_path, monkeypatch):
    client, main = _api(tmp_path, monkeypatch, "mock")
    status = client.get("/api/status").json()
    assert [e["id"] for e in status["exchanges"]] == ["revolutx", "traderepublic"]
    tr = status["exchanges"][1]
    assert tr["title"] == "Trade Republic" and tr["fees"] == {"rate": 0.0, "fixed": 1.0} and tr["simulated"]

    bot = client.post("/api/bots", json={"name": "SAP", "strategy": "dip", "symbol": "DE0007164600",
                                         "exchange": "traderepublic"}).json()
    assert bot["symbol"] == SAP and bot["exchange"] == "traderepublic" and bot["display_symbol"] == "SAP"
    revx = client.post("/api/bots", json={"name": "ETH", "strategy": "dip", "symbol": "ETH-EUR"}).json()
    assert revx["exchange"] == "revolutx" and revx["display_symbol"] == "ETH-EUR"
    r = client.post("/api/bots", json={"name": "x", "strategy": "dip", "symbol": "ETH-EUR", "exchange": "traderepublic"})
    assert r.status_code == 422
    r = client.put(f"/api/bots/{bot['id']}", json={"name": "SAP", "strategy": "dip", "symbol": "ETH-EUR",
                                                   "exchange": "revolutx"})
    assert r.status_code == 409  # a bot stays with its broker
    # an app that doesn't know brokers can still edit a Trade Republic bot – it stays where it is
    r = client.put(f"/api/bots/{bot['id']}", json={"name": "SAP 2", "strategy": "dip", "symbol": SAP})
    assert r.status_code == 200 and r.json()["exchange"] == "traderepublic"
    r = client.post("/api/bots", json={"name": "x", "strategy": "dip", "symbol": "US0378331005-USD", "exchange": "traderepublic"})
    assert r.json()["symbol"] == "US0378331005-EUR"  # Trade Republic trades in euros
    client.delete(f"/api/bots/{r.json()['id']}")
    # older apps only see Revolut X; the new app asks for all
    assert [b["exchange"] for b in client.get("/api/bots").json()] == ["revolutx"]
    assert len(client.get("/api/bots", params={"exchange": "all"}).json()) == 2
    assert client.get("/api/summary", params={"exchange": "nope"}).status_code == 422

    assert client.get("/api/summary", params={"exchange": "traderepublic"}).json()["bots_total"] == 1
    assert client.get("/api/summary").json()["exchange"] == "revolutx"

    client.put("/api/limits", params={"exchange": "traderepublic"},
               json={"max_open_positions": 7, "max_total_invested": 100, "one_position_per_symbol": False})
    assert client.get("/api/limits", params={"exchange": "traderepublic"}).json()["max_open_positions"] == 7
    assert client.get("/api/limits").json()["max_open_positions"] == 3

    fees = client.get("/api/paper-fees", params={"exchange": "traderepublic"}).json()
    assert fees == {"buy": 0.0, "sell": 0.0, "fixed": 1.0}
    fees = client.put("/api/paper-fees", params={"exchange": "traderepublic"}, json={"buy": 0, "sell": 0, "fixed": 1.5}).json()
    assert fees["fixed"] == 1.5
    # an app that only knows the two rates keeps the fixed part
    assert client.put("/api/paper-fees", params={"exchange": "traderepublic"}, json={"buy": 0.001, "sell": 0}).json()["fixed"] == 1.5
    assert client.get("/api/paper-fees").json() == {"buy": 0.0, "sell": 0.0009, "fixed": 0.0}

    found = client.get("/api/instruments", params={"exchange": "traderepublic", "q": "apple"}).json()
    assert found[0]["symbol"] == "US0378331005-EUR" and found[0]["short"] == "AAPL"
    assert "US0378331005-EUR" in client.get("/api/pairs", params={"exchange": "traderepublic"}).json()
    assert client.get("/api/traderepublic").json()["connected"] is True  # the demo market needs no login


def test_trade_republic_live_trading_needs_a_login(tmp_path, monkeypatch):
    client, main = _api(tmp_path, monkeypatch, "revolutx")
    info = client.get("/api/traderepublic").json()
    assert info["state"] == "logged_out" and info["connected"] is False
    tr = client.get("/api/status").json()["exchanges"][1]
    assert tr["configured"] is False and tr["live_trading_allowed"] is False
    r = client.put("/api/live-trading", json={"enabled": True, "confirm": "LIVE", "exchange": "traderepublic"})
    assert r.status_code == 409 and "Trade Republic" in r.json()["detail"]
    r = client.post("/api/traderepublic/login", json={"phone": "12", "pin": "1234"})
    assert r.status_code == 422
    r = client.post("/api/traderepublic/login", json={"phone": "+491711234567", "pin": "12"})
    assert r.status_code == 422 and "PIN" in r.json()["detail"]

    # logged in: live trading can be switched on – only for Trade Republic
    main.tr_session.cookies = {"tr_session": "s", "tr_refresh": jwt(time.time() + 3600)}
    main.tr_session.refresh_expires_at = int(time.time() + 3600)

    async def balances():
        return {"EUR": (Decimal(100), Decimal(100))}

    monkeypatch.setattr(main.engine.exchange_for("traderepublic"), "balances", balances)
    r = client.put("/api/live-trading", json={"enabled": True, "confirm": "LIVE", "exchange": "traderepublic"})
    assert r.status_code == 200
    exchanges = {e["id"]: e for e in r.json()["exchanges"]}
    assert exchanges["traderepublic"]["live_trading_allowed"] and not exchanges["revolutx"]["live_trading_allowed"]
    assert main.tr_needs_account()  # now the daily login may start itself

    # logging out switches live trading on Trade Republic off
    info = client.delete("/api/traderepublic").json()
    assert info["state"] == "logged_out" and info["phone_masked"] is None
    assert not main.engine.live_trading_enabled("traderepublic")


async def test_an_expiring_session_keeps_the_new_login_waiting(tmp_path: Path, monkeypatch):
    """The old session runs out while the next login waits for its confirmation – the login must go on."""
    monkeypatch.setattr("app.traderepublic.asyncio.sleep", _fast_sleep)
    fake = FakeLogin()
    fake.confirm_after = 10**6  # never confirmed during the test
    session = TradeRepublicSession(tmp_path, transport=httpx.MockTransport(fake), needs_account=lambda: True)
    session.phone, session.pin = "+491711234567", "1234"
    session.cookies = {"tr_session": "s1", "tr_refresh": jwt(time.time() + 60)}
    session.refresh_expires_at = int(time.time() + 60)  # ends in a minute: the daily login starts
    await session.maintain_once()
    assert session.process is not None
    fake.refresh_ok = False
    session.refreshed_at = float("-inf")
    with pytest.raises(Problem):
        await session.ensure_fresh()
    assert session.process is not None and session.state == "waiting"  # still waiting for the confirmation
    await session.close()


def test_a_broker_can_be_switched_off(tmp_path, monkeypatch):
    client, main = _api(tmp_path, monkeypatch, "mock")
    bot = client.post("/api/bots", json={"name": "BTC", "strategy": "dca", "symbol": "XF000BTC0017", "enabled": True,
                                         "exchange": "traderepublic"}).json()
    status = client.put("/api/brokers/traderepublic", json={"enabled": False}).json()
    assert {e["id"]: e["enabled"] for e in status["exchanges"]} == {"revolutx": True, "traderepublic": False}
    stopped = client.get("/api/bots", params={"exchange": "all"}).json()[0]
    assert not stopped["enabled"] and "switched off" in stopped["status"]
    assert client.post(f"/api/bots/{bot['id']}/start").status_code == 409
    r = client.post("/api/bots", json={"name": "x", "strategy": "dca", "symbol": "XF000BTC0017", "exchange": "traderepublic"})
    assert r.status_code == 409
    assert client.put("/api/brokers/revolutx", json={"enabled": False}).status_code == 409  # one has to stay on
    assert not main.engine.broker_enabled("traderepublic") and not main.tr_needs_account()
    assert client.put("/api/brokers/traderepublic", json={"enabled": True}).status_code == 200
    assert client.post(f"/api/bots/{bot['id']}/start").status_code == 200


async def test_a_broker_with_open_trades_stays_on(tmp_path: Path):
    db, engine, tr = two_brokers(tmp_path)
    db.create_bot("BTC", "dca", BTC, {"amount": 51}, True, True, exchange=TRADEREPUBLIC)
    await engine.tick()
    db.set_setting("brokers_disabled", [TRADEREPUBLIC])  # e.g. switched off by an older agent – the engine skips it
    calls = []
    original = tr.ticker

    async def counting(symbol):
        calls.append(symbol)
        return await original(symbol)

    tr.ticker = counting
    await engine.tick()
    assert calls == []


# --- order safety with Trade Republic -------------------------------------------------------


def test_unknown_error_codes_count_as_unclear():
    from app.engine import definitely_not_placed
    from app.traderepublic import TradeRepublicError, _error_status

    assert _error_status("JSON_PARSE_ERROR") == 422 and definitely_not_placed(TradeRepublicError(422, "x"))
    assert _error_status("AUTHENTICATION_ERROR") == 401
    assert _error_status("SOMETHING_NEW") == 503 and not definitely_not_placed(TradeRepublicError(503, "x"))


async def test_a_lost_order_is_only_matched_unambiguously(tmp_path: Path):
    async with FakeTR() as fake:
        db = Database(tmp_path / "t.db")
        session = logged_in_session(tmp_path)
        ex = TradeRepublicExchange(session, db, TRSocket(url=fake.url), TRSocket(cookies=session.cookie_header, url=fake.url))
        try:
            sold = await ex.place_market_order(SAP, "sell", client_order_id="c-sell", base_size=Decimal("0.5"))
            db.add_trade(bot_id=1, bot_name="b", symbol=SAP, side="sell", price="101", base_qty="0.5",
                         quote_amount="49.5", fee="1", pnl="0", order_id=sold, paper=0, reason="", exchange=TRADEREPUBLIC)
            # the next buy: its answer gets lost (the agent restarts and forgets the order id)
            await ex.place_market_order(SAP, "buy", client_order_id="c-buy", quote_size=Decimal("51"))
            ex._placed["c-buy"].order_id = ""
            pending = {"client_order_id": "c-buy", "side": "buy", "placed_at": int(time.time() * 1000)}
            found = await ex.find_lost_order(SAP, pending)
            assert found is not None and found.order_id != sold  # never the sale that is already booked
            assert ex._placed["c-buy"].order_id == found.order_id
            # a second buy of the same size in the same minute (e.g. by hand in the TR app) makes it ambiguous
            again = dict(fake.terminated[-1], id="o-by-hand")
            fake.terminated.append(again)
            ex._placed["c-buy"].order_id = ""
            assert await ex.find_lost_order(SAP, pending) is None
            # an order that never left the agent is not looked for at all
            assert await ex.find_lost_order(SAP, {"client_order_id": "never-sent", "side": "buy", "placed_at": 0}) is None
        finally:
            await ex.close()


async def test_an_executed_order_is_never_booked_without_a_price(tmp_path: Path, monkeypatch):
    session = logged_in_session(tmp_path)
    ex = TradeRepublicExchange(session, None)

    async def no_timeline(*_a, **_k):
        return None

    monkeypatch.setattr(ex, "_timeline_fill", no_timeline)
    now = int(time.time() * 1000)
    order = {"id": "o1", "status": "executed", "size": 0.5, "type": "buy", "instrumentId": "DE0007164600",
             "createdTime": now}
    assert (await ex._parse_order(order)).status == "new"  # wait for the timeline
    old = dict(order, createdTime=now - 10 * 60_000)

    async def quote(symbol):
        from app.exchange import Ticker
        return Ticker(Decimal("99"), Decimal("101"), Decimal("100"))

    monkeypatch.setattr(ex, "ticker", quote)
    result = await ex._parse_order(old)
    assert result.status == "filled" and result.avg_price == Decimal("101") and result.filled_amount > 0
    await ex.close()


async def test_a_rejected_saved_pin_is_forgotten(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.traderepublic.asyncio.sleep", _fast_sleep)
    session = TradeRepublicSession(tmp_path, transport=httpx.MockTransport(FakeLogin()), needs_account=lambda: True)
    session.phone, session.pin = "+491711234567", "9999"  # changed in the meantime
    await session.maintain_once()
    assert session.pin is None and session.process is None
    assert "saved PIN" in render(session.error, "en")
    session.auto_attempts, session.last_auto_attempt = 0, 0
    await session.maintain_once()
    assert session.process is None  # no further attempt with a PIN that isn't there
    await session.close()


def test_overnight_quotes_after_the_opening_mean_a_holiday():
    open_ = ms(2026, 12, 24, 7, 30)
    last_night = ms(2026, 12, 23, 22, 59)
    assert market_closed_at(STOCK, open_ + 2 * 60_000, last_night) is None  # the first minutes: quotes may still come
    assert market_closed_at(STOCK, open_ + 10 * 60_000, last_night) is not None
    assert market_closed_at(STOCK, open_ + 10 * 60_000, open_ + 9 * 60_000) is None
