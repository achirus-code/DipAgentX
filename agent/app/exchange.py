"""Exchange abstraction: the real Revolut X exchange and a mock market for demos/tests.

The agent trades on several brokers side by side (Revolut X and Trade Republic). Every bot belongs to one of them –
``Exchange.broker`` is that slot, whether the exchange behind it is the real one or the simulated demo market.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

from .i18n import Problem
from .revolutx import RevolutXClient

D0 = Decimal(0)
log = logging.getLogger("dipagentx.exchange")


def dec(value: object, default: Decimal = D0) -> Decimal:
    if value is None or value == "":
        return default
    return Decimal(str(value))


FIAT = {"EUR", "USD", "GBP", "CHF", "PLN"}


@dataclass(frozen=True)
class Fees:
    """What an order costs: a share of its value (Revolut X: 0.09 %) plus a fixed amount per order in the quote
    currency (Trade Republic: 1 €)."""

    rate: float = 0.0009
    fixed: float = 0.0

    def of(self, gross: Decimal, quote: str) -> Decimal:
        """Fee for an order of ``gross`` – fees in fiat are rounded up to a full cent, which matters for tiny orders."""
        fee = gross * Decimal(str(self.rate))
        if quote in FIAT:
            fee = (fee * 100).to_integral_value(rounding="ROUND_CEILING") / 100
        return fee + Decimal(str(self.fixed))

    def to_json(self) -> dict[str, float]:
        return {"rate": self.rate, "fixed": self.fixed}


REVOLUTX = "revolutx"
TRADEREPUBLIC = "traderepublic"
BROKERS = (REVOLUTX, TRADEREPUBLIC)
BROKER_TITLES = {REVOLUTX: "Revolut X", TRADEREPUBLIC: "Trade Republic"}


@dataclass
class Ticker:
    bid: Decimal
    ask: Decimal
    last: Decimal
    time: int | None = None  # ms of the quote, where the exchange tells (Trade Republic: stale outside trading hours)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.last


@dataclass
class Candle:
    start: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass
class PairInfo:
    symbol: str  # dash format, e.g. ETH-EUR
    base: str
    quote: str
    base_step: Decimal
    quote_step: Decimal
    min_order_size: Decimal
    min_order_size_quote: Decimal


@dataclass
class OrderResult:
    order_id: str
    status: str
    filled_qty: Decimal
    filled_amount: Decimal
    avg_price: Decimal
    fee: Decimal
    fee_currency: str
    reject_reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {"filled", "cancelled", "rejected", "replaced"}


class Exchange:
    name = "base"
    broker = REVOLUTX  # the slot the bots of this exchange belong to
    # Revolut X can report "filled" before the fill data is complete – the engine then keeps re-reading the order.
    # Exchanges that fill a market order completely or not at all don't need that.
    partial_fills = True
    # what a live sale costs, if the exchange knows it better than the agent's TAKER_FEE setting (Trade Republic: 1 €)
    live_fees: Fees | None = None
    # an order whose placement answer got lost and that can't be found for this long stops the bot (None: the
    # engine's default)
    order_lookup_grace_ms: int | None = None
    # candles per request – longer daily series are fetched in chunks of this size
    max_candles = 98

    @property
    def title(self) -> str:
        return BROKER_TITLES.get(self.broker, self.broker)

    def instrument(self, symbol: str) -> dict:
        """What the symbol stands for: name, type (crypto, stock, fund …) and a short code for amounts."""
        base = symbol.partition("-")[0]
        return {"name": base, "short": base, "type": "crypto"}

    def market_closed(self, symbol: str, ticker: Ticker) -> dict | None:
        """A message when the instrument can't be traded right now (outside trading hours), else None."""
        return None

    async def idle(self) -> None:
        """Called on every tick – exchanges with open streams drop the ones nobody needs any more."""

    def paper_buy(self, pair: "PairInfo", amount: Decimal, fee: Decimal, price: Decimal) -> tuple[Decimal, Decimal]:
        """A simulated buy for ``amount`` (fee included): (quantity, money spent). Exchanges that only sell whole
        units round the quantity down – the money spent is then less than the amount."""
        return (amount - fee) / price, amount

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def ticker(self, symbol: str) -> Ticker: ...
    async def tickers(self, symbols: list[str]) -> dict[str, Ticker]:
        """Tickers for several symbols; exchanges that support it fetch them in one request."""
        return {symbol: await self.ticker(symbol) for symbol in symbols}

    async def candles(self, symbol: str, interval: int, since: int, until: int) -> list[Candle]: ...
    async def pairs(self) -> dict[str, PairInfo]: ...
    async def balances(self) -> dict[str, tuple[Decimal, Decimal]]: ...
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        *,
        client_order_id: str,
        base_size: Decimal | None = None,
        quote_size: Decimal | None = None,
    ) -> str: ...
    # Limit orders as a maker (no fee on Revolut X): post-only at the best bid/ask, cancelled when they don't fill
    supports_limit = False

    async def place_limit_order(
        self, symbol: str, side: str, *, client_order_id: str, base_size: Decimal, price: Decimal,
    ) -> str:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    async def get_order(self, order_id: str) -> OrderResult: ...
    async def find_order(self, symbol: str, client_order_id: str, since: int) -> OrderResult | None:
        """Look up an order by our own client_order_id (used when the placement response got lost)."""

    async def find_lost_order(self, symbol: str, pending: dict) -> OrderResult | None:
        """The order of ``pending`` (side, sizes, client_order_id, placed_at) whose placement answer got lost."""
        return await self.find_order(symbol, pending["client_order_id"], pending["placed_at"] - 60_000)

    async def close(self) -> None: ...

    def invalidate_balances(self) -> None:
        """Called after every own order – exchanges that cache balances drop the cached ones."""

    async def pair(self, symbol: str) -> PairInfo:
        pairs = await self.pairs()
        if symbol not in pairs:
            raise Problem("err.unknown_pair", symbol=symbol)
        return pairs[symbol]


class UnconfiguredExchange(Exchange):
    """Placeholder until a broker is connected: every exchange call fails with a helpful message."""

    def __init__(self, reason: dict, broker: str = REVOLUTX):
        self.reason = reason
        self.broker = broker
        self.name = broker

    def __getattribute__(self, item: str):
        if item in {"ticker", "tickers", "candles", "pairs", "balances", "place_market_order", "get_order", "find_order", "pair"}:
            reason = object.__getattribute__(self, "reason")

            async def fail(*_, **__):
                raise Problem(reason["k"], **reason.get("a", {}))

            return fail
        return object.__getattribute__(self, item)

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Revolut X
# ---------------------------------------------------------------------------


class RevolutXExchange(Exchange):
    name = "revolutx"

    # Balances only change through our own orders (trades the user makes directly on Revolut X are deliberately
    # not tracked), so they are cached and dropped whenever we place an order. The app, the holdings check and the
    # pre-flight checks before buys and sells all share this cache.
    BALANCES_TTL = 60.0

    def __init__(self, client: RevolutXClient):
        self.client = client
        self._pairs: dict[str, PairInfo] = {}
        self._pairs_at = 0.0
        self._balances: dict[str, tuple[Decimal, Decimal]] | None = None
        self._balances_at = 0.0

    def invalidate_balances(self) -> None:
        self._balances = None

    @staticmethod
    def _parse_ticker(t: dict) -> Ticker:
        last = dec(t.get("last_price")) or dec(t.get("mid"))
        return Ticker(bid=dec(t.get("bid"), last), ask=dec(t.get("ask"), last), last=last)

    async def ticker(self, symbol: str) -> Ticker:
        data = await self.client.tickers([symbol])
        if not data:
            raise Problem("err.no_ticker", symbol=symbol)
        return self._parse_ticker(data[0])

    async def tickers(self, symbols: list[str]) -> dict[str, Ticker]:
        """One request for all symbols; symbols the exchange doesn't return are simply missing."""
        if not symbols:
            return {}
        return {
            t["symbol"].replace("/", "-"): self._parse_ticker(t)
            for t in await self.client.tickers(symbols)
            if t.get("symbol")
        }

    async def candles(self, symbol: str, interval: int, since: int, until: int) -> list[Candle]:
        raw = await self.client.candles(symbol, interval, since, until)
        candles = [
            Candle(int(c["start"]), dec(c["open"]), dec(c["high"]), dec(c["low"]), dec(c["close"])) for c in raw
        ]
        return sorted(candles, key=lambda c: c.start)

    async def pairs(self) -> dict[str, PairInfo]:
        if not self._pairs or time.time() - self._pairs_at > 3600:
            try:
                raw = await self.client.pairs()
            except Exception as exc:
                if not self._pairs:
                    raise
                log.warning("Refreshing the pair list failed (%s) – keeping the cached list", exc)
                self._pairs_at = time.time() - 3600 + 300  # try again in 5 minutes
                return self._pairs
            self._pairs = {
                key.replace("/", "-"): PairInfo(
                    symbol=key.replace("/", "-"),
                    base=p["base"],
                    quote=p["quote"],
                    base_step=dec(p["base_step"]),
                    quote_step=dec(p["quote_step"]),
                    min_order_size=dec(p["min_order_size"]),
                    min_order_size_quote=dec(p["min_order_size_quote"]),
                )
                for key, p in raw.items()
                if p.get("status", "active") == "active"
            }
            self._pairs_at = time.time()
        return self._pairs

    async def balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        if self._balances is not None and time.monotonic() - self._balances_at < self.BALANCES_TTL:
            return self._balances
        self._balances = {b["currency"]: (dec(b["available"]), dec(b["total"])) for b in await self.client.balances()}
        self._balances_at = time.monotonic()
        return self._balances

    async def place_market_order(self, symbol, side, *, client_order_id, base_size=None, quote_size=None) -> str:
        result = await self.client.place_market_order(
            symbol,
            side,
            client_order_id=client_order_id,
            base_size=str(base_size) if base_size is not None else None,
            quote_size=str(quote_size) if quote_size is not None else None,
        )
        return result["venue_order_id"]

    supports_limit = True

    async def place_limit_order(self, symbol, side, *, client_order_id, base_size, price) -> str:
        result = await self.client.place_limit_order(
            symbol, side, client_order_id=client_order_id, base_size=str(base_size), price=str(price),
        )
        return result["venue_order_id"]

    async def cancel_order(self, order_id: str) -> None:
        await self.client.cancel_order(order_id)

    async def get_order(self, order_id: str) -> OrderResult:
        return self._parse_order(await self.client.get_order(order_id))

    async def find_order(self, symbol: str, client_order_id: str, since: int) -> OrderResult | None:
        for orders in (await self.client.active_orders(symbol), await self.client.historical_orders(symbol, since)):
            for o in orders:
                if o.get("client_order_id") == client_order_id:
                    return await self.get_order(o["id"])  # full details incl. fees
        return None

    @staticmethod
    def _parse_order(o: dict) -> OrderResult:
        filled_qty = dec(o.get("filled_quantity"))
        avg = dec(o.get("average_fill_price")) or dec(o.get("price"))
        filled_amount = dec(o.get("filled_amount"), filled_qty * avg)
        return OrderResult(
            order_id=o["id"],
            status=o["status"],
            filled_qty=filled_qty,
            filled_amount=filled_amount,
            avg_price=avg,
            fee=dec(o.get("total_fee")),
            fee_currency=o.get("fee_currency") or "",
            reject_reason=o.get("reject_reason"),
        )

    async def close(self) -> None:
        await self.client.close()


# ---------------------------------------------------------------------------
# Mock market (demo mode without API keys)
# ---------------------------------------------------------------------------

_MOCK_BASE_PRICES = {
    "BTC-EUR": 58000.0,
    "ETH-EUR": 2300.0,
    "SOL-EUR": 140.0,
    "XRP-EUR": 0.52,
    "ADA-EUR": 0.35,
    "BTC-USD": 63000.0,
    "ETH-USD": 2500.0,
}


class MockExchange(Exchange):
    """Deterministic synthetic market so the whole system can be tried without real money.

    ``speed`` > 1 makes market time run faster (e.g. 60 = one hour per real minute).
    """

    name = "mock"

    def __init__(self, fee: Decimal, speed: float = 1.0):
        self.fee = fee
        self.speed = max(speed, 1.0)
        self._t0 = time.time() * 1000
        self._balances: dict[str, Decimal] = {"EUR": Decimal(5000), "USD": Decimal(5000)}
        self._orders: dict[str, OrderResult] = {}
        self._client_ids: dict[str, str] = {}

    def now_ms(self) -> int:
        real = time.time() * 1000
        return int(self._t0 + (real - self._t0) * self.speed)

    def _price(self, symbol: str, t_ms: float) -> float:
        base = _MOCK_BASE_PRICES.get(symbol, 100.0)
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:6], 16) % 1000
        h = t_ms / 3_600_000 + seed
        wave = (
            0.045 * math.sin(2 * math.pi * h / 41)
            + 0.022 * math.sin(2 * math.pi * h / 9.7 + 1.3)
            + 0.007 * math.sin(2 * math.pi * h / 1.9 + 0.4)
        )
        bucket = int(t_ms // 60_000)
        noise = (int(hashlib.md5(f"{symbol}{bucket}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF - 0.5) * 0.002
        return base * math.exp(wave + noise)

    def _q(self, value: float, symbol: str) -> Decimal:
        return Decimal(str(round(value, 6 if value < 10 else 2)))

    async def ticker(self, symbol: str) -> Ticker:
        p = self._price(symbol, self.now_ms())
        return Ticker(bid=self._q(p * 0.9998, symbol), ask=self._q(p * 1.0002, symbol), last=self._q(p, symbol))

    async def candles(self, symbol: str, interval: int, since: int, until: int) -> list[Candle]:
        step = interval * 60_000
        out: list[Candle] = []
        start = since - since % step
        while start <= until:
            end = min(start + step, until)
            samples = [self._price(symbol, start + (end - start) * i / 6) for i in range(7)]
            out.append(
                Candle(
                    start,
                    self._q(samples[0], symbol),
                    self._q(max(samples), symbol),
                    self._q(min(samples), symbol),
                    self._q(samples[-1], symbol),
                )
            )
            start += step
        return out

    async def pairs(self) -> dict[str, PairInfo]:
        return {
            s: PairInfo(
                symbol=s,
                base=s.split("-")[0],
                quote=s.split("-")[1],
                base_step=Decimal("0.00000001") if p > 10 else Decimal("0.01"),
                quote_step=Decimal("0.01"),
                min_order_size=Decimal("0.00001") if p > 10 else Decimal("1"),
                min_order_size_quote=Decimal("1"),
            )
            for s, p in _MOCK_BASE_PRICES.items()
        }

    async def balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {c: (v, v) for c, v in self._balances.items() if v > 0}

    async def place_market_order(self, symbol, side, *, client_order_id, base_size=None, quote_size=None) -> str:
        if client_order_id in self._client_ids:  # same idempotency guarantee as Revolut X
            return self._client_ids[client_order_id]
        base, quote = symbol.split("-")
        t = await self.ticker(symbol)
        if side == "buy":
            spend = quote_size if quote_size is not None else base_size * t.ask
            if self._balances.get(quote, D0) < spend:
                raise Problem("err.not_enough", currency=quote)
            amount = spend  # Revolut X charges no fee on buys, only on sells
            qty = (amount / t.ask).quantize(Decimal("0.00000001"))
            fee = D0
            self._balances[quote] = self._balances.get(quote, D0) - spend
            self._balances[base] = self._balances.get(base, D0) + qty
            price = t.ask
        else:
            qty = base_size if base_size is not None else quote_size / t.bid
            if self._balances.get(base, D0) < qty:
                raise Problem("err.not_enough", currency=base)
            amount = qty * t.bid
            fee = amount * self.fee
            self._balances[base] -= qty
            self._balances[quote] = self._balances.get(quote, D0) + amount - fee
            price = t.bid
        order_id = str(uuid.uuid4())
        self._orders[order_id] = OrderResult(order_id, "filled", qty, amount, price, fee, quote)
        self._client_ids[client_order_id] = order_id
        return order_id

    async def get_order(self, order_id: str) -> OrderResult:
        return self._orders[order_id]

    async def find_order(self, symbol: str, client_order_id: str, since: int) -> OrderResult | None:
        order_id = self._client_ids.get(client_order_id)
        return self._orders[order_id] if order_id else None

    async def close(self) -> None:
        return None
