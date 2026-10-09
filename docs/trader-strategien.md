# Strategien bekannter Krypto-Trader im Backtest

Keine Anlageberatung. Backtests auf vergangenen Kursen.

## Teil 1 – Regeln und Vorhersage (geschrieben vor dem Backtest)

Geschrieben am 2026-10-09 um 11:27 UTC und committet, bevor ein Backtest dieser Regeln lief.

### Wen ich mir angesehen habe

| Trader | Was über die Methode bekannt ist | Daraus abgeleitete Regel |
|---|---|---|
| **GCR** (FTX-Bestenliste 2021–22, Pseudonym) | Konträr: gegen den Konsens wetten, Reflexivität nach Soros, „inverse sell the news“; kauft, wenn alle Angst haben | T1a, T1b |
| **CryptoCred, Trader Mayne** | Höhere Zeitebenen; „Deviation“ / Swing Failure: Kurs sticht unter das Range-Tief, schließt wieder darüber → Long, Stop unter dem Docht, Ziel Range-Hoch | T2 |
| **Pentoshi, Crypto Kaleo** | Höhere Zeitebenen, Struktur und Momentum; Ausbruch aus Ranges, Retest des gebrochenen Levels | T3, T4 |
| **Rekt Capital, Benjamin Cowen** | Wochenschlusskurse; „Bull Market Support Band“ (20-Wochen-SMA und 21-Wochen-EMA); zwei Wochenschlüsse darunter = Bärenphase; über 40 % Abstand zum 20-Wochen-SMA = lokale Spitze | T5, T5b |
| **Rekt Capital, Bob Loukas** | Vierjahres-Zyklus rund ums Halving: Aufwärts vor dem Halving, Spitze ~520–550 Tage danach | T6 |
| **DCA-Bots** (3Commas-Stil, beliebt bei Copy-Tradern) | Kauf in Stufen beim Fallen, Verkauf mit kleinem Gewinn über dem Durchschnittspreis | T7 |
| **Hyperliquid-Wale** | Öffentliche Positionen; viele der größten Gewinner hatten vor allem viel Kapital (Rendite oft < 200 %), handeln Short und algorithmisch | nicht testbar: keine Historie der Positionen, short und gehebelt |
| Cobie, Hsaka | Cobie: Erzählungen und Frühphasen-Investments; Hsaka: Orderbuch, Liquidationen, Perp-Prämien | nicht als Regel fassbar bzw. schon getestet (Funding) |

Fast nichts davon ist mit Zahlen belegt. Die Erfolge sind selbst berichtet oder stammen von Bestenlisten, die vor allem
Größe und Hebel belohnen. Getestet wird also, ob die **Regeln** hinter dem Stil auf Spot (nur long, kein Hebel)
Gewinn gebracht hätten.

### Daten und Rahmen

- Binance BTC-USDT und ETH-USDT, Tageskerzen 2017-08-17 bis 2026-10-08 (für T1–T5).
- Coin Metrics Tageskurse BTC ab 2010, ETH ab 2015 (für T5, T6 mit langer Historie).
- Fear & Greed Index (alternative.me, ab 2018-02), Binance-Funding (ab 2019-09).
- 5-Minuten-Kerzen ETH-EUR/BTC-EUR 2020–2026 (für T7).
- Kauf und Verkauf zum Tagesschluss, 0,2 % Kosten je Runde. Stops intraday zum Stop-Kurs mit 0,1 % Slippage.
- Ein Bot je Coin, 100 % des Kapitals je Trade, sonst Cash (ohne Zins).
- Vergleich: Halten und ein vereinfachter Momentum-Trendfolger (M6 aus `docs/momentum-trendfolger.md`, täglich).

### Regeln (fest)

| # | Regel |
|---|---|
| T1a | Fear & Greed ≤ 15 → kaufen, 60 Tage halten, kein Stop |
| T1b | Ø Funding der letzten 7 Tage < 0 → kaufen, 30 Tage halten, kein Stop |
| T2 | Tagestief unter dem tiefsten Tief der 30 Vortage, Schluss wieder darüber → kaufen; Stop 1 % unter dem Tagestief; Ziel höchstes Hoch der 30 Vortage; spätestens nach 30 Tagen verkaufen |
| T3 | Schluss über dem höchsten Hoch der 30 Vortage → kaufen; verkaufen bei Schluss unter dem tiefsten Tief der 15 Vortage |
| T4 | Nach einem T3-Ausbruch über Level L: innerhalb von 10 Tagen Tagestief ≤ L × 1,01 und Schluss > L → kaufen; Stop L × 0,95; sonst Ausstieg wie T3 |
| T5 | Wochenschluss über max(20-W-SMA, 21-W-EMA) → long; raus nach zwei Wochenschlüssen in Folge unter min(beider) |
| T5b | T5, aber Hälfte verkaufen, wenn der Kurs > 1,4 × 20-W-SMA liegt; Hälfte zurück, wenn < 1,2 × |
| T6 | Long von 480 Tagen vor jedem Halving bis 540 Tage danach (Halvings 2012-11-28, 2016-07-09, 2020-05-11, 2024-04-20); sonst Cash |
| T7 | DCA-Bot auf 1-h-Kerzen: Grundorder 10 % des Kapitals, Nachkäufe bei −2 / −4,5 / −7,5 / −11 / −15 / −20 % vom ersten Kauf mit 10 / 12 / 14 / 16 / 18 / 20 % des Kapitals; Verkauf von allem bei +2 % über dem Durchschnittspreis; danach sofort neu |

### Vorhersage

| # | Erwartung |
|---|---|
| T1a | Wenige Trades (unter 15), fast alle im Plus, Ø +15–25 % je Trade; Endvermögen unter Halten, weil oft in Cash; gut als Ergänzung |
| T1b | Ø +5–10 % je 30-Tage-Trade, 10–20 Trades, besser als zufällige 30 Tage |
| T2 | Kleines Plus, Profitfaktor ~1,2; viele Stops |
| T3 | Klar positiv, Endvermögen in der Nähe von Halten bei etwa halbem Rückgang (Trendfolge funktioniert in Krypto) |
| T4 | Weniger Trades als T3, verpasst große Läufe ohne Retest – schlechter als T3 |
| T5 | Positiv, vermeidet die Bärenmärkte, Rückgang ~40 %, Endvermögen leicht unter Halten |
| T5b | Weniger als T5 (verkauft in starken Bullenmärkten zu früh) |
| T6 | Sehr gut – aber wertlos als Beweis, weil die Regel aus genau diesen drei, vier Zyklen abgeleitet ist |
| T7 | Trefferquote über 90 %, aber in Abwärtsphasen festgefahren; großer Rückgang (> 50 %), Endvermögen unter Halten |

Gesamterwartung: **Die Trendfolger (T3, T5) bringen Gewinn, aber keiner schlägt den Momentum-Trendfolger.** Die
konträren Angst-Käufe (T1a, T1b) sind die interessanteste Ergänzung, weil sie selten handeln. Die Range-Deviation
(T2) und der DCA-Bot (T7) bringen wenig bis nichts.

## Teil 2 – Ergebnisse

(folgt nach dem Test)
