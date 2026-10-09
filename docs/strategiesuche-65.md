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
