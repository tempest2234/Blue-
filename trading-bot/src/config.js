// All settings come from environment variables so nothing secret lives in the code.

export const LIVE_CONFIRM_PHRASE = "I_ACCEPT_THE_RISK";

export function loadConfig(env = process.env) {
  const num = (key, fallback, { min = -Infinity, max = Infinity } = {}) => {
    const raw = env[key];
    if (raw === undefined || raw === "") return fallback;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < min || n > max) {
      throw new Error(`${key} must be a number between ${min} and ${max} (got "${raw}")`);
    }
    return n;
  };

  const paper = String(env.ALPACA_PAPER ?? "true").toLowerCase() !== "false";
  if (!paper && env.LIVE_TRADING_CONFIRM !== LIVE_CONFIRM_PHRASE) {
    throw new Error(
      `Refusing to start with real money: ALPACA_PAPER=false also requires LIVE_TRADING_CONFIRM=${LIVE_CONFIRM_PHRASE}`
    );
  }

  const symbols = String(env.SYMBOLS || "SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-Z.]{1,10}$/.test(s));
  if (symbols.length === 0) throw new Error("SYMBOLS must list at least one ticker");

  const strategy = {
    fastPeriod: num("FAST_SMA", 20, { min: 2, max: 400 }),
    slowPeriod: num("SLOW_SMA", 50, { min: 3, max: 500 }),
    rsiPeriod: num("RSI_PERIOD", 14, { min: 2, max: 100 }),
    rsiMaxEntry: num("RSI_MAX_ENTRY", 70, { min: 1, max: 100 }),
    rsiExit: num("RSI_EXIT", 80, { min: 1, max: 100 }),
    crossLookback: num("CROSS_LOOKBACK", 3, { min: 1, max: 50 }),
  };
  if (strategy.fastPeriod >= strategy.slowPeriod) {
    throw new Error("FAST_SMA must be smaller than SLOW_SMA");
  }

  return {
    alpaca: {
      keyId: env.ALPACA_KEY_ID || "",
      secretKey: env.ALPACA_SECRET_KEY || "",
      paper,
      feed: env.ALPACA_DATA_FEED || "iex", // "iex" works on the free plan; "sip" needs a paid data plan
    },
    dashboardPassword: env.DASHBOARD_PASSWORD || "",
    port: num("PORT", 8080, { min: 1, max: 65535 }),
    symbols,
    timeframe: env.TIMEFRAME || "1Hour", // Alpaca bar size: 15Min, 1Hour, 1Day, ...
    checkIntervalMinutes: num("CHECK_INTERVAL_MIN", 15, { min: 1, max: 1440 }),
    strategy,
    risk: {
      maxPositionPct: num("MAX_POSITION_PCT", 10, { min: 0.1, max: 100 }),
      maxOpenPositions: num("MAX_OPEN_POSITIONS", 5, { min: 1, max: 100 }),
      stopLossPct: num("STOP_LOSS_PCT", 3, { min: 0.1, max: 90 }),
      takeProfitPct: num("TAKE_PROFIT_PCT", 6, { min: 0.1, max: 1000 }),
      maxDailyLossPct: num("MAX_DAILY_LOSS_PCT", 3, { min: 0.1, max: 100 }),
    },
    ntfyTopic: env.NTFY_TOPIC || "",
    dataDir: env.DATA_DIR || "data",
  };
}
