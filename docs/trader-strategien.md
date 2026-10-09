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

## Teil 2 – Ergebnisse (nach dem Test geschrieben)

Gerechnet am 2026-10-09 nach dem Commit von Teil 1. „×“ = Endvermögen als Vielfaches des Einsatzes, Binance-Tageskerzen
2017-08-17 bis 2026-10-08, 0,2 % Kosten je Runde.

### Alle Regeln auf einen Blick

| Regel (Trader) | BTC × · Rückgang | ETH × · Rückgang | 2022–26 BTC / ETH | Trades · Treffer |
|---|---|---|---|---|
| Halten | ×19,1 · −83 % | ×8,2 · −94 % | ×1,77 / ×0,67 | – |
| **Momentum-Trendfolger M6 (unser Bot, Vergleich)** | **×38,4 · −54 %** | **×29,0 · −54 %** | **×1,87 / ×1,84** | täglich angepasst |
| T1a Angst-Kauf bei Fear & Greed ≤ 15 (GCR) | ×1,1 · −61 % | ×0,5 · −85 % | ×0,59 / ×0,40 | 18 · 33 % |
| T1b Kauf bei negativem Funding (GCR) | ×5,2 · −45 % | ×0,7 · −74 % | ×1,00 / ×0,42 | 24 · 71 % / 22 · 55 % |
| T2 Deviation unter das 30-Tage-Tief (CryptoCred, Mayne) | ×0,4 · −73 % | ×0,1 · −92 % | ×0,45 / ×0,36 | 77 · 23 % |
| **T3 Ausbruch über das 30-Tage-Hoch, raus unter 15-Tage-Tief (Pentoshi, Kaleo)** | **×26,7 · −62 %** | **×20,3 · −64 %** | ×1,18 / ×1,21 | 34 · 44 % |
| T4 Retest nach dem Ausbruch (Kaleo) | ×43,4 · −51 % | ×20,8 · −57 % | ×1,36 / ×1,50 | 29 · 45 % |
| T5 Bull-Market-Support-Band (Rekt Capital, Cowen) | ×2,9 · −76 % | ×7,3 · −78 % | ×2,05 / ×1,05 | wöchentlich |
| T5b Band + Teilverkauf bei +40 % (Cowen) | ×2,2 · −70 % | ×6,5 · −64 % | ×2,16 / ×1,18 | wöchentlich |
| T6 Halving-Zyklus (Rekt Capital, Loukas), BTC ab 2011 | ×420.605 (Halten ×272.440) · −82 % | ×107.398 (Halten ×2.688) · −68 % | ×6,9 / ×3,5 | 4 Zyklen |
| T7 DCA-Bot, EUR 2020–26 (3Commas-Stil) | ×8,1 (Halten ×11,2) · −70 % | ×18,5 (Halten ×19,7) · −71 % | – | 494 / 715 · 100 % |

### Was die Regeln zeigen

- **Konträre Angst-Käufe (GCR) funktionieren als Regel nicht.** Fear & Greed ≤ 15 kaufte 2018 viermal in den
  fallenden Markt und 2022 zweimal – zwei Drittel der Käufe nach 60 Tagen im Minus. Negatives Funding hat bei BTC
  2019–2021 gut funktioniert (71 % Treffer), seit 2022 nicht mehr, bei ETH nie. Was GCR wirklich tat –
  einschätzen, wann die Masse falsch liegt –, ist kein Schwellenwert. Den brauchbaren Kern hat unser Momentum-Bot
  schon: Die Funding-Untergrenze in M6F hält bei Panik-Funding eine halbe Position.
- **Range-Deviations (CryptoCred, Mayne) verlieren klar**, auch auf Tageskerzen: 77 Trades, 23 % Treffer, Endvermögen
  ×0,4. Ein Stich unter das 30-Tage-Tief ist in Krypto öfter der Beginn eines Abwärtstrends als eine Falle.
- **Ausbrüche (Pentoshi, Kaleo) sind die einzige Trader-Regel mit robustem Gewinn.** Alle neun Varianten (Ausbruch
  über das 20-/30-/55-Tage-Hoch, Ausstieg unter das 10-/15-/20-Tage-Tief) lagen auf beiden Coins über oder nahe
  Halten, bei etwa zwei Dritteln des Rückgangs (BTC ×15–40, ETH ×12–38). Auf den alten Daten, die nie in einem Test
  vorkamen (BTC 2011–2017), schlugen 4 von 9 Varianten das Halten bei −64 bis −74 % statt −93 % Rückgang. Bei ETH
  2016–17 (×327 Halten in 20 Monaten) blieben sie darunter.
- **Der Retest (T4) war Glück der gewählten Zahlen:** In den Nachbar-Varianten oft schlechter als der einfache
  Ausbruch, auf den alten BTC-Daten ×13–40 statt ×3.655–28.227. Die Wartezeit auf den Retest verpasst die großen
  Läufe.
- **Das Bull-Market-Support-Band ist zu langsam.** Es steigt nach dem Hoch ein (BTC Ende Dezember 2017 bei 13.716 $)
  und wird in Seitwärtsphasen hin- und hergeschüttelt. Seit 2022 bei BTC gut (×2,05 gegen ×1,77), insgesamt weit
  unter Halten.
- **Der Halving-Zyklus sieht fantastisch aus, ist aber kein Beweis.** Die Regel ist aus genau diesen vier Zyklen
  abgeleitet. Mit vier Datenpunkten lässt sich jedes Muster finden; wer 2025 auf den Zyklus-Ausstieg gesetzt hat,
  hat die Zahlen nicht aus dem Backtest, sondern aus dem Glauben, dass es wieder so kommt.
- **Der DCA-Bot gewinnt jeden Zyklus (100 %), verliert aber gegen Halten.** Ein Zyklus hing 834 Tage fest (BTC),
  der Rückgang lag bei −70 %. Die hohe Trefferquote, mit der solche Bots beworben werden, kommt von kleinen
  Gewinnzielen und großen, nicht realisierten Verlusten.
- **Hyperliquid-Wale** lassen sich nicht nachbauen: Positionen sind nur ab heute sichtbar, die größten Gewinner
  handeln mit Hebel und short, und nach einer Auswertung haben die meisten Achtstelligen unter 200 % Rendite – sie
  hatten vor allem viel Kapital.

### Mischungen mit dem Momentum-Bot

| | BTC × · Rückgang | ETH × · Rückgang |
|---|---|---|
| M6 allein | ×38,4 · −54 % | ×29,0 · −54 % |
| 50 % M6 + 50 % Ausbruch T3 | ×33,4 · −58 % | ×26,6 · −57 % |
| 70 % M6 + 30 % Funding-Kauf T1b | ×24,7 · −43 % | ×12,6 · −42 % |

Keine Mischung schlägt den Momentum-Bot allein.

### Vorhersage gegen Ergebnis

| # | Vorhersage | Ergebnis |
|---|---|---|
| T1a | wenige Trades, fast alle im Plus | **falsch** – 18 Trades, nur 33 % im Plus |
| T1b | Ø +5–10 % je Trade | BTC ja (+8,4 %), ETH **falsch** (+1,8 %, Endvermögen ×0,7) |
| T2 | kleines Plus | **falsch** – klarer Verlust |
| T3 | nahe Halten bei halbem Rückgang | ja, eher besser (über Halten, zwei Drittel des Rückgangs) |
| T4 | schlechter als T3 | in der gewählten Variante falsch, über die Nachbarn hinweg richtig |
| T5 | leicht unter Halten | **falsch** – weit darunter |
| T5b | unter T5 | ja bei BTC, bei ETH fast gleich |
| T6 | sehr gut, aber wertlos | ja |
| T7 | > 90 % Treffer, großer Rückgang, unter Halten | ja |

Die Gesamterwartung „Trendfolger bringen Gewinn, keiner schlägt den Momentum-Trendfolger“ stimmte. Die konträren
Käufe, die ich für die beste Ergänzung hielt, waren die größte Enttäuschung.

### Fazit

Hinter den erfolgreichen Krypto-Tradern steckt, soweit sich ihre Methoden als Regel fassen lassen, vor allem eines:
**mit dem Trend auf hohen Zeitebenen gehen, Ausbrüche kaufen, raus, wenn der Trend bricht.** Genau das macht der
Momentum-Trendfolger schon – mit sechs Zeitfenstern statt einem, mit Volatilitätsdeckel und Funding-Untergrenze, und
deshalb besser als jede einzelne Trader-Regel hier. Was die bekanntesten Namen darüber hinaus auszeichnet
(GCRs Gespür für Stimmung, Hsakas Orderflow, Cobies frühe Investments), steckt nicht in einer Regel, und ihre
öffentlichen Erfolge sind nicht geprüft.

**Empfehlung:** kein neuer Bot. Den Momentum-Trendfolger weiterlaufen lassen. Wer eine zweite, unabhängige Regel
daneben will, nimmt den einfachen Ausbruch (30-Tage-Hoch rein, 15-Tage-Tief raus) – er hat mehr Rückgang und weniger
Ertrag, aber andere Ein- und Ausstiegszeitpunkte.

### Grenzen

- Tagesschlusskurse, 0,2 % Kosten je Runde; Stops auf Tageskerzen zum Stop-Kurs.
- USDT statt EUR (Wechselkurs ausgeblendet), ein Coin je Bot, kein Zins auf Cash.
- Die Regeln sind meine Fassung der Trader-Stile; die Trader selbst entscheiden mit Ermessen.
- M6 ist hier eine tägliche Vereinfachung ohne Funding-Untergrenze; der echte Bot (M6F) lag in früheren Tests höher.
