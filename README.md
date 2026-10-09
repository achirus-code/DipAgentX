# DipAgentX

[![CI](https://github.com/achirus-code/DipAgentX/actions/workflows/ci.yml/badge.svg)](https://github.com/achirus-code/DipAgentX/actions/workflows/ci.yml)

**Trading bots for [Revolut X](https://exchange.revolut.com) that run 24/7 in Docker – controlled from a tiny macOS menu bar app.**

Website: <https://achirus-code.github.io/DipAgentX/> (source in [`docs/`](docs/), served by GitHub Pages)

DipAgentX consists of two parts:

- **Agent** (`agent/`) – a small Python service in a Docker container. It checks the market around the clock, runs
  your bots and places orders on Revolut X. Run it on any always-on machine: a home server, NAS, Raspberry Pi or Mac mini.
- **App** (`macos/`) – a native SwiftUI menu bar app. One icon in the menu bar; a click shows your trades, bots and
  profit, and lets you manage bots, limits and the Revolut X connection.

The app is available in **English and German** (follows the macOS language, can be changed in the app).

<p align="center">
  <img src="docs/screenshots/bots.png" width="240" alt="Bots">
  <img src="docs/screenshots/trades.png" width="240" alt="Trades">
  <img src="docs/screenshots/bot-detail.png" width="240" alt="Bot detail">
  <img src="docs/screenshots/new-bot.png" width="240" alt="New bot">
</p>

> **Disclaimer:** DipAgentX is a personal project, not financial advice. Crypto trading can lose money. Everything
> starts in **paper mode** (real prices, simulated orders). Only enable live trading once you trust your setup –
> and start small.

## Features

- **Five strategies**, configurable per bot (see below) – e.g. *“buy ETH-EUR after the price dropped ≥ 1 % in 24 h,
  sell once it has recovered”*.
- **Paper mode by default.** Live trading is switched on in the app, only after Revolut X is connected and after a
  **double confirmation**. Switching back to paper mode sells all open live positions (with a warning first).
- **Risk limits:** max. open positions, max. invested capital, only one bot per trading pair.
- **No duplicate orders:** each bot holds at most one position, orders are persisted with their own
  `client_order_id` *before* they are sent and reconciled after connection drops, every exchange order is booked
  exactly once, and only one engine may trade per data directory. An order that cannot be found at the exchange
  for minutes stops the bot instead of being guessed about.
- **Revolut X setup from the app:** the agent generates the Ed25519 key pair – the private key never leaves the
  agent; the app shows the public key to register with Revolut X and verifies the API key you get back.
- **Menu bar app:** total and per-bot profit (realized/open/today), trade history, bot activity log, notifications
  for new trades, launch at login, light & dark mode.

## How it works

```
┌────────────────────────┐  HTTP · bearer token   ┌──────────────────────────────┐  signed REST calls  ┌───────────┐
│  macOS menu bar app    │ ─────────────────────▶ │  DipAgentX agent (Docker)     │ ──────────────────▶ │ Revolut X │
│  trades · bots · setup │ ◀───────────────────── │  REST API · bot engine · DB  │ ◀────────────────── │  API 1.0  │
└────────────────────────┘      port 3470         └──────────────────────────────┘      Ed25519        └───────────┘
```

The agent evaluates every active bot every `TICK_SECONDS` (default 30 s), places orders on Revolut X (market orders;
the momentum trend follower fee-free limit orders first) and
stores bots, trades, settings and the Revolut X key in a Docker volume (`/data`, SQLite).

## Strategies

| Strategy | Buys … | Sells … |
|---|---|---|
| **Dip buyer** | when the price change within a time window (default 24 h) is ≤ the buy threshold (default −1 %) | when the change is back to ≥ the sell threshold (default 0 %) *and* a minimum profit is reached, or at the profit target, or whichever comes first; optionally a trailing stop takes over from the sell signal instead of selling right away; optional stop-loss |
| **Rebound + trailing stop** | when the price is X % below the high of the last N hours | via a trailing stop once the activation profit is reached; optional stop-loss |
| **Price zones** | below a fixed price | above a target price or at a stop price |
| **Savings plan** | a fixed amount every N hours (up to a max. amount / number of buys) | optionally everything at the profit target |
| **Momentum trend follower** | for ETH and BTC: holds a share of its capital that follows the trend, in 10 % steps – the share of six lookbacks (14 to 60 days on the 4-hour closes) pointing up, less in very volatile markets, at least 50 % while the futures funding rate shows panic, optionally halved on large exchange inflows. Each step is its own trade of about 10 % of the capital; live on Revolut X as fee-free limit orders that follow the price – what isn't filled within 10 min of a rebalancing goes out at market | when the target step falls – one trade per step, also at a loss, the same way with limit orders first. Gains stay in the bot and are reinvested |
| **AI swing trader** | when Claude (Fable 5.1 by default) sees a setup from its playbook in the regime a backtest of six years of ETH/BTC data supports: 4 h uptrend with a trending 1 h chart (ADX ≥ 25), entry on a breakout of the 2 h/24 h high on volume or a pullback to the 15 min EMA20/VWAP in a 1 h uptrend, stop below the 1 h swing low (~3 %), target 3R, held for hours to days. Claude reads the candlestick chart as an image and the numbers behind it (trend on four timeframes, levels, volume, order book, BTC as the leader) plus the backtest record per setup and its own results. A scanner wakes it only for the backtested setups in the regime; checks follow a monthly API budget (default 50 $). Size 25–100 % of the amount by setup quality; daily loss limit and a pause after losing streaks. Intraday variants with tight stops lost money in every backtest – details in [docs/ki-swingtrader.md](docs/ki-swingtrader.md) (German) | by itself every 30 s at Claude's take-profit or stop (never further than the max. stop-loss, 5 %, never lowered), optional break-even/trailing stop (off by default – they cost money in the backtest), or when Claude closes. Live **only fee-free limit orders** – unfilled ones are cancelled, never sent to the market. Needs `ANTHROPIC_API_KEY` |

> **Going live with open paper positions:** bots keep simulating an open paper position until it is sold, then buy
> live. The savings plan is the exception – it closes its paper position (simulated) with the next instalment and
> continues live, otherwise it could never buy again.

> **Note on the momentum trend follower** (full rules and backtests in German:
> [docs/momentum-trendfolger.md](docs/momentum-trendfolger.md)): over less than a month its result is chance; in strong rallies it catches
> only about 55–70 % of the rise (it steps in gradually). The exchange-inflow brake only helps with fresh data and
> Coin Metrics revises values later – it is off by default. Without a fresh funding rate from Binance the bot uses
> Bybit's (the status says so); if neither can be fetched, the status starts with a ⚠ warning and the card shows it as
> a hint: the floor is off until the data is back. The bot counts as
> one open position for the limits, however many trades it holds; it can go from paper to live with open paper trades
> (they are closed simulated and the bot starts afresh with its capital).
>
> **Drawdowns – 2018 was worse than 2022.** Replaying the rule on Binance 4-hour USDT closes (Dec 2017 – Jun 2019,
> 0.09 % fee per side, no funding floor – the perpetual futures didn't exist yet) gives for **2018**:
>
> | | ETH bot | ETH hold | BTC bot | BTC hold |
> |---|---|---|---|---|
> | 2018 result | −15 % | −82 % | −38 % | −72 % |
> | largest drawdown in 2018 | 49 % | 94 % | 47 % | 81 % |
> | without volatility cap | 58 % | | 49 % | |
> | Dec 2017 – Jun 2019 | +113 % | −31 % | +134 % | +12 % |
>
> It entered 2018 fully invested at the top and lost on the false recoveries of the bear market before it was out.
> Expect drawdowns of **around 50 %**, not just the 30–39 % of 2022–2026; the volatility cap is why it stays below
> 60 %. Only invest what you can see halved.
>
> **Taxes (Germany, no tax advice):** coins sold within a year of buying are a *private sale* (§ 23 EStG), taxed at
> your personal income-tax rate – not the 25 % flat rate. Gains up to 1,000 € per year are tax-free, but it is an
> allowance limit (*Freigrenze*): at 1,001 € the whole amount is taxable. Losses only offset gains from private
> sales (also carried back one year or forward). The bot rebalances about twice a week, so practically every gain is
> taxable, while holding for over a year would be tax-free. The tax office matches sales to buys first-in-first-out
> per wallet, which can differ from the trade the bot sells – use the transaction export of Revolut X for the tax
> return, not the bot's per-trade results. Example: 3,000 € gain in a year at a 42 % tax rate (plus solidarity
> surcharge/church tax) costs about 1,300 €.

> **Note on the dip buyer:** the 24 h change is a *rolling* window. If the price keeps falling after the buy, the
> 24 h change can return to 0 % while the position is still at a loss. That's why the bot only sells in this mode
> once the **minimum profit** (default 0.25 %, covers fees) is reached. It can't be set below 0 – to cut a loss, set a
> **stop-loss**.

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

### 4. Create bots, then go live (optional)

Create bots under **Bots → New bot**. They trade in paper mode first: real prices, simulated orders and fees. When
you're happy, enable **Settings → Trading mode → Live trading** (double confirmation). All existing bots are switched
to live then – delete bots that shouldn't trade with real money beforehand.

## Agent configuration

All settings are optional environment variables in `agent/.env`:

| Variable | Default | Description |
|---|---|---|
| `API_TOKEN` | generated | Token the app authenticates with |
| `EXCHANGE` | `revolutx` | `revolutx` = real exchange, `mock` = simulated market for trying things out |
| `TICK_SECONDS` | `30` | How often the bots check the market |
| `TAKER_FEE` | `0.0009` | Fee used for simulated (paper) trades |
| `TZ` | UTC | Time zone, used for "today" in the summary (e.g. `Europe/Berlin`) |
| `REVX_API_KEY` | – | Alternative to the in-app setup: API key here + private key in `agent/secrets/revx_private.pem` (takes precedence; read-only in the app) |
| `MOCK_SPEED` | `1` | Only for `EXCHANGE=mock`: time lapse (60 = one market hour per minute) |
| `ANTHROPIC_API_KEY` | – | Only for the *AI decides* strategy (Claude decides when to buy and sell). Key from console.anthropic.com |
| `LOG_LEVEL` | `info` | `warning` = problems only, `info` = what the bots do, `debug` = also every exchange request and every app request |

Live trading, limits and bots are managed in the app and stored in the data volume – not in `.env`.

**Try it without Revolut X:** set `EXCHANGE=mock` (and e.g. `MOCK_SPEED=60`) – the agent then simulates a market
with realistic ups and downs.

### Operating the agent

```bash
docker compose logs -f                                # follow the log
docker compose pull && docker compose up -d           # update (or: git pull && … --build)
docker compose down                                   # stop (data stays in the volume)
docker run --rm -v dipagentx_dipagentx-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/dipagentx-backup.tgz -C /data .      # backup of bots, trades, settings and key
```

- **Data** lives in the Docker volume `dipagentx_dipagentx-data` (SQLite database, API token, Revolut X key with file
  mode 600). Coming from DipAgent (≤ 1.18)? Move the old volume once – see the [changelog for 1.19.0](CHANGELOG.md).
- **Backup from the app:** *Settings → Backup → Export* saves bots, trades, settings and the Revolut X key as a
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
`Accept-Language` (`de` or English).

| Route | Description |
|---|---|
| `GET /api/status` · `GET /api/summary` | agent status, P&L summary |
| `GET/POST /api/bots` · `PUT/DELETE /api/bots/{id}` | manage bots |
| `POST /api/bots/{id}/start` · `/stop` · `/close` | start/stop a bot, sell its position |
| `GET /api/trades` · `GET /api/events` | trade history, activity log |
| `GET /api/strategies` · `GET /api/pairs` · `GET /api/balances` | strategy schemas, trading pairs, balances |
| `GET/PUT /api/limits` · `PUT /api/live-trading` | risk limits, trading mode |
| `GET /api/exchange` · `POST /api/exchange/keypair` · `PUT/DELETE /api/exchange/credentials` · `GET /api/exchange/public-ip` | Revolut X setup |
| `GET /api/backup` · `POST /api/restore` | backup as `.tgz` (database snapshot + Revolut X key), restore from it |

Every route with its bodies and fields: [`docs/api.md`](docs/api.md) (German).

## License

[MIT](LICENSE) © Tillmann David
