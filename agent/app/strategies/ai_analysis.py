"""Market analysis for the AI day trader – what a day trader reads off the charts before deciding, computed from the
exchange's candles so that Claude gets the facts precisely (the chart image shows the same data as a picture).

Only closed candles are analysed; the forming candle is left out and the live price comes from the ticker.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..exchange import Candle

DAY_MS = 86_400_000


def closed(candles: list[Candle], interval: int, now: int) -> list[Candle]:
    return [c for c in candles if c.start + interval * 60_000 <= now]


def f(value: Decimal | float) -> float:
    return float(value)


def ema_series(values: list[float], n: int) -> list[float | None]:
    """EMA for every value (None until there are ``n`` values)."""
    out: list[float | None] = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def ema(values: list[float], n: int) -> float | None:
    return ema_series(values, n)[-1] if values else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:n], closes[1:n + 1]):
        gains += max(b - a, 0)
        losses += max(a - b, 0)
    avg_gain, avg_loss = gains / n, losses / n
    for a, b in zip(closes[n:], closes[n + 1:]):
        avg_gain = (avg_gain * (n - 1) + max(b - a, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(a - b, 0)) / n
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def true_ranges(candles: list[Candle]) -> list[float]:
    return [max(f(c.high) - f(c.low), abs(f(c.high) - f(p.close)), abs(f(c.low) - f(p.close)))
            for p, c in zip(candles, candles[1:])]


def atr(candles: list[Candle], n: int = 14) -> float | None:
    """Average true range (Wilder) in price units."""
    tr = true_ranges(candles)
    if len(tr) < n:
        return None
    a = sum(tr[:n]) / n
    for t in tr[n:]:
        a = (a * (n - 1) + t) / n
    return a


def adx(candles: list[Candle], n: int = 14) -> float | None:
    """Average directional index: trend strength 0–100 (below 20 no trend, above 25 a trend)."""
    if len(candles) < 2 * n + 1:
        return None
    plus_dm, minus_dm = [], []
    for p, c in zip(candles, candles[1:]):
        up, down = f(c.high) - f(p.high), f(p.low) - f(c.low)
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr = true_ranges(candles)

    def smooth(values: list[float]) -> list[float]:
        s = sum(values[:n])
        out = [s]
        for v in values[n:]:
            s = s - s / n + v
            out.append(s)
        return out

    s_tr, s_plus, s_minus = smooth(tr), smooth(plus_dm), smooth(minus_dm)
    dx = []
    for t, pl, mi in zip(s_tr, s_plus, s_minus):
        if t <= 0:
            dx.append(0.0)
            continue
        di_plus, di_minus = 100 * pl / t, 100 * mi / t
        total = di_plus + di_minus
        dx.append(100 * abs(di_plus - di_minus) / total if total else 0.0)
    if len(dx) < n:
        return None
    a = sum(dx[:n]) / n
    for d in dx[n:]:
        a = (a * (n - 1) + d) / n
    return a


def efficiency_ratio(closes: list[float], n: int = 20) -> float | None:
    """Net move / path length over ``n`` candles: near 1 a clean trend, near 0 chop."""
    if len(closes) <= n:
        return None
    window = closes[-n - 1:]
    path = sum(abs(b - a) for a, b in zip(window, window[1:]))
    return abs(window[-1] - window[0]) / path if path else 0.0


def swings(candles: list[Candle], k: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing highs and lows (a high above the ``k`` candles on either side) as (index, price)."""
    highs, lows = [], []
    for i in range(k, len(candles) - k):
        window = candles[i - k:i + k + 1]
        if candles[i].high == max(c.high for c in window) and candles[i].high > candles[i - 1].high:
            highs.append((i, f(candles[i].high)))
        if candles[i].low == min(c.low for c in window) and candles[i].low < candles[i - 1].low:
            lows.append((i, f(candles[i].low)))
    return highs, lows


def structure(candles: list[Candle]) -> str:
    """Market structure from the last two swing highs and lows."""
    highs, lows = swings(candles)
    if len(highs) < 2 or len(lows) < 2:
        return "unclear"
    hh, hl = highs[-1][1] > highs[-2][1], lows[-1][1] > lows[-2][1]
    if hh and hl:
        return "higher highs and higher lows"
    if not hh and not hl:
        return "lower highs and lower lows"
    return "higher lows, lower highs (contracting)" if hl else "lower lows, higher highs (expanding)"


def candle_patterns(candles: list[Candle], atr_value: float | None) -> list[str]:
    """Plain-language description of the last three closed candles."""
    out = []
    for back, c in zip((3, 2, 1), candles[-3:]):
        o, h, low, cl = f(c.open), f(c.high), f(c.low), f(c.close)
        rng = h - low
        if rng <= 0:
            continue
        body = abs(cl - o)
        upper, lower = h - max(o, cl), min(o, cl) - low
        prev = candles[-back - 1] if len(candles) > back else None
        name = "bullish" if cl > o else "bearish" if cl < o else "flat"
        if body <= 0.1 * rng:
            name = "doji"
        elif lower >= 2 * body and upper <= body:
            name = "hammer (long lower wick)"
        elif upper >= 2 * body and lower <= body:
            name = "shooting star (long upper wick)"
        elif prev is not None and cl > o and f(prev.close) < f(prev.open) and cl >= f(prev.open) and o <= f(prev.close):
            name = "bullish engulfing"
        elif prev is not None and cl < o and f(prev.close) > f(prev.open) and cl <= f(prev.open) and o >= f(prev.close):
            name = "bearish engulfing"
        elif prev is not None and h <= f(prev.high) and low >= f(prev.low):
            name = f"inside bar ({name})"
        if atr_value and rng >= 1.8 * atr_value and body >= 0.6 * rng:
            name = f"wide-range {name} ({rng / atr_value:.1f}x ATR)"
        out.append(f"{back} ago: {name}")
    return out


def timeframe(candles: list[Candle], label: str, price: float) -> dict[str, Any]:
    """Trend, momentum and volatility of one timeframe."""
    closes = [f(c.close) for c in candles]
    e20s = ema_series(closes, 20)
    e20, e50 = e20s[-1] if e20s else None, ema(closes, 50)
    slope = None
    if len(e20s) > 5 and e20s[-1] and e20s[-6]:
        slope = (e20s[-1] / e20s[-6] - 1) * 100
    a = atr(candles)
    st = structure(candles)
    strength = adx(candles)
    er = efficiency_ratio(closes)
    if e20 and e50 and slope is not None:
        if e20 > e50 and slope > 0 and price > e50 and not st.startswith("lower highs and lower"):
            trend = "up"
        elif e20 < e50 and slope < 0 and price < e50 and not st.startswith("higher highs and higher"):
            trend = "down"
        else:
            trend = "sideways"
    else:
        trend = "unknown"
    if trend in ("up", "down") and strength is not None and strength < 18:
        trend += " (weak)"
    rel = lambda v: round((v / price - 1) * 100, 3) if v and price else None  # noqa: E731
    return {
        "timeframe": label,
        "trend": trend,
        "structure": st,
        "ema20_vs_price_pct": rel(e20),
        "ema50_vs_price_pct": rel(e50),
        "ema20_slope_5_candles_pct": round(slope, 3) if slope is not None else None,
        "rsi14": round(r, 1) if (r := rsi(closes)) is not None else None,
        "adx14": round(strength, 1) if strength is not None else None,
        "efficiency_ratio_20": round(er, 2) if er is not None else None,
        "atr14_pct": round(a / price * 100, 3) if a and price else None,
        "last_candles": candle_patterns(candles, a),
    }


def regime(tf: dict[str, dict[str, Any]]) -> str:
    """One label for the market phase, from the 15-minute and 1-hour timeframes."""
    t15, t1h = tf.get("15m", {}), tf.get("1h", {})
    er, strength = t15.get("efficiency_ratio_20") or 0, t15.get("adx14") or 0
    up = [t.get("trend", "").startswith("up") for t in (t15, t1h)]
    down = [t.get("trend", "").startswith("down") for t in (t15, t1h)]
    if all(up):
        return "uptrend (15m and 1h agree)"
    if all(down):
        return "downtrend (15m and 1h agree)"
    if er < 0.2 and strength < 20:
        return "choppy range – no direction"
    if any(up) and not any(down):
        return "mixed, leaning up"
    if any(down) and not any(up):
        return "mixed, leaning down"
    return "range / transition"


def levels(candles: list[Candle], price: float, atr_value: float | None) -> dict[str, list[dict[str, Any]]]:
    """Support below and resistance above the price from swing points, clustered (nearest three each)."""
    highs, lows = swings(candles)
    points = [p for _, p in highs + lows]
    tolerance = max((atr_value or 0) * 0.5, price * 0.0015)
    clusters: list[list[float]] = []
    for p in sorted(points):
        if clusters and p - clusters[-1][-1] <= tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    zones = [{"price": round(statistics.fmean(c), 8), "touches": len(c)} for c in clusters]
    for z in zones:
        z["distance_pct"] = round((z["price"] / price - 1) * 100, 2)
    support = sorted((z for z in zones if z["price"] < price), key=lambda z: -z["price"])[:3]
    resistance = sorted((z for z in zones if z["price"] > price), key=lambda z: z["price"])[:3]
    return {"support": support, "resistance": resistance}


def session(candles: list[Candle], now: int, price: float) -> dict[str, Any]:
    """Previous UTC day's high/low/close, today's open and the volume-weighted average price since 00:00 UTC."""
    today = now - now % DAY_MS
    prev = [c for c in candles if today - DAY_MS <= c.start < today]
    cur = [c for c in candles if c.start >= today]
    out: dict[str, Any] = {}
    if prev:
        out.update(previous_day_high=f(max(c.high for c in prev)), previous_day_low=f(min(c.low for c in prev)),
                   previous_day_close=f(prev[-1].close))
    if cur:
        out["today_open"] = f(cur[0].open)
        volume = sum(f(c.volume) for c in cur)
        if volume > 0:
            vwap = sum((f(c.high) + f(c.low) + f(c.close)) / 3 * f(c.volume) for c in cur) / volume
            out["vwap_today"] = vwap
            out["price_vs_vwap_pct"] = round((price / vwap - 1) * 100, 3)
    return out


def volume_profile(candles: list[Candle]) -> dict[str, Any] | None:
    """Relative volume of the last candles and whether volume comes with rising or falling candles."""
    vols = [f(c.volume) for c in candles]
    if len(vols) < 30 or sum(vols) <= 0:
        return None
    base = statistics.fmean(vols[-51:-3]) if len(vols) > 50 else statistics.fmean(vols[:-3])
    recent = candles[-24:]
    up = sum(f(c.volume) for c in recent if c.close >= c.open)
    down = sum(f(c.volume) for c in recent if c.close < c.open)
    return {
        "last_candle_vs_average": round(vols[-1] / base, 2) if base else None,
        "last_3_candles_vs_average": round(statistics.fmean(vols[-3:]) / base, 2) if base else None,
        "up_vs_down_volume_last_2h": round(up / down, 2) if down else None,
    }


def squeeze(candles: list[Candle]) -> dict[str, Any] | None:
    """Bollinger band width now vs. its range over the series – a squeeze often comes before a big move."""
    closes = [f(c.close) for c in candles]
    if len(closes) < 40:
        return None
    widths = []
    for i in range(20, len(closes) + 1):
        w = closes[i - 20:i]
        mid = statistics.fmean(w)
        widths.append(4 * statistics.pstdev(w) / mid if mid else 0)
    now_w = widths[-1]
    rank = sum(1 for w in widths if w <= now_w) / len(widths)
    mid, sd = statistics.fmean(closes[-20:]), statistics.pstdev(closes[-20:])
    return {
        "bandwidth_percentile": round(rank * 100),
        "position_in_bands": round((closes[-1] - mid) / (2 * sd), 2) if sd else 0.0,  # -1 lower, +1 upper band
    }


def order_book_summary(book: tuple[list, list] | None, price: float) -> dict[str, Any] | None:
    """Depth within 0.25 % and 1 % of the price on both sides, and the biggest wall nearby."""
    if not book:
        return None
    bids, asks = book
    if not bids or not asks:
        return None

    def depth(rows: list, pct: float, side: int) -> float:
        limit = price * (1 - side * pct / 100)
        return sum(f(p) * f(q) for p, q in rows if (f(p) >= limit if side > 0 else f(p) <= limit))

    out: dict[str, Any] = {}
    for pct in (0.25, 1.0):
        b, a = depth(bids, pct, 1), depth(asks, pct, -1)
        out[f"bid_depth_{pct}pct"] = round(b)
        out[f"ask_depth_{pct}pct"] = round(a)
        out[f"imbalance_{pct}pct"] = round((b - a) / (b + a), 2) if b + a else None
    near = [r for r in bids + asks if abs(f(r[0]) / price - 1) <= 0.01]
    if near:
        wall = max(near, key=lambda r: f(r[0]) * f(r[1]))
        out["largest_order_within_1pct"] = {"price": f(wall[0]), "value": round(f(wall[0]) * f(wall[1])),
                                            "side": "bid" if wall in bids else "ask"}
    return out


@dataclass
class Signal:
    key: str
    text: str


def scan(c5: list[Candle], tf: dict[str, dict[str, Any]], sess: dict[str, Any], price: float) -> list[Signal]:
    """Setups worth a closer look by Claude – cheap rules on the closed 5-minute candles. They only wake Claude early;
    Claude decides whether there is a trade."""
    out: list[Signal] = []
    if len(c5) < 30:
        return out
    last = c5[-1]
    prior = c5[-25:-1]
    vols = [f(c.volume) for c in c5[-50:-1]]
    avg_vol = statistics.fmean(vols) if vols and sum(vols) > 0 else 0
    rel_vol = f(last.volume) / avg_vol if avg_vol else None
    hi, lo = max(f(c.high) for c in prior), min(f(c.low) for c in prior)
    if f(last.close) > hi and (rel_vol is None or rel_vol >= 1.5):
        out.append(Signal("breakout", "5m close above the 2 h high" + (f" on {rel_vol:.1f}x volume" if rel_vol else "")))
    if f(last.close) < lo and (rel_vol is None or rel_vol >= 1.5):
        out.append(Signal("breakdown", "5m close below the 2 h low" + (f" on {rel_vol:.1f}x volume" if rel_vol else "")))
    t15, t1h, t5 = tf.get("15m", {}), tf.get("1h", {}), tf.get("5m", {})
    bullish_close = f(last.close) > f(last.open)
    if t1h.get("trend", "").startswith("up") and not t15.get("trend", "").startswith("down"):
        near_ema = t15.get("ema20_vs_price_pct") is not None and abs(t15["ema20_vs_price_pct"]) <= max(
            0.6 * (t15.get("atr14_pct") or 0), 0.15)
        near_vwap = sess.get("price_vs_vwap_pct") is not None and abs(sess["price_vs_vwap_pct"]) <= 0.2
        if (near_ema or near_vwap) and (t5.get("rsi14") or 50) < 50 and bullish_close:
            out.append(Signal("pullback", "pullback to the 15m EMA20/VWAP in a 1 h uptrend, 5m turning up"))
    if (t15.get("rsi14") or 50) < 30 and bullish_close and (rel_vol or 0) >= 2:
        out.append(Signal("capitulation", "15m RSI below 30 and a 5m reversal candle on high volume"))
    if rel_vol and rel_vol >= 3 and not out:
        out.append(Signal("volume_spike", f"5m volume {rel_vol:.1f}x the average"))
    return out


def utc(now: int) -> str:
    return datetime.fromtimestamp(now / 1000, tz=timezone.utc).strftime("%a %Y-%m-%d %H:%M UTC")
