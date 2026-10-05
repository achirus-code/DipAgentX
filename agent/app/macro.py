"""US unemployment rate for the monthly trend follower's "growth-trend timing" (public BLS data, no key needed)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("dipagentx.macro")

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
UNEMPLOYMENT_SERIES = "LNS14000000"  # unemployment rate, seasonally adjusted (monthly)
CACHE_S = 24 * 3600  # new figures come out once a month – one request a day is plenty (BLS allows 25 without a key)
RETRY_S = 2 * 3600  # after a failed request
MAX_AGE_S = 40 * 24 * 3600  # older data is not used any more

_cache: tuple[float, dict[str, float] | None] = (0.0, None)  # (fetched at, rate per "YYYY-MM")
_failed_at = 0.0


@dataclass
class Unemployment:
    month: str  # latest published month, "YYYY-MM"
    rate: float
    average: float  # of the 12 months up to and including ``month``

    @property
    def rising(self) -> bool:
        return self.rate > self.average


def parse_bls(data: Any) -> dict[str, float]:
    """{"2026-08": 4.1, …} from a BLS API answer (skips annual averages and missing values like "-")."""
    if not isinstance(data, dict) or data.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS: {data.get('message') if isinstance(data, dict) else data}")
    values: dict[str, float] = {}
    for series in data["Results"]["series"]:
        for row in series["data"]:
            period = str(row.get("period", ""))
            if not period.startswith("M") or period == "M13":
                continue
            try:
                values[f"{int(row['year']):04d}-{int(period[1:]):02d}"] = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
    return values


async def fetch_unemployment_rates() -> dict[str, float] | None:
    """Monthly unemployment rates of the last two to three years, cached; None when BLS can't be reached."""
    global _cache, _failed_at
    fetched_at, values = _cache
    now = time.time()
    if values and now - fetched_at < CACHE_S:
        return values
    if now - _failed_at < RETRY_S:
        return values if values and now - fetched_at < MAX_AGE_S else None
    year = time.gmtime(now).tm_year
    body = {"seriesid": [UNEMPLOYMENT_SERIES], "startyear": str(year - 2), "endyear": str(year)}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "DipAgentX"}) as client:
            response = await client.post(BLS_URL, json=body)
            response.raise_for_status()
            fresh = parse_bls(response.json())
        if not fresh:
            raise ValueError("BLS: no values")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("US unemployment rate not available: %s", exc)
        _failed_at = now
        return values if values and now - fetched_at < MAX_AGE_S else None
    _cache = (now, fresh)
    return fresh


def summarize(values: dict[str, float]) -> Unemployment | None:
    """The latest month against the average of the 12 months up to it (gaps skipped, at least 9 values)."""
    if not values:
        return None
    latest = max(values)
    year, month = map(int, latest.split("-"))
    window = []
    for back in range(12):
        y, m = divmod(year * 12 + month - 1 - back, 12)
        if (key := f"{y:04d}-{m + 1:02d}") in values:
            window.append(values[key])
    if len(window) < 9:
        return None
    return Unemployment(latest, values[latest], sum(window) / len(window))


async def unemployment() -> Unemployment | None:
    """The latest published US unemployment rate and its 12-month average. Overridden in tests."""
    values = await fetch_unemployment_rates()
    return summarize(values) if values else None
