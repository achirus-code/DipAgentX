# BTC und ETH: Wie hängen sie zusammen, und lässt sich daraus Gewinn machen?

Keine Anlageberatung. Backtests auf vergangenen Kursen.

## Teil 1 – Hypothesen und Vorhersage (geschrieben vor dem Backtest)

Geschrieben am 2026-10-09 und committet, bevor ein Test lief.

Die Idee: „ETH folgt BTC oft.“ Wenn BTC sich zuerst bewegt und ETH mit Verzögerung nachzieht, kann man ETH kaufen,
nachdem BTC gestiegen ist. Das kann auf verschiedenen Zeitebenen gelten:

| # | Hypothese | Regel | Vorhersage |
|---|---|---|---|
| L1 | **Minuten-Vorsprung:** BTC bewegt sich Sekunden bis Minuten vor ETH | BTC steigt in 1–5 min um ≥ x, ETH noch nicht → ETH kaufen, 5–15 min halten. Leader BTC-USDT (liquidester Markt), gehandelt ETH-EUR. Daten: 1-min 2024–2026 | Messbare Korrelation BTC → ETH für 1–2 Minuten, vor allem von USDT zu EUR. Gewinn je Trade aber unter 0,05 % – kleiner als der Spread; mit Limit-Orders praktisch nicht zu fassen (der Kurs läuft weg). **Kein Gewinn.** |
| L2 | **Stunden-/Tages-Vorsprung** | BTC-Rendite der letzten Stunde/des letzten Tages sagt die nächste ETH-Rendite voraus | Kein Zusammenhang (Korrelation ≈ 0) |
| L3 | **BTC als Signal für ETH** | ETH halten, wenn das Momentum-Signal (M6) von **BTC** an ist, statt von ETH selbst | Nicht besser als ETHs eigenes Signal (frühere Tests: BTC-Filter für ETH schlechter) |
| L4 | **ETH/BTC-Verhältnis mit Trend** | Halten, was im Verhältnis stärker ist (ETH/BTC über/unter seinem 30/60-Tage-Schnitt) | Schwach positiv gegenüber 50/50, aber nicht besser als Momentum je Coin |
| L5 | **Aufholen nach Abweichung** | Ist ETH in 24 h um mehr als 2 Standardabweichungen hinter BTC zurückgeblieben → ETH kaufen, 24–72 h halten (Paar-Logik) | Kein verlässliches Aufholen – ETH/BTC hat lange Trends. Kein Gewinn |

Gesamterwartung: **Der Zusammenhang ist sehr eng (Tageskorrelation ~0,8), aber gleichzeitig, nicht zeitversetzt.**
Ein Vorsprung von BTC existiert höchstens im Minutenbereich und ist für einen Bot mit Limit-Orders auf Revolut X
nicht nutzbar. Am ehesten bringt etwas das ETH/BTC-Verhältnis als langsamer Trend (L4).

## Teil 2 – Ergebnisse

(folgt nach dem Test)
