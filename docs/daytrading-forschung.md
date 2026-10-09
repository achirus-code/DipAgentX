# Daytrading für ETH-EUR und BTC-EUR: Recherche, Vorhersagen, Backtests

Keine Anlageberatung. Alle Ergebnisse sind Backtests auf vergangenen Kursen.

## Teil 1 – Vorhersage (geschrieben vor dem Backtest)

Geschrieben am 2026-10-09 um 11:16 UTC und committet, **bevor** ein Backtest dieser Regeln lief. Regeln, Parameter
und Erfolgskriterien unten werden nachträglich nicht verändert. Varianten, die ich erst nach Sichtung der Ergebnisse
teste, stehen in Teil 2 ausdrücklich als „nachträglich“.

### Ausgangslage

Der Backtest vom selben Tag (`docs/ki-swingtrader.md`, PR #35) hat gezeigt: Die Intraday-Setups des Bots
(Pullback, Ausbruch, Kapitulation, Range) mit engen Stops verlieren in jeder Variante. Gewinne gab es nur, wenn
dieselben Einstiege als Swing-Trades über etwa einen Tag gehalten wurden. Die Frage jetzt: Gibt es andere Arten von
Daytrading, die einen belegten Vorteil haben – auch wenn der Bot dafür lange auf die nächste Gelegenheit wartet?

### Was ich gelesen habe

| Quelle | Kernaussage | Belastbarkeit |
|---|---|---|
| Shen, Urquhart, Wang (2022), *Bitcoin intraday time series momentum*, Financial Review | Die erste halbe Stunde des Handelstags sagt die letzte halbe Stunde voraus; am stärksten in Phasen hoher Volatilität und in Abwärtsmärkten | Fachzeitschrift, aber Effekt klein |
| Baur, Cahill, Godfrey, Liu (2017), Tageszeit-Effekte in Bitcoin | Zeitlich wechselnde Effekte, keine dauerhaften Muster; Markt effizient | Gegenposition |
| Quantpedia, *The Seasonality of Bitcoin* (2023) | Kaufen 21:00 UTC, verkaufen 23:00 UTC: 40 % p. a., Rückgang −23 % (2015–2023, Gemini), **ohne Kosten**; schwach 2022–23 | Blog eines Research-Anbieters |
| Quantpedia, *Trend-following and Mean-reversion in Bitcoin* | Am 10–20-Tage-Hoch läuft BTC weiter, am Tief prallt es ab | Blog, ohne Kosten |
| Zarattini, Aziz (2023), *Can Day Trading Really Be Profitable?* | Opening-Range-Breakout auf QQQ: 24 % Trefferquote, +0,13 R je Trade; eine unabhängige Nachrechnung findet nach Kosten null | Kommerzielles Interesse der Autoren |
| Zarattini, Aziz, Barbon (2024), *Beat the Market* (SPY) | „Noise Area“: Band um die Tageseröffnung aus der durchschnittlichen Bewegung bis zur gleichen Uhrzeit der letzten 14 Tage; Ausbruch = Trendtag; 19,6 % p. a. netto | Working Paper, Code veröffentlicht |
| Concretum Group, *Seasonality in Bitcoin Intraday Trend Trading* | Intraday-Trendfolge auf BTC Sharpe ~1,6 brutto (long und short); am besten Sonntag 19 Uhr New York bis Montag (Asien-Eröffnung), am schlechtesten Sonntagvormittag US | Blog, Regeln nicht offengelegt |
| Caporale, Plastun (2019), Überreaktionstage | An Tagen mit abnormaler Rendite läuft der Kurs bis Tagesende in dieselbe Richtung (Momentum), Umkehr nur selten | Working Paper |
| Miralles-Quirós (2022); Sheffield Hallam | Überreaktion nach negativen Stündlich-Schocks, negative Renditen kehren stärker um als positive | Fachzeitschrift |
| Bespoke, Falken (2025), KuCoin-Auswertung | Seit den Spot-ETFs (Jan. 2024) entsteht fast die ganze BTC-Rendite außerhalb der NYSE-Handelszeit; während der US-Sitzung im Schnitt negativ | Marktkommentar, Richtung wechselt |
| YouTube-Strategien (Text-Zusammenfassungen, TradingView-Umsetzungen, eine Nachprüfung auf dev.to) | Beliebt: VWAP-Rücksetzer, EMA-Kreuzungen, „Liquidity Sweep“ der Asien-Range in der London-Sitzung (ICT). Veröffentlichte Ergebnisse fehlen fast immer; eine nachgebaute „+3.888 %“-Strategie landete bei Münzwurf | Schwach |

Videos selbst kann ich nicht ansehen. Ich habe ihre Inhalte über Transkript-Zusammenfassungen, die Beschreibungen
und die TradingView-Skripte erfasst, die die Regeln der Videos umsetzen.

### Rahmen für alle Tests

- Daten: Binance ETH-EUR und BTC-EUR, 5-Minuten-Kerzen, 2020-01-03 bis 2026-09-30.
- **Entwicklungszeitraum 2020–2023, Prüfzeitraum 2024-01 bis 2026-09.** Eine Regel gilt nur als bestanden, wenn sie
  im Prüfzeitraum hält.
- Nur long (Spot), eine Position zur Zeit, kein Hebel – wie der Bot auf Revolut X.
- Kosten: Einstiege und geplante Ausstiege als Limit-Order zum Schlusskurs der Signalkerze, gefüllt wenn der Kurs ihn
  in den nächsten 10 Minuten berührt (0 % Maker-Gebühr). Stop-Ausstiege mit 0,09 % Gebühr und 0,05 % Slippage.
  Zusätzlich ein **pessimistischer Fall: jeder Trade 0,2 % Kosten** (Taker beide Seiten plus Spread).
- Ergebnisse je Trade in %, Profitfaktor, Summe pro Jahr, größter Rückgang, Anteil Jahre im Plus.

### Erfolgskriterium (für alle Hypothesen gleich)

Bestanden, wenn **im Prüfzeitraum 2024–2026 auf beiden Coins**: Ø Ergebnis je Trade > 0 nach Basiskosten,
Profitfaktor ≥ 1,10, mindestens 60 Trades, und im pessimistischen Fall nicht deutlich negativ (Ø ≥ −0,02 %).

### Die Hypothesen, ihre Regeln und meine Vorhersage

| # | Hypothese (Quelle) | Regel, fest vorab | Meine Vorhersage |
|---|---|---|---|
| H1 | Abendstunden 21–23 UTC (Quantpedia) | Jeden Tag Limit-Kauf 21:00 UTC, Verkauf 23:00 UTC; kein Stop | Brutto leicht positiv (Ø +0,03 bis +0,06 % je Trade), 2024–26 schwächer; **besteht nicht** im pessimistischen Fall, weil 0,2 % Kosten den Effekt mehrfach auffressen. Wahrscheinlichkeit Bestehen: 20 % |
| H2 | Außerhalb der US-Sitzung (ETF-Ära, Bespoke/Falken) | Kauf 20:00 UTC, Verkauf 13:30 UTC am nächsten Werktag (Wochenende durchhalten); kein Stop | 2024–26 klar besser als die US-Sitzung, aber als tägliche Runde nur knapp über null netto; Effekt erst seit 2024, also im Entwicklungszeitraum schwach. Bestehen: 35 % |
| H3 | Intraday-Momentum (Shen et al.) | Ist die Rendite 00:00–20:00 UTC > +1 %, Kauf 20:00, Verkauf 23:55 UTC | Klein positiv, wenige Trades (~100/Jahr), Ø +0,05 bis +0,15 %. Bestehen: 30 % |
| H4 | Noise-Area-Ausbruch (Zarattini/Aziz/Barbon), long only | Tagesstart 00:00 UTC; obere Grenze = Eröffnung × (1 + Ø |Bewegung Eröffnung→gleiche Uhrzeit| der letzten 14 Tage); Prüfung alle 30 min; Kauf, wenn der Schluss über der Grenze liegt; Ausstieg bei Rückfall unter max(Grenze, VWAP) zur halben Stunde oder spätestens 23:55 UTC | Bester Kandidat. Trefferquote 35–45 %, Ø +0,10 bis +0,25 % je Trade, Profitfaktor 1,1–1,3, ~150 Trades/Jahr, in Seitwärtsjahren (2023, 2025) negativ. Bestehen: 45 % |
| H5 | Wochentag-Effekt Asien-Montag (Concretum) | H4, aber nur Trades mit Einstieg So 23:00 – Mo 23:00 UTC | Besser je Trade als H4 (Ø +0,3 %), aber zu wenige Trades (~25/Jahr) – verfehlt die 60 Trades im Prüfzeitraum knapp. Bestehen: 25 % |
| H6 | 10-Tage-Hoch-Ausbruch (Quantpedia MAX) als Daytrade | 5-min-Schluss über dem Hoch der letzten 10 Tage (288×10 Kerzen) → Kauf, Verkauf nach 24 h oder Stop 1-h-Swing-Tief | Positiv (Ø +0,5 bis +1 %), aber nur ~20–30 Trades/Jahr; ist eher Swing als Day. Bestehen: 40 % (Kriterium Tradezahl wird knapp) |
| H7 | Überreaktion nach Absturz (Miralles-Quirós) | 1-h-Rendite ≤ −3 % (ETH) / ≤ −2 % (BTC) → Limit-Kauf, Verkauf nach 12 h, kein Stop | Positiv brutto in BTC, gemischt in ETH, sehr schwankend; nach pessimistischen Kosten knapp null. Bestehen: 25 % |
| H8 | Liquidity Sweep der Asien-Range (YouTube/ICT) | Asien-Range = Hoch/Tief 00:00–07:00 UTC; 07:00–11:00 UTC fällt ein 5-min-Tief unter das Asien-Tief und die Kerze schließt wieder darüber → Kauf; Stop 0,1 % unter dem Docht-Tief, Ziel Asien-Hoch, sonst Verkauf 20:00 UTC | **Kein Vorteil:** Profitfaktor 0,9–1,0, nach Stop-Kosten negativ. Bestehen: 10 % |
| H9 | VWAP-Rücksetzer (YouTube-Klassiker) | Kurs war 1 h lang über dem VWAP, 5-min-Tief berührt den VWAP, Schluss darüber → Kauf; Stop 0,5 % unter VWAP, Ziel 2R | Verliert wie die Intraday-Pullbacks im letzten Backtest (Ø R −0,1 bis −0,3). Bestehen: 5 % |

**Gesamterwartung vor dem Test:** Höchstens eine bis zwei Regeln bestehen, am ehesten H4 (Noise-Area-Ausbruch) oder
H6. Reine Uhrzeit-Effekte (H1–H3) halte ich nach realistischen Kosten für zu klein. Die beliebten YouTube-Setups
(H8, H9) erwarte ich im Minus. Wenn überhaupt etwas funktioniert, dann **Trendfolge innerhalb des Tages, nur long,
nur an wenigen Tagen mit klarer Ausbruchsbewegung** – das passt zum „warten auf die beste Gelegenheit“. Eine eigene
Strategie baue ich erst nach dem Test aus dem, was besteht, und prüfe sie ausdrücklich nur auf dem Prüfzeitraum.

## Teil 2 – Backtest-Ergebnisse

(folgt nach dem Test)
