# DipAgentX

[![CI](https://github.com/achirus-code/DipAgentX/actions/workflows/ci.yml/badge.svg)](https://github.com/achirus-code/DipAgentX/actions/workflows/ci.yml)

**Trading bots for [Revolut X](https://exchange.revolut.com) and [Trade Republic](https://traderepublic.com) that run 24/7 in Docker – controlled from a tiny macOS menu bar app (and an iPhone app).**

Website: <https://achirus-code.github.io/DipAgentX/> (source in [`docs/`](docs/), served by GitHub Pages)

DipAgentX consists of two parts:

- **Agent** (`agent/`) – a small Python service in a Docker container. It checks the market around the clock, runs
  your bots and places orders on Revolut X and Trade Republic. Run it on any always-on machine: a home server, NAS,
  Raspberry Pi or Mac mini.
- **App** (`macos/`) – a native SwiftUI menu bar app. One icon in the menu bar; a click shows your trades, bots and
  profit, and lets you manage bots, limits and the broker connections. Two tabs above the statistics switch between
  Revolut X and Trade Republic.

The app is available in **English and German** (follows the macOS language, can be changed in the app).

<p align="center">
  <img src="docs/screenshots/bots.png" width="240" alt="Bots">
  <img src="docs/screenshots/trades.png" width="240" alt="Trades">
  <img src="docs/screenshots/bot-detail.png" width="240" alt="Bot detail">
  <img src="docs/screenshots/new-bot.png" width="240" alt="New bot">
</p>

> **Disclaimer:** DipAgentX is a personal project, not financial advice. Trading can lose money. Everything
> starts in **paper mode** (real prices, simulated orders). Only enable live trading once you trust your setup –
> and start small.

> **Trade Republic has no official API.** DipAgentX speaks the protocol of the Trade Republic web app, as documented by
> open-source projects such as [pytr](https://github.com/pytr-org/pytr). Trade Republic's customer agreement doesn't
> allow access through programs it doesn't provide – it may block the access or terminate the account, and the
> protocol may change at any time. Paper trading only reads public market data; live trading logs in to your account.
> Use it at your own risk.

## Features

- **Two brokers side by side:** Revolut X (crypto) and Trade Republic (stocks, ETFs, crypto). Each has its own
  result, bots, trades, trading mode, limits and simulation fees – the tabs above the statistics switch between them.
  Don't need one? Switch it off under *Settings → Brokers* – its bots stop and the tabs disappear.
- **Five strategies**, configurable per bot (see below) – e.g. *“buy ETH-EUR after the price dropped ≥ 1 % in 24 h,
  sell once it has recovered”* or *“a savings plan for an MSCI World ETF on Trade Republic”*.
- **Paper mode by default.** Live trading is switched on in the app per broker, only after the broker is connected and
  after a **double confirmation**. Switching back to paper mode sells all open live positions (with a warning first).
- **Risk limits:** max. open positions, max. invested capital, only one bot per trading pair.
- **No duplicate orders:** each bot holds at most one position, orders are persisted with their own
  `client_order_id` *before* they are sent and reconciled after connection drops, every exchange order is booked
  exactly once, and only one engine may trade per data directory. An order that cannot be found at the exchange
  for minutes stops the bot instead of being guessed about.
- **Revolut X setup from the app:** the agent generates the Ed25519 key pair – the private key never leaves the
  agent; the app shows the public key to register with Revolut X and verifies the API key you get back.
- **Trade Republic from the app:** paper trading works right away without a login (public market data). For live
  trading log in with phone number and PIN and confirm it in the Trade Republic app. Trade Republic ends every login
  after 24 hours; with the PIN saved, the agent starts the next one itself and you only confirm it on your phone.
  Stocks and ETFs trade Monday to Friday 07:30–23:00 – outside these hours the bots wait; every order costs 1 €, which
  the simulation and the "never sell at a loss" rule include.
- **Menu bar app:** total and per-bot profit (realized/open/today), trade history, bot activity log, notifications
  for new trades, launch at login, light & dark mode.

## How it works

```
┌────────────────────────┐  HTTP · bearer token   ┌──────────────────────────────┐  signed REST calls  ┌────────────────┐
│  macOS / iPhone app    │ ─────────────────────▶ │  DipAgentX agent (Docker)     │ ──────────────────▶ │ Revolut X      │
│  trades · bots · setup │ ◀───────────────────── │  REST API · bot engine · DB  │      Ed25519        │ API 1.0        │
└────────────────────────┘      port 3470         │                              │  WebSocket          ├────────────────┤
                                                  │                              │ ──────────────────▶ │ Trade Republic │
                                                  └──────────────────────────────┘  web app protocol   │ (unofficial)   │
                                                                                                        └────────────────┘
```

The agent evaluates every active bot every `TICK_SECONDS` (default 30 s), places market orders on the bot's broker
and stores bots, trades, settings, the Revolut X key and the Trade Republic session in a Docker volume (`/data`,
SQLite).

## Strategies

| Strategy | Buys … | Sells … |
|---|---|---|
| **Dip buyer** | when the price change within a time window (default 24 h) is ≤ the buy threshold (default −1 %); optionally only while the market moves sideways (ADX of the 4-hour candles below a limit) | when the change is back to ≥ the sell threshold (default 0 %) *and* a minimum profit is reached, or at the profit target, or whichever comes first; optionally a trailing stop takes over from the sell signal instead of selling right away; optional stop-loss |
| **Rebound + trailing stop** | when the price is X % below the high of the last N hours | via a trailing stop once the activation profit is reached; optional stop-loss |
| **Price zones** | below a fixed price | above a target price or at a stop price |
| **Savings plan** | a fixed amount every N hours (up to a max. amount / number of buys) | optionally everything at the profit target |
| **AI decides** | when Claude sees an edge – it looks at trend, volatility of the last hours, momentum, optionally the news and optionally the Crypto Fear & Greed index (as background or as a contrarian signal at extremes) every N minutes (model selectable: Opus 5, Sonnet 5, Haiku 4.5; optional minimum confidence before a trade is executed) | when Claude decides to take the profit; never at a loss (only the optional stop-loss may). Needs `ANTHROPIC_API_KEY` on the agent; every check costs a few cents |

> **Going live with open paper positions:** bots keep simulating an open paper position until it is sold, then buy
> live. The savings plan is the exception – it closes its paper position (simulated) with the next instalment and
> continues live, otherwise it could never buy again.

> **Note on the dip buyer:** the 24 h change is a *rolling* window. If the price keeps falling after the buy, the
> 24 h change can return to 0 % while the position is still at a loss. That's why the bot only sells in this mode
> once the **minimum profit** (default 0.25 %, covers fees) is reached. It can't be set below 0 – to cut a loss, set a
> **stop-loss**.

> **Sideways filter (dip buyer):** a dip in a trending market often keeps falling. With *Only buy while ADX (4h)
> below* set (e.g. 23), the bot buys a dip only while the trend strength ADX (14) of the 4-hour candles is below that
> value – the market moves sideways. Selling isn't affected. In a backtest on 18 months of ETH-EUR and BTC-EUR
> (April 2025 – October 2026) the filter together with a stop-loss turned a dip buyer that held its losers into one
> that cut them early; past results don't predict future ones.

## Quick start

### 1. Run the agent (Docker)

Requirements: Docker with Docker Compose v2 on an always-on machine (x86-64 or arm64). Running Home Assistant OS?
Use the [add-on](#home-assistant-add-on) instead.

```bash
git clone https://github.com/achirus-code/DipAgentX.git
cd DipAgentX/agent
cp .env.example .env
sed -i.bak "s/^API_TOKEN=.*/API_TOKEN=$(openssl rand -hex 24)/" .env && rm .env.bak
docker compose up -d                         # pulls ghcr.io/achirus-code/dipagentx (or: up -d --build to build locally)
docker compose logs -f                       # "Engine started …"
```

The agent now listens on port **3470**. The token in `.env` is what the app uses to log in. If you leave `API_TOKEN`
empty, the agent generates one on first start and prints it to the log (it's also stored in the data volume:
`docker compose exec dipagentx cat /data/api_token`).

#### Home Assistant add-on

The agent is also available as a Home Assistant add-on – the same image, configured from the add-on's
**Configuration** tab instead of `.env`:

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**, add `https://github.com/achirus-code/DipAgentX`.
2. Install **DipAgentX**, optionally set an API token under *Configuration* (empty = generated and printed to the
   add-on log), then **Start**.
3. In the app, use the Home Assistant host as the agent address. All data is stored in the add-on's data directory
   and is part of Home Assistant backups.

Details: [homeassistant/dipagentx/DOCS.md](homeassistant/dipagentx/DOCS.md).

### 2. Install the app

Requirements: macOS 14 or newer and the Xcode Command Line Tools (`xcode-select --install`) – Xcode itself isn't needed.

```bash
cd DipAgentX/macos
./build-app.sh
cp -R build/DipAgentX.app /Applications/
open /Applications/DipAgentX.app
```

The chart icon appears in the menu bar. Open **Settings**, enter the agent's address (just the IP or host name,
e.g. `192.168.1.10` – port 3470 is added automatically) and the API token, then **Connect**.

> The app is ad-hoc signed. After each new build macOS may ask whether DipAgentX may use the keychain (where the
> token is stored) – choose *Always Allow*. If Gatekeeper complains on first launch, right-click the app → *Open*.

### 3. Connect Revolut X

In the app: **Settings → Revolut X → Connect** and follow the three steps:

1. **Generate key pair** – created on the agent; the app shows the public key with a *Copy* button.
2. **Register with Revolut X** – the link opens <https://exchange.revolut.com/account/api-keys>. Create a new API key
   with the public key (including the `BEGIN`/`END` lines), allow trading, and – if Revolut X asks for allowed IPs – add
   the agent's public IP shown in the app. The panel stays open during the setup so you can copy back and forth.
3. **Enter the API key** – the agent verifies it right away (balance request) and switches to Revolut X without a
   restart.

### 4. Trade Republic (optional)

Choose the **Trade Republic** tab above the statistics. Bots for stocks, ETFs and crypto can be created right away and
trade in paper mode with Trade Republic's real prices – no login needed. For live trading:

1. **Settings → Trade Republic → Log in**: phone number and PIN of your account. Read the note on the terms first.
2. **Confirm** the login in the Trade Republic app on your phone (accounts with an authenticator app enter its code
   instead). The agent then holds the session; the PIN is only kept if you tick *Remember PIN for the daily login*.
3. Trade Republic ends every login after **24 hours**. With the PIN saved, the agent starts the next login shortly
   before – only while live trading is on or live trades are open – and the app reminds you to confirm it. Without a
   saved PIN, log in again in the app. While logged out, live bots can't trade (not even sell at the stop-loss).

Notes: orders are market orders, every order costs **1 €** (the amount per buy includes it – small amounts pay a lot,
the bot editor shows it). Stocks and ETFs trade on Lang & Schwarz **Monday to Friday 07:30–23:00** (Europe/Berlin);
outside these hours the bots wait. Crypto trades around the clock. Most instruments can be bought in fractions from
1 €.

### 5. Create bots, then go live (optional)

Create bots under **Bots → New bot** – they belong to the broker of the selected tab. They trade in paper mode first:
real prices, simulated orders and fees. When you're happy, enable **Settings → Trading mode → Live trading** for that
broker (double confirmation). All of the broker's existing bots are switched to live then – delete bots that shouldn't
trade with real money beforehand.

## Agent configuration

All settings are optional environment variables in `agent/.env`:

| Variable | Default | Description |
|---|---|---|
| `API_TOKEN` | generated | Token the app authenticates with |
| `EXCHANGE` | `revolutx` | `revolutx` = the real brokers (Revolut X and Trade Republic), `mock` = simulated market for both, for trying things out |
| `TICK_SECONDS` | `30` | How often the bots check the market |
| `TAKER_FEE` | `0.0009` | Fee used for simulated (paper) trades |
| `TZ` | UTC | Time zone, used for "today" in the summary (e.g. `Europe/Berlin`) |
| `REVX_API_KEY` | – | Alternative to the in-app setup: API key here + private key in `agent/secrets/revx_private.pem` (takes precedence; read-only in the app) |
| `MOCK_SPEED` | `1` | Only for `EXCHANGE=mock`: time lapse (60 = one market hour per minute) |
| `ANTHROPIC_API_KEY` | – | Only for the *AI decides* strategy (Claude decides when to buy and sell). Key from console.anthropic.com |
| `TR_APP_VERSION` | built in | Only if Trade Republic refuses the login as outdated: the version of its web app the agent reports |

Live trading, limits and bots are managed in the app and stored in the data volume – not in `.env`.

**Try it without an account:** set `EXCHANGE=mock` (and e.g. `MOCK_SPEED=60`) – the agent then simulates a market
with realistic ups and downs for both brokers (Trade Republic's with its trading hours and 1 € per order).

### Operating the agent

```bash
docker compose logs -f                                # follow the log
docker compose pull && docker compose up -d           # update (or: git pull && … --build)
docker compose down                                   # stop (data stays in the volume)
docker run --rm -v dipagentx_dipagentx-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/dipagentx-backup.tgz -C /data .      # backup of bots, trades, settings and key
```

- **Data** lives in the Docker volume `dipagentx_dipagentx-data` (SQLite database, API token, Revolut X key and
  Trade Republic session with file mode 600). Coming from DipAgent (≤ 1.18)? Move the old volume once – see the [changelog for 1.19.0](CHANGELOG.md).
- **Backup from the app:** *Settings → Backup → Export* saves bots, trades, settings and the Revolut X key (not the
  Trade Republic login – log in again after a restore) as a
  `.tgz`; *Import* restores such a file on any agent (e.g. when moving from Docker to the Home Assistant add-on).
  Importing replaces the agent's data and switches live trading off until you enable it again.
- **Network:** the app talks plain HTTP with a bearer token. Keep port 3470 inside your home network or reach it via a
  VPN such as Tailscale/WireGuard – don't expose it to the internet. Revolut X API keys can additionally be restricted
  to the agent's public IP.
- **One instance only:** the engine takes a lock in `/data`; a second container on the same volume refuses to trade.
- **User:** the container starts as root only to take ownership of `/data` (a bind mount is chowned to uid 10001)
  and drops to the unprivileged user `dipagentx` (uid 10001) before the agent starts. `docker run --user 10001` on a
  volume that already belongs to that user works too.

## Development

```bash
# Agent: tests and a local instance with the simulated market
cd agent
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
DATA_DIR=./data EXCHANGE=mock MOCK_SPEED=120 API_TOKEN=devtoken TICK_SECONDS=5 \
  .venv/bin/uvicorn app.main:app --port 3470

# App: debug build, translation check, screenshots of every screen (light + dark) without the menu bar
cd macos
swift build
python3 scripts/check_localizations.py
./build-app.sh && build/DipAgentX.app/Contents/MacOS/DipAgentX --snapshot /tmp/shots \
  -serverURL 127.0.0.1 -apiToken devtoken -AppleLanguages "(de)"
```

### Project structure

```
agent/                    Python 3.12 · FastAPI · SQLite
  app/main.py             REST API (answers in the app's language via Accept-Language)
  app/engine.py           bot engine: evaluation, limits, idempotent order execution, bookkeeping
  app/strategies/         dip buyer, rebound + trailing stop, price zones, savings plan, AI decides (Claude)
  app/revolutx.py         Revolut X client (Ed25519 request signing)
  app/traderepublic.py    Trade Republic: login, WebSocket client, exchange, trading hours, demo market
  app/credentials.py      key pair generation / storage for the in-app Revolut X setup
  app/backup.py           backup archive (database snapshot + key) for export/import from the app
  app/i18n.py             English/German texts of the agent
  tests/
macos/                    SwiftUI menu bar app (Swift package, no Xcode project needed)
  Sources/DipAgentX/       app, views, API client
  Resources/*.lproj/      localizations (English = source strings, German translations)
  scripts/                translation check
  build-app.sh            builds and signs DipAgentX.app
homeassistant/dipagentx/   Home Assistant add-on (config.yaml, docs, translations) – uses the released agent image
scripts/sync-addon.py     copies the agent version and CHANGELOG.md into the add-on (checked in CI)
```

### Releasing

The Docker image and the Home Assistant add-on come from **one build**: bump `VERSION` in `agent/app/main.py`, add
the `## [x.y.z]` section to `CHANGELOG.md`, run `python3 scripts/sync-addon.py` (writes the version into
`homeassistant/dipagentx/config.yaml` and copies the changelog), commit, then push a tag `vx.y.z`. The release
workflow builds `ghcr.io/achirus-code/dipagentx` for amd64 and arm64 and pushes the `x.y.z` and `latest` tags – Docker
users `docker compose pull`, Home Assistant offers the update in the add-on store.

### Adding a strategy

Create a `Strategy` subclass in `agent/app/strategies/` (name, description and parameters as `L("English", "Deutsch")`)
and register it in `STRATEGIES`. The app renders the settings form from the strategy's parameters automatically – no
app changes needed.

### Translations

The app's source strings are English; `macos/Resources/de.lproj/Localizable.strings` holds the German translations.
To add a language, add `<lang>.lproj/Localizable.strings` (+ `InfoPlist.strings`), list the language in
`Resources/Info.plist` (`CFBundleLocalizations`) and in the agent's `app/i18n.py`. `scripts/check_localizations.py`
(also run in CI) reports missing or unused translations.

### REST API

All routes except `/api/health` require `Authorization: Bearer <API_TOKEN>`; texts are returned in the language of
`Accept-Language` (`de` or English). Summary, limits, paper fees, balances, pairs, instruments, trades and the live
switch take `?exchange=revolutx|traderepublic` (default: Revolut X; `all` for bots and trades of every broker); bots
carry their `exchange` (set when creating one).

| Route | Description |
|---|---|
| `GET /api/status` · `GET /api/summary` | agent status (`exchanges`: every broker), P&L summary of one broker |
| `GET/POST /api/bots` · `PUT/DELETE /api/bots/{id}` | manage bots |
| `POST /api/bots/{id}/start` · `/stop` · `/close` | start/stop a bot, sell its position |
| `GET /api/trades` · `GET /api/events` | trade history, activity log |
| `GET /api/strategies` · `GET /api/pairs` · `GET /api/balances` | strategy schemas, trading pairs, balances |
| `GET /api/instruments?q=` | instruments with names – Trade Republic: search by name, ticker or ISIN |
| `GET/PUT /api/limits` · `GET/PUT /api/paper-fees` · `PUT /api/live-trading` | risk limits, simulation fees, trading mode |
| `PUT /api/brokers/{revolutx\|traderepublic}` | switch a broker on or off |
| `GET /api/exchange` · `POST /api/exchange/keypair` · `PUT/DELETE /api/exchange/credentials` · `GET /api/exchange/public-ip` | Revolut X setup |
| `GET/DELETE /api/traderepublic` · `POST/DELETE /api/traderepublic/login` · `POST /api/traderepublic/login/code` | Trade Republic login (state, start/cancel, authenticator code, log out) |
| `GET /api/backup` · `POST /api/restore` | backup as `.tgz` (database snapshot + Revolut X key), restore from it |

## License

[MIT](LICENSE) © Tillmann David
