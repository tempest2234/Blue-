// Trend-following strategy: buy when a fast moving average crosses above a slow one
// (and the stock isn't already overbought), sell when the trend turns down or RSI
// shows it's very overbought. Stop-loss / take-profit are handled by bracket orders.

export function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

// Wilder's RSI.
export function rsi(values, period = 14) {
  const out = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d > 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  const calc = () => (avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  out[period] = calc();
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = calc();
  }
  return out;
}

export function computeIndicators(closes, p) {
  return {
    fast: sma(closes, p.fastPeriod),
    slow: sma(closes, p.slowPeriod),
    rsi: rsi(closes, p.rsiPeriod),
  };
}

export function minBars(p) {
  return Math.max(p.slowPeriod, p.rsiPeriod + 1) + p.crossLookback + 1;
}

// Decide what to do at bar index i, given precomputed indicators.
export function evaluateAt(closes, ind, i, p) {
  const fast = ind.fast[i];
  const slow = ind.slow[i];
  const r = ind.rsi[i];
  const price = closes[i];
  const indicators = { price, fast, slow, rsi: r };

  if (fast == null || slow == null || r == null || i < p.crossLookback) {
    return { action: "hold", reason: "Not enough price history yet", indicators };
  }

  if (fast < slow) {
    return { action: "sell", reason: "Trend turned down (fast average below slow)", indicators };
  }
  if (r >= p.rsiExit) {
    return { action: "sell", reason: `Very overbought (RSI ${r.toFixed(0)})`, indicators };
  }

  let crossedUp = false;
  for (let k = i - p.crossLookback + 1; k <= i; k++) {
    const pf = ind.fast[k - 1];
    const ps = ind.slow[k - 1];
    if (pf != null && ps != null && pf <= ps && ind.fast[k] > ind.slow[k]) crossedUp = true;
  }

  if (crossedUp && r < p.rsiMaxEntry && price > slow) {
    return { action: "buy", reason: `Fresh uptrend (fast average crossed above slow, RSI ${r.toFixed(0)})`, indicators };
  }
  if (crossedUp) {
    return { action: "hold", reason: `Uptrend started but RSI ${r.toFixed(0)} is too high to chase`, indicators };
  }
  return { action: "hold", reason: "In an uptrend, waiting for a fresh entry signal", indicators };
}

export function evaluate(closes, p) {
  if (closes.length < minBars(p)) {
    return { action: "hold", reason: "Not enough price history yet", indicators: { price: closes.at(-1) ?? null } };
  }
  return evaluateAt(closes, computeIndicators(closes, p), closes.length - 1, p);
}

// Simple historical simulation of the strategy with stop-loss / take-profit.
// Enters at the next bar's open after a buy signal; exits at the stop/target if a bar
// touches it (stop checked first, to be conservative) or next open after a sell signal.
export function backtest(bars, p, risk) {
  const closes = bars.map((b) => b.c);
  const ind = computeIndicators(closes, p);
  const trades = [];
  let pos = null;
  let equity = 1;
  let peak = 1;
  let maxDrawdown = 0;

  const exit = (i, price, why) => {
    const ret = price / pos.entry - 1;
    equity *= 1 + ret;
    trades.push({ entryTime: pos.time, exitTime: bars[i].t, entry: pos.entry, exit: price, returnPct: ret * 100, why });
    pos = null;
    peak = Math.max(peak, equity);
    maxDrawdown = Math.max(maxDrawdown, 1 - equity / peak);
  };

  for (let i = 1; i < bars.length; i++) {
    const bar = bars[i];
    if (pos) {
      if (bar.o <= pos.stop) exit(i, bar.o, "stop (gap)");
      else if (bar.l <= pos.stop) exit(i, pos.stop, "stop");
      else if (bar.o >= pos.take) exit(i, bar.o, "target (gap)");
      else if (bar.h >= pos.take) exit(i, pos.take, "target");
    }
    const sig = evaluateAt(closes, ind, i - 1, p);
    if (pos && sig.action === "sell") exit(i, bar.o, "signal");
    else if (!pos && sig.action === "buy") {
      pos = {
        entry: bar.o,
        time: bar.t,
        stop: bar.o * (1 - risk.stopLossPct / 100),
        take: bar.o * (1 + risk.takeProfitPct / 100),
      };
      // The entry bar itself can hit the stop/target.
      if (bar.l <= pos.stop) exit(i, pos.stop, "stop");
      else if (bar.h >= pos.take) exit(i, pos.take, "target");
    }
  }
  if (pos) exit(bars.length - 1, bars.at(-1).c, "end of data");

  const wins = trades.filter((t) => t.returnPct > 0).length;
  return {
    trades,
    totalReturnPct: (equity - 1) * 100,
    winRatePct: trades.length ? (wins / trades.length) * 100 : 0,
    maxDrawdownPct: maxDrawdown * 100,
    buyAndHoldPct: bars.length > 1 ? (bars.at(-1).c / bars[0].o - 1) * 100 : 0,
  };
}
