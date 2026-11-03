import test from "node:test";
import assert from "node:assert/strict";
import { sma, rsi, evaluate, backtest } from "../src/strategy.js";
import { positionSize, bracketPrices, dailyLossLimitHit, roundPrice } from "../src/risk.js";
import { loadConfig } from "../src/config.js";

const P = { fastPeriod: 3, slowPeriod: 6, rsiPeriod: 4, rsiMaxEntry: 70, rsiExit: 95, crossLookback: 2 };

test("sma", () => {
  assert.deepEqual(sma([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
});

test("rsi is 100 for only gains and between 0 and 100 otherwise", () => {
  assert.equal(rsi([1, 2, 3, 4, 5, 6], 4).at(-1), 100);
  const r = rsi([10, 11, 10.5, 11.5, 11, 12, 11.8, 12.5], 4);
  for (const v of r.filter((x) => x != null)) assert.ok(v > 0 && v < 100);
});

test("buy after the fast average crosses above the slow one", () => {
  // Down, flat, then a gentle choppy rise that makes the fast SMA cross up.
  const closes = [20, 19, 18, 17, 16, 15, 15, 15.2, 15, 15.4, 15.2, 15.6];
  const sig = evaluate(closes, P);
  assert.equal(sig.action, "buy", sig.reason);
});

test("sell when the trend turns down", () => {
  const closes = [10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 11];
  assert.equal(evaluate(closes, P).action, "sell");
});

test("hold with too little history", () => {
  assert.equal(evaluate([1, 2, 3], P).action, "hold");
});

test("backtest takes stop-loss exits", () => {
  const closes = [20, 19, 18, 17, 16, 15, 15, 15.2, 15, 15.4, 15.2, 15.6, 15.6, 10, 10, 10];
  const bars = closes.map((c, i) => ({ t: String(i), o: c, h: c, l: c, c }));
  const r = backtest(bars, P, { stopLossPct: 3, takeProfitPct: 50 });
  assert.equal(r.trades.length, 1);
  assert.match(r.trades[0].why, /stop/);
  assert.ok(r.totalReturnPct < 0);
});

test("position sizing respects equity % and buying power", () => {
  assert.equal(positionSize({ equity: 10000, buyingPower: 10000, price: 100, maxPositionPct: 10 }), 10);
  assert.equal(positionSize({ equity: 10000, buyingPower: 300, price: 100, maxPositionPct: 10 }), 2);
  assert.equal(positionSize({ equity: 1000, buyingPower: 1000, price: 500, maxPositionPct: 10 }), 0);
});

test("bracket prices and rounding", () => {
  assert.deepEqual(bracketPrices(100, 3, 6), { stop: 97, take: 106 });
  assert.equal(roundPrice(0.123456), 0.1235);
  assert.equal(roundPrice(12.3456), 12.35);
});

test("daily loss limit", () => {
  assert.equal(dailyLossLimitHit({ equity: 9600, lastEquity: 10000, maxDailyLossPct: 3 }), true);
  assert.equal(dailyLossLimitHit({ equity: 9800, lastEquity: 10000, maxDailyLossPct: 3 }), false);
});

test("config defaults to paper and guards live trading", () => {
  assert.equal(loadConfig({}).alpaca.paper, true);
  assert.throws(() => loadConfig({ ALPACA_PAPER: "false" }), /LIVE_TRADING_CONFIRM/);
  assert.equal(loadConfig({ ALPACA_PAPER: "false", LIVE_TRADING_CONFIRM: "I_ACCEPT_THE_RISK" }).alpaca.paper, false);
  assert.throws(() => loadConfig({ FAST_SMA: "60", SLOW_SMA: "50" }), /FAST_SMA/);
});
