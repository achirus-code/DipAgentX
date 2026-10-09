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

## Teil 2 – Backtest-Ergebnisse (nach dem Test geschrieben)

Gerechnet am 2026-10-09 nach dem Commit von Teil 1, mit genau den Regeln oben. Ø = Ergebnis je Trade nach
Basiskosten, „pess.“ = nach 0,2 % Kosten je Trade, PF = Profitfaktor.

### Die neun Hypothesen im Prüfzeitraum 2024-01 bis 2026-09

| # | ETH: Trades · Ø · pess. · PF | BTC: Trades · Ø · pess. · PF | Bestanden? | Vorhersage gestimmt? |
|---|---|---|---|---|
| H1 Abendstunden 21–23 UTC | 913 · +0,07 % · −0,13 % · 1,25 | 924 · +0,05 % · −0,15 % · 1,25 | nein (Kosten) | ja |
| H2 Außerhalb US-Sitzung | 670 · +0,25 % · +0,05 % · 1,25 | 665 · +0,17 % · −0,03 % · 1,24 | nur ETH | teilweise – stärker als erwartet, aber auch 2020–23 schon positiv |
| H3 Intraday-Momentum | 306 · +0,06 % · −0,14 % · 1,14 | 252 · −0,06 % · −0,26 % · 0,83 | nein | ja |
| H4 Noise-Area-Ausbruch | 1.627 · +0,02 % · −0,18 % · 1,06 | 1.642 · +0,01 % · −0,19 % · 1,04 | nein | **nein** – mein Favorit fiel durch |
| H5 Asien-Montag | 346 · +0,00 % · −0,20 % · 1,01 | 336 · +0,04 % · −0,16 % · 1,17 | nein | ja |
| H6 10-Tage-Hoch | 133 · +0,13 % · −0,04 % · 1,09 | 134 · +0,23 % · +0,05 % · 1,24 | nur BTC | teilweise |
| H7 Überreaktion nach Absturz | 145 · +0,34 % · +0,14 % · 1,26 | 173 · +0,22 % · +0,02 % · 1,27 | **ja** | **nein** – besser als erwartet |
| H8 Liquidity Sweep (YouTube/ICT) | 249 · −0,14 % · −0,26 % · 0,64 | 268 · −0,08 % · −0,21 % · 0,75 | nein, Verlust in jedem Jahr | ja |
| H9 VWAP-Rücksetzer (YouTube) | 814 · −0,14 % · −0,28 % · 0,72 | 801 · −0,11 % · −0,26 % · 0,74 | nein, Verlust in jedem Jahr | ja |

**Gegenprobe mit Zufall.** Jeder Long-Trade verdient in steigenden Märkten etwas, einfach weil der Kurs steigt. Deshalb
habe ich jede Regel mit zufälligen Einstiegen gleicher Anzahl und Haltedauer verglichen (300 Durchläufe):

- **H1, H6:** im Rahmen des Zufalls oder knapp darüber – kein belastbarer Vorteil.
- **H2 (außerhalb der US-Sitzung):** 2020–23 im Rahmen des Zufalls, **2024–26 bei ETH klar darüber** (+0,25 % gegen
  +0,05 %), bei BTC knapp innerhalb. Passt zur Literatur: Der Effekt entsteht mit den Spot-ETFs 2024.
- **H7 (Überreaktion):** mit festen Schwellen 2020–23 nicht besser als Zufall, 2024–26 besser. Deutlich und in beiden
  Zeiträumen besser wird es, **je größer der Einbruch**: ETH ab −4 % in 1 h, BTC ab −2,5 bis −3 %.

Gesamtbild: **Klassisches Daytrading mit Stops, Zielen und Chart-Mustern hat keinen Vorteil** – weder die
Varianten des Bots (letzter Backtest) noch die akademischen Ausbruchsregeln (H4, H5) noch die YouTube-Setups (H8, H9).
Übrig bleiben zwei Effekte, bei denen nicht das Muster, sondern **der Zeitpunkt** zählt: nachts halten und nach
Panik-Einbrüchen kaufen.

### Eigene Strategie „Gelegenheitskäufer“ (nachträglich entworfen)

Entworfen nur auf 2020–2023, dann einmal auf 2024–2026 geprüft. Zwei Bausteine, eine Position zur Zeit:

1. **Crash-Kauf:** Fällt der Kurs in einer Stunde um mindestens das 3,5-Fache der üblichen Stunden-Schwankung (30 Tage),
   Limit-Kauf zum Schlusskurs; Verkauf nach 24 Stunden. Kein Stop. Die Schwelle passt sich der Volatilität an, damit
   dieselbe Regel für ETH und BTC gilt (bei ETH heute etwa −3 %, bei BTC etwa −2 % in einer Stunde).
2. **Nachtschicht:** Montag bis Freitag 20:00 UTC kaufen, am nächsten Werktag 13:30 UTC verkaufen (Wochenende
   durchhalten), also nur außerhalb der US-Börsenzeit investiert.
3. **Filter für beides:** nur wenn der Schlusskurs des Vortags über dem 50-Tage-Durchschnitt liegt.

Warum diese Werte: Auf 2020–23 lagen alle Schwellen von 2,5 bis 5 und Haltezeiten von 24–48 h im Plus; mit dem
50-Tage-Filter halbierte sich der Rückgang. 3,5 und 24 h liegen in der Mitte des Plateaus. Der Filter wurde aus vier
Kandidaten gewählt (keiner, 20-Tage-Schnitt, 10-Tage-Rendite, 50-Tage-Schnitt).

| | ETH 2020–23 | ETH **2024–26** | BTC 2020–23 | BTC **2024–26** |
|---|---|---|---|---|
| Crash-Kauf: Trades/Jahr · Treffer · Ø · PF | 40 · 64 % · +0,86 % · 1,56 | 36 · 56 % · **+0,51 %** · 1,48 | 36 · 64 % · +0,88 % · 2,01 | 40 · 52 % · **+0,62 %** · 1,87 |
| Crash-Kauf: Summe · größter Rückgang | +178 % · −48 % | +56 % · −28 % | +199 % · −26 % | +87 % · −9 % |
| Nachtschicht: Trades/Jahr · Ø · PF | 142 · +0,43 % · 1,36 | 122 · **+0,44 %** · 1,51 | 130 · +0,41 % · 1,48 | 133 · **+0,23 %** · 1,37 |
| Beides zusammen: Ø · PF · Rückgang | +0,59 % · 1,48 · −40 % | **+0,47 %** · 1,49 · −25 % | +0,49 % · 1,53 · −48 % | **+0,22 %** · 1,28 · −27 % |
| Beides, nach 0,2 % Kosten je Trade | +0,39 % | +0,27 % | +0,29 % | +0,02 % |

Vermögen im Prüfzeitraum Januar 2024 bis September 2026 (Faktor auf den Einsatz):

| | ETH | BTC |
|---|---|---|
| Gelegenheitskäufer (beides, 41–46 % der Zeit investiert) | **×3,27** | ×1,77 |
| Nur Crash-Kauf (etwa 10 % der Zeit investiert) | ×1,56 | ×1,87 |
| Coin halten | ×1,14 | ×1,91 |
| **Ganztägig long, solange über dem 50-Tage-Schnitt** (50–55 % der Zeit) | **×3,59** | **×2,41** |

Je Jahr (Summe der Trade-Ergebnisse, beides zusammen): ETH 2020 +94 %, 2021 +159 %, 2022 −27 %, 2023 +47 %,
2024 +48 %, 2025 +55 %, 2026 +33 %. BTC 2020 +99 %, 2021 +88 %, 2022 −49 %, 2023 +69 %, 2024 +66 %, 2025 −9 %,
2026 +13 %.

**Robustheit des Crash-Kaufs im Prüfzeitraum** (nachträglich angesehen, nicht zur Auswahl benutzt): Alle 54
Nachbarvarianten (Schwelle 3–4, Haltezeit 12/24/48 h, Filter 50 Tage/20 Tage/keiner) sind nach Basiskosten im Plus;
24 h ist auf beiden Coins der beste Bereich, 12 h ist nach pessimistischen Kosten knapp null. Gegen zufällige
24-h-Käufe an denselben Filtertagen ist der Crash-Kauf bei BTC klar besser (+0,62 % gegen +0,20 %), bei ETH besser,
aber noch im Zufallsbereich (+0,51 % gegen +0,28 %, 95-%-Grenze +0,81 %). Bei ETH stammen 87 % des Gewinns aus den
fünf besten Trades, bei BTC 63 %. 2025 war bei beiden Coins fast null.

### Was das heißt

1. **Die Strategie hätte Geld verdient**, auch im Zeitraum, den ich beim Entwurf nicht angesehen habe – ETH ×3,3 statt
   ×1,1 beim Halten, BTC ×1,8 bei einem Drittel weniger Rückgang als beim Halten (−27 % gegen −32 % im Prüfzeitraum,
   über 2020–26 −48 % gegen −77 %).
2. **Aber sie schlägt nicht die einfachste Alternative.** Ganztägig long, solange der Kurs über dem 50-Tage-Schnitt
   liegt, brachte in beiden Coins mehr. Der Großteil des Gewinns kommt also vom Trendfilter, nicht vom Daytrading.
   Und der Momentum-Trendfolger (`docs/momentum-trendfolger.md`) ist noch einmal deutlich besser.
3. **Sinnvoll ist der Crash-Kauf als Ergänzung,** genau im Sinn von „warten auf die beste Gelegenheit“: etwa
   40 Käufe im Jahr, je 24 h, also nur rund 10 % der Zeit investiert; im Prüfzeitraum ETH +56 %, BTC +87 % auf den
   Einsatz, größter Rückgang −28 % bzw. −9 %. Das Geld wartet die übrige Zeit – es kann daneben verzinst liegen.
   Er braucht keine KI und keine API-Kosten: Die Regel ist eine einfache Rechnung.
4. **Die Nachtschicht** ist bei ETH seit 2024 belastbar, bei BTC nicht. Sie ist eher eine Eigenheit der ETF-Ära als
   ein dauerhaftes Gesetz und kann wieder verschwinden.
5. **Für den KI-Bot:** Claude kann das nicht besser lernen, als es die Regeln schon zeigen – die Setups, die ein
   Sprachmodell aus Chartbildern lesen würde (Ausbruch, Rücksetzer, Sweep, VWAP), haben keinen messbaren Vorteil.
   Wenn KI, dann als Filter, der offensichtlich schlechte Crash-Käufe auslässt (z. B. bei echten Pleite-Nachrichten
   wie FTX 2022). Das lässt sich nicht backtesten.

### Vorhersage gegen Ergebnis

Vorhergesagt waren „höchstens eine bis zwei Regeln bestehen, am ehesten H4 oder H6“. Bestanden hat eine Regel ganz
(H7), zwei halb (H2 bei ETH, H6 bei BTC). H4 und H6 lagen falsch, H7 hatte ich mit 25 % unterschätzt. Richtig lag die
Erwartung, dass reine Uhrzeit-Effekte nach Kosten zu klein sind (H1, H3) und dass die YouTube-Setups (H8, H9)
verlieren – sie verlieren in jedem einzelnen Jahr.

### Grenzen

- Füllung zum Schlusskurs der Signalkerze, sobald der Kurs ihn in 10 Minuten berührt; Ausstiege zum Schlusskurs ohne
  Gebühr. In einem echten Crash ist der Spread auf Revolut X breiter – deshalb der pessimistische Fall.
- Binance-Kurse statt Revolut X. Die Kurse laufen gleich, die Liquidität in Crashs nicht.
- Prüfzeitraum 2,75 Jahre, rund 100 Crash-Käufe je Coin. Ein Effekt, der von fünf Trades lebt, kann Glück sein.
- Über 30 Varianten habe ich nach dem Test angesehen; ausgewählt wurde aber nur auf 2020–23.
- Skripte lagen im Scratchpad der Sitzung (`dt.py`, `own.py`, `final.py`), nicht im Repository.
