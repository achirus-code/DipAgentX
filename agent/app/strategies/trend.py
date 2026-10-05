"""Monthly trend follower: once a month all in or all out, judged by the month-end closes of the bot's instrument.

While invested it may hold the currency-hedged share class instead (when the dollar is in a downtrend); while out it
may park the money in bonds instead of cash (when they beat the cash rate)."""

from __future__ import annotations

import calendar
import time
from decimal import Decimal

from .. import macro
from ..exchange import Candle
from ..i18n import L, day, m, money, month, num, pct
from .base import Buy, Context, Decision, Option, Param, Sell, Strategy

MONTHS = L("months", "Monate")
MAX_FALLBACKS = 3


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


def instrument_symbols(text: str, quote: str, limit: int = MAX_FALLBACKS) -> list[str]:
    """ "IE00BF1B7389, LU1407888137-EUR" → ["IE00BF1B7389-EUR", "LU1407888137-EUR"] (Trade Republic symbols)."""
    out = []
    for part in text.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip().upper()
        if not part:
            continue
        symbol = part if "-" in part else f"{part}-{quote}"
        if symbol not in out:
            out.append(symbol)
    return out[:limit]


class TrendStrategy(Strategy):
    key = "trend"
    name = L("Monthly trend follower", "Monatlicher Trendfolger")
    description = L(
        "Checks once a month, on the first trading day, how the price closed the previous month. Above its average "
        "of the last months (or with a better return than the cash rate) the bot holds the whole amount; otherwise "
        "it sells – also at a loss – and waits in cash or parks the money in bonds. Meant for ETFs and gold, e.g. one "
        "bot each for world shares, gold and euro government bonds.",
        "Prüft einmal im Monat, am ersten Handelstag, wie der Kurs den Vormonat geschlossen hat. Liegt er über seinem "
        "Durchschnitt der letzten Monate (oder ist die Rendite besser als der Zins), hält der Bot den ganzen Betrag; "
        "sonst verkauft er – auch mit Verlust – und wartet in Cash oder weicht in Anleihen aus. Gedacht für ETFs und "
        "Gold, z. B. je ein Bot für Weltaktien, Gold und Euro-Staatsanleihen.",
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
            Option("either", L("Price above its average or return better than the cash rate",
                               "Kurs über Durchschnitt oder Rendite besser als Zins")),
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
        Param("cash_rate_auto", L("Cash rate from the Euribor", "Zins aus dem Euribor"), "bool", True,
              L("The return has to beat what cash actually earned in the same months (3-month Euribor, ECB). "
                "Off – or without the data – the fixed rate below counts.",
                "Die Rendite muss schlagen, was Cash in denselben Monaten tatsächlich gebracht hat (3-Monats-Euribor, "
                "EZB). Aus – oder ohne die Daten – gilt der feste Zins darunter.")),
        Param("cash_rate", L("Cash rate", "Zins für Cash"), "percent", 2.0,
              L("What the money earns while it waits (per year) – the return has to beat it.",
                "Was das Geld beim Warten bringt (pro Jahr) – die Rendite muss ihn schlagen."),
              min=0, max=10, step=0.25),
        Param("unemployment", L("Recession sign: unemployment", "Rezessionszeichen: Arbeitslosigkeit"), "bool", False,
              L("A falling trend alone doesn't sell: only with a recession sign switched on here. This one: the US "
                "unemployment rate is above its 12-month average (US Bureau of Labor Statistics). Avoids selling "
                "after dips without an economic downturn; without the data the trend alone decides.",
                "Ein fallender Trend allein verkauft nicht: erst mit einem der hier eingeschalteten "
                "Rezessionszeichen. Dieses: die US-Arbeitslosenquote liegt über ihrem 12-Monats-Schnitt "
                "(US-Statistikamt BLS). Vermeidet Verkäufe nach Rücksetzern ohne Abschwung; ohne die Daten "
                "entscheidet der Trend allein.")),
        Param("claims", L("Recession sign: jobless claims", "Rezessionszeichen: Erstanträge"), "bool", False,
              L("US initial jobless claims of the last complete month more than 5 % above a year earlier (US "
                "Department of Labor, weekly) – reacts weeks before the unemployment rate.",
                "US-Erstanträge auf Arbeitslosenhilfe im letzten vollständigen Monat mehr als 5 % über dem "
                "Vorjahresmonat (US-Arbeitsministerium, wöchentlich) – reagiert Wochen vor der Arbeitslosenquote.")),
        Param("yield_curve", L("Recession sign: yield curve", "Rezessionszeichen: Zinskurve"), "bool", False,
              L("The US 10-year yield was below the 3-month yield at a month end of the last 24 months (US "
                "Treasury) – the classic recession warning.",
                "Die 10-jährige US-Rendite lag an einem Monatsende der letzten 24 Monate unter der 3-monatigen "
                "(US-Finanzministerium) – das klassische Rezessionszeichen.")),
        Param("hedged_symbol", L("Currency-hedged share class", "Währungsgesicherte Variante"), "text", "",
              L("ISIN of the EUR-hedged share class of the same index, e.g. IE00BF1B7389 (MSCI ACWI EUR hedged). "
                "While the euro is above its 12-month average against the dollar (the dollar falling), the bot holds "
                "it instead – the signal keeps using its own instrument. Empty = never.",
                "ISIN der EUR-gesicherten Anteilsklasse desselben Index, z. B. IE00BF1B7389 (MSCI ACWI EUR Hedged). "
                "Solange der Euro über seinem 12-Monats-Schnitt zum Dollar liegt (Dollar fällt), hält der Bot sie "
                "stattdessen – das Signal rechnet weiter mit dem eigenen Instrument. Leer = nie.")),
        Param("fallback_symbols", L("Park in instead of cash", "Ausweichen statt Cash"), "text", "",
              L("Up to three ISINs, e.g. LU0290355717 (euro government bonds) and LU1407888137 (US Treasuries 7-10 "
                "years, EUR hedged). While the trend is down the bot buys the one with the best 12-month return – "
                "only if it beats the cash rate, otherwise it stays in cash. Empty = cash.",
                "Bis zu drei ISINs, z. B. LU0290355717 (Euro-Staatsanleihen) und LU1407888137 (US-Staatsanleihen "
                "7-10 Jahre, EUR-gesichert). Ist der Trend unten, kauft der Bot die mit der besten 12-Monats-Rendite – "
                "nur wenn sie den Zins schlägt, sonst bleibt er in Cash. Leer = Cash.")),
    ]

    @staticmethod
    def _signature(p: dict) -> str:
        return "|".join(str(p[k]) for k in ("signal", "sma_months", "sma_buffer", "momentum_months", "cash_rate",
                                             "cash_rate_auto", "unemployment", "claims", "yield_curve",
                                             "hedged_symbol", "fallback_symbols", "amount"))

    @staticmethod
    async def _hurdle(p: dict, n: int) -> tuple[float, bool]:
        """What cash earned over ``n`` months in % – from the Euribor, else the fixed rate. (value, from Euribor)"""
        if p["cash_rate_auto"] and (c := await macro.euro_cash(n)):
            return c.total * 100, True
        return p["cash_rate"] * n / 12, False

    async def _trend(self, ctx: Context, st: dict, closes: list[tuple[str, Decimal]]) -> tuple[bool, dict]:
        p, q = ctx.params, ctx.quote
        last_month, last = closes[0]
        parts = []
        sma_on = mom_on = False
        if p["signal"] in ("sma", "either"):
            n = p["sma_months"]
            avg = sum((c for _, c in closes[:n]), Decimal(0)) / n
            buffer = Decimal(str(p["sma_buffer"])) / 100
            detail = m("monthly.sma", month=month(last_month), close=money(last, q), n=n, avg=money(avg, q),
                       diff=pct(float((last / avg - 1) * 100)))
            if last > avg * (1 + buffer):
                sma_on = True
            elif last < avg * (1 - buffer):
                sma_on = False
            else:  # inside the buffer: as last month (a new bot waits for a clear uptrend)
                sma_on = bool(st.get("sma_on", st.get("trend_on", False)))
                detail = m("monthly.sma_band", trend=detail, buffer=num(p["sma_buffer"]))
            parts.append(detail)
        if p["signal"] in ("momentum", "either"):
            n = p["momentum_months"]
            ret = float(last / closes[n][1] - 1) * 100
            hurdle, auto = await self._hurdle(p, n)
            mom_on = ret > hurdle
            parts.append(m("monthly.momentum_euribor" if auto else "monthly.momentum", n=n, ret=pct(ret),
                           hurdle=pct(hurdle), month=month(last_month)))
        st["sma_on"] = sma_on
        detail = parts[0] if len(parts) == 1 else m("monthly.either", sma=parts[0], momentum=parts[1])
        return sma_on or mom_on, detail

    @staticmethod
    async def _recession(p: dict) -> tuple[bool | None, dict | None]:
        """Whether a switched-on recession sign shows: True/False, None without any data (or none switched on)."""
        signs, calm = [], []
        if p["unemployment"]:
            if (u := await macro.unemployment()) is None:
                calm.append(m("monthly.missing", what=m("monthly.what_unemployment")))
            else:
                args = dict(rate=num(u.rate), avg=num(u.average), month=month(u.month))
                (signs if u.rising else calm).append(
                    m("monthly.unemployment_up" if u.rising else "monthly.unemployment_down", **args))
        if p["claims"]:
            if (c := await macro.claims()) is None:
                calm.append(m("monthly.missing", what=m("monthly.what_claims")))
            else:
                (signs if c.rising else calm).append(m("monthly.claims", change=pct(c.change * 100), month=month(c.month)))
        if p["yield_curve"]:
            if (curve := await macro.yield_curve()) is None:
                calm.append(m("monthly.missing", what=m("monthly.what_curve")))
            elif curve.warning:
                signs.append(m("monthly.curve_inverted", month=month(curve.last_inverted)))
            else:
                calm.append(m("monthly.curve_normal", spread=num(curve.spread)))
        if signs:
            return True, join(signs)
        if all(message_key(c) == "monthly.missing" for c in calm):
            return None, join(calm) if calm else None
        return False, join(calm)

    async def _parking(self, ctx: Context) -> tuple[str | None, dict | None]:
        """The fallback with the best 12-month return above the cash rate – (symbol, why) or (None, why)."""
        p = ctx.params
        candidates = [s for s in instrument_symbols(p["fallback_symbols"], ctx.quote) if s != ctx.market.symbol]
        if not candidates:
            return None, None
        hurdle, _ = await self._hurdle(p, 12)
        best, best_ret, notes = None, None, []
        for symbol in candidates:
            try:
                view = await ctx.market_of(symbol)
                closes = month_end_closes(await view.daily_candles(31 * 14 + 5), ctx.now)
            except Exception:  # noqa: BLE001 – an unknown ISIN or no data: not a candidate
                notes.append(m("monthly.park_no_data", name=symbol.split("-")[0]))
                continue
            name = view.instrument.get("short") or view.instrument.get("name") or symbol.split("-")[0]
            if len(closes) < 13:
                notes.append(m("monthly.park_no_data", name=name))
                continue
            ret = float(closes[0][1] / closes[12][1] - 1) * 100
            notes.append(m("monthly.park_candidate", name=name, ret=pct(ret)))
            if ret > hurdle and (best_ret is None or ret > best_ret):
                best, best_ret = symbol, ret
        why = m("monthly.park_choice" if best else "monthly.park_none", candidates=join(notes), hurdle=pct(hurdle))
        return best, why

    async def _share_class(self, ctx: Context, st: dict) -> tuple[str, dict | None]:
        """Own instrument or the currency-hedged share class (while the euro rises against the dollar)."""
        p = ctx.params
        hedged = instrument_symbols(p["hedged_symbol"], ctx.quote, 1)
        if not hedged:
            return ctx.market.symbol, None
        if (e := await macro.eurusd()) is None:
            keep = st.get("target") if st.get("target") in (hedged[0], ctx.market.symbol) else ctx.market.symbol
            return keep, m("monthly.hedge_unknown")
        args = dict(rate=num(e.rate, 4), avg=num(e.average, 4), month=month(e.month))
        if e.euro_rising:
            try:
                await ctx.market_of(hedged[0])  # it must exist (and its name is known from here on)
            except Exception:  # noqa: BLE001
                return ctx.market.symbol, m("monthly.hedge_unavailable", name=hedged[0].split("-")[0])
            return hedged[0], m("monthly.hedge_on", **args)
        return ctx.market.symbol, m("monthly.hedge_off", **args)

    async def _decide(self, ctx: Context, st: dict) -> dict | None:
        """The decision for this month, stored in ``st``. Returns a status message when there isn't enough history."""
        p = ctx.params
        sma = p["sma_months"] if p["signal"] in ("sma", "either") else 0
        mom = p["momentum_months"] + 1 if p["signal"] in ("momentum", "either") else 0
        need = max(sma, mom)
        closes = month_end_closes(await ctx.market.daily_candles(31 * (need + 1) + 5), ctx.now)
        if len(closes) < need:
            return m("monthly.no_months", have=len(closes), need=need)
        trend_on, detail = await self._trend(ctx, st, closes)
        on = trend_on
        if not trend_on and (p["unemployment"] or p["claims"] or p["yield_curve"]):
            sign, why = await self._recession(p)
            if sign is None:
                detail = m("monthly.recession_unknown", trend=detail)
            elif sign:
                detail = m("monthly.recession_yes", trend=detail, signs=why)
            else:
                on = True
                detail = m("monthly.recession_no", trend=detail, signs=why)
        extra = None
        if on:
            target, extra = await self._share_class(ctx, st)
        else:
            target, extra = await self._parking(ctx)
        if extra:
            detail = m("monthly.with", detail=detail, extra=extra)
        if st.get("amount") != p["amount"]:
            st.pop("capital", None)  # a new amount starts afresh – e.g. when the bots are rebalanced
        st.update(month=month_of(ctx.now), sig=self._signature(p), trend_on=trend_on, on=on, detail=detail,
                  target=target, amount=p["amount"], at=ctx.now)
        return None

    @staticmethod
    def _name(ctx: Context, symbol: str) -> str:
        info = ctx.market.exchange.instrument(symbol)
        return info.get("short") or info.get("name") or symbol.split("-")[0]

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
        own = ctx.market.symbol
        target = st.get("target", own if st.get("on") else None)
        if pos is None:
            if target is None:
                return Decision(m("monthly.out", detail=detail, date=check))
            capital = st.get("capital") if p["reinvest"] else None
            amount = Decimal(str(capital or p["amount"]))
            # repeated on every tick until it went through (market closed, an order error, a limit)
            if target == own:
                return Decision(m("monthly.buy"), Buy(amount, detail))
            key = "monthly.buy_hedged" if st.get("on") else "monthly.buy_parking"
            return Decision(m(key, name=self._name(ctx, target)), Buy(amount, detail, symbol=target))
        held = pos.symbol or own
        bid = ctx.held_market.bid
        profit = pos.pnl_pct(bid)
        if held == target:
            if held == own:
                return Decision(m("monthly.invested", profit=pct(profit), detail=detail, date=check))
            key = "monthly.invested_in" if st.get("on") else "monthly.parked_in"
            return Decision(m(key, name=self._name(ctx, held), profit=pct(profit), detail=detail, date=check))
        # what the sale brings in – the next buy reinvests it
        st["capital"] = float(pos.net_proceeds(bid, ctx.fees, q))
        if target is None:
            return Decision(m("monthly.exit"), Sell(m("monthly.exit_reason", detail=detail, profit=pct(profit)), stop=True))
        return Decision(m("monthly.switch", name=self._name(ctx, target)),
                        Sell(m("monthly.switch_reason", name=self._name(ctx, target), detail=detail, profit=pct(profit)),
                             stop=True))


def join(messages: list[dict]) -> dict | None:
    """Several messages in one: "a · b · c"."""
    if not messages:
        return None
    out = messages[0]
    for msg in messages[1:]:
        out = m("monthly.and", a=out, b=msg)
    return out


def message_key(msg: dict | str) -> str | None:
    return msg.get("k") if isinstance(msg, dict) else None

