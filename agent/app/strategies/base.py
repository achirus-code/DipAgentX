"""Common building blocks for trading strategies."""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..exchange import FIAT, Candle, Exchange, Fees, Ticker, dec
from ..i18n import L, Problem

CANDLE_INTERVALS = [5, 15, 30, 60, 240, 1440]  # minutes, as supported by Revolut X
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
MAX_CANDLES = 98  # per request – every candle series stays below this


def sell_fee(gross: Decimal, fees: Fees | float, quote: str) -> Decimal:
    """Fee for a sale of ``gross`` (a plain number is a rate without a fixed part)."""
    return (fees if isinstance(fees, Fees) else Fees(float(fees))).of(gross, quote)


@dataclass
class Option:
    value: str
    label: L


@dataclass
class Param:
    key: str
    label: L
    type: str  # number | percent | money | int | bool | select | text
    default: Any
    help: L | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[Option] | None = None
    unit: str | L | None = None  # display unit for plain numbers, e.g. "h" or "min" (L when it needs translating)

    def coerce(self, value: Any) -> Any:
        try:
            if self.type == "text":
                return "" if value is None else str(value).strip()[:2000]
            if self.type == "bool":
                v: Any = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes"}
            elif self.type == "int":
                v = int(float(value))
            elif self.type == "select":
                allowed = {o.value for o in self.options or []}
                v = value if value in allowed else self.default
            else:
                v = float(value)
                if not math.isfinite(v):  # JSON "NaN"/"Infinity" would poison every Decimal comparison
                    return self.default
        except (TypeError, ValueError):
            return self.default
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if self.min is not None:
                v = max(v, type(v)(self.min))
            if self.max is not None:
                v = min(v, type(v)(self.max))
        return v

    def to_json(self, lang: str) -> dict[str, Any]:
        data: dict[str, Any] = {"key": self.key, "label": self.label(lang), "type": self.type, "default": self.default}
        if self.help:
            data["help"] = self.help(lang)
        for name in ("min", "max", "step", "unit"):
            if (value := getattr(self, name)) is not None:
                data[name] = value(lang) if isinstance(value, L) else value
        if self.options:
            data["options"] = [{"value": o.value, "label": o.label(lang)} for o in self.options]
        return data


@dataclass
class Position:
    qty: Decimal
    cost: Decimal  # total quote currency spent incl. fees
    opened_at: int
    peak: Decimal
    buys: int = 1
    paper: bool = True  # bought with simulated or real money – sells always use the same mode
    id: str = ""  # a bot can hold several trades at once – each is sold on its own
    order_id: str | None = None  # the live buy order that opened it (a late fill of that order is added here)
    # the high since a strategy's sell signal armed a trailing stop (dip buyer); None = not armed. Raised like peak.
    trail_peak: Decimal | None = None
    # the instrument held when it is not the bot's own symbol (the monthly trend follower's currency-hedged ETF or
    # the bonds it parks in); None = the bot's symbol
    symbol: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

    @property
    def entry_price(self) -> Decimal:
        return self.cost / self.qty if self.qty else Decimal(0)

    def value(self, price: Decimal) -> Decimal:
        return self.qty * price

    def pnl_pct(self, price: Decimal) -> float:
        if not self.cost:
            return 0.0
        return float((self.value(price) - self.cost) / self.cost * 100)

    def net_proceeds(self, price: Decimal, fees: Fees | float, quote: str) -> Decimal:
        """What selling everything at ``price`` leaves after the exchange fee."""
        gross = self.value(price)
        return gross - sell_fee(gross, fees, quote)

    def break_even_price(self, fees: Fees | float, quote: str) -> Decimal:
        """The price at which a sale just recovers the cost (buy fee included) after the sell fee."""
        if not self.qty:
            return Decimal(0)
        return (self.cost + sell_fee(self.cost, fees, quote)) / self.qty

    def to_state(self) -> dict[str, Any]:
        return {
            "qty": str(self.qty),
            "cost": str(self.cost),
            "opened_at": self.opened_at,
            "peak": str(self.peak),
            "buys": self.buys,
            "paper": self.paper,
            "id": self.id,
            "order_id": self.order_id,
            "trail_peak": str(self.trail_peak) if self.trail_peak is not None else None,
            **({"symbol": self.symbol} if self.symbol else {}),
        }

    @classmethod
    def from_state(cls, raw: dict[str, Any] | None) -> "Position | None":
        if not raw:
            return None
        return cls(
            dec(raw["qty"]), dec(raw["cost"]), int(raw["opened_at"]), dec(raw["peak"]),
            int(raw.get("buys", 1)), bool(raw.get("paper", True)),
            str(raw.get("id") or "p1"), raw.get("order_id"),
            dec(raw["trail_peak"]) if raw.get("trail_peak") else None,
            raw.get("symbol") or None,
        )


def open_positions(state: dict[str, Any]) -> list[Position]:
    """The open trades of a bot, oldest first. Before 1.13 a bot held at most one, stored under "position"."""
    raw = state.get("positions")
    if raw is None and state.get("position"):
        raw = [state["position"]]
    return [p for p in (Position.from_state(r) for r in raw or []) if p]


def store_positions(state: dict[str, Any], positions: list[Position]) -> None:
    state.pop("position", None)
    state["positions"] = [p.to_state() for p in positions]


def has_position(state: dict[str, Any]) -> bool:
    return bool(state.get("positions") or state.get("position"))


def multi_trade_params() -> list[Param]:
    """Several trades at once – each buy is its own trade with its own entry and is sold on its own."""
    return [
        Param("max_trades", L("Max. open trades", "Max. offene Trades"), "int", 1,
              L("How many trades the bot may hold at the same time. Each buy is its own trade with its own entry, "
                "target and stop, and is sold on its own. 1 = one trade at a time.",
                "Wie viele Trades der Bot gleichzeitig halten darf. Jeder Kauf ist ein eigener Trade mit eigenem "
                "Einstieg, Ziel und Stop und wird einzeln verkauft. 1 = immer nur ein Trade."), min=1, max=20),
        Param("trade_spacing", L("Distance between trades", "Abstand zwischen Trades"), "percent", 2.0,
              L("With several trades: another one only when the price is at least this far below the lowest entry "
                "of the open trades – so they don't all buy at the same price.",
                "Bei mehreren Trades: ein weiterer erst, wenn der Kurs mindestens so weit unter dem niedrigsten "
                "Einstieg der offenen Trades liegt – damit nicht alle zum gleichen Kurs kaufen."),
              min=0, max=50, step=0.1),
        Param("trade_interval_days", L("Min. time between trades", "Mindestzeit zwischen Trades"), "number", 0.0,
              L("A new trade only when at least this many days have passed since the last buy – e.g. 1 or 2. "
                "0 = off.",
                "Ein neuer Trade erst, wenn seit dem letzten Kauf mindestens so viele Tage vergangen sind – "
                "z. B. 1 oder 2. 0 = aus."),
              min=0, max=60, step=0.5, unit=L("days", "Tage")),
    ]


Message = dict  # an i18n message, see app.i18n.m()


@dataclass
class Buy:
    quote_amount: Decimal
    reason: Message
    symbol: str | None = None  # another instrument than the bot's own (see Position.symbol)


@dataclass
class Sell:
    reason: Message  # always sells the whole position
    # True for protective sells (stop-loss): they may realize a loss. Every other sell is only executed
    # when it at least recovers the cost after fees – a position is never sold at a loss by a target rule.
    stop: bool = False


@dataclass
class Decision:
    status: Message
    action: Buy | Sell | None = None


CandleFetch = Callable[[str, int, int, int], Awaitable[list[Candle]]]  # (symbol, interval, since, until)
DailyFetch = Callable[[str, int, int], Awaitable[list[Candle]]]  # (symbol, days, now)


async def fetch_daily_candles(fetch: CandleFetch, symbol: str, days: int, now: int,
                              chunk: int = MAX_CANDLES) -> list[Candle]:
    """Daily candles of the last ``days`` completed UTC days, oldest first – fewer when the pair is younger
    (days without trading, like weekends on a stock exchange, have no candle).

    Long windows (a 200-day average) are fetched in chunks of at most ``chunk`` daily candles."""
    today = now - now % DAY_MS
    since = today - days * DAY_MS
    candles: dict[int, Candle] = {}
    start = since
    while start < today:
        end = min(start + chunk * DAY_MS, today)
        for c in await fetch(symbol, 1440, start, end - 1):
            if since <= c.start < today:  # not the forming candle of today
                candles[c.start] = c
        start = end
    return [candles[t] for t in sorted(candles)]


class MarketView:
    """Market data for one symbol during one engine tick (candles fetched lazily and cached).

    ``fetch`` lets the engine plug in a cache that survives ticks; by default candles come from the exchange.
    ``daily`` does the same for the daily candles of long averages (they change once a day).
    """

    def __init__(self, exchange: Exchange, symbol: str, ticker: Ticker, now: int, fetch: CandleFetch | None = None,
                 daily: DailyFetch | None = None):
        self.exchange = exchange
        self.symbol = symbol
        self.ticker = ticker
        self.now = now
        self._fetch = fetch or exchange.candles
        self._daily = daily
        self._cache: dict[tuple[int, float], list[Candle]] = {}
        self._daily_cache: dict[int, list[Candle]] = {}
        # name and type of the instrument (a coin, a stock, an ETF …) and why it can't be traded right now, if so
        self.instrument: dict[str, Any] = exchange.instrument(symbol)
        self.closed: dict | None = exchange.market_closed(symbol, ticker)

    @property
    def price(self) -> Decimal:
        return self.ticker.last or self.ticker.mid

    @property
    def bid(self) -> Decimal:
        return self.ticker.bid or self.price

    @property
    def ask(self) -> Decimal:
        return self.ticker.ask or self.price

    async def candles(self, hours: float) -> tuple[list[Candle], int]:
        minutes = hours * 60
        interval = next((i for i in CANDLE_INTERVALS if minutes / i <= MAX_CANDLES), CANDLE_INTERVALS[-1])
        key = (interval, hours)
        if key not in self._cache:
            since = self.now - int(hours * HOUR_MS) - interval * 60_000
            self._cache[key] = await self._fetch(self.symbol, interval, since, self.now)
        return self._cache[key], interval

    async def price_at(self, hours_ago: float) -> Decimal:
        candles, interval = await self.candles(hours_ago)
        if not candles:
            raise Problem("err.no_ticker", symbol=self.symbol)
        t0 = self.now - int(hours_ago * HOUR_MS)
        before = [c for c in candles if c.start <= t0]
        if not before:
            return candles[0].open
        c = before[-1]
        return c.close if (t0 - c.start) > interval * 30_000 else c.open

    async def change_pct(self, hours: float) -> float:
        ref = await self.price_at(hours)
        return float((self.price / ref - 1) * 100) if ref else 0.0

    async def high(self, hours: float) -> Decimal:
        candles, _ = await self.candles(hours)
        return max([c.high for c in candles] + [self.price])

    async def low(self, hours: float) -> Decimal:
        candles, _ = await self.candles(hours)
        return min([c.low for c in candles] + [self.price])

    async def daily_candles(self, days: int) -> list[Candle]:
        if days not in self._daily_cache:
            if self._daily:
                self._daily_cache[days] = await self._daily(self.symbol, days, self.now)
            else:
                self._daily_cache[days] = await fetch_daily_candles(
                    self._fetch, self.symbol, days, self.now, self.exchange.max_candles)
        return self._daily_cache[days]

    async def daily_closes(self, days: int) -> list[Decimal]:
        return [c.close for c in await self.daily_candles(days)]

    async def adx(self, interval: int, period: int = 14) -> float | None:
        """Trend strength ADX of the completed ``interval``-minute candles (about 98 of them, one request).
        None while there are too few candles."""
        candles, got = await self.candles(98 * interval / 60)
        if got != interval:
            return None
        return adx([c for c in candles if c.start + interval * 60_000 <= self.now], period)


def adx(candles: list[Candle], period: int = 14) -> float | None:
    """Average directional index (Wilder): below ~25 the market moves sideways, above it trends – up or down."""
    if len(candles) < 3 * period:
        return None
    a = 1 / period
    atr = plus = minus = value = None
    for prev, c in zip(candles, candles[1:]):
        high, low, close = float(c.high), float(c.low), float(prev.close)
        up, down = high - float(prev.high), float(prev.low) - low
        tr = max(high - low, abs(high - close), abs(low - close))
        pdm = up if up > down and up > 0 else 0.0
        ndm = down if down > up and down > 0 else 0.0
        if atr is None:
            atr, plus, minus = tr, pdm, ndm
        else:
            atr, plus, minus = atr + a * (tr - atr), plus + a * (pdm - plus), minus + a * (ndm - minus)
        pdi, ndi = (100 * plus / atr, 100 * minus / atr) if atr else (0.0, 0.0)
        dx = 100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi else 0.0
        value = dx if value is None else value + a * (dx - value)
    return value


@dataclass
class Context:
    params: dict[str, Any]
    position: Position | None
    state: dict[str, Any]
    market: MarketView
    quote: str = "EUR"
    fees: Fees = Fees()  # what a sale costs (rate and fixed part) – for break-even and net profit
    # set by the engine: strategies can persist a journal entry (used by "AI decides" for Claude's answers)
    journal: Callable[[dict[str, Any]], None] | None = None
    # set by the engine: market data of another instrument of the same broker (the position's, or one a strategy
    # may switch to); None in tests that don't need it
    view_of: Callable[[str], Awaitable["MarketView"]] | None = None
    # the market of the position's instrument when it is not the bot's symbol (else ``market``)
    held: "MarketView | None" = None

    @property
    def now(self) -> int:
        return self.market.now

    @property
    def held_market(self) -> "MarketView":
        return self.held or self.market

    async def market_of(self, symbol: str) -> "MarketView":
        if symbol == self.market.symbol:
            return self.market
        if self.held is not None and symbol == self.held.symbol:
            return self.held
        if self.view_of is None:
            raise Problem("err.no_market_data", error=symbol)
        return await self.view_of(symbol)

    def targets(self, buy: Decimal | float | None = None, sell: Decimal | float | None = None,
                stop: Decimal | float | None = None, note: dict | None = None) -> None:
        """What the bot is waiting for – the app shows it on the card instead of the plain price.
        Prices in the quote currency; ``note`` is a message for strategies without a fixed price."""
        self.state["targets"] = {
            "buy_price": float(buy) if buy else None,
            "sell_price": float(sell) if sell else None,
            "stop_price": float(stop) if stop else None,
            "note": note,
        }


class Strategy:
    key: str = ""
    name: L = L("", "")
    description: L = L("", "")
    icon: str = "chart.line.uptrend.xyaxis"
    params: list[Param] = []
    # False = at most one buy per position; the engine refuses any further buy while a position is open
    accumulates: bool = False
    # True = offers "Max. open trades": the bot may hold several positions (trades) at once, each sold on its own
    multi_trades: bool = False
    # > 0: the strategy decides itself which trades to open and close (no spacing, no "Max. open trades" option) –
    # at most this many at once
    fixed_trades: int = 0

    def normalize(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        return {p.key: p.coerce(raw.get(p.key, p.default)) for p in self.params}

    async def evaluate(self, ctx: Context) -> Decision:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_json(self, lang: str) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name(lang),
            "description": self.description(lang),
            "icon": self.icon,
            "params": [p.to_json(lang) for p in self.params],
        }


COOLDOWN_LABEL = L("Pause after buy or sale", "Pause nach Kauf oder Verkauf")
COOLDOWN_HELP = L("Minutes to wait after every buy and every sale before the bot buys again.",
                  "Minuten Wartezeit nach jedem Kauf und jedem Verkauf, bevor der Bot erneut kauft.")


def cooldown_left(ctx: Context, minutes: float) -> int:
    """The pause counts from the last trade – a sale, or a buy (which matters when several trades may be open)."""
    last_trade = max(int(ctx.state.get("last_sell_at") or 0), int(ctx.state.get("last_buy_at") or 0))
    return max(0, last_trade + int(minutes * 60_000) - ctx.now)
