# KI-Swingtrader (Claude Fable 5.1) für Revolut X

Stand 2026-10-09, ab DipAgentX 1.36.0. Strategie `ai` („KI-Swingtrader“, bis 1.35 „KI-Daytrader“). Keine Anlage-
und keine Steuerberatung. Ob der Bot Gewinn macht, ist nicht garantiert – siehe [Grenzen](#grenzen-und-risiken).

## Kurzfassung

Claude Fable 5.1 handelt ein Paar (z. B. ETH-EUR) mit den Einstiegen eines Daytraders, hält die Trades aber wie ein
Swingtrader – Stunden bis Tage. Die Regeln stammen aus einem Backtest genau dieses Playbooks auf sechs Jahren
ETH-EUR- und BTC-EUR-Daten (Abschnitt [Backtest](#backtest-was-in-der-vergangenheit-funktioniert-hat)):

1. **Nur im richtigen Regime:** 4-h-Trend aufwärts und ein trendender 1-h-Chart (ADX14 ≥ 25). Außerhalb wartet der Bot.
2. **Nur Setups, die Geld verdient haben:** Ausbruch über das 2-h- oder 24-h-Hoch mit Volumen, Rücksetzer an die
   15-min-EMA20 oder den VWAP im 1-h-Aufwärtstrend. Umkehr nach Ausverkauf und Range-Unterkante haben verloren.
3. **Stop unter dem letzten 1-h-Swing-Tief** (etwa 3 % entfernt), nie in der 5-Minuten-Unruhe. Enge Stops an der
   5-Minuten-Struktur haben in jeder Variante verloren.
4. **Ziel 3R** (das Dreifache des Risikos). Unter 2R hat es sich nicht gelohnt.
5. **Laufen lassen:** kein Stop auf Einstand, kein Trailing-Stop, kein Zeitlimit nach wenigen Stunden – all das hat
   das Ergebnis im Backtest halbiert oder zerstört. Vorzeitig geschlossen wird nur, wenn der Grund weg ist (1-h-Trend
   dreht, solange der Trade unter +1R steht).
6. **Claude sieht den Chart als Bild** und die Zahlen dahinter – und die Backtest-Bilanz jedes Setups als Vorwissen,
   dazu die eigene Live-Bilanz.
7. **Disziplin im Code:** Max. Stop-Abstand, Tagesverlust-Limit, Pause nach Verlustserie, kein Kauf ohne Stop,
   Positionsgröße nach Qualität.
8. **Ein Scanner weckt Claude** nur bei den getesteten Setups im getesteten Regime (etwa 700 Weckrufe im Jahr statt
   6.000) – das spart API-Budget.
9. **Nur gebührenfreie Limit-Orders.** Was nicht ausgeführt wird, wird storniert, nie zum Marktpreis gehandelt.
10. **Monatsbudget für die API** (Standard 50 $).

## Backtest: Was in der Vergangenheit funktioniert hat

### Daten und Methode

- Binance ETH-EUR und BTC-EUR, 5-Minuten-Kerzen, 3. Januar 2020 bis 30. September 2026 (je 708.786 Kerzen). Revolut X
  hat keine so lange Historie; die Kurse sind praktisch identisch, nur das Volumen ist dort kleiner.
- Nachgebaut wurde genau das, was der Bot selbst rechnet (`ai_analysis.py`): Trend je Zeitebene aus EMA20/EMA50,
  Steigung und Swing-Struktur, RSI, ADX, ATR, VWAP seit 0 Uhr UTC, relatives Volumen, 2-h-Hoch/-Tief, Swing-Tiefs.
- Claudes Entscheidung lässt sich nicht testen (das Modell kennt die Vergangenheit). Getestet wurde deshalb der
  **mechanische Kern**: Jedes Scanner-Signal wird gekauft, und der Plan des Bots läuft wie im Code – Limit-Kauf zum
  letzten Schlusskurs (gefüllt, wenn der Kurs ihn in den nächsten zehn Minuten berührt, sonst storniert), Stop und
  Ziel, Break-even und Trailing ab +1R, Zeitlimit. Eine Position zur Zeit, Gebühr 0 % (Maker), Stop-Verkäufe 0,05 %
  unter dem Stop (die Limit-Order läuft dem Kurs hinterher). Je Trade 100 % des Betrags, Gewinne reinvestiert.
- Getestet: 6 Setups × 9 Filter × 5 Stop-Arten × 4 Ziele (1.620 Varianten je Coin), danach 1.680 Varianten der
  Swing-Version. Aufgeteilt in 2020–21, 2022–23 und 2024–26, um Zufallstreffer zu erkennen.

### Ergebnis 1: Intraday verliert – in jeder Variante

Mit Stops an der 5-Minuten-Struktur (oder 1,5–3 ATR), Zielen von 1,5–3R, Stop auf Einstand ab +1R und Zeitlimits von
wenigen Stunden war **kein einziges Setup profitabel** – weder auf ETH noch auf BTC, in keinem Zeitabschnitt:

| Setup (Intraday-Plan, Stop 5-min-Struktur, Ziel 2R) | ETH: Trades, Trefferquote, Ø R | BTC: Trades, Trefferquote, Ø R |
|---|---|---|
| Ausbruch über 2-h-Hoch mit Volumen | 4.277 · 26 % · −0,08 | 4.059 · 24 % · −0,16 |
| Momentum (Ausbruch + 15m/1h aufwärts) | 1.443 · 26 % · −0,09 | 1.416 · 24 % · −0,14 |
| Pullback an EMA20/VWAP im 1-h-Aufwärtstrend | 7.510 · 25 % · −0,34 | 7.949 · 24 % · −0,46 |
| Kapitulation (RSI 15m < 30, Umkehrkerze, 2× Volumen) | 1.679 · 23 % · −0,21 | 1.757 · 23 % · −0,25 |
| Volumenspitze (3×) | 6.257 · 25 % · −0,17 | 6.134 · 24 % · −0,24 |
| Range-Unterkante | 3.933 · 25 % · −0,40 | 4.916 · 24 % · −0,53 |
| **Zufällige Einstiege** (gleicher Plan) | 3.841 · 25 % · −0,24 | 3.903 · 25 % · −0,31 |

Lesart: Die Setups sind besser als Zufall (Momentum −0,09 R gegen −0,24 R), aber nicht gut genug, um Spread und
Stop-Slippage zu bezahlen. Was Intraday am meisten kostete: der Stop auf Einstand (ein Drittel der Trades endete bei
null, kurz bevor der Kurs weiterlief), enge Stops in der 5-Minuten-Unruhe (Risiko ~1 %, Slippage 0,1 % = 0,1 R je
Stop) und Ziele vor dem nächsten Widerstand, die das Verhältnis Gewinner/Verlierer nicht tragen.

### Ergebnis 2: Dieselben Einstiege als Swing-Trade verdienen Geld

Von allen Stop-Arten war nur eine im Mittel positiv: **unter dem letzten 1-Stunden-Swing-Tief** (minus ¼ ATR 1h,
mindestens 1 ATR 5m, gedeckelt). Damit werden aus den Daytrades Swing-Trades mit etwa 3 % Risiko und Haltezeiten
von einem bis mehreren Tagen. Regel, die der Bot jetzt umsetzt („Basis“):

> Alle vier Trend-Setups (Pullback, Momentum, 2-h-/24-h-Ausbruch) · nur bei 4-h-Trend aufwärts **und** ADX14 (1 h)
> ≥ 25 · Stop unter dem 1-h-Swing-Tief, max. 5 % · Ziel 3R · kein Break-even, kein Trailing, kein Zeitlimit.

| | ETH-EUR | BTC-EUR |
|---|---|---|
| Trades 2020-01 bis 2026-09 (je Jahr) | 374 (56) | 291 (43) |
| Trefferquote | 28 % | 31 % |
| Ø Ergebnis je Trade | **+0,58 %** (+0,09 R) | **+0,75 %** (+0,19 R) |
| Profitfaktor (Gewinne / Verluste) | 1,28 | 1,44 |
| Ergebnis bei 100 % des Betrags je Trade, reinvestiert | **×4,3** | **×5,6** |
| Coin halten (Vergleich) | ×20,6 | ×11,4 |
| Größter Rückgang (Betrag) | −51 % | −48 % |
| Coin halten | −77 % | −77 % |
| Mittlere Haltezeit (Median) | 18 h | 25 h |
| Ausstiege | 269 Stop · 105 Ziel | 202 Stop · 89 Ziel |
| Bootstrap: Wahrscheinlichkeit, dass der Schnitt ≤ 0 ist | 4 % | 1,3 % |

Je Jahr (Summe der Trade-Ergebnisse in % des Betrags):

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (bis Sept.) |
|---|---|---|---|---|---|---|---|
| ETH | +59 | +86 | +12 | +29 | +2 | +14 | +14 |
| BTC | +106 | +24 | **−39** | +82 | +38 | −3 | +10 |

Je Setup (Swing-Plan, ETH / BTC: Trades · Trefferquote · Ø R · Ø %):

| Setup | ETH | BTC |
|---|---|---|
| Pullback an 15m-EMA20/VWAP im 1-h-Aufwärtstrend | 172 · 27 % · +0,05 · +0,50 | 145 · 31 % · +0,21 · +0,64 |
| Momentum (2-h-Ausbruch, 15m und 1h aufwärts) | 90 · 31 % · +0,24 · +0,49 | 68 · 31 % · +0,22 · +1,14 |
| Ausbruch über 24-h-Hoch | 12 · 50 % · +0,99 · +3,52 | 11 · 64 % · +1,54 · +4,33 |
| 2-h-Ausbruch ohne 15m-Aufwärtstrend | 100 · 24 % · −0,07 · +0,43 | 67 · 24 % · −0,11 · −0,01 |

Robustheit (Basis = ETH ×4,3 / BTC ×5,6):

| Änderung | ETH | BTC | Bewertung |
|---|---|---|---|
| ADX-Schwelle 20 / 30 statt 25 | ×4,2 / ×2,0 | ×5,3 / ×5,7 | Plateau 20–30 |
| nur 4-h-Trend, ohne ADX | ×5,1 | ×3,9 | geht auch, mehr Trades |
| Max. Stop 4 % / 6 % / 8 % | ×4,9 / ×7,3 / ×6,0 | ×3,8 / ×4,2 / ×5,3 | 5–8 % ähnlich; 3 % kostet ein Drittel |
| Ziel 2,5R / 3,5R / 4R | ×4,5 / ×4,5 / ×8,1 | ×4,5 / ×4,7 / ×7,1 | 2,5–4R alles positiv, 4R selten gefüllt |
| **Stop auf Einstand ab +1R** | ×2,3 (DD −35 %) | ×6,3 (DD −41 %) | halbiert ETH, senkt den Rückgang |
| Trailing-Stop 3–4 % ab +1R | ×1,5 | ×4,3 | schlechter |
| Zeitlimit 8 h, wenn unter +0,5R | ×0,8 | ×1,5 | zerstört die Strategie |
| 1-h-Trend dreht → schließen, wenn unter +1R | ×2,7 (DD −51 %) | ×6,6 (DD −30 %) | senkt Rückgang bei BTC; Claude darf das |
| Slippage 0 / 0,1 / 0,2 % statt 0,05 % | ×5,0 / ×3,8 / ×2,9 | ×6,2 / ×5,1 / ×4,2 | bleibt positiv |
| Claude reagiert 5 / 15 / 30 min später | ×3,6 / ×4,1 / ×6,4 | ×5,6 / ×4,9 / ×4,8 | Verzögerung unschädlich |
| Pullback nur an 15-min-Schlüssen (so im Scanner) | ×2,9 (46 Trades/J.) | ×3,8 (38/J.) | weniger Weckrufe, weniger Trades |
| Kapitulation und Range dazu | ×3,7 | ×10,1 | ETH schlechter, BTC besser – Claude entscheidet |
| Pause nach 3 Verlusten | ×4,7 | ×5,8 | neutral |

### Einordnung – ehrlich

- **Gegen den Momentum-Trendfolger (M6F+)** aus `docs/momentum-trendfolger.md` ist das schwach: ETH ×36 / BTC ×23 im
  selben Zeitraum bei ähnlichem Rückgang. Wer nur eine Strategie laufen lassen will, nimmt den Momentum-Bot.
- **Gegen Halten** liegt der Swing-Plan bei ETH klar zurück (×4,3 gegen ×20), bei BTC auf halber Höhe (×5,6 gegen
  ×11) – aber mit zwei Dritteln des Rückgangs und ohne das Jahr 2022 wie ein Halter zu erleben (ETH +12 %, BTC −39 %
  statt −66 %/−64 %).
- **Der Vorteil ist klein:** +0,6–0,75 % je Trade bei 3 % Risiko. Er verträgt die geprüften Slippage- und
  Verzögerungswerte, aber kaum mehr. Rund 50 Trades im Jahr; bei 1.000 € Einsatz sind das etwa 300–400 € Gewinn im
  Jahr – ein API-Budget von 50 $ im Monat (600 $ im Jahr) frisst das auf. **Unter etwa 2.000–3.000 € je Trade lohnt
  sich der Bot nach API-Kosten nicht.**
- **Was Claude dazutun kann** (und was der Backtest nicht zeigen kann): Setups ablehnen, die mechanisch gekauft
  worden wären (Widerstand direkt über dem Einstieg, BTC bricht gerade ein, Nachrichten), den Stop an ein echtes Level
  legen statt pauschal unter das Swing-Tief, und bei verlorenem Grund früher aussteigen. Was Claude nicht tun soll:
  intraday denken, enge Stops setzen, Gewinne „sichern“ – genau das hat verloren.
- **Mehrfachtest-Risiko:** Über 3.000 Varianten je Coin wurden angesehen. Die gewählte Regel liegt auf einem breiten
  Plateau (ADX 20–30, Ziel 2,5–4R, Stop 4–8 %), war in allen drei Zeitabschnitten und auf beiden Coins positiv und
  ist ökonomisch plausibel (Trendfolge über Tage). Trotzdem gilt: Vergangenheit ist kein Versprechen.

## Was einen guten Swingtrader ausmacht – und wie der Bot das umsetzt

| Prinzip | Umsetzung im Bot |
|---|---|
| Mit dem übergeordneten Trend handeln | Neue Longs nur bei 4-h-Trend aufwärts und ADX14 (1 h) ≥ 25 (`rules.backtested_regime_ok`); Scanner schweigt außerhalb |
| Wissen, in welcher Marktphase man ist | ADX, Effizienzquote, EMA-Lage und Hoch-/Tief-Struktur ergeben die Marktphase |
| An Levels handeln, nicht in der Mitte | Swing-Hochs/-Tiefs auf 15 min und 1 h als Zonen, VWAP, Vortageshoch/-tief/-schluss |
| Ein kleines Repertoire bewährter Setups | Playbook mit Backtest-Bilanz je Setup im Briefing (`backtest.by_setup`) |
| Bestätigung abwarten | Kerzenmuster der letzten drei Kerzen, relatives Volumen |
| Stop an der Invalidierung, außerhalb der Unruhe | `swing_plan.stop`: 1-h-Swing-Tief − ¼ ATR (1 h), mindestens 1 ATR (5 min), max. 5 % |
| Ziel, das die Verlierer bezahlt | `swing_plan.target_3r`; Prompt verlangt mindestens 2,5R |
| Positionsgröße nach Qualität | 25–100 % des Max. Betrags |
| Gewinne laufen lassen | Break-even und Trailing standardmäßig aus; kein Zeitlimit; Stop wird nie gesenkt |
| Verluste begrenzen, nicht „zurückholen“ | Tagesverlust-Limit und Pause nach Verlustserie – ohne Claude zu fragen |
| Kosten im Griff | Limit-Orders mit 0 % Maker-Gebühr; Scanner nur im Regime |
| Journal führen | Jeder Trade mit Setup, Ergebnis in % und R, bestem Kurs, Ausstiegsgrund; Statistik je Setup |

## Ablauf

```
alle 30 s (Engine-Tick)
 ├─ offene Position? → Plan ausführen: Stop / Ziel (Break-even / Trailing nur, wenn eingeschaltet), ohne Claude
 ├─ neue Position? → aus Claudes Plan Stop und Ziel relativ zum echten Einstieg setzen
 ├─ Disziplin: Tagesverlust-Limit oder Verlustserie → keine neuen Trades
 ├─ Budget aufgebraucht? → nur noch Plan ausführen
 ├─ neue 5-min-Kerze? → Scanner: Regime prüfen, Setups suchen
 └─ Claude fragen, wenn: Scanner-Signal · Preisalarm · große Bewegung · Zeitlimit · planmäßige Prüfung fällig
       → Briefing + Chart → Fable 5.1 → Entscheidung + Plan → Limit-Order
```

## Was Claude sieht

### Der Chart als Bild

Claude bekommt bei jeder Prüfung ein Kerzenchart-Bild (960 × 900 Pixel, etwa 1 Cent pro Prüfung, abschaltbar) mit
drei Panels: 1-Stunden-Kerzen der letzten 3 Tage, 15-Minuten-Kerzen der letzten 24 Stunden, 5-Minuten-Kerzen der
letzten 3 Stunden. In jedem Panel grüne und rote Kerzen, Volumenbalken, EMA20 (orange), EMA50 (blau), VWAP seit
00:00 UTC (violett, intraday), die nächsten Unterstützungen und Widerstände (grau gestrichelt), bei offener Position
Einstieg (weiß gepunktet), Stop (rot) und Ziel (grün). Genaue Werte liest ein Sprachmodell aus einem Bild nicht
zuverlässig ab; deshalb gibt es dieselben Daten als Zahlen, und bei Widerspruch gelten die Zahlen. Das Bild wird ohne
Zusatzbibliothek erzeugt (`agent/app/strategies/ai_chart.py`).

### Das Briefing (Zahlen)

Nur abgeschlossene Kerzen werden ausgewertet; den aktuellen Kurs liefert der Ticker.

| Feld | Inhalt |
|---|---|
| `woken_by` | warum Claude gerade gefragt wird |
| `price`, `bid`, `ask`, `spread_pct` | Kurs und Spread |
| `market_phase` | Aufwärtstrend / Abwärtstrend (15 min und 1 h einig), gemischt, Range, „choppy range“ |
| `changes_pct` | Veränderung über 15 min, 1 h, 4 h, 24 h, 72 h |
| `timeframes` | je 4h, 1h, 15m, 5m: Trend, Struktur, Lage zu EMA20/50, EMA20-Steigung, RSI14, ADX14, Effizienzquote, ATR14 in %, die letzten drei Kerzen in Worten |
| `levels_15m_24h`, `levels_1h_3d` | je drei Unterstützungen und Widerstände mit Berührungen und Abstand |
| `session` | Vortageshoch/-tief/-schluss, heutige Eröffnung, VWAP und Abstand |
| `volume_5m`, `bollinger_5m`, `order_book`, `market_leader` | Volumen, Squeeze, Orderbuch, BTC als Leitmarkt |
| `last_12_candles_5m_ohlcv` | die letzte Stunde als Zahlen |
| **`swing_plan`** | der getestete Stop (1-h-Swing-Tief − ¼ ATR), Abstand in %, Ziel 3R; Hinweis, wenn er über dem Max. Stop liegt |
| **`backtest`** | Zusammenfassung des Backtests und Bilanz je Setup (ETH und BTC) |
| `position` | Einstieg, Einsatz, Gewinn in % und R, Haltedauer, Hoch seit Einstieg, Setup, Ziel, Stop, Trailing, Zeitlimit |
| `your_notes`, `previous_decision` | Claudes Notizen und letzte Entscheidung |
| `performance` | Trades heute, Statistik der letzten 30 Trades gesamt und je Setup, letzte 8 Trades |
| `rules` | Max. Betrag, Wartezeit der Limit-Orders, Takt, Max. Stop, Break-even an/aus, Verlustverkauf erlaubt, Tageslimit, Mindestsicherheit, Maker-Gebühr 0 %, **`backtested_regime_ok`** |

Optional: Crypto Fear & Greed Index und bis zu drei Web-Suchen nach Nachrichten.

### Wie ein Aufwärtstrend erkannt wird

Je Zeitebene (`agent/app/strategies/ai_analysis.py`): **Aufwärts**, wenn EMA20 über EMA50, EMA20 steigt (über 5
Kerzen), Kurs über EMA50 und die Struktur nicht „tiefere Hochs und tiefere Tiefs“ ist; **abwärts** spiegelbildlich,
sonst **seitwärts**. ADX unter 18 macht daraus „up (weak)“. Das Regime für neue Käufe: 4-h-Trend beginnt mit „up“ und
ADX14 der 1-h-Kerzen ≥ 25.

## Das Playbook

| Setup | Idee | Backtest |
|---|---|---|
| `trend_pullback` | im 1-h-Aufwärtstrend ein Rücksetzer an die steigende 15m-EMA20 oder den VWAP, Verkaufsvolumen versiegt, 5-min-Kerze dreht | häufigstes Setup, auf beiden Coins positiv |
| `momentum` | 5-min-Schluss über dem 2-h-Hoch mit ≥ 1,5× Volumen, 15 min und 1 h aufwärts | bestes Risiko/Ertrag |
| `breakout` (24 h) | 5-min-Schluss über dem 24-h-Hoch mit Volumen | stärkstes Signal, selten |
| `breakout` (2 h, 15 min noch nicht aufwärts) / `breakout_retest` | Ausbruch ohne 15-min-Trend; besser der Retest | schwach – warten |
| `reversal` | Erschöpfung nach Ausverkauf und Rückeroberung eines Levels | hat verloren – nur mit Ausnahmegrund, 25 % |
| `range_support` | Unterkante einer Range hält | hat verloren – meiden |

Der Bot kann nur kaufen (Spot, kein Short, kein Hebel). Im Abwärtstrend heißt die Antwort „warten“.

## Wie Claude entscheidet

Der System-Prompt (`SYSTEM_PROMPT` in `agent/app/strategies/ai.py`) gibt den Prozess vor und nennt die
Backtest-Regeln als Begründung: Regime → Setup → Lage → Stop unter dem 1-h-Swing-Tief → Ziel 3R → Größe nach Qualität
→ laufen lassen → Rückblick. Claude antwortet als strukturiertes JSON: Aktion, Setup, Ziel, Stop, Größe,
Trailing-Abstand, Zeitlimit, Preisalarme, nächste Prüfung, Sicherheit, Notizen und Begründung (Englisch und Deutsch).
Lehnt Fable eine Anfrage ab, wiederholt die API sie auf dem empfohlenen Ersatzmodell.

## Was der Bot zwischen den Prüfungen selbst tut

Alle 30 Sekunden, ohne Claude: **Stop erreicht** (Geldkurs ≤ Stop) → Verkauf, auch mit Verlust. **Ziel erreicht** →
Verkauf. **Break-even** (ab +1R Stop auf Einstieg) nur, wenn eingeschaltet – Standard aus. **Trailing-Stop** nur,
wenn Claude `trail_pct` setzt. Der Stop wird **nie gesenkt** und liegt **nie weiter als der Max. Stop-Loss** vom
Einstieg. Claude sagt „verkaufen“ → die Limit-Order wird bis zur nächsten Prüfung immer wieder gestellt. Der Plan wird
relativ zum echten Einstiegskurs übernommen.

### Ausführung: nur Limit-Orders

Live geht jede Order als Post-only-Limit-Order einen Cent in den Spread (Maker-Gebühr 0 %). Läuft der Kurs weg, wird
die Order storniert und am neuen besten Kurs neu gestellt. Nach der Wartezeit (Standard 10 min) wird eine nicht
ausgeführte Order **storniert, nicht** zum Marktpreis ausgeführt. Bei Stop- und Zielverkäufen stellt der nächste Tick
sofort eine neue Limit-Order. Nur „Position jetzt verkaufen“ von Hand verkauft zum Marktpreis. Im Paper-Modus werden
Market-Orders simuliert.

## Wann Claude gefragt wird

**Scanner** – bei jeder neuen abgeschlossenen 5-min-Kerze, reine Rechenregeln ohne API-Kosten. Neue Käufe nur im
Regime (4 h aufwärts, ADX 1 h ≥ 25):

| Signal | Regel |
|---|---|
| Ausbruch 24 h | 5-min-Schluss über dem Hoch der letzten 24 Stunden, Volumen ≥ 1,5× |
| Momentum / Ausbruch 2 h | 5-min-Schluss über dem Hoch der letzten 2 Stunden, Volumen ≥ 1,5×; „Momentum“, wenn 15 min und 1 h aufwärts, sonst „Ausbruch (schwächer)“ |
| Pullback im Trend | 1-h-Trend aufwärts, 15 min nicht abwärts, Kurs nahe der 15-min-EMA20 (0,6 × ATR, mind. 0,15 %) oder des VWAP (0,2 %), 5-min-RSI < 50, grüne Kerze – nur am Schluss einer 15-Minuten-Kerze |
| Bruch nach unten | 5-min-Schluss unter dem 2-h-Tief mit Volumen – nur bei offener Position |

Kapitulation und Volumenspitze wecken Claude nicht mehr (Backtest negativ). Ein Signal weckt nur, wenn seit der
letzten Prüfung die Mindestzeit vergangen ist („Claude höchstens alle“, Standard 15 min), und verfällt nach 15 Minuten.
Im Backtest ergaben die Scanner-Regeln rund 700 Weckrufe im Jahr je Coin (ohne Regime-Filter wären es über 6.000).

**Weitere Weckgründe:** Claudes Preisalarme, eine Bewegung von mindestens 0,4 % bzw. 3 × 5-min-ATR seit der letzten
Prüfung, das Zeitlimit einer Position, „Jetzt fragen“ in der App. **Planmäßig** sonst nach dem Budget-Takt; Claude kann
mit `next_check_minutes` länger warten (bis 4 Stunden). **Denktiefe automatisch:** „mittel“ bei Signal, Alarm oder
offener Position, sonst „niedrig“.

## Disziplin-Regeln

| Regel | Standard | Wirkung |
|---|---|---|
| Max. Stop-Loss | 5 % | Stop nie weiter vom Einstieg; der getestete Stop liegt ~3 % entfernt, 4–6 % funktionierten, 3 % kostete ein Drittel |
| Stop auf Einstand ab +1R | aus | an: halbiert das Ergebnis, senkt den Rückgang |
| Kein Kauf ohne Stop | – | steht Max. Stop auf 0 und nennt Claude keinen Stop, wird nicht gekauft |
| Tagesverlust-Limit | 6 % des Max. Betrags | keine neuen Trades bis 00:00 UTC |
| Pause nach Verlusten in Folge | 3 Trades | 2 Stunden keine neuen Trades (im Backtest neutral) |
| Mindestsicherheit | 0 % (aus) | Käufe nur ab dieser Sicherheit |
| Claude darf mit Verlust schließen | an | aus: nur der Stop realisiert Verluste |

## Kosten und Budget

Fable 5.1 kostet 10 $ pro Million Eingabe-Tokens und 50 $ pro Million Ausgabe-Tokens. Eine Prüfung hat etwa 2.500
Tokens System-Prompt, 2.000 Tokens Briefing (mit Backtest-Bilanz) und 1.100 Tokens Chart-Bild plus Denken und
Antwort – **grob 0,10–0,20 $ pro Prüfung**, im Mittel etwa 0,13 $. Der Bot misst die echten Kosten.

Mit 50 $ im Monat sind das rund 380 Prüfungen, im Mittel etwa eine alle 2 Stunden; der Scanner verschiebt sie
dorthin, wo etwas passiert (etwa 60 Signale im Monat). Ist das Budget aufgebraucht, führt der Bot offene Positionen
weiter nach Plan. **Rechnung:** Der Backtest ergibt etwa +30–40 % des Einsatzes im Jahr (vor Zinseszins). Bei 1.000 €
je Trade sind das 300–400 €, das API-Budget kostet 600 $. Erst ab etwa 2.000–3.000 € je Trade bleibt nach API-Kosten
etwas übrig. Hebel: Budget senken (25 $ reichen, weil der Scanner selten weckt), Denktiefe „niedrig“, Chart aus,
Opus 5.5 statt Fable (ca. 40 % der Kosten).

## Einstellungen

| Einstellung | Standard | Bedeutung |
|---|---|---|
| Max. Betrag pro Trade | 50 | Claude nutzt 25–100 % davon |
| Modell | Claude Fable 5.1 | Opus 5.5, Sonnet 5.5, Haiku 5.5 wählbar |
| Denktiefe | Automatisch | niedrig / mittel / hoch fest |
| API-Budget pro Monat | 50 $ | pro Bot |
| Claude höchstens alle | 15 min | Mindestabstand, auch für Scanner und Alarme |
| Claude den Chart zeigen | an | Kerzenchart als Bild |
| Wartezeit für Limit-Orders | 10 min | danach Storno |
| Max. Stop-Loss | 5 % | |
| Stop auf Einstand ab +1R | aus | |
| Claude darf mit Verlust schließen | an | |
| Tagesverlust-Limit | 6 % | des Max. Betrags, 0 = aus |
| Pause nach Verlusten in Folge | 3 | 0 = aus |
| Mindestsicherheit | 0 % | |
| Nachrichten einbeziehen | aus | macht Prüfungen mehrfach so teuer |
| Fear-&-Greed-Index | aus | Hintergrund oder Kontrasignal an Extremen |
| Zusätzliche Anweisungen | – | eigene Regeln, z. B. „nur Pullbacks im Trend“ |

Voraussetzung: `ANTHROPIC_API_KEY` auf dem Agenten (Home Assistant: Option `anthropic_api_key`).

## Grenzen und Risiken

- **Der Backtest testet den mechanischen Kern, nicht Claude.** Ob Claudes Auswahl die mechanische Regel verbessert
  oder verschlechtert, zeigt erst der Paper-Betrieb. Der Vorteil der Regel selbst ist klein und kann verschwinden.
- **Long only.** In Abwärtsphasen wartet der Bot.
- **Rückgänge um 50 % des Einsatzes** kamen im Backtest vor (2022). Der Einsatz muss das aushalten.
- **Limit-only hat zwei Seiten:** keine Gebühren, aber manche Einstiege werden verpasst, und ein Stop-Verkauf in einem
  schnellen Absturz kann unter dem Stop landen.
- **Volumen und Orderbuch** kommen nur von Revolut X; das Volumen dort spiegelt den Gesamtmarkt nur teilweise.
- **API-Kosten** müssen erst verdient werden (siehe Rechnung oben).

## Empfehlung zum Start

1. Im **Paper-Modus** 1–3 Monate laufen lassen (Swing-Trades brauchen Zeit; 50 Trades im Jahr sind 4 im Monat).
2. Kennzahlen ansehen: Trefferquote um 30 %, Ø R positiv, Ergebnis nach API-Kosten, welche Setups funktionieren.
3. Live erst mit einem Betrag, bei dem der Backtest-Gewinn die API-Kosten deutlich übersteigt. Wer lieber die
   robuste Strategie will, nimmt den Momentum-Trendfolger.

## Code

| Datei | Inhalt |
|---|---|
| `agent/app/strategies/ai.py` | Strategie, Prompt, Plan, Budget, Disziplin, Wecken |
| `agent/app/strategies/ai_analysis.py` | Indikatoren, Trend, Struktur, Levels, Session, Volumen, Orderbuch, Regime, Swing-Stop, Scanner, Backtest-Bilanz |
| `agent/app/strategies/ai_chart.py` | Chart-Bild (PNG ohne Zusatzbibliothek) |
| `agent/app/engine.py` | `limit_only`: Limit-Orders ohne Market-Fallback |
| `agent/tests/test_ai.py` | Tests |
