"""AI swing trader: Claude (Fable 5.1 by default) trades one pair the way the backtest says it paid off – entries from
the day trader's playbook, held like swing trades.

- Top-down market read: trend and market phase on 4 h, 1 h, 15 min and 5 min, support/resistance, VWAP, the previous
  day's range, volume, candle patterns, the order book and BTC as the market leader (``ai_analysis``) – plus the
  chart as an image (``ai_chart``), so Claude sees the candles like a trader on the screen.
- The backtest (Binance ETH-EUR/BTC-EUR 5-minute candles 2020–2026, docs/ki-swingtrader.md) shapes the rules: the
  scanner wakes Claude only in the regime that made money (4 h uptrend, 1 h ADX ≥ 25) and only for the setups that
  did (breakouts of the 2 h/24 h high on volume, pullbacks in a 1 h uptrend); the brief carries the backtested stop
  (below the last 1 h swing low) and target (3R) and the track record of every setup; the prompt asks for swing
  trades of hours to days, no break-even stop, no trailing stop, no time exit.
- Every buy comes with a plan – take-profit, stop, optional trailing stop and time limit – that the bot runs every
  tick by itself; the stop is never lowered and never further away than the max. stop-loss (5 %).
- Discipline in code: a daily loss limit, a pause after a losing streak, position size by setup quality (25–100 % of
  the amount). Claude sees its own results by setup and keeps notes from one check to the next.

Orders go out only as fee-free limit orders (post-only, a cent inside the spread, following the price like the
momentum bot) – an order that isn't filled within the waiting time is cancelled, never sent to the market.
"""

from __future__ import annotations

import base64
import calendar
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import anthropic
import httpx
from pydantic import BaseModel, Field

from ..i18n import L, dur, m, money, pct
from . import ai_analysis as ta
from . import ai_chart
from .base import COOLDOWN_HELP, COOLDOWN_LABEL, Buy, Context, Decision, Option, Param, Sell, Strategy, cooldown_left

log = logging.getLogger("dipagentx")

DEFAULT_MODEL = "claude-fable-5-1"
# $ per million tokens: input, output, cache read (cache writes cost 1.25 × input). Fallback models are priced by
# the model that answered; an unknown model is priced like the most expensive one.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
WEB_SEARCH_USD = 0.01  # per search
# first guess of what one check costs (brief + chart, mixed effort) – replaced by the measured average after the first call
COST_GUESS = {"claude-fable-5-1": 0.12, "claude-opus-5-5": 0.05, "claude-sonnet-5-5": 0.025, "claude-haiku-5-5": 0.002}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# the anthropic SDK also accepts an OAuth token; both end up here as environment variables
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
RETRY_AUTH_MS = 60 * 60_000
RETRY_RATE_LIMIT_MS = 5 * 60_000
MIN_WAKE_MOVE = 0.4  # % – the bot wakes Claude early on a move at least this large (or 3 × the 5-minute ATR)
MAX_GAP_MS = 4 * 3_600_000  # Claude looks at least every 4 h, unless the budget only allows less
TRIGGER_TTL_MS = 15 * 60_000  # a scanner signal older than this no longer wakes Claude
LOSS_STREAK_PAUSE_MS = 2 * 3_600_000
HISTORY = 30  # closed trades kept for the statistics
RECENT = 8  # of which Claude sees the details
DAY_MS = 86_400_000
SETUPS = ("trend_pullback", "breakout", "breakout_retest", "range_support", "reversal", "momentum", "none")

# Crypto Fear & Greed index (alternative.me, free, no key). It is updated once a day – cached for an hour.
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=7"
FEAR_GREED_CACHE_S = 3600
_fear_greed_cache: tuple[float, dict[str, Any] | None] = (0.0, None)

SENTIMENT_INFO = (
    "The brief includes the Crypto Fear & Greed index of the market as a whole (0 = extreme fear, 100 = extreme "
    "greed; today first, then the previous days). It is daily background, not an intraday signal."
)
SENTIMENT_CONTRARIAN = (
    "The brief includes the Crypto Fear & Greed index of the market as a whole (0 = extreme fear, 100 = extreme "
    "greed; today first, then the previous days). The owner wants it used as a contrarian bias only at extremes: "
    "below 25 favour buying panic flushes and avoid panic selling, above 75 take profits sooner and be choosier with "
    "new buys. In between, ignore it."
)

SYSTEM_PROMPT = """You are the swing trader of one crypto spot pair on Revolut X, running inside an automated bot. \
The goal is to grow the capital with trades that have a positive expectancy. Your rules come from a backtest of \
this very playbook on six years of ETH-EUR and BTC-EUR data (the brief carries the numbers): intraday trading with \
tight stops lost money in every variant; the same entries held for hours to days with a stop below the 1-hour swing \
low and a 3R target made money in every period. So you trade like a swing trader with a day trader's entry: \
patient, few trades, wide enough stops, targets that pay for the losers. Most of the time the right action is to \
wait. Being flat is a position.

## What you get at every check
- A chart image with three panels, top to bottom: 1-hour candles of the last 3 days, 15-minute candles of the last \
24 h, 5-minute candles of the last 3 h. Green/red candles, volume bars at the bottom of each panel, EMA20 orange, \
EMA50 blue, VWAP since 00:00 UTC violet, support/resistance grey dashed, the open position's entry white dotted, \
stop red, take-profit green; prices on the right axis, the live price in the grey box. Read it like a trader: trend \
direction and structure, where the price sits relative to the levels, consolidations, wicks, how volume behaves.
- A JSON brief with the precise numbers behind the picture: market phase, per timeframe trend/structure/EMAs/RSI/\
ADX/efficiency/ATR and the last candle patterns, support and resistance zones with their touches, previous day's \
high/low/close and VWAP, relative volume, Bollinger squeeze, order book depth and imbalance, BTC as the market \
leader (for other coins), the open position with its plan, why you were woken, your notes from the last check, \
the backtest evidence per setup (backtest) and your own live track record by setup. Trust the numbers over your \
reading of the image when they disagree.

## The rules the backtest supports
1. Regime first: new longs only when the 4 h trend is up and the 1 h chart is trending (ADX14 >= 25) – the brief \
says so in rules.backtested_regime_ok. Outside that regime wait, whatever the 5-minute chart looks like. For an \
altcoin, BTC falling hard is a reason to wait too.
2. Setups that paid: trend_pullback (pullback to the rising 15m EMA20 / VWAP in a 1 h uptrend, selling volume \
drying up, a 5-minute candle turning up), momentum (5m close above the 2 h high on at least 1.5x volume with 15m \
and 1h in an uptrend) and breakout of the 24 h high on volume (the strongest, rare). A 2 h breakout while the 15m \
chart is not yet in an uptrend was weak – prefer the retest or wait for the 15m trend. reversal (catching a flush) \
and range_support lost money in the backtest: take them only with an exceptional reason and at 25 % size.
3. Location still matters: good longs start near support, at the reclaimed level or right at the breakout – not \
right under a strong resistance that sits inside the first 1R.
4. Stop: below the last 1-hour swing low with a quarter 1 h ATR of air – the brief computes it as \
swing_plan.stop (about 2-4 % away). Put it at a nearby level if one is closer, but never inside the 5-minute noise \
(at least one 5-minute ATR) and never further than max_stop_distance_pct. A stop at the 5-minute structure is what \
lost money.
5. Target: 3R above the entry (swing_plan.target_3r); 2.5-4R worked, below 2R did not. A take-profit before a \
major resistance is fine if it still pays at least 2.5R – otherwise there is no trade.
6. Size: size_pct of the amount by quality – 100 for an A setup in the regime, 50 for a good one with a flaw, 25 \
for anything speculative. If you would only take it at 25, consider waiting.
7. Managing: let it run. The backtest says: no break-even stop (it halved the result), no trailing stop, no time \
exit after a few hours – a swing trade needs about a day, often several. Hold through 5-minute noise. Close early \
only when the reason is gone: the 1 h trend has turned down while the trade is below +1R, or a level that defined \
the trade is clearly lost. Don't widen stops, don't add hope.
8. Review: the backtest numbers per setup are your prior, your own live statistics are the update. Lean into \
what works for this pair, avoid what keeps failing, and after losses become pickier, not more active.

## How the bot executes
- Spot, long only, one position at a time, at most the amount from the brief (size_pct of it). No leverage, no \
shorting: in a downtrend the choices are waiting or an exceptional reversal.
- Every order is a post-only limit order a cent inside the spread – a buy at the best bid, a sale at the best ask. \
Maker fees are 0 %, but a fill is not guaranteed: the order follows the price for limit_wait_minutes and is cancelled \
if still unfilled. Buying the pullback or the first pause after the breakout fills; chasing a vertical move rarely does.
- Between checks the bot runs the plan every 30 seconds: sells at the take-profit and at the stop (in a fast drop the \
stop sale follows the price down and may get less). Break-even and trailing stops are off by default; if the owner \
turned them on or you set trail_pct, the bot runs them from +1R. A stop is never lowered and never further away \
than max_stop_distance_pct.
- You are woken early by the scanner (the backtested setups, only in the regime), by your price alerts (wake_above / \
wake_below), by large moves, by a breakdown below the 2 h low while a position is open, and when a position's time \
limit is up. Otherwise you are asked at the pace the API budget allows (usual_gap_minutes). Without a position and \
outside the regime, a long next_check_minutes saves budget.

## Answer fields
- action: without a position "buy" or "wait"; with a position "hold" or "sell" (close now).
- setup: the playbook setup of a buy (for "hold" the setup of the trade, otherwise "none"); a 24 h breakout is "breakout".
- take_profit, stop_loss: absolute prices – for "buy" the plan of the new position, for "hold" the plan from now on \
(repeat when unchanged); 0 for "wait" and "sell".
- size_pct: 25–100 for a buy, otherwise 0.
- trail_pct: optional trailing distance in % from the high once the trade is +1R, 0 = none (the backtest says none).
- max_hold_minutes: optional time limit after which you want to re-check a position, 0 = none (think in days, not hours).
- wake_above, wake_below: price alerts at levels that would change your view, 0 = none.
- next_check_minutes: when to look again if nothing happens (the bot stays within its budget).
- confidence: how sure you are that this action is right now, honestly calibrated – 50 is a coin toss, 80 or more \
only for an A setup in the regime.
- notes: your working notes for the next check (at most 300 characters) – the levels and scenario you are watching.
- reason_en, reason_de: at most two short sentences each for the bot owner (English, then the same in German) naming \
the concrete facts behind the decision."""


class AiUnavailable(ValueError):
    """Claude gave no usable decision (refusal or unparsable answer) – treated like a transient error."""


class AiDecision(BaseModel):
    action: Literal["buy", "wait", "hold", "sell"]
    confidence: int = Field(ge=0, le=100, description="0-100")
    reason_en: str = Field(description="reason in English, max two sentences")
    reason_de: str = Field(description="the same reason in German")
    setup: Literal["trend_pullback", "breakout", "breakout_retest", "range_support", "reversal", "momentum",
                   "none"] = "none"
    take_profit: float = Field(0.0, description="take-profit price, 0 = none")
    stop_loss: float = Field(0.0, description="stop price, 0 = none")
    size_pct: int = Field(0, description="share of the amount for a buy, 25-100")
    trail_pct: float = Field(0.0, description="trailing stop distance in % once +1R, 0 = none")
    max_hold_minutes: int = Field(0, description="re-check a position after this time, 0 = none")
    wake_above: float = Field(0.0, description="price alert above, 0 = none")
    wake_below: float = Field(0.0, description="price alert below, 0 = none")
    next_check_minutes: int = Field(0, description="when to look again, 0 = the usual gap")
    notes: str = Field("", description="working notes for the next check, max 300 characters")


@dataclass
class MarketBrief:
    """Everything Claude gets to see – the JSON brief and the chart."""

    symbol: str
    data: dict[str, Any]
    position: dict[str, Any] | None = None
    sentiment: dict[str, Any] | None = None  # Fear & Greed index, only when the bot asks for it
    owner_instructions: str = ""  # optional extra rules from the bot owner
    chart_png: bytes | None = field(default=None, repr=False)

    def to_text(self) -> str:
        data = {"symbol": self.symbol, **self.data, "position": self.position}
        if self.sentiment is not None:
            data["sentiment"] = self.sentiment
        text = json.dumps(data, ensure_ascii=False, default=float, separators=(",", ":"))
        if self.owner_instructions:
            text += "\n\nAdditional instructions from the bot owner (follow them within the rules above):\n" + self.owner_instructions
        return text


async def fetch_fear_greed() -> dict[str, Any] | None:
    """Current Crypto Fear & Greed index with the last days, or None when unavailable. Overridden in tests."""
    global _fear_greed_cache
    cached_at, cached = _fear_greed_cache
    if cached is not None and time.time() - cached_at < FEAR_GREED_CACHE_S:
        return cached
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(FEAR_GREED_URL)
            response.raise_for_status()
            rows = response.json().get("data") or []
        values = [int(r["value"]) for r in rows]
        if not values:
            return cached
        result = {
            "fear_greed_index": values[0],
            "classification": str(rows[0].get("value_classification", "")),
            "last_7_days": values,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("Fear & Greed index not available: %s", exc)
        return cached
    _fear_greed_cache = (time.time(), result)
    return result


def _round(value: float | None, price: float) -> float | None:
    """A price with sensible precision (about 6 significant digits)."""
    if value is None or price <= 0:
        return value
    digits = max(0, 6 - len(str(int(price))))
    return round(value, digits)


def _price_at(candles: list, interval: int, t0: int) -> Decimal | None:
    """Price at ``t0`` from a candle series (same rule as MarketView.price_at)."""
    if not candles:
        return None
    before = [c for c in candles if c.start <= t0]
    if not before:
        return candles[0].open
    c = before[-1]
    return c.close if (t0 - c.start) > interval * 30_000 else c.open


# --- budget -----------------------------------------------------------------------


def call_cost(usage: Any, model: str) -> float:
    """What one response cost in $ – from the usage the API reports."""
    price_in, price_out, price_read = PRICES.get(model, PRICES[DEFAULT_MODEL])
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    return (tokens_in * price_in + written * price_in * 1.25 + read * price_read + tokens_out * price_out) / 1e6 \
        + searches * WEB_SEARCH_USD


def month_bounds(now_ms: int) -> tuple[str, int]:
    """The current month (UTC) as "YYYY-MM" and its end in ms."""
    t = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    days = calendar.monthrange(t.year, t.month)[1]
    end = datetime(t.year, t.month, days, tzinfo=timezone.utc).timestamp() * 1000 + DAY_MS
    return f"{t.year:04d}-{t.month:02d}", int(end)


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Win rate and average R overall and per setup – the trader's own track record."""
    if not trades:
        return None

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rs = [t["result_r"] for t in rows if t.get("result_r") is not None]
        return {
            "trades": len(rows),
            "win_rate_pct": round(100 * sum(1 for t in rows if t["result_pct"] > 0) / len(rows)),
            "avg_result_pct": round(sum(t["result_pct"] for t in rows) / len(rows), 2),
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        }

    setups: dict[str, list] = {}
    for t in trades:
        setups.setdefault(t.get("setup") or "none", []).append(t)
    return {"all": summary(trades), "by_setup": {k: summary(v) for k, v in setups.items()}}


class AiStrategy(Strategy):
    key = "ai"
    name = L("AI swing trader", "KI-Swingtrader")
    description = L(
        "Claude (Fable 5.1) trades the pair like a swing trader with a day trader's entries – the way a backtest of the "
        "playbook on six years of ETH/BTC data paid off: only in a 4 h uptrend with a trending 1 h chart, entries on "
        "breakouts on volume or pullbacks in a 1 h uptrend, stop below the 1 h swing low, target 3R, held for hours "
        "to days. Claude reads the chart as an image and the numbers behind it, sets take-profit and stop for every "
        "trade, which the bot runs by itself. A scanner wakes Claude when a setup forms; daily loss limit and a pause "
        "after losing streaks. Only fee-free limit orders, never at market. Paced by a monthly API budget; needs an "
        "Anthropic API key on the agent.",
        "Claude (Fable 5.1) handelt das Paar wie ein Swingtrader mit den Einstiegen eines Daytraders – so, wie ein "
        "Backtest des Playbooks auf sechs Jahren ETH/BTC-Daten Gewinn brachte: nur im 4-h-Aufwärtstrend mit "
        "trendendem 1-h-Chart, Einstieg bei Ausbrüchen mit Volumen oder Rücksetzern im 1-h-Aufwärtstrend, Stop unter "
        "dem 1-h-Swing-Tief, Ziel 3R, gehalten über Stunden bis Tage. Claude liest den Chart als Bild und die Zahlen "
        "dahinter und setzt für jeden Trade Gewinnziel und Stop, die der Bot selbst ausführt. Ein Scanner weckt "
        "Claude, wenn sich ein Setup bildet; Tagesverlust-Limit und Pause nach Verlustserien. Nur gebührenfreie "
        "Limit-Orders, nie zum Marktpreis. Getaktet nach monatlichem API-Budget; braucht einen Anthropic-API-Key auf "
        "dem Agenten.",
    )
    icon = "sparkles"
    limit_only = True
    params = [
        Param("amount", L("Max. amount per trade", "Max. Betrag pro Trade"), "money", 50.0,
              L("Claude uses 25–100 % of it, depending on how good the setup is.",
                "Claude nutzt davon 25–100 %, je nachdem, wie gut das Setup ist."), min=1),
        Param("model", L("Model", "Modell"), "select", DEFAULT_MODEL, options=[
            Option("claude-fable-5-1", L("Claude Fable 5.1", "Claude Fable 5.1")),
            Option("claude-opus-5-5", L("Claude Opus 5.5", "Claude Opus 5.5")),
            Option("claude-sonnet-5-5", L("Claude Sonnet 5.5", "Claude Sonnet 5.5")),
            Option("claude-haiku-5-5", L("Claude Haiku 5.5", "Claude Haiku 5.5")),
        ]),
        Param("effort", L("Thinking depth", "Denktiefe"), "select", "auto", options=[
            Option("auto", L("Automatic – deep at setups and open trades", "Automatisch – gründlich bei Setups und offenen Trades")),
            Option("low", L("Low – more checks per budget", "Niedrig – mehr Prüfungen pro Budget")),
            Option("medium", L("Medium", "Mittel")),
            Option("high", L("High – fewer, deeper checks", "Hoch – weniger, gründlichere Prüfungen")),
        ], help=L(
            "How long Claude thinks per check. Automatic: medium when the scanner found a setup, an alert fired or a "
            "trade is open, low for routine looks. Deeper thinking costs more, so the budget allows fewer checks.",
            "Wie lange Claude pro Prüfung nachdenkt. Automatisch: mittel, wenn der Scanner ein Setup gefunden hat, ein "
            "Alarm ausgelöst hat oder ein Trade offen ist, niedrig bei Routineblicken. Mehr Denken kostet mehr, das "
            "Budget reicht also für weniger Prüfungen.",
        )),
        Param("budget", L("API budget per month", "API-Budget pro Monat"), "number", 50.0,
              L("US dollars this bot may spend on Claude per calendar month. The bot measures what each check costs "
                "and spreads the rest evenly over the rest of the month. Per bot – split it when you run several.",
                "US-Dollar, die dieser Bot pro Kalendermonat für Claude ausgeben darf. Der Bot misst, was jede Prüfung "
                "kostet, und verteilt den Rest gleichmäßig auf den Rest des Monats. Pro Bot – bei mehreren aufteilen."),
              min=1, max=10000, step=5, unit="$"),
        Param("ai_interval", L("Ask Claude at most every", "Claude höchstens alle"), "int", 15,
              L("Shortest gap between two checks, also when the scanner or an alert wakes Claude.",
                "Kürzester Abstand zwischen zwei Prüfungen, auch wenn Scanner oder Alarm Claude wecken."),
              min=1, max=1440, unit="min"),
        Param("chart", L("Show Claude the chart", "Claude den Chart zeigen"), "bool", True,
              L("Sends a candlestick chart (1 h, 15 min, 5 min) as an image with every check – about 1 ct extra.",
                "Schickt bei jeder Prüfung einen Kerzenchart (1 h, 15 min, 5 min) als Bild mit – etwa 1 ct extra.")),
        Param("maker_wait", L("Waiting time for limit orders", "Wartezeit für Limit-Orders"), "int", 10,
              L("A buy waits a cent below the best bid, a sale a cent above the best ask (no fee); if the price moves "
                "away the order follows it. What isn't filled after this time is cancelled – never at market.",
                "Ein Kauf wartet einen Cent unter dem besten Geldkurs, ein Verkauf einen Cent über dem besten Briefkurs "
                "(ohne Gebühr); läuft der Kurs weg, zieht die Order nach. Was danach nicht ausgeführt ist, wird "
                "storniert – nie zum Marktpreis."),
              min=1, max=120, unit="min"),
        Param("stop_loss", L("Max. stop-loss", "Max. Stop-Loss"), "percent", 5.0,
              L("Claude sets a stop for every position; it may never be further away than this. The backtested stop "
                "below the 1 h swing low is about 3 % away; 4–6 % worked, 3 % cost a third of the result. 0 = Claude alone decides.",
                "Claude setzt für jede Position einen Stop; er darf nie weiter weg liegen als hier. Der getestete Stop unter "
                "dem 1-h-Swing-Tief liegt etwa 3 % entfernt; 4–6 % funktionierten, 3 % kostete ein Drittel des Ergebnisses. "
                "0 = nur Claude entscheidet."),
              min=0, max=50, step=0.5),
        Param("breakeven", L("Stop to break-even at +1R", "Stop auf Einstand ab +1R"), "bool", False,
              L("Once a trade is up by as much as it risked, the stop moves to the entry price. Off by default: in the "
                "backtest it halved the result (more trades stopped at zero), but lowered the drawdown.",
                "Sobald ein Trade so viel im Plus ist, wie er riskiert hat, rückt der Stop auf den Einstiegskurs. "
                "Standard aus: im Backtest halbierte das das Ergebnis (mehr Trades enden bei null), senkte aber den Rückgang.")),
        Param("cut_losses", L("Claude may close at a loss", "Claude darf mit Verlust schließen"), "bool", True,
              L("Off: Claude's own sell signal waits for break-even; only the stop realizes a loss.",
                "Aus: Claudes eigenes Verkaufssignal wartet auf die Gewinnschwelle; nur der Stop realisiert einen Verlust.")),
        Param("daily_loss_limit", L("Daily loss limit", "Tagesverlust-Limit"), "percent", 6.0,
              L("No new trades for the rest of the day (UTC) once the day's closed trades lost this much of the max. "
                "amount. 0 = off.",
                "Keine neuen Trades mehr für den Rest des Tages (UTC), sobald die abgeschlossenen Trades des Tages so "
                "viel vom max. Betrag verloren haben. 0 = aus."),
              min=0, max=100, step=1),
        Param("loss_streak", L("Pause after losses in a row", "Pause nach Verlusten in Folge"), "int", 3,
              L("After this many losing trades in a row the bot takes no new trade for 2 hours. 0 = off.",
                "Nach so vielen Verlust-Trades in Folge eröffnet der Bot 2 Stunden lang keinen neuen Trade. 0 = aus."),
              min=0, max=20),
        Param("min_confidence", L("Minimum confidence", "Mindestsicherheit"), "percent", 0.0,
              L("Buy only when Claude is at least this sure. 0 = every buy decision is executed.",
                "Nur kaufen, wenn Claude mindestens so sicher ist. 0 = jede Kaufentscheidung wird ausgeführt."),
              min=0, max=100, step=5),
        Param("news", L("Consider news", "Nachrichten einbeziehen"), "bool", False,
              L("Claude may search the web for current news before deciding – makes every check several times as "
                "expensive, so the budget allows fewer.",
                "Claude darf vor der Entscheidung im Web nach aktuellen Nachrichten suchen – macht jede Prüfung "
                "mehrfach so teuer, das Budget reicht also für weniger.")),
        Param("sentiment", L("Fear & Greed index", "Fear-&-Greed-Index"), "select", "off", options=[
            Option("off", L("Off", "Aus")),
            Option("info", L("As background information", "Als Hintergrundinformation")),
            Option("contrarian", L("As a contrarian signal at extremes", "Als Kontrasignal an Extremen")),
        ], help=L(
            "The Crypto Fear & Greed index (0–100) of the market as a whole. Contrarian: below 25 Claude leans towards "
            "buying panic, above 75 towards taking profits sooner; in between the index is ignored.",
            "Der Crypto Fear & Greed Index (0–100) für den Gesamtmarkt. Kontrasignal: unter 25 neigt Claude dazu, "
            "Panik zu kaufen, über 75 dazu, Gewinne früher mitzunehmen; dazwischen wird der Index ignoriert.",
        )),
        Param("instructions", L("Additional instructions", "Zusätzliche Anweisungen"), "text", "",
              L("Optional. Your own rules or focus for Claude, e.g. “only trend pullbacks” – sent with every check.",
                "Optional. Eigene Regeln oder Schwerpunkte für Claude, z. B. „nur Pullbacks im Trend“ – wird bei jeder Prüfung mitgeschickt.")),
        Param("cooldown_minutes", COOLDOWN_LABEL, "int", 0, COOLDOWN_HELP, min=0, max=10080, unit="min"),
    ]

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    # --- Claude -----------------------------------------------------------------

    @staticmethod
    def configured() -> bool:
        return any(os.getenv(var, "").strip() for var in API_KEY_VARS)

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(timeout=300.0, max_retries=2)
        return self._client

    async def ask(self, brief: MarketBrief, news: bool, model: str = DEFAULT_MODEL,
                  effort: str = "low") -> tuple[AiDecision, float]:
        """One decision from Claude and what it cost in $. Overridden in tests."""
        mode = (brief.sentiment or {}).get("mode")
        sentiment_hint = SENTIMENT_CONTRARIAN if mode == "contrarian" else SENTIMENT_INFO if mode == "info" else ""
        content: list[dict[str, Any]] = []
        if brief.chart_png:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                         "data": base64.b64encode(brief.chart_png).decode()}})
        content.append({"type": "text", "text": (
            ("You may run up to 3 web searches for news about this asset first.\n\n" if news else "")
            + (sentiment_hint + "\n\n" if sentiment_hint else "")
            + "Market brief:\n" + brief.to_text()
        )})
        request: dict[str, Any] = dict(
            model=model,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=AiDecision,
            output_config={"effort": effort},
        )
        if news:
            request["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        if model != "claude-haiku-5-5":  # a declined request is retried on the model Anthropic recommends for it
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        async with self._get_client().beta.messages.stream(**request) as stream:
            response = await stream.get_final_message()
        cost = call_cost(response.usage, response.model or model)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise AiUnavailable(f"no decision (stop_reason={response.stop_reason})")
        return response.parsed_output, cost

    # --- market data ------------------------------------------------------------

    async def brief(self, ctx: Context, state: dict[str, Any], woken_by: list[str] | None = None) -> MarketBrief:
        """The market read: four timeframes, levels, session, volume, order book, BTC, the position and the track
        record – and the chart."""
        market, pos, p = ctx.market, ctx.position, ctx.params
        price = float(market.price)
        now = ctx.now
        raw5, i5 = await market.candles(8)
        raw15, i15 = await market.candles(24)
        raw60, i60 = await market.candles(72)
        raw240, i240 = await market.candles(240)
        c5, c15 = ta.closed(raw5, i5, now), ta.closed(raw15, i15, now)
        c60, c240 = ta.closed(raw60, i60, now), ta.closed(raw240, i240, now)

        tf = {
            "4h": ta.timeframe(c240, "4h", price),
            "1h": ta.timeframe(c60, "1h", price),
            "15m": ta.timeframe(c15, "15m", price),
            "5m": ta.timeframe(c5, "5m", price),
        }
        atr15 = ta.atr(c15)
        atr60 = ta.atr(c60)
        state["atr_5m"] = tf["5m"]["atr14_pct"]  # sizes the move that wakes Claude early
        changes: dict[str, float] = {}
        for label, hours, candles, interval in (("15m", 0.25, raw5, i5), ("1h", 1, raw5, i5), ("4h", 4, raw5, i5),
                                                ("24h", 24, raw15, i15), ("72h", 72, raw60, i60)):
            ref = _price_at(candles, interval, now - int(hours * 3_600_000))
            if ref:
                changes[label] = round((price / float(ref) - 1) * 100, 2)
        levels_15 = ta.levels(c15, price, atr15)
        levels_1h = ta.levels(c60, price, atr60)
        sess = ta.session(c15, now, price)

        book = None
        try:
            book = ta.order_book_summary(await market.exchange.order_book(market.symbol, 50), price)
        except Exception as exc:  # noqa: BLE001 – the order book is a bonus, never a reason to skip a check
            log.info("Order book %s not available: %s", market.symbol, exc)

        leader = None
        base, _, quote = market.symbol.partition("-")
        if base != "BTC":
            try:
                btc_raw, btc_i = await market.candles_of(f"BTC-{quote}", 24)
                btc = ta.closed(btc_raw, btc_i, now)
                if btc:
                    last = ta.f(btc[-1].close)
                    leader = {"symbol": f"BTC-{quote}", "15m": ta.timeframe(btc, "15m", last)["trend"]}
                    for label, hours in (("1h", 1), ("4h", 4), ("24h", 24)):
                        ref = _price_at(btc, btc_i, now - hours * 3_600_000)
                        if ref:
                            leader[f"change_{label}_pct"] = round((last / float(ref) - 1) * 100, 2)
            except Exception as exc:  # noqa: BLE001
                log.info("BTC-%s as market leader not available: %s", quote, exc)

        sentiment = None
        if p.get("sentiment") in ("info", "contrarian"):
            index = await fetch_fear_greed()
            if index:
                sentiment = {"mode": p["sentiment"], **index}

        plan = state.get("plan") or {}
        position = None
        if pos:
            entry = float(pos.entry_price)
            risk = entry - float(plan.get("initial_stop") or 0) if plan.get("initial_stop") else None
            position = {
                "entry_price": _round(entry, price),
                "invested": round(float(pos.cost), 2),
                "profit_pct": round(pos.pnl_pct(market.bid), 2),
                "profit_r": round((float(market.bid) - entry) / risk, 2) if risk and risk > 0 else None,
                "held_minutes": round((now - pos.opened_at) / 60_000),
                "highest_since_entry": _round(float(pos.peak), price),
                "setup": plan.get("setup"),
                "take_profit": plan.get("target"),
                "stop_loss": plan.get("stop"),
                "initial_stop": plan.get("initial_stop"),
                "trail_pct": plan.get("trail_pct"),
                "time_limit_reached": bool(plan.get("hold_until") and now >= plan["hold_until"]),
            }
        last = state.get("last")
        previous = None
        if last:
            previous = {k: last.get(k) for k in ("action", "setup", "confidence", "reason_en")}
            previous["minutes_ago"] = round((now - int(last.get("at") or now)) / 60_000)
            previous["price_then"] = last.get("price")
        trades = list(state.get("trades") or [])
        today = now - now % DAY_MS
        today_trades = [t for t in trades if int(t.get("closed_at") or 0) >= today]
        pace = self.pace_ms(ctx, state)
        rules = {
            "max_amount": float(p["amount"]),
            "limit_wait_minutes": int(p["maker_wait"]),
            "usual_gap_minutes": round(pace / 60_000) if pace else None,
            "max_stop_distance_pct": float(p["stop_loss"]) or None,
            "breakeven_at_1r": bool(p["breakeven"]),
            "your_sell_may_realize_a_loss": bool(p["cut_losses"]),
            "daily_loss_limit_pct_of_amount": float(p["daily_loss_limit"]) or None,
            "min_confidence_for_a_buy": float(p["min_confidence"]) or None,
            "maker_fee_pct": 0,
            "backtested_regime_ok": ta.regime_ok(tf),
        }
        swing = ta.swing_stop(c60, price, ta.atr(c5))
        if swing:
            swing = {k: (_round(v, price) if isinstance(v, float) and not k.endswith("_pct") else v) for k, v in swing.items()}
            if float(p["stop_loss"]) > 0 and swing["distance_pct"] > float(p["stop_loss"]):
                swing["note"] = f"further than the owner's max. stop of {float(p['stop_loss']):g} % – the bot would cap it"
        data = {
            "time": ta.utc(now),
            "woken_by": woken_by or ["scheduled check"],
            "price": price, "bid": float(market.bid), "ask": float(market.ask),
            "spread_pct": round(float((market.ask - market.bid) / market.price * 100), 4) if market.price else 0.0,
            "market_phase": ta.regime(tf),
            "changes_pct": changes,
            "timeframes": tf,
            "levels_15m_24h": levels_15,
            "levels_1h_3d": levels_1h,
            "session": {k: (_round(v, price) if isinstance(v, float) and not k.endswith("_pct") else v)
                        for k, v in sess.items()},
            "volume_5m": ta.volume_profile(c5),
            "bollinger_5m": ta.squeeze(c5),
            "order_book": book,
            "market_leader": leader,
            "last_12_candles_5m_ohlcv": [
                [_round(ta.f(v), price) for v in (c.open, c.high, c.low, c.close)] + [round(ta.f(c.volume), 4)]
                for c in c5[-12:]
            ],
            "swing_plan": swing,
            "backtest": {"summary": ta.EVIDENCE_SUMMARY, "by_setup": ta.PLAYBOOK_EVIDENCE},
            "your_notes": state.get("notes") or None,
            "previous_decision": previous,
            "performance": {
                "today": {"trades": len(today_trades),
                          "result_pct_of_amount": round(sum(t.get("result_of_amount_pct", 0) for t in today_trades), 2)},
                "stats_last_30": trade_stats(trades),
                "recent_trades": trades[-RECENT:],
            },
            "rules": rules,
        }
        chart = None
        if p.get("chart"):
            level_prices = [z["price"] for z in levels_15["support"][:2] + levels_15["resistance"][:2]]
            chart = ai_chart.render(
                [("1H 3D", c60, False), ("15M 24H", c15, True), ("5M 3H", c5, True, 36)], price, level_prices,
                float(pos.entry_price) if pos else None, plan.get("stop") if pos else None,
                plan.get("target") if pos else None,
            )
        return MarketBrief(symbol=market.symbol, data=data, position=position, sentiment=sentiment,
                           owner_instructions=str(p.get("instructions") or ""), chart_png=chart)

    # --- budget -----------------------------------------------------------------

    @staticmethod
    def _spend(ctx: Context, state: dict[str, Any]) -> dict[str, Any]:
        month, _ = month_bounds(ctx.now)
        spend = state.get("spend") or {}
        if spend.get("month") != month:
            spend = {"month": month, "usd": 0.0, "calls": 0}
            state["spend"] = spend
        return spend

    def avg_cost(self, ctx: Context, state: dict[str, Any]) -> float:
        model = str(ctx.params["model"])
        guess = COST_GUESS.get(model, COST_GUESS[DEFAULT_MODEL])
        if ctx.params["news"]:
            guess *= 3
        avg = state.get("avg_cost")
        return float(avg) if avg and state.get("avg_model") == model else guess

    def pace_ms(self, ctx: Context, state: dict[str, Any]) -> int | None:
        """The gap between two checks that spends the rest of this month's budget evenly – None: used up."""
        spend = self._spend(ctx, state)
        _, end = month_bounds(ctx.now)
        left = float(ctx.params["budget"]) - float(spend["usd"])
        avg = self.avg_cost(ctx, state)
        if left < avg:
            return None
        return int((end - ctx.now) * avg / left)

    def _book_cost(self, ctx: Context, state: dict[str, Any], cost: float) -> None:
        spend = self._spend(ctx, state)
        spend["usd"] = round(float(spend["usd"]) + cost, 4)
        spend["calls"] = int(spend["calls"]) + 1
        model = str(ctx.params["model"])
        if state.get("avg_model") != model or not state.get("avg_cost"):
            state["avg_cost"], state["avg_model"] = cost, model
        else:  # moving average over roughly the last 10 checks
            state["avg_cost"] = round(float(state["avg_cost"]) * 0.9 + cost * 0.1, 5)

    def _budget_note(self, ctx: Context, state: dict[str, Any], status: dict) -> dict:
        spend = self._spend(ctx, state)
        return m("ai.with_budget", status=status, spent=money(float(spend["usd"]), "USD"),
                 budget=money(float(ctx.params["budget"]), "USD"))

    # --- trade bookkeeping ------------------------------------------------------

    def _track_trades(self, ctx: Context, state: dict[str, Any]) -> None:
        """Turn the entry plan into the position's plan once it is filled, follow its high, and record it with its
        result once it is closed – Claude sees its own track record in every brief."""
        pos, opened = ctx.position, state.get("open")
        realized = Decimal(str(ctx.state.get("realized") or 0))
        if pos is not None and (opened is None or opened.get("id") != pos.id):
            entry_plan = state.pop("entry_plan", None) or {}
            entry = float(pos.entry_price)
            target = entry * (1 + entry_plan["target_pct"] / 100) if entry_plan.get("target_pct") else None
            stop = entry * (1 - entry_plan["stop_pct"] / 100) if entry_plan.get("stop_pct") else None
            plan = self._bounded_plan(ctx, entry, target, stop, None, update=not entry_plan)
            if not entry_plan and (plan.get("stop") or 0) >= float(ctx.market.bid):
                # a position from before this strategy (or an update) already beyond the max. stop: not sold
                # blindly – Claude is asked right away and sets the plan
                plan["stop"] = None
                state["next_at"] = 0
            plan.update(initial_stop=plan.get("stop"), setup=entry_plan.get("setup"),
                        trail_pct=entry_plan.get("trail_pct"))
            if entry_plan.get("hold_minutes"):
                plan["hold_until"] = pos.opened_at + int(entry_plan["hold_minutes"]) * 60_000
            state["plan"] = plan
            state["open"] = {"id": pos.id, "at": pos.opened_at, "realized": str(realized), "cost": str(pos.cost),
                             "entry": entry, "peak": entry, "setup": entry_plan.get("setup"),
                             "size_pct": entry_plan.get("size_pct"),
                             "risk_pct": round((1 - plan["stop"] / entry) * 100, 3) if plan.get("stop") else None}
            state.pop("exit", None)
        elif pos is not None:
            opened["peak"] = max(float(opened.get("peak") or 0), float(ctx.market.bid))
        elif opened is not None:
            pnl = realized - Decimal(opened["realized"])
            cost = Decimal(opened["cost"])
            result = round(float(pnl / cost * 100), 2) if cost else 0.0
            risk = opened.get("risk_pct")
            entry = float(opened["entry"])
            trades = list(state.get("trades") or [])
            trades.append({
                "closed_at": ctx.now,
                "setup": opened.get("setup") or "none",
                "size_pct": opened.get("size_pct"),
                "held_minutes": round((ctx.now - int(opened["at"])) / 60_000),
                "result_pct": result,
                "result_r": round(result / risk, 2) if risk else None,
                "best_pct_during_trade": round((float(opened.get("peak") or entry) / entry - 1) * 100, 2) if entry else None,
                "result_of_amount_pct": round(float(pnl) / float(ctx.params["amount"]) * 100, 2),
                "exit": state.pop("exit_cause", "unknown"),
            })
            state["trades"] = trades[-HISTORY:]
            for key in ("open", "plan", "exit"):
                state.pop(key, None)
        for t in state.get("trades") or []:
            t["closed_minutes_ago"] = round((ctx.now - int(t.get("closed_at") or ctx.now)) / 60_000)

    def _bounded_plan(self, ctx: Context, entry: float, target: float | None, stop: float | None,
                      current: dict[str, Any] | None, update: bool = True) -> dict[str, Any]:
        """Take-profit and stop within the owner's limits: the stop never further than the max. stop-loss from the
        entry and never lowered once set. ``update``: Claude revises the plan of an open position – levels the price
        has already passed are ignored then (a new position's plan stands, even if the price ran through it)."""
        price = float(ctx.market.price)
        max_stop = float(ctx.params["stop_loss"])
        # measured from the entry – or, when Claude revises a position that is already further down, from the price
        base = min(entry, price) if update else entry
        floor = base * (1 - max_stop / 100) if max_stop > 0 else None
        if stop is not None and (stop <= 0 or (update and stop >= price)):  # would sell right away
            stop = None
        if floor is not None:
            stop = max(stop or floor, floor)
        if current and current.get("stop") is not None:
            stop = max(stop or 0, float(current["stop"])) or None
        if target is not None and (target <= 0 or (update and target <= price)):
            target = (current or {}).get("target")
        plan = dict(current or {})
        plan.update(target=_round(target, price) if target else None, stop=_round(stop, price) if stop else None)
        return plan

    def _manage(self, ctx: Context, state: dict[str, Any]) -> None:
        """Between checks, like a trader with a plan: stop to break-even at +1R, trailing stop from +1R."""
        pos, plan = ctx.position, state.get("plan") or {}
        if pos is None or not plan.get("initial_stop"):
            return
        entry, bid = float(pos.entry_price), float(ctx.market.bid)
        risk = entry - float(plan["initial_stop"])
        if risk <= 0 or bid < entry + risk:
            return
        stop = float(plan.get("stop") or 0)
        if ctx.params["breakeven"]:
            stop = max(stop, entry)
        if plan.get("trail_pct"):
            stop = max(stop, float(pos.peak) * (1 - float(plan["trail_pct"]) / 100))
        if stop > float(plan.get("stop") or 0) and stop < bid:
            plan["stop"] = _round(stop, float(ctx.market.price))
            state["plan"] = plan

    def _discipline(self, ctx: Context, state: dict[str, Any]) -> dict | None:
        """Why no new trade may be opened now (daily loss limit, losing streak) – None if trading is allowed."""
        p, trades = ctx.params, list(state.get("trades") or [])
        now = ctx.now
        today = now - now % DAY_MS
        limit = float(p["daily_loss_limit"])
        lost = sum(t.get("result_of_amount_pct", 0) for t in trades if int(t.get("closed_at") or 0) >= today)
        if limit > 0 and lost <= -limit:
            return m("ai.daily_limit", lost=pct(lost), limit=pct(-limit), left=dur(today + DAY_MS - now))
        streak = int(p["loss_streak"])
        if streak > 0 and len(trades) >= streak and all(t["result_pct"] < 0 for t in trades[-streak:]):
            until = int(trades[-1]["closed_at"]) + LOSS_STREAK_PAUSE_MS
            if now < until:
                return m("ai.loss_streak", count=streak, left=dur(until - now))
        return None

    # --- waking up ----------------------------------------------------------------

    async def _scan(self, ctx: Context, state: dict[str, Any]) -> None:
        """Look for setups once per new 5-minute candle – cheap rules that only decide whether Claude looks early."""
        raw5, i5 = await ctx.market.candles(8)
        c5 = ta.closed(raw5, i5, ctx.now)
        if not c5 or state.get("scanned") == c5[-1].start:
            return
        state["scanned"] = c5[-1].start
        price = float(ctx.market.price)
        raw15, i15 = await ctx.market.candles(24)
        raw60, i60 = await ctx.market.candles(72)
        c15, c60 = ta.closed(raw15, i15, ctx.now), ta.closed(raw60, i60, ctx.now)
        tf = {"5m": ta.timeframe(c5, "5m", price), "15m": ta.timeframe(c15, "15m", price),
              "1h": ta.timeframe(c60, "1h", price)}
        tf["4h"] = ta.timeframe(ta.closed(*(await ctx.market.candles(240)), ctx.now), "4h", price)
        signals = ta.scan(c5, tf, ta.session(c15, ctx.now, price), price, position=ctx.position is not None)
        if signals:
            state["trigger"] = {"at": ctx.now, "signals": [s.text for s in signals]}

    def _wake_reasons(self, ctx: Context, state: dict[str, Any]) -> list[str]:
        """Why Claude should look before its time: a scanner signal, a crossed price alert, a large move or a
        position's time limit – not sooner than the minimum gap after the last check."""
        last = state.get("last")
        if not last or ctx.now < int(state.get("wake_after") or 0):
            return []
        reasons = []
        price = float(ctx.market.price)
        trigger = state.get("trigger")
        if trigger and ctx.now - int(trigger["at"]) <= TRIGGER_TTL_MS and int(trigger["at"]) > int(last.get("at") or 0):
            reasons += [f"scanner: {s}" for s in trigger["signals"]]
        if last.get("wake_above") and price >= last["wake_above"]:
            reasons.append(f"price alert: above {last['wake_above']}")
        if last.get("wake_below") and price <= last["wake_below"]:
            reasons.append(f"price alert: below {last['wake_below']}")
        then = float(last.get("price") or 0)
        move = float(state.get("wake_move") or MIN_WAKE_MOVE * 2)
        if then and abs(price / then - 1) * 100 >= move:
            reasons.append(f"large move: {(price / then - 1) * 100:+.2f} % since the last check")
        plan = state.get("plan") or {}
        if ctx.position and plan.get("hold_until") and ctx.now >= plan["hold_until"] and not plan.get("hold_noted"):
            reasons.append("the position's time limit is up")
            plan["hold_noted"] = True
        return reasons

    def _effort(self, ctx: Context, woken_by: list[str]) -> str:
        effort = str(ctx.params["effort"])
        if effort != "auto":
            return effort
        return "medium" if woken_by or ctx.position is not None else "low"

    # --- strategy ---------------------------------------------------------------

    async def evaluate(self, ctx: Context) -> Decision:
        p, market, pos = ctx.params, ctx.market, ctx.position
        state = ctx.state.setdefault("ai", {})
        self._track_trades(ctx, state)
        self._manage(ctx, state)
        plan = state.get("plan") or {}
        ctx.targets(sell=plan.get("target") if pos else None, stop=plan.get("stop") if pos else None,
                    note=m("targets.ai"))

        # the plan runs every tick, whether Claude is asked or not
        if pos is not None:
            bid = float(market.bid)
            if plan.get("stop") and bid <= plan["stop"]:
                state["exit_cause"] = "stop" if plan["stop"] < float(pos.entry_price) else "trailing/break-even stop"
                return Decision(m("ai.stop_hit"), Sell(m("ai.stop_reason", price=money(plan["stop"], ctx.quote),
                                                         profit=pct(pos.pnl_pct(market.bid))), stop=True))
            if plan.get("target") and bid >= plan["target"]:
                state["exit_cause"] = "take_profit"
                return Decision(m("ai.target_hit"), Sell(m("ai.target_reason", price=money(plan["target"], ctx.quote),
                                                           profit=pct(pos.pnl_pct(market.bid)))))
            exit_reason = state.get("exit")
            if exit_reason and ctx.now < int(state.get("next_at") or 0):
                # Claude said sell: repeated until the limit order is filled – or until Claude is asked again
                state["exit_cause"] = "claude"
                return Decision(m("ai.sell", confidence=m("ai.confidence", value=int(exit_reason["confidence"]))),
                                Sell(exit_reason["reason"], stop=bool(p["cut_losses"])))
            state.pop("exit", None)
        else:
            wait = cooldown_left(ctx, p["cooldown_minutes"])
            if wait:
                return Decision(m("cooldown", left=dur(wait)))
            if blocked := self._discipline(ctx, state):
                return Decision(blocked)

        if not self.configured():
            return Decision(m("ai.no_key"))

        pace = self.pace_ms(ctx, state)
        if pace is None:
            _, end = month_bounds(ctx.now)
            spend = self._spend(ctx, state)
            return Decision(m("ai.budget_used_up", spent=money(float(spend["usd"]), "USD"),
                              budget=money(float(p["budget"]), "USD"), left=dur(end - ctx.now)))

        try:
            await self._scan(ctx, state)
        except Exception as exc:  # noqa: BLE001 – a scanner hiccup must not stop the plan or the checks
            log.warning("AI bot %s: scanner failed: %s", market.symbol, exc)
        next_at = int(state.get("next_at") or 0)
        last = state.get("last")
        woken_by = self._wake_reasons(ctx, state)
        if ctx.now < next_at and not woken_by:
            if not last:  # backing off after an error
                return Decision(m("ai.retry", left=dur(next_at - ctx.now)))
            return Decision(self._budget_note(ctx, state, self._last_status(ctx, state, next_at)))
        if next_at == 0 and last:
            woken_by = woken_by or ["asked by the owner or the position needs a plan"]

        try:
            brief = await self.brief(ctx, state, woken_by)
            decision, cost = await self.ask(brief, bool(p["news"]), str(p["model"]), self._effort(ctx, woken_by))
        except anthropic.AuthenticationError:
            state["next_at"] = ctx.now + RETRY_AUTH_MS
            log.error("AI bot %s: Anthropic API key rejected", market.symbol)
            return Decision(m("ai.auth_error"))
        except anthropic.RateLimitError:
            state["next_at"] = ctx.now + RETRY_RATE_LIMIT_MS
            return Decision(m("ai.rate_limited", left=dur(RETRY_RATE_LIMIT_MS)))
        except (anthropic.APIError, ValueError) as exc:
            retry = max(int(p["ai_interval"]) * 60_000, 5 * 60_000)
            state["next_at"] = ctx.now + retry
            state.pop("last", None)
            log.warning("AI bot %s: %s", market.symbol, exc)
            return Decision(m("ai.error", error=str(exc)[:120], left=dur(retry)))
        self._book_cost(ctx, state, cost)
        state.pop("trigger", None)
        return self._apply(ctx, state, decision)

    def _last_status(self, ctx: Context, state: dict[str, Any], next_at: int) -> dict:
        last, pos = state["last"], ctx.position
        confidence = m("ai.confidence", value=int(last.get("confidence") or 0))
        left = dur(next_at - ctx.now)
        if last.get("skipped"):
            return m("ai.too_unsure", verdict=m("ai.buy", confidence=confidence),
                     min=int(float(ctx.params["min_confidence"])), left=left)
        if pos:
            return m("ai.holding", profit=pct(pos.pnl_pct(ctx.market.bid)), confidence=confidence, left=left)
        return m("ai.waiting", confidence=confidence, left=left)

    def _apply(self, ctx: Context, state: dict[str, Any], decision: AiDecision) -> Decision:
        p, market, pos = ctx.params, ctx.market, ctx.position
        price = float(market.price)
        state["last"] = {
            "action": decision.action, "setup": decision.setup, "confidence": decision.confidence,
            "reason_en": decision.reason_en, "reason_de": decision.reason_de, "at": ctx.now, "price": price,
            "wake_above": decision.wake_above if decision.wake_above > price else None,
            "wake_below": decision.wake_below if 0 < decision.wake_below < price else None,
        }
        state["notes"] = decision.notes.strip()[:300] or None
        # when to look again: Claude's wish within the budget; alerts and the scanner may wake it after the minimum gap
        pace = self.pace_ms(ctx, state) or MAX_GAP_MS
        min_gap = int(p["ai_interval"]) * 60_000
        floor = max(min_gap, pace // 2)
        wanted = decision.next_check_minutes * 60_000 if decision.next_check_minutes > 0 else pace
        gap = min(max(floor, wanted), max(pace, MAX_GAP_MS))
        state["next_at"] = ctx.now + gap
        state["wake_after"] = ctx.now + min_gap
        state["wake_move"] = max(MIN_WAKE_MOVE, 3 * float(state["atr_5m"])) if state.get("atr_5m") else None
        if ctx.journal:
            ctx.journal({
                "action": decision.action, "confidence": decision.confidence,
                "reason_en": decision.reason_en, "reason_de": decision.reason_de,
                "price": str(market.price), "profit_pct": pos.pnl_pct(market.bid) if pos else None,
            })
        reason = m("ai.reason", en=decision.reason_en, de=decision.reason_de)
        trade_reason = m("ai.trade_reason", reason=reason, confidence=decision.confidence)
        confidence = m("ai.confidence", value=decision.confidence)
        left = dur(gap)

        if pos is None:
            if decision.action != "buy":
                return Decision(self._budget_note(ctx, state, m("ai.waiting", confidence=confidence, left=left)))
            if decision.confidence < float(p["min_confidence"]):
                # Claude's opinion is journaled as given – only the trade is held back
                state["last"]["skipped"] = True
                verdict = m("ai.buy", confidence=confidence)
                return Decision(m("ai.too_unsure", verdict=verdict, min=int(float(p["min_confidence"])), left=left))
            if not (0 < decision.stop_loss < price) and float(p["stop_loss"]) <= 0:
                return Decision(m("ai.no_stop", left=left))  # never a position without protection
            size = min(100, max(25, decision.size_pct or 100))
            state["entry_plan"] = {
                "target_pct": (decision.take_profit / price - 1) * 100 if decision.take_profit > price else None,
                "stop_pct": (1 - decision.stop_loss / price) * 100 if 0 < decision.stop_loss < price else None,
                "setup": decision.setup, "size_pct": size,
                "trail_pct": decision.trail_pct if decision.trail_pct > 0 else None,
                "hold_minutes": decision.max_hold_minutes if decision.max_hold_minutes > 0 else None,
            }
            amount = Decimal(str(p["amount"])) * size / 100
            return Decision(m("ai.buy", confidence=confidence), Buy(amount, trade_reason))

        if decision.action == "sell":
            state["exit"] = {"reason": trade_reason, "confidence": decision.confidence}
            state["exit_cause"] = "claude"
            return Decision(m("ai.sell", confidence=confidence), Sell(trade_reason, stop=bool(p["cut_losses"])))
        current = state.get("plan") or {}
        plan = self._bounded_plan(
            ctx, float(pos.entry_price),
            decision.take_profit if decision.take_profit > 0 else current.get("target"),
            decision.stop_loss if decision.stop_loss > 0 else None,
            current,
        )
        if decision.trail_pct > 0:
            plan["trail_pct"] = decision.trail_pct
        if decision.max_hold_minutes > 0:
            plan["hold_until"] = ctx.now + decision.max_hold_minutes * 60_000
            plan.pop("hold_noted", None)
        if not plan.get("initial_stop"):
            plan["initial_stop"] = plan.get("stop")
        state["plan"] = plan
        ctx.targets(sell=plan.get("target"), stop=plan.get("stop"), note=m("targets.ai"))
        return Decision(self._budget_note(ctx, state, m("ai.holding", profit=pct(pos.pnl_pct(market.bid)),
                                                         confidence=confidence, left=left)))
