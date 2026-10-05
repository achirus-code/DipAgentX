"""Market data of the crypto derivatives and on-chain world for the momentum trend follower – public, no key needed:

- the funding rate of the Binance USDT perpetual futures (ETHUSDT, BTCUSDT): what long positions pay short ones,
  around +11 % a year normally, near zero or negative when nearly everybody expects falling prices
- the net flow of coins onto exchanges (Coin Metrics community API, daily): large inflows mean many want to sell
"""

from __future__ import annotations

import calendar
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

log = logging.getLogger("dipagentx.cryptodata")

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
DAY_S = 86_400
FUNDING_CACHE_S = 3600  # a new rate every 8 hours
FLOWS_CACHE_S = 3 * 3600  # a new day once a day, around 02:00 UTC
RETRY_S = 15 * 60
FUNDING_MAX_AGE_S = 2 * DAY_S  # an older last rate is not used any more
FLOWS_MAX_AGE_S = 3 * DAY_S  # older flows only hurt – the brake needs them within about a day
PUBLISHED_AFTER_MS = 30 * 3_600_000  # a day's flows are used from 06:00 UTC the next morning


class Cached:
    """A download per key, cached for ``ttl`` seconds; during an outage the last good answer is kept."""

    def __init__(self, name: str, ttl: float, load: Callable[[httpx.AsyncClient, str], Awaitable[Any]]):
        self.name, self.ttl, self.load = name, ttl, load
        self.cache: dict[str, tuple[float, Any]] = {}
        self.failed_at: dict[str, float] = {}

    def reset(self) -> None:
        self.cache.clear()
        self.failed_at.clear()

    async def get(self, key: str) -> Any:
        fetched_at, value = self.cache.get(key, (0.0, None))
        now = time.time()
        if value is not None and now - fetched_at < self.ttl:
            return value
        if now - self.failed_at.get(key, 0.0) < RETRY_S:
            return value
        try:
            async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "DipAgentX"}) as client:
                fresh = await self.load(client, key)
            if not fresh:
                raise ValueError("no values")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            log.warning("%s (%s) not available: %s", self.name, key, exc)
            self.failed_at[key] = now
            return value
        self.cache[key] = (now, fresh)
        return fresh


async def _load_funding(client: httpx.AsyncClient, symbol: str) -> list[tuple[int, float]]:
    response = await client.get(FUNDING_URL, params={"symbol": symbol, "limit": 60})
    response.raise_for_status()
    return sorted((int(r["fundingTime"]), float(r["fundingRate"])) for r in response.json())


async def _load_flows(client: httpx.AsyncClient, asset: str) -> list[tuple[int, float, float, float]]:
    params = {"assets": asset, "metrics": "FlowInExNtv,FlowOutExNtv,SplyExNtv", "frequency": "1d",
              "page_size": 30, "paging_from": "end"}
    response = await client.get(COINMETRICS_URL, params=params)
    response.raise_for_status()
    out = []
    for row in response.json()["data"]:
        day = calendar.timegm(time.strptime(row["time"][:10], "%Y-%m-%d"))  # UTC midnight
        try:
            out.append((day * 1000, float(row["FlowInExNtv"]), float(row["FlowOutExNtv"]), float(row["SplyExNtv"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


FUNDING = Cached("Binance funding rate", FUNDING_CACHE_S, _load_funding)
FLOWS = Cached("Coin Metrics exchange flows", FLOWS_CACHE_S, _load_flows)


def average_funding(prints: list[tuple[int, float]], now: int, days: float = 7) -> float | None:
    """The average funding rate of the last ``days`` days up to ``now``, annualized in %. None without data."""
    known = [p for p in prints if p[0] <= now]
    if not known or now - known[-1][0] > FUNDING_MAX_AGE_S * 1000:
        return None
    if len(known) >= 2:  # 8 hours on Binance for ETH and BTC – measured, in case it ever changes
        gaps = sorted(b[0] - a[0] for a, b in zip(known, known[1:]))
        interval = gaps[len(gaps) // 2] or 8 * 3_600_000
    else:
        interval = 8 * 3_600_000
    recent = [rate for t, rate in known if t > now - days * DAY_S * 1000] or [known[-1][1]]
    per_year = 365 * DAY_S * 1000 / interval
    return sum(recent) / len(recent) * per_year * 100


def net_inflow(days: list[tuple[int, float, float, float]], now: int, window: int = 7) -> float | None:
    """Net coins sent to exchanges over the last ``window`` published days, in % of what the exchanges hold.
    A day counts from 06:00 UTC the morning after (it is published around 02:00); None without fresh data."""
    known = [d for d in days if d[0] + PUBLISHED_AFTER_MS <= now]
    if len(known) < window or now - known[-1][0] > FLOWS_MAX_AGE_S * 1000:
        return None
    last = known[-window:]
    supply = last[-1][3]
    if supply <= 0:
        return None
    return sum(inflow - outflow for _, inflow, outflow, _ in last) / supply * 100


async def funding(base: str, now: int, days: float = 7) -> float | None:
    """The average funding rate of ``base`` (ETH, BTC …) over ``days`` days, annualized in %. Overridden in tests."""
    prints = await FUNDING.get(f"{base.upper()}USDT")
    return average_funding(prints, now, days) if prints else None


async def exchange_inflow(base: str, now: int) -> float | None:
    """The 7-day net inflow of ``base`` onto exchanges in % of the exchange balance. Overridden in tests."""
    days = await FLOWS.get(base.lower())
    return net_inflow(days, now) if days else None
