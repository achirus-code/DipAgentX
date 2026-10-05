"""Dip buyer: buy after the price dropped by X % within a time window, sell on recovery."""

from __future__ import annotations

from decimal import Decimal

from ..i18n import L, dur, m, money, num, pct
from .base import (
    COOLDOWN_HELP, COOLDOWN_LABEL, Buy, Context, Decision, Option, Param, Sell, Strategy, cooldown_left,
    multi_trade_params,
)


class DipStrategy(Strategy):
    key = "dip"
    name = L("Dip buyer", "Dip-Käufer")
    description = L(
        "Buys once the price change within the time window (e.g. 24 h) falls below the buy threshold (e.g. −1 %) "
        "and sells when the price has recovered (e.g. 24h change ≥ 0 %) or the profit target is reached.",
        "Kauft, sobald die Kursveränderung im Zeitfenster (z. B. 24 h) unter die Kaufschwelle fällt (z. B. −1 %), "
        "und verkauft, wenn sich der Kurs wieder erholt hat (z. B. 24h-Veränderung ≥ 0 %) oder das Gewinnziel erreicht ist.",
    )
    icon = "arrow.down.right.circle"
    multi_trades = True
    params = [
        Param("amount", L("Amount per buy", "Betrag pro Kauf"), "money", 50.0,
              L("How much of the quote currency is invested per buy.", "Wie viel in der Quote-Währung pro Kauf investiert wird."), min=1),
        Param("lookback_hours", L("Time window", "Zeitfenster"), "int", 24,
              L("Over how many hours the change is measured.", "Über wie viele Stunden die Veränderung gemessen wird."),
              min=1, max=168, unit="h"),
        Param("buy_threshold", L("Buy at change ≤", "Kaufen bei Veränderung ≤"), "percent", -1.0,
              L("e.g. −1 % = the price fell by at least 1 % within the window.", "z. B. −1 % = Kurs ist im Zeitfenster um mind. 1 % gefallen."),
              min=-50, max=0, step=0.1),
        Param("max_adx", L("Only buy while ADX (4h) below", "Nur kaufen, solange ADX (4h) unter"), "number", 0.0,
              L("Sideways filter: buys only while the trend strength ADX (14) of the 4-hour candles is below this value – "
                "below about 20–25 the market moves sideways and dips tend to recover, above it it trends and a dip "
                "often keeps falling. Selling isn't affected. 0 = off.",
                "Seitwärtsfilter: kauft nur, solange die Trendstärke ADX (14) der 4-Stunden-Kerzen unter diesem Wert "
                "liegt – unter etwa 20–25 läuft der Markt seitwärts und Dips erholen sich eher, darüber trendet er und "
                "ein Dip fällt oft weiter. Verkäufe betrifft das nicht. 0 = aus."),
              min=0, max=100, step=1),
        Param("sell_mode", L("Sell when", "Verkaufen wenn"), "select", "change", options=[
            Option("change", L("Change recovered", "Veränderung wieder erreicht")),
            Option("profit", L("Profit target reached", "Gewinnziel erreicht")),
            Option("either", L("Whichever comes first", "Was zuerst eintritt")),
        ]),
        Param("sell_threshold", L("Sell at change ≥", "Verkaufen bei Veränderung ≥"), "percent", 0.0,
              L("e.g. 0 % = the price is back at its level of 24 h ago.", "z. B. 0 % = Kurs liegt wieder auf dem Niveau von vor 24 h."),
              min=-50, max=50, step=0.1),
        Param("take_profit", L("Profit target", "Gewinnziel"), "percent", 2.0,
              L("Sell as soon as the position has this much profit.", "Verkauf, sobald die Position so viel Gewinn hat."),
              min=0.1, max=100, step=0.1),
        Param("min_profit", L("Minimum profit", "Mindestgewinn"), "percent", 0.25,
              L("With “Change recovered” and with trailing, only sell with at least this profit. The bot never sells at a loss anyway – only the stop-loss does.",
                "Bei „Veränderung erreicht“ und beim Trailing nur verkaufen, wenn mindestens dieser Gewinn erzielt wird. Mit Verlust verkauft der Bot ohnehin nie – nur der Stop-Loss."),
              min=0, max=100, step=0.05),
        Param("trail", L("Trailing after the sell signal", "Trailing nach Verkaufssignal"), "percent", 0.0,
              L("Instead of selling as soon as the sell rule is met, a trailing stop follows the price and sells once it "
                "falls this far below its high since then – never below the minimum profit. 0 = off.",
                "Statt bei erfüllter Verkaufsregel sofort zu verkaufen, läuft ein Trailing-Stop mit und verkauft erst, wenn "
                "der Kurs so weit unter sein Hoch seitdem fällt – nie unter dem Mindestgewinn. 0 = aus."),
              min=0, max=50, step=0.1),
        Param("stop_loss", L("Stop-loss", "Stop-Loss"), "percent", 0.0,
              L("Sell at this loss. 0 = off.", "Verkauf bei so viel Verlust. 0 = aus."), min=0, max=90, step=0.5),
        Param("trend_days", L("Trend filter: long average", "Trendfilter: langer Schnitt"), "int", 0,
              L("Only buy while the price is above its average over this many days (e.g. 200) – no buys in a "
                "downtrend. 0 = off.",
                "Nur kaufen, solange der Kurs über seinem Durchschnitt dieser Anzahl Tage liegt (z. B. 200) – keine "
                "Käufe im Abwärtstrend. 0 = aus."),
              min=0, max=365, unit=L("days", "Tage")),
        Param("trend_fast_days", L("Trend filter: short average", "Trendfilter: kurzer Schnitt"), "int", 0,
              L("In addition, the price must be above its average over this many days (e.g. 60) – notices a turn "
                "of the trend sooner. 0 = off.",
                "Zusätzlich muss der Kurs über seinem Durchschnitt dieser Anzahl Tage liegen (z. B. 60) – erkennt "
                "eine Trendwende früher. 0 = aus."),
              min=0, max=365, unit=L("days", "Tage")),
        Param("trend_buffer", L("Trend filter: buffer", "Trendfilter: Puffer"), "percent", 3.0,
              L("The price must be this far above the long average to count as an uptrend and this far below it to "
                "count as a downtrend. In between the last state stays – so the filter doesn't flip back and forth.",
                "So weit muss der Kurs über dem langen Schnitt liegen, damit er als Aufwärtstrend gilt, und so weit "
                "darunter für einen Abwärtstrend. Dazwischen bleibt der letzte Zustand – damit der Filter nicht hin "
                "und her springt."),
              min=0, max=20, step=0.5),
        Param("trend_exit", L("Sell when the trend breaks", "Verkaufen bei Trendbruch"), "bool", False,
              L("Sells open trades as soon as the trend filter reports a downtrend – also at a loss, like a "
                "stop-loss. Needs a trend filter.",
                "Verkauft offene Trades, sobald der Trendfilter einen Abwärtstrend meldet – auch mit Verlust, wie ein "
                "Stop-Loss. Braucht einen Trendfilter.")),
        Param("cooldown_minutes", COOLDOWN_LABEL, "int", 60, COOLDOWN_HELP, min=0, max=10080, unit="min"),
        *multi_trade_params(),
    ]

    async def trend(self, ctx: Context) -> tuple[bool | None, dict, Decimal | None] | None:
        """The trend filter: (True = uptrend, False = downtrend, None = not enough history; detail message; the price
        above which it is an uptrend). None when it is off. Between the buffer lines around the long average the last
        state stays."""
        p, market = ctx.params, ctx.market
        slow, fast = p["trend_days"], p["trend_fast_days"]
        if not slow and not fast:
            ctx.state.pop("trend_up", None)
            return None
        need = max(slow, fast)
        closes = await market.daily_closes(need)
        if len(closes) < need:
            return None, m("trend.no_history", days=len(closes), need=need), None
        averages = {days: sum(closes[-days:], Decimal(0)) / days for days in (slow, fast) if days}
        price, buffer = market.price, Decimal(str(p["trend_buffer"])) / 100
        up = (not slow or price > averages[slow] * (1 + buffer)) and (not fast or price > averages[fast])
        down = (slow and price < averages[slow] * (1 - buffer)) or (fast and price < averages[fast])
        state = True if up else False if down else bool(ctx.state.get("trend_up", False))
        ctx.state["trend_up"] = state
        detail = m("trend.detail", price=money(price, ctx.quote),
                   averages=[m("trend.average", days=d, avg=money(a, ctx.quote)) for d, a in averages.items()])
        level = max(averages[slow] * (1 + buffer) if slow else Decimal(0), averages[fast] if fast else Decimal(0))
        return state, detail, level

    async def evaluate(self, ctx: Context) -> Decision:
        p, market, pos = ctx.params, ctx.market, ctx.position
        hours = p["lookback_hours"]
        ref = await market.price_at(hours)
        change = float((market.price / ref - 1) * 100) if ref else 0.0
        window = m("window", hours=hours, change=pct(change))

        if pos is None:
            trend = await self.trend(ctx)
            if trend and not trend[0]:
                ctx.targets(note=m("targets.trend"))
                if trend[0] is None:
                    return Decision(trend[1])
                return Decision(m("dip.trend_down", level=money(trend[2], ctx.quote), detail=trend[1]))
            ctx.targets(buy=ref * (1 + Decimal(str(p["buy_threshold"])) / 100))
            wait = cooldown_left(ctx, p["cooldown_minutes"])
            if wait:
                return Decision(m("cooldown.window", left=dur(wait), window=window))
            if change <= p["buy_threshold"]:
                if p["max_adx"] > 0:
                    # a dip in a trend tends to keep falling – only buy it while the market moves sideways
                    strength = await market.adx(240)
                    if strength is None:
                        return Decision(m("dip.adx_missing", window=window))
                    if strength >= p["max_adx"]:
                        return Decision(m("dip.trending", window=window, adx=num(strength, 0), max=num(p["max_adx"], 0)))
                reason = m("dip.buy_reason", hours=hours, change=pct(change), threshold=pct(p["buy_threshold"]))
                return Decision(m("dip.buy_signal", window=window), Buy(Decimal(str(p["amount"])), reason))
            return Decision(m("dip.waiting", window=window, threshold=pct(p["buy_threshold"])))

        profit = pos.pnl_pct(market.bid)
        mode = p["sell_mode"]
        q = ctx.quote
        entry = pos.entry_price
        min_price = entry * (1 + Decimal(str(p["min_profit"])) / 100)
        stop_loss = entry * (1 - Decimal(str(p["stop_loss"])) / 100) if p["stop_loss"] > 0 else None
        trail = p["trail"]

        def trailing_stop(high: Decimal) -> Decimal:
            # follows the high since the sell signal – never below the minimum profit or break-even
            return max(high * (1 - Decimal(str(trail)) / 100), min_price, pos.break_even_price(ctx.fees, q))

        if p["trend_exit"] and (trend := await self.trend(ctx)) and trend[0] is False:
            # like a stop-loss: out of the downtrend, at a loss if need be
            reason = m("dip.trend_exit.reason", detail=trend[1], profit=pct(profit))
            return Decision(m("dip.trend_exit"), Sell(reason, stop=True))

        if trail > 0 and pos.trail_peak is not None:
            # the sell rule was met earlier: from then on only the trailing stop sells (or the stop-loss)
            stop = trailing_stop(pos.trail_peak)
            ctx.targets(sell=stop, stop=stop_loss, note=m("targets.trailing"))
            if p["stop_loss"] > 0 and profit <= -p["stop_loss"]:
                return Decision(m("stop_loss"), Sell(m("stop_loss.reason", profit=pct(profit)), stop=True))
            if market.price <= stop:
                if profit >= p["min_profit"]:
                    reason = m("trailing.triggered_reason", stop=money(stop, q), high=money(pos.trail_peak, q), profit=pct(profit))
                    return Decision(m("trailing.triggered"), Sell(reason))
                return Decision(m("dip.trailing_hold", stop=money(stop, q), profit=pct(profit), min=pct(p["min_profit"])))
            return Decision(m("trailing.active", stop=money(stop, q), profit=pct(profit)))

        # the price the sale waits for: profit target and/or recovered change (never below the minimum profit)
        sell_at = []
        if mode in {"profit", "either"}:
            sell_at.append(entry * (1 + Decimal(str(p["take_profit"])) / 100))
        if mode in {"change", "either"}:
            sell_at.append(max(ref * (1 + Decimal(str(p["sell_threshold"])) / 100), min_price))
        ctx.targets(sell=min(sell_at) if sell_at else None, stop=stop_loss,
                    note=m("targets.trailing_from") if trail > 0 else None)
        if p["stop_loss"] > 0 and profit <= -p["stop_loss"]:
            return Decision(m("stop_loss"), Sell(m("stop_loss.reason", profit=pct(profit)), stop=True))

        signal: tuple[dict, dict] | None = None  # (status, reason) of a met sell rule
        if mode in {"profit", "either"} and profit >= p["take_profit"]:
            signal = m("take_profit"), m("take_profit.reason", profit=pct(profit), target=pct(p["take_profit"]))
        elif mode in {"change", "either"} and change >= p["sell_threshold"]:
            if profit < p["min_profit"]:
                return Decision(m("dip.recovered_hold", profit=pct(profit), min=pct(p["min_profit"])))
            signal = m("dip.recovered"), m("dip.recovered.reason", hours=hours, change=pct(change),
                                           threshold=pct(p["sell_threshold"]), profit=pct(profit))
        if signal and trail > 0:
            # don't sell yet: arm the trailing stop – it follows the price from here on
            pos.trail_peak = market.price
            stop = trailing_stop(market.price)
            ctx.targets(sell=stop, stop=stop_loss, note=m("targets.trailing"))
            return Decision(m("dip.trailing_armed", stop=money(stop, q), profit=pct(profit)))
        if signal:
            return Decision(signal[0], Sell(signal[1]))

        targets = []
        if mode in {"change", "either"}:
            targets.append(m("dip.target_change", hours=hours, threshold=pct(p["sell_threshold"])))
        if mode in {"profit", "either"}:
            targets.append(m("dip.target_profit", target=pct(p["take_profit"])))
        if trail > 0:
            return Decision(m("dip.position_trailing", profit=pct(profit), window=window, targets=targets, trail=pct(-trail)))
        return Decision(m("dip.position", profit=pct(profit), window=window, targets=targets))
