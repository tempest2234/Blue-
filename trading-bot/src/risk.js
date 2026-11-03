// Risk rules: how big each trade is, where its stop/target go, and when to stop buying.

export function roundPrice(price) {
  // US equities: whole cents at $1+, up to 4 decimals below $1.
  const factor = price >= 1 ? 100 : 10000;
  return Math.round(price * factor) / factor;
}

// Whole shares only (bracket orders don't accept fractional quantities).
export function positionSize({ equity, buyingPower, price, maxPositionPct }) {
  if (!(price > 0)) return 0;
  const budget = Math.min(equity * (maxPositionPct / 100), buyingPower * 0.95);
  return Math.max(0, Math.floor(budget / price));
}

export function bracketPrices(price, stopLossPct, takeProfitPct) {
  return {
    stop: roundPrice(price * (1 - stopLossPct / 100)),
    take: roundPrice(price * (1 + takeProfitPct / 100)),
  };
}

export function dailyChangePct(equity, lastEquity) {
  if (!(lastEquity > 0)) return 0;
  return ((equity - lastEquity) / lastEquity) * 100;
}

export function dailyLossLimitHit({ equity, lastEquity, maxDailyLossPct }) {
  return dailyChangePct(equity, lastEquity) <= -maxDailyLossPct;
}
