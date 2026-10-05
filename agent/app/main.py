"""DipAgentX – REST API for the macOS app plus the always-on bot engine.

Every response is rendered in the language of the request (``Accept-Language``: German or English).
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from datetime import datetime
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import backup
from .config import load_settings
from .credentials import CredentialStore
from .db import Database, scoped
from .engine import Engine, broker_of
from .exchange import (
    BROKER_TITLES, BROKERS, REVOLUTX, TRADEREPUBLIC, Exchange, MockExchange, RevolutXExchange, UnconfiguredExchange,
)
from .i18n import Problem, as_message, lang_from_header, m, render, text
from .revolutx import RevolutXClient, RevolutXError
from .strategies import STRATEGIES, has_position, open_positions
from .strategies.ai import AiStrategy
from .traderepublic import MockTradeRepublicExchange, TradeRepublicExchange, TradeRepublicSession

VERSION = "1.27.0"
# the app polls balances every few seconds – don't turn every poll into an exchange request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dipagentx")

settings = load_settings()
db = Database(settings.db_path)


def build_exchange() -> Exchange:
    """The Revolut X slot: the real exchange once it is set up – or the demo market."""
    if settings.exchange == "mock":
        log.warning("Demo mode: simulated market (EXCHANGE=mock)")
        return MockExchange(settings.taker_fee, settings.mock_speed)
    store = CredentialStore(settings)
    active = store.active()
    if active is None:
        return UnconfiguredExchange(store.missing_reason())
    api_key, private_pem = active
    return RevolutXExchange(RevolutXClient(api_key, private_pem, settings.revx_base_url))


def build_traderepublic() -> Exchange:
    """The Trade Republic slot. Prices work without a login (paper trading); the account needs one."""
    if settings.exchange == "mock":
        return MockTradeRepublicExchange(settings.mock_speed)
    return TradeRepublicExchange(tr_session, db)


def swap_exchange(new: Exchange) -> None:
    """Switch the engine to new credentials without restarting the container."""
    engine.replace_exchange(new)


def tr_live_positions() -> bool:
    return any(broker_of(b) == TRADEREPUBLIC and any(not p.paper for p in open_positions(b["state"])) for b in db.list_bots())


def tr_needs_account() -> bool:
    """The daily Trade Republic login is only started on its own while the account is needed."""
    return engine.broker_enabled(TRADEREPUBLIC) and (engine.live_trading_enabled(TRADEREPUBLIC) or tr_live_positions())


credentials = CredentialStore(settings)
tr_session = TradeRepublicSession(settings.data_dir, settings.tr_app_version or None, needs_account=lambda: tr_needs_account())
engine = Engine(db, {REVOLUTX: build_exchange(), TRADEREPUBLIC: build_traderepublic()}, settings)
_exchange_on_login = tr_session.on_login


def _tr_logged_in() -> None:
    if _exchange_on_login:
        _exchange_on_login()
    db.add_event(None, "info", m("event.tr_logged_in"))
    engine.wake()


tr_session.on_login = _tr_logged_in


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(engine.run())
    upkeep = asyncio.create_task(tr_session.maintain()) if settings.exchange != "mock" else None
    for broker in BROKERS:
        if not engine.live_trading_enabled(broker):
            log.warning("Live trading on %s is off – its bots trade simulated (paper trading)", BROKER_TITLES[broker])
    yield
    if upkeep:
        upkeep.cancel()
    # let a tick that is tracking an order finish (its pending order is persisted either way)
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=10)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    await engine.shutdown()
    await tr_session.close()
    db.close()


app = FastAPI(title="DipAgentX", version=VERSION, lifespan=lifespan)
_bearer = HTTPBearer(auto_error=False)


def get_lang(accept_language: str | None = Header(default=None)) -> str:
    return lang_from_header(accept_language)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), lang: str = Depends(get_lang)
) -> None:
    if creds is None or not secrets.compare_digest(creds.credentials.encode(), settings.api_token.encode()):
        raise HTTPException(status_code=401, detail=text("api.invalid_token", lang))


def fail(status: int, lang: str, key: str, **args: Any) -> HTTPException:
    return HTTPException(status, text(key, lang, **args))


def fail_with(status: int, lang: str, exc: BaseException) -> HTTPException:
    return HTTPException(status, render(as_message(exc), lang))


api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# --- request bodies -----------------------------------------------------------------------


class LiveTradingIn(BaseModel):
    enabled: bool
    confirm: str | None = None  # must be "LIVE" to switch on – the app asks twice before sending it
    exchange: str | None = None  # the broker to switch (older apps: Revolut X)


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=16, max_length=256)


class LimitsIn(BaseModel):
    max_open_positions: int = Field(ge=0, le=100)
    max_total_invested: float = Field(ge=0)
    one_position_per_symbol: bool


class PaperFeesIn(BaseModel):
    buy: float = Field(ge=0, le=0.1)  # fraction: 0.0009 = 0.09 %
    sell: float = Field(ge=0, le=0.1)
    fixed: float | None = Field(default=None, ge=0, le=50)  # per order in the quote currency; None = keep


class BotIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    strategy: str
    symbol: str = Field(min_length=3, max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    paper: bool = True
    exchange: str | None = None  # the broker the bot trades on (new bots: Revolut X; updates: the bot's own)


# --- helpers ------------------------------------------------------------------------------


def _broker(exchange: str | None, lang: str) -> str:
    broker = (exchange or REVOLUTX).strip().lower()
    if broker not in BROKERS:
        raise fail(422, lang, "api.unknown_exchange", exchange=exchange)
    return broker


def _scope(exchange: str | None, lang: str) -> str | None:
    """Lists of bots and trades: one broker, or "all". Without the parameter (apps before 1.20) only Revolut X –
    those apps don't know other brokers."""
    if exchange and exchange.strip().lower() == "all":
        return None
    return _broker(exchange, lang)


def _require_enabled(broker: str, lang: str) -> None:
    if not engine.broker_enabled(broker):
        raise fail(409, lang, "api.broker_disabled", broker=BROKER_TITLES[broker])


async def _validate(body: BotIn, lang: str, broker: str) -> tuple[str, dict[str, Any]]:
    strategy = STRATEGIES.get(body.strategy)
    if strategy is None:
        raise fail(422, lang, "api.unknown_strategy", strategy=body.strategy)
    exchange = engine.exchange_for(broker)
    symbol = body.symbol.strip().upper().replace("/", "-")
    if broker == TRADEREPUBLIC:
        symbol = f"{symbol.partition('-')[0]}-EUR"  # Trade Republic: an ISIN, traded in euros
    try:
        # Trade Republic knows far more instruments than it lists – an unknown ISIN is looked up
        known = symbol in await exchange.pairs() or bool(await exchange.pair(symbol))
    except Problem as exc:
        if exc.msg["k"] in {"err.unknown_pair", "tr.unknown_instrument"}:
            known = False
        else:
            known = True  # exchange offline or not connected: accept, the engine will report problems
    except Exception:  # noqa: BLE001
        known = True
    if not known:
        raise fail(422, lang, "api.pair_unavailable_on", symbol=symbol, broker=BROKER_TITLES[broker])
    return symbol, strategy.normalize(body.params)


def _bot_or_404(bot_id: int, lang: str) -> dict[str, Any]:
    bot = db.get_bot(bot_id)
    if bot is None:
        raise fail(404, lang, "api.bot_not_found")
    return bot


def _describe(bot_id: int, lang: str) -> dict[str, Any]:
    return engine.describe_bot(_bot_or_404(bot_id, lang), db.trade_stats(), lang)


def _account_missing(broker: str) -> dict | None:
    """Why the broker's account can't be used for live trading right now (None: it can)."""
    exchange = engine.exchange_for(broker)
    if reason := getattr(exchange, "reason", None):
        return reason
    if isinstance(exchange, TradeRepublicExchange) and not tr_session.logged_in:
        return m("tr.login_required")
    return None


def _exchange_status(broker: str, lang: str) -> dict[str, Any]:
    exchange = engine.exchange_for(broker)
    error = getattr(exchange, "reason", None) or engine.exchange_errors.get(broker)
    live_fees = engine.fees(broker, paper=False)
    return {
        "id": broker,
        "title": BROKER_TITLES[broker],
        "simulated": settings.exchange == "mock",
        "configured": _account_missing(broker) is None,
        "ok": error is None,
        "error": render(error, lang) if error else None,
        "live_trading_allowed": engine.live_trading_enabled(broker),
        "enabled": engine.broker_enabled(broker),
        "fees": {"rate": live_fees.rate, "fixed": live_fees.fixed},
    }


def _status(lang: str) -> dict[str, Any]:
    error = getattr(engine.exchange, "reason", None) or engine.exchange_error
    return {
        "version": VERSION,
        # Revolut X, as before the second broker – "exchanges" has every broker
        "exchange": engine.exchange.name,
        "exchange_ok": error is None,
        "exchange_error": render(error, lang) if error else None,
        "engine_error": render(engine.instance_error, lang) if engine.instance_error else None,
        "live_trading_allowed": engine.live_trading_enabled(),
        "last_tick": engine.last_tick,
        "tick_seconds": settings.tick_seconds,
        "taker_fee": float(settings.taker_fee),
        "ai_configured": AiStrategy.configured(),
        "exchanges": [_exchange_status(broker, lang) for broker in BROKERS],
    }


# --- general --------------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": VERSION}


@api.get("/status")
async def status(lang: str = Depends(get_lang)) -> dict[str, Any]:
    return _status(lang)


@api.get("/summary")
async def summary(exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    return engine.summary(_broker(exchange, lang))


# --- Revolut X setup from the app ------------------------------------------------------------


def _exchange_info(lang: str) -> dict[str, Any]:
    error = getattr(engine.exchange, "reason", None) or engine.exchange_error
    return {
        **credentials.describe(),
        "mode": settings.exchange,
        "connected": settings.exchange == "revolutx" and credentials.source != "none" and error is None,
        "error": render(error, lang) if error else None,
        "api_keys_url": "https://exchange.revolut.com/account/api-keys",
    }


def _require_app_setup(lang: str) -> None:
    if settings.exchange == "mock":
        raise fail(409, lang, "api.demo_mode")
    if credentials.source == "env":
        raise fail(409, lang, "api.env_configured")


@api.get("/exchange")
async def exchange_info(lang: str = Depends(get_lang)) -> dict[str, Any]:
    return _exchange_info(lang)


@api.post("/exchange/keypair")
async def generate_keypair(lang: str = Depends(get_lang)) -> dict[str, Any]:
    _require_app_setup(lang)
    credentials.generate_pending()
    db.add_event(None, "info", m("event.keypair"))
    return _exchange_info(lang)


@api.put("/exchange/credentials")
async def save_credentials(body: ApiKeyIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    _require_app_setup(lang)
    api_key = body.api_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", api_key):
        raise fail(422, lang, "api.api_key_chars")
    private_pem = credentials.signing_key_for_new_api_key()
    if private_pem is None:
        raise fail(409, lang, "api.keypair_first")

    client = RevolutXClient(api_key, private_pem, settings.revx_base_url)
    try:
        await client.balances()  # proves that API key + private key + IP whitelist fit together
    except RevolutXError as exc:
        await client.close()
        key = "api.key_rejected_hint" if exc.status in (401, 403) else "api.key_rejected"
        raise fail(422, lang, key, error=exc.message) from exc
    except httpx.HTTPError as exc:
        await client.close()
        raise fail(502, lang, "api.revx_unreachable", error=str(exc)) from exc

    credentials.save(api_key, private_pem)
    swap_exchange(RevolutXExchange(client))
    db.add_event(None, "info", m("event.revx_connected"))
    return _exchange_info(lang)


@api.delete("/exchange/credentials")
async def delete_credentials(lang: str = Depends(get_lang)) -> dict[str, Any]:
    _require_app_setup(lang)
    credentials.clear()
    if engine.live_trading_enabled():
        db.set_setting("live_trading", False)
        db.add_event(None, "info", m("event.live_off_access_removed"))
    swap_exchange(UnconfiguredExchange(credentials.missing_reason()))
    db.add_event(None, "info", m("event.revx_removed"))
    return _exchange_info(lang)


@api.get("/exchange/public-ip")
async def public_ip(lang: str = Depends(get_lang)) -> dict[str, Any]:
    """The agent's public IP – Revolut X can restrict API keys to whitelisted IPs."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            ip = (await client.get("https://api.ipify.org", params={"format": "json"})).json()["ip"]
    except Exception as exc:  # noqa: BLE001
        raise fail(502, lang, "api.public_ip_failed", error=str(exc)) from exc
    return {"ip": ip}


# --- Trade Republic login from the app ---------------------------------------------------------


class TrLoginIn(BaseModel):
    phone: str | None = Field(default=None, max_length=32)  # None: the saved phone number and PIN (daily login)
    pin: str | None = Field(default=None, max_length=8)
    remember_pin: bool = True


class TrCodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


def _tr_info(lang: str) -> dict[str, Any]:
    info = tr_session.describe()
    error = info.pop("error")
    market_error = engine.exchange_errors.get(TRADEREPUBLIC)
    return {
        **info,
        "mode": settings.exchange,
        "connected": True if settings.exchange == "mock" else info["connected"],
        "error": render(error, lang) if error else None,
        "market_error": render(market_error, lang) if market_error else None,
    }


def _require_real_tr(lang: str) -> None:
    if settings.exchange == "mock":
        raise fail(409, lang, "api.demo_mode")


@api.get("/traderepublic")
async def traderepublic_info(lang: str = Depends(get_lang)) -> dict[str, Any]:
    return _tr_info(lang)


@api.post("/traderepublic/login")
async def traderepublic_login(body: TrLoginIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Start the login: Trade Republic then asks for the confirmation in its app (or for an authenticator code)."""
    _require_real_tr(lang)
    try:
        await tr_session.start_login(body.phone, body.pin, body.remember_pin)
    except Problem as exc:
        raise fail_with(422, lang, exc) from exc
    tr_session.auto_attempts = 0  # the user is there – the automatic logins may try again later
    return _tr_info(lang)


@api.post("/traderepublic/login/code")
async def traderepublic_code(body: TrCodeIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    _require_real_tr(lang)
    try:
        await tr_session.submit_code(body.code)
    except Problem as exc:
        raise fail_with(422, lang, exc) from exc
    return _tr_info(lang)


@api.delete("/traderepublic/login")
async def traderepublic_cancel(lang: str = Depends(get_lang)) -> dict[str, Any]:
    await tr_session.cancel_login()
    return _tr_info(lang)


@api.delete("/traderepublic")
async def traderepublic_logout(force: bool = False, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Log out and forget phone number and PIN. Live trading on Trade Republic is switched off."""
    _require_real_tr(lang)
    if tr_live_positions() and not force:
        # without a login they could not be sold any more – not even by the stop-loss
        raise fail(409, lang, "api.tr_logout_open_trades")
    await tr_session.logout(forget=True)
    if engine.live_trading_enabled(TRADEREPUBLIC):
        db.set_setting(scoped("live_trading", TRADEREPUBLIC), False)
        db.add_event(None, "info", m("event.live_off_tr_logout"))
    db.add_event(None, "info", m("event.tr_logged_out"))
    return _tr_info(lang)


# --- brokers on/off ----------------------------------------------------------------------------


class BrokerIn(BaseModel):
    enabled: bool


@api.put("/brokers/{broker}")
async def set_broker(broker: str, body: BrokerIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Switch a broker off (its bots stop, no prices, no login) or on again. The apps hide the tabs while only one
    broker is on."""
    broker = _broker(broker, lang)
    title = BROKER_TITLES[broker]
    disabled = set(db.get_setting("brokers_disabled") or [])
    if not body.enabled and broker not in disabled:
        if all(b == broker or b in disabled for b in BROKERS):
            raise fail(409, lang, "api.last_broker")
        if any(broker_of(b) == broker and (has_position(b["state"]) or b["state"].get("pending_order")) for b in db.list_bots()):
            raise fail(409, lang, "api.broker_busy", broker=title)
        disabled.add(broker)
        db.set_setting("brokers_disabled", sorted(disabled))
        if engine.live_trading_enabled(broker):
            db.set_setting(scoped("live_trading", broker), False)
        for bot in db.list_bots():
            if broker_of(bot) == broker and bot["enabled"]:
                db.update_bot(bot["id"], enabled=False, status=m("status.broker_disabled", broker=title))
        if broker == TRADEREPUBLIC:
            await tr_session.cancel_login()
        db.add_event(None, "info", m("event.broker_disabled", broker=title))
    elif body.enabled and broker in disabled:
        disabled.discard(broker)
        db.set_setting("brokers_disabled", sorted(disabled))
        db.add_event(None, "info", m("event.broker_enabled", broker=title))
    engine.wake()
    return _status(lang)


# --- trading mode ------------------------------------------------------------------------------


@api.put("/live-trading")
async def set_live_trading(body: LiveTradingIn, exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    broker = _broker(body.exchange or exchange, lang)
    title = BROKER_TITLES[broker]
    if body.enabled:
        if settings.exchange != "revolutx":
            raise fail(409, lang, "api.no_live_in_demo")
        if _account_missing(broker) is not None:
            raise fail(409, lang, "api.connect_broker_first", broker=title)
        if body.confirm != "LIVE":
            raise fail(422, lang, "api.confirm_live")
        try:
            await engine.exchange_for(broker).balances()  # only switch on with a working connection
        except Exception as exc:  # noqa: BLE001
            raise fail(502, lang, "api.broker_unreachable_live", broker=title, error=as_message(exc)) from exc

    closed: list[dict[str, Any]] = []
    if body.enabled != engine.live_trading_enabled(broker):
        db.set_setting(scoped("live_trading", broker), body.enabled)  # first: no new live buys from here on
        db.add_event(None, "info", m("event.broker_live_on" if body.enabled else "event.broker_live_off", broker=title))
        if body.enabled:
            # the app told the user: all of the broker's bots go live (bots that shouldn't must be deleted
            # beforehand). Open paper positions keep being simulated until they are sold – see Engine._buy/_sell.
            for bot in db.list_bots():
                if bot["paper"] and broker_of(bot) == broker:
                    db.update_bot(bot["id"], paper=False)
                    db.add_event(bot["id"], "info", m("event.bot_live"))
        log.warning("Live trading on %s %s", title, "ENABLED" if body.enabled else "disabled")
    if not body.enabled:
        # back to paper mode: the app warned that all open live positions are sold right away
        closed = await engine.close_live_positions(m("engine.live_ended"), broker)
        for result in closed:
            result["message"] = render(result["message"], lang)
    engine.wake()
    return {**_status(lang), "closed_positions": closed}


# --- paper-mode fees -------------------------------------------------------------------------


@api.get("/paper-fees")
async def get_paper_fees(exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, float]:
    return engine.paper_fees(_broker(exchange, lang))


@api.put("/paper-fees")
async def put_paper_fees(body: PaperFeesIn, exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, float]:
    broker = _broker(exchange, lang)
    fees = body.model_dump()
    if fees["fixed"] is None:  # older apps only know the two rates
        fees["fixed"] = engine.paper_fees(broker).get("fixed", 0.0)
    async with engine.paused():  # trades and open positions are rebooked – no tick may write meanwhile
        db.set_paper_fees(fees, broker)
        engine.apply_paper_fees(broker)
        engine.reset_caches()
    db.add_event(None, "info", m("event.paper_fees_changed_on", broker=BROKER_TITLES[broker]))
    engine.wake()
    return engine.paper_fees(broker)


# --- limits ----------------------------------------------------------------------------------


@api.get("/limits")
async def get_limits(exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    broker = _broker(exchange, lang)
    count, invested, _ = engine.exposure(broker=broker)
    return {**db.get_limits(broker), "open_positions": count, "invested": float(invested)}


@api.put("/limits")
async def put_limits(body: LimitsIn, exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    broker = _broker(exchange, lang)
    db.set_limits(body.model_dump(), broker)
    db.add_event(None, "info", m("event.limits_changed_on", broker=BROKER_TITLES[broker]))
    engine.wake()
    return await get_limits(broker, lang)


# --- market data -----------------------------------------------------------------------------


@api.get("/strategies")
async def strategies(lang: str = Depends(get_lang)) -> list[dict[str, Any]]:
    return [s.to_json(lang) for s in STRATEGIES.values()]


@api.get("/pairs")
async def pairs(exchange: str | None = None, lang: str = Depends(get_lang)) -> list[str]:
    try:
        return sorted(await engine.exchange_for(_broker(exchange, lang)).pairs())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise fail_with(502, lang, exc) from exc


@api.get("/instruments")
async def instruments(exchange: str | None = None, q: str = "", lang: str = Depends(get_lang)) -> list[dict[str, Any]]:
    """What can be traded, with names: the known instruments – or, with ``q``, a search (Trade Republic lists far
    more than it can show at once; Revolut X filters its pairs)."""
    broker = _broker(exchange, lang)
    ex = engine.exchange_for(broker)
    try:
        if q.strip() and hasattr(ex, "search"):
            return await ex.search(q.strip())
        query = q.strip().upper()
        return [{"symbol": symbol, **ex.instrument(symbol)} for symbol in sorted(await ex.pairs())
                if not query or query in symbol or query in str(ex.instrument(symbol).get("name", "")).upper()]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise fail_with(502, lang, exc) from exc


@api.get("/balances")
async def balances(exchange: str | None = None, lang: str = Depends(get_lang)) -> list[dict[str, Any]]:
    ex = engine.exchange_for(_broker(exchange, lang))
    try:
        data = await ex.balances()  # cached by the exchange for a minute, dropped after own orders
    except Exception as exc:  # noqa: BLE001
        raise fail_with(502, lang, exc) from exc
    rows = []
    for c, (a, t) in sorted(data.items()):
        if t > Decimal(0):
            # Trade Republic holds its positions under the ISIN – the app shows the ticker
            name = ex.instrument(f"{c}-EUR").get("short") if len(c) == 12 else None
            rows.append({"currency": name or c, "available": float(a), "total": float(t)})
    return rows


# --- bots ------------------------------------------------------------------------------------


@api.get("/bots")
async def list_bots(exchange: str | None = None, lang: str = Depends(get_lang)) -> list[dict[str, Any]]:
    scope = _scope(exchange, lang)
    stats = db.trade_stats()
    return [engine.describe_bot(b, stats, lang) for b in db.list_bots() if scope is None or broker_of(b) == scope]


@api.post("/bots", status_code=201)
async def create_bot(body: BotIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    broker = _broker(body.exchange, lang)
    _require_enabled(broker, lang)
    symbol, params = await _validate(body, lang, broker)
    # a new bot follows its broker's mode – a live bot on a broker that is still in paper mode trades on paper anyway
    bot_id = db.create_bot(body.name.strip(), body.strategy, symbol, params, body.enabled, body.paper, broker)
    db.add_event(bot_id, "info", m("event.bot_created", strategy=m(f"strategy.{body.strategy}"), symbol=symbol))
    engine.wake()
    return _describe(bot_id, lang)


@api.put("/bots/{bot_id}")
async def update_bot(bot_id: int, body: BotIn, lang: str = Depends(get_lang)) -> dict[str, Any]:
    bot = _bot_or_404(bot_id, lang)
    broker = broker_of(bot)
    if body.exchange and _broker(body.exchange, lang) != broker:
        raise fail(409, lang, "api.locked_exchange")  # a bot stays with its broker – create a new one instead
    if body.enabled and not bot["enabled"]:
        _require_enabled(broker, lang)
    symbol, params = await _validate(body, lang, broker)
    # an order in flight is reconciled under the bot's pair – it must not change under it either
    busy = has_position(bot["state"]) or bot["state"].get("pending_order")
    if busy and (symbol != bot["symbol"] or body.strategy != bot["strategy"]):
        raise fail(409, lang, "api.locked_pair_strategy")
    # a strategy holding slices may go from paper to live with paper slices open: the engine closes them (simulated)
    # and starts afresh – never the other way round, and never with an order in flight
    strategy = STRATEGIES.get(body.strategy)
    paper_slices_only = (strategy is not None and strategy.fixed_trades and not body.paper
                         and not bot["state"].get("pending_order")
                         and all(p.paper for p in open_positions(bot["state"])))
    if busy and body.paper != bot["paper"] and not paper_slices_only:
        raise fail(409, lang, "api.locked_mode")
    db.update_bot(
        bot_id, name=body.name.strip(), strategy=body.strategy, symbol=symbol,
        params=params, enabled=body.enabled, paper=body.paper,
    )
    db.add_event(bot_id, "info", m("event.settings_changed"))
    engine.wake()
    return _describe(bot_id, lang)


@api.delete("/bots/{bot_id}", status_code=204, response_class=Response)
async def delete_bot(bot_id: int, force: bool = False, lang: str = Depends(get_lang)) -> Response:
    bot = _bot_or_404(bot_id, lang)
    if (has_position(bot["state"]) or bot["state"].get("pending_order")) and not force:
        raise fail(409, lang, "api.delete_open_position")
    db.delete_bot(bot_id)
    return Response(status_code=204)


@api.post("/bots/{bot_id}/start")
async def start_bot(bot_id: int, lang: str = Depends(get_lang)) -> dict[str, Any]:
    _require_enabled(broker_of(_bot_or_404(bot_id, lang)), lang)
    db.update_bot(bot_id, enabled=True, status=m("status.starting"))
    db.add_event(bot_id, "info", m("event.bot_started"))
    engine.wake()
    return _describe(bot_id, lang)


@api.post("/bots/{bot_id}/stop")
async def stop_bot(bot_id: int, lang: str = Depends(get_lang)) -> dict[str, Any]:
    _bot_or_404(bot_id, lang)
    db.update_bot(bot_id, enabled=False, status=m("status.stopped"))
    db.add_event(bot_id, "info", m("event.bot_stopped"))
    return _describe(bot_id, lang)


@api.post("/bots/{bot_id}/close")
async def close_position(bot_id: int, position_id: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Sell one trade (``position_id``) or all of the bot's trades at market."""
    _bot_or_404(bot_id, lang)
    try:
        await engine.close_position(bot_id, position_id=position_id)
    except Problem as exc:
        raise fail_with(409, lang, exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise fail_with(502, lang, exc) from exc
    return _describe(bot_id, lang)


@api.post("/bots/{bot_id}/discard")
async def discard_position(bot_id: int, position_id: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Remove one trade (or all) from the books without selling (the coins stay on the exchange, unmanaged)."""
    _bot_or_404(bot_id, lang)
    try:
        await engine.discard_position(bot_id, position_id=position_id)
    except Problem as exc:
        raise fail_with(409, lang, exc) from exc
    return _describe(bot_id, lang)


@api.post("/bots/{bot_id}/reset-paper")
async def reset_paper(bot_id: int, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Delete the bot's paper trades and discard its open paper trades – its paper result starts at zero."""
    _bot_or_404(bot_id, lang)
    try:
        await engine.reset_paper(bot_id)
    except Problem as exc:
        raise fail_with(409, lang, exc) from exc
    return _describe(bot_id, lang)


@api.post("/reset-paper")
async def reset_paper_broker(exchange: str | None = None, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Delete all trades of the broker and reset its bots' paper state – everything starts at zero."""
    broker = _broker(exchange, lang)
    try:
        await engine.reset_paper_broker(broker)
    except Problem as exc:
        raise fail_with(409, lang, exc) from exc
    engine.reset_caches()
    return engine.summary(broker)


@api.post("/bots/{bot_id}/ask")
async def ask_claude_now(bot_id: int, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """"AI decides" only: get a fresh decision from Claude right now instead of waiting for the next check."""
    _bot_or_404(bot_id, lang)
    try:
        await engine.ask_now(bot_id)
    except Problem as exc:
        raise fail_with(409, lang, exc) from exc
    return _describe(bot_id, lang)


# --- history ---------------------------------------------------------------------------------


@api.get("/trades")
async def trades(
    bot_id: int | None = None, limit: int = Query(200, ge=1, le=1000), exchange: str | None = None,
    lang: str = Depends(get_lang),
) -> list[dict[str, Any]]:
    rows = db.list_trades(bot_id, limit, None if bot_id is not None else _scope(exchange, lang))
    for r in rows:
        for key in ("price", "base_qty", "quote_amount", "fee"):
            r[key] = float(r[key])
        r["pnl"] = float(r["pnl"]) if r["pnl"] is not None else None
        r["paper"] = bool(r["paper"])
        r["reason"] = render(r["reason"], lang)
        if r["exchange"] != REVOLUTX:  # names instead of ISINs
            instrument = engine.exchange_for(r["exchange"]).instrument(r["symbol"])
            r["base_name"] = instrument.get("short")
            r["display_symbol"] = instrument.get("name")
    return rows


@api.get("/bots/{bot_id}/decisions")
async def ai_decisions(bot_id: int, limit: int = Query(100, ge=1, le=500), lang: str = Depends(get_lang)) -> list[dict[str, Any]]:
    """Claude's answers for an "AI decides" bot, newest first."""
    _bot_or_404(bot_id, lang)
    rows = db.list_ai_decisions(bot_id, limit)
    return [
        {
            "id": r["id"], "action": r["action"], "confidence": r["confidence"],
            "reason": r["reason_de"] if lang == "de" else r["reason_en"],
            "price": float(r["price"]), "profit_pct": r["profit_pct"], "created_at": r["created_at"],
        }
        for r in rows
    ]


@api.get("/events")
async def events(
    bot_id: int | None = None, limit: int = Query(100, ge=1, le=1000), lang: str = Depends(get_lang)
) -> list[dict[str, Any]]:
    rows = db.list_events(bot_id, limit)
    for r in rows:
        r["message"] = render(r["message"], lang)
    return rows


# --- backup ----------------------------------------------------------------------------------


@api.get("/backup")
async def export_backup() -> Response:
    """Bots, trades, settings and the app-managed Revolut X key as a .tgz (the API token is not included)."""
    creds = {name: path.read_bytes() for name, path in credentials.files().items() if path.is_file()}
    data, filename = backup.create(db.snapshot(), creds, {"agent_version": VERSION, "exchange": settings.exchange})
    return Response(
        data, media_type="application/gzip", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@api.post("/restore")
async def restore_backup(request: Request, lang: str = Depends(get_lang)) -> dict[str, Any]:
    """Replace the agent's data with an uploaded backup. Live trading is switched off afterwards, always."""
    body = await request.body()
    try:
        unpacked = backup.unpack(body, settings.data_dir)
    except backup.InvalidBackup as exc:
        raise fail(400, lang, "api.invalid_backup", error=str(exc)) from exc
    try:
        async with engine.paused():  # no tick touches the database while it is swapped
            live_was_on = any(engine.live_trading_enabled(b) for b in BROKERS)
            db.replace_with(unpacked.db_path)
            if unpacked.credentials:
                credentials.save(unpacked.credentials["revx_api_key"].decode().strip(), unpacked.credentials["revx_private.pem"])
            # off in any case: the restored data may have been backed up with live trading on, and the agent
            # it lands on may have been live before – the user re-enables it consciously (double confirmation)
            live_was_on = live_was_on or any(engine.live_trading_enabled(b) for b in BROKERS)
            if live_was_on:
                for broker in BROKERS:
                    db.set_setting(scoped("live_trading", broker), False)
            engine.reset_caches()
            swap_exchange(build_exchange())
            bots, trade_count = db.list_bots(), len(db.list_trades(limit=1000))
            created = unpacked.manifest.get("created_at")
            date = datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d %H:%M") if created else "?"
            db.add_event(None, "info", m("event.restored", date=date, bots=len(bots), trades=trade_count))
            if live_was_on:
                db.add_event(None, "info", m("event.live_off_restored"))
            engine.wake()
    finally:
        unpacked.cleanup()
    log.warning("Backup restored (%d bots, %d trades); live trading is off", len(bots), trade_count)
    return {
        "bots": len(bots),
        "trades": trade_count,
        "live_trading_disabled": live_was_on,
        "credentials_restored": bool(unpacked.credentials),
        "created_at": created,
        "agent_version": unpacked.manifest.get("agent_version"),
    }


app.include_router(api)
