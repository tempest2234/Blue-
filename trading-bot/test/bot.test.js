import test from "node:test";
import assert from "node:assert/strict";
import { Bot, completedBars } from "../src/bot.js";
import { createStore } from "../src/store.js";
import { createApp } from "../src/server.js";

const strategy = { fastPeriod: 3, slowPeriod: 6, rsiPeriod: 4, rsiMaxEntry: 70, rsiExit: 95, crossLookback: 2 };
const UP = [20, 19, 18, 17, 16, 15, 15, 15.2, 15, 15.4, 15.2, 15.6]; // buy signal
const DOWN = [10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 11]; // sell signal
const NOW = Date.parse("2026-01-05T18:00:00Z");

const toBars = (closes) =>
  closes.map((c, i) => ({ t: new Date(NOW - (closes.length - i + 1) * 3600e3).toISOString(), o: c, h: c, l: c, c }));

function fakeBroker({ open = true, equity = 10000, lastEquity = 10000, positions = [], prices = {} } = {}) {
  const calls = [];
  return {
    calls,
    paper: true,
    getClock: async () => ({ is_open: open }),
    getAccount: async () => ({ equity: String(equity), last_equity: String(lastEquity), buying_power: String(equity), cash: String(equity) }),
    getPositions: async () => positions,
    getOpenOrders: async () => [],
    getBars: async (s) => toBars(prices[s]),
    submitBracketBuy: async (o) => calls.push(["buy", o]),
    closePosition: async (s) => calls.push(["close", s]),
  };
}

const config = (over = {}) => ({
  symbols: ["AAA", "BBB"],
  timeframe: "1Hour",
  checkIntervalMinutes: 15,
  strategy,
  risk: { maxPositionPct: 10, maxOpenPositions: 5, stopLossPct: 3, takeProfitPct: 6, maxDailyLossPct: 3 },
  ...over,
});

const makeBot = (broker, cfg = config()) => new Bot({ config: cfg, broker, store: createStore(null), now: () => NOW });

test("buys on a buy signal and sells a held position on a sell signal", async () => {
  const broker = fakeBroker({
    prices: { AAA: UP, BBB: DOWN },
    positions: [{ symbol: "BBB", qty: "5", unrealized_pl: "12.5" }],
  });
  await makeBot(broker).tick();
  assert.ok(broker.calls.some((c) => c[0] === "close" && c[1] === "BBB"));
  const [kind, order] = broker.calls.find((c) => c[0] === "buy");
  assert.equal(kind, "buy");
  assert.equal(order.symbol, "AAA");
  assert.equal(order.qty, Math.floor(1000 / 15.6));
  assert.ok(order.stop < 15.6 && order.take > 15.6);
});

test("does nothing when the market is closed or the bot is paused", async () => {
  const closed = fakeBroker({ open: false, prices: { AAA: UP, BBB: UP } });
  await makeBot(closed).tick();
  assert.equal(closed.calls.length, 0);

  const broker = fakeBroker({ prices: { AAA: UP, BBB: UP } });
  const bot = makeBot(broker);
  bot.setPaused(true);
  await bot.tick();
  assert.equal(broker.calls.length, 0);
  assert.equal(bot.signals.AAA.action, "buy"); // still shows signals
});

test("no new buys after the daily loss limit, but sells still happen", async () => {
  const broker = fakeBroker({
    equity: 9500,
    lastEquity: 10000,
    prices: { AAA: UP, BBB: DOWN },
    positions: [{ symbol: "BBB", qty: "5", unrealized_pl: "-20" }],
  });
  const bot = makeBot(broker);
  await bot.tick();
  assert.deepEqual(broker.calls, [["close", "BBB"]]);
  assert.match(bot.haltedReason, /no new buys/);
});

test("respects the max open positions limit", async () => {
  const broker = fakeBroker({ prices: { AAA: UP, BBB: UP } });
  await makeBot(broker, config({ risk: { ...config().risk, maxOpenPositions: 1 } })).tick();
  assert.equal(broker.calls.filter((c) => c[0] === "buy").length, 1);
});

test("drops the still-forming bar", () => {
  const bars = [{ t: new Date(NOW - 2 * 3600e3).toISOString() }, { t: new Date(NOW - 1800e3).toISOString() }];
  assert.equal(completedBars(bars, "1Hour", NOW).length, 1);
});

test("dashboard API requires the password", async () => {
  const broker = fakeBroker({ prices: { AAA: UP, BBB: UP } });
  const server = createApp({ bot: makeBot(broker), broker, password: "correct horse battery" });
  await new Promise((r) => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const h = { "Content-Type": "application/json", "X-Requested-With": "dashboard" };
  try {
    assert.equal((await fetch(`${base}/api/status`)).status, 401);
    assert.equal((await fetch(`${base}/api/login`, { method: "POST", headers: h, body: '{"password":"nope"}' })).status, 401);
    assert.equal((await fetch(`${base}/api/login`, { method: "POST", body: '{"password":"correct horse battery"}' })).status, 403);

    const login = await fetch(`${base}/api/login`, { method: "POST", headers: h, body: '{"password":"correct horse battery"}' });
    assert.equal(login.status, 200);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    const status = await fetch(`${base}/api/status`, { headers: { cookie } });
    assert.equal(status.status, 200);
    const body = await status.json();
    assert.equal(body.mode, "paper");
    assert.equal(body.account.equity, 10000);

    assert.equal((await fetch(`${base}/`)).status, 200);
    assert.equal((await fetch(`${base}/../src/server.js`)).status, 404);
  } finally {
    server.close();
  }
});
