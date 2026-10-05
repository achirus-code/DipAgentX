"""Trade Republic: login, WebSocket client and the exchange the engine trades on.

Trade Republic has no official API. This module speaks the protocol of its web app (app.traderepublic.com), as
documented by the open-source projects that reverse-engineered it (pytr and others):

* **Login** (v2 web login): phone number + PIN, then the user confirms the login in the Trade Republic app (push) –
  or enters the code of an authenticator app. The session cookie ``tr_session`` lives 5 minutes and is renewed with
  ``tr_refresh``, which itself expires 24 hours after the login. After that a new, confirmed login is needed.
* **WebSocket** ``wss://api.traderepublic.com``: ``connect 31 {…}``, then ``sub <id> <json>`` / ``unsub <id>``.
  Answers are ``<id> A <json>`` (full), ``<id> D <delta>`` (difference to the previous answer), ``<id> C``
  (completed) and ``<id> E <json>`` (error). Market data (prices, candles, instruments, search, trading hours) needs
  no login; the account (cash, portfolio, orders) needs the session cookies on the WebSocket handshake.
* **Orders**: ``simpleCreateOrder`` (market orders only – 1 € per order). Crypto trades 24/7, stocks and ETFs on
  Lang & Schwarz (LSX) Monday to Friday 07:30–23:00 (Europe/Berlin). Most instruments can be bought in fractions
  down to 1 €.

Note: Trade Republic's customer agreement doesn't allow access through programs it doesn't provide. The app says so
before anybody logs in.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import platform
import re
import secrets
import time
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import websockets
from websockets.exceptions import WebSocketException

from .errors import ExchangeError
from .exchange import (
    D0, TRADEREPUBLIC, Candle, Exchange, Fees, MockExchange, OrderResult, PairInfo, Ticker, dec,
)
from .i18n import Problem, at, m

log = logging.getLogger("dipagentx.traderepublic")

API_HOST = "https://api.traderepublic.com"
WS_URL = "wss://api.traderepublic.com"
CONNECT_VERSION = 31  # the server accepts 26–34; the topics depend on it
CONNECT_INFO = {
    "locale": "de",
    "platformId": "webtrading",
    "platformVersion": "chrome - 146.0.0",
    "clientId": "app.traderepublic.com",
    "clientVersion": "5582",
}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
# the web app's version – Trade Republic refuses outdated ones (HTTP 426); can be overridden with TR_APP_VERSION
DEFAULT_APP_VERSION = "2.2631.13"

FEE = Decimal("1")  # "Fremdkostenpauschale": 1 € per order, buy or sell
SESSION_REFRESH_S = 240  # tr_session lives 300 s
LOGIN_TIMEOUT_S = 180  # how long a login waits for the confirmation in the app
RELOGIN_BEFORE_S = 15 * 60  # start the next login this long before the 24 h refresh token runs out
RELOGIN_RETRY_S = 30 * 60  # an unconfirmed automatic login is retried after this long …
RELOGIN_MAX_ATTEMPTS = 3  # … this many times, then the app has to start it
REQUEST_TIMEOUT_S = 15
ORDER_TIMEOUT_S = 20
TICKER_IDLE_S = 600  # price subscriptions nobody asked for this long are dropped
STREAM_STALE_S = 90  # a price stream without an update for this long is subscribed again
TICKER_TIMEOUT_S = 10
STALE_QUOTE_MS = 30 * 60_000  # no new quote for this long during trading hours: the venue is closed (holiday)
# a buy is sized a little below the amount: the market order may execute slightly above the quoted ask
BUY_BUFFER = Decimal("0.997")
TIMELINE_WAIT_MS = 3 * 60_000  # an executed order without its price: wait this long for the timeline


class TradeRepublicError(ExchangeError):
    venue = "Trade Republic"


def _tr_errors(data: Any) -> tuple[str, str]:
    """(errorCode, errorMessage) of a Trade Republic error answer ``{"errors": [{…}]}``."""
    errors = data.get("errors") if isinstance(data, dict) else None
    if errors and isinstance(errors, list) and isinstance(errors[0], dict):
        return str(errors[0].get("errorCode") or ""), str(errors[0].get("errorMessage") or errors[0].get("errorCode") or "")
    return "", ""


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


def apply_delta(previous: str, delta: str) -> str:
    """Apply a "D" answer: tab-separated ``=n`` (keep n characters), ``-n`` (drop n), ``+text`` (insert)."""
    out: list[str] = []
    pos = 0
    for op in delta.split("\t"):
        if not op:
            continue
        sign, arg = op[0], op[1:]
        if sign == "+":
            out.append(urllib.parse.unquote_plus(arg))
        elif sign == "=":
            n = int(arg)
            out.append(previous[pos:pos + n])
            pos += n
        elif sign == "-":
            pos += int(arg)
        else:
            raise ValueError(f"unknown delta operation {op!r}")
    return "".join(out)


class _Subscription:
    """One ``sub``. One-shot requests read their answers from a queue; a persistent stream (prices) only keeps the
    latest value – it is sent again after a reconnect."""

    def __init__(self, payload: dict, persistent: bool):
        self.payload = payload
        self.persistent = persistent
        self.text: str | None = None  # the last full answer – the base of the next delta
        self.value: Any = None
        self.error: Exception | None = None  # persistent streams: why the stream is dead
        self.received_at = 0.0
        self.queue: asyncio.Queue = asyncio.Queue()
        self.updated = asyncio.Event()

    def push(self, item: Any) -> None:
        if self.persistent:
            if isinstance(item, Exception) and not isinstance(item, _Completed):
                self.error = item
                self.value = None  # a stream that failed must not serve its old price
            self.updated.set()
        else:
            self.queue.put_nowait(item)


class _Completed(Exception):
    pass


# error codes of "E" answers that clearly refuse the request; anything else may be temporary and – for an order –
# means "unclear": it is looked up instead of being sent again
REFUSED_CODES = {"JSON_PARSE_ERROR", "BAD_SUBSCRIPTION_TYPE", "VALIDATION_ERROR", "INVALID_VALUE", "INVALID_REQUEST"}


def _error_status(code: str) -> int:
    if code == "AUTHENTICATION_ERROR":
        return 401
    if code == "TOO_MANY_REQUESTS":
        return 429
    if "NOT_FOUND" in code or code == "UNKNOWN_INSTRUMENT":
        return 404
    if code in REFUSED_CODES or code.startswith(("INVALID_", "VALIDATION_")):
        return 422
    return 503


class TRSocket:
    """A WebSocket connection to Trade Republic that reconnects on demand.

    ``cookies`` supplies the session cookies for the account socket; the market data socket has none. When the
    cookies change (the session was renewed), the next request reconnects with the new ones. A keepalive ("echo")
    every 20 seconds detects a dead connection: without any frame for a minute the socket is closed.
    """

    KEEPALIVE_S = 20
    SILENCE_S = 60

    def __init__(self, cookies: Callable[[], str] | None = None, url: str = WS_URL,
                 connect: Callable[..., Awaitable[Any]] | None = None):
        self._cookies = cookies
        self._url = url
        self._connect = connect or websockets.connect
        self._ws: Any = None
        self._cookie_used = ""
        self._lock = asyncio.Lock()
        self._subs: dict[int, _Subscription] = {}
        self._next_id = 0
        self._tasks: list[asyncio.Task] = []
        self._last_frame = 0.0

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        """Make sure there is a connection – raises when Trade Republic can't be reached."""
        await self._ensure()

    async def _ensure(self) -> Any:
        async with self._lock:
            cookie = self._cookies() if self._cookies else ""
            if self._ws is not None and cookie == self._cookie_used:
                return self._ws
            # renewed session cookies: reconnect – but not under a request that is still waiting for its answer
            # (an order!); the next request reconnects, and an expired socket answers 401 anyway
            if self._ws is not None and any(not sub.persistent for sub in self._subs.values()):
                return self._ws
            await self._disconnect()
            headers = {"Cookie": cookie} if cookie else None
            try:
                ws = await self._connect(self._url, additional_headers=headers, user_agent_header=USER_AGENT,
                                         open_timeout=10, ping_interval=None, max_size=8 * 1024 * 1024)
                await ws.send(f"connect {CONNECT_VERSION} {json.dumps(CONNECT_INFO)}")
                reply = await asyncio.wait_for(ws.recv(), 10)
            except (OSError, TimeoutError, asyncio.TimeoutError, WebSocketException) as exc:
                raise TradeRepublicError(503, f"connection failed ({exc})") from exc
            if reply != "connected":
                with contextlib.suppress(Exception):
                    await ws.close()
                raise TradeRepublicError(503, f"connection refused ({reply})")
            self._ws, self._cookie_used = ws, cookie
            self._last_frame = time.monotonic()
            self._tasks = [asyncio.create_task(self._read(ws)), asyncio.create_task(self._keepalive(ws))]
            for sid, sub in self._subs.items():  # after a reconnect: the price streams start over
                if sub.persistent:
                    sub.text = None
                    await ws.send(f"sub {sid} {json.dumps(sub.payload)}")
            return ws

    async def _disconnect(self) -> None:
        ws, self._ws = self._ws, None
        for task in self._tasks:
            if task is not asyncio.current_task():
                task.cancel()
        self._tasks = []
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect()
            self._subs.clear()

    async def _keepalive(self, ws: Any) -> None:
        with contextlib.suppress(Exception):
            while True:
                await asyncio.sleep(self.KEEPALIVE_S)
                if time.monotonic() - self._last_frame > self.SILENCE_S:
                    # no answer, not even to the echo: the connection is dead (e.g. half-open after a network change)
                    log.info("Trade Republic connection silent for %ss – reconnecting", self.SILENCE_S)
                    await ws.close()
                    return
                await ws.send(f"echo {int(time.time() * 1000)}")

    async def _read(self, ws: Any) -> None:
        try:
            async for frame in ws:
                self._last_frame = time.monotonic()
                if isinstance(frame, bytes) or frame == "connected" or frame.startswith("echo"):
                    continue  # binary (protobuf) topics aren't used; echo answers the keepalive
                self._dispatch(frame)
        except (WebSocketException, OSError) as exc:
            log.info("Trade Republic connection closed: %s", exc)
        finally:
            if self._ws is ws:
                self._ws = None
            lost = TradeRepublicError(503, "connection lost")
            for sub in self._subs.values():
                if not sub.persistent:
                    sub.push(lost)

    def _dispatch(self, frame: str) -> None:
        sid_text, _, rest = frame.partition(" ")
        if not sid_text.isdigit():
            return
        sub = self._subs.get(int(sid_text))
        if sub is None:
            return  # an answer for something already unsubscribed
        code, payload = rest[:1], rest[1:].lstrip()
        try:
            if code == "A":
                sub.text = payload
            elif code == "D":
                if sub.text is None:
                    return  # a delta without its base – the next full answer follows
                sub.text = apply_delta(sub.text, payload)
            elif code == "C":
                sub.push(_Completed())
                return
            elif code == "E":
                try:
                    data = json.loads(payload) if payload else {}
                except ValueError:
                    data = {}
                error_code, message = _tr_errors(data)
                sub.push(TradeRepublicError(_error_status(error_code), message or error_code or payload or "error"))
                return
            else:
                return
            sub.value = json.loads(sub.text)
            sub.error = None
            sub.received_at = time.monotonic()
            sub.push(sub.value)
        except ValueError as exc:
            sub.text = None  # a broken base would spoil every following delta – wait for the next full answer
            log.warning("Unreadable Trade Republic answer for %s: %s", sub.payload.get("type"), exc)

    async def _send_sub(self, payload: dict, persistent: bool) -> tuple[int, _Subscription]:
        ws = await self._ensure()
        self._next_id += 1
        sid, sub = self._next_id, _Subscription(payload, persistent)
        self._subs[sid] = sub
        try:
            await ws.send(f"sub {sid} {json.dumps(payload)}")
        except (WebSocketException, OSError) as exc:
            self._subs.pop(sid, None)
            raise TradeRepublicError(503, f"connection lost ({exc})") from exc
        return sid, sub

    async def unsubscribe(self, sid: int) -> None:
        self._subs.pop(sid, None)
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.send(f"unsub {sid}")

    async def request(self, payload: dict, timeout: float = REQUEST_TIMEOUT_S,
                      until: Callable[[Any], bool] | None = None) -> Any:
        """Subscribe, wait for the first answer (or the first one ``until`` accepts) and unsubscribe."""
        sid, sub = await self._send_sub(payload, persistent=False)
        try:
            async with asyncio.timeout(timeout):
                while True:
                    item = await sub.queue.get()
                    if isinstance(item, _Completed):
                        if sub.value is not None:
                            return sub.value
                        raise TradeRepublicError(404, f"no answer for {payload.get('type')}")
                    if isinstance(item, Exception):
                        raise item
                    if until is None or until(item):
                        return item
        except TimeoutError as exc:
            raise TradeRepublicError(504, f"no answer for {payload.get('type')}") from exc
        finally:
            await self.unsubscribe(sid)

    async def stream(self, payload: dict) -> int:
        """A subscription that stays open (and survives reconnects); its latest value is ``latest(id)``."""
        sid, _ = await self._send_sub(payload, persistent=True)
        return sid

    def latest(self, sid: int) -> tuple[Any, float] | None:
        """The stream's latest value and when it arrived (monotonic seconds)."""
        sub = self._subs.get(sid)
        return (sub.value, sub.received_at) if sub and sub.value is not None else None

    async def wait_first(self, sid: int, timeout: float = REQUEST_TIMEOUT_S) -> Any:
        """The stream's value – waits for the first one. Raises when the stream failed."""
        sub = self._subs.get(sid)
        if sub is None:
            raise TradeRepublicError(503, "subscription closed")
        try:
            async with asyncio.timeout(timeout):
                while sub.value is None:
                    if sub.error is not None:
                        raise sub.error
                    sub.updated.clear()
                    await sub.updated.wait()
        except TimeoutError as exc:
            raise TradeRepublicError(504, f"no answer for {sub.payload.get('type')}") from exc
        return sub.value


# ---------------------------------------------------------------------------
# Login and session
# ---------------------------------------------------------------------------


def _jwt_exp(token: str | None) -> int | None:
    """Expiry (unix seconds) of a JWT – read only, Trade Republic checks the signature."""
    try:
        payload = token.split(".")[1]  # type: ignore[union-attr]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(data["exp"])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


def normalize_phone(raw: str) -> str:
    """"0171 1234567" / "+49 171-1234567" → "+491711234567" (German numbers without a country code)."""
    phone = re.sub(r"[\s\-/()]", "", raw or "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    elif phone.startswith("0"):
        phone = "+49" + phone[1:]
    if not re.fullmatch(r"\+\d{8,15}", phone):
        raise Problem("tr.phone_invalid")
    return phone


def mask_phone(phone: str | None) -> str | None:
    return f"{phone[:3]}…{phone[-3:]}" if phone and len(phone) > 7 else None


@dataclass
class LoginProcess:
    process_id: str
    started_at: float
    expires_at: float
    automatic: bool
    http: httpx.AsyncClient  # its own cookies: the current session stays usable until the new one is confirmed
    code_required: bool = False
    task: asyncio.Task | None = None


class TradeRepublicSession:
    """The login: started from the app, confirmed in the Trade Republic app, renewed in the background.

    The cookies (and, if the user wants, phone number and PIN for the daily login) are kept in
    ``<data>/tr_session.json`` with file mode 600. With the PIN saved the agent starts the next login on its own
    when the 24-hour session runs out – but only while it needs the account (live trading on or live trades
    open); the user then only confirms it in the Trade Republic app.
    """

    def __init__(self, data_dir: Path, app_version: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 needs_account: Callable[[], bool] | None = None):
        self.file = data_dir / "tr_session.json"
        self.device_file = data_dir / "tr_device_id"
        self.app_version = app_version or DEFAULT_APP_VERSION
        self.needs_account = needs_account or (lambda: False)
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self.phone: str | None = None
        self.pin: str | None = None
        self.cookies: dict[str, str] = {}
        self.account: dict[str, Any] = {}
        self.logged_in_at: int | None = None
        self.refresh_expires_at: int | None = None  # unix seconds
        self.refreshed_at = float("-inf")  # monotonic – a session read from the file is renewed before its first use
        self._generation = 0  # counts the logins: a refresh answer of an older login is ignored
        self._login_lock = asyncio.Lock()
        self.error: dict | None = None  # why the last login failed or the session ended (an i18n message)
        self.process: LoginProcess | None = None
        self.auto_attempts = 0
        self.last_auto_attempt = 0.0
        self.on_login: Callable[[], None] | None = None  # the exchange drops its account socket
        self._refresh_lock = asyncio.Lock()
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self.file.read_text())
        except (OSError, ValueError):
            return
        self.phone = data.get("phone")
        self.pin = data.get("pin")
        self.cookies = dict(data.get("cookies") or {})
        self.account = dict(data.get("account") or {})
        self.logged_in_at = data.get("logged_in_at")
        self.refresh_expires_at = data.get("refresh_expires_at")

    def _save(self) -> None:
        data = {
            "phone": self.phone, "pin": self.pin, "cookies": self.cookies, "account": self.account,
            "logged_in_at": self.logged_in_at, "refresh_expires_at": self.refresh_expires_at,
        }
        tmp = self.file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.file)

    def _device_info(self) -> str:
        """What the web app tells about the browser – the device id must stay the same across logins."""
        try:
            seed = self.device_file.read_text().strip()
        except OSError:
            seed = secrets.token_hex(32)
            fd = os.open(self.device_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(seed)
        offset = datetime.now(ZoneInfo("Europe/Berlin")).utcoffset() or timedelta()
        device = {
            "stableDeviceId": hashlib.sha512(seed.encode()).hexdigest(),
            "browser": "Chrome", "browserVersion": "146.0.0.0", "os": platform.system(), "osVersion": platform.release(),
            "timezone": "Europe/Berlin", "timezoneOffset": -int(offset.total_seconds() // 60),
            "screen": "1920x1080x24", "preferredLanguages": ["de"], "numberOfCores": os.cpu_count() or 4,
        }
        return base64.b64encode(json.dumps(device).encode()).decode()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "X-TR-Device-Info": self._device_info(),
            "X-TR-App-Version": self.app_version,
            "X-Tr-Platform": "web-pro",
            "Accept-Language": "de",
            "Accept": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=API_HOST, timeout=httpx.Timeout(15.0), transport=self._transport)
            for name, value in self.cookies.items():
                self._http.cookies.set(name, value, domain=".traderepublic.com")
        return self._http

    def _take_cookies(self) -> None:
        jar = self._client().cookies
        self.cookies = {c.name: c.value for c in jar.jar if c.domain.endswith("traderepublic.com")}

    async def close(self) -> None:
        await self.cancel_login()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- state ----------------------------------------------------------------

    @property
    def logged_in(self) -> bool:
        return bool(self.cookies.get("tr_refresh")) and (self.refresh_expires_at or 0) > time.time()

    @property
    def state(self) -> str:
        """logged_out | waiting (for the confirmation in the app) | code (authenticator code needed) | logged_in"""
        if self.process:
            return "code" if self.process.code_required else "waiting"
        return "logged_in" if self.logged_in else "logged_out"

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def describe(self) -> dict[str, Any]:
        process = self.process
        return {
            "state": self.state,
            "connected": self.logged_in,
            "phone_masked": mask_phone(self.phone),
            "pin_saved": bool(self.pin),
            "logged_in_at": self.logged_in_at,
            "session_expires_at": int(self.refresh_expires_at * 1000) if self.refresh_expires_at and self.logged_in else None,
            "waiting_until": int(process.expires_at * 1000) if process else None,
            "automatic": bool(process and process.automatic),
            "error": self.error,
        }

    # --- login ----------------------------------------------------------------

    async def start_login(self, phone: str | None = None, pin: str | None = None, remember_pin: bool = True,
                          automatic: bool = False) -> None:
        """Send phone number and PIN; Trade Republic then asks for the confirmation in its app. Without arguments
        the saved phone number and PIN are used (the daily login)."""
        async with self._login_lock:  # an automatic and a manual login never run side by side
            await self._start_login(phone, pin, remember_pin, automatic)

    async def _start_login(self, phone: str | None, pin: str | None, remember_pin: bool, automatic: bool) -> None:
        phone = normalize_phone(phone) if phone else self.phone
        pin = pin or self.pin
        if not phone or not pin:
            raise Problem("tr.credentials_missing")
        if not re.fullmatch(r"\d{4}", pin):
            raise Problem("tr.pin_invalid")
        await self.cancel_login()
        http = httpx.AsyncClient(base_url=API_HOST, timeout=httpx.Timeout(15.0), transport=self._transport)
        try:
            r = await http.post("/api/v2/auth/web/login", json={"phoneNumber": phone, "pin": pin}, headers=self._headers())
            if r.status_code >= 400:
                raise self._login_problem(r)
            data = r.json()
            process_id = data.get("processId")
            if not process_id:
                raise Problem("tr.login_failed", error=str(data)[:200])
        except httpx.HTTPError as exc:
            await http.aclose()
            raise Problem("tr.unreachable", error=str(exc)) from exc
        except BaseException:
            await http.aclose()
            raise
        self.phone = phone
        self.pin = pin if remember_pin else None
        self.error = None
        countdown = float(data.get("countdownInSeconds") or 0) or LOGIN_TIMEOUT_S
        now = time.time()
        self.process = LoginProcess(process_id, now, now + max(countdown, 60), automatic, http)
        self._save()
        self.process.task = asyncio.create_task(self._wait_for_confirmation(self.process))
        log.info("Trade Republic login started%s – waiting for the confirmation in the app",
                 " automatically" if automatic else "")

    def _login_problem(self, r: httpx.Response) -> Problem:
        try:
            code, message = _tr_errors(r.json())
        except ValueError:
            code, message = "", r.text[:200]
        if r.status_code == 426 or code == "CLIENT_VERSION_OUTDATED":
            return Problem("tr.version_outdated")
        if code in {"AUTHENTICATION_ERROR", "INVALID_VALUE", "VALIDATION_CODE_INVALID"} or r.status_code == 401:
            return Problem("tr.wrong_credentials")
        if code == "NUMBER_INVALID":
            return Problem("tr.phone_invalid")
        if code == "TOO_MANY_REQUESTS" or r.status_code == 429:
            return Problem("tr.too_many_attempts")
        if code in {"LOGIN_NOT_ALLOWED", "WEBTRADING_NOT_AVAILABLE"}:
            return Problem("tr.web_login_unavailable")
        return Problem("tr.login_failed", error=message or code or f"HTTP {r.status_code}")

    async def submit_code(self, code: str) -> None:
        """The six-digit code of an authenticator app, when Trade Republic asks for it."""
        process = self.process
        if process is None:
            raise Problem("tr.no_login_running")
        code = re.sub(r"\s", "", code or "")
        if not re.fullmatch(r"\d{4,8}", code):
            raise Problem("tr.code_invalid")
        r = await process.http.post(f"/api/v2/auth/web/login/processes/{process.process_id}/authenticator-verification",
                                    json={"code": code}, headers=self._headers())
        if r.status_code >= 400:
            raise self._login_problem(r)
        process.code_required = False  # Trade Republic may still want the confirmation in the app

    async def cancel_login(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        if process.task and process.task is not asyncio.current_task():
            process.task.cancel()
        with contextlib.suppress(Exception):
            await process.http.aclose()

    async def _wait_for_confirmation(self, process: LoginProcess) -> None:
        http = process.http
        try:
            while time.time() < process.expires_at:
                await asyncio.sleep(2)
                if self.process is not process:
                    return
                try:
                    r = await http.get(f"/api/v2/auth/web/login/processes/{process.process_id}", headers=self._headers())
                except httpx.HTTPError as exc:
                    log.warning("Trade Republic login: %s", exc)
                    continue
                if r.status_code in (404, 410):
                    self._login_failed(m("tr.login_not_confirmed"))
                    return
                data = r.json() if r.content else {}
                if r.status_code >= 400:
                    self._login_failed(self._login_problem(r).msg)
                    return
                if data.get("requiredAction") == "AUTHENTICATOR_VERIFICATION" and data.get("status") == "PENDING":
                    process.code_required = True
                status = data.get("status")
                if status not in (None, "PENDING", "CONFIRMED", "COMPLETED"):
                    self._login_failed(m("tr.login_failed", error=status))
                    return
                if "tr_session" not in http.cookies and "tr_refresh" in http.cookies:
                    with contextlib.suppress(httpx.HTTPError):
                        await http.get("/api/v1/auth/web/session", headers=self._headers())
                if "tr_session" in http.cookies:
                    await self._logged_in(http)
                    return
            self._login_failed(m("tr.login_not_confirmed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 – a failed login must never take the agent down
            log.exception("Trade Republic login failed")
            self._login_failed(m("tr.login_failed", error=str(exc)[:200]))
        finally:
            with contextlib.suppress(Exception):
                await http.aclose()

    def _login_failed(self, reason: dict) -> None:
        automatic = bool(self.process and self.process.automatic)
        self.process = None
        self.error = reason
        log.warning("Trade Republic login %s", "not confirmed" if automatic else "failed")

    async def _logged_in(self, login_http: httpx.AsyncClient) -> None:
        async with self._refresh_lock:  # a refresh of the old session must not overwrite (or end) the new one
            self._generation += 1
            client = self._client()
            client.cookies.clear()
            for c in login_http.cookies.jar:
                client.cookies.set(c.name, c.value, domain=c.domain or ".traderepublic.com")
            self._take_cookies()
        now = time.time()
        self.logged_in_at = int(now * 1000)
        self.refresh_expires_at = _jwt_exp(self.cookies.get("tr_refresh")) or int(now + 24 * 3600)
        self.refreshed_at = time.monotonic()
        self.process = None
        self.error = None
        self.auto_attempts = 0
        await self.load_account()
        self._save()
        log.info("Trade Republic login confirmed – session valid until %s",
                 datetime.fromtimestamp(self.refresh_expires_at).strftime("%Y-%m-%d %H:%M"))
        if self.on_login:
            self.on_login()

    async def load_account(self) -> None:
        """The securities account number (needed for the portfolio) – fetched at the login, or later if that failed."""
        try:
            r = await self._client().get("/api/v2/auth/account", headers=self._headers())
            if r.status_code < 400:
                data = r.json()
                self.account = {k: data.get(k) for k in ("securitiesAccountNumber", "cashAccount", "jurisdiction") if k in data}
                self._save()
            else:
                log.warning("Trade Republic account details not available: HTTP %s", r.status_code)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Trade Republic account details not available: %s", exc)

    def _session_ended(self) -> None:
        """The 24 hours are over: forget the session – a login that is waiting for its confirmation goes on."""
        self.cookies = {}
        self.account = {}
        self.logged_in_at = self.refresh_expires_at = None
        if self._http is not None:
            self._http.cookies.clear()
        self.error = m("tr.session_expired")
        self._save()
        log.warning("Trade Republic session expired – a new, confirmed login is needed")

    async def logout(self, forget: bool = True) -> None:
        await self.cancel_login()
        self.cookies = {}
        self.account = {}
        self.logged_in_at = self.refresh_expires_at = None
        if forget:
            self.phone = self.pin = None
            self.error = None
        if self._http is not None:
            self._http.cookies.clear()
        if forget:
            self.file.unlink(missing_ok=True)
        else:
            self._save()

    # --- keeping the session alive ---------------------------------------------

    async def ensure_fresh(self) -> None:
        """Renew ``tr_session`` (5 minutes) when it is older than 4 minutes. Raises when there is no login."""
        if not self.logged_in:
            raise Problem("tr.login_required")
        if time.monotonic() - self.refreshed_at < SESSION_REFRESH_S:
            return
        async with self._refresh_lock:
            if time.monotonic() - self.refreshed_at < SESSION_REFRESH_S:
                return
            generation = self._generation
            try:
                r = await self._client().get("/api/v1/auth/web/session", headers=self._headers())
            except httpx.HTTPError as exc:
                raise TradeRepublicError(503, f"session refresh failed ({exc})") from exc
            if generation != self._generation:
                return  # a new login arrived meanwhile – this answer belongs to the old one
            if r.status_code in (401, 403):
                self._session_ended()
                raise Problem("tr.login_required")
            if r.status_code >= 400:
                raise TradeRepublicError(r.status_code, f"session refresh failed ({r.text[:120]})")
            self._take_cookies()
            self.refreshed_at = time.monotonic()
            self._save()

    async def maintain(self) -> None:
        """Background loop: start the daily login on its own – only with a saved PIN and only while the account is
        needed (live trading on, or live trades open). The user confirms it in the Trade Republic app."""
        while True:
            try:
                await asyncio.sleep(30)
                await self.maintain_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Trade Republic session upkeep: %s", exc)

    async def maintain_once(self) -> None:
        if self.process or not (self.phone and self.pin) or not self.needs_account():
            return
        now = time.time()
        expiring = self.logged_in and (self.refresh_expires_at or 0) - now < RELOGIN_BEFORE_S
        if not (expiring or not self.logged_in):
            return
        if self.auto_attempts >= RELOGIN_MAX_ATTEMPTS or now - self.last_auto_attempt < RELOGIN_RETRY_S:
            return
        self.auto_attempts += 1
        self.last_auto_attempt = now
        try:
            await self.start_login(automatic=True)
        except Problem as exc:
            self.error = exc.msg
            log.warning("Automatic Trade Republic login failed: %s", exc)
            if exc.msg["k"] == "tr.wrong_credentials":
                # the PIN was changed: never try the old one again – too many wrong PINs may lock the account
                self.pin = None
                self.error = m("tr.saved_pin_rejected")
                self._save()


# ---------------------------------------------------------------------------
# Instruments and trading hours
# ---------------------------------------------------------------------------

# Offered in the app before anybody searches – and the instruments of the demo market (EXCHANGE=mock).
DEFAULT_INSTRUMENTS: dict[str, dict[str, Any]] = {
    "XF000BTC0017": {"name": "Bitcoin", "short": "BTC", "type": "crypto", "price": 58000.0},
    "XF000ETH0019": {"name": "Ethereum", "short": "ETH", "type": "crypto", "price": 2300.0},
    "XF000SOL0012": {"name": "Solana", "short": "SOL", "type": "crypto", "price": 140.0},
    "XF000XRP0018": {"name": "XRP", "short": "XRP", "type": "crypto", "price": 0.52},
    "IE00B4L5Y983": {"name": "iShares Core MSCI World", "short": "EUNL", "type": "fund", "price": 98.0},
    "IE00BK5BQT80": {"name": "Vanguard FTSE All-World (Acc)", "short": "VWCE", "type": "fund", "price": 128.0},
    "IE00B5BMR087": {"name": "iShares Core S&P 500", "short": "SXR8", "type": "fund", "price": 560.0},
    "US0378331005": {"name": "Apple", "short": "AAPL", "type": "stock", "price": 205.0},
    "US5949181045": {"name": "Microsoft", "short": "MSFT", "type": "stock", "price": 430.0},
    "US67066G1040": {"name": "NVIDIA", "short": "NVDA", "type": "stock", "price": 150.0},
    "US88160R1014": {"name": "Tesla", "short": "TSLA", "type": "stock", "price": 300.0},
    "DE0007164600": {"name": "SAP", "short": "SAP", "type": "stock", "price": 240.0},
    "DE0007236101": {"name": "Siemens", "short": "SIE", "type": "stock", "price": 210.0},
    "DE0008404005": {"name": "Allianz", "short": "ALV", "type": "stock", "price": 350.0},
}
LSX_HOURS = {"venue": "LSX", "open_ms": 27_000_000, "close_ms": 82_800_000, "tz": "Europe/Berlin", "weekdays": True}
CRYPTO_HOURS = {"venue": "BHS", "open_ms": 0, "close_ms": 86_399_000, "tz": "Europe/Berlin", "weekdays": False}
ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def isin_of(symbol: str) -> str:
    isin = symbol.partition("-")[0].upper()
    if not ISIN_RE.fullmatch(isin):
        raise Problem("tr.unknown_instrument", symbol=symbol)
    return isin


def default_meta(isin: str) -> dict[str, Any]:
    """What we assume about an instrument before Trade Republic told us more (the defaults above)."""
    known = DEFAULT_INSTRUMENTS.get(isin, {})
    crypto = known.get("type") == "crypto" or isin.startswith("XF000")
    return {
        "isin": isin, "name": known.get("name", isin), "short": known.get("short"),
        "type": known.get("type", "crypto" if crypto else "stock"),
        **(CRYPTO_HOURS if crypto else LSX_HOURS),
        "step": "0.000001", "min_size": "0.000001", "min_amount": "1", "fractional": True,
    }


def market_closed_at(meta: dict[str, Any], now_ms: int, quote_ms: int | None = None) -> dict | None:
    """Why the venue is closed at ``now_ms`` (a message with the next opening), or None while it trades."""
    open_ms, close_ms = int(meta.get("open_ms", 0)), int(meta.get("close_ms", 86_399_000))
    weekdays = bool(meta.get("weekdays", True))
    if close_ms - open_ms >= 86_000_000 and not weekdays:
        return None  # crypto: around the clock
    tz = ZoneInfo(meta.get("tz") or "Europe/Berlin")
    now = datetime.fromtimestamp(now_ms / 1000, tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_midnight = (now - midnight).total_seconds() * 1000

    def trading_day(day: datetime) -> bool:
        return not weekdays or day.weekday() < 5

    if trading_day(now) and open_ms <= since_midnight < close_ms:
        opened = midnight.timestamp() * 1000 + open_ms
        # a holiday: no quote since the opening (after a few minutes), or none for half an hour during the day
        no_quote_today = quote_ms and quote_ms < opened and now_ms - opened > 5 * 60_000
        silent = quote_ms and now_ms - quote_ms > STALE_QUOTE_MS and now_ms - opened > STALE_QUOTE_MS
        if no_quote_today or silent:
            return m("tr.no_quotes", since=at(quote_ms, meta.get("tz") or "Europe/Berlin"))
        return None
    day = midnight if since_midnight < open_ms else midnight + timedelta(days=1)
    while not trading_day(day):
        day += timedelta(days=1)
    opens = day + timedelta(milliseconds=open_ms)
    return m("tr.market_closed", opens=at(int(opens.timestamp() * 1000), meta.get("tz") or "Europe/Berlin"))


def _rebucket(raw: list[Candle], interval: int) -> list[Candle]:
    """Candles of ``interval`` minutes from finer (or equal) ones."""
    step = interval * 60_000
    out: list[Candle] = []
    for c in sorted(raw, key=lambda c: c.start):
        start = c.start - c.start % step
        if out and out[-1].start == start:
            last = out[-1]
            out[-1] = Candle(start, last.open, max(last.high, c.high), min(last.low, c.low), c.close)
        else:
            out.append(Candle(start, c.open, c.high, c.low, c.close))
    return out


def _german_number(text: str) -> Decimal | None:
    """"1.234,56 €" → 1234.56 (Trade Republic's timeline is formatted in German)."""
    match = re.search(r"-?[\d.]+(?:,\d+)?", text.replace(" ", " "))
    if not match:
        return None
    try:
        return Decimal(match.group().replace(".", "").replace(",", "."))
    except ArithmeticError:
        return None


# ---------------------------------------------------------------------------
# The exchange
# ---------------------------------------------------------------------------


@dataclass
class _PlacedOrder:
    """An order the agent sent – remembered (also across restarts) to find it again when its answer got lost."""

    client_order_id: str
    isin: str
    side: str
    size: Decimal
    step: Decimal
    created_ms: int
    price_hint: Decimal  # the quote when it was sent – only used if Trade Republic never tells the fill price
    order_id: str = ""  # Trade Republic's id, once known

    def to_json(self) -> dict[str, Any]:
        return {"client_order_id": self.client_order_id, "isin": self.isin, "side": self.side, "size": str(self.size),
                "step": str(self.step), "created_ms": self.created_ms, "price_hint": str(self.price_hint),
                "order_id": self.order_id}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "_PlacedOrder":
        return cls(d["client_order_id"], d["isin"], d["side"], Decimal(d["size"]), Decimal(d.get("step") or "0.000001"),
                   int(d["created_ms"]), Decimal(d.get("price_hint") or "0"), d.get("order_id") or "")


class TradeRepublicExchange(Exchange):
    """Trade Republic for the engine: prices and candles from the public market data, orders and balances from the
    logged-in account. Instruments are ISINs (symbol ``<ISIN>-EUR``); what they stand for is kept in the database."""

    name = "traderepublic"
    broker = TRADEREPUBLIC
    partial_fills = False  # a market order executes completely or not at all
    live_fees = Fees(0.0, float(FEE))
    # the order lists lag behind and executed orders may only show up in the timeline – look longer before giving up
    order_lookup_grace_ms = 15 * 60_000
    BALANCES_TTL = 60.0
    ORDERS_KEPT = 200

    def __init__(self, session: TradeRepublicSession, db: Any, market: TRSocket | None = None,
                 account: TRSocket | None = None):
        self.session = session
        self.db = db
        self.market = market or TRSocket()
        self.account = account or TRSocket(cookies=session.cookie_header)
        self._meta: dict[str, dict[str, Any]] = {}
        self._meta_lock = asyncio.Lock()
        self._tickers: dict[str, int] = {}  # symbol → stream id
        self._ticker_used: dict[str, float] = {}
        self._balances: dict[str, tuple[Decimal, Decimal]] | None = None
        self._balances_at = 0.0
        self._placed: dict[str, _PlacedOrder] = {}  # by our client_order_id
        self._orders_file = session.file.parent / "tr_orders.json"
        self._load_orders()
        session.on_login = self._on_login
        if db is not None:
            for symbol, meta in db.instruments(TRADEREPUBLIC).items():
                self._meta[symbol] = meta

    # --- the orders the agent sent ------------------------------------------------

    def _load_orders(self) -> None:
        try:
            rows = json.loads(self._orders_file.read_text())
        except (OSError, ValueError):
            return
        for row in rows if isinstance(rows, list) else []:
            with contextlib.suppress(KeyError, TypeError, ArithmeticError, ValueError):
                placed = _PlacedOrder.from_json(row)
                self._placed[placed.client_order_id] = placed

    def _save_orders(self) -> None:
        newest = sorted(self._placed.values(), key=lambda p: p.created_ms)[-self.ORDERS_KEPT:]
        self._placed = {p.client_order_id: p for p in newest}
        tmp = self._orders_file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump([p.to_json() for p in newest], f)
        os.replace(tmp, self._orders_file)

    def _placed_by_id(self, order_id: str) -> _PlacedOrder | None:
        return next((p for p in self._placed.values() if p.order_id == order_id), None)

    def _on_login(self) -> None:
        self.invalidate_balances()

    def invalidate_balances(self) -> None:
        self._balances = None

    # --- instruments ------------------------------------------------------------

    def instrument(self, symbol: str) -> dict:
        isin = symbol.partition("-")[0]
        meta = self._meta.get(symbol) or default_meta(isin)
        return {"name": meta.get("name") or isin, "short": meta.get("short"), "type": meta.get("type"), "isin": isin}

    async def resolve(self, symbol: str) -> dict[str, Any]:
        """Name, ticker, venue, trading hours and fraction rules of an instrument – asked once, then remembered."""
        if symbol in self._meta and self._meta[symbol].get("resolved"):
            return self._meta[symbol]
        async with self._meta_lock:
            if symbol in self._meta and self._meta[symbol].get("resolved"):
                return self._meta[symbol]
            isin = isin_of(symbol)
            try:
                info = await self.market.request({"type": "instrument", "id": isin, "jurisdiction": "DE"})
            except TradeRepublicError as exc:
                if exc.status in (404, 422):
                    raise Problem("tr.unknown_instrument", symbol=isin) from exc
                raise
            home = await self.market.request({"type": "homeInstrumentExchange", "id": isin})
            meta = self._parse_meta(isin, info, home)
            self._meta[symbol] = meta
            if self.db is not None:
                self.db.save_instrument(TRADEREPUBLIC, symbol, meta)
            return meta

    @staticmethod
    def _parse_meta(isin: str, info: dict, home: dict) -> dict[str, Any]:
        meta = default_meta(isin)
        type_id = str(info.get("typeId") or meta["type"]).lower()
        venue = home.get("exchangeId") or (info.get("exchangeIds") or [meta["venue"]])[0]
        exchange = next((e for e in info.get("exchanges") or [] if e.get("slug") == venue), {})
        fractional = exchange.get("fractionalTrading") or {}
        fractional_allowed = bool(info.get("fractionalTradingAllowed", True)) and bool(fractional)
        # AAPL rather than the German APC; ETFs often only have the home symbol (EUNL)
        short = info.get("intlSymbol") or info.get("homeSymbol") or exchange.get("symbolAtExchange")
        meta.update({
            "name": info.get("shortName") or info.get("name") or meta["name"],
            "short": short or meta.get("short") or (info.get("shortName") or isin)[:6],
            "type": "crypto" if type_id == "crypto" else type_id,
            "venue": venue,
            "tz": ((home.get("exchange") or {}).get("timeZoneId")) or "Europe/Berlin",
            "open_ms": int(home.get("openTimeOffsetMillis") or meta["open_ms"]),
            "close_ms": int(home.get("closeTimeOffsetMillis") or meta["close_ms"]),
            "weekdays": type_id != "crypto",
            "order_modes": home.get("orderModes") or ["market"],
            "fractional": fractional_allowed,
            "step": str(fractional.get("stepSize") or "1") if fractional_allowed else "1",
            "min_size": str(fractional.get("minOrderSize") or "1") if fractional_allowed else "1",
            "min_amount": str(fractional.get("minOrderAmount") or "1") if fractional_allowed else "0",
            "tradable": bool(info.get("tradable", True)),
            "resolved": True,
        })
        return meta

    def _pair_info(self, symbol: str, meta: dict[str, Any]) -> PairInfo:
        return PairInfo(
            symbol=symbol, base=meta["isin"], quote="EUR",
            base_step=Decimal(meta["step"]), quote_step=Decimal("0.01"),
            min_order_size=Decimal(meta["min_size"]),
            # the amount of a bot includes the 1 € fee
            min_order_size_quote=Decimal(meta["min_amount"]) + FEE,
        )

    async def pairs(self) -> dict[str, PairInfo]:
        symbols = {f"{isin}-EUR" for isin in DEFAULT_INSTRUMENTS} | set(self._meta)
        return {s: self._pair_info(s, self._meta.get(s) or default_meta(s.partition("-")[0])) for s in sorted(symbols)}

    async def pair(self, symbol: str) -> PairInfo:
        return self._pair_info(symbol, await self.resolve(symbol))

    async def search(self, query: str) -> list[dict[str, Any]]:
        if ISIN_RE.fullmatch(query.upper()):
            symbol = f"{query.upper()}-EUR"
            meta = await self.resolve(symbol)
            return [{"symbol": symbol, **self.instrument(symbol), "type": meta.get("type")}]
        data = await self.market.request({"type": "neonSearch", "data": {"q": query, "page": 1, "pageSize": 20, "filter": []}})
        results = []
        for r in (data or {}).get("results") or []:
            isin = r.get("isin")
            if not isin or not ISIN_RE.fullmatch(isin):
                continue
            symbol = f"{isin}-EUR"
            known = self._meta.get(symbol) or {}
            results.append({
                "symbol": symbol, "isin": isin, "name": r.get("name") or isin,
                "short": known.get("short") or DEFAULT_INSTRUMENTS.get(isin, {}).get("short"),
                "type": str(r.get("instrumentType") or known.get("type") or "").lower() or None,
            })
        return results

    def market_closed(self, symbol: str, ticker: Ticker) -> dict | None:
        meta = self._meta.get(symbol) or default_meta(symbol.partition("-")[0])
        return market_closed_at(meta, self.now_ms(), ticker.time)

    # --- prices ---------------------------------------------------------------

    @staticmethod
    def _parse_ticker(data: dict) -> Ticker:
        def part(key: str) -> tuple[Decimal, int]:
            p = data.get(key) or {}
            return dec(p.get("price")), int(p.get("time") or 0)

        (bid, bt), (ask, at_), (last, lt) = part("bid"), part("ask"), part("last")
        last = last or (bid + ask) / 2 if (bid and ask) else last or bid or ask
        return Ticker(bid=bid or last, ask=ask or last, last=last, time=max(bt, at_, lt) or None)

    async def ticker(self, symbol: str) -> Ticker:
        meta = await self.resolve(symbol)
        self._ticker_used[symbol] = time.monotonic()
        sid = self._tickers.get(symbol)
        latest = self.market.latest(sid) if sid is not None else None
        # a stream without news for a while is subscribed again: a silent stream must never serve an old price
        stale = latest is not None and time.monotonic() - latest[1] > STREAM_STALE_S
        if sid is None or not self.market.connected or stale:
            if sid is not None:
                await self.market.unsubscribe(sid)
            sid = self._tickers[symbol] = await self.market.stream({"type": "ticker", "id": f"{meta['isin']}.{meta['venue']}"})
        try:
            value = await self.market.wait_first(sid, timeout=TICKER_TIMEOUT_S)
        except TradeRepublicError:
            # a stream that failed (or never answered) is dropped – the next request subscribes afresh
            self._tickers.pop(symbol, None)
            await self.market.unsubscribe(sid)
            raise
        ticker = self._parse_ticker(value)
        if not ticker.last:
            raise Problem("err.no_ticker", symbol=symbol)
        return ticker

    async def idle(self) -> None:
        """Drop the price streams nobody asked for in a while (stopped or deleted bots)."""
        now = time.monotonic()
        for symbol in [s for s, used in self._ticker_used.items() if now - used > TICKER_IDLE_S]:
            self._ticker_used.pop(symbol, None)
            if (sid := self._tickers.pop(symbol, None)) is not None:
                await self.market.unsubscribe(sid)

    async def tickers(self, symbols: list[str]) -> dict[str, Ticker]:
        await self.idle()
        results = await asyncio.gather(*(self.ticker(s) for s in symbols), return_exceptions=True)
        return {s: r for s, r in zip(symbols, results) if isinstance(r, Ticker)}

    async def candles(self, symbol: str, interval: int, since: int, until: int) -> list[Candle]:
        meta = await self.resolve(symbol)
        span_days = (until - since) / 86_400_000
        # "1d" is only the current trading day – "5d" covers a full 24 h window over night and weekend
        range_ = "5d" if span_days <= 5 else "1m" if span_days <= 30 else "3m" if span_days <= 90 else "1y"
        # Trade Republic only answers 10-minute and hourly candles (other resolutions get no answer at all)
        resolution = 600_000 if interval < 60 else 3_600_000
        payload = {"type": "aggregateHistoryLight", "range": range_, "id": f"{meta['isin']}.{meta['venue']}"}
        try:
            data = await self.market.request({**payload, "resolution": resolution}, timeout=10)
        except TradeRepublicError:
            data = await self.market.request(payload)
        raw = [
            Candle(int(a["time"]), dec(a.get("open")), dec(a.get("high")), dec(a.get("low")), dec(a.get("close")))
            for a in (data or {}).get("aggregates") or [] if a.get("close") is not None
        ]
        candles = [c for c in _rebucket(raw, interval) if c.start <= until]
        # keep the last candle before the window: outside trading hours "the price 24 h ago" is the last close
        first = next((i for i, c in enumerate(candles) if c.start >= since), len(candles))
        return candles[max(first - 1, 0):]

    # --- account --------------------------------------------------------------

    async def _account_request(self, payload: dict, **kwargs: Any) -> Any:
        await self.session.ensure_fresh()
        try:
            return await self.account.request(payload, **kwargs)
        except TradeRepublicError as exc:
            if exc.status != 401:
                raise
            # the socket was opened with an older session: renew it and try once more
            self.session.refreshed_at = 0
            await self.session.ensure_fresh()
            return await self.account.request(payload, **kwargs)

    async def balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        if self._balances is not None and time.monotonic() - self._balances_at < self.BALANCES_TTL:
            return self._balances
        if not self.session.account.get("securitiesAccountNumber"):
            await self.session.load_account()  # missed at the login – without it there is no portfolio
        available = await self._account_request({"type": "availableCash"})
        cash = await self._account_request({"type": "cash"})
        portfolio = await self._account_request(
            {"type": "compactPortfolioByType", "secAccNo": self.session.account.get("securitiesAccountNumber")})
        result: dict[str, tuple[Decimal, Decimal]] = {}

        def cash_by_currency(rows: Any) -> dict[str, Decimal]:
            return {r.get("currencyId") or "EUR": dec(r.get("amount")) for r in rows or [] if isinstance(r, dict)}

        totals = cash_by_currency(cash)
        for currency, amount in cash_by_currency(available).items():
            result[currency] = (amount, max(totals.get(currency, amount), amount))
        for category in (portfolio or {}).get("categories") or []:
            for p in category.get("positions") or []:
                if p.get("isin"):
                    size = dec(p.get("netSize"))
                    held = result.get(p["isin"], (D0, D0))
                    result[p["isin"]] = (held[0] + size, held[1] + size)
        self._balances, self._balances_at = result, time.monotonic()
        return result

    async def place_market_order(self, symbol, side, *, client_order_id, base_size=None, quote_size=None) -> str:
        if not self.session.logged_in:
            raise Problem("tr.login_required")
        try:
            # everything that can fail before the order leaves the agent – such a failure means "not sent"
            meta = await self.resolve(symbol)
            ticker = await self.ticker(symbol)
            await self.session.ensure_fresh()
            await self.account.connect()
        except (TradeRepublicError, httpx.HTTPError) as exc:
            raise Problem("tr.unreachable", error=getattr(exc, "message", str(exc))) from exc
        if not meta.get("tradable", True):
            raise Problem("tr.not_tradable", name=meta.get("name"))
        if closed := self.market_closed(symbol, ticker):
            raise Problem("err.market_closed", reason=closed)
        step, min_size = Decimal(meta["step"]), Decimal(meta["min_size"])
        if side == "buy" and base_size is None:
            size = ((quote_size - FEE) / ticker.ask * BUY_BUFFER / step).to_integral_value(rounding=ROUND_DOWN) * step
        else:
            size = (Decimal(base_size) / step).to_integral_value(rounding=ROUND_DOWN) * step
        if size < min_size or size <= 0:
            raise Problem("tr.order_too_small", qty=float(size), min=float(min_size), name=meta.get("name"))
        parameters = {
            "instrumentId": meta["isin"], "exchangeId": meta["venue"], "expiry": {"type": "gfd"},
            "mode": "market", "size": float(size), "type": side,
            "sellFractions": side == "sell" and size != size.to_integral_value(),
        }
        payload = {
            "type": "simpleCreateOrder", "clientProcessId": client_order_id,
            "warningsShown": ["userExperience"], "acceptedWarnings": ["userExperience"], "parameters": parameters,
        }
        # remembered before it is sent: if the answer gets lost, the order is recognised by these details
        placed = _PlacedOrder(client_order_id, meta["isin"], side, size, step, self.now_ms(),
                              ticker.ask if side == "buy" else ticker.bid)
        self._placed[client_order_id] = placed
        self._save_orders()
        answer = await self.account.request(
            payload, timeout=ORDER_TIMEOUT_S, until=lambda a: str((a or {}).get("status")) in ("succeeded", "failed"))
        if answer.get("status") == "failed":
            self._placed.pop(client_order_id, None)
            self._save_orders()
            error = answer.get("error") or {}
            code = error.get("code") or ""
            if code == "exchangeClosed":
                raise Problem("tr.exchange_closed")
            if code in ("timeoutError", "internalError"):
                # Trade Republic itself doesn't know whether the order went out – look it up
                raise TradeRepublicError(503, answer.get("message") or code)
            raise TradeRepublicError(422, answer.get("message") or error.get("message") or code or "order refused")
        order_id = str(answer.get("orderId") or "")
        if not order_id:
            raise TradeRepublicError(502, f"order without id ({str(answer)[:120]})")
        placed.order_id = order_id
        self._save_orders()
        return order_id

    async def _orders_list(self, terminated: bool) -> list[dict]:
        payload: dict[str, Any] = {"type": "orders"}
        if terminated:
            payload["terminated"] = True
        try:
            data = await self._account_request(payload)
        except TradeRepublicError as exc:
            if terminated and exc.status in (404, 422):
                return []  # no list of finished orders – the timeline has to do
            raise
        return [o for o in (data or {}).get("orders") or [] if isinstance(o, dict)]

    async def get_order(self, order_id: str) -> OrderResult:
        for terminated in (False, True):
            for o in await self._orders_list(terminated):
                if str(o.get("id")) == order_id:
                    return await self._parse_order(o)
        placed = self._placed_by_id(order_id)
        if placed:
            # not (or no longer) in the lists: an executed order shows up in the timeline
            if fill := await self._timeline_fill(placed.isin, placed.side, placed.created_ms, placed.size, placed.step):
                size, amount, fee = fill
                return OrderResult(order_id, "filled", size, amount, amount / size, fee, "EUR")
            if self.now_ms() - placed.created_ms < (self.order_lookup_grace_ms or 0) - 60_000:
                return OrderResult(order_id, "new", D0, D0, D0, D0, "EUR")  # the lists lag behind
        raise TradeRepublicError(404, f"order {order_id} not found")

    async def _parse_order(self, o: dict) -> OrderResult:
        order_id = str(o.get("id"))
        status = str(o.get("status") or "").lower()
        size = dec(o.get("size"))
        executions = [e for e in o.get("executions") or [] if isinstance(e, dict)]

        def first(e: dict, *keys: str) -> Decimal:
            for key in keys:
                value = e.get(key)
                if isinstance(value, dict):
                    value = value.get("value") if "value" in value else value.get("price")
                if value not in (None, ""):
                    return dec(value)
            return D0

        filled = sum((first(e, "size", "executionSize", "quantity") for e in executions), D0)
        amount = sum((first(e, "size", "executionSize", "quantity") * first(e, "price", "executionPrice")
                      for e in executions), D0)
        fees = sum((first(e, "fee", "fees", "executionFees") for e in executions), D0)
        new = OrderResult(order_id, "new", D0, D0, D0, D0, "EUR")
        if status in {"executed", "filled", "done", "completed", "settled"} or (filled and size and filled >= size):
            mapped = "filled"
        elif status in {"cancelled", "canceled", "expired", "deleted"}:
            mapped = "cancelled"
        elif status in {"rejected", "failed", "refused"}:
            mapped = "rejected"
        else:
            return new
        if mapped == "filled" and (not filled or not amount):
            # the order list doesn't tell the execution – the timeline does
            created = int(o.get("createdTime") or 0)
            placed = self._placed_by_id(order_id)
            step = placed.step if placed else Decimal("0.000001")
            fill = await self._timeline_fill(str(o.get("instrumentId") or ""), str(o.get("type") or ""), created,
                                             size or None, step)
            if fill:
                filled, amount, fees = fill
            elif self.now_ms() - created < TIMELINE_WAIT_MS:
                return new  # executed, but the timeline isn't there yet – read again on the next tick
            else:
                # never book without a price: the quote when it was sent, else the current one
                price = placed.price_hint if placed else D0
                if not price and o.get("instrumentId"):
                    with contextlib.suppress(Exception):
                        t = await self.ticker(f"{o['instrumentId']}-EUR")
                        price = t.ask if o.get("type") == "buy" else t.bid
                if not price:
                    return new
                filled = filled or size
                amount = filled * price
                log.warning("Trade Republic order %s: execution price unknown – booked at the quote %s", order_id, price)
        if mapped != "filled" and not filled:
            return OrderResult(order_id, mapped, D0, D0, D0, D0, "EUR", reject_reason=o.get("rejectReason") or status)
        if not filled or not amount:
            return new
        return OrderResult(order_id, "filled", filled, amount, amount / filled, fees or FEE, "EUR")

    async def _timeline_fill(self, isin: str, side: str, created_ms: int, size: Decimal | None = None,
                             step: Decimal = Decimal("0.000001")) -> tuple[Decimal, Decimal, Decimal] | None:
        """(size, amount, fee) of an executed order from the timeline: matched by ISIN, side, time and size."""
        side_words = ("kauf", "buy") if side == "buy" else ("verkauf", "sell")
        try:
            data = await self._account_request({"type": "timelineTransactions"})
        except (TradeRepublicError, Problem) as exc:
            log.warning("Trade Republic timeline not available: %s", exc)
            return None
        for item in (data or {}).get("items") or []:
            if isin and isin not in str(item.get("icon") or "") + str(item.get("action") or ""):
                continue
            subtitle = str(item.get("subtitle") or "").lower()
            if not any(w in subtitle for w in side_words) or ("verkauf" in subtitle and side == "buy"):
                continue
            try:
                stamp = int(datetime.strptime(str(item.get("timestamp")), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp() * 1000)
            except ValueError:
                stamp = 0
            if not stamp or (created_ms and stamp < created_ms - 60_000):
                continue
            try:
                detail = await self._account_request({"type": "timelineDetailV2", "id": item.get("id")})
            except (TradeRepublicError, Problem):
                continue
            fill = self._parse_timeline_detail(detail)
            if fill and (size is None or abs(fill[0] - size) <= step * 2):
                return fill
        return None

    @staticmethod
    def _parse_timeline_detail(detail: dict) -> tuple[Decimal, Decimal, Decimal] | None:
        size = price = None
        fee = FEE
        for section in (detail or {}).get("sections") or []:
            for row in section.get("data") or []:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").lower()
                text = str((row.get("detail") or {}).get("text") or "")
                if title in {"transaktion", "transaction"} and "×" in text:
                    qty_text, _, price_text = text.partition("×")
                    size, price = _german_number(qty_text), _german_number(price_text)
                elif title in {"anteile", "aktien", "shares"} and size is None:
                    size = _german_number(text)
                elif title in {"aktienkurs", "kurs", "share price", "price"} and price is None:
                    price = _german_number(text)
                elif title in {"gebühr", "fee"}:
                    fee = abs(_german_number(text) or FEE)
        if size and price:
            return size, size * price, fee
        return None

    async def find_order(self, symbol: str, client_order_id: str, since: int) -> OrderResult | None:
        return await self.find_lost_order(symbol, {"client_order_id": client_order_id, "placed_at": since + 60_000})

    async def find_lost_order(self, symbol: str, pending: dict) -> OrderResult | None:
        """The order whose answer got lost. Only an unambiguous match counts: same instrument, side and size, sent
        after the order and not booked yet – otherwise nothing is guessed (the engine stops the bot after a while
        so a human can check)."""
        client_id = pending["client_order_id"]
        placed = self._placed.get(client_id)
        if placed and placed.order_id:
            return await self.get_order(placed.order_id)
        if placed is None:
            return None  # never left the agent: it is remembered before it is sent
        known = {p.order_id for p in self._placed.values() if p.order_id}
        candidates: dict[str, dict] = {}
        for terminated in (False, True):
            for o in await self._orders_list(terminated):
                order_id = str(o.get("id") or "")
                if o.get("clientProcessId") == client_id:
                    candidates = {order_id: o}
                    break
                if (o.get("instrumentId") != placed.isin or o.get("type") != placed.side
                        or int(o.get("createdTime") or 0) < placed.created_ms - 60_000
                        or order_id in known or (self.db is not None and self.db.trade_exists(order_id))
                        or abs(dec(o.get("size")) - placed.size) > placed.step * 2):
                    continue
                candidates[order_id] = o
            else:
                continue
            break
        if len(candidates) != 1:
            if candidates:
                log.warning("Trade Republic: %d orders fit the lost order %s – not guessing", len(candidates), client_id)
            return None
        order_id, order = next(iter(candidates.items()))
        placed.order_id = order_id
        self._save_orders()
        return await self._parse_order(order)

    def paper_buy(self, pair: PairInfo, amount: Decimal, fee: Decimal, price: Decimal) -> tuple[Decimal, Decimal]:
        """Like a real buy: fractions down to the instrument's step (whole shares where there are no fractions)."""
        qty = ((amount - fee) / price / pair.base_step).to_integral_value(rounding=ROUND_DOWN) * pair.base_step
        return qty, (qty * price + fee if qty else amount)

    async def close(self) -> None:
        await self.market.close()
        await self.account.close()


class MockTradeRepublicExchange(MockExchange):
    """The demo market (EXCHANGE=mock) for the Trade Republic tab: the default instruments with simulated prices,
    1 € per order and the real trading hours – stocks and ETFs pause at night and on weekends."""

    name = "mock"
    broker = TRADEREPUBLIC
    partial_fills = False
    live_fees = Fees(0.0, float(FEE))

    def __init__(self, speed: float = 1.0):
        super().__init__(Decimal(0), speed)
        self._balances = {"EUR": Decimal(5000)}

    def _price(self, symbol: str, t_ms: float) -> float:
        base = DEFAULT_INSTRUMENTS.get(symbol.partition("-")[0], {}).get("price", 100.0)
        return super()._price(symbol, t_ms) / 100.0 * base  # the mock market's waves around the instrument's price

    def instrument(self, symbol: str) -> dict:
        isin = symbol.partition("-")[0]
        known = DEFAULT_INSTRUMENTS.get(isin, {})
        return {"name": known.get("name", isin), "short": known.get("short"), "type": known.get("type"), "isin": isin}

    def market_closed(self, symbol: str, ticker: Ticker) -> dict | None:
        return market_closed_at(default_meta(symbol.partition("-")[0]), self.now_ms())

    async def pairs(self) -> dict[str, PairInfo]:
        return {
            f"{isin}-EUR": PairInfo(f"{isin}-EUR", isin, "EUR", Decimal("0.000001"), Decimal("0.01"),
                                    Decimal("0.000001"), Decimal("2"))
            for isin in DEFAULT_INSTRUMENTS
        }

    async def search(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        return [{"symbol": f"{isin}-EUR", **self.instrument(f"{isin}-EUR")} for isin, i in DEFAULT_INSTRUMENTS.items()
                if q in i["name"].lower() or q in isin.lower() or q in (i.get("short") or "").lower()]

    def paper_buy(self, pair: PairInfo, amount: Decimal, fee: Decimal, price: Decimal) -> tuple[Decimal, Decimal]:
        qty = ((amount - fee) / price / pair.base_step).to_integral_value(rounding=ROUND_DOWN) * pair.base_step
        return qty, (qty * price + fee if qty else amount)

    async def place_market_order(self, symbol, side, *, client_order_id, base_size=None, quote_size=None) -> str:
        if closed := self.market_closed(symbol, await self.ticker(symbol)):
            raise Problem("err.market_closed", reason=closed)
        if client_order_id in self._client_ids:
            return self._client_ids[client_order_id]
        isin = symbol.partition("-")[0]
        t = await self.ticker(symbol)
        if side == "buy":
            qty = ((quote_size - FEE) / t.ask / Decimal("0.000001")).to_integral_value(rounding=ROUND_DOWN) * Decimal("0.000001")
            cost = qty * t.ask + FEE
            if self._balances.get("EUR", D0) < cost:
                raise Problem("err.not_enough", currency="EUR")
            self._balances["EUR"] -= cost
            self._balances[isin] = self._balances.get(isin, D0) + qty
            amount, price = qty * t.ask, t.ask
        else:
            qty = Decimal(base_size)
            if self._balances.get(isin, D0) < qty:
                raise Problem("err.not_enough", currency=isin)
            amount, price = qty * t.bid, t.bid
            self._balances[isin] -= qty
            self._balances["EUR"] = self._balances.get("EUR", D0) + amount - FEE
        order_id = str(uuid.uuid4())
        self._orders[order_id] = OrderResult(order_id, "filled", qty, amount, price, FEE, "EUR")
        self._client_ids[client_order_id] = order_id
        return order_id


__all__ = [
    "DEFAULT_INSTRUMENTS", "MockTradeRepublicExchange", "TRSocket", "TradeRepublicError", "TradeRepublicExchange",
    "TradeRepublicSession", "apply_delta", "market_closed_at", "normalize_phone",
]
