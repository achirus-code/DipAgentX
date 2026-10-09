"""Lead-lag monitor: does ETH-EUR on Revolut X follow large one-minute BTC jumps the way it does on Binance?

Measurement only – it never trades. The backtest (docs/btc-eth-verbindung.md) found that after BTC-USDT rises by at
least 0.5 % within one minute while ETH-EUR has moved less than half of that, Binance's ETH-EUR rises by another
0.4–0.7 % on average over the next 15 minutes. Whether Revolut X lags the same way can only be measured live:

- Binance (public, no key): best bid/ask of BTC-USDT, ETH-USDT and ETH-EUR every 2 seconds.
- Revolut X: ETH-EUR bid/ask every 10 seconds, every 2 seconds in the first minute after a jump (few requests, so
  the trading bots are not slowed down; after a rate limit it backs off).
- Every BTC-USDT move of at least 0.3 % within 60 seconds (up or down, at most one every 5 minutes) is stored with
  ETH's move in the same 60 seconds and ETH-EUR on Revolut X and Binance after 1, 5 and 15 minutes.

``summary()`` answers the question: average move of Revolut X ETH-EUR after the jump, at mid prices and as a taker
round trip (buy at the ask, sell at the bid), split by jump size and by whether ETH had lagged.
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
BINANCE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ETHEUR")
REVX_SYMBOL = "ETH-EUR"
BINANCE_EVERY_S = 2.0
REVX_EVERY_S = 10.0
REVX_FAST_EVERY_S = 2.0
REVX_FAST_FOR_S = 60.0
REVX_BACKOFF_S = 60.0
WINDOW_S = 60.0  # the jump is measured over this window
LOG_THRESHOLD = 0.003  # store moves from 0.3 %
EVENT_GAP_S = 300.0  # at most one event every 5 minutes
FOLLOW_UPS = (60, 300, 900)  # seconds after the jump
KEEP_S = 180.0  # samples kept in memory
THRESHOLDS = (0.003, 0.004, 0.005, 0.007)

# fetchers: return {"BTCUSDT": (bid, ask), ...} and (bid, ask) of ETH-EUR on Revolut X
BinanceFetch = Callable[[], Awaitable[dict[str, tuple[float, float]]]]
RevxFetch = Callable[[], Awaitable[tuple[float, float] | None]]


def enabled() -> bool:
    return os.getenv("LEADLAG_MONITOR", "1").strip().lower() not in ("0", "false", "off", "no")


def _mid(quote: tuple[float, float] | None) -> float | None:
    if not quote or not quote[0] or not quote[1]:
        return None
    return (quote[0] + quote[1]) / 2


def _pct(new: float | None, old: float | None) -> float | None:
    if not new or not old:
        return None
    return round((new / old - 1) * 100, 4)


class LeadLagMonitor:
    def __init__(self, db: Any, binance: BinanceFetch | None = None, revx: RevxFetch | None = None,
                 clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock
        self._binance_fetch = binance
        self._revx_fetch = revx
        self.binance: deque[tuple[float, dict[str, tuple[float, float]]]] = deque()
        self.revx: deque[tuple[float, tuple[float, float]]] = deque()
        self.open: list[dict[str, Any]] = []  # events still waiting for follow-ups
        self.last_event_at = float("-inf")
        self.started_at: float | None = None
        self.revx_errors = 0
        self.binance_errors = 0
        self._revx_next = 0.0
        self._fast_until = 0.0

    # --- samples ----------------------------------------------------------------

    def observe_binance(self, now: float, quotes: dict[str, tuple[float, float]]) -> None:
        self.binance.append((now, quotes))
        while self.binance and now - self.binance[0][0] > KEEP_S:
            self.binance.popleft()

    def observe_revx(self, now: float, quote: tuple[float, float]) -> None:
        self.revx.append((now, quote))
        while self.revx and now - self.revx[0][0] > KEEP_S:
            self.revx.popleft()

    def _binance_at(self, t: float) -> dict[str, tuple[float, float]] | None:
        """The last Binance sample at or before ``t``."""
        best = None
        for ts, q in self.binance:
            if ts <= t:
                best = q
            else:
                break
        return best

    def _revx_at(self, t: float) -> tuple[float, tuple[float, float]] | None:
        best = None
        for ts, q in self.revx:
            if ts <= t:
                best = (ts, q)
            else:
                break
        return best

    # --- events -----------------------------------------------------------------

    def check(self, now: float) -> dict[str, Any] | None:
        """Detect a new BTC jump and fill the follow-ups of open events. Returns a new event, if any."""
        self._follow_up(now)
        if not self.binance or now - self.last_event_at < EVENT_GAP_S:
            return None
        cur = self.binance[-1][1]
        then = self._binance_at(now - WINDOW_S)
        if then is None or self.binance[0][0] > now - WINDOW_S:
            return None  # not a full window yet
        btc = _pct(_mid(cur.get("BTCUSDT")), _mid(then.get("BTCUSDT")))
        if btc is None or abs(btc) < LOG_THRESHOLD * 100:
            return None
        revx_now, revx_then = self._revx_at(now), self._revx_at(now - WINDOW_S)
        event: dict[str, Any] = {
            "at": int(now * 1000),
            "direction": "up" if btc > 0 else "down",
            "btc_usdt_jump_pct": btc,
            "eth_usdt_same_minute_pct": _pct(_mid(cur.get("ETHUSDT")), _mid(then.get("ETHUSDT"))),
            "eth_eur_binance_same_minute_pct": _pct(_mid(cur.get("ETHEUR")), _mid(then.get("ETHEUR"))),
            "binance_eth_eur_mid": _mid(cur.get("ETHEUR")),
            "binance_btc_usdt_mid": _mid(cur.get("BTCUSDT")),
            "revx": None,
            "follow_ups": {},
        }
        if revx_now:
            age, (bid, ask) = now - revx_now[0], revx_now[1]
            event["revx"] = {
                "bid": bid, "ask": ask, "age_s": round(age, 1),
                "spread_pct": round((ask / bid - 1) * 100, 4) if bid else None,
                "same_minute_pct": _pct(_mid(revx_now[1]), _mid(revx_then[1])) if revx_then else None,
            }
        lag_ref = (event["revx"] or {}).get("same_minute_pct")
        if lag_ref is None:
            lag_ref = event["eth_eur_binance_same_minute_pct"]
        event["eth_lagged"] = lag_ref is not None and (lag_ref < 0.5 * btc if btc > 0 else lag_ref > 0.5 * btc)
        self.last_event_at = now
        self._fast_until = now + REVX_FAST_FOR_S
        self._revx_next = min(self._revx_next, now)
        self.open.append(event)
        self._store(event)
        log.info("Lead-lag: BTC %+.2f %% in 60 s, ETH-EUR Revolut X %s, Binance %s – following up for 15 min",
                 btc, lag_ref if lag_ref is not None else "?", event["eth_eur_binance_same_minute_pct"])
        return event

    def _follow_up(self, now: float) -> None:
        for event in list(self.open):
            t0 = event["at"] / 1000
            for after in FOLLOW_UPS:
                key = str(after)
                if key in event["follow_ups"] or now < t0 + after:
                    continue
                b = self.binance[-1][1] if self.binance else {}
                r = self.revx[-1] if self.revx else None
                fu: dict[str, Any] = {
                    "btc_usdt_pct": _pct(_mid(b.get("BTCUSDT")), event["binance_btc_usdt_mid"]),
                    "eth_eur_binance_pct": _pct(_mid(b.get("ETHEUR")), event["binance_eth_eur_mid"]),
                }
                if r and event["revx"] and now - r[0] <= REVX_EVERY_S * 2:
                    bid, ask = r[1]
                    fu["revx_mid_pct"] = _pct((bid + ask) / 2, (event["revx"]["bid"] + event["revx"]["ask"]) / 2)
                    # buy at the ask at the jump, sell at the bid now (Revolut X taker round trip without fees)
                    fu["revx_taker_round_trip_pct"] = _pct(bid, event["revx"]["ask"])
                event["follow_ups"][key] = fu
            if all(str(a) in event["follow_ups"] for a in FOLLOW_UPS):
                self.open.remove(event)
            self._store(event)

    # --- storage and summary -----------------------------------------------------

    def _store(self, event: dict[str, Any]) -> None:
        if "id" in event:
            self.db.update_leadlag_event(event["id"], event)
        else:
            event["id"] = self.db.add_leadlag_event(event["at"], event)

    def summary(self) -> dict[str, Any]:
        events = [e for e in self.db.list_leadlag_events(10_000) if len(e.get("follow_ups", {})) == len(FOLLOW_UPS)]
        rows = []
        for thr in THRESHOLDS:
            for lagged in (True, False):
                sel = [e for e in events if e["direction"] == "up" and e["btc_usdt_jump_pct"] >= thr * 100
                       and e.get("eth_lagged") is lagged]
                row: dict[str, Any] = {"btc_jump_min_pct": thr * 100, "eth_lagged": lagged, "events": len(sel)}
                for after in FOLLOW_UPS:
                    for field, name in (("revx_mid_pct", "revx"), ("revx_taker_round_trip_pct", "revx_taker"),
                                        ("eth_eur_binance_pct", "binance")):
                        vals = [e["follow_ups"][str(after)].get(field) for e in sel]
                        vals = [v for v in vals if v is not None]
                        row[f"{name}_{after // 60}min_avg_pct"] = round(sum(vals) / len(vals), 3) if vals else None
                spreads = [e["revx"]["spread_pct"] for e in sel if e.get("revx") and e["revx"].get("spread_pct") is not None]
                row["revx_spread_avg_pct"] = round(sum(spreads) / len(spreads), 4) if spreads else None
                rows.append(row)
        return {
            "question": "Does ETH-EUR on Revolut X follow BTC-USDT jumps of >= 0.5 % within a minute "
                        "(backtest on Binance: +0.4–0.7 % in 15 min)?",
            "events_complete": len(events),
            "events_open": len(self.open),
            "running_since": int(self.started_at * 1000) if self.started_at else None,
            "errors": {"binance": self.binance_errors, "revolutx": self.revx_errors},
            "by_threshold": rows,
        }

    # --- loop -------------------------------------------------------------------

    async def run(self) -> None:
        self.started_at = self.clock()
        log.info("Lead-lag monitor started (measurement only, no trades)")
        while True:
            now = self.clock()
            try:
                if self._binance_fetch:
                    self.observe_binance(now, await self._binance_fetch())
            except Exception as exc:  # noqa: BLE001 – a measurement must never take the agent down
                self.binance_errors += 1
                log.debug("Lead-lag: Binance not available: %s", exc)
            if self._revx_fetch and now >= self._revx_next:
                try:
                    quote = await self._revx_fetch()
                    if quote:
                        self.observe_revx(now, quote)
                    self._revx_next = now + (REVX_FAST_EVERY_S if now < self._fast_until else REVX_EVERY_S)
                except Exception as exc:  # noqa: BLE001
                    self.revx_errors += 1
                    self._revx_next = now + REVX_BACKOFF_S
                    log.debug("Lead-lag: Revolut X ticker not available: %s", exc)
            try:
                self.check(self.clock())
            except Exception:  # noqa: BLE001
                log.exception("Lead-lag check failed")
            await asyncio.sleep(BINANCE_EVERY_S)


async def binance_quotes(client: httpx.AsyncClient) -> dict[str, tuple[float, float]]:
    resp = await client.get(BINANCE_URL, params={"symbols": json.dumps(list(BINANCE_SYMBOLS), separators=(",", ":"))})
    resp.raise_for_status()
    return {r["symbol"]: (float(r["bidPrice"]), float(r["askPrice"])) for r in resp.json()}
