# Strategien und Backtests: drei Säulen und Krypto-Dip-Bot

Stand: 5. Oktober 2026 (nachgeprüft mit bereinigter Datenbasis, siehe Abschnitt 8) · DipAgentX 1.21.0 ·
Backtest-Ergebnisse, keine Anlageberatung.

## 1. Ziel und Ergebnis der Suche

Gesucht war eine Strategie für World-ETF, EM oder Gold, die in über 90 % aller Zeiträume Gewinn bringt, weil sie
schlechte Phasen erkennt und auslässt.

- **Einzelne Anlagen** (nur World, nur EM, nur Gold) schaffen das mit keinem Timing-Signal. Auch mit dem besten Signal
  bleiben 22 % (World) bzw. 25–32 % (Gold) der 12-Monats-Zeiträume im Minus.
- **Dip-Käufe** (−1 % in 24 h, Trailing, Mindestgewinn) funktionieren bei ETFs und Gold schlecht: zu wenig
  Schwankung, und in Abwärtstrends werden Verluste gekauft. Daher hat der Dip-Käufer jetzt einen Trendfilter und einen
  Trend-Exit (und aus `main` zusätzlich einen ADX-Seitwärtsfilter).
- **Erreichbar sind ~90 % nur durch Streuung plus Timing:** drei voneinander praktisch unabhängige Säulen (Aktien
  weltweit, Gold, Euro-Staatsanleihen), jede mit eigenem monatlichen Ausstiegssignal; ausgestiegenes Geld liegt
  verzinst als Cash.

## 2. Die Strategie

| Säule | Anteil | Instrument (Beispiel) | Signal (Monatsschlusskurse) |
|---|---|---|---|
| Welt | 40 % | MSCI ACWI IMI (z. B. SPYI) oder MSCI World (EUNL) | Kurs über 10-Monats-Durchschnitt, Puffer ±2 %, Ausstieg nur bei steigender US-Arbeitslosigkeit |
| Gold | 30 % | Gold-ETC (z. B. Xetra-Gold, 4GLD) | 12-Monats-Rendite besser als der **aktuelle Euro-Zins** (Parameter „Zins für Cash“, Okt. 2026: Euribor 3M ≈ 2,6 %) |
| Anleihen | 30 % | Euro-Staatsanleihen-ETF (z. B. XGLE) | Kurs über 10-Monats-Durchschnitt, Puffer 0 % |

### Das Ausstiegssignal (Welt-Säule)

Geprüft wird einmal im Monat, am ersten Handelstag, mit dem Schlusskurs des Vormonats:

1. **Trend:** Liegt der Schlusskurs mehr als 2 % unter dem Durchschnitt der letzten 10 Monatsschlusskurse, ist der
   Trend „aus“; mehr als 2 % darüber „an“; dazwischen bleibt der Vormonatszustand (verhindert Hin-und-Her).
2. **Konjunktur:** Ein fallender Trend allein verkauft nicht. Verkauft wird erst, wenn zusätzlich die
   US-Arbeitslosenquote (BLS, Serie LNS14000000) über ihrem 12-Monats-Durchschnitt liegt – ein Rezessionszeichen.
3. Wieder eingestiegen wird, sobald der Trend wieder „an“ ist oder die Arbeitslosigkeit nicht mehr steigt.

Was das Signal historisch getan hat (Euro-Kurse):

- **Ausgesessen** (kein einziger Monat draußen): Crash 1987, 2011, 2015/16. Nur einen Monat draußen: 1998, Anfang 2019,
  Frühjahr 2023. Der reine Trend ohne Arbeitslosen-Bedingung wäre in diesen Phasen 2–12 Monate draußen gewesen.
- **Gemieden:** 1974, 1981/82, 1990/91, Februar 2001 bis Juni 2003, November 2007 bis Juli 2009.
- **Schwäche bei schnellen Crashs:** 2020 kam das Signal erst nach dem Einbruch (raus Ende April, wieder rein Ende
  August) und verpasste einen Teil der Erholung; ähnlich April bis Juli 2025.

Gold steigt aus, wenn seine 12-Monats-Rendite den Zins nicht schlägt; Anleihen, wenn sie unter ihrem 10-Monats-Schnitt
schließen.

### Umsetzung in DipAgentX

Je Säule ein Bot mit der Strategie **„Monatlicher Trendfolger“** (`trend`) auf Trade Republic, „Erlös wieder anlegen“
an. Drei getrennte Bots verhalten sich im Test praktisch wie ein rebalanciertes Portfolio. Einmal im Jahr die Beträge
wieder auf 40/30/30 setzen. Beim Gold-Bot den „Zins für Cash“ an den aktuellen Euro-Zins anpassen, wenn die EZB die
Zinsen deutlich ändert (siehe Abschnitt 8.4).

## 3. Backtest-Ergebnisse (EUR, Oktober 1973 – Oktober 2026)

Datenbasis (bereinigt, Abschnitt 8): MSCI World Preisindex USD plus Dividendenschätzung (3 % bis 1989, danach 2 %),
Gold aus dem Frankfurter Goldfixing (DM, bis 1998) bzw. COMEX (ab 2000), Wechselkurse der Bundesbank/EZB, Anleihen
aus der Bund-Zinsstruktur der Bundesbank (bis 2007) bzw. dem echten XGLE (ab 2008), Cash = Euribor 3M (davor
kurzfristige Bund-Rendite). Alles Monatsschlusskurse, 0,1 % Kosten je Umschichtung, vor Steuern.

| | Strategie (Gold-Hürde = Euro-Zins) | Strategie (Gold-Hürde fix 2 %) | 40/30/30 ohne Timing | World halten |
|---|---|---|---|---|
| Rendite p. a. | 9,5 % | 9,1 % | 7,9 % | 8,9 % |
| 12-Monats-Zeiträume im Plus | 92 % | 90 % | 80 % | 74 % |
| 3-Jahres-Zeiträume im Plus | 98 % | 97 % | 92 % | 82 % |
| 5-Jahres-Zeiträume im Plus | 100 % | 100 % | 99 % | 85 % |
| schlechteste 12 Monate | −9,3 % | −9,3 % | −18,2 % | −37,6 % |
| größter Rückgang | −11,0 % | −11,9 % | −19,4 % | −54,5 % |
| Verlust-Kalenderjahre | 4 (1994 −4 %, 2002 −1 %, 2018 −2 %, 2022 −3 %) | 6 | 9 | 13 |

### Vor und nach 2000

| | 1973–1999 | 2000–2026 |
|---|---|---|
| Strategie (fix 2 %) | 11,3 % p. a. · 92 % · −11,9 % | 7,0 % p. a. · 87 % · −9,3 % |
| Strategie (Euro-Zins) | 11,9 % p. a. · 95 % | 7,1 % p. a. · 90 % |
| 40/30/30 ohne Timing | 8,8 % p. a. · 81 % · −19,4 % | 7,1 % p. a. · 78 % · −19,3 % |
| World halten | 11,6 % p. a. · 73 % · −36,7 % | 6,6 % p. a. · 75 % · −54,5 % |

(Rendite · 12-Monats-Zeiträume im Plus · größter Rückgang)

**Wichtig:** Seit 2000 bringt das Timing gegenüber einem einfach gehaltenen 40/30/30-Portfolio **keine Mehrrendite**
(7,0–7,1 % gegen 7,1 %). Es halbiert aber den größten Rückgang und hebt den Anteil der Gewinn-Jahre von 78 % auf
87–90 %. Der Renditevorsprung gegenüber World halten kommt fast ganz aus 1973–1990 und 2000–2010.

| Jahrzehnt | Strategie (fix 2 %) | World halten |
|---|---|---|
| 1973–1990 | 12,1 % | 10,1 % |
| 1990–2000 | 10,0 % | 13,6 % |
| 2000–2010 | 5,7 % | −3,3 % |
| 2010–2020 | 7,7 % | 12,4 % |
| 2020–2026 | 8,0 % | 13,6 % |

### Vergleich mit dem MSCI ACWI IMI (ab 1989)

- Strategie 7,7 % p. a. gegenüber ACWI IMI 8,2 % p. a. – **seit 1989 liegt die Strategie bei der Rendite hinten**
  (bei −9 % statt −53 % größtem Rückgang).
- Die Strategie schlägt den ACWI IMI in 37 % der 5-Jahres-, 43 % der 10-Jahres- und 53 % der 15-Jahres-Zeiträume.
- 100 % ACWI IMI mit Ausstiegssignal: 10,2 % p. a. bei −31 % größtem Rückgang, 77 % der 12-Monats-Zeiträume im Plus;
  schlägt den ACWI IMI in 61/68/86 % der 5/10/15-Jahres-Zeiträume.
- ACWI IMI statt MSCI World als Aktien-Säule ändert am Ergebnis praktisch nichts (7,7 % gegen 7,7 %).

### Bandbreite nach Anlagedauer (alle Startmonate ab Oktober 1973)

Faktor auf den Einsatz – typisch (Median) / schlecht (5 %-Quantil) / schlechtester Startmonat:

| Dauer | Strategie (Euro-Zins) | World halten | Strategie im Plus | Strategie besser als World |
|---|---|---|---|---|
| 1 Jahr | 1,088 / 0,990 / 0,907 | 1,108 / 0,767 / 0,624 | 92 % | 41 % |
| 3 Jahre | 1,294 / 1,056 / 0,957 | 1,380 / 0,732 / 0,502 | 98 % | 37 % |
| 5 Jahre | 1,540 / 1,216 / 1,041 | 1,628 / 0,845 / 0,634 | 100 % | 44 % |
| 10 Jahre | 2,249 / 1,752 / 1,672 | 2,679 / 0,875 / 0,667 | 100 % | 41 % |

Mit fester Gold-Hürde von 2 % liegen die Werte etwas darunter (10 Jahre: 2,175 / 1,712 / 1,604; besser als World
nur in 31 % der 10-Jahres-Zeiträume).

## 4. Beispiele für den Einstieg jetzt

Signalstand Oktober 2026: **Welt investiert** (Schluss September 7,8 % über dem 10-Monats-Schnitt), **Gold investiert**
(+11,8 % in 12 Monaten gegen 2,2 % Zins), **Anleihen in Cash** (3,1 % unter dem Schnitt). Nächste Prüfung 2. November.

| Einsatz | Welt | Gold | Anleihen (jetzt Cash) |
|---|---|---|---|
| 20.000 € | 8.000 € | 6.000 € | 6.000 € |
| 40.000 € | 16.000 € | 12.000 € | 12.000 € |
| 50.000 € | 20.000 € | 15.000 € | 15.000 € |
| 100.000 € | 40.000 € | 30.000 € | 30.000 € |

Endwert (typisch / schlecht / schlechtester Startmonat) laut Backtest, vor Steuern:

| Einsatz | 1 Jahr | 3 Jahre | 5 Jahre | 10 Jahre | größter Rückgang |
|---|---|---|---|---|---|
| 20.000 € | 21.760 / 19.800 / 18.140 | 25.880 / 21.120 / 19.140 | 30.800 / 24.320 / 20.820 | 44.980 / 35.040 / 33.440 | ~−2.200 € |
| 40.000 € | 43.520 / 39.600 / 36.280 | 51.760 / 42.240 / 38.280 | 61.600 / 48.640 / 41.640 | 89.960 / 70.080 / 66.880 | ~−4.400 € |
| 50.000 € | 54.400 / 49.500 / 45.350 | 64.700 / 52.800 / 47.850 | 77.000 / 60.800 / 52.050 | 112.450 / 87.600 / 83.600 | ~−5.500 € |
| 100.000 € | 108.800 / 99.000 / 90.700 | 129.400 / 105.600 / 95.700 | 154.000 / 121.600 / 104.100 | 224.900 / 175.200 / 167.200 | ~−11.000 € |

Zum Vergleich 100.000 € World halten nach 10 Jahren: typisch 267.900 €, schlechtester Start 66.700 €.

## 5. Hinweise

- **Gebühren:** ca. 1 € pro Order bei Trade Republic; wenige Umschichtungen pro Jahr, kaum relevant.
- **Steuern:** Jeder Verkauf versteuert Gewinne sofort (~26,4 % über dem Freibetrag) – das kostet gegenüber Halten
  Rendite. Beim Gold-ETC beginnt nach jedem Verkauf die Ein-Jahres-Frist zur Steuerfreiheit neu.
- **Cash:** TR verzinst Guthaben (Stand meines Wissens) nur bis 50.000 €; Einlagensicherung bis 100.000 €.
  ETFs sind Sondervermögen.
- **Schwächen:** In Bullenmärkten (1990er, 2010er, seit 2020) liegt die Strategie deutlich hinter World halten.
  Schnelle Crashs wie 2020 erkennt das Signal zu spät. Anleihen hatten 1981–2020 ein außergewöhnliches Zinsumfeld
  (fallende Zinsen). Die Arbeitslosen-Bedingung stützt sich auf US-Daten im heutigen (revidierten) Stand.
- **Trade Republic:** keine offizielle API, Nutzung auf eigenes Risiko.

## 6. Technische Erkenntnisse

- TR-Marktdaten (`aggregateHistoryLight`) liefern mit Range `max` und Tagesauflösung ~5 Jahre Tageskerzen;
  Stundenkerzen nur ~3 Monate. Bisher fehlten Daten älter als 1 Jahr still – behoben in 1.21.0.
- BLS-API v2 funktioniert ohne Key (Limit 25 Abrufe/Tag); die Reihe hat eine Lücke im Oktober 2025.
- Seit 5. Oktober 2026 laufen die drei Säulen-Bots im Papiermodus mit 100.000 € (Agent 1.21.0): Welt (SPYI) und Gold
  (4GLD) investiert, Anleihen (XGLE) in Cash – wie im Backtest.
- Bundesbank-Zeitreihen (Zinsstruktur, DM-/EUR-Kurse, Frankfurter Goldfixing) sind über
  `api.statistiken.bundesbank.de` frei abrufbar; Monatswerte der Zinsstruktur sind Monatsendstände.

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

## 8. Nachprüfung (Oktober 2026): Korrekturen, Robustheit, eigene Indikatoren

### 8.1 Was in der ersten Rechnung falsch war

| Fehler | Wirkung | Korrektur |
|---|---|---|
| Gold-Monatsreihe bestand aus **Monatsdurchschnitten** statt Monatsschlusskursen | begünstigt Trendsignale (Kauf zum Durchschnitt, Signal vom Monatsende) | Frankfurter Goldfixing (täglich, DM) bzw. COMEX, jeweils Monatsschluss; nur 1999-01 bis 2000-07 genähert |
| Anleihen = synthetische **US-Staatsanleihe**, in Euro abgesichert | passt nicht zu XGLE | Bund-Nullkuponkurve der Bundesbank (Laufzeiten 1–20 J.), ab 2008 echter XGLE |
| Gold-Hürde im Test = **US-T-Bill-Zins**, im Bot fix 2 % | Test und Bot wichen voneinander ab | beide Varianten getrennt gerechnet |
| DM/EUR-Kurse als Monatsdurchschnitte | leichte Verzerrung | Bundesbank-/EZB-Kurse zum Monatsende |

Was sich dadurch an den Aussagen geändert hat:

| Aussage (vorher) | nachgerechnet |
|---|---|
| Rendite ~9,3–9,5 % gegen World 8,4 % | 9,1 % (fix 2 %) bzw. 9,5 % (Euro-Zins) gegen 8,9 % (Start Okt. 1973) |
| 12-Monats-Zeiträume im Plus ~89–93 % | 90 % bzw. 92 %; seit 2000 nur 87 % bzw. 90 % |
| nach 3 Jahren nur der schlechteste Start knapp im Minus | 2–3 % der 3-Jahres-Zeiträume im Minus, schlechtester −4 % bis −6 % |
| schlechteste 12 Monate −6 % | −9,3 % |
| größter Rückgang −11,8 % | −11,0 % bzw. −11,9 % (bestätigt) |
| kein 5-Jahres-Zeitraum im Minus | bestätigt |
| 10 Jahre typisch 2,29-fach | 2,25-fach (Euro-Zins) bzw. 2,18-fach (fix 2 %) |
| seit 1989: Strategie 8,4 % gegen ACWI IMI 8,1 % | **falsch:** 7,7 % gegen 8,2 % |
| schlägt ACWI IMI in 37/45/68 % der 5/10/15-J.-Zeiträume | 37/43/53 % |
| 100 % ACWI IMI mit Ausstiegssignal 10,0 %, 77 % | 10,2 %, 77 % (bestätigt) |
| 5-Jahres-Zeiträume World halten im Minus 17 % | 15 % |

### 8.2 Robustheit

- **Ausführung erst am ersten Handelstag** des Folgemonats (wie der Bot, mit Tageskursen gerechnet): 9,10 % statt
  9,13 % p. a. – vernachlässigbar.
- **Revisionen der Arbeitslosenquote** (der Test nutzt den heutigen, revidierten Datenstand): mit zufälligen
  Abweichungen von ±0,1 bzw. ±0,2 Prozentpunkten je Monat liegen 90 % der Läufe bei 9,0–9,4 % bzw. 8,8–9,4 % p. a.
  und 88–91 % Gewinn-Zeiträumen.
- **Parameter-Gitter** (448 Kombinationen: Durchschnitt 6–14 Monate, Puffer 0–3 %, Gold-Rückblick 6–15 Monate,
  Anleihen 6–12 Monate): 8,2–9,4 % p. a., 88–92 % der 12-Monats-Zeiträume im Plus, größter Rückgang −12 bis −15 %.
  Die gewählte Einstellung liegt im unteren Mittelfeld, ist also nicht herausgepickt.
- **Optimieren hilft nicht:** Die fünf besten Einstellungen für 1973–1999 (97 % im Plus) kommen 2000–2026 nur auf
  84–85 % – schlechter als die Standardeinstellung (87 %).

### 8.3 Zusammenhänge zwischen den Säulen

- Die Monatsrenditen von Welt, Gold und Bund-Anleihen (in Euro) sind praktisch **unkorreliert** (+0,09, +0,07,
  −0,01). Verluste treten so oft gleichzeitig auf, wie es bei Unabhängigkeit zu erwarten ist – nicht seltener.
- In 35 % der 12-Monats-Zeiträume waren alle drei Säulen im Plus, in 50 % eine im Minus, in 13 % zwei, in 2 % alle drei
  (12-Monats-Zeiträume, die 1988, 1990, 1994 und 1995 endeten).
- **Wenn das Aktien-Signal draußen ist**, verdienen Gold (+4,6 % bzw. +5,2 % p. a. über Cash) und Anleihen
  (+2,5 % p. a. über Cash) in beiden Hälften des Zeitraums überdurchschnittlich – Rezessionen sind gute Zeiten für
  sichere Häfen.

### 8.4 Suche nach eigenen Indikatoren

Getestet wurden rund 40 vorab festgelegte Varianten, jeweils getrennt für 1973–1999 und 2000–2026. Als Verbesserung
zählte nur, was in **beiden** Hälften bei Rendite, Gewinn-Anteil und größtem Rückgang mindestens gleich gut war.

**Kein Vorteil** (in mindestens einer Hälfte schlechter oder nur im Rauschbereich von ±0,3 %-Punkten):
US-Zinskurve invers, deutsche Zinskurve, Sahm-Regel, steigende Inflation, Bewertung (Shiller-CAPE), Halloween-Effekt,
Dollar- und Euro-Trend, US-Realzins für Gold, S&P-500-Trend statt World, Gold-gegen-Aktien-Verhältnis, andere
Formen der Arbeitslosen-Bedingung (Veränderung gegenüber 3–12 Monaten zuvor, andere Durchschnitte), asymmetrischer
Puffer, Trend auf USD- statt EUR-Kurs, Anleihen-Signal über Rendite oder Inflation.

**Zwei robuste Verbesserungen:**

1. **Gold-Hürde = tatsächlicher Euro-Zins** statt fester 2 %. Besser in beiden Hälften (11,9/7,1 % statt
   11,3/7,0 % p. a., 95/90 % statt 92/87 % im Plus). Begründung: Gold muss schlagen, was Cash gerade bringt – in den
   1980ern waren das 8–10 %. Feste Hürden von 0–4 % sind alle schlechter. Für den Bot heißt das: „Zins für Cash“ an den
   Euribor anpassen (Oktober 2026: ≈ 2,6 %).
2. **Frei werdendes Geld in Anleihen parken**, solange deren Trend steigt (statt Cash). Besser in beiden Hälften,
   stabil für Anleihen-Trends von 6–12 Monaten. Begründung: siehe 8.3. Das entspricht dem Ansatz von Antonacci
   (Ausweichen in Anleihen statt T-Bills).

| Variante | Rendite p. a. | vor 2000 / ab 2000 | 12 Monate im Plus | größter Rückgang | Verlustjahre |
|---|---|---|---|---|---|
| Bot heute (fix 2 %) | 9,1 % | 11,3 / 7,0 % | 90 % | −11,9 % | 6 |
| + Gold-Hürde = Euro-Zins | 9,5 % | 11,9 / 7,1 % | 92 % | −11,0 % | 4 |
| + Parken in Anleihen | 10,1 % | 12,8 / 7,4 % | 93 % | −10,8 % | 4 |

Das Parken in Anleihen kann DipAgentX heute nicht, weil jeder Bot für sich arbeitet; es bräuchte eine neue Option
(z. B. „im Ausstieg statt Cash ein Ausweich-Instrument kaufen, solange dessen Trend steigt“).

**Fazit der ersten Runde** (die zweite Runde in Abschnitt 9 geht weiter): Einen geheimen neuen Indikator gibt es nach dieser Prüfung nicht. Die Stärke des Ansatzes liegt in drei
unabhängigen Säulen und einem einfachen Monatssignal. Was zusätzlich hilft, ist ökonomisch begründet und klein:
die Gold-Hürde am tatsächlichen Zins ausrichten und Ausstiegsgeld in steigende Anleihen statt in Cash legen.

### 8.5 Quellen der Bausteine (geprüft)

- **10-Monats-Durchschnitt:** Mebane Faber, *A Quantitative Approach to Tactical Asset Allocation*, SSRN 2006,
  Journal of Wealth Management 2007 (Updates 2009/2013); gilt als eines der meistgeladenen SSRN-Papiere.
- **12-Monats-Momentum:** Moskowitz, Ooi & Pedersen, *Time Series Momentum*, Journal of Financial Economics 2012;
  Gary Antonacci, *Dual Momentum Investing*, 2014 (absolutes Momentum gegen T-Bills, im Ausstieg Anleihen).
- **Trend plus Arbeitslosigkeit:** Blog *Philosophical Economics* („Jesse Livermore“), Beitrag *In Search of the
  Perfect Recession Indicator* (Februar 2016). Der vorangehende Beitrag *Growth and Trend* (Januar 2016) nutzt
  Einzelhandelsumsatz und Industrieproduktion. Außerhalb der USA waren die Ergebnisse gemischt. Replikationen: Wouter
  Keller (*Lethargic Asset Allocation*, SSRN 2019), CXO Advisory (2019, Vorteil vor allem aus den 2000ern).
- **Drei/vier Säulen:** Harry Browne, Permanent Portfolio (1981 mit Terry Coxon, 4 × 25 % ab 1987);
  Bridgewater All Weather (1996).
- **Schwäche in den 2010ern:** Der reine 10-Monats-Trend lag 2010–2019 klar hinter Kaufen und Halten (in Euro hier
  8,5–10,0 % gegen 12,4 %). Die Arbeitslosen-Bedingung vermied die meisten Fehlsignale (12,0 %).
- **Nach Veröffentlichung schwächer:** McLean & Pontiff (Journal of Finance 2016) zeigen das für Aktien-Anomalien
  (−58 % nach Veröffentlichung); für Trendregeln ist das eine Übertragung, keine direkte Evidenz.
- **Gold:** London-Fixing 850 $ am 21.1.1980 (Tageshoch New York ~875 $), Tief 252,80 $ im Juli 1999, erst im
  Januar 2008 wieder über 850 $. In Euro sah es anders aus: Hoch Oktober 1980 (~623 €/oz Monatsschluss), wegen des
  starken Dollars schon 1983 wieder erreicht, danach −61 % bis Juli 1999.
- **Anleihen 2022:** XGLE −18,4 % (Bloomberg-Index Euro-Staatsanleihen −18,2 %), in dieser Datenreihe seit 1973 das
  mit Abstand schlechteste Jahr (zweitschlechtestes 1994 mit −6 %).

## 9. Zweite Suchrunde: drei Verbesserungen, die zusammen tragen

Neue Daten: wöchentliche US-Erstanträge auf Arbeitslosenhilfe (US-Arbeitsministerium, Bericht ar539, ab 1986, nicht
saisonbereinigt, Vergleich zum Vorjahresmonat), US-Staatsanleihen 10 J. (synthetisch aus der Rendite, Korrelation 0,99
zum IEF), Hochzins- und Unternehmensanleihen-Fonds (Vanguard, ab 1980), Franken/Yen-Kurse (Bundesbank).

**Was nicht half:** Kreditmarkt-Signal (Hochzinsfonds unter Trend), vierte Säule US-Staatsanleihen ungesichert,
Gewichtung nach Schwankung (sicherer, aber deutlich weniger Rendite), Gold zusätzlich mit Trendsignal.

**Was half – jeweils in beiden Hälften und in allen drei Teilzeiträumen (1973–89, 1990–2007, 2008–26):**

1. **Schnelleres Rezessionszeichen:** Aktien raus, wenn der Trend fällt UND (Arbeitslosenquote über 12-Monats-Schnitt
   ODER Erstanträge mehr als 5 % über Vorjahr). Erstanträge reagieren Wochen früher als die Quote. Schwellen von 0–20 %
   funktionieren ähnlich.
2. **Zwei Trendmaße statt einem:** Der Aktien-Trend gilt erst als gefallen, wenn der Kurs unter dem 10-Monats-Schnitt
   liegt UND die 12-Monats-Rendite unter dem Euro-Zins. Das vermeidet Fehlsignale.
3. **Ausweichen statt Cash:** Geld einer ausgestiegenen Säule geht in die bessere von Bund-Anleihen (XGLE) und
   **währungsgesicherten US-Staatsanleihen** (bei TR z. B. Amundi US Treasury Bond 7-10Y EUR Hedged,
   LU1407888137), gemessen an der 12-Monats-Rendite – nur wenn diese den Euro-Zins schlägt, sonst Cash.
   In Krisen steigen US-Staatsanleihen meist stärker als Bunds (2000–02 +44 %, 2008 +24 %, 2011 +18 %).

| | Basis (Abschnitt 3, Euro-Zins) | mit den drei Verbesserungen | World halten |
|---|---|---|---|
| Rendite p. a. 1973–2026 | 9,5 % | **10,8 %** | 8,9 % |
| vor 2000 / ab 2000 | 11,9 / 7,1 % | 13,5 / 8,2 % | 11,6 / 6,6 % |
| 12-Monats-Zeiträume im Plus | 92 % | 93 % | 74 % |
| 3-Jahres-Zeiträume im Plus | 98 % | 99,5 % | 82 % |
| schlechteste 12 Monate | −9,3 % | −8,4 % | −37,6 % |
| größter Rückgang | −11,0 % | −10,8 % | −54,5 % |
| Verlust-Kalenderjahre | 4 | 4 (1977 −0,1 %, 1994 −5,5 %, 2018 −2,6 %, 2022 −3,0 %) | 13 |
| besser als World über 10 Jahre | 41 % | 62 % | – |
| ab 1989 gegen ACWI IMI (8,2 %) | 8,0 % | **9,3 %** | – |
| schlägt ACWI IMI in 5/10/15-J.-Zeiträumen | 37/43/53 % | 42/60/76 % | – |
| Umschichtungen pro Jahr | 3,2 | 5,6 | 0 |

Faktor auf den Einsatz (typisch / 5 %-Quantil / schlechtester Start): 1 Jahr 1,106 / 0,990 / 0,916 · 3 Jahre
1,330 / 1,093 / 0,966 · 5 Jahre 1,652 / 1,267 / 1,082 · 10 Jahre 2,549 / 1,879 / 1,762.

Jahrzehnte (Verbesserungen / Basis / World): 1973–90 13,7 / 12,4 / 10,1 % · 1990–2000 13,0 / 11,1 / 13,6 % ·
2000–10 7,0 / 5,5 / −3,3 % · 2010–20 8,7 / 7,9 / 12,4 % · 2020–26 9,2 / 8,3 / 13,6 %.

**Robustheit:** 288 Nachbar-Einstellungen (Durchschnitt 8–12 Monate, Puffer 0–2 %, Momentum 9/12, Erstanträge-Schwelle
0–20 %, Ausweich-Rückblick 9–15 Monate, mit/ohne US-Anleihen): Rendite 10,0–10,9 % – jede liegt über der Basis –,
91–95 % der 12-Monats-Zeiträume im Plus, größter Rückgang stets ≈ −11 %. Kosten von 0,5 % je Umschichtung statt 0,1 %:
immer noch 9,9 % p. a. Gewichte: 34/33/33 → 10,5 %, −9 %; 50/25/25 → 11,1 %, −14 %; 60/20/20 → 11,5 %, −17 %.

**Vorbehalte:** Insgesamt wurden rund 70 Varianten getestet; ein Teil des Vorsprungs kann Zufall sein. Die drei
Bausteine sind aber ökonomisch begründet und in der Literatur bekannt (Erstanträge als Frühindikator, Antonaccis
Ausweichen in Anleihen). Erstanträge gibt es erst ab 1986 (davor nur die Arbeitslosenquote); die gesicherten
US-Anleihen sind synthetisch (Rendite plus Zinsdifferenz).

**Stand jetzt (Schluss September 2026):** gleiche Aufteilung wie heute – Welt und Gold investiert, Anleihen draußen;
das freie Geld bleibt in Cash, weil weder Bunds (−2,9 % in 12 Monaten) noch gesicherte US-Anleihen (−6,0 %) den
Zins (+2,2 %) schlagen. Erstanträge liegen 10 % unter Vorjahr.

**Umsetzung in DipAgentX:** braucht drei neue Optionen im Trendfolger – Erstanträge als zusätzliche Bedingung,
„Durchschnitt UND 12-Monats-Rendite“ als Trendsignal und Ausweich-Instrumente statt Cash.

## 10. Dritte Suchrunde: systematische Suche über 57.024 Kombinationen

Kombiniert wurden 8 Aktien-Trendsignale × 11 Rezessionsfilter (Arbeitslosenquote, Erstanträge, US-Zinskurve,
Hochzinsmarkt, Volatilität, Aktien-zu-Anleihen-Verhältnis und Kombinationen) × 6 Gold-Signale × 4 Anleihen-Signale ×
5 Ausweich-Regeln × 2 Rückblicke × 3 Gewichtungen.

**Blindtest:** Die besten Kombinationen aus 1973–1999 erreichen 2000–2026 nur 7,6 % p. a. und 85 % Gewinn-Zeiträume –
weniger als die Strategie aus Abschnitt 9 (8,2 %, 92 %). Die Rangfolge der Kombinationen in beiden Hälften hängt kaum
zusammen (Rangkorrelation 0,23 bei der Rendite, 0,11 bei der Gewinnquote). **Walk-forward** (alle fünf Jahre die bis
dahin beste Kombination nehmen): 1985–2026 nur 8,2 % p. a. gegen 9,5 % für die feste Strategie aus Abschnitt 9.
Mehr Optimieren findet also vor allem Zufall.

**Was trotzdem trägt:** 17 der 57.024 Kombinationen sind in beiden Hälften besser als Abschnitt 9. Fast alle teilen zwei
Bausteine, und genau die bringen einen kleinen, aber stabilen Vorsprung:

1. **US-Zinskurve als drittes Rezessionszeichen:** Aktien raus, wenn der Trend fällt UND (Arbeitslosenquote steigt ODER
   Erstanträge > +5 % ODER die Zinskurve 10 J. − 3 M. war in den letzten 24 Monaten invers). Fenster 12–36 Monate
   funktionieren ähnlich.
2. **Anleihen-Säule mit Momentum statt Durchschnitt:** XGLE nur halten, solange seine 12-Monats-Rendite den Euro-Zins
   schlägt (dieselbe Logik wie bei Gold). Rückblicke 6–15 Monate funktionieren ähnlich.

| | Abschnitt 9 | **mit beiden Bausteinen** |
|---|---|---|
| Rendite p. a. 1973–2026 | 10,75 % | **10,98 %** |
| vor 2000 / ab 2000 | 13,5 / 8,2 % | 13,6 / 8,5 % |
| 12-Monats-Zeiträume im Plus | 93 % | 93 % |
| größter Rückgang | −10,8 % | −10,8 % |
| Verlust-Kalenderjahre | 1977, 1994, 2018, 2022 (−3,0 %) | 1977, 1987, 1994, 2018, 2022 (−0,3 %) |
| ab 1989 gegen ACWI IMI (8,2 %) | 9,3 % | 9,5 % |
| schlägt ACWI IMI in 5/10/15-J.-Zeiträumen | 42/60/76 % | 43/61/78 % |
| besser als World über 10 Jahre | 62 % | 63 % |

Faktor auf den Einsatz (typisch / 5 %-Quantil / schlechtester Start): 1 Jahr 1,105 / 0,992 / 0,915 · 3 Jahre
1,334 / 1,117 / 0,972 · 5 Jahre 1,675 / 1,273 / 1,088 · 10 Jahre 2,658 / 1,829 / 1,717.

**Wie sicher ist der Vorsprung?** Block-Bootstrap der Monatsrenditen: +0,20 % p. a. gegenüber Abschnitt 9,
90 %-Band −0,09 bis +0,50 %, zu 87 % größer als null. Zum Vergleich: Gegenüber World halten ist der Renditevorsprung
der Strategie statistisch unsicher (zu 64 % größer als null) – sicher ist der Vorteil beim Risiko (−11 % statt −55 %
Rückgang, 93 % statt 74 % Gewinn-Zeiträume).

**Stand jetzt:** keine Änderung (Welt, Gold investiert; Anleihen draußen; freies Geld in Cash). Die Zinskurve war
zuletzt im April 2025 invers – bis April 2027 würde ein Trendbruch bei Aktien deshalb auch ohne steigende
Arbeitslosigkeit zum Verkauf führen.

**Fazit:** Die beste belastbare Kombination ist Abschnitt 9 plus Zinskurve plus Anleihen-Momentum. Darüber hinaus
liefert die Suche nur noch Varianten, die in der Vergangenheit besser aussehen, aber im Blindtest nicht halten.

## 11. Vierte Suchrunde: Währungen

Daten: Monatsschlusskurse von US-Dollar, Franken, Pfund (ab 1948/49), Yen (ab 1969) und Austral-Dollar (ab 1966)
gegen DM bzw. Euro (Bundesbank/EZB), Dollar-Index (ab 1971). Gesicherte Anlagen = Rendite in Dollar plus
Zinsdifferenz Euro − Dollar (Devisentermin-Logik); geprüft gegen den echten iShares MSCI World EUR Hedged
(IE00B441G979, ab 2010): Korrelation 0,97, der echte ETF liegt ~0,5 % p. a. darunter – dieser Abschlag ist unten
eingerechnet.

**Kein Vorteil:** Franken- oder Yen-Stärke, AUD/JPY unter Trend oder starker Dollar als Krisenzeichen (weder als
zusätzliches Rezessionszeichen noch als eigener Verkaufsgrund); Dollar-Tagesgeld oder ungesicherte US-Anleihen als
Ausweich-Anlage; Welt und Gold dauerhaft gesichert; Puffer gegen Hin-und-Her beim Dollar-Signal.

**Vorteil: Welt-Säule dynamisch währungsgesichert.** Liegt der Euro über seinem 12-Monats-Durchschnitt gegenüber dem
Dollar (Dollar im Abwärtstrend), hält der Welt-Bot den gesicherten ETF (z. B. IE00B441G979, bei TR handelbar),
sonst den ungesicherten. Begründung: Währungen haben Trends (Zeitreihen-Momentum, Moskowitz/Ooi/Pedersen 2012); ein
fallender Dollar kostet ungesicherte Euro-Anleger Rendite. Rückblicke von 6–18 Monaten funktionieren ähnlich.
Im Schnitt ist die Welt-Säule gut die Hälfte der Zeit gesichert, 1,6 Wechsel pro Jahr.

**Gold besser nicht absichern:** vor Steuern +0,3 %-Punkte, aber größerer Rückgang (−13 %) und nach Steuern
schlechter, weil ein gesicherter Gold-ETC die Steuerfreiheit von Xetra-Gold nach einem Jahr verliert.

| | Abschnitt 10 (C6) | **+ Welt dynamisch gesichert (C7)** | World halten |
|---|---|---|---|
| Rendite p. a. (monatl. Gewichte) | 10,98 % | **11,37 %** | 8,93 % |
| vor 2000 / ab 2000 | 13,6 / 8,5 % | 14,3 / 8,6 % | 11,6 / 6,6 % |
| 12-Monats-Zeiträume im Plus | 93 % | **96 %** | 74 % |
| 3-Jahres-Zeiträume im Plus | 99,5 % | 99,7 % | 82 % |
| größter Rückgang | −10,8 % | −10,5 % | −54,5 % |
| Verlust-Kalenderjahre | 5 | 3 (1994 −1,8 %, 2018 −4,7 %, 2022 −0,3 %) | 13 |
| ab 1989 gegen ACWI IMI (8,2 %) | 9,5 % | 9,7 % | – |
| schlägt ACWI IMI in 5/10/15-J.-Zeiträumen | 43/61/78 % | 44/62/82 % | – |
| besser als World über 10 Jahre | 63 % | 69 % | – |

Faktor auf den Einsatz C7 (typisch / 5 %-Quantil / schlechtester Start): 1 Jahr 1,105 / 1,007 / 0,930 ·
3 Jahre 1,354 / 1,126 / 0,994 · 5 Jahre 1,699 / 1,289 / 1,078 · 10 Jahre 2,765 / 1,846 / 1,703.

Bootstrap C7 gegen C6: +0,44 % p. a. (ohne Hedge-Abschlag), 90 %-Band −0,19 bis +1,11 %, zu 87 % größer als null.
Mit 1 % statt 0,5 % Hedge-Kosten: 11,28 % p. a.

### Nach Steuern (DipAgentX-nah gerechnet)

Simulation mit drei unabhängigen Bots, jährlichem Angleichen auf 40/30/30, Abgeltungsteuer 26,375 % bei jedem Verkauf
(Aktien-ETF mit 30 % Teilfreistellung, Xetra-Gold nach 12 Monaten steuerfrei, Verlusttopf, Zinsen versteuert, kein
Freibetrag), am Ende alles verkauft und versteuert, 0,5 % Hedge-Kosten:

| | vor Steuern | nach Steuern | 12M im Plus (nach St.) | größter Rückgang (nach St.) |
|---|---|---|---|---|
| C6 | 11,0 % | 9,3 % | 86 % | −13,2 % |
| **C7** | 11,4 % | **9,5 %** | **92 %** | −11,3 % |
| World halten | 9,0 % | 8,6 % | – | −55 % |

Die Steuer kostet die Strategie rund 1,7–2 %-Punkte pro Jahr (World halten nur 0,4, weil erst am Ende versteuert
wird). Auch nach Steuern liegt C7 knapp 1 %-Punkt über World halten – bei einem Fünftel des Rückgangs.

**Stand jetzt:** Euro bei 1,1355 $ unter seinem 12-Monats-Schnitt (1,1606 $) → Welt-Säule **ungesichert** (wie heute).
Zuletzt wechselte das Signal oft (2023–2026 elfmal), das kostet in seitwärts laufenden Dollar-Phasen.

**Umsetzung in DipAgentX:** braucht im Trendfolger zusätzlich „Ersatz-Instrument je nach Dollar-Trend“ (z. B. SPYI
bzw. EUNL ungesichert ↔ IE00B441G979 gesichert).

## 12. Tagesgenauer Einstieg, auch an den ungünstigsten Tagen

Simulation mit Tageskursen (MSCI World und Wechselkurse täglich ab 1972, Gold täglich aus Frankfurter Fixing bzw.
COMEX; Anleihen, US-Anleihen und Cash aus Monatswerten auf die Tage verteilt). Einstieg an **jedem Handelstag ab
Oktober 1973** (≈ 13.400 Einstiege): Der Bot kauft am Einstiegstag sofort mit den Signalen des letzten
Monatsschlusses, danach entscheidet er monatlich. Die Tageskurven bestätigen die Monatsrechnung (C7 11,35 % p. a.,
Bot heute 9,12 %, World 8,91 %).

| Einstieg an jedem Tag | im Plus nach 1 / 3 / 5 / 10 J. | schlechtester Einstieg nach 1 / 3 / 5 J. | tiefster Stand unter Einstand (3 J.) | Zeit bis Einstand zurück (Median / 95 % / längste) |
|---|---|---|---|---|
| **C7** (beste Kombination) | 95,9 / 99,7 / 100 / 100 % | −9,9 / −2,9 / +0,9 % | Median −1,1 %, schlimmster −18 % (Gold-Hoch 21.1.1980) | 0,1 / 0,7 / 3,9 J. |
| Bot heute (laufende Papier-Bots) | 89,8 / 97,5 / 100 / 100 % | −12,1 / −7,6 / −1,7 % | Median −1,4 %, schlimmster −17 % (21.2.2020) | 0,1 / 1,3 / 4,7 J. |
| 40/30/30 ohne Timing | 79,9 / 91,8 / 99,1 / 100 % | −19,0 / −17,3 / −9,5 % | Median −3,1 %, schlimmster −23 % | 0,4 / 3,6 / 5,0 J. |
| World halten | 73,9 / 82,0 / 84,8 / 92,8 % | −43,6 / −51,6 / −37,3 % | Median −8,0 %, schlimmster −57 % (5.9.2000) | 1,1 / 10,9 / 13,3 J. |

### Einstieg genau am Hoch vor großen Einbrüchen (Rendite nach 1 / 3 / 5 / 10 J., tiefster Stand)

| Einstiegstag | C7 | Bot heute | World halten |
|---|---|---|---|
| 1.10.1973 Ölkrise | +29 / +57 / +92 / +324 %, −0 % | +26 / +60 / +79 / +285 %, −1 % | −33 / −5 / −6 / +111 %, −36 % |
| 14.8.1987 vor Crash 1987 | −1 / +20 / +46 / +184 %, −9 % | −4 / +11 / +23 / +115 %, −13 % | −6 / −9 / −13 / +139 %, −30 % |
| 5.9.1989 Hoch 1989/90 | +5 / +28 / +61 / +199 %, −3 % | −2 / +10 / +35 / +123 %, −6 % | −30 / −28 / +5 / +169 %, −36 % |
| 5.9.2000 Dotcom-Hoch (in Euro) | −4 / +8 / +25 / +139 %, −8 % | −8 / −4 / +6 / +83 %, −10 % | −27 / −43 / −32 / −32 %, −57 % |
| 15.6.2007 vor Finanzkrise | +10 / +55 / +78 / +154 %, −2 % | +1 / +40 / +59 / +114 %, −4 % | −20 / −21 / −13 / +72 %, −53 % |
| 15.4.2015 Hoch 2015 | −9 / −3 / +8 / +63 %, −12 % | −11 / −7 / +8 / +55 %, −15 % | −10 / +7 / +18 / +125 %, −22 % |
| 19.2.2020 vor Corona-Crash | −0 / +8 / +44 %, −17 % | −2 / +6 / +44 %, −17 % | +5 / +21 / +84 %, −34 % |
| 4.1.2022 vor Zinswende | +0 / +28 %, −4 % | −2 / +29 %, −4 % | −12 / +33 %, −17 % |
| 13.2.2025 vor April 2025 | +18 %, −10 % | +10 %, −10 % | +3 %, −20 % |
| 21.1.1980 Gold-Hoch | +2 / +38 / +76 / +248 %, −18 % | +5 / +33 / +68 / +143 %, −16 % | +37 / +78 / +202 / +426 %, −1 % |
| 31.12.2020 Anleihen-Hoch | +7 / +16 / +62 %, −3 % | +9 / +15 / +54 %, −2 % | +33 / +39 / +90 %, −1 % |

### Die echte Schwachstelle: Korrektur ohne Rezession, alle drei Säulen gleichzeitig

Der schlechteste Einstieg für beide Bot-Varianten war **April 2015** (C7 −10 % nach 1 Jahr, −3 % nach 3 Jahren,
4 Jahre bis zum Einstand). Damals fielen alle drei Säulen gleichzeitig: Weltaktien −22 % bis Februar 2016 (ohne
Rezession, die Arbeitslosigkeit sank – deshalb kein Verkauf, so gewollt), Bundesanleihen im „Bund-Tantrum“ nach
dem Renditetief, Gold bis Dezember 2015 schwach. Dann verkaufte der Gold-Bot im Januar 2016 genau vor einem Anstieg
von +16 % in zwei Monaten. Ähnlich, aber milder: Dezember 2017, Mai 2000, Februar 1994 (Anleihen-Crash).

Schnelle Crashs (Oktober 1987, Februar 2020) und Gold-Hochs (Januar 1980) führen zu einem tiefen Zwischenstand von
bis zu −18 %, weil die Signale erst zum Monatsende reagieren; der Einstand war jeweils nach 0,7–1,4 Jahren zurück.
Lange Bärenmärkte (1973/74, 2000–03, 2007–09) sind dagegen gerade die Stärke der Strategie.

## 13. Nachkaufen und Abbauen nach Indikatoren

Getestet auf Basis von C7 (Abschnitt 11, mit 0,5 % Hedge-Kosten: 11,37 % p. a., 95,7 % der 12-Monats-Zeiträume im
Plus, −10,5 % größter Rückgang, schlechteste 12 Monate −7,0 %).

### Kein Vorteil

| Variante | Rendite p. a. | 12M im Plus | größter Rückgang |
|---|---|---|---|
| Trendbruch ohne Rezession → halbe Position abbauen | 11,23 % | 94,2 % | −10,5 % |
| Punkte-System: Anteil = Ø aus 5 Signalen | 10,58 % | 93,8 % | −8,7 % |
| Aus- und Einstieg über 2 / 3 Monate verteilt | 11,36 / 11,34 % | 95,2 % | −10,3 / −8,7 % |
| nur Wiedereinstieg in 3 Raten | 11,38 % | 95,4 % | −8,7 % |
| Abbauen bei Überhitzung (Kurs > 10–15 % über Ø10, 12M > 30 %) | 11,15–11,33 % | 95,8–96,3 % | −10,5 % |
| Größe nach Schwankung (Ziel 15/20 %) | 11,20 / 11,31 % | 95,7 % | −10,5 % |
| gegen den Trend im Crash zurückkaufen (−25/−30/−40 %) | 11,28–11,53 % | 95,5–95,7 % | −10,5 % (nur eine Schwelle hilft, nicht robust) |
| Gold bzw. Anleihen gestaffelt (Ø zweier Signale) | 10,97 / 11,29 % | 95,4 / 95,7 % | −10,5 / −11,0 % |

Teilpositionen glätten nichts, was das Alles-oder-nichts-Signal nicht schon leistet – sie kosten meist Rendite.
Einzige Ausnahme: der Wiedereinstieg in drei Monatsraten senkt den größten Rückgang auf −8,7 % bei gleicher Rendite
(ab 2000 aber 8,4 % statt 8,6 %).

### Vorteil: Nachkaufen bei Rücksetzern im Aufwärtstrend

Solange das Aktien-Signal „investiert“ ist und der Welt-Index (Monatsschluss) mindestens 10 % unter seinem
12-Monats-Hoch liegt, werden 20 Prozentpunkte zusätzlich in Aktien gehalten – finanziert aus Anleihen, Ausweich-Anlage
bzw. Cash. Erholt sich der Kurs über die Schwelle oder dreht das Signal, wird das Zusatzstück wieder abgebaut.

- 70 Varianten (Schwelle −3 bis −20 %, Zusatz 5–30 Pp., halten bis Schwelle oder neues Hoch): alle mindestens so gut
  wie C7 (11,38–12,13 %), 62 davon in beiden Hälften besser.
- Kandidat −10 %/+20 Pp.: **11,63 % p. a.**, 96,2 % im Plus, −10,5 % Rückgang, schlechteste 12 Monate **−5,5 %**;
  1973–89 15,8 / 15,5 %, 1990–2007 10,6 / 10,5 %, 2008–26 9,1 / 8,8 % (Kandidat / C7). Bootstrap: +0,25 % p. a.,
  90 %-Band +0,08 bis +0,42 %.
- **Gegentest:** Gleich häufiges Nachkaufen zu zufälligen Zeitpunkten (500 Läufe) bringt im Median 11,45 %, nur 2 %
  der Zufallsläufe erreichen das echte Signal. Dauerhaft entsprechend mehr Aktien: 11,47 %. Der Zeitpunkt zählt also.
- Eingesetzt nur in 6 % der Monate, 19-mal seit 1973 (z. B. Okt. 1987, Aug. 1998, Juli 2009, Aug. 2011, Sept. 2015,
  Dez. 2018, Juni 2022, Apr. 2025).

**Umsetzung als Bots** (nach Steuern, unabhängige Bots, jährlich angeglichen):

| Aufteilung | vor Steuern | nach Steuern | schlechteste 12 M | größter Rückgang |
|---|---|---|---|---|
| C7: Welt 40 / Gold 30 / Anleihen 30 | 11,43 % | 9,47 % | −7,5 % | −11,1 % |
| Welt 40 / Gold 30 / Anleihen 20 / **Anleihen-oder-Nachkauf 10** | 11,56 % | 9,58 % | −6,7 % | −11,1 % |
| Welt 40 / Gold 30 / Anleihen 10 / **Anleihen-oder-Nachkauf 20** | **11,69 %** | **9,67 %** | **−6,0 %** | −11,1 % |
| eigener Reserve-Bot 20 % (wartet in Anleihen/Cash), Säulen 32/24/24 | 10,90 % | 8,90 % | −4,9 % | −8,6 % |

Der „Anleihen-oder-Nachkauf“-Bot verhält sich wie der Anleihen-Bot, wechselt aber bei einem Rücksetzer im
Aufwärtstrend in Weltaktien. Ein eigener Reserve-Bot, der nur auf Rücksetzer wartet, senkt das Risiko weiter, kostet
aber Rendite, weil sein Geld meist in Anleihen oder Cash liegt.

### Einstieg auf einmal, verteilt oder als Sparplan (Tageskurse, jeder dritte Handelstag ab 1973)

| | Raten | im Plus nach 1 J. / schlechtester | im Plus nach 3 J. / schlechtester |
|---|---|---|---|
| C7 | auf einmal | 95,9 % / −8,8 % | 99,7 % / −2,5 % |
| C7 | 6 Monatsraten | 95,7 % / −8,7 % | 100 % / +0,2 % |
| C7 | 12 Monatsraten | 95,9 % / −8,2 % | 100 % / −0,2 % |
| C7 + Anleihen-oder-Nachkauf 20 | auf einmal | 96,3 % / −5,7 % | 99,6 % / −1,9 % |
| World halten | auf einmal | 74,0 % / −42,5 % | 82,0 % / −51,6 % |
| World halten | 12 Monatsraten | 79,0 % / −30,9 % | 84,3 % / −51,2 % |

Bei der Strategie bringt verteiltes Einsteigen kaum etwas – sie hat ihr Timing schon eingebaut. In den ungünstigsten
Fällen hilft es trotzdem etwas (6 Raten statt sofort, nach 1 / 3 J.): Aug. 1987 +5/+27 % statt −1/+20 %,
Sept. 2000 +1/+13 % statt −4/+8 %, Apr. 2015 −5/+3 % statt −10/−3 %, Feb. 2020 +9/+17 % statt −0/+8 %.

Sparplan (gleicher Monatsbetrag, 10 Jahre): C7 im Median 1,77-fach der Einzahlungen, schlechtester Start 1,29-fach
(Sept. 2013), immer im Plus. World halten: Median 1,73-fach, schlechtester Start 0,66-fach (Febr. 1999), 96 % im Plus.
