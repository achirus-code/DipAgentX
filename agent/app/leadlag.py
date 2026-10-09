"""Lead-lag monitor: do coins on Revolut X follow large one-minute BTC jumps the way ETH does on Binance?

Measurement only – it never trades. The backtest (docs/btc-eth-verbindung.md) found that after BTC-USDT rises by at
least 0.5 % within one minute while ETH-EUR has moved less than half of that, Binance's ETH-EUR rises by another
0.4–0.7 % on average over the next 15 minutes. Whether Revolut X lags the same way – for ETH, for other coins and for
BTC-EUR itself – can only be measured live:

- Binance (public, no key): best bid/ask of BTC-USDT and of every measured coin against USDT, every 2 seconds, one
  request.
- Revolut X: bid/ask of every measured coin against EUR in one request, every 10 seconds, every 2 seconds in the
  first minute after a jump (few requests, so the trading bots are not slowed down; after an error it backs off).
- Every BTC-USDT move of at least 0.3 % within 60 seconds (up or down, at most one every 5 minutes) is stored with
  each coin's move in the same 60 seconds and its price on Revolut X and Binance after 1, 5 and 15 minutes.

Everything survives a restart: the events are in the database, the counters (start of the measurement, restarts,
errors, last jump) in the settings, and events still waiting for follow-ups are resumed – or marked "interrupted" if
the agent was down when a follow-up was due. ``cleanup()`` removes interrupted events, events before a date or all.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

log = logging.getLogger("dipagentx.leadlag")

BINANCE_URL = "https://api.binance.com/api/v3/ticker/bookTicker"
LEADER = "BTCUSDT"
DEFAULT_COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC", "SUI")
BINANCE_EVERY_S = 2.0
REVX_EVERY_S = 10.0
REVX_FAST_EVERY_S = 2.0
REVX_FAST_FOR_S = 60.0
REVX_BACKOFF_S = 60.0
WINDOW_S = 60.0  # the jump is measured over this window
LOG_THRESHOLD = 0.003  # store moves from 0.3 %
EVENT_GAP_S = 300.0  # at most one event every 5 minutes
FOLLOW_UPS = (60, 300, 900)  # seconds after the jump
GRACE_S = 30.0  # a follow-up taken this late still counts (e.g. after a quick restart)
KEEP_S = 180.0  # samples kept in memory
THRESHOLDS = (0.003, 0.004, 0.005, 0.007)
STATE_KEY = "leadlag_state"
SAVE_EVERY_S = 60.0

Quotes = dict[str, tuple[float, float]]
# fetchers: Binance {"BTCUSDT": (bid, ask), "ETHUSDT": ...} and Revolut X {"ETH-EUR": (bid, ask), ...}
BinanceFetch = Callable[[list[str]], Awaitable[Quotes]]
RevxFetch = Callable[[list[str]], Awaitable[Quotes | None]]


def enabled() -> bool:
    return os.getenv("LEADLAG_MONITOR", "1").strip().lower() not in ("0", "false", "off", "no")


def coins_from_env() -> tuple[str, ...]:
    raw = os.getenv("LEADLAG_COINS", "").strip()
    coins = tuple(dict.fromkeys(c.strip().upper() for c in raw.split(",") if c.strip())) if raw else DEFAULT_COINS
    return coins or DEFAULT_COINS


def binance_symbol(coin: str) -> str:
    return f"{coin}USDT"


def revx_symbol(coin: str) -> str:
    return f"{coin}-EUR"


def _mid(quote: tuple[float, float] | None) -> float | None:
    if not quote or not quote[0] or not quote[1]:
        return None
    return (quote[0] + quote[1]) / 2


def _pct(new: float | None, old: float | None) -> float | None:
    if not new or not old:
        return None
    return round((new / old - 1) * 100, 4)


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def normalize(event: dict[str, Any]) -> dict[str, Any]:
    """Events stored by 1.35.1 measured ETH-EUR only, without per-coin data – shown in today's shape."""
    if "coins" in event:
        return event
    revx = event.get("revx")
    lag = (revx or {}).get("same_minute_pct")
    if lag is None:
        lag = event.get("eth_eur_binance_same_minute_pct")
    follow = {}
    for key, fu in (event.get("follow_ups") or {}).items():
        follow[key] = {"revx_mid_pct": fu.get("revx_mid_pct"), "revx_taker_round_trip_pct": fu.get("revx_taker_round_trip_pct"),
                       "binance_pct": fu.get("eth_eur_binance_pct")}
    complete = len(follow) == len(FOLLOW_UPS)
    return {
        "id": event.get("id"), "at": event["at"], "direction": event["direction"],
        "btc_usdt_jump_pct": event["btc_usdt_jump_pct"],
        "btc_follow_ups": {k: fu.get("btc_usdt_pct") for k, fu in (event.get("follow_ups") or {}).items()},
        "status": "complete" if complete else "interrupted",
        "coins": {"ETH-EUR": {"binance_same_minute_pct": event.get("eth_eur_binance_same_minute_pct"),
                              "revx": revx, "lagged": event.get("eth_lagged"), "follow_ups": follow}},
    }


class LeadLagMonitor:
    def __init__(self, db: Any, binance: BinanceFetch | None = None, revx: RevxFetch | None = None,
                 clock: Callable[[], float] = time.time, coins: tuple[str, ...] | None = None):
        self.db = db
        self.clock = clock
        self.coins = coins or coins_from_env()
        self._binance_fetch = binance
        self._revx_fetch = revx
        self.binance: deque[tuple[float, Quotes]] = deque()
        self.revx: deque[tuple[float, Quotes]] = deque()
        self.open: list[dict[str, Any]] = []  # events still waiting for follow-ups
        self._revx_next = 0.0
        self._fast_until = 0.0
        self._saved_at = 0.0
        self.state = self._load_state()

    # --- persistent state --------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        state = self.db.get_setting(STATE_KEY) or {}
        state.setdefault("first_started_at", None)
        state.setdefault("restarts", 0)
        state.setdefault("errors", {"binance": 0, "revolutx": 0})
        state.setdefault("last_event_at", None)
        state.setdefault("interrupted_on_start", 0)
        return state

    def _save_state(self, now: float | None = None, force: bool = False) -> None:
        now = self.clock() if now is None else now
        if force or now - self._saved_at >= SAVE_EVERY_S:
            self.db.set_setting(STATE_KEY, self.state)
            self._saved_at = now

    def start(self, now: float) -> None:
        """Called once when the agent starts: count the restart, resume open events or mark them interrupted."""
        if self.state["first_started_at"] is None:
            self.state["first_started_at"] = int(now * 1000)
        else:
            self.state["restarts"] += 1
        self.state["current_start_at"] = int(now * 1000)
        interrupted = 0
        for event in self.db.list_leadlag_events(10_000, status="open"):
            event = normalize(event)
            t0 = event["at"] / 1000
            missed = [a for a in FOLLOW_UPS if now > t0 + a + GRACE_S and str(a) not in self._done(event)]
            if missed:
                event["status"] = "interrupted"
                self.db.update_leadlag_event(event["id"], event)
                interrupted += 1
            else:
                self.open.append(event)
        self.state["interrupted_on_start"] = interrupted
        self._save_state(now, force=True)
        if interrupted or self.open:
            log.info("Lead-lag: resumed %d open event(s), %d interrupted by the restart", len(self.open), interrupted)

    @staticmethod
    def _done(event: dict[str, Any]) -> set[str]:
        """Follow-ups already taken (the BTC leg is recorded for every follow-up)."""
        return set(event.get("btc_follow_ups") or {})

    def _error(self, source: str, now: float) -> None:
        self.state["errors"][source] = int(self.state["errors"].get(source, 0)) + 1
        self._save_state(now)

    # --- samples ----------------------------------------------------------------

    def observe_binance(self, now: float, quotes: Quotes) -> None:
        self.binance.append((now, quotes))
        while self.binance and now - self.binance[0][0] > KEEP_S:
            self.binance.popleft()

    def observe_revx(self, now: float, quotes: Quotes) -> None:
        self.revx.append((now, quotes))
        while self.revx and now - self.revx[0][0] > KEEP_S:
            self.revx.popleft()

    @staticmethod
    def _at(samples: deque, t: float) -> tuple[float, Quotes] | None:
        """The last sample at or before ``t``."""
        best = None
        for ts, q in samples:
            if ts <= t:
                best = (ts, q)
            else:
                break
        return best

    # --- events -----------------------------------------------------------------

    def check(self, now: float) -> dict[str, Any] | None:
        """Detect a new BTC jump and fill the follow-ups of open events. Returns a new event, if any."""
        self._follow_up(now)
        last = self.state.get("last_event_at")
        if not self.binance or (last is not None and now - last / 1000 < EVENT_GAP_S):
            return None
        cur = self.binance[-1][1]
        then_s = self._at(self.binance, now - WINDOW_S)
        if then_s is None or self.binance[0][0] > now - WINDOW_S:
            return None  # not a full window yet
        then = then_s[1]
        btc = _pct(_mid(cur.get(LEADER)), _mid(then.get(LEADER)))
        if btc is None or abs(btc) < LOG_THRESHOLD * 100:
            return None
        revx_now, revx_then = self._at(self.revx, now), self._at(self.revx, now - WINDOW_S)
        coins: dict[str, Any] = {}
        for coin in self.coins:
            sym, bsym = revx_symbol(coin), binance_symbol(coin)
            entry: dict[str, Any] = {
                "binance_same_minute_pct": _pct(_mid(cur.get(bsym)), _mid(then.get(bsym))),
                "binance_mid": _mid(cur.get(bsym)),
                "revx": None,
                "follow_ups": {},
            }
            quote = revx_now[1].get(sym) if revx_now else None
            if quote:
                bid, ask = quote
                before = revx_then[1].get(sym) if revx_then else None
                entry["revx"] = {"bid": bid, "ask": ask, "age_s": round(now - revx_now[0], 1),
                                 "spread_pct": round((ask / bid - 1) * 100, 4) if bid else None,
                                 "same_minute_pct": _pct(_mid(quote), _mid(before)) if before else None}
            ref = (entry["revx"] or {}).get("same_minute_pct")
            if ref is None:
                ref = entry["binance_same_minute_pct"]
            entry["lagged"] = ref is not None and (ref < 0.5 * btc if btc > 0 else ref > 0.5 * btc)
            coins[sym] = entry
        event: dict[str, Any] = {
            "at": int(now * 1000),
            "direction": "up" if btc > 0 else "down",
            "btc_usdt_jump_pct": btc,
            "btc_usdt_mid": _mid(cur.get(LEADER)),
            "btc_follow_ups": {},
            "status": "open",
            "coins": coins,
        }
        self.state["last_event_at"] = event["at"]
        self._save_state(now, force=True)
        self._fast_until = now + REVX_FAST_FOR_S
        self._revx_next = min(self._revx_next, now)
        self.open.append(event)
        self._store(event)
        lagging = [s for s, c in coins.items() if c["lagged"]]
        log.info("Lead-lag: BTC %+.2f %% in 60 s – lagging on Revolut X: %s – following up for 15 min",
                 btc, ", ".join(lagging) or "none")
        return event

    def _follow_up(self, now: float) -> None:
        for event in list(self.open):
            t0 = event["at"] / 1000
            changed = False
            for after in FOLLOW_UPS:
                key = str(after)
                if key in self._done(event) or now < t0 + after:
                    continue
                if now > t0 + after + GRACE_S:  # the agent wasn't running when this follow-up was due
                    event["status"] = "interrupted"
                    break
                b = self.binance[-1][1] if self.binance else {}
                r = self.revx[-1] if self.revx and now - self.revx[-1][0] <= REVX_EVERY_S * 2 else None
                event["btc_follow_ups"][key] = _pct(_mid(b.get(LEADER)), event.get("btc_usdt_mid"))
                for sym, entry in event["coins"].items():
                    coin = sym.split("-")[0]
                    fu: dict[str, Any] = {"binance_pct": _pct(_mid(b.get(binance_symbol(coin))), entry.get("binance_mid"))}
                    quote = r[1].get(sym) if r else None
                    if quote and entry.get("revx"):
                        bid, ask = quote
                        fu["revx_mid_pct"] = _pct((bid + ask) / 2, (entry["revx"]["bid"] + entry["revx"]["ask"]) / 2)
                        # buy at the ask at the jump, sell at the bid now (Revolut X taker round trip without fees)
                        fu["revx_taker_round_trip_pct"] = _pct(bid, entry["revx"]["ask"])
                    entry["follow_ups"][key] = fu
                changed = True
            if event["status"] == "open" and len(self._done(event)) == len(FOLLOW_UPS):
                event["status"] = "complete"
            if event["status"] != "open":
                self.open.remove(event)
                changed = True
            if changed:
                self._store(event)

    # --- storage, summary, cleanup -------------------------------------------------

    def _store(self, event: dict[str, Any]) -> None:
        if event.get("id"):
            self.db.update_leadlag_event(event["id"], event)
        else:
            event["id"] = self.db.add_leadlag_event(event["at"], event)

    def summary(self) -> dict[str, Any]:
        events = [normalize(e) for e in self.db.list_leadlag_events(100_000)]
        complete = [e for e in events if e.get("status") == "complete"]
        coins = list(dict.fromkeys([revx_symbol(c) for c in self.coins] + [s for e in complete for s in e["coins"]]))
        by_coin = {}
        for sym in coins:
            rows = []
            for thr in THRESHOLDS:
                for lagged in (True, False):
                    sel = [e["coins"][sym] for e in complete if sym in e["coins"] and e["direction"] == "up"
                           and e["btc_usdt_jump_pct"] >= thr * 100 and e["coins"][sym].get("lagged") is lagged]
                    row: dict[str, Any] = {"btc_jump_min_pct": thr * 100, "lagged": lagged, "events": len(sel)}
                    for after in FOLLOW_UPS:
                        for field, name in (("revx_mid_pct", "revx"), ("revx_taker_round_trip_pct", "revx_taker"),
                                            ("binance_pct", "binance")):
                            row[f"{name}_{after // 60}min_avg_pct"] = _avg([c["follow_ups"].get(str(after), {}).get(field) for c in sel])
                    row["revx_spread_avg_pct"] = _avg([(c.get("revx") or {}).get("spread_pct") for c in sel])
                    rows.append(row)
            by_coin[sym] = rows
        key = {sym: next((r for r in rows if r["btc_jump_min_pct"] == 0.5 and r["lagged"]), None) for sym, rows in by_coin.items()}
        return {
            "question": "Do coins on Revolut X follow BTC-USDT jumps of >= 0.5 % within a minute when they lagged "
                        "(backtest ETH-EUR on Binance: +0.4–0.7 % in 15 min)? Worth a bot when revx_taker_15min_avg_pct "
                        "stays above +0.3 % after about 30 events.",
            "coins": [revx_symbol(c) for c in self.coins],
            "events_total": len(events),
            "events_complete": len(complete),
            "events_open": sum(1 for e in events if e.get("status") == "open"),
            "events_interrupted": sum(1 for e in events if e.get("status") == "interrupted"),
            "measuring_since": self.state.get("first_started_at"),
            "running_since": self.state.get("current_start_at"),
            "restarts": self.state.get("restarts", 0),
            "errors": self.state.get("errors"),
            "key_figures_0_5pct_lagged": {sym: {k: r[k] for k in ("events", "revx_15min_avg_pct", "revx_taker_15min_avg_pct",
                                                                  "binance_15min_avg_pct")} if r else None
                                          for sym, r in key.items()},
            "by_coin": by_coin,
        }

    def cleanup(self, scope: str, before: int | None = None, reset_counters: bool = False) -> dict[str, Any]:
        """Remove measurement data: "interrupted" events, all events "before" a time (ms), or "all" events (the
        measurement then starts over). ``reset_counters`` also clears restarts and errors."""
        if scope == "interrupted":
            ids = [e["id"] for e in map(normalize, self.db.list_leadlag_events(100_000)) if e.get("status") == "interrupted"]
            deleted = self.db.delete_leadlag_events(ids=ids)
        elif scope == "before":
            if before is None:
                raise ValueError("before is required")
            deleted = self.db.delete_leadlag_events(before=before)
            self.open = [e for e in self.open if e["at"] >= before]
        elif scope == "all":
            deleted = self.db.delete_leadlag_events()
            self.open = []
            self.state["first_started_at"] = int(self.clock() * 1000)
            self.state["last_event_at"] = None
        else:
            raise ValueError(f"unknown scope {scope!r}")
        if reset_counters or scope == "all":
            self.state["restarts"] = 0
            self.state["errors"] = {"binance": 0, "revolutx": 0}
            self.state["interrupted_on_start"] = 0
        self._save_state(force=True)
        log.info("Lead-lag: removed %d event(s) (%s)", deleted, scope)
        return {"deleted": deleted, "scope": scope, "counters_reset": reset_counters or scope == "all"}

    # --- loop -------------------------------------------------------------------

    async def run(self) -> None:
        self.start(self.clock())
        log.info("Lead-lag monitor started for %s (measurement only, no trades)", ", ".join(self.coins))
        bsyms = [LEADER] + [binance_symbol(c) for c in self.coins if binance_symbol(c) != LEADER]
        rsyms = [revx_symbol(c) for c in self.coins]
        while True:
            now = self.clock()
            try:
                if self._binance_fetch:
                    self.observe_binance(now, await self._binance_fetch(bsyms))
            except Exception as exc:  # noqa: BLE001 – a measurement must never take the agent down
                self._error("binance", now)
                log.debug("Lead-lag: Binance not available: %s", exc)
            if self._revx_fetch and now >= self._revx_next:
                try:
                    quotes = await self._revx_fetch(rsyms)
                    if quotes:
                        self.observe_revx(now, quotes)
                    self._revx_next = now + (REVX_FAST_EVERY_S if now < self._fast_until else REVX_EVERY_S)
                except Exception as exc:  # noqa: BLE001
                    self._error("revolutx", now)
                    self._revx_next = now + REVX_BACKOFF_S
                    log.debug("Lead-lag: Revolut X tickers not available: %s", exc)
            try:
                self.check(self.clock())
            except Exception:  # noqa: BLE001
                log.exception("Lead-lag check failed")
            await asyncio.sleep(BINANCE_EVERY_S)


async def binance_quotes(client: httpx.AsyncClient, symbols: list[str]) -> Quotes:
    resp = await client.get(BINANCE_URL, params={"symbols": json.dumps(symbols, separators=(",", ":"))})
    resp.raise_for_status()
    return {r["symbol"]: (float(r["bidPrice"]), float(r["askPrice"])) for r in resp.json()}
