# Changelog

All notable changes to DipAgentX (formerly DipAgent) are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.24.0] – 2026-10-05

### Added

- **Signal overview for the monthly trend follower** – the bot's page in the apps shows, line by line, what the last
  decision rested on: the price against its average and the return against the cash rate, each with the price that
  would turn it at the coming month end ("today 112 € – off below 103 € (−8 %)"); every switched-on recession sign
  (unemployment, jobless claims, yield curve) with its value; EUR/USD against its 12-month average (hedged or not);
  and the 12-month return of each bond ETF to park in against the cash rate. The recession signs, the dollar and the
  bonds are now looked at every month, also while they don't decide anything (the decisions don't change).
- The months so far as a strip: invested, currency-hedged, parked in bonds or in cash (up to 24 months).
- **Pillars**: with two or more running trend followers on a broker, each one's page lists all of them – value,
  actual share against the share its amount stands for – and once one drifts 5 percentage points or more, the amounts
  that would restore the shares.
- API: `signals` and `pillars` on every bot (null for other strategies).

## [1.23.0] – 2026-10-05

### Added

- **Momentum trend follower** – a new strategy for ETH and BTC (the best of more than 2,000 variants in the backtests,
  see `docs/strategien-backtests.md`, section 14). Six lookbacks (14, 21, 30, 40, 50, 60 days) on the 4-hour closes each
  count as up once the price rose more than 5 % over them (2 % while the 90-day return is above 20 %) and as down once
  it fell; the bot invests the share of lookbacks that are up, in 10 % steps of its capital – each step its own trade,
  sold also at a loss, gains reinvested. Less while the volatility of the last 20 days is above 100 % a year; at least
  50 % while the 7-day average funding rate of the Binance perpetual futures is below 2 % a year (fetched hourly,
  public). Optional: *Halve on exchange inflows* (net inflow onto exchanges over 7 days above 1 % of their balance,
  Coin Metrics community API, daily). It only trades when the target step changes – about twice a week.
- The engine supports strategies that manage their trades themselves: no "Max. open trades" option, no spacing, and
  the sliced position counts as one open position for the limits. Every sale adds its result to the bot's state
  (`realized`) – the momentum follower reinvests it.

## [1.22.0] – 2026-10-05

### Added

- **Monthly trend follower: the combination that held up best in the backtests** (see
  `docs/strategien-backtests.md`, sections 8–12). All new options are off by default, except the Euribor hurdle:
  - *Trend signal: price above its average or return better than the cash rate* – the trend only counts as broken
    when both are down, which avoids many false signals.
  - *Cash rate from the Euribor* (on by default): "return better than the cash rate" compares with what cash actually
    earned in the same months (3-month Euribor from the ECB, fetched once a day); without the data, or switched off,
    the fixed rate counts as before.
  - Two more recession signs next to the unemployment rate: *jobless claims* (US initial claims of the last complete
    month more than 5 % above a year earlier, weekly from the US Department of Labor) and *yield curve* (the US
    10-year yield below the 3-month one at a month end of the last 24 months, from the US Treasury). A falling trend
    only sells when at least one switched-on sign shows; without any data the trend alone decides.
  - *Currency-hedged share class*: while the euro is above its 12-month average against the dollar (ECB month-end
    rates), the bot holds the EUR-hedged share class of its index instead of its own instrument – the signal keeps
    using its own instrument.
  - *Park in instead of cash*: up to three ISINs (e.g. euro government bonds and EUR-hedged US Treasuries); while the
    trend is down the bot buys the one with the best 12-month return, as long as it beats the cash rate.
- **A bot can hold another instrument than its own.** The engine buys, sells, tracks orders, checks the holdings on the
  broker and values open trades per instrument; the apps show the held instrument's ticker with the quantity. Trades
  are booked under the instrument actually traded.

## [1.21.0] – 2026-10-05

### Added

- **Monthly trend follower** – a new strategy for ETFs and gold. Once a month, on the first trading day, it looks at
  how the instrument closed the previous month: above its average of the last months (default 10, with a ±2 % buffer
  so a price close to the average doesn't trade back and forth) – or, as the other signal, with a better return than
  the cash rate (e.g. 12 months) – the bot holds the whole amount; otherwise it sells, also at a loss, and waits in
  cash until a later month turns up again. The decision holds for the month, a crash in between doesn't trade. With
  *Sell only when unemployment rises* a falling trend only sells when the US unemployment rate is also above its
  12-month average (the agent fetches it from the US Bureau of Labor Statistics once a day; without it the trend alone
  decides). *Reinvest the proceeds* (on by default) buys again with what the last sale brought in. The README shows a
  three-bot setup for world shares, gold and euro government bonds on Trade Republic, with backtest results.
- **Dip buyer: trend filter and trend exit.** New rules *Trend filter: long average* and *short average* (in days,
  0 = off, the default) with a *buffer* (default 3 %): the bot only buys while the price is above both averages – the
  long one by at least the buffer. It counts as a downtrend once the price falls below the short average or more than
  the buffer below the long one; in between the last state stays. *Sell when the trend breaks* (off by default) then
  sells open trades right away – also at a loss, like a stop-loss. A backtest on BTC and ETH (2018–2026) worked best
  with 200 and 60 days, a 3 % buffer, trend exit and a wide trailing stop (10 %). The daily closes for the averages
  are fetched once a day (in chunks of at most 98 candles). Without enough history (a young pair) the bot doesn't buy.
- **Dip buyer: sideways filter.** New option *Only buy while ADX (4h) below*: the bot buys a dip only while the trend
  strength ADX (14) of the 4-hour candles is below the value – i.e. while the market moves sideways and dips tend to
  recover. In a trend the bot shows "Dip, but the market trends (ADX 4h …)" and waits. Selling isn't affected; 0 (the
  default) switches the filter off, so existing bots behave as before.

### Fixed

- **Trade Republic: long daily price series.** Daily candles were built from hourly ones, which Trade Republic only
  serves for the last three months – longer averages (like the dip buyer's 200-day trend filter) saw only part of the
  history. They now come as daily candles, up to about five years back, in one request.

## [1.20.0] – 2026-10-05

### Added

- **Trade Republic as a second broker.** Bots can now trade stocks, ETFs and crypto on Trade Republic as well – with
  every strategy, paper mode, live trading, limits, statistics, trade history, profit chart and notifications. Revolut X
  stays as it was.
- **Two tabs above the statistics** switch between Revolut X and Trade Republic (macOS menu bar app and iPhone). Each
  broker has its own result, bots, trades, trading mode (paper/live switch with double confirmation), risk limits and
  simulation fees; the tabs show both results at a glance.
- **Brokers on/off** (*Settings → Brokers*): a broker that is switched off is left alone – its bots stop, no prices,
  no login. With only one broker on, the tabs disappear and the app looks as before. A broker with open trades or
  orders can't be switched off.
- **Paper trading on Trade Republic without a login:** prices, charts, trading hours and the instrument search come
  from Trade Republic's public market data. New bots start in paper mode, as on Revolut X.
- **Trade Republic login from the app** (*Settings → Trade Republic*): phone number and PIN, confirmed in the Trade
  Republic app (or with an authenticator code). Trade Republic ends every login after 24 hours; with the PIN saved on
  the agent, the agent starts the next login itself while live trading is on or live trades are open – you only
  confirm it in the Trade Republic app, and the DipAgentX app reminds you.
- **Instrument search** in the bot editor (name, ticker or ISIN) – bots show the instrument's name and ticker
  instead of the ISIN.
- **Fixed fees per order:** Trade Republic charges 1 € per order. The simulation, the "never sell at a loss" rule,
  break-even prices, trailing stops and the fee check in the bot editor include it; the paper fees have a new
  *Fee per order* field.
- **Trading hours:** stocks and ETFs trade Monday to Friday 07:30–23:00 (Europe/Berlin). Outside them the bots wait
  ("Market closed · opens Mon 07:30") and no order is sent; crypto trades around the clock.
- New option `TR_APP_VERSION` (and the add-on option *Trade Republic web app version*) in case Trade Republic refuses
  the login as outdated.

### Changed

- **New icon with the X of Revolut X** in the bottom-right corner – app icon (macOS, iPhone), menu bar icon,
  Home Assistant add-on and website.
- The REST API takes `?exchange=revolutx|traderepublic` for the summary, limits, paper fees, balances, pairs, trades
  and the live switch (`?exchange=all` for bots and trades of every broker); bots and trades carry their `exchange`.
  Without it everything refers to Revolut X, so older apps keep working – they only see the Revolut X bots.
- "AI decides" knows whether it looks at a coin, a stock or an ETF and on which broker; the Crypto Fear & Greed index
  is only used for crypto.
- Backups don't include the Trade Republic login – log in again after restoring one.

### Note

Trade Republic has no official API for programs. DipAgentX uses the interface of the Trade Republic web app; Trade
Republic's customer agreement doesn't allow access through other programs and Trade Republic may block it or the
account. The app says so before the login. Use it at your own risk.

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
