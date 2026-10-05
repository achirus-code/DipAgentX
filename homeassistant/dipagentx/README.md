# DipAgentX

Trading bots for [Revolut X](https://exchange.revolut.com) and [Trade Republic](https://traderepublic.com) that run
24/7 on your Home Assistant – controlled from the DipAgentX macOS menu bar app.

The add-on runs the DipAgentX agent (REST API + bot engine) and stores bots, trades, settings, the Revolut X key and the Trade Republic session in
the add-on's data directory, which is part of your Home Assistant backups. There is no web UI: install the macOS app
from <https://github.com/achirus-code/DipAgentX>, point it at your Home Assistant host (port 3470) and enter the API
token.

Everything starts in **paper mode** (real prices, simulated orders). Trading can lose money – this is a personal
project, not financial advice. Trade Republic has no official API; DipAgentX uses the interface of its web app, which
its terms don't allow – use it at your own risk.
