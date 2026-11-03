// The trading loop: every few minutes while the market is open, look at each symbol,
// sell positions whose trend ended, and buy fresh uptrends within the risk limits.
import { evaluate, minBars } from "./strategy.js";
import { positionSize, bracketPrices, dailyLossLimitHit, dailyChangePct } from "./risk.js";

const UNIT_MS = { Min: 60e3, T: 60e3, Hour: 3600e3, H: 3600e3, Day: 86400e3, D: 86400e3, Week: 7 * 86400e3, W: 7 * 86400e3 };

export function timeframeMs(tf) {
  const m = /^(\d+)(Min|T|Hour|H|Day|D|Week|W)$/.exec(tf);
  return m ? Number(m[1]) * UNIT_MS[m[2]] : 0;
}

// Drop the newest bar if it is still forming, so signals only use finished bars.
export function completedBars(bars, timeframe, now = Date.now()) {
  const ms = timeframeMs(timeframe);
  if (!ms || bars.length === 0) return bars;
  const last = bars.at(-1);
  return Date.parse(last.t) + ms > now ? bars.slice(0, -1) : bars;
}

export class Bot {
  constructor({ config, broker, store, notify = async () => {}, now = () => Date.now() }) {
    this.config = config;
    this.broker = broker;
    this.store = store;
    this.notify = notify;
    this.now = now;
    this.running = false;
    this.timer = null;
    this.lastRun = null;
    this.nextRun = null;
    this.marketOpen = null;
    this.signals = {};
    this.haltedReason = null;
    this.lastError = null;
  }

  start() {
    const ms = this.config.checkIntervalMinutes * 60e3;
    this.store.log("info", `Bot started (${this.broker.paper ? "PAPER" : "LIVE"} trading, checking every ${this.config.checkIntervalMinutes} min)`);
    const loop = async () => {
      await this.tick();
      this.nextRun = new Date(this.now() + ms).toISOString();
      this.timer = setTimeout(loop, ms);
    };
    loop();
  }

  stop() {
    clearTimeout(this.timer);
  }

  setPaused(paused) {
    this.store.setPaused(paused);
    this.store.log("info", paused ? "Bot paused from dashboard" : "Bot resumed from dashboard");
  }

  async tick() {
    if (this.running) return { skipped: "already running" };
    this.running = true;
    try {
      return await this._tick();
    } catch (e) {
      this.lastError = e.message;
      this.store.log("error", e.message);
      return { error: e.message };
    } finally {
      this.lastRun = new Date(this.now()).toISOString();
      this.running = false;
    }
  }

  async _tick() {
    const { config, broker, store } = this;
    const clock = await broker.getClock();
    this.marketOpen = Boolean(clock.is_open);
    if (!clock.is_open) return { skipped: "market closed" };

    const account = await broker.getAccount();
    if (account.trading_blocked || account.account_blocked) {
      this.haltedReason = "Your Alpaca account is blocked from trading";
      store.log("error", this.haltedReason);
      return { skipped: "account blocked" };
    }

    const equity = Number(account.equity);
    const lastEquity = Number(account.last_equity);
    let buyingPower = Number(account.buying_power);

    this.haltedReason = null;
    if (dailyLossLimitHit({ equity, lastEquity, maxDailyLossPct: config.risk.maxDailyLossPct })) {
      this.haltedReason = `Down ${dailyChangePct(equity, lastEquity).toFixed(2)}% today: no new buys until tomorrow`;
    }

    const positions = await broker.getPositions();
    const held = new Map(positions.map((p) => [p.symbol, p]));
    const openOrders = await broker.getOpenOrders();
    const pendingBuys = new Set(openOrders.filter((o) => o.side === "buy").map((o) => o.symbol));
    let openCount = positions.filter((p) => config.symbols.includes(p.symbol)).length + pendingBuys.size;

    const actions = [];
    const barsNeeded = minBars(config.strategy) + 50;

    for (const symbol of config.symbols) {
      try {
        const bars = completedBars(await broker.getBars(symbol, config.timeframe, barsNeeded + 1), config.timeframe, this.now());
        const closes = bars.map((b) => b.c);
        const sig = evaluate(closes, config.strategy);
        this.signals[symbol] = { ...sig, time: new Date(this.now()).toISOString() };

        if (store.paused) continue;
        const pos = held.get(symbol);

        if (pos && sig.action === "sell") {
          await broker.closePosition(symbol);
          const pl = Number(pos.unrealized_pl);
          const msg = `SELL ${pos.qty} ${symbol} at ~$${sig.indicators.price.toFixed(2)} (P/L ${pl >= 0 ? "+" : ""}$${pl.toFixed(2)}). ${sig.reason}`;
          store.log("sell", msg, { symbol });
          this.notify(`Sold ${symbol}`, msg);
          actions.push({ symbol, action: "sell" });
          openCount--;
        } else if (!pos && !pendingBuys.has(symbol) && sig.action === "buy") {
          if (this.haltedReason) continue;
          if (openCount >= config.risk.maxOpenPositions) {
            store.log("info", `Buy signal for ${symbol} skipped: already at ${config.risk.maxOpenPositions} positions`, { symbol });
            continue;
          }
          const price = sig.indicators.price;
          const qty = positionSize({ equity, buyingPower, price, maxPositionPct: config.risk.maxPositionPct });
          if (qty < 1) {
            store.log("info", `Buy signal for ${symbol} skipped: not enough buying power for 1 share`, { symbol });
            continue;
          }
          const { stop, take } = bracketPrices(price, config.risk.stopLossPct, config.risk.takeProfitPct);
          await broker.submitBracketBuy({
            symbol,
            qty,
            stop,
            take,
            clientOrderId: `bot-${symbol}-${this.now()}`,
          });
          const msg = `BUY ${qty} ${symbol} at ~$${price.toFixed(2)} (stop $${stop}, target $${take}). ${sig.reason}`;
          store.log("buy", msg, { symbol });
          this.notify(`Bought ${symbol}`, msg);
          actions.push({ symbol, action: "buy", qty });
          buyingPower -= qty * price;
          openCount++;
        }
      } catch (e) {
        store.log("error", `${symbol}: ${e.message}`, { symbol });
      }
    }
    this.lastError = null;
    return { actions };
  }

  async closeAll() {
    const positions = await this.broker.getPositions();
    const mine = positions.filter((p) => this.config.symbols.includes(p.symbol));
    for (const p of mine) {
      await this.broker.closePosition(p.symbol);
      this.store.log("sell", `Closed ${p.qty} ${p.symbol} from dashboard (emergency close all)`, { symbol: p.symbol });
    }
    return mine.length;
  }

  async closeOne(symbol) {
    await this.broker.closePosition(symbol);
    this.store.log("sell", `Closed ${symbol} from dashboard`, { symbol });
  }

  status() {
    return {
      mode: this.broker.paper ? "paper" : "live",
      paused: this.store.paused,
      haltedReason: this.haltedReason,
      running: this.running,
      marketOpen: this.marketOpen,
      lastRun: this.lastRun,
      nextRun: this.nextRun,
      lastError: this.lastError,
      symbols: this.config.symbols,
      signals: this.signals,
      settings: {
        timeframe: this.config.timeframe,
        checkIntervalMinutes: this.config.checkIntervalMinutes,
        ...this.config.risk,
        ...this.config.strategy,
      },
      log: this.store.recentLog(50),
    };
  }
}
