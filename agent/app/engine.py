"""Bot engine: evaluates every enabled bot periodically and executes its orders.

All texts produced here (statuses, events, trade reasons) are i18n messages (see ``app.i18n``) that are
rendered in the app's language when they are read.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

import httpx

from .config import Settings
from .db import Database, now_ms, scoped
from .errors import ExchangeError
from .exchange import REVOLUTX, Candle, Exchange, Fees, OrderResult, PairInfo, Ticker, UnconfiguredExchange
from .i18n import Problem, as_message, dump, dur, m, message_key, money, month, qty, render
from .strategies import STRATEGIES, Buy, Context, MarketView, Position, Sell, has_position, open_positions, store_positions
from .strategies.base import DAY_MS, fetch_daily_candles

log = logging.getLogger("dipagentx.engine")

# market orders usually fill within a second – poll quickly first, then back off (≈ 8 s in total)
# first read a second after placing (Revolut X rarely has complete fill data earlier), ~9 s in total
ORDER_POLL_DELAYS = (1.0, 0.7, 1.0, 1.0, 1.5, 1.5, 2.0)
ERROR_BACKOFF_MS = 5 * 60_000
# network hiccups and exchange-side errors clear up quickly – don't sit out a dip for 5 minutes because of one
TRANSIENT_BACKOFF_MS = 60_000
# an order whose placement response got lost and that can't be found at the exchange after this long stops the bot
ORDER_LOOKUP_GRACE_MS = 3 * 60_000
# a "filled" order whose reported fill is still short of what we asked for: re-read it for this long
FILL_CHECK_MS = 15 * 60_000
# how often the booked live positions are compared with the balances on the exchange
HOLDINGS_CHECK_MS = 30 * 60_000  # plus right after every own fill
# how many symbols are fetched from the exchange concurrently during a tick
MARKET_DATA_CONCURRENCY = 4
# candles are re-fetched when a new candle starts or after this long, not on every tick
CANDLE_MAX_AGE_MS = 6 * 3_600_000  # safety net only – candles are normally reused until the next candle starts

Message = dict | str


def round_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def split_symbol(symbol: str) -> tuple[str, str]:
    base, _, quote = symbol.partition("-")
    return base, quote


def bot_has_live_position(bot: dict[str, Any] | None) -> bool:
    return bool(bot) and any(not p.paper for p in open_positions(bot["state"]))


def broker_of(bot: dict[str, Any]) -> str:
    """The broker a bot trades on – bots from before the second broker are Revolut X bots."""
    return bot.get("exchange") or REVOLUTX


def held_symbol(bot: dict[str, Any], position: Position | None) -> str:
    """The instrument a trade holds – the bot's own symbol unless the strategy bought another one."""
    return (position.symbol if position else None) or bot["symbol"]


def find_position(state: dict[str, Any], position_id: str | None) -> Position | None:
    """The trade with this id – without an id (orders placed before 1.13) the bot's only trade."""
    positions = open_positions(state)
    if position_id is None:
        return positions[0] if positions else None
    return next((p for p in positions if p.id == position_id), None)


def definitely_not_placed(exc: Exception) -> bool:
    """True only if the exchange clearly refused the order.

    Everything else (timeouts, 5xx, an unreadable response – note that a JSON decoding error is a ``ValueError``)
    means the order *may* have gone through and must be looked up instead of being sent again.
    """
    return isinstance(exc, Problem) or (isinstance(exc, ExchangeError) and not exc.transient)


def is_transient(exc: Exception) -> bool:
    """Network or exchange-side trouble that usually clears up by itself."""
    return isinstance(exc, (httpx.HTTPError, ConnectionError, TimeoutError)) or (
        isinstance(exc, ExchangeError) and exc.transient
    )


def short_fill(pending: dict, r: OrderResult, partial_fills: bool = True) -> bool:
    """A terminal order whose reported fill is smaller than what we asked for. Revolut X can report "filled" a
    moment before the fill data is complete; booking that would leave part of the position unbooked. Exchanges
    without partial fills (Trade Republic) round the size themselves – their fill is never "short"."""
    if r.status != "filled" or not partial_fills:
        return False
    if pending.get("base_size"):
        return r.filled_qty < Decimal(pending["base_size"])
    if pending.get("quote_size"):
        return r.filled_amount < Decimal(pending["quote_size"]) * Decimal("0.98")
    return False


def backoff_for(exc: Exception) -> int:
    return TRANSIENT_BACKOFF_MS if is_transient(exc) else ERROR_BACKOFF_MS


class CandleCache:
    """Candles per (symbol, interval, window), shared by all bots and kept across ticks.

    The set of candles only changes when a new candle starts; in between only the forming candle moves, which is
    covered by the live ticker price the strategies use anyway. So a series is reused until the next candle starts
    (15 min for 24 h windows, an hour for 48–72 h windows) – ``CANDLE_MAX_AGE_MS`` is only a safety net.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, int, int], tuple[int, int, list[Candle]]] = {}
        self._daily: dict[tuple[str, int], tuple[int, list[Candle]]] = {}

    def clear(self) -> None:
        self._entries.clear()
        self._daily.clear()

    async def daily_candles(self, exchange: Exchange, symbol: str, days: int, now: int) -> list[Candle]:
        """Daily candles for long averages – fetched once per day."""
        key, day = (symbol, days), now // DAY_MS
        entry = self._daily.get(key)
        if entry and entry[0] == day:
            return entry[1]
        candles = await fetch_daily_candles(exchange.candles, symbol, days, now, exchange.max_candles)
        self._daily[key] = (day, candles)
        return candles

    async def fetch(self, exchange: Exchange, symbol: str, interval: int, since: int, until: int) -> list[Candle]:
        key = (symbol, interval, until - since)
        bucket = until // (interval * 60_000)
        entry = self._entries.get(key)
        if entry and entry[0] == bucket and now_ms() - entry[1] < CANDLE_MAX_AGE_MS:
            return entry[2]
        candles = await exchange.candles(symbol, interval, since, until)
        self._entries[key] = (bucket, now_ms(), candles)
        return candles


PILLAR_DRIFT = 5.0  # percentage points a trend follower may drift from its share before rebalancing is suggested


class Engine:
    """Runs the bots of every broker. Symbols of different brokers never collide (Revolut X: ``ETH-EUR``, Trade
    Republic: ``<ISIN>-EUR``), so prices and candles are kept per symbol; limits, live trading, simulation fees and
    the summary are kept per broker."""

    def __init__(self, db: Database, exchanges: Exchange | dict[str, Exchange], settings: Settings):
        self.db = db
        self.exchanges: dict[str, Exchange] = (
            dict(exchanges) if isinstance(exchanges, dict) else {exchanges.broker: exchanges}
        )
        self.settings = settings
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.last_tick: int | None = None
        self.exchange_errors: dict[str, Message | None] = {}
        self.instance_error: Message | None = None
        self._wake = asyncio.Event()
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        # serialises "check limits + place buy" across all bots so limits can't be overrun concurrently
        self._buy_lock = asyncio.Lock()
        # held while a tick runs – lets an exchange swap wait until in-flight requests are done
        self._tick_lock = asyncio.Lock()
        self._instance_lock_file = None
        self._candles = CandleCache()
        # last evaluation per bot; only persisted together with a state/status change (saves a write per tick)
        self._last_check: dict[int, int] = {}
        self._holdings_checked_at: dict[str, int] = defaultdict(int)
        self._background: set[asyncio.Task] = set()

    # --- brokers -----------------------------------------------------------

    @property
    def exchange(self) -> Exchange:
        """The Revolut X slot (what there was before the second broker)."""
        return self.exchanges[REVOLUTX]

    @exchange.setter
    def exchange(self, value: Exchange) -> None:
        self.exchanges[REVOLUTX] = value

    @property
    def exchange_error(self) -> Message | None:
        return self.exchange_errors.get(REVOLUTX)

    def exchange_for(self, bot_or_broker: dict[str, Any] | str) -> Exchange:
        broker = bot_or_broker if isinstance(bot_or_broker, str) else broker_of(bot_or_broker)
        exchange = self.exchanges.get(broker)
        if exchange is None:
            exchange = self.exchanges[broker] = UnconfiguredExchange(m("exchange.unknown", broker=broker), broker)
        return exchange

    # --- loop -------------------------------------------------------------

    def _acquire_instance_lock(self) -> bool:
        """Only one engine may trade per data directory (protects against a 2nd container/worker)."""
        self._instance_lock_file = open(self.settings.data_dir / "engine.lock", "w")  # noqa: SIM115
        try:
            fcntl.flock(self._instance_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self.instance_error = m("engine.instance_locked")
            log.error(render(self.instance_error, "en"))
            return False

    async def run(self) -> None:
        if not self._acquire_instance_lock():
            return
        log.info("Engine started (exchanges: %s, interval: %ss)",
                 ", ".join(f"{b}={e.name}" for b, e in self.exchanges.items()), self.settings.tick_seconds)
        async with self._tick_lock:
            for broker in self.exchanges:
                self.apply_paper_fees(broker)
        while True:
            try:
                async with self._tick_lock:
                    await self.tick()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.tick_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def paper_fees(self, broker: str = REVOLUTX) -> dict[str, float]:
        """What the simulation charges on the broker: rates for buys and sells and a fixed amount per order
        (settings; defaults: the Revolut X taker rate on sells, 1 € per order on Trade Republic)."""
        return self.db.get_paper_fees(broker, float(self.settings.taker_fee) if broker == REVOLUTX else None)

    def fees(self, broker: str, paper: bool, side: str = "sell") -> Fees:
        """What a ``buy`` or ``sell`` costs on the broker, simulated or real."""
        if paper:
            f = self.paper_fees(broker)
            return Fees(float(f[side]), float(f.get("fixed") or 0))
        return self.exchange_for(broker).live_fees or Fees(float(self.settings.taker_fee))

    def sell_fees(self, bot: dict) -> Fees:
        """What a sale of this bot's trades costs – strategies use it for break-even and net profit."""
        return self.fees(broker_of(bot), self.is_paper(bot))

    def apply_paper_fees(self, broker: str = REVOLUTX) -> int:
        """Rebook the simulated trades if the fee settings differ from the rates they were booked with."""
        taker = float(self.settings.taker_fee)
        target = self.paper_fees(broker)
        # before 1.17.1 Revolut X simulated the taker rate on both sides; other brokers start with their defaults
        legacy = {"buy": taker, "sell": taker, "fixed": 0.0} if broker == REVOLUTX else target
        applied = self.db.get_setting(scoped("paper_fees_applied", broker)) or legacy
        count = self.db.reprice_paper(applied, target, broker)
        self.db.set_setting(scoped("paper_fees_applied", broker), target)
        if count:
            log.info("Simulated %s trades rebooked with fees buy %s / sell %s / fixed %s (%d trades)",
                     broker, target["buy"], target["sell"], target.get("fixed"), count)
        return count

    def wake(self) -> None:
        self._wake.set()

    def replace_exchange(self, new: Exchange) -> None:
        """Switch a broker to new credentials without a restart. The old client is closed once the running tick
        is done."""
        old = self.exchanges.get(new.broker)
        self.exchanges[new.broker] = new
        self.exchange_errors.pop(new.broker, None)
        self._candles.clear()
        self.wake()
        if old is None or old is new:
            return

        async def close_old() -> None:
            async with self._tick_lock:
                await old.close()

        task = asyncio.create_task(close_old())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    @asynccontextmanager
    async def paused(self):
        """No tick runs while the body executes (used to swap the database during a restore)."""
        async with self._tick_lock:
            yield

    def reset_caches(self) -> None:
        """Forget everything derived from the old database (after a restore)."""
        self._last_check.clear()
        self._candles.clear()
        self.exchange_errors.clear()

    async def shutdown(self) -> None:
        for task in list(self._background):
            task.cancel()
        for exchange in self.exchanges.values():
            await exchange.close()

    def live_trading_enabled(self, broker: str = REVOLUTX) -> bool:
        """Switch per broker, off by default; only the app can turn it on (with double confirmation)."""
        return bool(self.db.get_setting(scoped("live_trading", broker), False))

    def is_paper(self, bot: dict[str, Any]) -> bool:
        """Mode for *new* buys. Open positions keep the mode they were bought with."""
        return bot["paper"] or not self.live_trading_enabled(broker_of(bot))

    async def market_view(self, symbol: str, ticker: Ticker | None = None, exchange: Exchange | None = None) -> MarketView:
        exchange = exchange or self.exchange

        async def fetch(symbol: str, interval: int, since: int, until: int) -> list[Candle]:
            return await self._candles.fetch(exchange, symbol, interval, since, until)

        async def daily(symbol: str, days: int, now: int) -> list[Candle]:
            return await self._candles.daily_candles(exchange, symbol, days, now)

        if ticker is None:
            ticker = await exchange.ticker(symbol)
        view = MarketView(exchange, symbol, ticker, exchange.now_ms(), fetch=fetch, daily=daily)
        self.snapshots[symbol] = {
            "price": float(view.price),
            "bid": float(view.bid),
            "ask": float(view.ask),
            "change_24h": await view.change_pct(24),
            "closed": view.closed,
            "updated_at": now_ms(),
        }
        return view

    async def _market_views(self, exchange: Exchange, symbols: list[str]) -> tuple[dict[str, MarketView], dict[str, Message]]:
        """Ticker for all symbols in one request (where supported), candles concurrently."""
        views: dict[str, MarketView] = {}
        errors: dict[str, Message] = {}
        if not symbols:
            return views, errors
        try:
            tickers = await exchange.tickers(symbols)
        except Exception as exc:  # noqa: BLE001 – fall back to one request per symbol below
            log.warning("Ticker batch failed: %s", exc)
            tickers = {}
        semaphore = asyncio.Semaphore(MARKET_DATA_CONCURRENCY)

        async def build(symbol: str) -> None:
            async with semaphore:
                try:
                    views[symbol] = await self.market_view(symbol, tickers.get(symbol), exchange)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Market data for %s failed: %s", symbol, exc)
                    errors[symbol] = as_message(exc)

        await asyncio.gather(*(build(symbol) for symbol in symbols))
        return views, errors

    def broker_enabled(self, broker: str) -> bool:
        """A broker switched off in the settings is left alone: no prices, no bots, no login."""
        return broker not in (self.db.get_setting("brokers_disabled") or [])

    async def tick(self) -> None:
        bots = self.db.list_bots()
        brokers = sorted(b for b in {*self.exchanges, *(broker_of(bot) for bot in bots)} if self.broker_enabled(b))
        # every broker on its own: a slow or logged-out broker doesn't hold up the other one's bots
        await asyncio.gather(*(self._tick_broker(broker, [b for b in bots if broker_of(b) == broker]) for broker in brokers))
        self.last_tick = now_ms()

    async def _tick_broker(self, broker: str, bots: list[dict[str, Any]]) -> None:
        exchange = self.exchange_for(broker)
        try:
            await exchange.idle()
        except Exception as exc:  # noqa: BLE001
            log.warning("Housekeeping on %s failed: %s", broker, exc)
        # stopped bots still need a price while they hold a position (unrealised P&L) or an order is in flight
        relevant = [b for b in bots if b["enabled"] or has_position(b["state"]) or b["state"].get("pending_order")]
        symbols = set()
        for b in relevant:  # the bots' symbols and what their trades hold (or an order in flight buys) instead
            symbols.add(b["symbol"])
            symbols.update(p.symbol for p in open_positions(b["state"]) if p.symbol)
            if (b["state"].get("pending_order") or {}).get("symbol"):
                symbols.add(b["state"]["pending_order"]["symbol"])
        views, errors = await self._market_views(exchange, sorted(symbols))
        self.exchange_errors[broker] = next(iter(errors.values()), None)
        await self._verify_holdings(broker, bots)

        for bot in bots:
            if not bot["enabled"]:
                continue
            view = views.get(bot["symbol"])
            if view is None:
                status = m("engine.no_market_data", error=errors.get(bot["symbol"], "?"))
                async with self._locks[bot["id"]]:
                    if current := self.db.get_bot(bot["id"]):  # re-read: the API may have changed it meanwhile
                        self._persist(current, current["state"], status, self._snapshot(current))
                continue
            await self.process(bot["id"], view, views)

    # --- per bot ------------------------------------------------------------

    @staticmethod
    def _snapshot(bot: dict[str, Any]) -> tuple[str, Any]:
        """What is in the database right now – ``_persist`` only writes when state/status differ from it."""
        return json.dumps(bot["state"]), dump(bot["status"])

    def _persist(self, bot: dict[str, Any], state: dict[str, Any], status: Message, before: tuple[str, Any]) -> None:
        """Write state/status back – only when something changed (the check time alone is kept in memory)."""
        self._last_check[bot["id"]] = now_ms()
        if (json.dumps(state), dump(status)) == before:
            return
        self.db.update_bot(bot["id"], state=state, status=status, last_check=self._last_check[bot["id"]])

    async def process(self, bot_id: int, view: MarketView, views: dict[str, MarketView] | None = None) -> None:
        async with self._locks[bot_id]:
            bot = self.db.get_bot(bot_id)
            if not bot or not bot["enabled"]:
                return
            before = self._snapshot(bot)
            state = bot["state"]
            status: Message = bot["status"]
            try:
                if state.get("pending_order"):
                    status = await self._reconcile(bot, state) or status
                    if state.get("pending_order"):
                        status = m("engine.waiting_for_order")
                        return
                    if not bot["enabled"]:  # stopped by the reconciliation – needs a human look
                        return
                if int(state.get("retry_after") or 0) > now_ms():
                    return
                if state.get("fill_check") or self._sold_but_still_open(bot, state):
                    status = await self._complete_fill(bot, state) or status
                if mismatch := state.get("holdings_mismatch"):
                    # the exchange holds less than we booked – no trading until that is resolved (a late fill
                    # gets booked above; otherwise "Sell position now" sells what is there and writes off the rest)
                    base = mismatch.get("base") or view.instrument.get("short") or split_symbol(bot["symbol"])[0]
                    status = m("engine.holdings_mismatch", booked=qty(Decimal(mismatch["booked"])),
                               held=qty(Decimal(mismatch["held"])), base=base)
                    return
                if view.closed:
                    # outside trading hours (stocks and ETFs on Trade Republic): nothing can be bought or sold, and
                    # the prices don't move – the strategy waits for the opening as well
                    status = view.closed
                    return
                status = await self._evaluate(bot, state, view, views)
                state.pop("retry_after", None)
            except Exception as exc:  # noqa: BLE001
                log.warning("Bot %s: %s", bot["name"], exc)
                self.db.add_event(bot_id, "error", as_message(exc))
                status = m("engine.error", error=as_message(exc))
                state["retry_after"] = now_ms() + backoff_for(exc)
            finally:
                self._persist(bot, state, status, before)

    async def _evaluate(self, bot: dict[str, Any], state: dict[str, Any], view: MarketView,
                        views: dict[str, MarketView] | None = None) -> Message:
        strategy = STRATEGIES.get(bot["strategy"])
        if strategy is None:
            return m("engine.unknown_strategy", strategy=bot["strategy"])
        views = {**(views or {}), bot["symbol"]: view}
        exchange = self.exchange_for(bot)

        async def view_of(symbol: str) -> MarketView:
            """Market data of another instrument of the broker – fetched once per check."""
            if symbol not in views:
                views[symbol] = await self.market_view(symbol, exchange=exchange)
            return views[symbol]

        positions = open_positions(state)
        held: dict[str, MarketView] = {p.id: await view_of(p.symbol) for p in positions if p.symbol}
        if positions:
            for position in positions:
                price = held[position.id].price if position.id in held else view.price
                position.peak = max(position.peak, price)
                if position.trail_peak is not None:
                    position.trail_peak = max(position.trail_peak, price)
            store_positions(state, positions)

        _, quote = split_symbol(bot["symbol"])
        params = strategy.normalize(bot["params"])

        def context(position: Position | None) -> Context:
            return Context(params, position, state, view, quote, self.sell_fees(bot),
                           journal=lambda entry: self.db.add_ai_decision(bot_id=bot["id"], **entry),
                           view_of=view_of, held=held.get(position.id) if position else None)

        async def buy(action: Buy) -> Message:
            target = action.symbol or bot["symbol"]
            return await self._buy(bot, state, await view_of(target), action.quote_amount, action.reason, target)

        if strategy.accumulates:  # savings plan: one position that every buy adds to
            position = positions[0] if positions else None
            decision = await strategy.evaluate(context(position))
            if position:
                store_positions(state, positions)  # the strategy may have changed the trade (an armed trailing stop)
            if isinstance(decision.action, Buy):
                return await buy(decision.action)
            if isinstance(decision.action, Sell) and position:
                sold = await self._sell_unless_loss(bot, state, held.get(position.id, view), position, decision.action, quote)
                return sold[1]
            state.pop("position_targets", None)
            if not self.blocked_buy(bot, state):
                state.pop("blocked_buy", None)
            return decision.status

        # every open trade is judged on its own – one order per tick, the next tick continues with the rest
        max_trades = self.max_trades(bot)
        statuses: dict[str, Message] = {}
        position_targets: dict[str, Any] = {}
        for position in positions:
            decision = await strategy.evaluate(context(position))
            # the strategy may have changed the trade (an armed trailing stop) – store it before any order rereads the state
            store_positions(state, positions)
            position_targets[position.id] = state.pop("targets", None)
            statuses[position.id] = decision.status
            if isinstance(decision.action, Sell):
                sold, status = await self._sell_unless_loss(bot, state, held.get(position.id, view), position,
                                                            decision.action, quote)
                if sold:
                    return status
                statuses[position.id] = status

        buy_status: Message | None = None
        buy_targets: dict[str, Any] | None = None
        if len(positions) < max_trades:
            decision = await strategy.evaluate(context(None))
            buy_targets = state.pop("targets", None)
            next_price = None
            if positions and not strategy.fixed_trades:
                # another trade only well below the open ones – otherwise a lasting signal would buy them all at once
                spacing = Decimal(str(params.get("trade_spacing", 0))) / 100
                next_price = min(p.entry_price for p in positions) * (1 - spacing)
                if buy_targets and buy_targets.get("buy_price"):
                    # both conditions must hold – the app shows each, the headline the stricter one
                    buy_targets["signal_price"] = buy_targets["buy_price"]
                    buy_targets["spacing_price"] = float(next_price)
                    buy_targets["buy_price"] = min(buy_targets["buy_price"], float(next_price))
            # "Min. time between trades": counted from the last buy, whether that trade is still open or not
            interval_ms = int(float(params.get("trade_interval_days") or 0) * 86_400_000)
            wait = int(state.get("last_buy_at") or 0) + interval_ms - view.now if interval_ms else 0
            if isinstance(decision.action, Buy):
                if wait > 0:
                    buy_status = m("engine.trade_interval", left=dur(wait))
                elif next_price is None or view.price <= next_price:
                    return await buy(decision.action)
                else:
                    buy_status = m("engine.trade_spacing", price=money(next_price, quote))
            elif wait > 0:
                buy_status = m("engine.trade_interval_waiting", left=dur(wait), status=decision.status)
            else:
                buy_status = decision.status

        # what the card shows: the next buy while there is room, else the trade closest to its sale
        nearest = min(
            (p for p in positions if (position_targets.get(p.id) or {}).get("sell_price")),
            key=lambda p: abs(position_targets[p.id]["sell_price"] / float(view.price) - 1),
            default=positions[0] if positions else None,
        )
        targets = {"buy_price": None, "sell_price": None, "stop_price": None, "note": None, **(buy_targets or {})}
        if nearest and position_targets.get(nearest.id):
            near = position_targets[nearest.id]
            targets.update(sell_price=near.get("sell_price"), stop_price=near.get("stop_price"))
            targets["note"] = targets["note"] or near.get("note")
        state["targets"] = targets if buy_targets or (nearest and position_targets.get(nearest.id)) else None
        # also when the limit was lowered below the open trades; a strategy that manages its trades speaks for all
        several = (max_trades > 1 or len(positions) > 1) and not strategy.fixed_trades
        if several and positions:
            state["position_targets"] = position_targets
        else:
            state.pop("position_targets", None)

        if not self.blocked_buy(bot, state):
            state.pop("blocked_buy", None)
        if not positions:
            return buy_status
        status = buy_status or statuses[nearest.id]
        if several:
            return m("engine.trades_open", open=len(positions), max=max_trades, status=status)
        return status

    async def _sell_unless_loss(self, bot: dict, state: dict, view: MarketView, position: Position, sell: Sell,
                                quote: str) -> tuple[bool, Message]:
        """Sell one trade – unless it is a target rule that would realize a loss. Returns (sold, status)."""
        # Safety net: a target rule never sells at a loss. Fees, cent rounding and the sell fee are included –
        # strategies compare the gross profit, which a 2 € order can lose to a fee rounded up to 0.01.
        net = position.net_proceeds(view.bid, self.fees(broker_of(bot), position.paper), quote)
        if not sell.stop and net < position.cost:
            return False, m("engine.hold_no_loss", net=money(net, quote), cost=money(position.cost, quote))
        return True, await self._sell(bot, state, view, sell.reason, position)

    def max_trades(self, bot: dict) -> int:
        """How many trades the bot may hold at once (1 for strategies without the option)."""
        strategy = STRATEGIES.get(bot["strategy"])
        if strategy and strategy.fixed_trades:
            return strategy.fixed_trades
        if not strategy or not strategy.multi_trades:
            return 1
        return int(strategy.normalize(bot["params"]).get("max_trades", 1))

    def blocked_buy(self, bot: dict, state: dict) -> Message | None:
        """Why the last buy signal was skipped, as long as the limits still block it (else None)."""
        blocked = state.get("blocked_buy")
        if not blocked or len(open_positions(state)) >= self.max_trades(bot):
            return None
        return self._limit_violation(bot, state, Decimal(blocked["amount"]))

    async def close_position(self, bot_id: int, reason: Message | None = None, position_id: str | None = None,
                             live_only: bool = False) -> Message:
        """Sell one trade (``position_id``) or all of them at market."""
        bot = self.db.get_bot(bot_id)
        if not bot:
            raise KeyError(bot_id)
        exchange = self.exchange_for(bot)
        view = await self.market_view(bot["symbol"], exchange=exchange)
        if view.closed:
            raise Problem("err.market_closed", reason=view.closed)
        held = {}
        for p in open_positions(bot["state"]):
            if p.symbol and p.symbol not in held:
                held[p.symbol] = await self.market_view(p.symbol, exchange=exchange)
        async with self._locks[bot_id]:
            bot = self.db.get_bot(bot_id)
            if not bot:
                raise KeyError(bot_id)
            state = bot["state"]
            chosen = [p for p in open_positions(state)
                      if (position_id is None or p.id == position_id) and not (live_only and p.paper)]
            if not chosen:
                raise Problem("err.no_position")
            if state.get("pending_order"):
                raise Problem("err.order_running")
            before = self._snapshot(bot)
            status: Message = bot["status"]
            try:
                for position in chosen:
                    pview = held.get(position.symbol) or view if position.symbol else view
                    status = await self._sell(bot, state, pview, reason or m("engine.manual_close"), position)
                    if state.get("pending_order"):  # still filling – the next tick finishes it, the rest waits
                        break
            except Exception as exc:
                status = m("engine.error", error=as_message(exc))
                raise
            finally:
                # always write the state back: a rejected order must not leave a pending order behind
                self._persist(bot, state, status, before)
            return status

    async def ask_now(self, bot_id: int) -> Message:
        """"AI decides" only: forget the wait until the next check and evaluate the bot right away – one extra
        Claude call. Everything else (cooldown, missing key, limits) applies as in a normal check."""
        async with self._locks[bot_id]:
            bot = self.db.get_bot(bot_id)
            if not bot:
                raise KeyError(bot_id)
            if bot["strategy"] != "ai":
                raise Problem("err.not_ai")
            if not bot["enabled"]:
                raise Problem("err.bot_stopped")
            if bot["state"].get("pending_order"):
                raise Problem("err.order_running")
            before = self._snapshot(bot)
            bot["state"].setdefault("ai", {})["next_at"] = 0
            self._persist(bot, bot["state"], bot["status"], before)
        views, errors = await self._market_views(self.exchange_for(bot), [bot["symbol"]])
        view = views.get(bot["symbol"])
        if view is None:
            raise Problem("err.no_market_data", error=errors.get(bot["symbol"], "?"))
        await self.process(bot_id, view)
        return self.db.get_bot(bot_id)["status"]

    async def discard_position(self, bot_id: int, position_id: str | None = None) -> Message:
        """Drop a position from the books without selling – for a position that is wrong (e.g. booked from a
        short-reported fill) while the coins stay, or don't exist, on the exchange. No trade is booked."""
        async with self._locks[bot_id]:
            bot = self.db.get_bot(bot_id)
            if not bot:
                raise KeyError(bot_id)
            state = bot["state"]
            positions = open_positions(state)
            chosen = [p for p in positions if position_id is None or p.id == position_id]
            if not chosen:
                raise Problem("err.no_position")
            if state.get("pending_order"):
                raise Problem("err.order_running")
            before = self._snapshot(bot)
            exchange = self.exchange_for(bot)
            pair = await exchange.pair(held_symbol(bot, chosen[0]))
            store_positions(state, [p for p in positions if p not in chosen])
            state.pop("holdings_mismatch", None)
            state.pop("fill_check", None)
            state["last_sell_at"] = exchange.now_ms()
            status = m("engine.position_discarded", qty=qty(sum(p.qty for p in chosen)),
                       base=self._base(bot, pair, chosen[0].symbol),
                       cost=money(sum(p.cost for p in chosen), pair.quote))
            self.db.add_event(bot["id"], "info", status)
            self._holdings_checked_at[broker_of(bot)] = 0
            self._persist(bot, state, status, before)
            return status

    async def reset_paper(self, bot_id: int) -> Message:
        """Start the bot's paper result from scratch: its simulated trades are deleted and open paper trades
        discarded. Live trades are never touched – a bot with an open live trade or an order in flight refuses."""
        async with self._locks[bot_id]:
            bot = self.db.get_bot(bot_id)
            if not bot:
                raise KeyError(bot_id)
            state = bot["state"]
            if state.get("pending_order"):
                raise Problem("err.order_running")
            if bot_has_live_position(bot):
                raise Problem("err.reset_live_open")
            before = self._snapshot(bot)
            deleted = self.db.delete_paper_trades(bot_id)
            store_positions(state, [])  # only paper trades are open (checked above)
            for key in ("targets", "position_targets", "blocked_buy", "last_sell_at", "last_buy_at", "realized", "momentum"):
                state.pop(key, None)
            status = m("engine.paper_reset", count=deleted)
            self.db.add_event(bot_id, "info", status)
            self._persist(bot, state, status, before)
            return status

    async def close_live_positions(self, reason: Message, broker: str = REVOLUTX) -> list[dict[str, Any]]:
        """Market-sell every open live position on the broker (used when switching it back to paper mode)."""
        results = []
        for bot in self.db.list_bots():
            if broker_of(bot) != broker or not bot_has_live_position(bot):
                continue
            try:
                message = await self.close_position(bot["id"], reason, live_only=True)
                ok = not bot_has_live_position(self.db.get_bot(bot["id"]))
            except Exception as exc:  # noqa: BLE001 – report per bot, keep closing the others
                message, ok = as_message(exc), False
                self.db.add_event(bot["id"], "error", m("engine.live_close_failed", error=as_message(exc)))
            results.append({"bot_id": bot["id"], "bot_name": bot["name"], "ok": ok, "message": message})
        return results

    # --- limits -------------------------------------------------------------------

    def exposure(self, exclude_bot_id: int | None = None, broker: str = REVOLUTX) -> tuple[int, Decimal, set[str]]:
        """Open positions (incl. buy orders in flight), invested capital and busy symbols of the broker's bots."""
        count, invested, symbols = 0, Decimal(0), set()
        for b in self.db.list_bots():
            if b["id"] == exclude_bot_id or broker_of(b) != broker:
                continue
            positions = open_positions(b["state"])
            pending = b["state"].get("pending_order") or {}
            buying = pending.get("side") == "buy"
            if positions or buying:
                strategy = STRATEGIES.get(b["strategy"])
                if strategy and strategy.fixed_trades:  # one position, held in slices
                    count += 1
                else:
                    # every trade counts; a buy in flight opens one more (a savings plan's adds to its position)
                    count += len(positions) + (1 if buying and not (positions and strategy and strategy.accumulates) else 0)
                symbols.add(b["symbol"])
                invested += sum((p.cost for p in positions), Decimal(0))
                invested += Decimal(pending.get("quote_size") or 0) if buying else Decimal(0)
        return count, invested, symbols

    def _limit_violation(self, bot: dict, state: dict, quote_size: Decimal) -> dict | None:
        limits = self.db.get_limits(broker_of(bot))
        count, invested, symbols = self.exposure(exclude_bot_id=bot["id"], broker=broker_of(bot))
        positions = open_positions(state)
        strategy = STRATEGIES.get(bot["strategy"])
        # this buy opens a new trade (a savings plan adds to its position, the momentum follower to its slices)
        if not (positions and strategy and (strategy.accumulates or strategy.fixed_trades)):
            count += len(positions)  # the bot's own open trades count as well
            max_positions = int(limits["max_open_positions"])
            if max_positions > 0 and count >= max_positions:
                return m("limit.positions", count=count, max=max_positions)
            if limits["one_position_per_symbol"] and bot["symbol"] in symbols:
                return m("limit.symbol", symbol=bot["symbol"])
        max_invested = Decimal(str(limits["max_total_invested"]))
        own = sum((p.cost for p in positions), Decimal(0))
        if max_invested > 0 and invested + own + quote_size > max_invested:
            _, quote = split_symbol(bot["symbol"])
            return m("limit.capital", invested=money(invested + own, quote), max=money(max_invested, quote))
        return None

    # --- order execution ------------------------------------------------------

    async def _buy(self, bot: dict, state: dict, view: MarketView, amount: Decimal, reason: Message,
                   symbol: str | None = None) -> Message:
        """Buy for ``amount`` – the bot's instrument, or ``symbol`` (``view`` is that instrument's market)."""
        strategy = STRATEGIES[bot["strategy"]]
        symbol = symbol or bot["symbol"]
        if symbol != bot["symbol"] and view.closed:
            return view.closed
        if state.get("pending_order"):
            return m("engine.order_running_no_buy")
        positions = open_positions(state)
        if not strategy.accumulates and len(positions) >= self.max_trades(bot):
            return m("engine.position_open_no_buy")
        # all trades of a bot run in the same mode – a mode change only sells until they are closed
        open_position = next((p for p in positions if p.paper != self.is_paper(bot)), None)
        exchange = self.exchange_for(bot)
        if open_position:
            if not (open_position.paper and strategy.accumulates):
                return m("engine.mode_changed_paper" if open_position.paper else "engine.mode_changed_live")
            # a savings plan would otherwise never buy again (and without a profit target never sell): close the
            # simulated position the simulated way and carry on live – real coins are never "sold" on paper
            pair = await exchange.pair(bot["symbol"])
            price = view.bid
            gross = open_position.qty * price
            fee = self._paper_fee(bot, "sell", gross)
            self._record_sell(bot, state, pair, open_position.qty, gross - fee, price, fee, None, True,
                              m("engine.mode_changed_close"), position_id=open_position.id)
        pair = await exchange.pair(symbol)
        quote_size = round_down(amount, pair.quote_step)
        if quote_size < pair.min_order_size_quote:
            raise Problem("err.amount_below_min", amount=money(quote_size, pair.quote),
                          min=money(pair.min_order_size_quote, pair.quote))

        async with self._buy_lock:
            blocked = self._limit_violation(bot, state, quote_size)
            if blocked:
                status = m("engine.buy_skipped", reason=blocked)
                if render(bot["status"], "en") != render(status, "en"):  # log once, not every tick
                    self.db.add_event(bot["id"], "info", m("paren", text=status, detail=reason))
                # shown as a hint until the limit allows the buy – a strategy like "AI decides" signals only
                # once per check, so the skipped status alone would be gone with the next tick
                state["blocked_buy"] = {"amount": str(quote_size), "at": now_ms()}
                return status
            state.pop("blocked_buy", None)

            if self.is_paper(bot):
                price = view.ask
                fee = self._paper_fee(bot, "buy", quote_size)
                bought, spent = exchange.paper_buy(pair, quote_size, fee, price)
                if bought <= 0:
                    raise Problem("err.amount_below_min", amount=money(quote_size, pair.quote),
                                  min=money(price + fee, pair.quote))
                return self._record_buy(bot, state, pair, bought, spent, price, fee, None, True, reason, symbol=symbol)

            balances = await exchange.balances()
            available = balances.get(pair.quote, (Decimal(0), Decimal(0)))[0]
            if available < quote_size:
                raise Problem("err.insufficient", currency=pair.quote, available=money(available, pair.quote),
                              needed=money(quote_size, pair.quote))
            pending = await self._submit_order(bot, state, "buy", reason, quote_size=quote_size, symbol=symbol)
        # the pending order already counts towards the limits – don't hold up other bots while it fills
        return await self._track_order(bot, state, pair, pending)

    def _paper_fee(self, bot: dict, side: str, gross: Decimal) -> Decimal:
        """The fee the simulation books for an order of ``gross``: the rate of the side plus the fixed part."""
        fees = self.paper_fees(broker_of(bot))
        return gross * Decimal(str(fees[side])) + Decimal(str(fees.get("fixed") or 0))

    def _base(self, bot: dict, pair: PairInfo, symbol: str | None = None) -> str:
        """The unit of the bot's quantities as people know it: ETH – or AAPL instead of an ISIN."""
        return self.exchange_for(bot).instrument(symbol or bot["symbol"]).get("short") or pair.base

    async def _sell(self, bot: dict, state: dict, view: MarketView, reason: Message, position: Position) -> Message:
        """Sell a whole trade; ``view`` is the market of the instrument it holds."""
        exchange = self.exchange_for(bot)
        symbol = held_symbol(bot, position)
        pair = await exchange.pair(symbol)
        amount = position.qty

        if position.paper:  # sell the way it was bought – never "simulate" selling real coins
            price = view.bid
            gross = amount * price
            fee = self._paper_fee(bot, "sell", gross)
            return self._record_sell(bot, state, pair, amount, gross - fee, price, fee, None, True, reason,
                                     position_id=position.id, symbol=symbol)

        balances = await exchange.balances()
        available, total = balances.get(pair.base, (Decimal(0), Decimal(0)))
        amount = round_down(min(amount, available), pair.base_step)
        manual = message_key(reason) == "engine.manual_close"
        if manual and total + pair.min_order_size < position.qty:
            # the coins are not on the exchange (whatever happened to them) – a manual close is the explicit
            # decision to clean the books: sell what is there, write off the rest
            missing = position.qty - max(total, Decimal(0))
            if amount < pair.min_order_size:
                return self._write_off(bot, state, pair, position, missing)
            status = await self._track_order(bot, state, pair, await self._submit_order(
                bot, state, "sell", reason, base_size=amount, position_id=position.id, symbol=symbol))
            if not state.get("pending_order") and (rest := find_position(state, position.id)):
                return self._write_off(bot, state, pair, rest, missing)
            return status
        if amount <= 0 or amount < pair.min_order_size:
            raise Problem("err.sell_below_min", qty=qty(amount), base=self._base(bot, pair, position.symbol),
                          min=qty(pair.min_order_size), available=qty(available))
        if available + pair.min_order_size < position.qty:
            self.db.add_event(bot["id"], "error", m("engine.sell_less_available", booked=qty(position.qty),
                                                    available=qty(available), base=self._base(bot, pair, position.symbol)))
        pending = await self._submit_order(bot, state, "sell", reason, base_size=amount, position_id=position.id,
                                           symbol=symbol)
        return await self._track_order(bot, state, pair, pending)

    def _write_off(self, bot: dict, state: dict, pair: PairInfo, position: Position, missing: Decimal) -> Message:
        """Drop the part of a position the exchange does not hold. No trade is booked – nothing was sold."""
        missing = min(missing, position.qty)
        store_positions(state, [p for p in open_positions(state) if p.id != position.id])
        state.pop("holdings_mismatch", None)
        state.pop("fill_check", None)
        msg = m("engine.position_written_off", qty=qty(missing), base=self._base(bot, pair, position.symbol),
                cost=money(position.cost * missing / position.qty, pair.quote))
        self.db.add_event(bot["id"], "error", msg)
        log.error("Bot %s: %s", bot["name"], render(msg, "en"))
        self._holdings_checked_at[broker_of(bot)] = 0
        return msg

    async def _submit_order(
        self, bot: dict, state: dict, side: str, reason: Message,
        *, base_size: Decimal | None = None, quote_size: Decimal | None = None, position_id: str | None = None,
        symbol: str | None = None,
    ) -> dict:
        """Place a market order exactly once.

        The pending order (with our own client_order_id) is persisted *before* it is sent. If the response
        gets lost, the next tick looks the order up by that id instead of sending a second one.
        """
        pending = {
            "client_order_id": str(uuid.uuid4()),
            "id": None,
            "side": side,
            "reason": reason,
            "placed_at": now_ms(),
            "quote_size": str(quote_size) if quote_size is not None else None,
            "base_size": str(base_size) if base_size is not None else None,
            "position_id": position_id,  # the trade a sell closes
            "symbol": symbol or bot["symbol"],  # the instrument (not always the bot's own)
        }
        state["pending_order"] = pending
        self.db.update_bot(bot["id"], state=state)
        exchange = self.exchange_for(bot)
        try:
            pending["id"] = await exchange.place_market_order(
                pending["symbol"], side, client_order_id=pending["client_order_id"],
                base_size=base_size, quote_size=quote_size,
            )
        except Exception as exc:
            exchange.invalidate_balances()  # the order may have gone through anyway
            if definitely_not_placed(exc):
                state.pop("pending_order", None)
                raise
            raise Problem("err.order_unclear", error=as_message(exc)) from exc
        exchange.invalidate_balances()  # balances change with this order – the cache must not serve the old ones
        self.db.update_bot(bot["id"], state=state)
        self.db.add_event(bot["id"], "info", m("engine.order_sent", id=pending["id"], side=m(f"side.{side}")))
        return pending

    async def _track_order(self, bot: dict, state: dict, pair: PairInfo, pending: dict) -> Message:
        exchange = self.exchange_for(bot)
        result = previous = None
        for delay in ORDER_POLL_DELAYS:
            await asyncio.sleep(delay)
            previous, result = result, await exchange.get_order(pending["id"])
            # book only what two consecutive reads agree on – fill data can still be moving right after "filled"
            confirmed = previous is not None and (previous.status, previous.filled_qty) == (result.status, result.filled_qty)
            if result.terminal and confirmed and not short_fill(pending, result, exchange.partial_fills):
                return self._apply_order(bot, state, pair, pending, result)
        if result is not None and result.terminal:
            # Revolut X reported "filled" but the fill data still lags behind the order size – book what is
            # there and keep re-reading the order (see _complete_fill) so the rest is booked as well
            return self._apply_order(bot, state, pair, pending, result)
        return m("engine.waiting_for_order")

    async def _reconcile(self, bot: dict, state: dict) -> Message | None:
        """Finish a pending order. Returns the new status once the order is settled, else None."""
        pending = state["pending_order"]
        exchange = self.exchange_for(bot)
        symbol = pending.get("symbol") or bot["symbol"]
        pair = await exchange.pair(symbol)
        overdue = now_ms() - pending["placed_at"] > (exchange.order_lookup_grace_ms or ORDER_LOOKUP_GRACE_MS)
        if not pending.get("id"):
            found = await exchange.find_lost_order(symbol, pending)
            if found is None:
                return self._abandon_order(bot, state, pending) if overdue else None
            pending["id"] = found.order_id
            self.db.update_bot(bot["id"], state=state)
            result = found
        else:
            try:
                result = await exchange.get_order(pending["id"])
            except ExchangeError as exc:
                if exc.status == 404 and overdue:  # the exchange doesn't know the id (any more)
                    return self._abandon_order(bot, state, pending)
                raise
        if result.terminal and (not short_fill(pending, result, exchange.partial_fills) or overdue):
            return self._apply_order(bot, state, pair, pending, result)
        return None

    async def _verify_holdings(self, broker: str, bots: list[dict[str, Any]], force: bool = False) -> None:
        """Compare the live positions we booked on the broker with what it actually holds.

        Whatever goes wrong in order handling ends up here: if the exchange holds less of a coin than the bots
        think they own, every bot with a live position in that coin is flagged and stops trading. Holding *more*
        is fine (coins the user keeps outside the bots)."""
        live = [b for b in bots if bot_has_live_position(b)]
        if not live or (not force and now_ms() - self._holdings_checked_at[broker] < HOLDINGS_CHECK_MS):
            return
        exchange = self.exchange_for(broker)
        try:
            balances = await exchange.balances()
        except Exception as exc:  # noqa: BLE001 – checked again in 5 minutes, not on every tick
            log.warning("Holdings check on %s skipped: %s", broker, exc)
            self._holdings_checked_at[broker] = now_ms() - HOLDINGS_CHECK_MS + 5 * 60_000
            return
        self._holdings_checked_at[broker] = now_ms()
        # what the bots booked per instrument they hold (usually their own symbol, see Position.symbol)
        booked: dict[str, Decimal] = defaultdict(Decimal)
        held_by: dict[int, set[str]] = defaultdict(set)
        for b in live:
            for p in open_positions(b["state"]):
                if not p.paper:
                    symbol = held_symbol(b, p)
                    booked[split_symbol(symbol)[0]] += p.qty
                    held_by[b["id"]].add(symbol)
        for b in live:
            mismatch = None
            unit = ""
            for symbol in sorted(held_by[b["id"]]):
                base, _ = split_symbol(symbol)
                held = balances.get(base, (Decimal(0), Decimal(0)))[1]
                pair = await exchange.pair(symbol)
                unit = self._base(b, pair, symbol)
                tolerance = max(pair.min_order_size, booked[base] * Decimal("0.005"))
                if booked[base] - held > tolerance:
                    mismatch = (booked[base], held, unit)
                    break
            async with self._locks[b["id"]]:
                bot = self.db.get_bot(b["id"])
                if not bot:
                    continue
                state = bot["state"]
                before = self._snapshot(bot)
                if mismatch:
                    if not state.get("holdings_mismatch"):
                        booked_qty, held, unit = mismatch
                        state["holdings_mismatch"] = {"booked": str(booked_qty), "held": str(held), "since": now_ms(),
                                                      "base": unit}
                        msg = m("engine.holdings_mismatch_event", booked=qty(booked_qty), held=qty(held), base=unit)
                        self.db.add_event(bot["id"], "error", msg)
                        log.error("Bot %s: %s", bot["name"], render(msg, "en"))
                elif state.pop("holdings_mismatch", None):
                    self.db.add_event(bot["id"], "info", m("engine.holdings_ok", base=unit))
                self._persist(bot, state, bot["status"], before)

    def _sold_but_still_open(self, bot: dict, state: dict) -> bool:
        """A trade that survived its live sell: sells always close the whole trade, so the exchange must have
        reported the fill short (seen on Revolut X right after placing) – re-read that order."""
        if not self.exchange_for(bot).partial_fills:
            return False
        if sold := state.get("last_live_sell"):
            position = find_position(state, sold["position_id"])
            if not position or position.paper or state.get("fill_checked") == sold["order_id"]:
                return False
            state["fill_check"] = {"order_id": sold["order_id"], "side": "sell", "position_id": position.id,
                                   "until": sold["at"] + FILL_CHECK_MS, "symbol": sold.get("symbol")}
            return True
        # sells booked before 1.13 don't record their trade – a bot held only one then
        positions = open_positions(state)
        if len(positions) != 1 or positions[0].paper:
            return False
        position = positions[0].to_state()
        last = next(iter(self.db.list_trades(bot["id"], 1)), None)
        if not last or last["side"] != "sell" or not last["order_id"] or last["paper"]:
            return False
        if last["created_at"] < int(position.get("opened_at") or 0):
            return False
        order_id = last["order_id"].split("#")[0]
        if state.get("fill_checked") == order_id:  # already re-read to the end
            return False
        state["fill_check"] = {"order_id": order_id, "side": "sell", "until": last["created_at"] + FILL_CHECK_MS}
        return True

    async def _complete_fill(self, bot: dict, state: dict) -> Message | None:
        """Re-read a short-filled order and book what the exchange executed on top of what we booked."""
        check = state["fill_check"]
        order_id = check["order_id"]
        exchange = self.exchange_for(bot)
        try:
            r = await exchange.get_order(order_id)
        except ExchangeError as exc:
            if exc.status == 404:
                state.pop("fill_check", None)
                state["fill_checked"] = order_id
            return None
        symbol = check.get("symbol") or bot["symbol"]
        pair = await exchange.pair(symbol)
        booked = self.db.booked_for_order(order_id)
        fee_base = r.fee if r.fee_currency == pair.base else Decimal(0)
        fee_quote = r.fee if r.fee_currency == pair.quote else Decimal(0)
        fee_in_quote = fee_quote + fee_base * r.avg_price
        if check["side"] == "sell":
            qty_total, amount_total = r.filled_qty + fee_base, r.filled_amount - fee_quote
        else:
            qty_total, amount_total = r.filled_qty - fee_base, r.filled_amount + fee_quote
        more_qty = qty_total - Decimal(str(booked["qty"]))
        status: Message | None = None
        if more_qty >= pair.base_step:
            more_amount = amount_total - Decimal(str(booked["amount"]))
            more_fee = max(fee_in_quote - Decimal(str(booked["fee"])), Decimal(0))
            late_id = f"{order_id}#{int(booked['n']) + 1}"
            reason = m("engine.late_fill", id=order_id)
            if check["side"] == "sell" and (position := find_position(state, check.get("position_id"))):
                status = self._record_sell(bot, state, pair, more_qty, more_amount, r.avg_price, more_fee, late_id, False,
                                           reason, position_id=position.id, symbol=symbol)
            elif check["side"] == "buy":
                # the rest belongs to the trade this order opened (a new one if that is sold already)
                into = next((p.id for p in open_positions(state) if p.order_id == order_id), None)
                status = self._record_buy(bot, state, pair, more_qty, more_amount, r.avg_price, more_fee, late_id, False,
                                          reason, into=into, symbol=symbol)
            self.db.add_event(bot["id"], "info", m("engine.late_fill_booked", id=order_id, qty=qty(more_qty),
                                                   base=self._base(bot, pair, symbol)))
        if r.terminal and (more_qty >= pair.base_step or now_ms() > check["until"]):
            state.pop("fill_check", None)
            state["fill_checked"] = order_id
        elif now_ms() > check["until"]:
            state.pop("fill_check", None)
            state["fill_checked"] = order_id
        return status

    def _abandon_order(self, bot: dict, state: dict, pending: dict) -> Message:
        """An order we can't find for minutes: don't guess. Drop it and stop the bot so nobody buys twice.

        If the order was in fact executed, the coins are on the account unbooked – a human has to check that
        at the exchange before starting the bot again.
        """
        state.pop("pending_order", None)
        state.pop("retry_after", None)
        bot["enabled"] = False
        self.db.update_bot(bot["id"], enabled=False)
        msg = m("engine.order_not_found", id=pending.get("id") or pending["client_order_id"])
        self.db.add_event(bot["id"], "error", msg)
        log.error("Bot %s: %s", bot["name"], render(msg, "en"))
        return msg

    def _apply_order(self, bot: dict, state: dict, pair: PairInfo, pending: dict, r: OrderResult) -> Message:
        state.pop("pending_order", None)
        state.pop("retry_after", None)  # the "order unclear" error is resolved with the order
        # the balances changed with the fill – a balance read while the order ran must not be served any more
        self.exchange_for(bot).invalidate_balances()
        if self.db.trade_exists(r.order_id):  # never book the same exchange order twice
            return m("engine.order_booked")
        if short_fill(pending, r, self.exchange_for(bot).partial_fills):
            state["fill_check"] = {"order_id": r.order_id, "side": pending["side"], "until": now_ms() + FILL_CHECK_MS,
                                   "position_id": pending.get("position_id"), "symbol": pending.get("symbol")}
        self._holdings_checked_at[broker_of(bot)] = 0  # verify the books against the exchange at the next tick
        if r.filled_qty <= 0:
            msg = (m("engine.order_failed_reason", status=r.status, reason=r.reject_reason) if r.reject_reason
                   else m("engine.order_failed", status=r.status))
            self.db.add_event(bot["id"], "error", msg)
            state["retry_after"] = now_ms() + ERROR_BACKOFF_MS
            return msg
        fee_base = r.fee if r.fee_currency == pair.base else Decimal(0)
        fee_quote = r.fee if r.fee_currency == pair.quote else Decimal(0)
        fee_in_quote = fee_quote + fee_base * r.avg_price
        if pending["side"] == "buy":
            return self._record_buy(
                bot, state, pair, r.filled_qty - fee_base, r.filled_amount + fee_quote,
                r.avg_price, fee_in_quote, r.order_id, False, pending["reason"], symbol=pending.get("symbol"),
            )
        return self._record_sell(
            bot, state, pair, r.filled_qty + fee_base, r.filled_amount - fee_quote,
            r.avg_price, fee_in_quote, r.order_id, False, pending["reason"], position_id=pending.get("position_id"),
            symbol=pending.get("symbol"),
        )

    # --- bookkeeping ----------------------------------------------------------

    def _record_buy(self, bot, state, pair, bought, spent, price, fee, order_id, paper, reason, into=None,
                    symbol=None) -> Message:
        """Book a buy: a new trade – or more of an existing one (``into``, or the savings plan's only position)."""
        symbol = symbol or bot["symbol"]
        positions = open_positions(state)
        state.pop("targets", None)  # the next check computes what the bot waits for now
        state.pop("position_targets", None)
        strategy = STRATEGIES.get(bot["strategy"])
        position = next((p for p in positions if p.id == into), None) if into else None
        if position is None and positions and strategy and strategy.accumulates:
            position = positions[0]
        if position:
            position.qty += bought
            position.cost += spent
            position.buys += 1
            position.peak = max(position.peak, price)
        else:
            position = Position(bought, spent, now_ms(), price, paper=paper, order_id=order_id,
                                symbol=symbol if symbol != bot["symbol"] else None)
            positions.append(position)
        store_positions(state, positions)
        state["last_buy_at"] = self.exchange_for(bot).now_ms()
        self.db.add_trade(
            bot_id=bot["id"], bot_name=bot["name"], symbol=symbol, side="buy",
            price=str(price), base_qty=str(bought), quote_amount=str(spent), fee=str(fee), pnl=None,
            order_id=order_id, paper=int(paper), reason=reason, position_id=position.id, exchange=broker_of(bot),
        )
        status = m("engine.bought", qty=qty(bought), base=self._base(bot, pair, symbol), amount=money(spent, pair.quote))
        self.db.add_event(bot["id"], "trade", m("paren", text=status, detail=reason))
        return status

    def _record_sell(self, bot, state, pair, sold, proceeds, price, fee, order_id, paper, reason, position_id=None,
                     symbol=None) -> Message:
        positions = open_positions(state)
        position = find_position(state, position_id)
        position = next((p for p in positions if position and p.id == position.id), None)
        if position is None:
            return m("engine.no_position")
        symbol = symbol or held_symbol(bot, position)
        state.pop("targets", None)  # the next check computes what the bot waits for now
        state.pop("position_targets", None)
        sold = min(sold, position.qty)
        cost_part = position.cost * sold / position.qty
        pnl = proceeds - cost_part
        # what the bot's sales gained or lost in total – a strategy reinvesting it (momentum) counts its capital with it
        state["realized"] = str(Decimal(str(state.get("realized") or 0)) + pnl)
        position.qty -= sold
        position.cost -= cost_part
        if position.qty <= 0 or position.qty < pair.min_order_size:
            positions.remove(position)  # only dust left
        store_positions(state, positions)
        state["last_sell_at"] = self.exchange_for(bot).now_ms()
        if order_id and not paper and "#" not in order_id:
            # lets the next tick spot a trade that survived its sell (a fill reported short)
            state["last_live_sell"] = {"order_id": order_id, "position_id": position.id, "at": now_ms(), "symbol": symbol}
        self.db.add_trade(
            bot_id=bot["id"], bot_name=bot["name"], symbol=symbol, side="sell",
            price=str(price), base_qty=str(sold), quote_amount=str(proceeds), fee=str(fee), pnl=str(pnl),
            order_id=order_id, paper=int(paper), reason=reason, position_id=position.id, exchange=broker_of(bot),
        )
        status = m("engine.sold", qty=qty(sold), base=self._base(bot, pair, symbol), amount=money(proceeds, pair.quote),
                   pnl=money(pnl, pair.quote))
        self.db.add_event(bot["id"], "trade", m("paren", text=status, detail=reason))
        return status

    # --- views for the API ------------------------------------------------------

    def _bot_value(self, bot: dict[str, Any]) -> float:
        """What a bot is worth now: its open trades at the bid, or the money it waits with (the monthly trend
        follower reinvests its last sale)."""
        positions = open_positions(bot["state"])
        if positions:
            total = 0.0
            for position in positions:
                snap = self.snapshots.get(position.symbol or bot["symbol"])
                price = Decimal(str(snap["bid"])) if snap else position.entry_price
                total += float(position.value(price))
            return total
        params = bot["params"]
        capital = (bot["state"].get("monthly") or {}).get("capital")
        return float(capital if capital and params.get("reinvest", True) else params.get("amount") or 0)

    def pillars(self, bot: dict[str, Any], lang: str = "en") -> dict[str, Any] | None:
        """The running trend followers of the bot's broker side by side: the share each should have (by its
        amount) and has (by its value) – the app suggests rebalancing once they drift apart."""
        if bot["strategy"] != "trend":
            return None
        group = [b for b in self.db.list_bots() if b["strategy"] == "trend" and b["enabled"]
                 and broker_of(b) == broker_of(bot)]
        if len(group) < 2 or bot["id"] not in {b["id"] for b in group}:
            return None
        amounts = [float(b["params"].get("amount") or 0) for b in group]
        values = [self._bot_value(b) for b in group]
        if not sum(amounts) or not sum(values):
            return None
        shares = [{"id": b["id"], "name": b["name"], "value": v, "target": a / sum(amounts) * 100,
                   "actual": v / sum(values) * 100, "rebalanced": a / sum(amounts) * sum(values)}
                  for b, a, v in zip(group, amounts, values)]
        drift = max(abs(x["actual"] - x["target"]) for x in shares)
        return {"shares": shares, "total": sum(values), "drift": drift, "due": drift >= PILLAR_DRIFT}

    @staticmethod
    def signals(bot: dict[str, Any], lang: str = "en") -> dict[str, Any] | None:
        """A strategy's overview of its signals (the monthly trend follower), rendered for the app."""
        raw = bot["state"].get("signals")
        if not raw or not bot["enabled"]:
            return None
        rows = [{"label": render(r["label"], lang), "value": render(r["value"], lang), "state": r.get("state"),
                 "note": render(r["note"], lang) if r.get("note") else None} for r in raw.get("rows", [])]
        history = [{"month": h["month"], "label": render(m("signals.month", month=month(h["month"])), lang), "state": h["state"],
                    "name": h.get("name")} for h in raw.get("history", [])]
        return {"rows": rows, "history": history, "at": raw.get("at")}

    def describe_bot(self, bot: dict[str, Any], stats: dict[int, dict[str, Any]], lang: str = "en") -> dict[str, Any]:
        base, quote = split_symbol(bot["symbol"])
        broker = broker_of(bot)
        instrument = self.exchange_for(broker).instrument(bot["symbol"])
        strategy = STRATEGIES.get(bot["strategy"])
        snap = self.snapshots.get(bot["symbol"])
        blocked = self.blocked_buy(bot, bot["state"]) if bot["enabled"] else None
        hint = render(m("engine.buy_blocked", reason=blocked), lang) if blocked else None
        s = stats.get(bot["id"], {})
        positions = open_positions(bot["state"])
        position_targets = bot["state"].get("position_targets") or {}

        def pos_json(position: Position) -> dict[str, Any]:
            own = self.snapshots.get(position.symbol) if position.symbol else snap
            price = Decimal(str(own["bid"])) if own else position.entry_price
            value = position.value(price)
            extra: dict[str, Any] = {}
            if position.symbol:  # another instrument than the bot's (a currency-hedged ETF, bonds to park in)
                other = self.exchange_for(broker).instrument(position.symbol)
                extra = {"symbol": position.symbol, "display_symbol": other.get("name") or split_symbol(position.symbol)[0],
                         "base_currency": other.get("short") or split_symbol(position.symbol)[0]}
            return {
                "id": position.id,
                "qty": float(position.qty),
                "cost": float(position.cost),
                "entry_price": float(position.entry_price),
                "opened_at": position.opened_at,
                "value": float(value),
                "unrealized_pnl": float(value - position.cost),
                "unrealized_pct": position.pnl_pct(price),
                "paper": position.paper,
                **extra,
            }

        def trade_json(position: Position) -> dict[str, Any]:
            t = position_targets.get(position.id) or {}
            return {**pos_json(position), "sell_price": t.get("sell_price"), "stop_price": t.get("stop_price"),
                    "note": render(t["note"], lang) if t.get("note") and bot["enabled"] else None}

        # "position" sums up all trades (what older apps show); "positions" lists them one by one
        total = None
        if positions:
            total = Position(sum(p.qty for p in positions), sum(p.cost for p in positions),
                             min(p.opened_at for p in positions), max(p.peak for p in positions),
                             paper=positions[0].paper, id="total",
                             symbol=positions[0].symbol if len({p.symbol for p in positions}) == 1 else None)
        return {
            "id": bot["id"],
            "name": bot["name"],
            "strategy": bot["strategy"],
            "strategy_name": strategy.name(lang) if strategy else bot["strategy"],
            "strategy_icon": strategy.icon if strategy else "questionmark.circle",
            "symbol": bot["symbol"],
            "exchange": broker,
            # Revolut X: ETH-EUR / ETH. Trade Republic: the instrument's name and ticker instead of the ISIN
            "display_symbol": bot["symbol"] if broker == REVOLUTX else instrument.get("name") or base,
            "instrument_type": instrument.get("type"),
            "base_currency": instrument.get("short") or base,
            "quote_currency": quote,
            "params": strategy.normalize(bot["params"]) if strategy else bot["params"],
            "enabled": bot["enabled"],
            "paper": self.is_paper(bot),
            "paper_requested": bot["paper"],
            # a skipped buy: the reason goes into the hint (it outlives the status), the status just says "buy signal"
            "status": render(m("engine.buy_signal") if hint and message_key(bot["status"]) == "engine.buy_skipped" else bot["status"], lang),
            "status_error": message_key(bot["status"]) in {"engine.error", "engine.order_not_found", "engine.holdings_mismatch"}
            or str(bot["status"]).startswith("Fehler"),
            "hint": hint,
            "targets": {**t, "note": render(t["note"], lang) if t.get("note") else None}
            if bot["enabled"] and (t := bot["state"].get("targets")) else None,
            "last_check": self._last_check.get(bot["id"], bot["last_check"]),
            "created_at": bot["created_at"],
            "pending_order": bool(bot["state"].get("pending_order")),
            "position": pos_json(total) if total else None,
            "positions": [trade_json(p) for p in positions],
            "max_trades": self.max_trades(bot),
            "realized_pnl": float(s.get("realized") or 0),
            "trades_count": int(s.get("trades") or 0),
            "wins": int(s.get("wins") or 0),
            "losses": int(s.get("losses") or 0),
            "market": {"price": snap["price"], "change_24h": snap["change_24h"],
                       "closed": render(snap["closed"], lang) if snap.get("closed") else None} if snap else None,
            "signals": self.signals(bot, lang),
            "pillars": self.pillars(bot, lang),
        }

    def summary(self, broker: str = REVOLUTX) -> dict[str, Any]:
        """The broker's result. Each broker has its own account, mode and limits – nothing is added up across them."""
        stats = self.db.trade_stats()
        bots = [self.describe_bot(b, stats) for b in self.db.list_bots() if broker_of(b) == broker]
        start_of_day = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        # Paper and live results are kept apart: the card shows the active mode, the other one is a footnote
        paper_mode = not self.live_trading_enabled(broker)

        def totals_for(paper: bool) -> dict[str, dict[str, float]]:
            totals: dict[str, dict[str, float]] = {}

            def bucket(currency: str) -> dict[str, float]:
                return totals.setdefault(currency, {"realized": 0.0, "unrealized": 0.0, "today": 0.0, "invested": 0.0, "fees": 0.0})

            for row in self.db.realized_by_symbol(paper, broker):
                bucket(split_symbol(row["symbol"])[1])["realized"] += row["pnl"] or 0.0
            for row in self.db.fees_by_symbol(paper, broker):
                bucket(split_symbol(row["symbol"])[1])["fees"] += row["fee"] or 0.0
            for row in self.db.realized_since(start_of_day, paper, broker):
                bucket(split_symbol(row["symbol"])[1])["today"] += row["pnl"] or 0.0
            for b in bots:
                for position in b["positions"]:
                    if position["paper"] == paper:
                        t = bucket(b["quote_currency"])
                        t["unrealized"] += position["unrealized_pnl"]
                        t["invested"] += position["cost"]
            return totals

        active, other = totals_for(paper_mode), totals_for(not paper_mode)
        currencies = [
            {"currency": c, **v, "total": v["realized"] + v["unrealized"]}
            for c, v in sorted(active.items(), key=lambda kv: -abs(kv[1]["realized"]) - kv[1]["invested"])
        ]
        return {
            "exchange": broker,
            "mode": "paper" if paper_mode else "live",
            "currencies": currencies,
            # the other mode's result per currency – only where something was traded or is open
            "other_mode": [
                {"currency": c, "total": v["realized"] + v["unrealized"], "realized": v["realized"], "unrealized": v["unrealized"]}
                for c, v in other.items()
            ],
            "other_mode_trades": self.db.trades_count(not paper_mode, broker),
            "bots_total": len(bots),
            "bots_active": sum(1 for b in bots if b["enabled"]),
            "open_positions": sum(len(b["positions"]) for b in bots),
            "max_open_positions": int(self.db.get_limits(broker)["max_open_positions"]),
            "trades_count": self.db.trades_count(paper_mode, broker),
        }
