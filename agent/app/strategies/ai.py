"""AI day trader: Claude (Fable 5.1 by default) trades one pair intraday – it decides when to buy, sets a take-profit
and a stop for every position, and the bot executes that plan between two checks by itself.

Orders go out only as fee-free limit orders (post-only, a cent inside the spread, following the price like the
momentum bot) – an order that isn't filled within the waiting time is cancelled, never sent to the market. How often
Claude is asked follows a monthly API budget: the bot measures what every check costs and spreads the rest of the
budget over the rest of the month.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import anthropic
import httpx
from pydantic import BaseModel, Field

from ..i18n import L, dur, m, money, pct
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
# first guess of what one check costs (effort "low", no news) – replaced by the measured average after the first call
COST_GUESS = {"claude-fable-5-1": 0.07, "claude-opus-5-5": 0.03, "claude-sonnet-5-5": 0.015, "claude-haiku-5-5": 0.001}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# the anthropic SDK also accepts an OAuth token; both end up here as environment variables
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
RETRY_AUTH_MS = 60 * 60_000
RETRY_RATE_LIMIT_MS = 5 * 60_000
MIN_WAKE_MOVE = 0.4  # % – the bot wakes Claude early on a move at least this large (or 3 × the 5-minute ATR)
MAX_GAP_MS = 4 * 3_600_000  # Claude looks at least every 4 h, unless the budget only allows less
HISTORY = 8  # closed trades shown to Claude

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

SYSTEM_PROMPT = """You are the intraday trader of one crypto spot pair on Revolut X, running inside an automated bot. \
The goal is to grow the capital with short-term trades – minutes to a few hours – that have a positive expectancy. \
Being flat is a position too: the goal is profit, not activity.

How the bot works – the facts you decide within:
- Spot, long only, one position at a time with the fixed amount from the brief. No leverage, no shorting: in a \
downtrend the choices are waiting or a quick bounce trade.
- Every order is a post-only limit order a cent inside the spread – a buy at the best bid, a sale at the best ask. \
Maker fees are 0 %, so trading costs nothing, but a fill is not guaranteed: the order follows the price for \
limit_wait_minutes and is cancelled if it is still unfilled. Chasing a fast move rarely fills; buying a pullback does.
- You are asked only every so often (usual_gap_minutes in the brief – it depends on the API budget). Between checks \
the bot runs your plan every 30 seconds: it sells when the bid reaches your take_profit and when it falls to your \
stop_loss. These levels are the only protection while you are not looking, so set both for every buy and revise them \
on every check while holding. A stop can be raised but never lowered. In a fast drop the stop sale follows the price \
down – it is not guaranteed to get the stop price.
- You can be woken earlier: wake_above / wake_below are price alerts at levels that would change your view (a \
breakout, a lost support). The bot also wakes you on an unusually large move.

The brief has the price and spread, changes over several windows, the 5-minute candles of the last 3 hours, \
indicators on 5- and 15-minute candles, the 24 h and 72 h range, the open position with its plan, your previous \
decision and your recent trades with their results. Your own track record is the most honest feedback you get – if \
recent trades lost, find out why before repeating the pattern.

Take a trade when the reward clearly outweighs the risk: the distance to the take-profit should usually be at least \
1.5 times the distance to the stop, and the stop belongs where the trade idea is proven wrong, not at an arbitrary \
percentage. A directionless chop, a spread that eats the move, or a target inside normal noise are reasons to wait.

Fields of the answer:
- action: without a position "buy" or "wait"; with a position "hold" or "sell" (close now).
- take_profit, stop_loss: absolute prices. For "buy" the plan of the new position, for "hold" the plan from now on \
(repeat it when unchanged). 0 for "wait" and "sell".
- wake_above, wake_below: optional price alerts, 0 = none.
- next_check_minutes: when you want to look again if nothing happens before (the bot stays within its budget and may \
stretch it).
- confidence: how sure you are that the action is right now, honestly calibrated – 50 is a coin toss, 80 or more \
only for a clear setup.
- reason_en, reason_de: at most two short sentences each, for the bot owner (English, then the same in German), \
naming the concrete facts behind the decision."""


class AiUnavailable(ValueError):
    """Claude gave no usable decision (refusal or unparsable answer) – treated like a transient error."""


class AiDecision(BaseModel):
    action: Literal["buy", "wait", "hold", "sell"]
    confidence: int = Field(ge=0, le=100, description="0-100")
    reason_en: str = Field(description="reason in English, max two sentences")
    reason_de: str = Field(description="the same reason in German")
    take_profit: float = Field(0.0, description="take-profit price, 0 = none")
    stop_loss: float = Field(0.0, description="stop price, 0 = none")
    wake_above: float = Field(0.0, description="price alert above, 0 = none")
    wake_below: float = Field(0.0, description="price alert below, 0 = none")
    next_check_minutes: int = Field(0, description="when to look again, 0 = the usual gap")


@dataclass
class MarketBrief:
    """Everything Claude gets to see – built from the exchange data the other strategies use as well."""

    symbol: str
    quote: str
    time_utc: str
    price: float
    bid: float
    ask: float
    spread_pct: float
    changes_pct: dict[str, float]  # e.g. {"15m": -0.2, "1h": -0.4, "4h": 1.2, "24h": -3.1, "72h": 2.0}
    indicators: dict[str, Any]
    candles_5m: list[list[float]]  # last 3 h, [open, high, low, close]
    hourly_closes_24h: list[float]
    range: dict[str, float]
    position: dict[str, Any] | None
    amount: float
    rules: dict[str, Any]
    previous_decision: dict[str, Any] | None = None
    recent_trades: list[dict[str, Any]] = field(default_factory=list)
    owner_instructions: str = ""  # optional extra rules from the bot owner
    sentiment: dict[str, Any] | None = None  # Fear & Greed index, only when the bot asks for it

    def to_text(self) -> str:
        data = {k: v for k, v in self.__dict__.items()
                if k != "owner_instructions" and not (k == "sentiment" and v is None)}
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


# --- indicators -------------------------------------------------------------------


def _price_at(candles: list, interval: int, t0: int) -> Decimal | None:
    """Price at ``t0`` from a candle series (same rule as MarketView.price_at)."""
    if not candles:
        return None
    before = [c for c in candles if c.start <= t0]
    if not before:
        return candles[0].open
    c = before[-1]
    return c.close if (t0 - c.start) > interval * 30_000 else c.open


def _ema(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes: list[float], n: int = 14) -> float | None:
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
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def _atr_pct(candles: list, n: int = 14) -> float | None:
    """Average true range of the last ``n`` candles in % of the last close."""
    if len(candles) <= n:
        return None
    ranges = []
    for prev, c in zip(candles[-n - 1:], candles[-n:]):
        pc = float(prev.close)
        ranges.append(max(float(c.high) - float(c.low), abs(float(c.high) - pc), abs(float(c.low) - pc)))
    last = float(candles[-1].close)
    return sum(ranges) / n / last * 100 if last else None


def _returns_stdev(values: list[Decimal]) -> float:
    closes = [float(v) for v in values if v]
    if len(closes) < 3:
        return 0.0
    returns = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:]) if a]
    return statistics.pstdev(returns) if len(returns) > 1 else 0.0


def _rel(value: float | None, price: float) -> float | None:
    """``value`` as % distance from ``price`` (an EMA above the price is positive)."""
    return round((value / price - 1) * 100, 3) if value and price else None


def _round(value: float, price: float) -> float:
    """A price with sensible precision (5 significant digits relative to the price)."""
    if price <= 0:
        return value
    digits = max(0, 5 - len(str(int(price))))
    return round(value, digits + 1)


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
    end = datetime(t.year, t.month, days, tzinfo=timezone.utc).timestamp() * 1000 + 86_400_000
    return f"{t.year:04d}-{t.month:02d}", int(end)


class AiStrategy(Strategy):
    key = "ai"
    name = L("AI day trader", "KI-Daytrader")
    description = L(
        "Claude (Fable 5.1) trades the pair intraday: it decides when to buy, sets a take-profit and a stop for every "
        "position, and the bot runs that plan between two checks by itself. Only fee-free limit orders, like the "
        "momentum bot – what isn't filled is cancelled, never sent to the market. How often Claude is asked follows "
        "your monthly API budget. Needs an Anthropic API key on the agent.",
        "Claude (Fable 5.1) handelt das Paar intraday: Es entscheidet, wann gekauft wird, setzt für jede Position "
        "Gewinnziel und Stop, und der Bot führt diesen Plan zwischen zwei Prüfungen selbst aus. Nur gebührenfreie "
        "Limit-Orders wie beim Momentum-Bot – was nicht ausgeführt wird, wird storniert, nie zum Marktpreis gehandelt. "
        "Wie oft Claude gefragt wird, richtet sich nach deinem monatlichen API-Budget. Braucht einen "
        "Anthropic-API-Key auf dem Agenten.",
    )
    icon = "sparkles"
    limit_only = True
    params = [
        Param("amount", L("Amount per trade", "Betrag pro Trade"), "money", 50.0, min=1),
        Param("model", L("Model", "Modell"), "select", DEFAULT_MODEL, options=[
            Option("claude-fable-5-1", L("Claude Fable 5.1", "Claude Fable 5.1")),
            Option("claude-opus-5-5", L("Claude Opus 5.5", "Claude Opus 5.5")),
            Option("claude-sonnet-5-5", L("Claude Sonnet 5.5", "Claude Sonnet 5.5")),
            Option("claude-haiku-5-5", L("Claude Haiku 5.5", "Claude Haiku 5.5")),
        ]),
        Param("effort", L("Thinking depth", "Denktiefe"), "select", "low", options=[
            Option("low", L("Low – more checks per budget", "Niedrig – mehr Prüfungen pro Budget")),
            Option("medium", L("Medium", "Mittel")),
            Option("high", L("High – fewer, deeper checks", "Hoch – weniger, gründlichere Prüfungen")),
        ], help=L(
            "How long Claude thinks per check. Deeper thinking costs more per check, so the budget allows fewer.",
            "Wie lange Claude pro Prüfung nachdenkt. Mehr Denken kostet mehr pro Prüfung, das Budget reicht also für weniger.",
        )),
        Param("budget", L("API budget per month", "API-Budget pro Monat"), "number", 100.0,
              L("US dollars this bot may spend on Claude per calendar month. The bot measures what each check costs "
                "and spreads the rest evenly over the rest of the month. Per bot – split it when you run several.",
                "US-Dollar, die dieser Bot pro Kalendermonat für Claude ausgeben darf. Der Bot misst, was jede Prüfung "
                "kostet, und verteilt den Rest gleichmäßig auf den Rest des Monats. Pro Bot – bei mehreren aufteilen."),
              min=1, max=10000, step=5, unit="$"),
        Param("ai_interval", L("Ask Claude at most every", "Claude höchstens alle"), "int", 5,
              L("Shortest gap between two checks, also for price alerts and big moves.",
                "Kürzester Abstand zwischen zwei Prüfungen, auch bei Preisalarmen und großen Bewegungen."),
              min=1, max=1440, unit="min"),
        Param("maker_wait", L("Waiting time for limit orders", "Wartezeit für Limit-Orders"), "int", 10,
              L("A buy waits a cent below the best bid, a sale a cent above the best ask (no fee); if the price moves "
                "away the order follows it. What isn't filled after this time is cancelled – never at market.",
                "Ein Kauf wartet einen Cent unter dem besten Geldkurs, ein Verkauf einen Cent über dem besten Briefkurs "
                "(ohne Gebühr); läuft der Kurs weg, zieht die Order nach. Was danach nicht ausgeführt ist, wird "
                "storniert – nie zum Marktpreis."),
              min=1, max=120, unit="min"),
        Param("stop_loss", L("Max. stop-loss", "Max. Stop-Loss"), "percent", 3.0,
              L("Claude sets a stop for every position; it may never be further away than this. 0 = Claude alone decides.",
                "Claude setzt für jede Position einen Stop; er darf nie weiter weg liegen als hier. 0 = nur Claude entscheidet."),
              min=0, max=50, step=0.5),
        Param("cut_losses", L("Claude may close at a loss", "Claude darf mit Verlust schließen"), "bool", True,
              L("Off: Claude's own sell signal waits for break-even; only the stop realizes a loss.",
                "Aus: Claudes eigenes Verkaufssignal wartet auf die Gewinnschwelle; nur der Stop realisiert einen Verlust.")),
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
              L("Optional. Your own rules or focus for Claude, e.g. “only trade in the direction of the 4 h trend” – sent with every check.",
                "Optional. Eigene Regeln oder Schwerpunkte für Claude, z. B. „nur in Richtung des 4-h-Trends handeln“ – wird bei jeder Prüfung mitgeschickt.")),
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
            self._client = anthropic.AsyncAnthropic(timeout=180.0, max_retries=2)
        return self._client

    async def ask(self, brief: MarketBrief, news: bool, model: str = DEFAULT_MODEL,
                  effort: str = "low") -> tuple[AiDecision, float]:
        """One decision from Claude and what it cost in $. Overridden in tests."""
        mode = (brief.sentiment or {}).get("mode")
        sentiment_hint = SENTIMENT_CONTRARIAN if mode == "contrarian" else SENTIMENT_INFO if mode == "info" else ""
        request: dict[str, Any] = dict(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    ("You may run up to 3 web searches for news about this asset first.\n\n" if news else "")
                    + (sentiment_hint + "\n\n" if sentiment_hint else "")
                    + "Market brief:\n" + brief.to_text()
                ),
            }],
            output_format=AiDecision,
            output_config={"effort": effort},
        )
        if news:
            request["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        if model != "claude-haiku-5-5":  # a declined request is retried on the model Anthropic recommends for it
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        response = await self._get_client().beta.messages.parse(**request)
        cost = call_cost(response.usage, response.model or model)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise AiUnavailable(f"no decision (stop_reason={response.stop_reason})")
        return response.parsed_output, cost

    # --- market data ------------------------------------------------------------

    async def brief(self, ctx: Context, state: dict[str, Any]) -> MarketBrief:
        """Three candle series – 8 h in 5-minute candles, 24 h in 15-minute candles (shared with the engine's 24 h
        change) and 72 h in hourly candles."""
        market, pos, p = ctx.market, ctx.position, ctx.params
        price = float(market.price)
        c5, i5 = await market.candles(8)
        c15, i15 = await market.candles(24)
        c60, i60 = await market.candles(72)
        changes: dict[str, float] = {}
        for label, hours, candles, interval in (("15m", 0.25, c5, i5), ("1h", 1, c5, i5), ("4h", 4, c5, i5),
                                                ("24h", 24, c15, i15), ("72h", 72, c60, i60)):
            ref = _price_at(candles, interval, ctx.now - int(hours * 3_600_000))
            if ref:
                changes[label] = round(float((market.price / ref - 1) * 100), 2)
        closes5 = [float(c.close) for c in c5]
        closes15 = [float(c.close) for c in c15]
        last20 = closes5[-20:]
        bb_pos = None
        if len(last20) == 20:
            mid, sd = statistics.fmean(last20), statistics.pstdev(last20)
            bb_pos = round((price - mid) / (2 * sd), 2) if sd else 0.0  # -1 = lower band, +1 = upper band
        indicators = {
            "rsi14_5m": round(r, 1) if (r := _rsi(closes5)) is not None else None,
            "rsi14_15m": round(r, 1) if (r := _rsi(closes15)) is not None else None,
            "ema9_5m_vs_price_pct": _rel(_ema(closes5, 9), price),
            "ema21_5m_vs_price_pct": _rel(_ema(closes5, 21), price),
            "ema20_15m_vs_price_pct": _rel(_ema(closes15, 20), price),
            "ema50_15m_vs_price_pct": _rel(_ema(closes15, 50), price),
            "atr14_5m_pct": round(a, 3) if (a := _atr_pct(c5)) is not None else None,
            "bollinger20_5m_position": bb_pos,
            "volatility_15m_returns_24h_pct": round(_returns_stdev([c.close for c in c15]), 3),
        }
        per_3h = max(1, int(180 / i5))
        candles_5m = [[_round(float(v), price) for v in (c.open, c.high, c.low, c.close)] for c in c5[-per_3h:]]
        step = max(1, int(60 / i15))
        hourly = [_round(v, price) for v in closes15[::-1][::step][::-1]][-24:]
        high_24h = float(max([c.high for c in c15] + [market.price]))
        low_24h = float(min([c.low for c in c15] + [market.price]))
        high_72h = float(max([c.high for c in c60] + [market.price]))
        low_72h = float(min([c.low for c in c60] + [market.price]))

        sentiment = None
        if p.get("sentiment") in ("info", "contrarian"):
            index = await fetch_fear_greed()
            if index:
                sentiment = {"mode": p["sentiment"], **index}

        position = None
        if pos:
            plan = state.get("plan") or {}
            position = {
                "entry_price": _round(float(pos.entry_price), price),
                "qty": float(pos.qty),
                "profit_pct": round(pos.pnl_pct(market.bid), 2),
                "held_minutes": round((ctx.now - pos.opened_at) / 60_000),
                "highest_price_since_buy": _round(float(pos.peak), price),
                "take_profit": plan.get("target"),
                "stop_loss": plan.get("stop"),
            }
        last = state.get("last")
        previous = None
        if last:
            previous = {k: last.get(k) for k in ("action", "confidence", "reason_en", "take_profit", "stop_loss")}
            previous["minutes_ago"] = round((ctx.now - int(last.get("at") or ctx.now)) / 60_000)
            previous["price_then"] = last.get("price")
        state["atr_5m"] = indicators["atr14_5m_pct"]  # sizes the move that wakes Claude early
        pace = self.pace_ms(ctx, state)
        rules = {
            "limit_wait_minutes": int(p["maker_wait"]),
            "usual_gap_minutes": round(pace / 60_000) if pace else None,
            "max_stop_distance_pct": float(p["stop_loss"]) or None,
            "your_sell_may_realize_a_loss": bool(p["cut_losses"]),
            "min_confidence_for_a_buy": float(p["min_confidence"]) or None,
            "maker_fee_pct": 0,
        }
        return MarketBrief(
            symbol=market.symbol, quote=ctx.quote,
            time_utc=datetime.fromtimestamp(ctx.now / 1000, tz=timezone.utc).strftime("%a %Y-%m-%d %H:%M"),
            price=price, bid=float(market.bid), ask=float(market.ask),
            spread_pct=round(float((market.ask - market.bid) / market.price * 100), 4) if market.price else 0.0,
            changes_pct=changes,
            indicators=indicators,
            candles_5m=candles_5m,
            hourly_closes_24h=hourly,
            range={
                "high_24h": _round(high_24h, price), "low_24h": _round(low_24h, price),
                "high_72h": _round(high_72h, price), "low_72h": _round(low_72h, price),
            },
            position=position,
            amount=float(p["amount"]),
            rules=rules,
            previous_decision=previous,
            recent_trades=list(state.get("trades") or [])[-HISTORY:],
            owner_instructions=str(p.get("instructions") or ""),
            sentiment=sentiment,
        )

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
        """Remember when a position opened and record it with its result once it is closed – Claude sees its own
        recent trades in every brief."""
        pos, opened = ctx.position, state.get("open")
        realized = Decimal(str(ctx.state.get("realized") or 0))
        if pos is not None and (opened is None or opened.get("id") != pos.id):
            plan = state.pop("entry_plan", None) or {}
            entry = float(pos.entry_price)
            target = entry * (1 + plan["target_pct"] / 100) if plan.get("target_pct") else None
            stop = entry * (1 - plan["stop_pct"] / 100) if plan.get("stop_pct") else None
            state["plan"] = self._bounded_plan(ctx, entry, target, stop, None)
            if not plan and (state["plan"].get("stop") or 0) >= float(ctx.market.bid):
                # a position from before this strategy (or an update) already beyond the max. stop: not sold
                # blindly – Claude is asked right away and sets the plan
                state["plan"]["stop"] = None
                state["next_at"] = 0
            state["open"] = {"id": pos.id, "at": pos.opened_at, "realized": str(realized), "cost": str(pos.cost),
                             "entry": entry}
            state.pop("exit", None)
        elif pos is None and opened is not None:
            pnl = realized - Decimal(opened["realized"])
            cost = Decimal(opened["cost"])
            trades = list(state.get("trades") or [])
            trades.append({
                "closed_minutes_ago": 0,
                "closed_at": ctx.now,
                "held_minutes": round((ctx.now - int(opened["at"])) / 60_000),
                "entry": opened["entry"],
                "result_pct": round(float(pnl / cost * 100), 2) if cost else 0.0,
                "exit": state.pop("exit_cause", "unknown"),
            })
            state["trades"] = trades[-HISTORY:]
            for key in ("open", "plan", "exit"):
                state.pop(key, None)
        for t in state.get("trades") or []:
            t["closed_minutes_ago"] = round((ctx.now - int(t.get("closed_at") or ctx.now)) / 60_000)

    def _bounded_plan(self, ctx: Context, entry: float, target: float | None, stop: float | None,
                      current: dict[str, Any] | None) -> dict[str, Any]:
        """Take-profit and stop within the owner's limits: the stop never further than the max. stop-loss from the
        entry and never lowered once set."""
        price = float(ctx.market.price)
        max_stop = float(ctx.params["stop_loss"])
        # measured from the entry – or from the price when a position from before is already further down
        floor = min(entry, price) * (1 - max_stop / 100) if max_stop > 0 else None
        if stop is not None and not 0 < stop < price:  # a stop at or above the price would sell right away
            stop = None
        if floor is not None:
            stop = max(stop or floor, floor)
        if current and current.get("stop") is not None:
            stop = max(stop or 0, float(current["stop"])) or None
        if target is not None and target <= price:
            target = (current or {}).get("target")
        return {"target": _round(target, price) if target else None, "stop": _round(stop, price) if stop else None}

    # --- strategy ---------------------------------------------------------------

    async def evaluate(self, ctx: Context) -> Decision:
        p, market, pos = ctx.params, ctx.market, ctx.position
        state = ctx.state.setdefault("ai", {})
        self._track_trades(ctx, state)
        plan = state.get("plan") or {}
        ctx.targets(sell=plan.get("target") if pos else None, stop=plan.get("stop") if pos else None,
                    note=m("targets.ai"))

        # the plan runs every tick, whether Claude is asked or not
        if pos is not None:
            bid = float(market.bid)
            if plan.get("stop") and bid <= plan["stop"]:
                state["exit_cause"] = "stop"
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

        if not self.configured():
            return Decision(m("ai.no_key"))

        pace = self.pace_ms(ctx, state)
        if pace is None:
            _, end = month_bounds(ctx.now)
            spend = self._spend(ctx, state)
            return Decision(m("ai.budget_used_up", spent=money(float(spend["usd"]), "USD"),
                              budget=money(float(p["budget"]), "USD"), left=dur(end - ctx.now)))

        next_at = int(state.get("next_at") or 0)
        last = state.get("last")
        if ctx.now < next_at and not self._woken(ctx, state):
            if not last:  # backing off after an error
                return Decision(m("ai.retry", left=dur(next_at - ctx.now)))
            return Decision(self._budget_note(ctx, state, self._last_status(ctx, state, next_at)))

        try:
            decision, cost = await self.ask(await self.brief(ctx, state), bool(p["news"]), str(p["model"]),
                                            str(p["effort"]))
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
        return self._apply(ctx, state, decision)

    def _woken(self, ctx: Context, state: dict[str, Any]) -> bool:
        """Ask Claude before its time: a price alert it set was crossed or the price moved unusually far – not
        sooner than the minimum gap (and half the budget's pace) after the last check."""
        last = state.get("last")
        if not last or ctx.now < int(state.get("wake_after") or 0):
            return False
        price = float(ctx.market.price)
        if last.get("wake_above") and price >= last["wake_above"]:
            return True
        if last.get("wake_below") and price <= last["wake_below"]:
            return True
        then = float(last.get("price") or 0)
        return bool(then) and abs(price / then - 1) * 100 >= float(state.get("wake_move") or MIN_WAKE_MOVE * 2)

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
            "action": decision.action, "confidence": decision.confidence,
            "reason_en": decision.reason_en, "reason_de": decision.reason_de, "at": ctx.now, "price": price,
            "take_profit": decision.take_profit or None, "stop_loss": decision.stop_loss or None,
            "wake_above": decision.wake_above if decision.wake_above > price else None,
            "wake_below": decision.wake_below if 0 < decision.wake_below < price else None,
        }
        # when to look again: Claude's wish within the budget – never before the minimum gap or half the pace
        pace = self.pace_ms(ctx, state) or MAX_GAP_MS
        floor = max(int(p["ai_interval"]) * 60_000, pace // 2)
        wanted = decision.next_check_minutes * 60_000 if decision.next_check_minutes > 0 else pace
        gap = min(max(floor, wanted), max(pace, MAX_GAP_MS))
        state["next_at"] = ctx.now + gap
        state["wake_after"] = ctx.now + floor
        state["wake_move"] = None
        if state.get("atr_5m"):
            state["wake_move"] = max(MIN_WAKE_MOVE, 3 * float(state["atr_5m"]))
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
            state["entry_plan"] = {
                "target_pct": (decision.take_profit / price - 1) * 100 if decision.take_profit > price else None,
                "stop_pct": (1 - decision.stop_loss / price) * 100 if 0 < decision.stop_loss < price else None,
            }
            return Decision(m("ai.buy", confidence=confidence), Buy(Decimal(str(p["amount"])), trade_reason))

        if decision.action == "sell":
            state["exit"] = {"reason": trade_reason, "confidence": decision.confidence}
            state["exit_cause"] = "claude"
            return Decision(m("ai.sell", confidence=confidence), Sell(trade_reason, stop=bool(p["cut_losses"])))
        state["plan"] = self._bounded_plan(
            ctx, float(pos.entry_price),
            decision.take_profit if decision.take_profit > 0 else (state.get("plan") or {}).get("target"),
            decision.stop_loss if decision.stop_loss > 0 else None,
            state.get("plan"),
        )
        plan = state["plan"]
        ctx.targets(sell=plan.get("target"), stop=plan.get("stop"), note=m("targets.ai"))
        return Decision(self._budget_note(ctx, state, m("ai.holding", profit=pct(pos.pnl_pct(market.bid)),
                                                         confidence=confidence, left=left)))
