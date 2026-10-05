# Strategien und Backtests: drei Säulen und Krypto-Dip-Bot

Stand: 5. Oktober 2026 · DipAgentX 1.21.0 · Backtest-Ergebnisse, keine Anlageberatung.

## 1. Ziel und Ergebnis der Suche

Gesucht war eine Strategie für World-ETF, EM oder Gold, die in über 90 % aller Zeiträume Gewinn bringt, weil sie
schlechte Phasen erkennt und auslässt.

- **Einzelne Anlagen** (nur World, nur EM, nur Gold) schaffen das mit keinem Timing-Signal. Auch mit Trendfilter
  bleiben 12-Monats-Zeiträume mit Verlust bei 20–30 %.
- **Dip-Käufe** (−1 % in 24 h, Trailing, Mindestgewinn) funktionieren bei ETFs und Gold schlecht: zu wenig
  Schwankung, und in Abwärtstrends werden Verluste gekauft. Daher hat der Dip-Käufer jetzt einen Trendfilter und einen
  Trend-Exit (und aus `main` zusätzlich einen ADX-Seitwärtsfilter).
- **Erreichbar sind ~90 % nur durch Streuung plus Timing:** drei wenig korrelierte Säulen (Aktien welt, Gold,
  Euro-Staatsanleihen), jede mit eigenem monatlichen Ausstiegssignal; ausgestiegenes Geld liegt verzinst als Cash.

## 2. Die Strategie

| Säule | Anteil | Instrument (Beispiel) | Signal (Monatsschlusskurse) |
|---|---|---|---|
| Welt | 40 % | MSCI ACWI IMI (z. B. SPYI) oder MSCI World (EUNL) | Kurs über 10-Monats-Durchschnitt, Puffer ±2 %, Ausstieg nur bei steigender US-Arbeitslosigkeit |
| Gold | 30 % | Gold-ETC (z. B. Xetra-Gold, 4GLD) | 12-Monats-Rendite besser als der Zins (2 % p. a.) |
| Anleihen | 30 % | Euro-Staatsanleihen-ETF (z. B. XGLE) | Kurs über 10-Monats-Durchschnitt, Puffer 0 % |

### Das Ausstiegssignal (Welt-Säule)

Geprüft wird einmal im Monat, am ersten Handelstag, mit dem Schlusskurs des Vormonats:

1. **Trend:** Liegt der Schlusskurs mehr als 2 % unter dem Durchschnitt der letzten 10 Monatsschlusskurse, ist der
   Trend „aus“; mehr als 2 % darüber „an“; dazwischen bleibt der Vormonatszustand (verhindert Hin-und-Her).
2. **Konjunktur:** Ein fallender Trend allein verkauft nicht. Verkauft wird erst, wenn zusätzlich die
   US-Arbeitslosenquote (BLS, Serie LNS14000000) über ihrem 12-Monats-Durchschnitt liegt – ein Rezessionszeichen.
   So werden Rücksetzer ohne Abschwung (z. B. 1987, 1998, 2011, 2018) ausgesessen und echte Bärenmärkte
   (2001–03, 2008) gemieden.
3. Wieder eingestiegen wird, sobald der Trend wieder „an“ ist oder die Arbeitslosigkeit nicht mehr steigt.

Gold steigt aus, wenn seine 12-Monats-Rendite den Zins nicht schlägt; Anleihen, wenn sie unter ihrem 10-Monats-Schnitt
schließen.

### Umsetzung in DipAgentX

Je Säule ein Bot mit der Strategie **„Monatlicher Trendfolger“** (`trend`) auf Trade Republic, „Erlös wieder anlegen“
an. Drei getrennte Bots verhalten sich im Test praktisch wie ein rebalanciertes Portfolio. Einmal im Jahr die Beträge
wieder auf 40/30/30 setzen.

## 3. Backtest-Ergebnisse (EUR, 1973–2026)

Datenbasis: MSCI World Preisindex plus Dividendenschätzung, Goldpreis monatlich, Anleihen-/Zinsreihen, DM/EUR-Kurse,
Euribor 3M (EZB) als Cash-Zins; geprüft gegen echte EUR-ETFs (EUNL, 4GLD, XGLE, XEON).

| | Strategie 40/30/30 | World halten |
|---|---|---|
| Rendite p. a. | ~9,3–9,5 % | ~8,4 % |
| 12-Monats-Zeiträume im Plus | ~89–93 % | 74 % |
| 5-Jahres-Zeiträume im Minus | keiner | 17 % |
| größter Rückgang | −11,8 % | −54 % |

### Vergleich mit dem MSCI ACWI IMI (ab 1989)

- Strategie 8,4 % p. a. gegenüber ACWI IMI 8,1 % p. a.
- Die Strategie schlägt den ACWI IMI in 37 % der 5-Jahres-, 45 % der 10-Jahres- und 68 % der 15-Jahres-Zeiträume –
  der Vorteil kommt aus den Crashs, in Bullenmärkten liegt sie zurück.
- 100 % ACWI IMI mit Ausstiegssignal: 10,0 % p. a., aber nur 77 % der 12-Monats-Zeiträume im Plus.
- Ein Dollar-Filter hilft nur in USD-Rechnung, nicht für Euro-Anleger.

### Bandbreite nach Anlagedauer (alle 645 Startmonate)

Faktor auf den Einsatz – typisch (Median) / schlecht (5 %-Quantil) / schlechtester Startmonat:

| Dauer | Strategie | World halten | im Plus (Strategie) |
|---|---|---|---|
| 1 Jahr | 1,089 / 0,991 / 0,937 | 1,107 / 0,758 / 0,607 | 93 % |
| 3 Jahre | 1,292 / 1,079 / 0,985 | 1,380 / 0,730 / 0,513 | 100 % (bis auf −1,5 %) |
| 5 Jahre | 1,527 / 1,245 / 1,065 | 1,626 / 0,842 / 0,637 | 100 % |
| 10 Jahre | 2,293 / 1,834 / 1,710 | 2,661 / 0,895 / 0,675 | 100 % |

Die Strategie ist in 44 % der 10-Jahres-Zeiträume besser als World halten.

## 4. Beispiele für den Einstieg jetzt

Signalstand Oktober 2026: **Welt investiert, Gold investiert, Anleihen in Cash** (nächste Prüfung 2. November).

| Einsatz | Welt | Gold | Anleihen (jetzt Cash) |
|---|---|---|---|
| 20.000 € | 8.000 € | 6.000 € | 6.000 € |
| 40.000 € | 16.000 € | 12.000 € | 12.000 € |
| 50.000 € | 20.000 € | 15.000 € | 15.000 € |
| 100.000 € | 40.000 € | 30.000 € | 30.000 € |

Erwarteter Endwert (typisch / schlecht / schlechtester Startmonat), vor Steuern:

| Einsatz | 1 Jahr | 3 Jahre | 5 Jahre | 10 Jahre | größter Rückgang |
|---|---|---|---|---|---|
| 20.000 € | 21.800 / 19.800 / 18.700 | 25.800 / 21.600 / 19.700 | 30.500 / 24.900 / 21.300 | 45.900 / 36.700 / 34.200 | ~−2.400 € |
| 40.000 € | 43.600 / 39.600 / 37.500 | 51.700 / 43.200 / 39.400 | 61.100 / 49.800 / 42.600 | 91.700 / 73.400 / 68.400 | ~−4.700 € |
| 50.000 € | 54.500 / 49.600 / 46.900 | 64.600 / 54.000 / 49.300 | 76.400 / 62.300 / 53.300 | 114.700 / 91.700 / 85.500 | ~−5.900 € |
| 100.000 € | 108.900 / 99.100 / 93.700 | 129.200 / 107.900 / 98.500 | 152.700 / 124.500 / 106.500 | 229.300 / 183.400 / 171.000 | ~−11.800 € |

Zum Vergleich 100.000 € World halten nach 10 Jahren: typisch 266.100 €, schlechtester Start 67.500 €.

## 5. Hinweise

- **Gebühren:** ca. 1 € pro Order bei Trade Republic; wenige Umschichtungen pro Jahr, kaum relevant.
- **Steuern:** Jeder Verkauf versteuert Gewinne sofort (~26,4 % über dem Freibetrag) – das kostet gegenüber Halten
  Rendite. Beim Gold-ETC beginnt nach jedem Verkauf die Ein-Jahres-Frist zur Steuerfreiheit neu.
- **Cash:** TR verzinst Guthaben (Stand meines Wissens) nur bis 50.000 €; Einlagensicherung bis 100.000 €.
  ETFs sind Sondervermögen.
- **Schwächen:** In Bullenmärkten liegt die Strategie hinter World halten. Anleihen hatten 1973–2026 ein
  außergewöhnliches Zinsumfeld (fallende Zinsen ab 1981). Die Arbeitslosen-Bedingung stützt sich auf US-Daten.
- **Trade Republic:** keine offizielle API, Nutzung auf eigenes Risiko.

## 6. Technische Erkenntnisse

- TR-Marktdaten (`aggregateHistoryLight`) liefern mit Range `max` und Tagesauflösung ~5 Jahre Tageskerzen;
  Stundenkerzen nur ~3 Monate. Bisher fehlten Daten älter als 1 Jahr still – behoben in 1.21.0.
- BLS-API v2 funktioniert ohne Key (Limit 25 Abrufe/Tag); die Reihe hat eine Lücke im Oktober 2025.
- Paper-Lauf mit echten TR-Daten: Welt und Gold investiert, Anleihen in Cash – wie im Backtest.
- Update für Home Assistant: PR #3 mergen, dann Tag `v1.21.0` auf `main` pushen (baut das Image
  `ghcr.io/achirus-code/dipagentx:1.21.0`).

## 7. Ergänzung: Kurzfristiger Krypto-Bot (ETH/BTC auf Revolut X)

Getrennt von den drei Säulen wurde geprüft, ob sich ein Dip-Bot mit kurzem Zeithorizont (Stunden bis Tage) für
ETH-EUR und BTC-EUR auf Revolut X lohnt (Gebühren 0 % Kauf / 0,09 % Verkauf). Er gehört nicht zur 40/30/30-Aufteilung,
sondern wäre – wenn überhaupt – ein kleiner, spekulativer Zusatz.

**Datenbasis und Vorgehen:** Minutenkurse April 2025 – Oktober 2026 (18 Monate, Binance-EUR-Preise als Ersatz für
Revolut X, 0,03 % Spread), rund 2,5 Mio. getestete Einstellungen (Dip-Käufer, Rebound/Trailing, RSI, Bollinger,
Raster, zehn Marktphasen-Filter, Zeit-Stops). Optimiert nur auf April–Dezember 2025, blind geprüft auf Januar–Oktober
2026, gewählt aus der Mitte stabiler Bereiche. Die finalen Einstellungen liefen anschließend Minute für Minute durch
die echte Bot-Engine – mit praktisch gleichem Ergebnis.

### Erkenntnisse

- **Der wichtigste Baustein ist ein Seitwärtsfilter:** nur kaufen, solange der ADX (14) der 4-Stunden-Kerzen unter
  23 liegt. ETH mit sonst gleichen Einstellungen: ohne Filter +32 % bei 59 % Rückgang, mit Filter +96 % bei 20 %.
  Stabil zwischen 22 und 25, ab 27 deutlich schlechter. Umgesetzt als Option *„Nur kaufen, solange ADX (4h) unter“*
  im Dip-Käufer (PR #2).
- **Stop-Loss statt „nie mit Verlust verkaufen“:** ohne Stop-Loss nur +40 % bei 64 % Rückgang – Positionen hängen im
  Crash monatelang fest. Dasselbe Muster wie bei den ETFs: Verluste begrenzen schlägt Verluste aussitzen.
- **Gewinne laufen lassen:** Mini-Ziele (0,5 %) verlieren nach Gebühren; besser Gewinnziel 2,5–3 %, dann Trailing.
- **Gestaffelte Mehrfach-Käufe bringen nichts** (der Stop greift vorher), kurze Pausen nach einem Trade schaden
  (kauft ins fallende Messer); 12 Stunden Pause sind am besten.
- **ETH eignet sich deutlich besser als BTC** – BTC schwankt weniger, nach Gebühren bleibt wenig übrig.

### Einstellungen (Dip-Käufer, „Verkaufen wenn: Gewinnziel erreicht“, max. 1 offener Trade)

| Einstellung | ETH-EUR | BTC-EUR |
|---|---|---|
| Zeitfenster / Kaufen bei Veränderung ≤ | 24 h / −1 % | 24 h / −2 % |
| Nur kaufen, solange ADX (4h) unter | 23 | 23 |
| Gewinnziel / Trailing / Mindestgewinn | 2,5 % / 2 % / 0,5 % | 3 % / 2,5 % / 0,5 % |
| Stop-Loss | 2 % | 2,5 % |
| Pause nach Kauf oder Verkauf | 720 min | 720 min |

### Ergebnisse (in % vom Betrag pro Kauf)

| | ETH | BTC |
|---|---|---|
| 18 Monate, echte Engine | +103 % (140 Trades, ~8/Monat) | +67 % (63 Trades, ~3,5/Monat) |
| 2025 (optimiert) / 2026 (blind) | +39 % / +56 % | +20 % / +37 % |
| größter Rückgang | 20 % | 17 % |
| Monate im Plus / schlechtester Monat | 74 % / −6 % | 74 % / −10 % |
| Kurs selbst im Zeitraum | +44 %, zwischendurch −69 % | +1 %, zwischendurch −53 % |

ETH nach Marktphase: Seitwärtsmonate ~+3 %, Bärenmonate ~+1 %, Bullenmonate ~+13 % pro Monat. Mit 0,09 % Kaufgebühr
und 0,1 % Spread bleiben bei ETH noch +85 %.

### Einordnung

- Nur 18 Monate Daten und bei BTC wenige Trades – die Unsicherheit ist viel größer als beim 53-Jahre-Backtest der
  drei Säulen. Erst einige Wochen im Paper-Modus laufen lassen.
- Etwa die Hälfte der Trades endet am Stop-Loss; der Gewinn kommt aus Erholungen von mehr als 2,5 %.
- Krypto-Gewinne bei Haltedauer unter einem Jahr sind einkommensteuerpflichtig (Freigrenze 1.000 € pro Jahr).
