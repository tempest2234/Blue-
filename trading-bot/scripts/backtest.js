// Try the strategy on past prices before trusting it with money.
// Usage: node scripts/backtest.js [SYMBOL ...] [--days 365]
import { loadConfig } from "../src/config.js";
import { createAlpaca } from "../src/alpaca.js";
import { backtest } from "../src/strategy.js";

const args = process.argv.slice(2);
let days = 365;
const di = args.indexOf("--days");
if (di !== -1) {
  days = Number(args[di + 1]) || days;
  args.splice(di, 2);
}

const config = loadConfig();
if (!config.alpaca.keyId || !config.alpaca.secretKey) {
  console.error("Set ALPACA_KEY_ID and ALPACA_SECRET_KEY first.");
  process.exit(1);
}
const broker = createAlpaca(config.alpaca);
const symbols = args.length ? args.map((s) => s.toUpperCase()) : config.symbols;
const end = new Date(Date.now() - 20 * 60e3).toISOString(); // free data lags 15 min
const start = new Date(Date.now() - days * 86400e3).toISOString();

console.log(`Backtest: ${config.timeframe} bars, last ${days} days, stop ${config.risk.stopLossPct}%, target ${config.risk.takeProfitPct}%\n`);
console.log("Symbol   Trades  Win%   Strategy%  Buy&Hold%  MaxDrawdown%");
for (const symbol of symbols) {
  try {
    const bars = await broker.getBarsRange(symbol, config.timeframe, start, end);
    const r = backtest(bars, config.strategy, config.risk);
    console.log(
      [
        symbol.padEnd(8),
        String(r.trades.length).padStart(6),
        r.winRatePct.toFixed(0).padStart(5),
        r.totalReturnPct.toFixed(1).padStart(10),
        r.buyAndHoldPct.toFixed(1).padStart(10),
        r.maxDrawdownPct.toFixed(1).padStart(13),
      ].join(" ")
    );
  } catch (e) {
    console.log(`${symbol.padEnd(8)} error: ${e.message}`);
  }
}
console.log("\nPast results don't predict future returns. Ignores commissions and slippage.");
