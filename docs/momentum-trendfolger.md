# Momentum-Trendfolger („M6F“) für ETH-EUR und BTC-EUR (Revolut X)

Stand 2026-10-05. Regeln des Bots `momentum` (ab DipAgentX 1.20.0) und Ergebnisse der Backtests auf echten
Binance-Kursen. Alles vor Steuern, sofern nicht anders angegeben. Keine Anlage- und keine Steuerberatung.

## Kurzfassung

Ein Bot pro Coin mit eigenem Kapital. Die Strategie besteht aus drei klar trennbaren Bausteinen:

1. **Momentum:** Sechs Zeitfenster (14, 21, 30, 40, 50, 60 Tage) zeigen je aufwärts oder abwärts.
   Anteil = eingeschaltete Fenster / 6.
2. **Schwankungsdeckel:** In sehr schwankenden Märkten wird der Anteil gekürzt.
3. **Funding-Gegenwette:** Fällt die Funding-Rate der Futures unter +2 % p. a., hält der Bot mindestens 50 % (mal
   Schwankungsfaktor), auch wenn alle Trendfenster abwärts zeigen.

Das Ergebnis wird auf 10-%-Stufen gerundet (0 bis 100 % des Bot-Vermögens). Gehandelt wird nur bei Stufenwechsel, auch
mit Verlust. Die Positionsgröße bezieht sich auf das aktuelle Vermögen (Cash plus Marktwert), Gewinne wirken also
automatisch mit.

Der Name „Momentum-Trendfolger“ trifft nur Baustein 1. Baustein 3 kann die Trendentscheidung überschreiben: Bei 0 von 6
Fenstern und Funding unter +2 % ist der Bot trotzdem zur Hälfte investiert. Im Bärenmarkt ist er damit nie ganz „aus“,
solange die Funding-Rate Panik zeigt.

## 1. Marktdaten

- 4-Stunden-Kerzen, an UTC 00/04/08/12/16/20 Uhr ausgerichtet. Nur abgeschlossene Kerzen; die laufende Kerze wird nie
  verwendet.
- Benötigter Verlauf 76 Tage (60 längstes Fenster + 14 Aufwärmen + 2 Reserve). Mit weniger als 74 Tagen handelt der
  Bot nicht („Warte auf Kursverlauf“).
- Tagesschluss = Schlusskurs der Kerze 20 bis 24 Uhr UTC.
- Funding-Rate: Binance-USDT-Perpetual (ETHUSDT/BTCUSDT), öffentliche API `/fapi/v1/fundingRate`, Abstände 8 h. Mittel
  der letzten 7 Tage, auf Jahresrate umgerechnet (0,01 % je 8 h = 10,95 % p. a.). Fehlt die Rate oder ist der letzte
  Wert älter als 2 Tage, nimmt der Bot ersatzweise die Funding-Rate derselben Kontrakte auf Bybit
  (`/v5/market/funding/history`, öffentlich); der Status zeigt dann „(Bybit)“ hinter dem Wert. Liefert auch Bybit
  nichts, gibt es keine Untergrenze. Der Status beginnt dann mit „⚠ Seit … keine Funding-Rate von Binance oder Bybit –
  die Untergrenze ist aus“, und die Karte zeigt das als Hinweis. Historie gibt es erst ab 2019-09 (BTC) bzw. 2019-11
  (ETH).
- Bybit als Ersatz (geprüft 2022–2026, alle 4 h): im Mittel gleich wie Binance (BTC ±0,0, ETH +0,3 Prozentpunkte),
  einzelne Wochen aber ±4 Punkte daneben; die Entscheidung „unter +2 %“ stimmt in 82 % (BTC) bzw. 86 % (ETH) der Checks
  überein. Die ganze Regel mit Bybit statt Binance (50 % Limit-Käufe): ETH ×4,29 statt ×3,74, BTC ×2,22 statt ×2,97 –
  so viel wie ganz ohne Untergrenze (×2,21). Der Vorsprung der Untergrenze bei BTC hängt also an den Binance-Werten und
  ist weniger robust als bei ETH. Als Ersatz während eines Binance-Ausfalls ist Bybit trotzdem besser als keine
  Untergrenze.
- Börsenzuflüsse (Coin Metrics Community API) nur für die optionale Bremse, standardmäßig aus.

## 2. Baustein 1: Momentum mit sechs Fenstern und Hysterese

- Für jedes Fenster n in (14, 21, 30, 40, 50, 60) Tagen bei jeder neuen Kerze:
  Veränderung = Schluss jetzt / Schluss vor n Tagen − 1, in Prozent.
- Veränderung > `entry` (Standard +5 %): Fenster an. Veränderung < `exit` (Standard 0 %): Fenster aus. Dazwischen
  bleibt der Zustand (Hysterese gegen Flattern).
- Anteil = Anzahl eingeschalteter Fenster / 6.
- Nach Neustart oder Ausfall über 14 Tage: alle Fenster auf 0, die letzten 14 Tage werden nachgerechnet. Im Backtest
  ergab das an 0 % der Tage einen anderen Zustand als der Dauerbetrieb.
- Entfernt: Eine frühere Variante („M6F+“) senkte im starken Aufwärtstrend (90-Tage-Rendite über +20 %) die
  Einschaltschwelle auf +2 % (`fast_entry`/`fast_after`). Sie war renditeneutral, erzeugte aber rund 20 % mehr Orders.

Beispiel: 14 T +8 %, 21 T +7 %, 30 T +6 %, 40 T +4 % (war an, bleibt an), 50 T +2 % (war an, bleibt an), 60 T −3 % (aus)
→ 5 von 6 → Anteil 0,833.

## 3. Baustein 2: Schwankungsdeckel

- Volatilität = Stichproben-Standardabweichung der letzten 20 täglichen Log-Renditen × √365 (abgeschlossene UTC-Tage).
- Faktor = min(1, `vol_target` / max(Volatilität, 5 %)), Standard `vol_target` 100 %. Beispiel: Volatilität 150 % →
  Faktor 0,667.
- Gewicht = Anteil × Faktor. `vol_target` = 0 schaltet den Deckel ab.
- Wirkung im Backtest: kaum Renditeeffekt, aber geringerer größter Rückgang (ETH 2017–2021: 53 % statt 63 %; nur 2018:
  ETH 49 % statt 58 %, BTC 47 % statt 49 %).

## 4. Baustein 3: Funding-Gegenwette (Untergrenze)

- Liegt die 7-Tage-Funding-Rate unter `funding_below` (+2 % p. a.; normal sind etwa +10 %), gilt:
  Gewicht = max(Gewicht, `funding_floor` × Faktor) mit `funding_floor` 50 %.
- Mit Volatilität 150 % und 0 von 6 Fenstern hält der Bot also 33 %, mit Volatilität unter 100 % 50 %.
- Begründung: Negative oder sehr niedrige Funding-Raten markierten historisch oft Kapitulationstiefs. Das ist eine
  Gegenwette zum Trend, keine Trendfolge, und ein eigenständiger Baustein mit eigenem Parameterrisiko.
- Alle Werte unter der Schwelle (+1 %, 0 %, −5 %) werden gleich behandelt.
- `funding_floor` = 0 schaltet die Regel ab.

## 5. Optional: Zufluss-Bremse (Standard aus)

- Nettozufluss zu Börsen der letzten 7 Tage in % des dortigen Bestands. Über `inflow_above` (1 %) wird das Gewicht
  halbiert, einschließlich Untergrenze.
- Aus, weil Coin Metrics Werte nachträglich korrigiert und ein Tag erst 30 Stunden nach Tagesbeginn nutzbar ist.
  Nicht im Backtest geprüft.

## 5a. Optional: BTC als Bremse (Standard aus, nur für Coins außer BTC)

- Der ETH-Bot hält höchstens so viel, wie der Trend von BTC erlauben würde: Anteil der sechs BTC-Zeitfenster, die
  aufwärts zeigen (gleiche Schwellen `entry` / `exit`, BTC-EUR-4-h-Kurse), mal dem Schwankungsfaktor von ETH.
- Die Funding-Untergrenze bleibt nur, wenn auch das BTC-Funding unter `funding_below` liegt. Panik nur bei ETH reicht
  nicht mehr.
- Wirkt nach der Untergrenze und vor der Zufluss-Bremse. Fehlen die BTC-Kurse, ist die Bremse aus (Signal „BTC-Kurse
  nicht verfügbar“).
- Im Bot sichtbar als eigenes Signal: „BTC-Trend 4 von 6 aufwärts – keine Bremse“ (grün), „… – höchstens 70 %“ (rot),
  „… auch BTC-Funding zeigt Panik – Untergrenze bleibt“ (grün).

Backtest mit Nachbau des Bots, ETH-EUR, März 2020 bis September 2026, ohne Gebühr (Details in
`docs/btc-eth-verbindung.md`, Teil 3):

| | Gewinn | pro Jahr | größter Rückgang | 2022–26 | schlechteste 12 Monate |
|---|---|---|---|---|---|
| ETH halten | +1.050 % | 45 % | −79 % | −28 % | – |
| ETH-Bot ohne Bremse | +4.531 % | 79 % | −40 % | +298 % | −31 % |
| ETH-Bot mit BTC-Bremse | +4.190 % | 77 % | −29 % | +313 % | −19 % |

Der kleinere Rückgang hielt in allen sechs geprüften Grundeinstellungen (−29 bis −31 % statt −37 bis −40 %). Der
Preis: In starken ETH-Läufen bleibt der Bot zurück (2021 +323 % statt +362 %, 2025 +46 % statt +63 %), und wie viel
Ertrag die Bremse kostet, hängt stark von der Funding-Einstellung ab (bei den Standardwerten 7 %, bei einer
Funding-Schwelle von 0 % fast 30 %). Für den BTC-Bot mit ETH als Bremse lohnte es sich nicht.

## 6. Stufe und Zielposition

- Stufe = `round(Gewicht × 10)`, 0 bis 10, mit Pythons `round` (bei genau ,5 zur geraden Zahl). Kaufmännische Rundung
  änderte im Backtest nichts.
- Größen strikt getrennt:

  | Größe | Bedeutung |
  |---|---|
  | Startkapital (`amount`) | eingestellter Betrag |
  | Cash | Startkapital + realisierte Ergebnisse − Kosten der offenen Trades |
  | Positionswert | Σ Menge × Geldkurs |
  | Equity | Cash + Positionswert |

- Ziel = Equity × Stufe / 10. Da das Ziel auf der Equity beruht, wächst die Position mit Kursgewinnen automatisch mit
  (Start 1.000 €, 70 % investiert, Kurs +50 % → Equity 1.350 €, Ziel 945 €). Eine Änderung von `amount` startet die
  Rechnung neu ab dem neuen Betrag.

## 7. Umsetzung in Trades

- Die Position besteht aus bis zu 10 Trades zu je rund 10 % der Equity. Für die Limits zählt der Bot als eine
  Position; die Apps zeigen eine Position und darunter die eröffneten Trades.
- Gehandelt wird nur bei Stufenwechsel. Zwischen zwei Wechseln schwankt die Position mit dem Kurs, ohne
  Nachjustierung.
- Aufstocken: pro Check (alle 30 s) eine Order über min(Lücke, Cash, 10 % der Equity), solange die Lücke ≥ 2,5 % der
  Equity und ≥ 10 € ist. Ein Wechsel von 0 auf 100 % sind zehn Käufe binnen weniger Minuten; der gehandelte Betrag ist
  dabei einmal die Equity, nicht zehnmal.
- Reduzieren: Verkauft wird der Trade, dessen Wert dem Überschuss am nächsten kommt, nur wenn der Rest-Überschuss dann
  unter 2,5 % der Equity liegt (Stufe 0: alles). Auch mit Verlust.
- Von Hand verkaufte Trades kauft der Bot beim nächsten Check zurück. Wer draußen bleiben will, stoppt den Bot.
- Wechsel von Papier zu live mit offenen Papier-Trades: Diese werden simuliert geschlossen, der Bot startet live neu
  mit seinem Kapital. Von live zu Papier geht es nur ohne offene Trades.

## 8. Orders und Kosten (live, Revolut X)

- Revolut X: Maker 0 %, Taker 0,09 % (offiziell angegeben, für Kauf und Verkauf gleich).
- Strategie-Orders (Kauf und Verkauf) gehen zuerst als Post-Only-Limit-Order raus: Kauf einen Cent unter dem besten
  Geldkurs, Verkauf einen Cent über dem besten Briefkurs. Der eine Cent Abstand verhindert, dass Post-Only abgelehnt
  wird, wenn sich der Kurs bewegt, während die Order unterwegs ist.
- Nachziehen: Läuft der Kurs weg (Geldkurs beim Kauf bzw. Briefkurs beim Verkauf mehr als einen Cent von der Order
  entfernt), storniert der Bot beim nächsten Check (alle 30 s) die Order, bucht den gefüllten Teil und stellt den Rest
  zum neuen Kurs ein. Teilfüllungen eines Kaufs landen im selben Trade, es entstehen also keine Mini-Trades.
- Wartezeit `maker_wait` (10 min) gilt einmal pro Umschichtung, ab ihrer ersten Order – auch wenn die Umschichtung
  mehrere Trades braucht (z. B. 0 → 50 % = 5 Käufe). Was danach noch fehlt, geht als Market-Order raus. Eine Stufe ist
  also spätestens nach der Wartezeit plus wenigen Checks umgesetzt. Ein Check ohne Order beendet die Umschichtung; die
  nächste bekommt wieder die volle Wartezeit.
- Lehnt die Börse eine Limit-Order ab (Post-Only hätte das Buch gekreuzt), ist das kein Fehler: Der nächste Check
  versucht es zum dann aktuellen Kurs erneut, nach der Wartezeit als Market-Order. (Bis 1.33 gingen nach einer
  ungefüllten oder abgelehnten Limit-Order 30 Minuten lang alle Orders als Market-Order raus, und Verkäufe immer
  sofort als Market-Order.)
- Manuelle Verkäufe und „alle Positionen schließen“: immer Market-Order (eine noch wartende Limit-Order wird vorher
  storniert, ihr gefüllter Teil gebucht). Papierhandel: Market-Orders mit der eingestellten Papier-Gebühr
  (0,09 % je Seite).
- Erster Live-Tag (8.10.2026, noch mit der 30-Minuten-Market-Pause): 42 % des Kaufvolumens als Limit-Order ohne
  Gebühr (ETH 6 von 8 Käufen, BTC 800 von 2.800 €) – die übrigen Käufe gingen nach einer einzigen nicht ganz gefüllten
  Limit-Order als Market-Order raus.
- Die reale Kostenlast hängt von der Maker-Füllquote ab. Backtest 2022–2026 mit gemessenem Umsatz (24-mal die mittlere
  Equity pro Jahr):

  | Ausführung | Kosten | ETH | BTC |
  |---|---|---|---|
  | alles Taker 0,09 % + 0,03 % Spread | ca. 2,9 % p. a. | ×3,64 | ×3,17 |
  | 50 % Maker-Fills | | ×3,91 | ×3,41 |
  | alles Maker (Obergrenze) | | ×4,20 | ×3,66 |

## 9. Ausführungszeitpunkt

- Signal bei Kerzenschluss t, Ausführung frühestens danach zum nächsten verfügbaren Preis (live: nächster Check nach
  Kerzenschluss; Backtest: Eröffnung der Folgekerze). Handel zum Signal-Close wäre Look-ahead und wurde nicht
  verwendet.
- Verzögerung kostet: 4 h später ETH ×3,28 statt ×3,64, 8 h später ×3,05. Minuten sind unerheblich, Stunden nicht – der
  Agent muss zuverlässig laufen.

## 10. Parameter (Standard)

| Parameter | Standard |
|---|---|
| `amount` | 1.000 € |
| `entry` / `exit` | +5 % / 0 % |
| `vol_target` | 100 % |
| `funding_floor` / `funding_below` | 50 % / +2 % p. a. |
| `inflow_brake` / `inflow_above` | aus / 1 % |
| `btc_brake` | aus |
| `maker_orders` / `maker_wait` | an / 10 min |

## 11. Beispiel eines Checks

ETH: 5 von 6 Fenstern an → Anteil 0,833. Volatilität 120 % bei Ziel 100 % → Faktor 0,833. Gewicht 0,694. Funding
+6 % p. a. → keine Untergrenze. Stufe = round(6,94) = 7 → Ziel 70 % der Equity. War die Stufe 9, verkauft der Bot zwei
Trades. Status: „Trend: 5 von 6 Zeitfenstern aufwärts · Schwankung 120 % über 100 % – weniger · Funding +6 % p. a.“

Gegenbeispiel: 0 von 6 Fenstern, Volatilität 100 %, Funding −3 % → Gewicht = max(0, 0,5 × 1) = 0,5 → Stufe 5. Halb
investiert trotz fallender Trends.

## 12. Was der Backtest zeigt (echte Binance-Kurse)

Datenlage:

- ETH-EUR / BTC-EUR 4-h-Kerzen: Binance ab 2020-01. Haupttest 2022-01-01 bis 2026-10-04. Dieser Zeitraum wurde auch zur
  Abstimmung der Parameter genutzt, er ist also in-sample.
- 2017-12 bis 2021: nur als Proxy auf ETH-USDT / BTC-USDT möglich; vor Ende 2019 ohne Funding, also nur Momentum +
  Schwankungsdeckel.
- Vollständiger Test aller drei Bausteine: erst ab 2019-12.
- Die Zahlen unten wurden noch mit `fast_entry` gerechnet („M6F+“); die Variante ohne ist renditeneutral.

Ergebnisse 2022–2026 (Market-Orders, 0,09 % + 0,03 %):

| | ETH-EUR | BTC-EUR |
|---|---|---|
| M6F+ komplett | ×3,64, DD 41 % | ×3,17, DD 29 % |
| ohne Funding-Floor | ×3,34, DD 35 % | ×2,36, DD 32 % |
| ohne Vol-Deckel | ×3,64, DD 41 % | ×3,17, DD 29 % |
| 60-Tage-Momentum (alles oder nichts) | ×4,14, DD 42 % | ×3,26, DD 35 % |
| 30-Tage-Momentum (alles oder nichts) | ×5,09, DD 40 % | ×1,93, DD 40 % |
| Halten | ×0,74, DD 74 % | ×1,87, DD 65 % |
| 100 % Cash | ×1,00 | ×1,00 |

Das Jahr 2018 einzeln (Proxy auf USDT, 4-h-Kerzen, 0,09 % je Seite, ohne Funding):

| 2018 | ETH Bot | ETH Halten | BTC Bot | BTC Halten |
|---|---|---|---|---|
| Ergebnis | −15 % | −82 % | −38 % | −72 % |
| größter Rückgang | 49 % | 94 % | 47 % | 81 % |
| größter Rückgang ohne Schwankungsdeckel | 58 % | | 49 % | |

Der Bot ging Anfang 2018 voll investiert vom Hoch aus in den Bärenmarkt und verlor an den Fehlausbrüchen, bevor er
draußen war.

Einordnung:

- Die Referenzwerte (×3,60 / ×3,32) sind reproduzierbar.
- Eine simple 60-Tage-Regel ist in-sample nicht schlechter. Der Mehrwert der Strategie ist nicht mehr Rendite, sondern
  Gleichmäßigkeit über Zeiträume und Coins und geringerer Drawdown; ein Einzelfenster schwankt stark (2019–2021: ETH
  60 T ×7,9, 30 T ×22, M6F+ ×15,6).
- Der Funding-Floor trägt bei BTC den größten Teil des Vorsprungs seit 2022. Er ist im Bereich `funding_below` −2 bis
  +5 % stabil positiv; bei +10 % kippt ETH auf ×1,66 bei 49 % Drawdown. Ohne ihn bleibt die Strategie vor Halten und
  robuster.
- Proxy-Test 2017–2021 (USDT): ETH ×23 (Halten ×8,6), BTC ×15 (Halten ×4,8), größter Rückgang 53 % / 58 %, bis zu
  1,5 Jahre bis zur Erholung. Die Rückgänge von rund 39 % / 30 % gelten nur für 2022–2026 – **mit Rückgängen um 50 %
  muss man rechnen.**
- Stufenwechsel gemessen: 125 pro Jahr, Abstand im Median 28 h, 90-%-Quantil 170 h, jeder fünfte Wechsel binnen 8 h
  nach dem vorigen.
- Rallyes werden zu 55 bis 75 % mitgenommen; über 6 bis 12 Monate ist das Ergebnis gegen Halten etwa ein Münzwurf,
  unter einem Monat Zufall. Über 3 Jahre lag die Strategie in den verfügbaren Zyklen vorn, das sind aber nur rund drei
  unabhängige Beobachtungen.

## 13. Steuern (Deutschland)

- Verkäufe innerhalb eines Jahres nach dem Kauf sind private Veräußerungsgeschäfte (§ 23 EStG) und werden mit dem
  persönlichen Einkommensteuersatz besteuert, nicht mit der Abgeltungsteuer.
- Gewinne bis 1.000 € pro Jahr sind steuerfrei – als Freigrenze: Ab 1.001 € ist der ganze Betrag steuerpflichtig.
- Verluste lassen sich nur mit Gewinnen aus privaten Veräußerungsgeschäften verrechnen (auch ein Jahr zurück oder in
  Folgejahre).
- Der Bot schichtet etwa zweimal pro Woche um, praktisch jeder Gewinn ist also steuerpflichtig; Halten über ein Jahr
  wäre steuerfrei.
- Das Finanzamt ordnet Verkäufe den Käufen „first in, first out“ je Wallet zu, das kann vom Trade abweichen, den der
  Bot verkauft. Für die Steuererklärung den Transaktions-Export von Revolut X nehmen, nicht die Ergebnisse je Trade.
- Wirkung im Backtest 2022–2026 mit 44 % Grenzsteuersatz: ETH ×2,28 gegen Halten ×0,74, BTC ×2,11 gegen ×1,87.
  Beispiel: 3.000 € Gewinn in einem Jahr bei 42 % Steuersatz (plus Soli/Kirchensteuer) kosten rund 1.300 €.
