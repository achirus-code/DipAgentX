"""Economic data for the monthly trend follower – all public, no key needed:

- US unemployment rate (BLS) and weekly initial jobless claims (US Department of Labor): is a recession coming?
- US Treasury yield curve (US Treasury): 10 years below 3 months is the classic recession warning
- 3-month Euribor (ECB): what money earns while it waits – the hurdle for "return better than the cash rate"
- the euro in US dollars at month end (ECB): whether to hold the currency-hedged share class
"""

from __future__ import annotations

import calendar
import csv
import io
import logging
import re
import time
from collections.abc import Awaitable, Callable
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


# --- the newer feeds: one request a day each, the last good answer is kept through outages ---------------------

ECB_URL = "https://data-api.ecb.europa.eu/service/data/{flow}/{key}"
EURIBOR_KEY = ("FM", "M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA")  # 3-month Euribor, monthly average
EURUSD_KEY = ("EXR", "M.USD.EUR.SP00.E")  # US dollars per euro, end of month
DOL_URL = "https://oui.doleta.gov/unemploy/wkclaims/report.asp"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")


class Feed:
    """A daily cached download. ``get()`` gives the values, the last good ones during an outage (up to 40 days),
    else None."""

    def __init__(self, name: str, load: Callable[[httpx.AsyncClient], Awaitable[dict]]):
        self.name = name
        self.load = load
        self.cache: tuple[float, dict | None] = (0.0, None)
        self.failed_at = 0.0

    def reset(self) -> None:
        self.cache, self.failed_at = (0.0, None), 0.0

    async def get(self) -> dict | None:
        fetched_at, values = self.cache
        now = time.time()
        if values and now - fetched_at < CACHE_S:
            return values
        if now - self.failed_at < RETRY_S:
            return values if values and now - fetched_at < MAX_AGE_S else None
        try:
            async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "DipAgentX"},
                                         follow_redirects=True) as client:
                fresh = await self.load(client)
            if not fresh:
                raise ValueError("no values")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            log.warning("%s not available: %s", self.name, exc)
            self.failed_at = now
            return values if values and now - fetched_at < MAX_AGE_S else None
        self.cache = (now, fresh)
        return fresh


def month_key(t: float) -> str:
    g = time.gmtime(t)
    return f"{g.tm_year:04d}-{g.tm_mon:02d}"


def months_before(key: str, n: int) -> str:
    year, month = map(int, key.split("-"))
    y, m = divmod(year * 12 + month - 1 - n, 12)
    return f"{y:04d}-{m + 1:02d}"


def parse_ecb_csv(text: str) -> dict[str, float]:
    """{"2026-09": 2.635, …} from the ECB data API's CSV."""
    rows = list(csv.DictReader(io.StringIO(text)))
    out = {}
    for row in rows:
        try:
            out[str(row["TIME_PERIOD"])[:7]] = float(row["OBS_VALUE"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def _load_ecb(client: httpx.AsyncClient, flow_key: tuple[str, str], n: int) -> dict[str, float]:
    flow, key = flow_key
    r = await client.get(ECB_URL.format(flow=flow, key=key), params={"lastNObservations": n, "format": "csvdata"})
    r.raise_for_status()
    return parse_ecb_csv(r.text)


EURIBOR = Feed("3-month Euribor (ECB)", lambda c: _load_ecb(c, EURIBOR_KEY, 36))
EURUSD = Feed("EUR/USD (ECB)", lambda c: _load_ecb(c, EURUSD_KEY, 15))


@dataclass
class CashReturn:
    months: int
    total: float  # what cash earned over ``months`` (0.021 = 2.1 %)
    latest_month: str
    latest_rate: float  # % p. a.


def cash_return(rates: dict[str, float], months: int) -> CashReturn | None:
    """What money earned in the last ``months`` months at the monthly Euribor averages (compounded)."""
    if not rates:
        return None
    latest = max(rates)
    window = [rates.get(months_before(latest, back)) for back in range(months)]
    if any(r is None for r in window):
        return None
    total = 1.0
    for r in window:
        total *= 1 + max(r, 0.0) / 100 / 12
    return CashReturn(months, total - 1, latest, rates[latest])


async def euro_cash(months: int) -> CashReturn | None:
    """The cash return of the last ``months`` months from the 3-month Euribor. Overridden in tests."""
    rates = await EURIBOR.get()
    return cash_return(rates, months) if rates else None


@dataclass
class EuroTrend:
    month: str  # latest month end
    rate: float  # US dollars per euro
    average: float  # of the 12 month ends up to and including ``month``

    @property
    def euro_rising(self) -> bool:
        """Euro above its average = the dollar in a downtrend: the currency-hedged share class is held."""
        return self.rate > self.average


def euro_trend(values: dict[str, float]) -> EuroTrend | None:
    if not values:
        return None
    latest = max(values)
    window = [values.get(months_before(latest, back)) for back in range(12)]
    if any(v is None for v in window):
        return None
    return EuroTrend(latest, values[latest], sum(window) / 12)


async def eurusd() -> EuroTrend | None:
    """The euro's month-end rate in US dollars against its 12-month average. Overridden in tests."""
    values = await EURUSD.get()
    return euro_trend(values) if values else None


# --- initial jobless claims (weekly, US Department of Labor) ---


def parse_dol_xml(text: str) -> dict[str, float]:
    """{"2026-09-05": 177695.0, …}: initial claims, not seasonally adjusted, per week (ending Saturday)."""
    out = {}
    for week in re.findall(r"<week>(.*?)</week>", text, re.S):
        ended = re.search(r"<weekEnded>(\d\d)/(\d\d)/(\d{4})</weekEnded>", week)
        nsa = re.search(r"<InitialClaims>.*?<NSA>([\d,]+)</NSA>", week, re.S)
        if ended and nsa:
            mon, day, year = ended.groups()
            out[f"{year}-{mon}-{day}"] = float(nsa.group(1).replace(",", ""))
    if not out and "<week>" not in text:
        raise ValueError("DOL: no weekly data")
    return out


def monthly_claims(weekly: dict[str, float]) -> dict[str, float]:
    """The average weekly claims of each complete month (all weeks ending in it reported)."""
    by_month: dict[str, list[tuple[str, float]]] = {}
    for date, value in weekly.items():
        by_month.setdefault(date[:7], []).append((date, value))
    out = {}
    for key, weeks in by_month.items():
        year, month = map(int, key.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        last_saturday = max(d for d in range(last_day - 6, last_day + 1) if calendar.weekday(year, month, d) == 5)
        if f"{key}-{last_saturday:02d}" in weekly:
            out[key] = sum(v for _, v in weeks) / len(weeks)
    return out


async def _load_claims(client: httpx.AsyncClient) -> dict[str, float]:
    year = time.gmtime(time.time()).tm_year
    r = await client.post(DOL_URL, data={"level": "nat", "strtdate": str(year - 2), "enddate": str(year),
                                         "filetype": "xml", "final": "Submit"})
    r.raise_for_status()
    return parse_dol_xml(r.text)


CLAIMS = Feed("US initial jobless claims (DOL)", _load_claims)
CLAIMS_RISE = 0.05  # more than 5 % above the same month a year earlier counts as rising


@dataclass
class Claims:
    month: str
    average: float  # weekly average of the month
    year_ago: float

    @property
    def change(self) -> float:
        return self.average / self.year_ago - 1

    @property
    def rising(self) -> bool:
        return self.change > CLAIMS_RISE


def claims_summary(weekly: dict[str, float]) -> Claims | None:
    monthly = monthly_claims(weekly)
    for key in sorted(monthly, reverse=True):
        if (ago := monthly.get(months_before(key, 12))) is not None:
            return Claims(key, monthly[key], ago)
    return None


async def claims() -> Claims | None:
    """The latest complete month of US initial jobless claims against a year earlier. Overridden in tests."""
    weekly = await CLAIMS.get()
    return claims_summary(weekly) if weekly else None


# --- US Treasury yield curve (daily, US Treasury) ---


def parse_treasury_csv(text: str) -> dict[str, tuple[float, float]]:
    """{"2026-10-02": (3-month yield, 10-year yield), …}"""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            mon, day, year = row["Date"].split("/")
            out[f"{year}-{mon}-{day}"] = (float(row["3 Mo"]), float(row["10 Yr"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def _load_curve(client: httpx.AsyncClient) -> dict[str, tuple[float, float]]:
    year = time.gmtime(time.time()).tm_year
    out: dict[str, tuple[float, float]] = {}
    for y in (year - 2, year - 1, year):
        r = await client.get(TREASURY_URL.format(year=y))
        r.raise_for_status()
        out.update(parse_treasury_csv(r.text))
    return out


CURVE = Feed("US Treasury yield curve", _load_curve)
CURVE_MONTHS = 24  # an inversion counts as a warning for two years


@dataclass
class Curve:
    month: str  # latest complete month
    spread: float  # 10 years minus 3 months at its end, percentage points
    last_inverted: str | None  # the latest month end within CURVE_MONTHS with 10 years below 3 months

    @property
    def warning(self) -> bool:
        return self.last_inverted is not None


def curve_summary(daily: dict[str, tuple[float, float]], now: float | None = None) -> Curve | None:
    """Month-end spreads of the completed months; inverted at any of the last 24 month ends = warning."""
    current = month_key(time.time() if now is None else now)
    ends: dict[str, float] = {}
    for date in sorted(daily):
        if date[:7] < current:
            short, long = daily[date]
            ends[date[:7]] = long - short
    if not ends:
        return None
    latest = max(ends)
    window = [months_before(latest, back) for back in range(CURVE_MONTHS)]
    if sum(1 for k in window if k in ends) < CURVE_MONTHS - 2:
        return None
    inverted = [k for k in window if ends.get(k, 0.0) < 0]
    return Curve(latest, ends[latest], max(inverted) if inverted else None)


async def yield_curve() -> Curve | None:
    """Whether the US yield curve was inverted in the last two years. Overridden in tests."""
    daily = await CURVE.get()
    return curve_summary(daily) if daily else None
