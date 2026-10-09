# BTC und ETH: Wie hängen sie zusammen, und lässt sich daraus Gewinn machen?

Keine Anlageberatung. Backtests auf vergangenen Kursen.

## Teil 1 – Hypothesen und Vorhersage (geschrieben vor dem Backtest)

Geschrieben am 2026-10-09 und committet, bevor ein Test lief.

Die Idee: „ETH folgt BTC oft.“ Wenn BTC sich zuerst bewegt und ETH mit Verzögerung nachzieht, kann man ETH kaufen,
nachdem BTC gestiegen ist. Das kann auf verschiedenen Zeitebenen gelten:

| # | Hypothese | Regel | Vorhersage |
|---|---|---|---|
| L1 | **Minuten-Vorsprung:** BTC bewegt sich Sekunden bis Minuten vor ETH | BTC steigt in 1–5 min um ≥ x, ETH noch nicht → ETH kaufen, 5–15 min halten. Leader BTC-USDT (liquidester Markt), gehandelt ETH-EUR. Daten: 1-min 2024–2026 | Messbare Korrelation BTC → ETH für 1–2 Minuten, vor allem von USDT zu EUR. Gewinn je Trade aber unter 0,05 % – kleiner als der Spread; mit Limit-Orders praktisch nicht zu fassen (der Kurs läuft weg). **Kein Gewinn.** |
| L2 | **Stunden-/Tages-Vorsprung** | BTC-Rendite der letzten Stunde/des letzten Tages sagt die nächste ETH-Rendite voraus | Kein Zusammenhang (Korrelation ≈ 0) |
| L3 | **BTC als Signal für ETH** | ETH halten, wenn das Momentum-Signal (M6) von **BTC** an ist, statt von ETH selbst | Nicht besser als ETHs eigenes Signal (frühere Tests: BTC-Filter für ETH schlechter) |
| L4 | **ETH/BTC-Verhältnis mit Trend** | Halten, was im Verhältnis stärker ist (ETH/BTC über/unter seinem 30/60-Tage-Schnitt) | Schwach positiv gegenüber 50/50, aber nicht besser als Momentum je Coin |
| L5 | **Aufholen nach Abweichung** | Ist ETH in 24 h um mehr als 2 Standardabweichungen hinter BTC zurückgeblieben → ETH kaufen, 24–72 h halten (Paar-Logik) | Kein verlässliches Aufholen – ETH/BTC hat lange Trends. Kein Gewinn |

Gesamterwartung: **Der Zusammenhang ist sehr eng (Tageskorrelation ~0,8), aber gleichzeitig, nicht zeitversetzt.**
Ein Vorsprung von BTC existiert höchstens im Minutenbereich und ist für einen Bot mit Limit-Orders auf Revolut X
nicht nutzbar. Am ehesten bringt etwas das ETH/BTC-Verhältnis als langsamer Trend (L4).

## Teil 2 – Ergebnisse (nach dem Test geschrieben)

### Wie BTC und ETH zusammenhängen

| Jahr | Korrelation (Tag) | ETH-Beta auf BTC | Schwankung BTC / ETH | ETH gegen BTC im Jahr |
|---|---|---|---|---|
| 2018 | 0,82 | 1,09 | 84 % / 111 % | −37 % |
| 2019 | 0,82 | 0,98 | 68 % / 81 % | −51 % |
| 2020 | 0,87 | 1,14 | 81 % / 105 % | +40 % |
| 2021 | 0,78 | 1,05 | 81 % / 109 % | +220 % |
| 2022 | 0,90 | 1,22 | 64 % / 87 % | −8 % |
| 2023 | 0,83 | 0,89 | 44 % / 47 % | −25 % |
| 2024 | 0,80 | 0,97 | 53 % / 64 % | −33 % |
| 2025 | 0,82 | 1,47 | 42 % / 74 % | −5 % |
| 2026 | 0,91 | 1,23 | 46 % / 62 % | −10 % |

ETH bewegt sich fast immer **gleichzeitig** mit BTC, im Schnitt etwa 1,1-mal so stark und deutlich schwankender. Gegen
BTC hat ETH seit 2022 jedes Jahr verloren. „ETH folgt BTC“ stimmt im Sinn von „gleiche Richtung“, aber nicht im Sinn
von „später“ – mit einer Ausnahme im Minutenbereich (L1).

### L2 – Vorsprung über Stunden oder Tage: keiner

Korrelation der BTC-Rendite mit der **nächsten** ETH-Rendite (EUR, 2020–2026): 5 min +0,004, 1 h −0,010, 1 Tag
−0,071. Gleichzeitig: 0,77 / 0,83 / 0,83. Es gibt keinen nutzbaren Vorsprung ab 5 Minuten aufwärts. Vorhersage
gestimmt.

### L3 – BTC-Signal für ETH (Tageskerzen 2017–2026)

| | Endvermögen | Rückgang | 2017–21 | 2022–26 |
|---|---|---|---|---|
| M6 auf ETH (eigenes Signal) | ×29,0 | −54 % | ×15,8 | ×1,84 |
| ETH mit BTC-Signal (gleiche ETH-Schwankung, fair) | ×39,9 | −63 % | ×21,8 | ×1,83 |
| ETH nur, wenn BTC- **und** ETH-Signal an sind | ×41,3 | **−40 %** | ×23,3 | ×1,77 |

Das BTC-Signal für ETH bringt mehr, aber nur 2017–21 und mit mehr Rückgang. Die Variante „nur, wenn beide an“
senkt den Rückgang deutlich (−40 % statt −54 %), seit 2022 bei etwas weniger Ertrag (×1,77 statt ×1,84). Kein klarer
Gewinn, eher ein Risiko-Regler. Vorhersage („nicht besser“) teilweise falsch.

### L4 – ETH/BTC-Verhältnis: Rotation in den stärkeren Coin

Momentum-Anteil wie beim Bot, aber angelegt in dem Coin, dessen Verhältnis ETH/BTC über bzw. unter seinem
n-Tage-Schnitt liegt:

| | Endvermögen | Rückgang | 2017–21 | 2022–26 |
|---|---|---|---|---|
| M6 je Coin 50/50 | ×39,4 | −49 % | ×20,4 | ×1,93 |
| Rotation 10 / 20 / 30 / 45 / 60 / 90 Tage | ×87 / ×93 / ×75 / ×83 / ×51 / ×42 | −46 bis −49 % | ×44 / ×57 / ×43 / ×41 / ×28 / ×27 | ×1,97 / ×1,62 / ×1,73 / ×2,02 / ×1,84 / ×1,53 |

Über die ganze Zeit sieht die Rotation stark aus, aber der Gewinn stammt aus 2017–2021 (vor allem dem ETH-Lauf
2021). Seit 2022 liegt sie je nach Fenster mal über, mal unter 50/50 – kein verlässlicher Vorteil mehr. Das deckt
sich mit dem früheren 4-h-Test („ETH/BTC-Rotation schlechter“).

### L5 – Aufholen nach Abweichung: keiner

Ist ETH in 24 h um mehr als 2 Standardabweichungen hinter BTC zurück, holt es in den nächsten 24–72 h nicht
verlässlich auf (z < −2: +0,32 % gegenüber BTC; z < −2,5: −0,15 %). Rauschen. Vorhersage gestimmt.

### L1 – Minuten-Vorsprung: **gefunden, und er hält auf ungesehenen Daten**

Leader BTC-USDT (der liquideste Markt), gehandelt ETH-EUR, 1-Minuten-Kerzen. Korrelation BTC(t) → ETH-EUR(t+1 min):
+0,048, nach 2 Minuten weg. Der Effekt ist klein im Schnitt, aber groß nach **großen** BTC-Sprüngen, wenn ETH-EUR
noch nicht mitgezogen hat:

> **Regel:** Steigt BTC-USDT in einer Minute um mindestens 0,5 % und ist ETH-EUR in derselben Minute um weniger als
> die Hälfte davon gestiegen → ETH-EUR kaufen, nach 15 Minuten verkaufen.

Gefunden auf 2024–2026, danach geprüft auf 2021–2023 (vorher nicht angesehen). Ø ETH-Bewegung nach dem Signal, vor
Kosten:

| BTC-Sprung | Daten | Signale/Jahr | sofort, 5 min | sofort, 15 min | 1 min später, 15 min | Limit gefüllt / Ø | Kontrolle: ETH schon mitgezogen, 15 min |
|---|---|---|---|---|---|---|---|
| ≥ 0,3 % | 2021–23 | 567 | +0,04 % | +0,14 % | +0,12 % | 93 % / +0,11 % | +0,10 % |
| ≥ 0,3 % | 2024–26 | 150 | +0,14 % | +0,25 % | +0,12 % | 77 % / +0,17 % | +0,07 % |
| ≥ 0,4 % | 2021–23 | 263 | +0,09 % | +0,24 % | +0,22 % | 94 % / +0,19 % | +0,15 % |
| ≥ 0,4 % | 2024–26 | 51 | +0,21 % | +0,44 % | +0,24 % | 85 % / +0,35 % | +0,10 % |
| **≥ 0,5 %** | **2021–23** | **139** | **+0,16 %** | **+0,40 %** | **+0,37 %** | 95 % / +0,32 % | +0,24 % |
| **≥ 0,5 %** | **2024–26** | **26** | **+0,37 %** | **+0,68 %** | **+0,47 %** | 90 % / +0,72 % | +0,14 % |
| ≥ 0,7 % | 2021–23 | 53 | +0,43 % | +0,83 % | +0,73 % | 93 % / +0,72 % | +0,40 % |
| ≥ 0,7 % | 2024–26 | 12 | +0,65 % | +1,12 % | +0,83 % | 97 % / +1,08 % | +0,22 % |

Je Jahr (≥ 0,5 %, sofort, 15 min): 2021 305 Signale Ø +0,48 %, 2022 61 · +0,16 %, 2023 50 · +0,23 %,
2024 49 · +0,30 %, 2025 18 · +1,64 %, 2026 (bis Sept.) 5 · +0,88 %. **Jedes Jahr positiv.**

Was das zeigt:

- **Je größer der BTC-Sprung, desto mehr zieht ETH nach** – in beiden Zeiträumen, bei jeder Schwelle.
- **Das Nachhinken zählt:** Hat ETH schon mitgezogen, steigt es danach weniger (Kontrolle). Ein Teil ist allgemeines
  Momentum nach großen BTC-Minuten, der größere Teil ist das Aufholen.
- **Geschwindigkeit zählt:** Eine Minute später ist ein Teil weg (bei ≥ 0,3 % fast die Hälfte, bei ≥ 0,5 % ein
  Viertel bis ein Drittel).
- **Nach Kosten** (Revolut X Taker 0,09 % je Seite plus Spread, ~0,25 % je Runde) bleiben bei ≥ 0,5 % rund
  +0,1 bis +0,4 % je Trade; bei ≥ 0,3 % bleibt nichts. Mit Limit-Order zum letzten Kurs wurden 90–95 % gefüllt, ohne
  dass der Schnitt schlechter wurde.
- **Selten:** 2024–2026 nur 26 Signale im Jahr bei ≥ 0,5 %, 51 bei ≥ 0,4 %. Bei 1.000 € Einsatz sind das grob
  50–150 € im Jahr. Das Geld ist dabei nur Minuten im Jahr investiert und kann die übrige Zeit anders arbeiten.

### Vorhersage gegen Ergebnis

| # | Vorhersage | Ergebnis |
|---|---|---|
| L1 | Korrelation ja, aber kein Gewinn nach Kosten | **falsch** – nach großen BTC-Sprüngen nutzbar, auf ungesehenen Daten bestätigt |
| L2 | kein Vorsprung über Stunden/Tage | richtig |
| L3 | BTC-Signal nicht besser | teilweise falsch – „beide Signale“ senkt den Rückgang deutlich |
| L4 | schwach positiv | über alles stark positiv, seit 2022 aber nicht mehr |
| L5 | kein Aufholen | richtig |

### Was das für einen Bot heißt

1. **„ETH folgt BTC“ gibt es nur im Minutenbereich**, und nutzbar nur bei großen, schnellen BTC-Sprüngen. Ein Bot
   dafür muss BTC live verfolgen (Binance-Websocket, öffentlich, ohne Key) und innerhalb von Sekunden ETH-EUR auf
   Revolut X kaufen. Der Agent prüft heute nur alle 30 Sekunden und hat keinen Live-Kurs von Binance – das wäre neu
   zu bauen.
2. **Offene Frage vor jedem Geld:** Hinkt ETH-EUR auf **Revolut X** genauso nach wie auf Binance? Revolut X ist
   kleiner; vermutlich ja, vielleicht stärker, vielleicht gleichen Market-Maker es in Sekunden aus. Das lässt sich nur
   live messen: erst ein paar Wochen im Paper-Modus die Signale und die Revolut-X-Kurse mitschreiben.
3. **Für den bestehenden Momentum-Bot:** siehe die genaue Nachprüfung in Teil 3. Die Aussage „weniger Rückgang bei
   etwa gleichem Ertrag“ hält mit dem echten Bot nicht; es bleibt ein Tausch Rückgang gegen Ertrag.
4. Die ETH/BTC-Rotation war bis 2021 ein Volltreffer und ist seitdem keiner mehr. Nicht einbauen.

### Grenzen

- Binance-Kurse. ETH-EUR ist dort ein dünnes Paar – ein Teil des Nachhinkens kann daher kommen, dass dort weniger
  gehandelt wird. Auf Revolut X kann das anders sein.
- 1-Minuten-Schlusskurse: Gekauft wird im Test zum Schlusskurs der Signalminute; in der Praxis kommt eine Order erst
  Sekunden später an. Die Spalte „1 min später“ ist die vorsichtige Schätzung.
- Die Schwelle 0,5 % wurde auf 2024–26 gewählt, dann auf 2021–23 bestätigt; alle Schwellen zeigen dasselbe Muster.

## Teil 3 – Genaue Nachprüfung: BTC-Signal als Bremse für den ETH-Bot

Die Aussage aus L3 („ETH nur so weit wie beide Signale: Rückgang −54 % → −40 % bei gleichem Ertrag“) stammte aus einer
vereinfachten Tagesrechnung in USDT ohne Funding-Untergrenze. Nachgeprüft mit dem **echten Bot**: 4-h-Schlusskurse
ETH-EUR/BTC-EUR, sechs Zeitfenster mit Einstieg +5 % / Ausstieg 0 %, Volatilitätsdeckel 100 %, Funding-Untergrenze
50 % unter 2 % p. a. (Binance, 7-Tage-Mittel), 10-%-Stufen, März 2020 bis September 2026. Der Nachbau trifft die
früheren Zahlen (ETH ×46, mit Deckel 80 % ×36 wie in `docs/momentum-trendfolger.md`).

### Drei Varianten für den ETH-Bot

| Regel | Endvermögen | Rückgang | 2020–21 | 2022–26 | 2024–26 | Ø investiert |
|---|---|---|---|---|---|---|
| ETH-Bot heute | ×46,3 | −39,9 % | ×11,6 | ×3,98 | ×3,26 | 55 % |
| ETH-Anteil = min(ETH-, BTC-Fenster), Untergrenze danach | ×41,4 | −35,8 % | ×11,0 | ×3,75 | ×2,97 | 47 % |
| **wie oben, und BTC darf auch die Untergrenze kippen** | ×42,9 | **−29,3 %** | ×10,4 | **×4,13** | ×3,12 | 44 % |
| Mittel aus ETH- und BTC-Fenstern | ×46,8 | −37,6 % | ×12,6 | ×3,70 | ×2,92 | 54 % |

Mit 0,09 % Gebühr je Trade sinken alle Werte um etwa 12 %, die Reihenfolge bleibt. „BTC darf die Untergrenze kippen“
heißt: Die ETH-Untergrenze bei Panik-Funding gilt nur, wenn auch BTC sie hätte (BTC-Funding unter 2 %) oder die
BTC-Fenster so weit oben sind.

**Die einfache Variante (nur min) lohnt nicht:** 11 % weniger Ertrag für 4 Punkte weniger Rückgang, und in jedem
Teilzeitraum weniger Ertrag. Die ursprüngliche Aussage war zu optimistisch.

### Die Variante mit BTC-Veto im Detail

| | ETH-Bot heute | mit BTC-Veto |
|---|---|---|
| Rendite pro Jahr | 79,3 % | 77,2 % |
| Größter Rückgang | −39,9 % (Aug.–Nov. 2022) | −29,3 % (März–Nov. 2024) |
| Zweit-/drittgrößter | −38 % (Aug. 2025–Feb. 2026), −36 % (Mai–Juni 2021) | −29 % (Feb. 2021), −26 % (Aug.–Nov. 2022) |
| Rendite / Rückgang (Calmar) | 1,99 | 2,64 |
| Sharpe | 1,20 | 1,40 |
| Schlechteste 12 Monate | −31 % | −19 % |
| Jahre 2020 / 21 / 22 / 23 / 24 / 25 / 26 | +152 / +362 / −4 / +27 / +57 / +63 / +27 % | +146 / +323 / +8 / +23 / +65 / +46 / +29 % |
| Rollierend 12 Monate besser | – | 58 % der Startzeitpunkte, im Schnitt −0,3 % |
| Schlimmster Rückstand in 12 Monaten | – | −51 % (Bullenlauf 2021) |

Über alle sechs Grundeinstellungen (Einstieg 2 / 5 / 8 %, Deckel 80 / 100 %) lag der Rückgang mit Veto bei −29 bis
−31 % statt −37 bis −40 %, und 2022–26 war das Endvermögen in allen sechs höher. 2020–21 war es in allen sechs
niedriger.

### Abhängigkeit von der Funding-Untergrenze (Einstieg 5 %, Deckel 100 %)

| Funding unter | Untergrenze | Rückgang heute → Veto | Endvermögen heute → Veto | 2022–26 heute → Veto |
|---|---|---|---|---|
| (ohne Untergrenze) | 0 % | −36 → −30 % | ×34 → ×28 | ×3,6 → ×3,4 |
| 0 % p. a. | 50 % | −38 → −29 % | ×53 → ×38 | ×4,5 → ×3,7 |
| **2 % p. a. (Standard)** | **50 %** | **−40 → −29 %** | **×46 → ×43** | **×4,0 → ×4,1** |
| 2 % p. a. | 30 / 70 % | −37 → −30 % / −43 → −30 % | ×39 → ×36 / ×59 → ×56 | ×3,8 → ×3,9 / ×4,5 → ×4,7 |
| 5 % p. a. | 50 % | −41 → −39 % | ×48 → ×48 | ×3,9 → ×4,5 |

Der kleinere Rückgang ist robust (bis auf die 5-%-Schwelle). Was er an Ertrag kostet, hängt stark von den
Einstellungen ab: bei den heutigen Standardwerten 7 %, bei einer Funding-Schwelle von 0 % fast 30 %.

### Der BTC-Bot mit ETH-Signal als Bremse

| | Endvermögen | Rückgang | 2022–26 | 12 Monate besser |
|---|---|---|---|---|
| BTC-Bot heute | ×24,2 | −30,5 % | ×3,18 | – |
| BTC: min(BTC-, ETH-Fenster) | ×20,7 | −24,4 % | ×3,18 | 45 % |

Für den BTC-Bot kostet die Bremse 15 % Ertrag bei 6 Punkten weniger Rückgang – kein guter Tausch.

### Urteil

- **Nicht bestätigt:** „Gleicher Ertrag, viel weniger Rückgang.“ Die einfache Variante kostet in jedem Zeitraum
  Ertrag.
- **Bestätigt, aber mit Preis:** Mit BTC-Veto auch für die Funding-Untergrenze sinkt der größte Rückgang des ETH-Bots
  verlässlich um rund 10 Punkte (auf etwa −30 %), das schlechteste Jahr von −31 % auf −19 %. Dafür bleibt der Bot in
  starken ETH-Läufen zurück (2021 +323 % statt +362 %, 2025 +46 % statt +63 %). Bei den heutigen Einstellungen kostet
  das 7 % Endvermögen; ob es so günstig bleibt, ist unsicher, weil der Preis mit den Einstellungen stark schwankt.
- **Einordnung:** Das ist eine Risiko-Einstellung, kein Gratis-Gewinn. Sinnvoll als **abschaltbare Option** im
  ETH-Bot („BTC als Bremse“) für alle, denen −40 % zu viel sind – nicht als neuer Standard.
