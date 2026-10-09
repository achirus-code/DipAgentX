# KI-Daytrader (Claude Fable 5.1) für Revolut X

Stand 2026-10-09, ab DipAgentX 1.35.0. Strategie `ai` („KI-Daytrader“, vorher „KI entscheidet“). Keine Anlage- und
keine Steuerberatung. Ob der Bot Gewinn macht, ist nicht garantiert – siehe [Grenzen](#grenzen-und-risiken).

## Kurzfassung

Claude Fable 5.1 handelt ein Paar (z. B. ETH-EUR) intraday – Trades von Minuten bis wenigen Stunden. Der Bot ist so
gebaut, wie ein disziplinierter Daytrader arbeitet:

1. **Erst der Überblick, dann der Einstieg:** Trend und Marktphase auf vier Zeitebenen (4 h, 1 h, 15 min, 5 min),
   Unterstützungen und Widerstände, VWAP, Vortagesspanne, Volumen, Orderbuch und BTC als Leitmarkt.
2. **Claude sieht den Chart als Bild** – Kerzen, EMAs, VWAP, Volumen, Levels, Stop und Ziel – und dazu die genauen
   Zahlen.
3. **Nur Setups aus einem festen Playbook:** Pullback im Trend, Ausbruch und Retest, Abpraller an der Range-Unterkante,
   bestätigte Umkehr nach Ausverkauf, Momentum-Fortsetzung.
4. **Jeder Trade hat einen Plan:** Stop dort, wo die Idee widerlegt ist, Ziel vor dem nächsten Widerstand, mindestens
   1,5 : 1. Den Plan führt der Bot alle 30 Sekunden selbst aus – Stop auf Einstand ab +1R, optional Trailing-Stop.
5. **Disziplin im Code:** Tagesverlust-Limit, Pause nach Verlustserie, maximaler Stop-Abstand, kein Kauf ohne Stop,
   Positionsgröße nach Qualität des Setups.
6. **Ein Scanner weckt Claude**, wenn sich ein Setup bildet – statt stur im Takt zu fragen. Dann denkt Claude gründlicher.
7. **Lernen aus den eigenen Trades:** Trefferquote und durchschnittliches R je Setup, Notizen von Prüfung zu Prüfung.
8. **Nur gebührenfreie Limit-Orders** wie beim Momentum-Bot. Was nicht ausgeführt wird, wird storniert, nie zum
   Marktpreis gehandelt.
9. **Monatsbudget für die API** (Standard 100 $): Der Bot misst die Kosten jeder Prüfung und verteilt den Rest.

## Was einen guten Daytrader ausmacht – und wie der Bot das umsetzt

| Prinzip erfolgreicher Daytrader | Umsetzung im Bot |
|---|---|
| Kontext vor Einstieg: mit dem übergeordneten Trend handeln | Trend, Struktur und Marktphase auf 4 h, 1 h, 15 min, 5 min; Claude soll Longs gegen einen 1-h-Abwärtstrend nur bei bestätigter Kapitulation eingehen |
| Wissen, in welcher Marktphase man ist (Trend, Range, Chop) | ADX, Effizienzquote, EMA-Lage und Hoch-/Tief-Struktur ergeben die Marktphase; bei „Chop“ wird gewartet |
| An Levels handeln, nicht in der Mitte | Swing-Hochs und -Tiefs auf 15 min und 1 h zu Zonen gebündelt (mit Anzahl Berührungen), VWAP, Vortageshoch/-tief/-schluss |
| Ein kleines Repertoire guter Setups | Playbook mit sechs Setups; jeder Kauf nennt sein Setup |
| Bestätigung abwarten | Kerzenmuster der letzten drei Kerzen (Hammer, Engulfing, Inside Bar, Shooting Star, große Kerzen), relatives Volumen |
| Volumen bestätigt Bewegungen | Relatives Volumen, Volumen auf steigenden vs. fallenden Kerzen, Volumenbalken im Chart |
| Stop an der Invalidierung, Chance-Risiko ≥ 1,5–2 | So im Prompt verlangt; Stop nie weiter als der Max. Stop-Loss; ohne Stop kein Kauf |
| Positionsgröße nach Qualität | 25–100 % des Max. Betrags, A-Setup 100 %, gutes Setup 50 %, spekulativ 25 % |
| Gewinne laufen lassen, Risiko schnell herausnehmen | Stop auf Einstand ab +1R, Trailing-Stop ab +1R, Stop wird nie gesenkt |
| Ein Trade ohne Fortschritt ist ein schlechter Trade | Zeitlimit pro Trade weckt Claude zur Neubewertung |
| Tagesverlust begrenzen, nicht „zurückholen“ wollen | Tagesverlust-Limit und Pause nach Verlustserie stoppen neue Trades – ohne Claude zu fragen |
| Kosten im Griff | Limit-Orders mit 0 % Maker-Gebühr; Spread steht im Briefing |
| Journal führen, aus Fehlern lernen | Jeder Trade mit Setup, Ergebnis in % und R, bestem Kurs während des Trades und Ausstiegsgrund; Statistik je Setup |
| Geduld: meistens ist Warten richtig | Ausdrücklich im Prompt; der Scanner holt Claude, wenn etwas passiert |

## Ablauf

```
alle 30 s (Engine-Tick)
 ├─ offene Position? → Plan ausführen: Stop / Ziel / Break-even / Trailing (ohne Claude)
 ├─ neue Position? → aus Claudes Plan Stop und Ziel relativ zum echten Einstieg setzen
 ├─ Disziplin: Tagesverlust-Limit oder Verlustserie → keine neuen Trades
 ├─ Budget aufgebraucht? → nur noch Plan ausführen
 ├─ neue 5-min-Kerze? → Scanner sucht Setups
 └─ Claude fragen, wenn: Scanner-Signal · Preisalarm · große Bewegung · Zeitlimit · planmäßige Prüfung fällig
       → Briefing + Chart → Fable 5.1 → Entscheidung + Plan → Limit-Order
```

## Was Claude sieht

### Der Chart als Bild

Ja: Claude bekommt bei jeder Prüfung ein Kerzenchart-Bild (960 × 900 Pixel, etwa 1 Cent pro Prüfung, abschaltbar) und
liest es wie ein Trader am Bildschirm. Drei Panels von oben nach unten:

| Panel | Inhalt |
|---|---|
| 1H 3D | 1-Stunden-Kerzen der letzten 3 Tage – das große Bild |
| 15M 24H | 15-Minuten-Kerzen der letzten 24 Stunden |
| 5M 3H | 5-Minuten-Kerzen der letzten 3 Stunden – der Einstieg |

In jedem Panel: grüne und rote Kerzen, Volumenbalken unten, EMA20 (orange), EMA50 (blau), VWAP seit 00:00 UTC
(violett, in den Intraday-Panels), die nächsten Unterstützungen und Widerstände (grau gestrichelt), bei offener
Position Einstieg (weiß gepunktet), Stop (rot) und Ziel (grün), Preise an der rechten Achse, der aktuelle Kurs im grauen
Kasten. Die EMAs werden auf der ganzen Historie berechnet, damit sie auch im kurzen 5-Minuten-Panel ab der ersten Kerze
stimmen.

Das Bild zeigt die Gestalt – Trendverlauf, Seitwärtsphasen, Dochte, Ausbrüche, wie sich das Volumen verhält. Genaue
Werte liest ein Sprachmodell aus einem Bild aber nicht zuverlässig ab. Deshalb gibt es dieselben Daten zusätzlich als
Zahlen, und der Prompt sagt: Bei Widerspruch gelten die Zahlen.

Das Bild wird ohne Zusatzbibliothek erzeugt (eigener PNG-Encoder in `agent/app/strategies/ai_chart.py`), damit das
Docker-Image auf amd64 und aarch64 gleich bleibt.

### Das Briefing (Zahlen)

Nur abgeschlossene Kerzen werden ausgewertet; den aktuellen Kurs liefert der Ticker.

| Feld | Inhalt |
|---|---|
| `woken_by` | warum Claude gerade gefragt wird (Scanner-Signal, Preisalarm, große Bewegung, Zeitlimit, planmäßig) |
| `price`, `bid`, `ask`, `spread_pct` | Kurs und Spread |
| `market_phase` | Aufwärtstrend / Abwärtstrend (15 min und 1 h einig), gemischt, Range, „choppy range – no direction“ |
| `changes_pct` | Veränderung über 15 min, 1 h, 4 h, 24 h, 72 h |
| `timeframes` | je Zeitebene 4h, 1h, 15m, 5m: Trend, Struktur, Lage zu EMA20/EMA50, EMA20-Steigung, RSI14, ADX14, Effizienzquote, ATR14 in %, die letzten drei Kerzen in Worten |
| `levels_15m_24h`, `levels_1h_3d` | je drei Unterstützungen und Widerstände mit Kurs, Anzahl Berührungen und Abstand in % |
| `session` | Vortageshoch, -tief, -schluss, heutige Eröffnung, VWAP seit 00:00 UTC und Abstand dazu |
| `volume_5m` | Volumen der letzten Kerze und der letzten drei relativ zum Durchschnitt, Volumen steigender zu fallender Kerzen (2 h) |
| `bollinger_5m` | Bandbreite als Perzentil (niedrig = Squeeze, oft vor einer großen Bewegung), Lage in den Bändern |
| `order_book` | Tiefe der Kauf- und Verkaufsseite bis 0,25 % und 1 % vom Kurs, Ungleichgewicht, größte Order in der Nähe |
| `market_leader` | bei Altcoins: BTC im selben Quote (Trend 15 min, Veränderung 1 h / 4 h / 24 h) |
| `last_12_candles_5m_ohlcv` | die letzte Stunde als Zahlen |
| `position` | Einstieg, Einsatz, Gewinn in % und in R, Haltedauer, Hoch seit Einstieg, Setup, Ziel, Stop, Anfangsstop, Trailing, Zeitlimit erreicht |
| `your_notes` | Claudes eigene Notizen von der letzten Prüfung |
| `previous_decision` | letzte Entscheidung mit Setup, Sicherheit, Begründung, Kurs damals |
| `performance` | Trades und Ergebnis heute, Statistik der letzten 30 Trades gesamt und je Setup, Details der letzten 8 Trades |
| `rules` | Max. Betrag, Wartezeit der Limit-Orders, üblicher Abstand der Prüfungen, Max. Stop, Break-even, Verlustverkauf erlaubt, Tageslimit, Mindestsicherheit, Maker-Gebühr 0 % |

Optional: Crypto Fear & Greed Index und bis zu drei Web-Suchen nach Nachrichten.

### Wie ein Aufwärtstrend erkannt wird

Je Zeitebene (`agent/app/strategies/ai_analysis.py`):

- **Aufwärts:** EMA20 über EMA50, EMA20 steigt (über die letzten 5 Kerzen), Kurs über EMA50 und die Struktur ist nicht
  „tiefere Hochs und tiefere Tiefs“. **Abwärts** spiegelbildlich, sonst **seitwärts**.
- **Struktur:** die letzten zwei Swing-Hochs und -Tiefs (ein Hoch, das höher ist als je zwei Kerzen links und rechts):
  „higher highs and higher lows“ ist die klassische Definition eines Aufwärtstrends.
- **Stärke:** ADX unter 18 macht daraus „up (weak)“. Die Effizienzquote (Nettobewegung durch zurückgelegten Weg über
  20 Kerzen) zeigt, ob der Kurs sauber läuft (nahe 1) oder hin- und herschlägt (nahe 0).
- **Marktphase:** Zeigen 15 min und 1 h beide aufwärts, heißt sie „uptrend (15m and 1h agree)“; Effizienz unter 0,2 und
  ADX unter 20 heißt „choppy range – no direction“.

Claude bekommt diese Einordnung, die Rohwerte und das Bild – und soll sie selbst gewichten. Die Regeln sind eine
Lesehilfe, keine Handelssignale.

## Das Playbook

| Setup | Idee |
|---|---|
| `trend_pullback` | im Aufwärtstrend ein Rücksetzer an die steigende EMA20, den VWAP oder einen früheren Widerstand, Verkaufsvolumen versiegt, 5-min-Kerze dreht nach oben |
| `breakout` / `breakout_retest` | enge Konsolidierung oder Squeeze unter einem Widerstand bricht mit deutlich steigendem Volumen; besser noch der Retest des gebrochenen Levels von oben |
| `range_support` | in einer klaren Range hält die Unterkante (Docht, Abweisung), mit Platz bis zur Oberkante |
| `reversal` | nach starkem Ausverkauf Erschöpfung (Klimax-Volumen, lange untere Dochte, RSI tief überverkauft) und Rückeroberung eines Levels – nur mit Bestätigung |
| `momentum` | starker, geordneter Impuls mit steigendem Volumen, eine flache Pause bietet den Einstieg |

Der Bot kann nur kaufen (Spot, kein Short, kein Hebel). Im Abwärtstrend heißt die Antwort meist „warten“.

## Wie Claude entscheidet

Der System-Prompt (`SYSTEM_PROMPT` in `agent/app/strategies/ai.py`) gibt Fable einen Prozess vor, aber keine starren
Schwellen – Fable 5.1 entscheidet mit weniger engen Vorgaben besser:

1. **Kontext:** Trend auf 4 h und 1 h, Marktphase, bei Altcoins BTC. Mit dem höheren Trend handeln.
2. **Lage:** Wo steht der Kurs zu Unterstützung, Widerstand, VWAP und Vortagesspanne? Gute Longs starten nahe
   Unterstützung oder direkt nach der Rückeroberung eines Levels.
3. **Setup:** nur saubere Setups aus dem Playbook.
4. **Auslöser:** Die Einstiegskerze soll die Idee bestätigen. Ohne Bestätigung kein Trade – der Scanner oder ein
   Preisalarm holt Claude wieder.
5. **Risiko:** Stop dort, wo die Idee widerlegt ist (unter Swing-Tief oder Level) und außerhalb des normalen Rauschens
   (mehr als etwa ein 5-min-ATR). Ziel vor dem nächsten Widerstand. Mindestens 1,5 : 1, besser 2 : 1 – sonst kein
   Trade.
6. **Größe:** 100 % des Max. Betrags für ein A-Setup, 50 % für ein gutes mit Schwäche, 25 % für ein spekulatives.
7. **Führen:** Bei jeder Prüfung einer offenen Position entscheiden: halten (Stop nachziehen, Ziel anpassen) oder
   schließen, wenn der Grund für den Trade weg ist. Stops nie erweitern.
8. **Rückblick:** Die eigene Statistik je Setup ist das ehrlichste Feedback. Was bei diesem Paar funktioniert, öfter;
   was immer wieder scheitert, meiden; nach Verlusten wählerischer werden, nicht aktiver.

Claude antwortet als strukturiertes JSON (Structured Outputs): Aktion, Setup, Ziel, Stop, Größe, Trailing-Abstand,
Zeitlimit, Preisalarme, nächste Prüfung, Sicherheit, Notizen (max. 300 Zeichen) und eine Begründung auf Englisch und
Deutsch. Lehnt Fable eine Anfrage ab, wiederholt die API sie automatisch auf dem von Anthropic empfohlenen
Ersatzmodell (`fallbacks: "default"`).

## Was der Bot zwischen den Prüfungen selbst tut

Alle 30 Sekunden, ohne Claude:

- **Stop erreicht** (Geldkurs ≤ Stop) → Verkauf, auch mit Verlust.
- **Ziel erreicht** (Geldkurs ≥ Ziel) → Verkauf.
- **Break-even:** Steht der Trade so weit im Plus, wie er riskiert hat (+1R = Einstieg + (Einstieg − Anfangsstop)),
  rückt der Stop auf den Einstieg. Abschaltbar.
- **Trailing-Stop:** Hat Claude `trail_pct` gesetzt, folgt der Stop ab +1R dem Hoch seit Einstieg im Abstand von
  `trail_pct`.
- Der Stop wird **nie gesenkt** und liegt **nie weiter als der Max. Stop-Loss** vom Einstieg.
- Claude sagt „verkaufen“ → die Limit-Order wird bis zur nächsten Prüfung immer wieder gestellt, bis sie ausgeführt ist.
- Plan relativ zum echten Einstieg: Claude nennt Ziel und Stop beim Kaufkurs von damals; wird die Limit-Order etwas
  anders ausgeführt, verschiebt der Bot beide um denselben Prozentsatz.

### Ausführung: nur Limit-Orders

Live auf Revolut X geht jede Order als Post-only-Limit-Order einen Cent in den Spread – ein Kauf einen Cent unter dem
besten Geldkurs, ein Verkauf einen Cent über dem besten Briefkurs. Maker-Gebühr 0 % statt 0,09 % – bei vielen Trades am
Tag entscheidend. Läuft der Kurs weg, wird die Order storniert und am neuen besten Kurs neu gestellt (wie beim
Momentum-Bot). Nach der Wartezeit (Standard 10 min) wird eine nicht ausgeführte Order **storniert, nicht** zum
Marktpreis ausgeführt. Bei Stop- und Zielverkäufen stellt der nächste Tick sofort eine neue Limit-Order. Nur „Position
jetzt verkaufen“ von Hand verkauft zum Marktpreis. Im Paper-Modus werden Market-Orders simuliert.

## Wann Claude gefragt wird

**Scanner** – bei jeder neuen abgeschlossenen 5-min-Kerze, reine Rechenregeln ohne API-Kosten:

| Signal | Regel |
|---|---|
| Ausbruch | 5-min-Schluss über dem Hoch der vorherigen 2 Stunden, Volumen mindestens 1,5 × Durchschnitt |
| Bruch nach unten | 5-min-Schluss unter dem Tief der vorherigen 2 Stunden, Volumen mindestens 1,5 × (wichtig für offene Positionen) |
| Pullback im Trend | 1-h-Trend aufwärts, 15 min nicht abwärts, Kurs nahe der 15-min-EMA20 (innerhalb 0,6 × ATR, mind. 0,15 %) oder des VWAP (0,2 %), 5-min-RSI unter 50, letzte 5-min-Kerze grün |
| Kapitulation | 15-min-RSI unter 30, grüne 5-min-Kerze, Volumen mindestens 2 × |
| Volumenspitze | Volumen mindestens 3 ×, wenn sonst nichts anschlägt |

Ein Signal weckt Claude nur, wenn seit der letzten Prüfung die Mindestzeit vergangen ist („Claude höchstens alle“,
Standard 5 min), und nur einmal. Es verfällt nach 15 Minuten.

**Weitere Weckgründe:** Claudes eigene Preisalarme (`wake_above`, `wake_below`), eine Bewegung seit der letzten
Prüfung von mindestens dem Größeren aus 0,4 % und 3 × 5-min-ATR, das Zeitlimit einer offenen Position, „Jetzt fragen“
in der App.

**Planmäßig:** sonst nach dem Budget-Takt (siehe unten). Claude kann mit `next_check_minutes` länger warten oder früher
schauen – frühestens nach dem halben Budget-Takt, spätestens nach 4 Stunden.

**Denktiefe automatisch:** „mittel“ bei Scanner-Signal, Alarm oder offener Position, „niedrig“ bei Routineblicken ohne
Anlass. Fest einstellbar auf niedrig, mittel oder hoch.

## Disziplin-Regeln

| Regel | Standard | Wirkung |
|---|---|---|
| Max. Stop-Loss | 3 % | Stop nie weiter vom Einstieg entfernt; ohne Stop von Claude gilt dieser |
| Kein Kauf ohne Stop | – | steht Max. Stop-Loss auf 0 und nennt Claude keinen Stop, wird nicht gekauft |
| Tagesverlust-Limit | 6 % des Max. Betrags | keine neuen Trades bis 00:00 UTC; Claude wird nicht gefragt (spart Budget) |
| Pause nach Verlusten in Folge | 3 Trades | 2 Stunden keine neuen Trades |
| Mindestsicherheit | 0 % (aus) | Käufe nur ab dieser Sicherheit |
| Claude darf mit Verlust schließen | an | aus: Claudes eigenes Verkaufssignal wartet auf die Gewinnschwelle, nur der Stop realisiert Verluste |
| Pause nach Kauf oder Verkauf | 0 min | optionale Abkühlzeit |

Offene Positionen werden auch bei erreichtem Limit weiter nach Plan geführt.

## Lernen aus den eigenen Trades

Für jeden abgeschlossenen Trade speichert der Bot: Setup, Größe, Haltedauer, Ergebnis in % und in R (Ergebnis geteilt
durch das Anfangsrisiko), den besten Kurs während des Trades (zeigt, ob Ziele zu weit oder Stops zu eng waren),
Ergebnis in % des Max. Betrags und den Ausstiegsgrund (`take_profit`, `stop`, `trailing/break-even stop`, `claude`).
Daraus bekommt Claude Trefferquote, durchschnittliches Ergebnis und durchschnittliches R – gesamt und je Setup über die
letzten 30 Trades. Mit `notes` hält Claude fest, welches Szenario es beobachtet („Range 1985–2010, warte auf
Rückeroberung von 2010 mit Volumen“), und liest das bei der nächsten Prüfung wieder.

## Kosten und Budget

Fable 5.1 kostet 10 $ pro Million Eingabe-Tokens und 50 $ pro Million Ausgabe-Tokens. Eine Prüfung hat etwa 2.000
Tokens System-Prompt, 1.200 Tokens Briefing und 1.100 Tokens Chart-Bild (zusammen ca. 0,045 $) plus Denken und
Antwort (niedrig ca. 0,03–0,05 $, mittel ca. 0,08–0,13 $). **Grob 0,08–0,18 $ pro Prüfung**, im Mittel etwa 0,12 $.
Diese Werte sind Schätzungen; der Bot misst die echten Kosten aus der API-Antwort.

Mit 100 $ im Monat sind das rund 800 Prüfungen, im Mittel etwa eine alle 50–60 Minuten. Der Scanner verschiebt sie
dorthin, wo etwas passiert. Der Takt errechnet sich laufend: verbleibendes Budget / gemessene Kosten pro Prüfung,
verteilt auf die verbleibende Zeit im Monat. Ist das Budget aufgebraucht, führt der Bot offene Positionen weiter nach
Plan und fragt Claude ab dem Monatsersten wieder. Das Budget gilt pro Bot. Der Status zeigt den Verbrauch des Monats.

Hebel, wenn öfter gefragt werden soll: Budget erhöhen, Denktiefe „niedrig“, Chart abschalten (spart ca. 1 Cent),
Opus 5.5 statt Fable (ca. 40 % der Kosten).

## Einstellungen

| Einstellung | Standard | Bedeutung |
|---|---|---|
| Max. Betrag pro Trade | 50 | Claude nutzt 25–100 % davon |
| Modell | Claude Fable 5.1 | Opus 5.5, Sonnet 5.5, Haiku 5.5 wählbar |
| Denktiefe | Automatisch | niedrig / mittel / hoch fest |
| API-Budget pro Monat | 100 $ | pro Bot |
| Claude höchstens alle | 5 min | Mindestabstand, auch für Scanner und Alarme |
| Claude den Chart zeigen | an | Kerzenchart als Bild |
| Wartezeit für Limit-Orders | 10 min | danach Storno |
| Max. Stop-Loss | 3 % | |
| Stop auf Einstand ab +1R | an | |
| Claude darf mit Verlust schließen | an | |
| Tagesverlust-Limit | 6 % | des Max. Betrags, 0 = aus |
| Pause nach Verlusten in Folge | 3 | 0 = aus |
| Mindestsicherheit | 0 % | |
| Nachrichten einbeziehen | aus | macht Prüfungen mehrfach so teuer |
| Fear-&-Greed-Index | aus | Hintergrund oder Kontrasignal an Extremen |
| Zusätzliche Anweisungen | – | eigene Regeln, z. B. „nur Pullbacks im Trend“ |

Voraussetzung: `ANTHROPIC_API_KEY` auf dem Agenten (Home Assistant: Option `anthropic_api_key`).

## Grenzen und Risiken

- **Kein Beweis für einen Vorteil.** Es gibt keinen Backtest: Entscheidungen eines Sprachmodells lassen sich nicht
  ohne Weiteres auf Vergangenheitsdaten testen (es kennt viele vergangene Kurse und würde sich selbst etwas vormachen).
  Daytrading ist für die meisten Menschen ein Verlustgeschäft; ein guter Prozess erhöht die Chancen, garantiert aber
  nichts.
- **Long only.** In Abwärtsphasen verdient der Bot nichts; er kann nur warten.
- **Limit-only hat zwei Seiten:** keine Gebühren, aber manche Einstiege werden verpasst und ein Stop-Verkauf in einem
  schnellen Absturz kann deutlich unter dem Stop landen oder sich verzögern, weil die Order dem Kurs hinterherläuft.
- **Volumen und Orderbuch** kommen nur von Revolut X – einem kleineren Handelsplatz. Das Volumen dort spiegelt den
  Gesamtmarkt nur teilweise.
- **Reaktionszeit:** Zwischen zwei Prüfungen handelt nur der Plan. Claude reagiert frühestens nach der Mindestzeit und
  braucht pro Antwort je nach Denktiefe 10 Sekunden bis wenige Minuten.
- **Kosten:** 100 $ API-Budget im Monat müssen erst einmal verdient werden. Bei 1.000 € Einsatz pro Trade sind das rund
  10 % des Einsatzes pro Monat.

## Empfehlung zum Start

1. Im **Paper-Modus** 2–4 Wochen laufen lassen.
2. Danach die Kennzahlen ansehen: Trefferquote, durchschnittliches R, Ergebnis nach API-Kosten, welche Setups
   funktionieren (Entscheidungsprotokoll in der App und `performance` im Briefing).
3. Live erst mit einem kleinen Betrag. Setups, die nicht funktionieren, per „Zusätzliche Anweisungen“ ausschließen.

## Code

| Datei | Inhalt |
|---|---|
| `agent/app/strategies/ai.py` | Strategie, Prompt, Plan, Budget, Disziplin, Wecken |
| `agent/app/strategies/ai_analysis.py` | Indikatoren, Trend, Struktur, Levels, Session, Volumen, Orderbuch, Scanner |
| `agent/app/strategies/ai_chart.py` | Chart-Bild (PNG ohne Zusatzbibliothek) |
| `agent/app/engine.py` | `limit_only`: Limit-Orders ohne Market-Fallback |
| `agent/tests/test_ai.py` | Tests |
