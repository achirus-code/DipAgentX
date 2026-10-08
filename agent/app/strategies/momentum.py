"""Momentum trend follower for coins: how much of the bot's capital is invested follows the trend, in 10 % steps.

Six lookbacks (14 to 60 days) on the 4-hour closes each count as "up" once the price rose more than the entry
threshold over that time and as "down" once it fell; the invested share is the share of lookbacks that are up. Very
volatile markets get a smaller share, and while the futures funding shows panic the bot keeps at least a floor. An
optional brake halves the position while many coins are sent to the exchanges. Every step is its own trade (a slice
of about 10 % of the capital), so the engine can raise and lower the position trade by trade – sales also at a loss.
"""

from __future__ import annotations

import math
import weakref
from bisect import bisect_right
from decimal import Decimal

from .. import cryptodata
from ..i18n import L, dur, m, num, pct
from .base import DAY_MS, HOUR_MS, Buy, Context, Decision, Param, Sell, Strategy, open_positions

LOOKBACKS = (14, 21, 30, 40, 50, 60)  # days
STEP_MS = 4 * HOUR_MS  # the trend is judged on the 4-hour closes
VOL_DAYS = 20  # realized volatility of this many daily returns
WARMUP_DAYS = 14  # the lookbacks' up/down states are rebuilt from this many days (a new bot, a long outage)
HISTORY_DAYS = max(LOOKBACKS) + WARMUP_DAYS + 2
SLICE = Decimal("0.1")  # one step: 10 % of the capital per trade
MIN_BUY = Decimal("0.025")  # a smaller gap to the target (in capital) isn't bought – avoids crumbs
MIN_ORDER = Decimal("10")  # nor below this amount of the quote currency

# a candle read this long after it closed is final – it isn't read again
FINAL_AFTER_MS = 5 * 60_000

# 4-hour closes per exchange and symbol, kept across checks: only new candles are fetched (about one request per
# 4 hours), plus when each request was made
_closes: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_fetched: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


async def four_hour_closes(market) -> dict[int, Decimal]:
    """{candle start: close} of the completed 4-hour candles of the last ``HISTORY_DAYS`` days."""
    store: dict[int, Decimal] = _closes.setdefault(market.exchange, {}).setdefault(market.symbol, {})
    fetched = _fetched.setdefault(market.exchange, {})
    last = market.now // STEP_MS * STEP_MS - STEP_MS  # start of the last completed candle
    first = last - HISTORY_DAYS * DAY_MS
    if store and min(store) <= first and max(store) == last and fetched.get(market.symbol, 0) >= last + STEP_MS + FINAL_AFTER_MS:
        # complete and the newest candle read well after it closed: nothing new until the next candle closes
        for t in [t for t in store if t < first]:
            del store[t]
        return store
    if store and min(store) <= first:
        since = max(store)  # the newest candle once more: fetched right after it closed, it may not have been final
    else:
        store.clear()
        since = first
    chunk = max(1, min(market.exchange.max_candles, 98) - 2) * STEP_MS
    while since <= last:
        until = min(since + chunk, last + STEP_MS)
        for c in await market.exchange.candles(market.symbol, 240, since, until - 1):
            if first <= c.start <= last:
                store[c.start] = c.close
        since = until
    fetched[market.symbol] = market.now
    for t in [t for t in store if t < first]:
        del store[t]
    return store


class History:
    """Lookups in the 4-hour closes: the close at or before a time."""

    def __init__(self, closes: dict[int, Decimal]):
        self.starts = sorted(closes)
        self.closes = [float(closes[t]) for t in self.starts]

    def at(self, start: int) -> float | None:
        """The close of the candle starting at ``start`` (or the last one before, when a candle is missing)."""
        i = bisect_right(self.starts, start) - 1
        return self.closes[i] if i >= 0 and start - self.starts[i] < DAY_MS else None

    def daily(self, end: int) -> float | None:
        """The close of the UTC day ending at ``end`` (= the close of its last 4-hour candle)."""
        return self.at(end - STEP_MS)


def realized_vol(h: History, now: int) -> float | None:
    """Annualized volatility of the last ``VOL_DAYS`` daily returns (completed UTC days)."""
    today = now // DAY_MS * DAY_MS
    closes = [h.daily(today - k * DAY_MS) for k in range(VOL_DAYS, -1, -1)]
    if any(c is None or c <= 0 for c in closes):
        return None
    r = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(r) / len(r)
    return math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1) * 365)


def update_lookbacks(h: History, st: dict, p: dict, last: int) -> None:
    """Brings the up/down state of every lookback up to the candle starting at ``last`` – candle by candle."""
    done = st.get("at")
    if done is None or done < last - WARMUP_DAYS * DAY_MS:  # new, or offline too long: rebuild from scratch
        st["on"] = {str(n): 0 for n in LOOKBACKS}
        done = last - WARMUP_DAYS * DAY_MS
    on = st["on"]
    for start in [t for t in h.starts if done < t <= last]:
        close = h.at(start)
        for n in LOOKBACKS:
            ref = h.at(start - n * DAY_MS)
            if not ref or not close:
                continue
            change = (close / ref - 1) * 100
            if change > p["entry"]:
                on[str(n)] = 1
            elif change < p["exit"]:
                on[str(n)] = 0
    st["at"] = last


def hodl_comparison(state: dict, params: dict, price: Decimal) -> dict | None:
    """What the bot's capital is worth now against having bought the coin with it at the start and simply held
    (no fees) – the start is set with the amount and again after a reset or a switch of the mode."""
    st = state.get("momentum") or {}
    start = st.get("hodl")
    if not start or price <= 0:
        return None
    positions = open_positions(state)
    realized = Decimal(str(state.get("realized") or 0))
    capital = Decimal(str(params["amount"])) + realized - Decimal(st.get("realized_from") or "0")
    value = capital - sum((x.cost for x in positions), Decimal(0)) + sum((x.qty * price for x in positions), Decimal(0))
    start_capital, start_price = Decimal(start["capital"]), Decimal(start["price"])
    return {
        "since": int(start["since"]), "start_price": float(start_price), "start_capital": float(start_capital),
        "value": float(value), "hodl_value": float(start_capital * price / start_price),
    }


class MomentumStrategy(Strategy):
    key = "momentum"
    name = L("Momentum trend follower", "Momentum-Trendfolger")
    description = L(
        "For ETH and BTC: invests the more of its capital the more of six lookbacks (14 to 60 days) point up, in 10 % "
        "steps – fully invested in a clear uptrend, in cash in a downtrend. Very volatile markets get less, and while "
        "the futures funding shows panic it keeps a floor. The position is held in up to 10 trades of 10 % of the capital "
        "each – on entry they are bought one after the other within minutes; when the target falls e.g. to 80 %, two "
        "of them are sold. Rebalances about twice a week, "
        "also at a loss. Gains are reinvested.",
        "Für ETH und BTC: investiert umso mehr seines Kapitals, je mehr von sechs Zeitfenstern (14 bis 60 Tage) "
        "aufwärts zeigen, in 10-%-Stufen – im klaren Aufwärtstrend ganz, im Abwärtstrend in Cash. In sehr "
        "schwankenden Märkten weniger, und solange die Funding-Rate der Futures Panik zeigt, hält er eine "
        "Untergrenze. Die Position liegt in bis zu 10 Trades zu je 10 % des Kapitals – beim Einstieg kauft er sie "
        "nacheinander innerhalb weniger Minuten; sinkt das Ziel z. B. auf 80 %, verkauft er 2 davon. Schichtet etwa "
        "zweimal pro Woche um, auch mit Verlust. "
        "Gewinne werden wieder angelegt.",
    )
    icon = "chart.line.uptrend.xyaxis.circle"
    fixed_trades = 30
    params = [
        Param("amount", L("Capital", "Kapital"), "money", 1000.0,
              L("What the bot manages. Fully invested in a clear uptrend; sales and gains stay in the bot. Changing "
                "it starts afresh from the new amount.",
                "Was der Bot verwaltet. Im klaren Aufwärtstrend ganz investiert; Erlöse und Gewinne bleiben im Bot. "
                "Ein geänderter Betrag gilt ab sofort."), min=10),
        Param("entry", L("A lookback turns up above", "Ein Zeitfenster zählt als aufwärts über"), "percent", 5.0,
              L("A lookback counts as up once the price rose more than this over it (e.g. +5 % in 30 days).",
                "Ein Zeitfenster zählt als aufwärts, sobald der Kurs darüber mehr als so viel gestiegen ist "
                "(z. B. +5 % in 30 Tagen)."), min=0, max=30, step=0.5),
        Param("exit", L("A lookback turns down below", "Ein Zeitfenster zählt als abwärts unter"), "percent", 0.0,
              L("… and as down once the price is below its level of then. In between it stays as it was.",
                "… und als abwärts, sobald der Kurs unter seinem damaligen Stand liegt. Dazwischen bleibt es, wie es "
                "war."), min=-30, max=30, step=0.5),
        Param("vol_target", L("Less when volatility is above", "Weniger, wenn die Schwankung über"), "percent", 100.0,
              L("Annualized volatility of the last 20 days. Above it the bot holds proportionally less: at 125 % "
                "volatility at most 80 %. 0 = off.",
                "Jährliche Schwankung der letzten 20 Tage. Darüber hält der Bot anteilig weniger: bei 125 % "
                "Schwankung höchstens 80 %. 0 = aus."), min=0, max=300, step=5),
        Param("funding_floor", L("Floor while funding is low", "Untergrenze bei niedriger Funding-Rate"), "percent",
              50.0,
              L("While the 7-day average funding rate of the Binance perpetual futures is below the threshold "
                "below – nearly everybody expects falling prices – the bot stays at least this much invested, even "
                "if the trend is down: after such panic the market often turned up. 0 = off.",
                "Solange die Funding-Rate der Binance-Futures im 7-Tage-Schnitt unter der Schwelle unten liegt – fast "
                "alle erwarten fallende Kurse –, bleibt der Bot mindestens so viel investiert, auch wenn der Trend "
                "abwärts zeigt: nach solcher Panik drehte der Markt oft nach oben. 0 = aus."),
              min=0, max=100, step=10),
        Param("funding_below", L("Funding threshold (per year)", "Funding-Schwelle (pro Jahr)"), "percent", 2.0,
              L("Normal is about +10 % a year.", "Normal sind etwa +10 % pro Jahr."), min=-50, max=50, step=0.5),
        Param("inflow_brake", L("Halve on exchange inflows", "Halbieren bei Börsenzuflüssen"), "bool", False,
              L("Halves the position while more coins were sent to the exchanges than withdrawn – more than the "
                "threshold below of what they hold, over 7 days (Coin Metrics, daily). Helped in the backtests, but "
                "only with data at most a day old – without fresh data it does nothing.",
                "Halbiert die Position, solange mehr Coins an die Börsen geschickt als abgezogen wurden – mehr als die "
                "Schwelle unten von ihrem Bestand, über 7 Tage (Coin Metrics, täglich). Half in den Backtests, aber "
                "nur mit höchstens einen Tag alten Daten – ohne frische Daten tut sie nichts.")),
        Param("inflow_above", L("Inflow threshold", "Zufluss-Schwelle"), "percent", 1.0, min=0.1, max=10, step=0.1),
        Param("maker_orders", L("Limit orders first (no fee)", "Erst Limit-Orders (ohne Gebühr)"), "bool", True,
              L("Live on Revolut X: buys at the best bid and sells at the best ask with a limit order, which costs no "
                "fee (maker 0 % instead of 0.09 %). What isn't filled within the waiting time below goes out as a "
                "market order – so every step is executed. Paper trades always simulate market orders.",
                "Live auf Revolut X: kauft zum besten Geldkurs und verkauft zum besten Briefkurs mit einer "
                "Limit-Order, die keine Gebühr kostet (Maker 0 % statt 0,09 %). Was in der Wartezeit unten nicht "
                "ausgeführt ist, geht als Market-Order raus – jede Stufe wird also ausgeführt. Paper-Trades "
                "simulieren immer Market-Orders.")),
        Param("maker_wait", L("Waiting time of the limit order", "Wartezeit der Limit-Order"), "int", 10,
              min=1, max=240, unit="min"),
    ]

    async def target(self, ctx: Context) -> tuple[int | None, dict]:
        """The target in 10 % steps (0–10) and what it is based on; None while the price history is missing.
        Worked out once per check – the engine asks for every open trade."""
        key = (id(ctx.state), repr(sorted(ctx.params.items())))
        cached = getattr(ctx.market, "_momentum_target", None)
        if cached and cached[0] == key:
            return cached[1]
        result = await self._target(ctx)
        ctx.market._momentum_target = (key, result)
        return result

    async def _target(self, ctx: Context) -> tuple[int | None, dict]:
        p, market, st = ctx.params, ctx.market, ctx.state.setdefault("momentum", {})
        h = History(await four_hour_closes(market))
        last = market.now // STEP_MS * STEP_MS - STEP_MS
        need = (max(LOOKBACKS) + WARMUP_DAYS) * DAY_MS
        if not h.starts or h.starts[0] > last - need or h.at(last) is None:
            have = (last - h.starts[0]) // DAY_MS if h.starts else 0
            return None, m("momentum.no_history", have=have, need=need // DAY_MS)
        update_lookbacks(h, st, p, last)
        up = sum(st["on"].values())
        share = up / len(LOOKBACKS)
        parts = [m("momentum.trend", up=up, n=len(LOOKBACKS))]
        scale = 1.0
        vol = realized_vol(h, market.now)
        if vol is not None:
            if p["vol_target"] > 0:
                scale = min(1.0, p["vol_target"] / 100 / max(vol, 0.05))
            parts.append(m("momentum.vol_capped" if scale < 1 else "momentum.vol", vol=num(vol * 100, 0),
                           limit=num(p["vol_target"], 0)))
        weight = share * scale
        base = ctx.market.symbol.split("-")[0]
        if p["funding_floor"] <= 0:
            st.pop("funding_missing_since", None)
        else:
            rate = await cryptodata.funding(base, market.now)
            if rate is None:
                # shown in front of the status and as the card's hint (see evaluate): without the rate the floor is off
                st.setdefault("funding_missing_since", market.now)
                parts.append(m("momentum.funding_missing"))
            else:
                st.pop("funding_missing_since", None)
                if rate < p["funding_below"]:
                    floor = p["funding_floor"] / 100 * scale
                    parts.append(m("momentum.funding_floor", rate=pct(rate), limit=pct(p["funding_below"]),
                                   floor=num(round(floor * 100), 0)))
                    weight = max(weight, floor)
                else:
                    parts.append(m("momentum.funding", rate=pct(rate)))
        if p["inflow_brake"]:
            flow = await cryptodata.exchange_inflow(base, market.now)
            if flow is None:
                parts.append(m("momentum.inflow_missing"))
            elif flow > p["inflow_above"]:
                parts.append(m("momentum.inflow_brake", flow=pct(flow)))
                weight /= 2
            else:
                parts.append(m("momentum.inflow", flow=pct(flow)))
        level = round(min(1.0, max(0.0, weight)) * 10)
        detail = parts[0]
        for part in parts[1:]:
            detail = m("momentum.and", a=detail, b=part)
        return level, detail

    async def evaluate(self, ctx: Context) -> Decision:
        p, st, q = ctx.params, ctx.state.setdefault("momentum", {}), ctx.quote
        level, detail = await self.target(ctx)
        if level is None:
            ctx.targets(note=detail)
            return Decision(detail)
        positions = open_positions(ctx.state)
        bid = ctx.market.bid
        # the capital: the amount plus what the bot's sales gained or lost since the amount was set
        realized = Decimal(str(ctx.state.get("realized") or 0))
        if st.get("amount") != p["amount"]:
            st["amount"], st["realized_from"] = p["amount"], str(realized)
            st.pop("hodl", None)  # a new amount starts the comparison afresh
        capital = Decimal(str(p["amount"])) + realized - Decimal(st["realized_from"])
        if "hodl" not in st:
            # the comparison starts with the capital: at the first buy of the open trades (a bot older than the
            # comparison), else now
            first = min(positions, key=lambda x: x.opened_at, default=None)
            st["hodl"] = {"capital": str(capital), "price": str(first.entry_price if first else ctx.market.ask),
                          "since": first.opened_at if first else ctx.now}
        cash = capital - sum((x.cost for x in positions), Decimal(0))
        exposure = sum((x.qty * bid for x in positions), Decimal(0))
        equity = cash + exposure
        target = equity * level / 10
        invested = float(exposure / equity * 100) if equity > 0 else 0.0
        ctx.targets(note=m("momentum.target", target=num(level * 10, 0)))
        status = m("momentum.status", invested=num(invested, 0), target=num(level * 10, 0), detail=detail)
        ctx.state.pop("warning", None)
        if (since := st.get("funding_missing_since")) is not None:
            # without the funding rate the floor can't protect – say so first (and as the card's hint), not hidden
            # in the details
            warning = m("momentum.funding_down", since=dur(ctx.now - since))
            ctx.state["warning"] = warning
            status = m("momentum.warn", warning=warning, status=status)
        if st.get("held") is not None and sorted(x.id for x in positions) != st["held"]:
            st.pop("level", None)  # trades sold or discarded by hand: back to the target
        if level == st.get("level") or equity <= 0:
            # trades only when the target step changes – in between the position rises and falls with the price
            return Decision(status)

        # lower: sell the trade that brings the position closest to the target (each step is about one trade)
        excess = exposure - target
        if positions and excess > 0:
            def miss(x) -> Decimal:
                return abs(excess - x.qty * bid)
            best = min(positions, key=miss)
            if level == 0 or miss(best) < excess - equity * MIN_BUY:
                if ctx.position is None or ctx.position.id != best.id:
                    return Decision(status)  # the engine asks every trade – only this one is sold
                reason = m("momentum.sell_reason", target=num(level * 10, 0), detail=detail,
                           profit=pct(best.pnl_pct(bid)))
                return Decision(m("momentum.selling", target=num(level * 10, 0)), Sell(reason, stop=True))
        if ctx.position is not None:
            return Decision(status)
        # raise: buy the gap in slices of 10 % of the capital
        gap = min(target - exposure, cash, equity * SLICE)
        if target - exposure >= equity * MIN_BUY and gap >= MIN_ORDER:
            reason = m("momentum.buy_reason", target=num(level * 10, 0), detail=detail)
            return Decision(m("momentum.buying", target=num(level * 10, 0)), Buy(gap.quantize(Decimal("0.01")), reason))
        st["level"] = level  # reached (as close as whole trades allow)
        st["held"] = sorted(x.id for x in positions)
        return Decision(status)
