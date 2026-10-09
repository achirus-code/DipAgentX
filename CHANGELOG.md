# Changelog

All notable changes to DipAgentX (formerly DipAgent) are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **Own icon for the lead-lag bot** in the iOS and macOS apps: two step lines – BTC jumps first, the coin follows a
  moment later – on a tile from Bitcoin orange to Ethereum blue, with the coin badge of the traded coin like the
  momentum follower.
- **Menu bar icon with an open trade** (macOS): the circle is a bit larger (full icon height), so it no longer looks
  smaller than the idle chart; the Revolut X stays the same and overlaps it.

## [1.37.0] – 2026-10-09

### Added

- **New strategy "Lead-lag: follows BTC"** (`leadlag`). Buys the coin within seconds after BTC-USDT jumped by at least
  0.5 % in one minute while the coin rose less than half as much, and sells after 15 minutes (stop-loss 1.5 %). It
  trades the signal of the lead-lag measurement: the monitor hands every jump to the bots and wakes the engine at once
  instead of at the next 30-second tick. Market orders, because speed matters more than the fee. Each buy says how
  many seconds after the jump the order went out. Meant for paper trading first – the measurement
  (`/api/research/leadlag`) still has to show that Revolut X lags like Binance. Coins must be in `LEADLAG_COINS`
  (default BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC, SUI).

## [1.36.1] – 2026-10-09

### Changed

- **Lead-lag measurement for more coins:** besides ETH-EUR it now measures BTC-EUR itself (does Revolut X lag the
  world market?) and SOL, XRP, DOGE, ADA, LINK, AVAX, LTC and SUI against EUR – one Revolut X request and one Binance
  request for all of them, as before every 10 s / 2 s. Other coins with `LEADLAG_COINS`. The summary shows every coin
  by jump size and lag, with the key figures (jump ≥ 0.5 %, coin lagged) on top.
- **The measurement survives restarts:** start of the measurement, number of restarts, error counts and the time of
  the last jump are stored in the database; events still waiting for their 1/5/15-minute follow-ups are resumed after
  a restart, or marked "interrupted" when a follow-up fell into the downtime (they don't distort the averages).

### Added

- `DELETE /api/research/leadlag?scope=interrupted|before|all` to clean up the measurement (`before=<ms>` for older
  events, `all` starts over; `reset_counters=true` clears restarts and errors).

## [1.36.0] – 2026-10-09

### Added

- **Momentum trend follower: "BTC as a brake"** (off by default, for coins other than BTC). The ETH bot then holds at
  most what BTC's own trend allows – the share of BTC's six lookbacks that are up, times ETH's volatility factor – and
  keeps the funding floor only while BTC's funding shows panic too. Shown in the bot as its own signal ("BTC trend 4
  of 6 up – no brake" / "– at most 70 %"). Backtest ETH-EUR 2020-03 to 2026-09: largest drop −29 % instead of −40 %,
  worst 12 months −19 % instead of −31 %, ×43 instead of ×46 – it lags in strong ETH rallies
  (`docs/momentum-trendfolger.md`, section 5a).

## [1.35.1] – 2026-10-09

### Added

- **Lead-lag measurement "does ETH follow BTC?"** – measurement only, never trades. A backtest on Binance found that
  after BTC-USDT jumps by at least 0.5 % within a minute while ETH-EUR has moved less than half of that, ETH-EUR rises
  by another 0.4–0.7 % on average within 15 minutes (2021–2026, every year positive). Whether ETH-EUR on Revolut X
  lags the same way can only be measured live: the agent now polls BTC-USDT, ETH-USDT and ETH-EUR on Binance every
  2 s (public, no key) and ETH-EUR on Revolut X every 10 s (every 2 s in the minute after a jump, backs off after
  errors), stores every BTC move of at least 0.3 % in 60 s and ETH-EUR on Revolut X and Binance after 1, 5 and
  15 minutes. `GET /api/research/leadlag` shows the events and the averages by jump size, including the taker round
  trip (buy at the ask, sell at the bid). Off with `LEADLAG_MONITOR=0`.

## [1.35.0] – 2026-10-09

### Changed

- **"AI decides" becomes the AI day trader on Claude Fable 5.1**, built around how a disciplined day trader works
  (details in `docs/ki-daytrader.md`):
  - **Top-down market read:** trend, structure (higher highs/lows), EMAs, RSI, ADX, efficiency ratio and ATR on 4 h,
    1 h, 15 min and 5 min, one label for the market phase (trend, range, chop), support/resistance zones from swing
    points, the previous day's high/low/close, VWAP since 00:00 UTC, relative volume, Bollinger squeeze, the order
    book (depth and imbalance) and BTC as the market leader for other coins.
  - **Claude sees the chart:** a candlestick image with three panels (1 h for 3 days, 15 min for 24 h, 5 min for 3 h)
    with EMA20/50, VWAP, volume, levels and the position's entry, stop and take-profit – drawn without an extra
    library.
  - **A playbook and a process** in the prompt: context, location, setup (trend pullback, breakout/retest, range
    support, confirmed reversal, momentum), confirmation, stop at the invalidation, at least 1.5 : 1, size by quality.
  - **The plan runs between checks:** take-profit and stop every tick, stop to break-even at +1R, optional trailing
    stop from +1R, a time limit that wakes Claude. A stop is never lowered and never further away than the
    "Max. stop-loss" (3 %).
  - **Discipline in code:** daily loss limit (6 % of the amount), a 2-hour pause after 3 losses in a row, position size
    25–100 % of the amount by setup quality, no buy without a stop.
  - **Track record and notes:** every trade with setup, result in % and R, best price during the trade and exit
    reason; Claude sees win rate and average R by setup and keeps notes from one check to the next.
  - Models: Fable 5.1 (default), Opus 5.5, Sonnet 5.5, Haiku 5.5; thinking depth automatic (medium at setups and open
    trades, low for routine looks). A declined request is retried on Anthropic's recommended fallback model.
- **Only limit orders:** live orders of the AI day trader go out as fee-free post-only limit orders a cent inside the
  spread that follow the price, like the momentum bot – but what isn't filled within the waiting time is cancelled
  instead of going to the market. Stop and take-profit sales too; only "Sell position now" sells at market.

### Added

- **Scanner:** on every new 5-minute candle cheap rules look for a breakout, a breakdown, a pullback in an uptrend, a
  capitulation or a volume spike and wake Claude early; price alerts Claude sets and large moves wake it too.
- **Monthly API budget** for the AI day trader (default 100 $ per bot): the bot measures what every check costs and
  spreads the rest of the budget evenly over the rest of the month. The status shows what was spent this month.
- Candles carry the volume, and the Revolut X order book can be read.

## [1.34.0] – 2026-10-08

### Changed

- **Momentum: sales as fee-free limit orders too.** Revolut X charges no fee for maker orders on either side, so the
  trend follower sells a cent above the best ask first, like it buys a cent below the best bid. Sales by hand and
  "close all" still go out at market right away.
- **Limit orders follow the price:** when the market moves away from a waiting limit order, the next check cancels it,
  books what it filled and places the rest at the new best price (a partly filled buy stays one trade).
- **Waiting time per rebalancing instead of a 30-minute market pause:** the waiting time (10 min) counts once from the
  first order of a rebalancing, also when it takes several trades; what is left after it goes out at market, and the
  next rebalancing waits as a limit order again. Before, one limit order that wasn't filled completely sent every
  order of the next 30 minutes to the market – on the first live day more than half of the buys paid the fee.
- A limit order the exchange refuses (post-only would have crossed the book) is no error any more and doesn't pause
  the bot: the next check tries again at the price of then.

### Added

- **Apps: a new icon for the momentum trend follower** – a green tile with a rising arrow over three steps, and for
  the ten most important coins (BTC, ETH, XRP, BNB, SOL, DOGE, ADA, TRX, LINK, LTC) a small coin badge in the corner,
  in the bot list, the bot details and the editor.
- **Funding rate from Bybit when Binance has none:** without a fresh rate from Binance the momentum follower uses the
  same contracts on Bybit, and the status says "(Bybit)". Only when both fail is the floor off (⚠ warning as before).

### Fixed

- A refused order could stay behind as an order "in flight" in the database when the check otherwise changed nothing.

## [1.33.3] – 2026-10-08

### Changed

- Bot status: each indicator gets a small traffic light (red, orange, green – the light of its effect is on)
  instead of a dot.

## [1.33.2] – 2026-10-08

### Changed

- The indicator dots in the status are smaller than the pulsing status dot.

## [1.33.1] – 2026-10-08

### Changed

- Bot status: a small coloured dot in front of each indicator instead of coloured text.

## [1.33.0] – 2026-10-08

### Added

- **Remove all paper data** (settings → trading mode, while live trading is on): deletes every paper trade,
  simulated transaction and open paper trade of all bots; live trades and positions stay. The button only shows up
  while there is paper data (`paper_data` in `GET /api/status`, new `DELETE /api/paper`).

## [1.32.6] – 2026-10-08

### Changed

- Comparison with holding: the difference is labelled "Bot performance".

## [1.32.5] – 2026-10-08

### Changed

- Comparison with holding: "Difference to the bot", with the difference in percent of the money put in below.

## [1.32.4] – 2026-10-08

### Changed

- The percent moved from the bots to the total result at the top: the total in percent of the capital of the bots
  that manage one (momentum). The bots show their result in money only again.

## [1.32.3] – 2026-10-08

### Added

- Momentum bots show their total result in percent as well (of the money put in), on the card and in the details.

## [1.32.2] – 2026-10-08

### Added

- Indicators: the trend shows every lookback (14 to 60 days) in detail – the price change over it and whether it
  counts as up or down, with the thresholds.

## [1.32.1] – 2026-10-08

### Changed

- Bot details: the indicators open with an **Indicators** button (popover on the Mac, sheet on the iPhone) instead of
  taking up a section of their own.

## [1.32.0] – 2026-10-08

### Added

- Bot details (momentum): **Indicators** – each indicator on its own line in green, orange or red by what it means
  for the decision – and the **decision** below in one sentence (target, what the bot holds, what it does).
- Profit history: a **HODL** switch per momentum bot shows what holding would have made since the bot's start, as a
  dashed line in a paler shade of the bot's colour (new endpoint `GET /api/bots/{id}/hodl`).

### Changed

- The comparison with holding no longer starts afresh when the amount changes: the change counts as money put in
  (or taken out), which holding "buys" at the price of then. A paper reset or a switch of the mode still restarts it.

## [1.31.1] – 2026-10-08

### Changed

- Limit buys go out a cent below the best bid. Before, at exactly the bid, the exchange refused many of them
  (post-only would have crossed the book when the price ticked in the meantime), and the bot then bought at market
  with a fee for 30 minutes.
- Sales always go out at market right away: Revolut X charges a sale its fee as a limit order too, so waiting for a
  better price only risked a worse one.
- Mac: the comparison with holding in the bot details is no longer cut off.
- Momentum: the indicators in the status are coloured by what they mean for the decision – green lets the bot
  invest, orange holds it partly back (volatility cap, missing data), red keeps it out (weak trend, inflow brake).
- No red "open live position/trades" any more – the green LIVE badge says it.

## [1.31.0] – 2026-10-08

### Added

- Every live trade records how its order went out: as a fee-free **limit order** or as a **market order**. The
  history marks limit trades with "LIMIT · NO FEE" and shows the fee of any other trade; the trade details name the
  order type.
- **Fees per bot**: the bot details show the sum of all fees of the bot's trades (in its current mode).
- **Against holding** (momentum follower): the bot details compare the bot's capital now with having bought the coin
  with it at the start and simply held (no fees) – with the difference in euros. The comparison starts with the
  amount and again after a new amount, a reset or a switch between paper and live; for a running bot it starts at
  its first open trade.

## [1.30.1] – 2026-10-08

### Fixed

- A bot's result, trade count and wins/losses only count trades of its current mode. After switching a bot from
  paper to live it showed the simulated trades and the paper loss of closing the paper slices as its result.

## [1.30.0] – 2026-10-06

Performance release: less CPU on the Mac and on small Home Assistant hosts, fewer requests, far fewer log lines.

### Added

- **Log level** (`LOG_LEVEL`, add-on option `log_level`): `warning` = problems only, `info` = what the bots do
  (default), `debug` = also every request to the exchange and from the apps.

### Changed

- The request lines of the exchange client and the access log are only written at `debug` – before, they were many
  thousands of lines a day in the add-on log.
- Docker health check every 5 minutes instead of every 30 seconds: each check starts a Python interpreter, which on a
  small Home Assistant box cost more CPU than the agent itself (Home Assistant's watchdog checks the agent anyway).
- macOS/iPhone app: while the panel is closed (iPhone: in the background) the app only fetches the bots and the latest
  trades – enough for the menu bar icon and the notifications. Everything else is loaded when the panel opens.

### Fixed

- macOS app: about 10 % CPU while the panel was closed – the pulsing status dot of every active bot kept the hidden
  panel redrawing at the display's frame rate. It now pulses only while it can be seen.
- Momentum trend follower: the 4-hour candles were fetched again on every check (every 30 s per bot) instead of once
  per new candle.

## [1.28.0] – 2026-10-05

Built on 1.19.0: Trade Republic and everything from 1.20.0 to 1.27.0 were removed (the monthly trend followers, the
first momentum bot, paper reset per broker). Version numbers go on from 1.27.0 so updates and the Docker image
tags stay unique.

### Added

- **Momentum trend follower** (`momentum`) for ETH-EUR and BTC-EUR: invests the more of its capital the more of six
  lookbacks (14 to 60 days, 4-hour closes) point up, in 10 % steps – fully invested in a clear uptrend, in cash in a
  downtrend. Less in very volatile markets (above 100 % a year), a 50 % floor while the 7-day funding rate of the
  Binance perpetual futures is below +2 % a year, optionally halved on large exchange inflows (Coin Metrics, off by
  default). Each step is its own trade of about 10 % of the capital; it only trades when the target step changes,
  also at a loss, and reinvests its gains.
- **Fee-free limit orders** for the momentum follower live on Revolut X: buys at the best bid, sells at the best ask
  (post-only, maker 0 % instead of 0.09 %). What isn't filled within 10 minutes (adjustable) is cancelled and goes
  out as a market order; after an unfilled or rejected limit order the next 30 minutes use market orders.
- The momentum follower counts as **one open position** for the limits and the apps show it as one position with
  its opened trades below. It may switch from paper to live with open paper trades: they are closed (simulated) and
  the bot starts afresh with its capital.
- If the Binance funding rate is unavailable, the momentum follower's status starts with a **⚠ warning** (since when,
  the floor is off) and the card shows it as a hint.
- README: the momentum follower's **2018 drawdowns** (replay on Binance data: ~50 %, hold 81–94 %) and a concrete
  **German tax note** (private sales within a year, 1,000 € Freigrenze, FIFO per wallet).
- Bot documentation `docs/momentum-trendfolger.md` (German): the three building blocks, order handling and costs,
  execution timing, parameters, worked examples and the backtest results 2017–2026.

### Changed

- **New icon with the X of Revolut X** in the bottom-right corner – app icon (macOS, iPhone), menu bar icon,
  Home Assistant add-on and website.

## [1.19.0] – 2026-10-05

### Changed

- **DipAgent is now DipAgentX.** New repository <https://github.com/achirus-code/DipAgentX> (the old URL redirects),
  website <https://achirus-code.github.io/DipAgentX/>, Docker image `ghcr.io/achirus-code/dipagentx`, Home Assistant
  add-on `dipagentx`, app `DipAgentX.app` (bundle ID `de.achirus.DipAgentX`).
- **Taken over automatically:** the agent renames `dipagent.db` to `dipagentx.db` on start; the macOS app takes over
  the settings and the API token of the old app; backups made with DipAgent can still be restored.
- **Docker – move the data volume once.** The compose project and volume are now called `dipagentx`. Stop the old
  container and copy the volume before starting the new one:
  `docker compose -p dipagent down`, then
  `docker volume create dipagentx_dipagentx-data && docker run --rm -v dipagent_dipagent-data:/from -v dipagentx_dipagentx-data:/to alpine cp -a /from/. /to/`,
  then `docker compose up -d`.
- **Home Assistant – new add-on.** The add-on slug changed, so Home Assistant sees a new add-on. Make a backup in the
  app (*Settings → Backup → Export*), remove the old repository and add-on, add `https://github.com/achirus-code/DipAgentX`,
  install **DipAgentX** and restore the backup from the app.
- The macOS app is a new app: delete `/Applications/DipAgent.app` after installing `DipAgentX.app`.

## [1.18.0] – 2026-10-04

### Added

- **Dip buyer: trailing after the sell signal.** New rule *Trailing after the sell signal* (0 = off, the default).
  When the sell rule is met – the change has recovered (e.g. 24 h back to ≥ 0 %), the profit target is reached, or
  whichever comes first – the bot no longer sells right away. A trailing stop follows the price from there and sells
  once it falls this far below its high since the signal – never below the minimum profit; the stop-loss still sells
  immediately. The card shows "until trailing starts" and then the trailing stop.

## [1.17.1] – 2026-10-03

### Fixed

- **Paper mode: no fee on buys.** Revolut X charges nothing for a buy placed as a maker order, but the simulation
  charged the taker fee on buys too.

### Added

- **Paper mode fees are adjustable** under Settings, prefilled with buy 0 % / sell 0.09 %. Changing a fee rebooks all
  simulated trades and open simulated positions (coins bought, fees, proceeds, profit); live trades are untouched.
  Existing simulated trades are corrected once on the first start of this version.

## [1.17.0] – 2026-10-03

### Added

- **App: profit history.** The statistics card shows the realized result as a small curve. *Chart* opens a window
  with one line per bot (or all together), every buy (▲) and sale (●) as a point, 7 days to all time, paper and live
  apart. Bots can be switched on and off; a table shows each bot's trades, volume, result and fees in the period.
- **App: trade details.** A click on a trade – in the chart, in the trade list or under a bot's recent trades – shows
  when and at what price it was bought and sold, how long it was held, the price change, the fees and the result.
  The buy and the sale that belong together link to each other.
- **Sales are linked to their buys.** Every trade now stores which of the bot's trades it opened, added to or
  closed – so the app shows the exact buy of a sale. Trades from before this version are matched by quantity and order.

## [1.16.0] – 2026-09-30

### Changed

- **The pause also follows a buy.** *Pause after selling* is now *Pause after buy or sale*: the bot waits that long
  after every buy and every sale before it buys again – so with several trades the next one doesn't open right
  after the last. With one trade at a time nothing changes (it can't buy while its trade is open).

- **App: profits easier to read.** In light mode profits use a darker green (the system green was too light on
  light backgrounds); the statistics card no longer turns green behind green numbers.
- **App: PAPER and LIVE badges easier to read** – a darker orange and green in light mode.

## [1.15.0] – 2026-09-30

### Added

- **Min. time between trades** (Dip buyer, Rebound + trailing stop, Price zones): a new trade only when at least this
  many days have passed since the last buy – e.g. 1 or 2. 0 = off (default).

### Changed

- **The card shows both buy conditions** while trades are open: the strategy's buy threshold and the distance to the
  open trades, each with how far the price still has to fall (or *already reached*) – the headline is the stricter one.
- **App: trades show their result in percent** next to the amount (e.g. *+1.03 € +2.06 %*) – in the trade list and
  under the bot's recent trades. Relative to what the sold coins cost, fees included.
- **App: Claude's decisions** in the bot view scroll inside a fixed height once there are more than a few – the
  sections below stay in reach. The list now holds all loaded answers instead of the last 30.
- **App: faster bot view and editor.** Claude's decisions are built lazily (only the rows in view). The trading
  pair is chosen from a searchable list instead of a menu with several hundred pairs that was rebuilt on every
  keystroke in the editor.

## [1.14.0] – 2026-09-30

### Added

- **Reset a bot's paper result.** In the bot view of a paper bot, *Reset paper result* deletes the bot's simulated
  trades and discards its open paper trades – the result starts at zero. Live trades are never deleted; a bot with
  an open live trade or an order in flight refuses.

### Fixed

- **App: new bot settings after an agent update.** The app reloads the strategies when the agent's version
  changes – before, new settings (e.g. *Max. open trades*) only appeared after restarting the app.

## [1.13.0] – 2026-09-30

### Added

- **Several trades per bot.** Dip buyer, Rebound + trailing stop and Price zones get *Max. open trades* (default 1 –
  existing bots behave as before) and *Distance between trades*: the bot may buy again while earlier trades are
  open, but only once the price is that far below the lowest open entry. Each trade has its own entry, target and
  stop and is sold on its own. Every trade counts towards *Max. open positions* and the capital limit. Positions
  stored by older versions are taken over as one trade.
- **App: open trades on the card and in the bot view.** The card shows *Open trades 2/3* with one line per trade
  (value, result, its target); the bot view has a card per trade with *Sell this trade now*. The headline shows the
  distance to the next trade. The editor shows how much can be invested at the same time.

- **App: quit button** at the top right of the panel. It asks first – the bots keep trading on the agent – with a
  "Don't ask again" checkbox; *Settings → Ask before quitting* turns the question back on.

### Changed

- **App: bot cards** show only the percentage to the next trade (e.g. *−1.80 % to buy*); the amount in the quote
  currency had too many decimals for cheap coins.
- **App: open position on the bot card** shows its size – current value and invested amount – above amount and
  entry price.

## [1.12.0] – 2026-09-29

### Added

- **AI decides: Fear & Greed index.** New option per bot – *Off* (default), *As background information* or *As a
  contrarian signal at extremes*. The agent fetches the Crypto Fear & Greed index (alternative.me, no key needed,
  cached for an hour) and adds today's value with the last seven days to Claude's market brief. In contrarian
  mode Claude is told to use it only below 25 (leaning towards patient buying) and above 75 (leaning towards
  taking profits) and to ignore it in between. If the index cannot be fetched, the brief goes out without it.
- **Bot cards show how far the next trade is.** Instead of the coin price, a running bot's card leads with the
  distance to its trigger in percent and in the quote currency (e.g. *−1.80 % · −42.00 $ to buy*, *+2.40 % · +58.00 $
  to sell*, or the distance to the trailing stop), followed by the trigger price, the stop and the current price in
  small print. Strategies without a fixed trigger (AI decides, the savings plan's next instalment) show their note.
  Needs agent 1.12 – the agent now reports the prices each bot waits for.

## [1.11.0] – 2026-09-29

### Added

- **Statistics per trading mode.** The summary keeps paper and live results apart: the card shows the active
  mode's numbers (result, realized, open, today, fees, trades), the other mode's result is a small footnote.
  Open positions count in the mode they were bought in. Switching modes deletes nothing.
- **App: prompt page.** The AI bot's "Additional instructions" are edited on their own page with a full-height
  text area, character count and "Clear"; the editor shows a preview and an "Edit…" button.
- **App: capital limit in the statistics.** What the bots may still invest and how much of the limit is in use –
  so a new bot is not sized straight into the limit. The exchange balance became a small footnote.

### Changed

- **App: "Ask now"** is a small round button with a brain symbol and asks for confirmation before the extra
  Claude call.

## [1.10.0] – 2026-09-29

### Added

- **AI decides: "Ask now".** A small button on the bot card gets a fresh decision from Claude right away instead
  of waiting for the next check (`POST /bots/{id}/ask`). One extra Claude call; minimum confidence, cooldown,
  limits and the no-loss rule apply as in a scheduled check, and the regular rhythm continues from that moment.

## [1.9.0] – 2026-09-29

### Added

- **Blocked buys stay visible.** A buy signal skipped by the limits (capital, open positions, one per symbol) used
  to be in the bot status for a single tick – *AI decides* signals once per check, so the skip was gone right
  away. The engine now keeps the blocked buy in the bot state and reports it as a `hint` until the limits allow
  it; the status then just says "Buy signal". The app shows the hint in orange on the bot card and in the
  details, and posts a notification when a bot becomes blocked.
- **AI decides: minimum confidence.** New per-bot parameter – buy and sell decisions below the threshold are not
  executed and stay visible as "below the threshold, not executed" until the next check. Default 0 keeps every
  decision executed. Claude is asked for an honestly calibrated confidence (50 = coin toss, 80+ = clear setup).

### Fixed

- **App: empty window on first open.** The SwiftUI settings scene opened an empty "DipAgent Settings" window the
  first time the app was activated; the entry point is now plain AppKit.
- **App: start tab.** The panel opens on *Bots*; only when the connection failed or is not configured it opens
  on *Settings*. The choice is made when the panel first opens, not before the first connection attempt.

## [1.8.0] – 2026-09-29

### Added

- **AI decides: additional instructions.** An optional free-text field in the bot's rules – your own rules or
  focus for Claude (e.g. "only buy on strong dips") – is sent with every check. New parameter type `text` for
  strategies; the app renders it as a multi-line field.

## [1.7.1] – 2026-09-29

### Changed

- AI decides: the model options are just the model names; the app shows the estimated cost per check and per
  month under the field. Without an Anthropic API key on the agent the *AI decides* card in the bot editor is
  greyed out with a note.

## [1.7.0] – 2026-09-29

### Added

- **AI decides: the model is selectable per bot** – Claude Opus 5 (~4 ct per check), Claude Sonnet 5
  (~1.5 ct) or Claude Haiku 4.5 (~1 ct). New default is Sonnet 5; existing AI bots switch to it unless you
  pick Opus in the bot editor.

## [1.6.0] – 2026-09-29

### Added

- **Claude's decision history.** Every answer of an *AI decides* bot is kept (action, how sure Claude was, the
  reason, price and open result at that moment; `GET /api/bots/{id}/decisions`). The bot view shows them as a
  list with an action badge and a confidence bar, the bot card gets a *Decisions* button. The bot status is
  now short – "Claude: hold (71 % sure) · next check in 12 min" – instead of carrying the whole reason.

## [1.5.0] – 2026-09-29

### Added

- **Discard position (no sale).** In the bot view next to *Sell position now*: removes a position from the
  agent's books without placing an order (`POST /api/bots/{id}/discard`). For a position that is wrong in the
  books – e.g. booked from a short-reported fill – while the coins stay, or don't exist, on the exchange.

### Changed

- **Fewer requests to Revolut X**, without touching how orders are tracked: candle series are reused until the
  next candle starts instead of being re-fetched every 5 minutes; balances are cached for a minute in the
  exchange wrapper (shared by the app, the holdings check and the checks before buys and sells) and dropped
  after every own order; the app only fetches balances while the panel is open; the holdings check runs every
  30 minutes (plus right after every own fill); the *AI decides* brief is built from two candle series instead
  of four; the first read of a new order happens a second after placing it. Roughly halves the daily request
  count with the default settings. Trades the user makes directly on Revolut X are, as before, not tracked.

## [1.4.2] – 2026-09-29

### Added

- **Holdings check.** Every 5 minutes (and right after every live fill) the agent compares the live positions it
  has booked with the balances on the exchange. If the exchange holds less of a coin than the bots think they
  own, every bot with a live position in that coin is flagged with an error event and stops trading – status
  *"Books don't match the exchange … trading paused"* – until the books match again (e.g. after a late fill was
  booked). Holding more than booked is fine.
- **Write-off on manual close.** *Sell position now* on a flagged bot sells what the exchange holds and writes
  off the rest with an error event (no trade is booked for coins that were never sold), so a wrong position can
  always be cleaned up from the app.

### Changed

- An order is only booked once two consecutive reads of it agree on status and filled quantity; fill data that
  is still moving right after "filled" is no longer booked. A sell that finds less available on the exchange
  than the position says logs an error event with both numbers.

## [1.4.1] – 2026-09-29

### Fixed

- **Short-reported fills.** Revolut X can report a market order as "filled" a moment before its fill data is
  complete; the agent then booked only the first part (a manual close of 0.00128 ETH was booked as 0.00043 ETH,
  the rest stayed open as a position that no longer existed on the exchange). Now an order whose reported fill
  is smaller than the requested size is re-read while polling, and if it is still short after that, the agent
  keeps re-reading it for up to 15 minutes and books the remainder as a late fill (`order-id#2`). Positions that
  are still open after a live sell – bookkeeping from earlier versions – are reconciled the same way on the next
  tick.

## [1.4.0] – 2026-09-29

### Added

- **Strategy "AI decides".** Claude (`claude-opus-5`) gets a market brief every N minutes – price, changes over
  1 h / 4 h / 24 h / 72 h, volatility of the last 4 h and 24 h, 24 h range, distance to the 72 h high and low, the
  last hourly closes, fees and the open position – and decides itself whether to buy, wait, hold or sell, with a
  short reason in English and German that ends up in the bot status and the trade. Optionally it may run a few
  web searches for news and market sentiment first. Needs `ANTHROPIC_API_KEY` on the agent (add-on option
  `anthropic_api_key`); every check costs a few cents. The safety net applies: a sell below break-even is held
  back, only the bot's stop-loss may realize a loss. The app shows a hint in the bot editor while the agent has
  no key (`GET /api/status` reports `ai_configured`).

## [1.3.0] – 2026-09-28

### Changed

- **A position is never sold at a loss by a target rule.** Before every strategy sell the agent checks the net
  proceeds at the current bid – sell fee included, rounded up to a full cent the way Revolut X does it for fiat –
  and holds the position while they are below its cost (`engine.hold_no_loss` status). Only the stop-loss, a
  manual "Sell position now" and the end of live trading may realize a loss. Background: a 2 € dip position was
  sold at "+0.33 %" gross and ended at −0.01 € because the sell fee was rounded from 0.0018 € to 0.01 €.
- **Dip buyer:** the minimum profit can no longer be negative.
- **Rebound + trailing stop:** once activated, the trailing stop never sits below break-even (cost plus sell fee),
  so a trailing distance wider than the activation cannot turn into a loss.
- **Price zones:** a reached target price is only sold when it also covers the entry; otherwise the bot holds
  and says so.
- `GET /api/status` reports the exchange fee (`taker_fee`), `GET /api/summary` the fees paid per currency.

### Added

- **Bot editor: cost check.** Below the rules the app shows what a buy plus sell costs at the chosen amount and
  whether the rules' profit target covers it; tiny orders (cent-rounded fee) get a warning with one-click fixes.
- **Bots tab:** bots are grouped into *Active* and *Stopped*, stopped bots get a compact card. A small sort menu
  (running first, result, name, newest) sits in the header, "New bot" moved below the list. Tab order is now
  Bots · Trades · Settings.
- **Statistics card:** the total result is the headline; fees so far and the Revolut X balance (cash plus open
  live positions) sit below it as small lines. Losses are shown in the normal text color, not red.
- **Panel height** can be changed by dragging its bottom edge; the height is remembered.
- **Refresh interval** options are now 30 s, 60 s, 2 min and 5 min (default 60 s).
- *Settings → Trading mode* moves below the agent details once live trading is switched on.

### Fixed

- Results and percentages no longer show "-0,00" for values that round to zero.

## [1.2.0] – 2026-09-28

### Added

- **Backup export and import in the app** (*Settings → Backup*). Export saves bots, trades, settings and the
  Revolut X key as a `.tgz` (`GET /api/backup`, a consistent SQLite snapshot; the API token is not included).
  Import (`POST /api/restore`) replaces the agent's data with such a file without a restart – e.g. to move from
  Docker to the Home Assistant add-on. Live trading is switched off after every restore.
- **Home Assistant add-on** (`homeassistant/dipagent/`). Add this repository in the add-on store, configure the
  token and exchange in the add-on's *Configuration* tab and point the macOS app at your Home Assistant host. The
  add-on uses the very same image as Docker users and stores its data in the add-on data directory (part of
  Home Assistant backups).
- **Released image on GHCR:** `ghcr.io/achirus-code/dipagent` (amd64 + arm64) is built by the release workflow
  from a `vX.Y.Z` tag; `docker compose up -d` pulls it instead of building locally. `scripts/sync-addon.py` keeps
  the add-on version and changelog in sync with the agent (checked in CI).

### Changed

- The container starts as root, takes ownership of `/data` and drops to the unprivileged user (uid 10001) before
  the agent starts (`app/entrypoint.py`). Needed because Home Assistant mounts the data directory root-owned; a
  bind mount on plain Docker is now chowned to uid 10001 as well.

## [1.1.0] – 2026-09-28

Review of the agent with a focus on order execution, stability and load on the exchange API. No changes to
strategies or to the macOS app.

### Fixed

- **A rejected manual close left a ghost order behind.** `POST /api/bots/{id}/close` (and switching back to paper
  mode) persisted the pending order before sending it but did not write the state back when the exchange refused
  it (e.g. insufficient funds). The bot then showed *Waiting for order execution* for three minutes, could not sell
  or be closed in that time and finally logged a misleading *order not found* event.
- **A reconciled order kept the bot in error state for five minutes.** When the response to an order got lost, the
  next tick found and booked the order but the *order unclear* backoff stayed in place: no evaluation (so no
  stop-loss) for five minutes and an *Error* status although the position was open.
- **An unreadable response to an order counted as "order not placed".** `ValueError` (which includes JSON decoding
  errors) was treated like an explicit rejection, so a garbled 2xx response could lead to a second live order. Only
  an explicit `Problem` or a non-transient 4xx from Revolut X is now treated as "definitely not placed"; everything
  else is looked up by `client_order_id` before anything is sent again.
- **Pending orders no longer vanish silently.** An order that cannot be found at the exchange after the grace period
  (placement response lost, or the exchange no longer knows the order id) stops the bot with an error status and
  event instead of being discarded – if it was executed after all, buying again would double the position. The same
  applies to an order id the exchange answers with 404 for.
- **Bots with an order in flight are protected like bots with a position:** trading pair, strategy and mode cannot be
  changed and the bot cannot be deleted without `force` while a `pending_order` exists.
- **Savings plan stuck after enabling live trading.** A DCA bot with an open paper position could neither buy (mode
  changed) nor sell (no profit target). It now closes the paper position with a simulated sell when the next
  instalment is due and continues live.
- **Stale bot state could be written back** when market data for a symbol was missing; the bot is re-read under its
  lock first.
- **Strategy parameters reject `NaN` and `Infinity`** (Python's JSON parser accepts them), which would have broken
  every Decimal comparison in the engine.
- **Exchange error messages** are parsed robustly when the error body is not a JSON object.

### Changed

- **Transient errors back off for one minute instead of five.** Network errors, 429 and 5xx from Revolut X are
  distinguished from real problems, so a single hiccup before a buy no longer costs the dip.
- **Idempotent requests are retried** (GET: three retries with backoff on network errors, 429 and 5xx). Orders are
  never resent – the existing reconciliation covers them.
- **Order tracking polls faster first** (0.3 s … 1.5 s, still about 8 s in total) and the global buy lock is released
  as soon as the pending order is persisted, so other bots are not held up while an order fills.
- **Exchange swap without dropping the running tick:** after entering or removing Revolut X credentials the old HTTP
  client is closed once the current tick has finished instead of mid-request.
- **Graceful shutdown:** the engine task is awaited (up to 10 s), background tasks are cancelled and the database is
  closed.
- The status of a stopped-by-reconciliation bot is flagged as an error in the API (`status_error`).
- API version reported as 1.1.0.

### Performance

- **SQLite:** `synchronous=NORMAL` in WAL mode (no fsync per statement – every tick used to fsync once per bot),
  `busy_timeout`, and a `created_at` index for the P&L summary. Schema changes are now tracked with
  `PRAGMA user_version` (migration list in `app/db.py`).
- **Bot state is only written when it changes;** the last check time is kept in memory and persisted with the next
  real change.
- **Market data:** all tickers of a tick are fetched in one request (with a per-symbol fallback), candles are cached
  across ticks and shared by all bots (re-fetched when a new candle starts or after five minutes), and symbols are
  fetched concurrently (4 at a time). Stopped bots without a position or order no longer cause market-data requests.
- **`GET /api/balances` is cached for 10 s** so the app's polling does not turn into an exchange request every time.
- The pair list keeps the cached copy (retry in five minutes) when a refresh fails instead of failing every order.

### Tests

- 20 new tests (`tests/test_engine_robustness.py`, `tests/test_exchange_setup.py`) covering the fixes above, the
  candle cache, ticker batching, write-on-change, client retries and the API guards.

### Known limitations

- Fee handling of live orders assumes Revolut X reports `filled_amount` *without* the fee and `total_fee` /
  `fee_currency` separately. This has not been verified against a real order yet – if `filled_amount` already
  includes the fee, cost and P&L of live buys are overstated by the fee.
- A bot stopped because its order could not be found has to be checked and restarted by hand; there is no API to
  reset a pending order manually.

## [1.0.0]

Initial release.
