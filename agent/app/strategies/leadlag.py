"""Lead-lag bot: buys a coin right after a large one-minute BTC jump it hasn't followed yet, sells after a fixed time.

The backtest (Binance 1-minute candles 2021–2026, docs/btc-eth-verbindung.md) found that after BTC-USDT rose at least
0.5 % within one minute while ETH-EUR moved less than half of that, ETH-EUR rose another 0.4–0.7 % on average over
the next 15 minutes. Whether that holds on Revolut X is what the lead-lag measurement (``app.leadlag``) checks; this
bot trades the signal of that measurement – paper first. The monitor wakes the engine on every jump, so the order goes
out within seconds. Orders go to the market: speed matters more than the fee, a limit order would trail the price.
"""

from __future__ import annotations

from decimal import Decimal

from .. import leadlag
from ..i18n import L, dur, m, pct
from .base import COOLDOWN_HELP, COOLDOWN_LABEL, Buy, Context, Decision, Param, Sell, Strategy, cooldown_left


class LeadLagStrategy(Strategy):
    key = "leadlag"
    name = L("Lead-lag: follows BTC", "Lead-Lag: folgt BTC")
    description = L(
        "Buys the coin within seconds after BTC jumped by at least 0.5 % in one minute while this coin hasn't moved "
        "with it yet, and sells after 15 minutes. Uses the live BTC price from Binance (lead-lag measurement). "
        "Backtest ETH-EUR 2021–2026: +0.4 to +0.7 % on average per signal before costs, 25–140 signals a year. "
        "Market orders (speed over fee). Start in paper mode – whether Revolut X lags like Binance is still being "
        "measured.",
        "Kauft den Coin wenige Sekunden nachdem BTC in einer Minute um mindestens 0,5 % gesprungen ist und dieser "
        "Coin noch nicht mitgezogen hat, und verkauft nach 15 Minuten. Nutzt den Live-BTC-Kurs von Binance "
        "(Lead-Lag-Messung). Backtest ETH-EUR 2021–2026: im Schnitt +0,4 bis +0,7 % je Signal vor Kosten, 25–140 "
        "Signale im Jahr. Market-Orders (Tempo vor Gebühr). Erst im Paper-Modus starten – ob Revolut X so nachhinkt "
        "wie Binance, wird noch gemessen.",
    )
    icon = "bolt.circle"
    params = [
        Param("amount", L("Amount per trade", "Betrag pro Trade"), "money", 100.0, min=1),
        Param("min_jump", L("BTC jump of at least", "BTC-Sprung mindestens"), "percent", 0.5,
              L("BTC-USDT rise within 60 seconds that triggers a buy. Smaller jumps didn't pay after costs in the backtest.",
                "Anstieg von BTC-USDT innerhalb von 60 Sekunden, der einen Kauf auslöst. Kleinere Sprünge lohnten im "
                "Backtest nach Kosten nicht."), min=0.3, max=5, step=0.1),
        Param("only_lagging", L("Only if the coin lagged", "Nur wenn der Coin nachhinkt"), "bool", True,
              L("Buy only if the coin rose less than half as much as BTC in the same minute.",
                "Nur kaufen, wenn der Coin in derselben Minute weniger als halb so stark gestiegen ist wie BTC.")),
        Param("hold_minutes", L("Sell after", "Verkaufen nach"), "int", 15,
              L("Holding time; the backtest gain came within 15 minutes.", "Haltedauer; der Gewinn kam im Backtest "
                "innerhalb von 15 Minuten."), min=1, max=240, unit="min"),
        Param("max_delay_s", L("Max. delay after the jump", "Max. Verzögerung nach dem Sprung"), "int", 60,
              L("Older signals are ignored – a minute later part of the gain was gone.",
                "Ältere Signale werden ignoriert – eine Minute später war ein Teil des Gewinns weg."),
              min=5, max=600, unit="s"),
        Param("stop_loss", L("Stop-loss", "Stop-Loss"), "percent", 1.5,
              L("Sell early at this loss. 0 = off.", "Vorzeitig verkaufen bei so viel Verlust. 0 = aus."),
              min=0, max=20, step=0.1),
        Param("cooldown_minutes", COOLDOWN_LABEL, "int", 0, COOLDOWN_HELP, min=0, max=10080, unit="min"),
    ]

    async def evaluate(self, ctx: Context) -> Decision:
        p, pos, st = ctx.params, ctx.position, ctx.state.setdefault("leadlag", {})
        if pos is not None:
            held = ctx.now - int(st.get("entry_at") or pos.opened_at)  # the bot's clock, also in tests
            hold = int(p["hold_minutes"]) * 60_000
            loss = pos.pnl_pct(ctx.market.bid)
            if p["stop_loss"] > 0 and loss <= -p["stop_loss"]:
                return Decision(m("leadlag.stop"), Sell(m("leadlag.stop_reason", profit=pct(loss)), stop=True))
            if held >= hold:
                return Decision(m("leadlag.time_up"), Sell(m("leadlag.sell_reason", minutes=int(p["hold_minutes"]),
                                                            profit=pct(loss)), stop=True))
            ctx.targets(note=m("leadlag.target", left=dur(hold - held)))
            return Decision(m("leadlag.holding", profit=pct(loss), left=dur(hold - held)))

        symbol = ctx.market.symbol
        signal = leadlag.latest_signal()
        last = m("leadlag.no_jump_yet") if not signal else m(
            "leadlag.last_jump", jump=pct(signal["btc_usdt_jump_pct"]), ago=dur(max(0, ctx.now - int(signal["at"]))))
        ctx.targets(note=m("leadlag.waiting_short", jump=pct(p["min_jump"])))
        if not leadlag.enabled():
            return Decision(m("leadlag.off"))
        if signal and symbol not in signal.get("coins", {}):
            return Decision(m("leadlag.not_measured", symbol=symbol))
        wait = cooldown_left(ctx, p["cooldown_minutes"])
        if wait:
            return Decision(m("cooldown", left=dur(wait)))
        waiting = Decision(m("leadlag.waiting", jump=pct(p["min_jump"]), last=last))
        if not signal or st.get("used") == signal["at"]:
            return waiting
        age = ctx.now - int(signal["at"])
        coin = signal["coins"][symbol]
        if (signal["direction"] != "up" or signal["btc_usdt_jump_pct"] < p["min_jump"]
                or age > int(p["max_delay_s"]) * 1000 or (p["only_lagging"] and not coin.get("lagged"))):
            return waiting
        st["used"], st["entry_at"] = signal["at"], ctx.now
        reason = m("leadlag.buy_reason", jump=pct(signal["btc_usdt_jump_pct"]),
                   coin=pct(coin["same_minute_pct"]) if coin.get("same_minute_pct") is not None else "–",
                   delay=f"{age / 1000:.0f}")
        return Decision(m("leadlag.buy"), Buy(Decimal(str(p["amount"])), reason))
