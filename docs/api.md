# DipAgentX – Client-API (App ↔ Agent)

Kurzreferenz der HTTP-API, über die die Mac- und iPhone-App mit dem Agenten sprechen. Stand: Agent 1.33.

## Grundlagen

| | |
|---|---|
| Basis-URL | `http://<agent>:3470/api` (Home-Assistant-Add-on oder Docker) |
| Auth | `Authorization: Bearer <API-Token>` – fehlt oder falsch: `401` |
| Sprache | `Accept-Language: de` oder `en` – Texte (Status, Fehler, Gründe) kommen in dieser Sprache |
| Format | JSON, Beträge als Zahl, Zeiten als Unix-Millisekunden (`created_at`, `last_check` …) |
| Fehler | `{"detail": "<Text>"}`; `409` = gerade nicht möglich, `422` = ungültige Eingabe, `502` = Börse nicht erreichbar |

Ohne Token erreichbar ist nur `GET /api/health` → `{"ok": true, "version": "1.32.3"}`.

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Accept-Language: de" http://192.168.178.75:3470/api/bots
```

## Agent & Übersicht

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/status` | Version, Börse, `exchange_ok`/`exchange_error`, `live_trading_allowed`, `last_tick`, `tick_seconds`, `taker_fee` |
| GET | `/summary` | Ergebnis je Währung im aktiven Modus (`mode`: `paper`/`live`): realisiert, offen, heute, investiert, Gebühren; dazu `other_mode` |
| GET | `/strategies` | Strategien mit Beschreibung und Parametern (`key`, `type`, `default`, `min`/`max`, Hilfetext) |
| GET | `/pairs` | Handelbare Paare der Börse, z. B. `ETH-EUR` |
| GET | `/balances` | Guthaben auf der Börse |

## Bots

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/bots` | Alle Bots mit Zustand (Felder siehe unten) |
| POST | `/bots` | Bot anlegen → `201` + Bot |
| PUT | `/bots/{id}` | Bot ändern (gleicher Body wie POST) |
| DELETE | `/bots/{id}?force=true` | Bot löschen; mit offener Position nur mit `force` (Coins bleiben auf der Börse) → `204` |
| POST | `/bots/{id}/start`, `/bots/{id}/stop` | Bot starten / anhalten |
| POST | `/bots/{id}/close?position_id=` | Einen Trade oder alle zum Marktpreis verkaufen |
| POST | `/bots/{id}/discard?position_id=` | Trade ohne Verkauf aus den Büchern nehmen |
| POST | `/bots/{id}/reset-paper` | Papier-Ergebnis neu starten (nicht mit offener Live-Position) |
| POST | `/bots/{id}/ask` | Nur „KI entscheidet“: sofort neue Entscheidung holen |
| GET | `/bots/{id}/decisions?limit=100` | Nur „KI entscheidet“: Claudes Antworten |
| GET | `/bots/{id}/hodl` | Nur Momentum: Ergebnis von reinem Halten seit dem Start, alle 4 h – `[{"t", "value"}]` |

Body für `POST`/`PUT /bots`:

```json
{ "name": "M6F+ ETH 30%", "strategy": "momentum", "symbol": "ETH-EUR",
  "params": { "amount": 1800 }, "enabled": true, "paper": false }
```

Fehlende `params` bekommen die Standardwerte der Strategie. `paper: false` handelt nur live, wenn Live-Handel im Agenten freigeschaltet ist.

Wichtige Felder eines Bots:

| Feld | Bedeutung |
|---|---|
| `paper`, `paper_requested` | Tatsächlicher / gewünschter Modus |
| `status`, `status_error`, `hint` | Letzter Zustand als Text, Fehlerflag, Hinweis (z. B. blockierter Kauf) |
| `position`, `positions` | Offene Position gesamt / einzelne Trades (`qty`, `cost`, `value`, `unrealized_pnl` …) |
| `sliced`, `max_trades` | Position aus Teilkäufen (Momentum) / maximale Trades |
| `realized_pnl`, `trades_count`, `wins`, `losses`, `fees` | Statistik – nur Trades im aktuellen Modus |
| `market` | `price`, `change_24h` |
| `hodl` | Momentum: `value` (Bot) gegen `hodl_value` (nur gehalten), `start_capital`, `since`, `deposits` |
| `signals` | Momentum: Indikatoren `[{"text", "tone"}]`, `tone` = `good` / `warn` / `bad` |
| `lookbacks` | Momentum: `entry`, `exit` und `items` `[{"days", "change", "up"}]` |
| `decision` | Momentum: Entscheidung in einem Satz |

## Trades & Ereignisse

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/trades?bot_id=&limit=200` | Trades, neueste zuerst (max. 1000): `side`, `price`, `base_qty`, `quote_amount`, `fee`, `pnl`, `paper`, `order_type` (`limit`/`market`), `reason`, `position_id` |
| GET | `/events?bot_id=&limit=100` | Protokoll: `level` (`info`/`trade`/`error`), `message`, `created_at` |

## Einstellungen

| Methode | Pfad | Body / Zweck |
|---|---|---|
| GET, PUT | `/limits` | `{"max_open_positions": 2, "max_total_invested": 6000, "one_position_per_symbol": true}` – 0 = unbegrenzt |
| GET, PUT | `/paper-fees` | `{"buy": 0.0, "sell": 0.0009}` (Anteil, 0.0009 = 0,09 %) – bucht Papier-Trades neu |
| PUT | `/live-trading` | `{"enabled": true, "confirm": "LIVE"}` – Ausschalten verkauft alle Live-Positionen |
| DELETE | `/paper` | Alle Papier-Trades und offenen Papier-Trades aller Bots löschen – Live-Daten bleiben; `GET /status` meldet die Menge als `paper_data` |

## Revolut X verbinden

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/exchange` | Verbindungsstand, Quelle der Zugangsdaten |
| POST | `/exchange/keypair` | Schlüsselpaar erzeugen, liefert den Public Key für Revolut X |
| PUT | `/exchange/credentials` | `{"api_key": "…"}` speichern |
| DELETE | `/exchange/credentials` | Zugangsdaten entfernen |
| GET | `/exchange/public-ip` | Öffentliche IP des Agenten (für die IP-Freigabe bei Revolut X) |

## Sicherung

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/backup` | Bots, Trades, Einstellungen und Revolut-X-Schlüssel als `.tgz` (ohne API-Token) |
| POST | `/restore` | `.tgz` als Body hochladen – ersetzt alle Daten, Live-Handel ist danach aus |
