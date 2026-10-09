# Strategiesuche: Gewinnquote mindestens 65 %

Stand: 9. Oktober 2026 · DipAgentX 1.38.1 · Backtests, keine Anlageberatung.

Gesucht sind Handelsregeln für die Revolut-X-Bots (EUR-Paare, nur Long, Market- oder Maker-Limit-Orders), die
**mindestens 65 % ihrer Trades im Plus** schließen **und** nach Kosten Geld verdienen. Die Quote allein ist leicht zu
erzeugen (kleines Ziel, weiter Stop: viele kleine Gewinne, seltene große Verluste), deshalb zählen vier Kriterien:

1. Gewinnquote ≥ 65 % im Entwurfs- **und** im Prüfzeitraum,
2. Gewinn je Trade nach Kosten > 0 im Prüfzeitraum (Taker: 0,09 % Gebühr + 0,05 % halber Spread je Seite; Maker-Limit:
   nur der halbe Spread, Gebühr 0),
3. auch ohne die fünf besten Trades noch positiv,
4. mindestens 10 Trades im Jahr.

Entwurf: Januar 2021 bis Dezember 2023 (Tages-Regeln ab 2020). Prüfung: Januar 2024 bis September 2026 – dort wird
nichts mehr verändert. Daten: Binance-Minutenkerzen ETH-EUR und BTC-EUR (zu 1 h, 4 h, Tag verdichtet), acht weitere
EUR-Paare 2024–2026 als Gegenprobe, Binance-Funding-Sätze seit 2020.

## Teil 1 – Hypothesen und Vorhersagen (vor dem Test geschrieben)

| # | Regel | Vorhersage Quote | Vorhersage Gewinn |
|---|---|---|---|
| S1 | **Rücksetzer im Aufwärtstrend** (Tag): Schluss über SMA200; Kauf, wenn der Schluss erstmals ≥ 5 % unter dem 10-Tage-Hoch liegt; Ziel +3 % (Limit) oder nach 5 Tagen zum Markt | 60–65 % | +0,5 % je Trade, 2022 negativ, ~15/Jahr |
| S2 | **RSI(2)-Rückkehr** (4 h): Schluss über SMA200 (4 h); Kauf bei RSI(2) < 10; Verkauf bei RSI(2) > 65 oder nach 18 Kerzen (3 Tage) | 65–70 % | +0,3 % vor Kosten, nach Taker-Kosten ≈ 0 |
| S3 | **Flash-Move-Käufer** (aus `docs/lead-lag-backtest.md` Abschnitt 7): BTC ±1,5 % in 1 min, BTC ≥ 8 % unter 7-Tage-Hoch, 60 min halten – ohne neue Parameter | abwärts 70 %, aufwärts 55 % | +1,5 % je Trade, 9–12/Jahr (zu wenig für Kriterium 4) |
| S4 | **Nacht-Session ETH** (aus `docs/daytrading-forschung.md`): Kauf 20:00 UTC, Verkauf 13:30 UTC am nächsten Werktag | 53–57 % | positiv, scheitert an der Quote |
| S5 | **Funding-Kontra**: 3-Tage-Mittel der Funding-Rate (Binance Perp) < 0 → Kauf; Verkauf, wenn das Mittel > +0,01 %/8 h oder nach 10 Tagen | 55–60 % | positiv, 3–6 Trades/Jahr, scheitert an Quote und Anzahl |
| S6 | **Bollinger-Rückkehr in Seitwärtsphase** (1 h): Tages-ADX(14) < 20; Kauf, wenn der 1-h-Schluss unter dem unteren Band (20, 2σ) liegt; Verkauf am Mittelband (Limit) oder nach 48 h | 65–70 % | +0,2 % je Trade mit Maker-Einstieg, ~40/Jahr; nach Taker-Kosten ≈ 0 |
| S7 | **Maker-Leiter**: stündlich Kauf-Limit 2 % unter dem Kurs; nach Fill Verkaufs-Limit +2 % über dem Einstand, spätestens nach 7 Tagen zum Markt; (a) ohne Filter, (b) nur bei Tagesschluss über SMA100 | 75–85 % | (a) 2022 stark negativ; (b) positiv, aber größter Rückgang der Kandidaten |
| S8 | **Wochenende**: Kauf Freitag 21:00 UTC, Verkauf Montag 00:00 UTC | ~50 % | ≈ 0 |
| S9 | **Monatswechsel**: Kauf am letzten Kalendertag 00:00 UTC, Verkauf am 3. des Monats 00:00 UTC | ~55 % | ≈ 0 |
| S10 | **Großer Tagesverlust im Aufwärtstrend** (Tag): Schluss ≤ −6 % und über SMA200; Kauf zur nächsten Eröffnung, Verkauf nach 2 Tagen oder bei +4 % | ~60 % | +1 % je Trade, ~5/Jahr |

Gesamterwartung: Die Quote von 65 % erreichen voraussichtlich S2, S6, S7 und S3 (abwärts). Nach Kosten Geld
verdienen davon nur S3 und S7(b); S7 bezahlt die hohe Quote mit den größten Rückgängen (gekaufte Verluste in
Abwärtswellen). Keine der Regeln wird den Momentum-Trendfolger (M6F+, `docs/momentum-trendfolger.md`) über die ganze
Zeit schlagen; sie können aber dessen Kasse in den ausgestiegenen Phasen beschäftigen.

Nicht getestet, mit Begründung: Grid-Bots (jeder geschlossene Grid ist per Bauart ein Gewinn, die Quote sagt nichts –
das Risiko steckt im offenen Bestand), Short-Strategien (auf Revolut X nicht möglich), Cash-and-Carry/Funding-Arbitrage
(kein Terminmarkt), Arbitrage Revolut X gegen Binance (keine Kurshistorie von Revolut X).

## Teil 2 – Ergebnisse (nach dem Test geschrieben)

Alle Zahlen: ETH-EUR, 5.000 € je Trade, eine Position auf einmal, Kosten wie oben. „ohne Top 5“ = Durchschnitt ohne
die fünf besten Trades. Entwurf 2021–2023, Prüfung 2024 – September 2026.

| # | Regel | Trades/Jahr | Quote Entwurf / Prüfung | Ø netto Entwurf / Prüfung | ohne Top 5 (Prüfung) | €/Jahr (Prüfung) | Urteil |
|---|---|---|---|---|---|---|---|
| S1 | Rücksetzer im Aufwärtstrend | 23 / 14 | 84 % / 68 % | +1,2 % / +0,1 % | −0,3 % | +66 | Quote ja, Gewinn nein – im Prüfzeitraum in 26 von 27 Nachbar-Einstellungen negativ |
| S2 | RSI(2)-Rückkehr | 46 / 39 | 58 % / 57 % | −0,2 % / −0,4 % | −0,7 % | −716 | nein |
| S3 | Flash-Move-Käufer, abwärts | 15 / 4 | 71 % / 89 % | +1,2 % / +3,6 % | +0,6 % | +770 | beste Qualität, zu selten (Kriterium 4) |
| S3 | Flash-Move-Käufer, beide Richtungen | 31 / 5 | 57 % / 85 % | +1,1 % / +3,2 % | +0,9 % | +861 | zu selten |
| S4 | Nacht-Session | 261 / 261 | 48 % / 48 % | −0,1 % / −0,1 % | −0,2 % | −1.005 | nein (nach Kosten) |
| S5 | Funding-Kontra | 13 / 11 | 47 % / 65 % | −0,8 % / +3,6 % | −0,1 % | +1.961 | Entwurf negativ, BTC umgekehrt (67 % → 53 %): Zufall |
| S6 | Bollinger in Seitwärtsphase | 36 / 29 | 51–56 % / 73 % | −0,3 % / 0,0 % | −0,2 % | −22 | Quote nur im Prüfzeitraum, kein Gewinn |
| S7a | Maker-Leiter 2 %/2 %, 7 Tage, ohne Filter | 112 / 74 | 89 % / 80 % | +0,4 % / −0,1 % | −0,2 % | −508 | 2022 frisst alles |
| **S7b** | **Maker-Leiter 2 %/2 %, 7 Tage, über SMA100** | **75 / 41** | **90 % / 83 %** | **+0,50 % / +0,47 %** | **+0,40 %** | **+962** | **besteht alle vier Kriterien** |
| S8 | Wochenende | 52 / 52 | 46 % / 49 % | +0,4 % / −0,1 % | −0,4 % | −140 | nein |
| S9 | Monatswechsel | 12 / 12 | 72 % / 53 % | +3,1 % / −1,3 % | −2,7 % | −786 | Entwurf gut, Prüfung schlecht: Zufall |
| S10 | Großer Tagesverlust im Trend | 14 / 7 | 69 % / 50 % | +1,1 % / +0,2 % | −2,3 % | +79 | nein |

BTC-EUR: S7b scheitert (81 % / 74 %, aber −0,1 % je Trade in beiden Zeiträumen), S3 abwärts 47 % / 100 % (4/Jahr),
alles andere wie bei ETH oder schlechter.

**Vorhersage gegen Ergebnis:** S2 und S6 erreichen die Quote nicht (vorhergesagt 65–70 %) – die Rückkehr zum Mittel
ist bei Krypto zu schwach gegen die Kosten. S7 und S3 (abwärts) wie vorhergesagt. S1 erreicht die Quote (nicht
erwartet), verdient aber nichts. S4, S5, S8, S9, S10 wie vorhergesagt nichts. Die Gesamterwartung („S3 und S7b
verdienen, S7 mit den größten Rückgängen“) stimmt.

### Die Maker-Leiter im Detail

So funktioniert sie: Jede Stunde liegt ein Kauf-Limit 2 % unter dem letzten Stundenschluss (Maker, keine Gebühr).
Wird es getroffen, liegt sofort ein Verkaufs-Limit 2 % über dem Einstand (+1,9 % netto). Gehandelt wird nur, solange
der Tagesschluss über dem gleitenden Durchschnitt liegt.

**Was die hohe Quote kostet.** 86 % der Trades enden am Ziel mit +1,9 %. Die übrigen 14 % enden am Zeit-Exit nach
7 Tagen mit im Schnitt **−8,3 %** (Median −6,5 %, schlechtester −39 %). Ein Verlierer frisst vier Gewinner. Deshalb
hängt alles daran, wie oft der Markt nach dem Kauf weiterfällt – 2022 passierte das in 22 von 22 Fällen:

| Jahr (S7b, SMA100, 7-Tage-Exit) | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| Trades | 70 | 152 | 22 | 49 | 56 | 40 | 16 |
| Quote | 79 % | 94 % | 73 % | 84 % | 84 % | 82 % | 81 % |
| Summe auf den Einsatz | +25 % | +140 % | **−68 %** | +40 % | +40 % | +12 % | +1 % |

**Stop-Loss macht es schlimmer:** mit 3 / 5 / 10 % Stop fällt die Quote auf 61 / 72 / 83 % und der Gewinn je Trade
auf −0,08 / −0,07 / −0,01 % (Entwurf). Die Verluste liegen in den Kursen selbst, nicht in der Haltedauer.

**Nachträglich gefunden (nicht vorab angemeldet):** Statt des Zeit-Exits ein **Trend-Exit** – die Position wird erst
verkauft, wenn der Tagesschluss unter den Durchschnitt fällt (frühestens nach einem Tag). Das verbessert ETH **und**
BTC und 6 von 8 Altcoins, ist also wohl kein Zufall. Und ein längerer Durchschnitt (SMA200) hält die Leiter 2022
fast ganz aus dem Markt:

| Variante (Trend-Exit) | Trades/Jahr | Quote Entwurf / Prüfung | Ø netto Entwurf / Prüfung | €/Jahr Prüfung | größter Rückgang Prüfung | 2022 | schlechtester Trade |
|---|---|---|---|---|---|---|---|
| ETH 2 %/2 %, SMA100 | 61 / 33 | 92 % / 90 % | +0,59 % / +0,88 % | +1.464 | −1.070 € | −57 % | −50 % (Mai 2021) |
| **ETH 2 %/2 %, SMA200** | 52 / 26 | **95 % / 92 %** | **+0,89 % / +0,67 %** | +875 | −1.781 € | **−7 %** (2 Trades) | **−56 % (Mai 2021)** |
| ETH 1,5 %/2 %, SMA200 | 57 / 31 | 95 % / 93 % | +0,91 % / +0,66 % | +1.017 | −1.662 € | −4 % | – |
| BTC 2 %/2 %, SMA100 | 28 / 18 | 87 % / 82 % | +0,70 % / +0,29 % | +272 | −1.403 € | −8 % | – |
| **BTC 3 %/2 %, SMA100** | 25 / 12 | **92 % / 94 %** | **+1,28 % / +1,71 %** | +1.040 | −108 € | −9 % (2 Trades) | −13 % |
| BTC 3 %/3 %, SMA200 | 16 / 12 | 90 % / 91 % | +1,30 % / +2,05 % | +1.246 | −693 € | 0 (kein Trade) | −39 % (2021) |

Jahr für Jahr (ETH 2 %/2 %, SMA200, Trend-Exit; Summe auf den Einsatz): 2020 +53 %, 2021 +123 %, 2022 −7 %,
2023 +21 %, 2024 +33 %, 2025 −4 %, 2026 +19 %. BTC 3 %/2 %, SMA100: 2020 +29 %, 2021 +77 %, 2022 −9 %, 2023 +30 %,
2024 +43 %, 2025 +9 %, 2026 +2 % (1 Trade). Die Position ist im Median 4–8 Stunden offen, in 10 % der Fälle länger als
4–5 Tage; das Geld ist bei ETH 40 %, bei BTC 10 % der Zeit investiert.

Gegenprobe auf den acht Altcoins (Prüfzeitraum, dieselben Regeln ohne Anpassung): ETH-Variante (2/2, SMA200) bei 7 von
8 positiv (SUI +0,80 %, LTC +0,71 %, XRP +0,35 %, SOL +0,34 %, AVAX +0,30 %, DOGE +0,15 %, LINK +0,07 %, ADA −0,81 %),
BTC-Variante (3/2, SMA100) bei 6 von 8 positiv. Die Quote liegt überall bei 83–96 %.

**Die Grenze dieser Strategie steht im schlechtesten Trade:** −56 % im Mai 2021, als ETH innerhalb von zwei Wochen
von 3.400 € auf 1.600 € fiel und der SMA200 erst weit unten griff. Mit SMA100 war es −50 %. Ein einziger solcher Trade
kostet ein halbes Jahr Gewinne. Die Quote von 92–95 % sagt darüber nichts – genau das ist die Falle hoher Quoten.

**„Nie mit Verlust verkaufen“** (die Philosophie des Dip-Käufers in der App) im Test: Quote 100 %, Gewinn +1,9 % je
Trade – und eine offene ETH-Position seit August 2025 mit **−42 %**, bei BTC seit Oktober 2025 mit −34 %. Die Quote
ist perfekt, das Geld ist weg.

### Urteil

1. **Von zehn vorab angemeldeten Regeln besteht genau eine alle vier Kriterien:** die Maker-Leiter mit Trendfilter
   (S7b) auf ETH-EUR. Mit dem nachträglich gefundenen Trend-Exit und SMA200 kommt sie auf 92–95 % Quote, +0,7 bis
   +0,9 % je Trade, rund 30–50 Trades und +900 bis +1.500 € im Jahr auf 5.000 € Einsatz, bei einem Rückgang von
   1.000–1.800 €. Für BTC-EUR passt die tiefere Leiter (3 %/2 %, SMA100): +1,3 bis +1,7 % je Trade, 12–25 Trades,
   −108 € Rückgang im Prüfzeitraum.
2. **Der Flash-Move-Käufer (S3)** hat die beste Qualität je Trade (abwärts: 71 % / 89 %, +1,2 % / +3,6 %), aber nur
   4–15 Trades im Jahr. Er ist die einzige Regel hier, die in **Crash-Phasen** handelt – also genau dann, wenn der
   Momentum-Bot draußen ist. Als Beimischung sinnvoll, als Hauptstrategie zu selten.
3. **Rückkehr zum Mittel ohne Trendfilter** (RSI, Bollinger, Rücksetzer, Funding, Kalender) verdient bei Krypto nach
   Kosten nichts, egal wie die Quote aussieht.
4. **Die Leiter konkurriert mit dem Momentum-Bot um dasselbe Geld:** Sie handelt nur über dem SMA200, also genau in
   den Phasen, in denen der Momentum-Bot investiert ist. 2021 brachte die Leiter +123 % auf den Einsatz, der
   Momentum-Bot +362 %. Die Leiter ist der ruhigere Weg (95 % Quote, Geld 60 % der Zeit frei), nicht der ertragreichere.
5. **Der schlechteste Trade (−56 %) ist der Preis** für die Quote. Wer das nicht tragen will, braucht einen Stop –
   und mit Stop verdient die Leiter nichts mehr.

### Falls gebaut: Strategie „Maker-Leiter“

Stündlich Kauf-Limit `x` % unter dem letzten Stundenschluss (Maker, bei Revolut X ohne Gebühr), bei Fill sofort
Verkaufs-Limit `y` % über dem Einstand; täglich prüfen, ob der Tagesschluss unter dem SMA `n` liegt – dann zum Markt
verkaufen und keine neuen Limits, bis der Kurs wieder darüber schließt. Vorschlag ETH-EUR 2 %/2 %/SMA200,
BTC-EUR 3 %/2 %/SMA100. Kein Stop. Erst Paper: Der Test nimmt an, dass ein Limit gefüllt wird, sobald das Stundentief
es berührt – auf Revolut X kann die Schlange vor der eigenen Order länger sein.
