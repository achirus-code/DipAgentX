"""Candlestick chart for the AI swing trader – a PNG that Claude looks at like a trader looks at the screen.

Three panels from top to bottom: 1-hour candles of the last 3 days (the bigger picture), 15-minute candles of the last
24 h and 5-minute candles of the last 3 h. Each panel shows the EMA20 (orange), EMA50 (blue), the VWAP since 00:00 UTC
(violet, intraday panels), volume bars, support/resistance (grey dashed), and the open position's entry (white),
stop (red) and take-profit (green). Prices are written on the right axis.

Pure standard library (zlib PNG encoder, a tiny bitmap font) – no image library needed in the container.
"""

from __future__ import annotations

import struct
import zlib
from typing import Iterable

from ..exchange import Candle
from .ai_analysis import ema_series, f

W, PANEL_H = 960, 300
AXIS_W = 78
PAD_TOP, VOL_H, GAP = 18, 44, 6

BG = (17, 19, 24)
GRID = (40, 44, 52)
TEXT = (170, 176, 186)
UP = (38, 166, 154)
DOWN = (239, 83, 80)
EMA20 = (255, 167, 38)
EMA50 = (66, 165, 245)
VWAP = (186, 104, 200)
LEVEL = (120, 126, 136)
ENTRY = (235, 235, 235)
STOP = (239, 83, 80)
TARGET = (102, 187, 106)

# 3×5 bitmap font: digits and the few letters of the panel titles
FONT = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111", ".": "000000000000010", "-": "000000111000000",
    ":": "000010000010000", " ": "000000000000000", "H": "101101111101101", "M": "101111111101101",
    "D": "110101101101110", "E": "111100110100111", "A": "010101111101101", "V": "101101101101010",
    "W": "101101101111101", "P": "111101111100100", "S": "111100111001111", "T": "111010010010010",
    "O": "111101101101111", "R": "110101110101101", "G": "111100101101111", "N": "101111111111101",
    "x": "000101010101000", "L": "100100100100111", "U": "101101101101111", "I": "111010010010111",
    "C": "111100100100111", "K": "101101110101101", "B": "110101110101110", "F": "111100110100100",
}


class Canvas:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.px = bytearray(bytes(BG) * width * height)

    def dot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(color)

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        x0, x1 = max(0, min(x0, x1)), min(self.w - 1, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(self.h - 1, max(y0, y1))
        row = bytes(color) * (x1 - x0 + 1)
        for y in range(y0, y1 + 1):
            i = (y * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def hline(self, x0: int, x1: int, y: int, color: tuple[int, int, int], dash: int = 0) -> None:
        for x in range(x0, x1 + 1):
            if not dash or (x // dash) % 2 == 0:
                self.dot(x, y, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.dot(x0, y0, color)
            self.dot(x0, y0 + 1, color)  # 2 px thick
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def text(self, x: int, y: int, s: str, color: tuple[int, int, int], scale: int = 2) -> None:
        for ch in s:
            glyph = FONT.get(ch, FONT[" "])
            for i, bit in enumerate(glyph):
                if bit == "1":
                    self.rect(x + (i % 3) * scale, y + (i // 3) * scale,
                              x + (i % 3) * scale + scale - 1, y + (i // 3) * scale + scale - 1, color)
            x += 4 * scale

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def price_label(value: float) -> str:
    digits = 2 if value >= 100 else 4 if value >= 1 else 6
    return f"{value:.{digits}f}"


def draw_panel(cv: Canvas, top: int, title: str, candles: list[Candle], price: float,
               lines: dict[str, tuple[float, tuple[int, int, int], int]], with_vwap: bool, visible: int) -> None:
    """One panel: the last ``visible`` candles with EMAs and VWAP (computed on the whole series), volume and
    horizontal lines (label → (price, color, dash))."""
    if not candles:
        return
    chart_w = W - AXIS_W - 10
    price_h = PANEL_H - PAD_TOP - VOL_H - GAP
    closes = [f(c.close) for c in candles]
    e20, e50 = ema_series(closes, 20)[-visible:], ema_series(closes, 50)[-visible:]
    vwap = session_vwap(candles)[-visible:] if with_vwap else None
    candles = candles[-visible:]
    in_view = [v for v, _, _ in lines.values() if v]
    lo = min([f(c.low) for c in candles] + [price])
    hi = max([f(c.high) for c in candles] + [price])
    # lines close to the range stay visible; far-away levels are left out instead of squashing the candles
    span = hi - lo or price * 0.001
    for v in in_view + [v for v in (e20 or []) + (vwap or []) if v]:
        if lo - span * 0.25 <= v <= hi + span * 0.25:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.04 or price * 0.0005
    lo, hi = lo - pad, hi + pad

    def y(v: float) -> int:
        return top + PAD_TOP + int((hi - v) / (hi - lo) * price_h)

    labels: list[tuple[int, int, float, tuple[int, int, int]]] = []  # (priority, y, price, color) – drawn last
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        cv.hline(10, 10 + chart_w, y(v), GRID, dash=4)
        labels.append((3, y(v), v, TEXT))
    cv.text(12, top + 2, title, TEXT)
    n = len(candles)
    step = chart_w / max(n, 1)
    body_w = max(1, int(step * 0.7))
    x_of = lambda i: 10 + int(i * step + step / 2)  # noqa: E731
    max_vol = max((f(c.volume) for c in candles), default=0)
    vol_base = top + PANEL_H - 2
    for i, c in enumerate(candles):
        x = x_of(i)
        color = UP if c.close >= c.open else DOWN
        cv.rect(x, y(f(c.high)), x, y(f(c.low)), color)
        cv.rect(x - body_w // 2, y(f(max(c.open, c.close))), x - body_w // 2 + body_w - 1,
                y(f(min(c.open, c.close))), color)
        if max_vol > 0 and c.volume > 0:
            h = max(1, int(f(c.volume) / max_vol * (VOL_H - 4)))
            cv.rect(x - body_w // 2, vol_base - h, x - body_w // 2 + body_w - 1, vol_base, tuple(v // 2 for v in color))
    for series, color in ((e50, EMA50), (e20, EMA20), (vwap, VWAP)):
        pts = [(x_of(i), y(v)) if v and lo <= v <= hi else None for i, v in enumerate(series or [])]
        for a, b in zip(pts, pts[1:]):
            if a and b:  # clipped to the price area – far-away parts of a line are left out
                cv.line(a[0], a[1], b[0], b[1], color)
    for label, (v, color, dash) in lines.items():
        if v and lo <= v <= hi:
            cv.hline(10, 10 + chart_w, y(v), color, dash=dash)
            labels.append((2 if color == LEVEL else 1, y(v), v, color))
    # the live price, then the other labels where there is room
    cv.hline(10 + chart_w - 30, 10 + chart_w, y(price), ENTRY)
    cv.rect(W - AXIS_W + 1, y(price) - 7, W - 2, y(price) + 7, (60, 64, 72))
    cv.text(W - AXIS_W + 4, y(price) - 5, price_label(price), ENTRY)
    taken = [y(price)]
    for _, ly, v, color in sorted(labels, key=lambda label: label[0]):
        if all(abs(ly - t) >= 13 for t in taken) and top + 6 <= ly <= top + PANEL_H - 8:
            cv.text(W - AXIS_W + 4, ly - 5, price_label(v), color)
            taken.append(ly)
    cv.hline(0, W - 1, top + PANEL_H - 1, GRID)


def session_vwap(candles: list[Candle]) -> list[float | None]:
    """VWAP restarting at 00:00 UTC, per candle (None without volume)."""
    out: list[float | None] = []
    day, pv, vol = None, 0.0, 0.0
    for c in candles:
        d = c.start // 86_400_000
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        v = f(c.volume)
        pv += (f(c.high) + f(c.low) + f(c.close)) / 3 * v
        vol += v
        out.append(pv / vol if vol else None)
    return out


def render(panels: Iterable[tuple[str, list[Candle], bool] | tuple[str, list[Candle], bool, int]], price: float,
           levels: list[float], entry: float | None, stop: float | None, target: float | None) -> bytes:
    """The chart as PNG bytes. ``panels``: (title, candles, with VWAP[, number of candles shown]) – the lines are
    computed on all candles, so a short panel still has its EMAs from the first candle on."""
    panels = list(panels)
    cv = Canvas(W, PANEL_H * len(panels))
    lines: dict[str, tuple[float, tuple[int, int, int], int]] = {
        f"level{i}": (v, LEVEL, 6) for i, v in enumerate(levels)
    }
    if entry:
        lines["entry"] = (entry, ENTRY, 3)
    if stop:
        lines["stop"] = (stop, STOP, 0)
    if target:
        lines["target"] = (target, TARGET, 0)
    for i, (title, candles, with_vwap, *visible) in enumerate(panels):
        draw_panel(cv, i * PANEL_H, title, candles, price, lines, with_vwap, visible[0] if visible else len(candles))
    return cv.png()
