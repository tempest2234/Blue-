# Trade Bot

An automated stock trading bot that you run and watch from your phone.

- Trades US stocks and ETFs through [Alpaca](https://alpaca.markets) (commission-free, with a free API)
- **Starts in paper-trading mode (fake money).** Real money needs two settings you change on purpose.
- Phone dashboard (add it to your home screen): equity, today's P/L, positions, live signals and an activity log, plus buttons to pause, resume, check now, sell one position, or sell everything
- Optional push notifications to your phone for every buy and sell (via the free ntfy app)

> **Read this first.** No bot can promise good trades. This one follows a simple, common
> trend-following strategy with strict risk limits, and it **will** have losing trades and
> losing stretches. Run it on paper for at least a few weeks, and backtest it, before you
> consider real money. Only ever trade money you can afford to lose.

## How it trades

Every `CHECK_INTERVAL_MIN` minutes while the market is open, for each symbol in `SYMBOLS`:

**Buy** when all of these are true:
1. The 20-bar moving average has *just* crossed above the 50-bar moving average (in the last 3 bars), which marks a new uptrend
2. RSI is below 70 (it doesn't chase stocks that already jumped)
3. The price is above the 50-bar average

**Sell** when the 20-bar average falls back below the 50-bar average (the trend has ended), or RSI goes above 80 (very overbought).

Each buy is a **bracket order**: Alpaca holds a stop-loss (default 3% below) and a take-profit (default 6% above) for the position. These orders live at Alpaca, so they still protect you if the bot or your server goes down.

**Risk limits:**
| Setting | Default | Meaning |
|---|---|---|
| `MAX_POSITION_PCT` | 10 | Each buy uses at most 10% of your account |
| `MAX_OPEN_POSITIONS` | 5 | No more than 5 positions at once |
| `STOP_LOSS_PCT` | 3 | Auto-sell if a position falls 3% |
| `TAKE_PROFIT_PCT` | 6 | Auto-sell if a position rises 6% |
| `MAX_DAILY_LOSS_PCT` | 3 | If the account is down 3% today, no new buys until tomorrow |

The bot only manages the symbols in `SYMBOLS`. It leaves any other stocks in the account alone, apart from the dashboard's per-position Sell button, which works on anything.

## Setup (about 15 minutes)

### 1. Get Alpaca API keys
1. Sign up at https://alpaca.markets (free).
2. In the dashboard, switch to **Paper Trading**, then **API Keys → Generate**. Copy the Key ID and Secret.

### 2. Put the bot online so your phone can reach it
The bot has to run around the clock on a server, not on your phone. A small always-on host is enough. For example:

**Railway** (easy, about $5/month):
1. Fork or push this repo to your GitHub.
2. At https://railway.app: **New Project → Deploy from GitHub repo**, and pick this repo.
3. In the service settings, set **Root Directory** to `trading-bot`.
4. Under **Variables**, add `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` and `DASHBOARD_PASSWORD` (see `.env.example` for all the options).
5. Under **Settings → Networking**, click **Generate Domain**. That URL is your dashboard.

**Render, Fly.io, or any VPS** work too. Use the included `Dockerfile`, or run `npm start` with Node 18+. Avoid free tiers that "sleep" when idle: a sleeping bot doesn't trade.

> Always open the dashboard over **https** (Railway, Render and Fly give you this automatically). Your password protects a brokerage account.

### 3. Open it on your phone
Open the URL, log in with your `DASHBOARD_PASSWORD`, then:
- **iPhone:** Share → *Add to Home Screen*
- **Android:** ⋮ menu → *Add to Home screen* / *Install app*

### 4. (Optional) Get notified on your phone
Install the **ntfy** app, subscribe to a long, random topic name (for example `trade-bot-x7k2p9q4mz`), and set `NTFY_TOPIC` to the same name.

## Test it on past data

```bash
cd trading-bot
export ALPACA_KEY_ID=... ALPACA_SECRET_KEY=...
npm run backtest                    # all symbols in SYMBOLS, last 365 days
npm run backtest -- NVDA AAPL --days 730
```

It prints the trade count, win rate, strategy return, buy-and-hold return and worst drawdown for each symbol. If the strategy doesn't beat buy-and-hold on your symbols, change the settings or the symbols before you rely on it.

## Running locally

```bash
cd trading-bot
cp .env.example .env    # then fill it in
set -a; source .env; set +a
npm start               # dashboard at http://localhost:8080
npm test
```

No `npm install` is needed: the bot has no dependencies beyond Node.js 18+.

## Switching to real money

Only do this after paper trading gives results you're happy with.
1. In Alpaca, fund a live account and generate **live** API keys.
2. Replace the keys and add:
   ```
   ALPACA_PAPER=false
   LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK
   ```
The dashboard then shows a red **LIVE MONEY** badge. Consider lowering `MAX_POSITION_PCT` when you start.

Note: US rules limit accounts under $25,000 to 3 day trades in 5 business days (the "pattern day trader" rule). With hourly bars the bot may sometimes buy and sell on the same day. On a small live account, use `TIMEFRAME=1Day` to make that rare.

## Files

```
src/server.js     Dashboard web server and password-protected API; starts the bot
src/bot.js        Trading loop: signals → buy/sell within risk limits
src/strategy.js   Indicators (SMA, RSI), buy/sell rules, and the backtester
src/risk.js       Position sizing, stop/target prices, daily loss limit
src/alpaca.js     Alpaca API client
src/store.js      Saves pause state and the activity log (data/state.json)
src/notify.js     ntfy push notifications
public/           The phone dashboard
scripts/backtest.js
test/             npm test
```
