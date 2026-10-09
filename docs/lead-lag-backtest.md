# Lead-Lag-Bot: Bringt er Gewinn? Backtest mit Minuten- und Sekundendaten

Stand: 9. Oktober 2026 · DipAgentX 1.38.1 · Backtest-Ergebnisse, keine Anlageberatung.

## 1. Frage und Antwort

Der Lead-Lag-Bot (Strategie `leadlag`, seit 1.37.0) kauft einen Coin wenige Sekunden nachdem BTC-USDT in 60 Sekunden
um mindestens 0,5 % gestiegen ist, sofern der Coin in denselben 60 Sekunden weniger als halb so stark mitgezogen hat,
und verkauft nach 15 Minuten (Stop-Loss 1,5 %, Market-Orders). Grundlage war der Backtest in
`docs/btc-eth-verbindung.md` (Teil 2, L1): auf 1-Minuten-Kerzen folgte ETH-EUR nach solchen Sprüngen im Schnitt mit
+0,4 bis +0,7 % in 15 Minuten.

**Antwort: Nein, so wie er gebaut ist, bringt er keinen Gewinn.**

- Auf **Minutenkerzen** (2021–2026) liegt der Bot mit seinen Standardwerten nach Kosten bei **−0,06 % je Trade**
  (−200 € im Jahr bei 5.000 € Einsatz). Ohne Stop-Loss bleiben +0,08 % je Trade – nicht von Null unterscheidbar.
- Auf **Sekundendaten** (Oktober 2025 bis September 2026, Nachbildung des Monitors auf die Sekunde) **verschwindet das
  Nachhinken**: ETH zieht innerhalb desselben 60-Sekunden-Fensters mit (Median 1,0- bis 1,1-fache BTC-Bewegung). Nur
  2–5 % der Sprünge gelten als „nachgehinkt“, und genau diese holen danach **nicht** auf (−0,2 bis −0,3 % in 15 Minuten).
- Der scheinbare Gewinn im alten Backtest war ein **Artefakt der Minutenkerzen**: Fällt der BTC-Sprung ans Ende einer
  Minute, landet ETHs Mitbewegung (Sekunden später) in der nächsten Kerze. Die Kerze sagt „nachgehinkt“, die
  „Aufholbewegung“ ist in Wirklichkeit die gleichzeitige Bewegung. Dazu wird ETH-EUR auf Binance nur in 15 % aller
  Sekunden gehandelt, der Minutenschlusskurs ist also oft Sekunden alt.
- Der **Paper-Bot (5.000 €) hätte in den letzten zwölf Monaten genau zwei Trades gemacht**, beide am Abend des
  10. Oktober 2025 (Crash-Erholung), zusammen +427 €. Alle anderen Monate: kein einziger Trade.

## 2. Was genau getestet wurde

**Daten.** Binance-Kerzen von data.binance.vision. 1 Minute: BTC-USDT, ETH-USDT, ETH-EUR, BTC-EUR Januar 2021 bis
September 2026; SOL, XRP, DOGE, ADA, LINK, AVAX, LTC, SUI gegen EUR Januar 2024 bis September 2026. 1 Sekunde: BTC-USDT
und ETH-EUR Oktober 2025 bis September 2026, ETH-USDT März und August 2026.

**Kosten.** 0,09 % Gebühr je Seite (wie die Papier-Gebühren des Agenten seit 1.37.0) plus 0,05 % halber Spread je Seite
(Kauf zum Ask, Verkauf zum Bid) – 0,28 % je Runde. Der echte Spread auf Revolut X ist noch nicht gemessen; ist er
größer, wird alles schlechter.

**Bot-Regeln.** Einstieg frühestens zum ersten Kurs nach der Signalminute (Minutenkerzen) bzw. 2–60 Sekunden nach der
Erkennung (Sekundendaten). Eine Position auf einmal, höchstens ein Ereignis je 5 Minuten (wie der Monitor). Stop-Loss
auf dem Bid, alle 30 Sekunden geprüft (Takt des Agenten).

## 3. Minutenkerzen: der Bot wie konfiguriert

ETH-EUR, Sprung ≥ 0,5 %, nachgehinkt, 15 Minuten halten, 5.000 € je Trade:

| Variante | Zeitraum | Trades/Jahr | brutto je Trade | **netto je Trade** | Gewinnquote | €/Jahr | t-Wert |
|---|---|---|---|---|---|---|---|
| Bot (Stop 1,5 %) | 2021–23 | 112 | +0,36 % | **−0,05 %** | 39 % | −297 | −0,5 |
| Bot (Stop 1,5 %) | 2024–26 | 21 | +0,50 % | **−0,10 %** | 40 % | −103 | −0,6 |
| ohne Stop | 2021–23 | 110 | +0,35 % | +0,07 % | 43 % | +363 | 0,6 |
| ohne Stop | 2024–26 | 21 | +0,43 % | +0,15 % | 43 % | +157 | 0,7 |
| ohne Stop, 1 min später | 2024–26 | 20 | +0,25 % | −0,03 % | 42 % | −31 | −0,2 |

- Der **Stop-Loss kostet** rund 0,15 % je Trade: 12–15 % der Trades werden bei −1,5 % ausgestoppt, und viele davon
  hätten sich bis Minute 15 erholt. Auch Stops von 1 %, 2 %, 3 % oder 5 % machen es nicht besser.
- Ohne Stop ist der Rest (+0,07 bis +0,15 %) statistisch Rauschen (t-Werte unter 1) und steht gegen einen
  unbekannten Revolut-X-Spread.
- Die Kontrolle bestätigt den Filter: nach Sprüngen, bei denen ETH **schon** mitgezogen hatte, liegt der Bot bei
  −0,21 bis −0,23 % je Trade (1.700 bzw. 440 Trades).

**Schwelle und Haltedauer.** Größere Sprünge sehen besser aus – aber es sind wenige Ereignisse, und der Gewinn hängt
an einzelnen Tagen:

| Sprung ≥ | Zeitraum | Trades/Jahr | netto je Trade (ohne Stop) | t-Wert |
|---|---|---|---|---|
| 0,4 % | 2021–23 / 2024–26 | 209 / 39 | −0,09 % / −0,00 % | −1,3 / 0,0 |
| 0,5 % | 2021–23 / 2024–26 | 110 / 21 | +0,07 % / +0,15 % | 0,6 / 0,7 |
| 0,7 % | 2021–23 / 2024–26 | 42 / 9 | +0,51 % / +0,64 % | 1,9 / 1,2 |
| 1,0 % | 2021–23 / 2024–26 | 15 / 4 | +1,44 % / +2,47 % | 2,1 / 1,8 |

Bei ≥ 0,7 % stammen **75 % des Gesamtgewinns aus fünf Trades** (19. Mai 2021 zweimal, 22. Februar 2021, 12. Mai 2022,
10. Oktober 2025); ohne diese fünf bleiben +0,14 % je Trade. 2022, 2023 und 2024 lagen bei +0,02 / +0,01 / +0,19 %.
Das ist kein Nachhinken, sondern der Erholungsschub an Crash-Tagen – derselbe Effekt wie der „Crash-Käufer“ in
`docs/daytrading-forschung.md`, nur seltener getroffen.

**Andere Coins (2024–2026, Minutenkerzen).** Mit den Bot-Standardwerten (0,5 %, Stop 1,5 %) verlieren SOL, LINK, LTC
und BTC-EUR (−0,2 bis −0,4 % je Trade), ETH liegt bei −0,10 %, XRP/AVAX/SUI um Null, nur DOGE und ADA sind positiv
(+0,07 / +0,44 %). Ohne Stop und mit Schwelle 1 % zeigen DOGE, ADA, XRP, LINK, AVAX +4 bis +7 % je Trade – bei
8 bis 13 Trades in 2¾ Jahren, fast alle an denselben Crash-Tagen. Keine Grundlage.

## 4. Sekundendaten: das Nachhinken gibt es nicht

Nachgebaut wie der Monitor im Agenten (`agent/app/leadlag.py`): alle 2 Sekunden BTC-USDT jetzt gegen vor 60 Sekunden,
Ereignis ab 0,3 %, höchstens eines je 5 Minuten, „nachgehinkt“ = Coin-Bewegung in denselben 60 Sekunden unter der
Hälfte der BTC-Bewegung.

**Wie stark zieht ETH im selben 60-Sekunden-Fenster mit?** Verhältnis ETH-Bewegung / BTC-Bewegung bei Sprüngen ab 0,3 %
(März und August 2026, 395 Ereignisse):

| | 10 % | 25 % | Median | 75 % | 90 % | Anteil „nachgehinkt“ (< 0,5) |
|---|---|---|---|---|---|---|
| ETH-USDT (liquide) | 0,66 | 0,88 | **1,10** | 1,32 | 1,60 | 4 % |
| ETH-EUR | 0,61 | 0,80 | **1,03** | 1,26 | 1,56 | 5 % |

ETH bewegt sich innerhalb der 60 Sekunden praktisch gleichzeitig mit BTC, meist sogar stärker. Ein Vorsprung von BTC,
den ein Bot abwarten könnte, zeigt sich nicht einmal auf Sekundenebene.

**Holen die wenigen „nachgehinkten“ Fälle auf?** Bewegung des Coins ab dem Zeitpunkt der Erkennung:

| Fall | n | nach 2 s | 5 s | 10 s | 30 s | 60 s | 15 min |
|---|---|---|---|---|---|---|---|
| ETH-USDT nachgehinkt, Sprung 0,3–0,4 % | 16 | +0,02 % | +0,00 % | +0,00 % | −0,01 % | −0,03 % | **−0,28 %** |
| ETH-USDT mitgezogen, Sprung 0,3–0,4 % | 356 | +0,01 % | +0,02 % | +0,02 % | +0,01 % | +0,01 % | +0,06 % |
| ETH-EUR nachgehinkt, 0,3–0,4 % (12 Monate) | 94 | +0,01 % | +0,01 % | +0,05 % | +0,08 % | +0,12 % | +0,13 % |
| ETH-EUR mitgezogen, 0,3–0,4 % (12 Monate) | 2.191 | +0,01 % | +0,01 % | +0,01 % | +0,01 % | +0,01 % | +0,01 % |
| ETH-EUR, Sprung ≥ 0,5 % (12 Monate, alle) | 29 | – | – | – | – | – | +0,26 % (nicht nachgehinkt, 26) / +4,9 % (nachgehinkt, 3, alle 10. Okt. 2025) |

Nichts davon deckt 0,28 % Kosten. Was auf ETH-EUR an Aufholen bleibt (+0,13 %), ist zur Hälfte der veraltete
Binance-Druck (ETH-EUR handelt dort nur in 15 % der Sekunden; BTC-USDT in 90 %). Revolut X stellt Bid/Ask fortlaufend –
dort ist eher noch weniger zu holen.

**Der Bot auf die Sekunde nachgespielt** (Oktober 2025 bis September 2026, Einstieg 5 Sekunden nach der Erkennung):

| Variante | Trades in 12 Monaten | netto je Trade | Summe bei 5.000 € |
|---|---|---|---|
| Monitor wie gebaut (Ereignis ab 0,3 %, 5-min-Sperre), Bot ab 0,5 % nachgehinkt, Stop 1,5 % | **2** (beide 10. Okt. 2025, 21:28 und 21:49 UTC) | +7,26 % und +1,28 % | +427 € |
| Monitor erst ab 0,5 % (ohne die 0,3-%-Sperre), Stop 1,5 % | 7 | +0,02 % | +7 € |
| dito ohne Stop | 7 | +0,15 % | +51 € |
| dito ohne „nachgehinkt“-Filter, Stop 1,5 % | 386 | **−0,26 %** | −5.000 € |

Zwei Nebenbefunde zum Bau:

1. **Der Monitor hungert den Bot aus.** Er speichert schon Bewegungen ab 0,3 % (auch nach unten) und sperrt danach
   5 Minuten. Ein Sprung wird als „≥ 0,5 %“ gemeldet nur, wenn BTC innerhalb eines 2-Sekunden-Takts von unter 0,3 % auf
   über 0,5 % springt. Deshalb sieht der Bot mit „mindestens 0,5 %“ nur 29 statt rund 400 solcher Sprünge im Jahr.
   Ändern lohnt aber nicht – mit allen 400 verliert er (siehe letzte Zeile).
2. **Tempo hilft nicht.** Einstieg 2, 5, 10, 30 oder 60 Sekunden nach der Erkennung ergibt bei den neun nachgehinkten
   Fällen ab 0,5 % zwischen +0,14 % (2 s) und −0,35 % (30 s) je Trade – Rauschen um Null; es gibt keine Bewegung, die
   man mit mehr Tempo einfangen könnte.

## 5. Vorhersage gegen Ergebnis

In `docs/btc-eth-verbindung.md` war die Vorhersage für L1: „Korrelation ja, aber kein Gewinn nach Kosten, Vorsprung
höchstens Sekunden“. Der Minuten-Backtest schien das zu widerlegen; der Sekunden-Backtest bestätigt die ursprüngliche
Vorhersage. Die Lehre: Ein Effekt, der innerhalb einer Minute spielen soll, darf nicht mit Minutenkerzen getestet
werden.

## 6. Was zu tun ist

- **Kein echtes Geld** in den Lead-Lag-Bot. Der Paper-Bot „Lead-Lag ETH (Paper)“ kann als kostenlose Live-Messung
  weiterlaufen, wird aber nach diesem Ergebnis in den meisten Monaten keinen einzigen Trade machen.
- Die Beschreibung der Strategie in der App („Backtest ETH-EUR 2021–2026: +0,4 bis +0,7 % je Signal“) ist nach diesem
  Ergebnis falsch und sollte korrigiert werden; alternativ die Strategie als Experiment kennzeichnen oder entfernen.
- Die Live-Messung (`GET /api/research/leadlag`) hatte bis zum Abend des 9. Oktober noch kein einziges Ereignis
  (Start 12:37 UTC, 2 Neustarts, keine Fehler). Sie bleibt der einzige Weg, den Revolut-X-Spread und ein eventuelles
  Nachhinken **dort** zu messen – erwartbar ist nach den Binance-Daten aber nichts.
- Der Rest-Effekt bei Sprüngen ≥ 1 % ist der Erholungsschub an Crash-Tagen. Wer den will, ist mit dem untersuchten
  „Crash-Käufer“ (1-Stunden-Rendite ≤ −3,5 Standardabweichungen, 24 h halten) besser bedient als mit einem Bot, der auf
  die Sekunde reagieren muss.

## 7. Wie könnte er profitabel werden?

Nachgeprüft am 9. Oktober 2026 (Abend), gleiche Daten und Kosten wie oben. Alle Varianten hier wurden **nach** dem
Ergebnis gesucht (36 Kombinationen aus Richtung, Schwelle, Haltedauer, Marktlage) – also mit Vorsicht lesen.

**Nicht über Nachhinken.** Ohne Kosten (Maker-Orders, kein Spread) bleibt die Variante „≥ 0,7 %, nachgehinkt“ ohne ihre
fünf besten Trades bei +0,07 % (2021–23) bzw. −0,87 % (2024–26) je Trade. Mehr Tempo bringt nichts (Abschnitt 4).
Der Filter „Coin hinkt nach“ ist zu streichen, nicht zu verfeinern.

**Was auf den Daten Geld zeigt: große BTC-Sprünge in Crash-Phasen – in beide Richtungen.** Regel: BTC-USDT bewegt
sich in einer Minute um mindestens 1,5 % (egal ob rauf oder runter), **und** BTC steht mindestens 8 % unter seinem
7-Tage-Hoch; dann den Coin zum nächsten Kurs kaufen und 60 Minuten halten, kein enger Stop. Ohne die Crash-Bedingung
(„ruhige Lage“) bleibt von allem fast nichts (+0,1 bis +0,4 %, ohne Top-Trades negativ).

ETH-EUR 2021–2026, 5.000 € je Trade, Kosten 0,28 %:

| Regel | Trades/Jahr | netto je Trade | ohne die 5 besten | Gewinnquote | t-Wert | €/Jahr | Jahre |
|---|---|---|---|---|---|---|---|
| BTC **−1,5 %** in 1 min, Crash-Phase, 60 min | 9 | **+1,62 %** | +0,81 % | 74 % | 3,2 | +750 | 2021 +1,8 · 2022 −0,3 · 2023 +1,0 · 2024 +3,2 · 2025 +3,4 · 2026 +5,9 (1 Trade) |
| dito, 4 h halten | 9 | +2,02 % | +1,05 % | 70 % | 3,3 | +870 | 2022 +0,7, sonst alle positiv |
| BTC **+1,5 %** in 1 min, Crash-Phase, 60 min | 12 | +1,52 % | +0,82 % | 55 % | 3,1 | +940 | alle positiv außer 2026 (2 Trades, −0,1) |
| BTC ±1,0 %, Crash-Phase, 60 min | 57 | +0,61 % | +0,43 % | 56 % | 3,2 | +1.730 | 2022 −0,4, sonst positiv; größter Rückgang −2.700 € |
| BTC −1,5 %, Crash-Phase, 60 min, Stop 3 % | 10 | +1,42 % | +0,45 % | 64 % | 2,2 | +740 | Stop kostet auch hier |
| zum Vergleich: ±1,0 %, **ruhige Lage**, 60 min | 19 | +0,08 % / −0,11 % | negativ | 48 % | 0,5 / −0,6 | ≈ 0 | – |

Auf den Sekundendaten (Oktober 2025 bis September 2026, rollierendes 60-s-Fenster) zeigt sich dasselbe: nach BTC
−1,0 % in 60 s steigt ETH-EUR in der nächsten Stunde um +1,66 % (23 Fälle), nach +1,0 % um +0,36 % (45 Fälle);
unter 1 % bleibt nichts.

**Dieselbe Regel auf anderen Coins** (BTC −1,5 % in Crash-Phase, 60 min): 2021–26 ETH-USDT +1,33 %, BTC-EUR +0,85 %;
2024–26 (nur 9 Signale, dieselben Tage) SOL +4,5 %, ADA +3,2 %, SUI +2,8 %, LINK +2,4 %, AVAX +2,4 %, DOGE +2,3 %,
XRP +1,7 %, LTC +0,3 % – ohne die drei besten Trades noch 8 von 11 positiv. Die Variante „BTC +1,5 %“ lebt bei den
Altcoins dagegen fast nur vom 10. Oktober 2025 (ein Trade mit +50 bis +120 %, weil die dünnen Binance-EUR-Paare dort
ins Leere gefallen waren – auf Revolut X so nicht handelbar); ohne ihre Top-Trades bleibt sie bei 0 bis +0,5 %.

**Einordnung.**

- Das ist kein Lead-Lag mehr, sondern der **Erholungsschub nach Flash-Moves in Abwärtsphasen** – der minutengenaue
  Verwandte des „Crash-Käufers“ aus `docs/daytrading-forschung.md` (1-h-Rendite ≤ −3,5 Standardabweichungen, 24 h
  halten), der dort vorab angemeldet und auf ungesehenen Daten bestätigt wurde. Diese Variante hier ist nachträglich
  gefunden; die Bestätigung ist nur, dass sie in 5 von 6 Jahren, in beide Richtungen und auf 10 von 11 Coins hält.
- **Wenige Trades** (9–12 im Jahr bei 1,5 %, 57 bei 1,0 %), das Geld ist 99 % der Zeit unbeschäftigt; 750–1.700 € im
  Jahr auf 5.000 € sind 15–35 % auf den Einsatz, aber nur, wenn der Einsatz sonst nichts verpasst.
- **Ausführung ist leicht**, kein Sekundentempo nötig: der 30-Sekunden-Takt reicht, der Einstieg zum nächsten
  Minutenkurs ist eingerechnet. Unbekannt bleibt der Revolut-X-Spread in genau diesen Minuten – in Crash-Minuten ist
  er sicher breiter als die angenommenen 0,1 % je Runde.
- 2022 (Bärenmarkt mit langen Abwärtswellen) war das schwächste Jahr: Flash-Moves nach unten gingen dort öfter weiter.
  Ein Jahr wie 2022 kann also leicht ins Minus laufen.

**Falls gebaut:** Strategie „Flash-Move-Käufer“ statt Lead-Lag – Auslöser |BTC 60 s| ≥ 1,5 % aus dem vorhandenen
Monitor, Bedingung BTC ≥ 8 % unter 7-Tage-Hoch (4-h-Kerzen reichen), Kauf per Market, Verkauf nach 60–240 Minuten,
kein Stop unter 3 %. Erst Paper, und dort vor allem den Spread in den Signalminuten mitschreiben.
