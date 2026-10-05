"""Monthly trend follower: once a month all in or all out of one instrument, judged by its month-end closes."""

from __future__ import annotations

import calendar
import time
from decimal import Decimal

from .. import macro
from ..exchange import Candle
from ..i18n import L, day, m, money, month, num, pct
from .base import Buy, Context, Decision, Option, Param, Sell, Strategy

MONTHS = L("months", "Monate")


def month_of(ms: int) -> str:
    """The UTC month of a point in time: "2026-10"."""
    t = time.gmtime(ms / 1000)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def next_month_start(ms: int) -> int:
    t = time.gmtime(ms / 1000)
    year, mon = (t.tm_year + 1, 1) if t.tm_mon == 12 else (t.tm_year, t.tm_mon + 1)
    return calendar.timegm((year, mon, 1, 0, 0, 0)) * 1000


def previous_month(key: str) -> str:
    year, mon = map(int, key.split("-"))
    return f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"


def month_end_closes(candles: list[Candle], now: int) -> list[tuple[str, Decimal]]:
    """The close of the last trading day of every completed month, newest first – stops at the first month without
    any candle, so a gap never mixes up the months."""
    last: dict[str, Decimal] = {}
    for c in sorted(candles, key=lambda c: c.start):
        last[month_of(c.start)] = c.close
    out: list[tuple[str, Decimal]] = []
    key = previous_month(month_of(now))
    while key in last:
        out.append((key, last[key]))
        key = previous_month(key)
    return out


class TrendStrategy(Strategy):
    key = "trend"
    name = L("Monthly trend follower", "Monatlicher Trendfolger")
    description = L(
        "Checks once a month, on the first trading day, how the price closed the previous month. Above its average "
        "of the last months (or with a better return than the cash rate) the bot holds the whole amount; otherwise "
        "it sells – also at a loss – and waits in cash. Meant for ETFs and gold, e.g. one bot each for world shares, "
        "gold and euro government bonds.",
        "Prüft einmal im Monat, am ersten Handelstag, wie der Kurs den Vormonat geschlossen hat. Liegt er über seinem "
        "Durchschnitt der letzten Monate (oder ist die Rendite besser als der Zins), hält der Bot den ganzen Betrag; "
        "sonst verkauft er – auch mit Verlust – und wartet in Cash. Gedacht für ETFs und Gold, z. B. je ein Bot für "
        "Weltaktien, Gold und Euro-Staatsanleihen.",
    )
    icon = "calendar.badge.clock"
    params = [
        Param("amount", L("Amount", "Betrag"), "money", 1000.0,
              L("Invested as a whole while the trend is up.", "Wird als Ganzes investiert, solange der Trend steigt."),
              min=1),
        Param("reinvest", L("Reinvest the proceeds", "Erlös wieder anlegen"), "bool", True,
              L("After a sale the next buy uses what that sale brought in – profits keep working, losses aren't "
                "topped up. Off: always the amount above. Changing the amount starts afresh from it.",
                "Nach einem Verkauf kauft der Bot mit dem Erlös dieses Verkaufs – Gewinne arbeiten weiter, Verluste "
                "werden nicht aufgefüllt. Aus: immer der Betrag oben. Ein geänderter Betrag gilt ab sofort."),
              ),
        Param("signal", L("Trend signal", "Trendsignal"), "select", "sma", options=[
            Option("sma", L("Price above its average", "Kurs über seinem Durchschnitt")),
            Option("momentum", L("Return better than the cash rate", "Rendite besser als der Zins")),
        ]),
        Param("sma_months", L("Average over", "Durchschnitt über"), "int", 10,
              L("The average of this many month-end closes (e.g. 10).",
                "Der Durchschnitt so vieler Monatsschlusskurse (z. B. 10)."),
              min=2, max=24, unit=MONTHS),
        Param("sma_buffer", L("Buffer", "Puffer"), "percent", 2.0,
              L("Buy only this far above the average, sell only this far below it – in between nothing changes, "
                "so a price close to the average doesn't trade back and forth.",
                "Kauf erst so weit über dem Durchschnitt, Verkauf erst so weit darunter – dazwischen ändert sich "
                "nichts, damit ein Kurs nahe am Durchschnitt nicht hin und her handelt."),
              min=0, max=10, step=0.5),
        Param("momentum_months", L("Return over", "Rendite über"), "int", 12,
              L("Invested while the return over this many months (month-end closes) beats the cash rate.",
                "Investiert, solange die Rendite über so viele Monate (Monatsschlusskurse) den Zins schlägt."),
              min=1, max=24, unit=MONTHS),
        Param("cash_rate", L("Cash rate", "Zins für Cash"), "percent", 2.0,
              L("What the money earns while it waits (per year) – the return has to beat it.",
                "Was das Geld beim Warten bringt (pro Jahr) – die Rendite muss ihn schlagen."),
              min=0, max=10, step=0.25),
        Param("unemployment", L("Sell only when unemployment rises", "Nur verkaufen, wenn die Arbeitslosigkeit steigt"),
              "bool", False,
              L("A falling trend alone doesn't sell: only when the US unemployment rate is also above its 12-month "
                "average (a sign of a recession). Avoids selling after dips without an economic downturn. "
                "The rate comes from the US Bureau of Labor Statistics; without it the trend alone decides.",
                "Ein fallender Trend allein verkauft nicht: erst wenn auch die US-Arbeitslosenquote über ihrem "
                "12-Monats-Schnitt liegt (ein Rezessionszeichen). Vermeidet Verkäufe nach Rücksetzern ohne "
                "Abschwung. Die Quote kommt vom US-Statistikamt (BLS); ohne sie entscheidet der Trend allein.")),
    ]

    @staticmethod
    def _signature(p: dict) -> str:
        return "|".join(str(p[k]) for k in ("signal", "sma_months", "sma_buffer", "momentum_months", "cash_rate",
                                             "unemployment", "amount"))

    async def _decide(self, ctx: Context, st: dict) -> dict | None:
        """The decision for this month, stored in ``st``. Returns a status message when there isn't enough history."""
        p, q = ctx.params, ctx.quote
        sma = p["signal"] == "sma"
        n = p["sma_months"] if sma else p["momentum_months"]
        need = n if sma else n + 1
        closes = month_end_closes(await ctx.market.daily_candles(31 * (need + 1) + 5), ctx.now)
        if len(closes) < need:
            return m("monthly.no_months", have=len(closes), need=need)
        last_month, last = closes[0]
        if sma:
            avg = sum((c for _, c in closes[:n]), Decimal(0)) / n
            buffer = Decimal(str(p["sma_buffer"])) / 100
            detail = m("monthly.sma", month=month(last_month), close=money(last, q), n=n, avg=money(avg, q),
                       diff=pct(float((last / avg - 1) * 100)))
            if last > avg * (1 + buffer):
                trend_on = True
            elif last < avg * (1 - buffer):
                trend_on = False
            else:  # inside the buffer: as last month (a new bot waits for a clear uptrend)
                trend_on = bool(st.get("trend_on", False))
                detail = m("monthly.sma_band", trend=detail, buffer=num(p["sma_buffer"]))
        else:
            ret = float(last / closes[n][1] - 1) * 100
            hurdle = p["cash_rate"] * n / 12
            trend_on = ret > hurdle
            detail = m("monthly.momentum", n=n, ret=pct(ret), hurdle=pct(hurdle), month=month(last_month))
        on = trend_on
        if p["unemployment"] and not trend_on:
            u = await macro.unemployment()
            if u is None:
                note = m("monthly.unemployment_unavailable")
            else:
                args = dict(rate=num(u.rate), avg=num(u.average), month=month(u.month))
                on = not u.rising
                note = m("monthly.unemployment_holds" if on else "monthly.unemployment_rising", **args)
            detail = m("monthly.with_unemployment", trend=detail, unemployment=note)
        if st.get("amount") != p["amount"]:
            st.pop("capital", None)  # a new amount starts afresh – e.g. when the bots are rebalanced
        st.update(month=month_of(ctx.now), sig=self._signature(p), trend_on=trend_on, on=on, detail=detail,
                  amount=p["amount"], at=ctx.now)
        return None

    async def evaluate(self, ctx: Context) -> Decision:
        p, pos, q = ctx.params, ctx.position, ctx.quote
        st = ctx.state.setdefault("monthly", {})
        check = day(next_month_start(ctx.now))
        ctx.targets(note=m("targets.trend_check", date=check))
        if st.get("month") != month_of(ctx.now) or st.get("sig") != self._signature(p):
            # a new month (the engine only gets here while the market is open – so on its first trading day)
            if waiting := await self._decide(ctx, st):
                return Decision(waiting)
        detail = st["detail"]
        if pos is None:
            if not st["on"]:
                return Decision(m("monthly.out", detail=detail, date=check))
            capital = st.get("capital") if p["reinvest"] else None
            amount = Decimal(str(capital or p["amount"]))
            # repeated on every tick until it went through (market closed, an order error, a limit)
            return Decision(m("monthly.buy"), Buy(amount, detail))
        profit = pos.pnl_pct(ctx.market.bid)
        if st["on"]:
            return Decision(m("monthly.invested", profit=pct(profit), detail=detail, date=check))
        # what the sale brings in – the next buy reinvests it
        st["capital"] = float(pos.net_proceeds(ctx.market.bid, ctx.fees, q))
        return Decision(m("monthly.exit"), Sell(m("monthly.exit_reason", detail=detail, profit=pct(profit)), stop=True))
