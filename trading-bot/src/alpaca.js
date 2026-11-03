// Minimal Alpaca REST client (https://docs.alpaca.markets) using Node's built-in fetch.

export function createAlpaca({ keyId, secretKey, paper, feed = "iex" }) {
  const tradeBase = paper ? "https://paper-api.alpaca.markets" : "https://api.alpaca.markets";
  const dataBase = "https://data.alpaca.markets";
  const headers = {
    "APCA-API-KEY-ID": keyId,
    "APCA-API-SECRET-KEY": secretKey,
    "Content-Type": "application/json",
  };

  async function req(base, method, path, body) {
    const res = await fetch(base + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(20000),
    });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) {
      const msg = (data && data.message) || text || res.statusText;
      const err = new Error(`Alpaca ${method} ${path} failed (${res.status}): ${msg}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  const enc = encodeURIComponent;

  return {
    paper,
    getAccount: () => req(tradeBase, "GET", "/v2/account"),
    getClock: () => req(tradeBase, "GET", "/v2/clock"),
    getPositions: () => req(tradeBase, "GET", "/v2/positions"),
    getOpenOrders: () => req(tradeBase, "GET", "/v2/orders?status=open&limit=500&nested=false"),
    cancelOrder: (id) => req(tradeBase, "DELETE", `/v2/orders/${enc(id)}`),

    // Most recent `limit` bars, oldest first.
    async getBars(symbol, timeframe, limit) {
      const start = new Date(Date.now() - 2 * 365 * 24 * 3600 * 1000).toISOString();
      const qs = new URLSearchParams({
        timeframe,
        limit: String(limit),
        start,
        sort: "desc",
        adjustment: "split",
        feed,
      });
      const data = await req(dataBase, "GET", `/v2/stocks/${enc(symbol)}/bars?${qs}`);
      return (data.bars || []).reverse();
    },

    // Historical bars between two dates, oldest first (used by the backtest script).
    async getBarsRange(symbol, timeframe, start, end) {
      const bars = [];
      let pageToken = null;
      do {
        const qs = new URLSearchParams({ timeframe, start, end, limit: "10000", adjustment: "split", feed });
        if (pageToken) qs.set("page_token", pageToken);
        const data = await req(dataBase, "GET", `/v2/stocks/${enc(symbol)}/bars?${qs}`);
        bars.push(...(data.bars || []));
        pageToken = data.next_page_token;
      } while (pageToken);
      return bars;
    },

    // Market buy with an attached stop-loss and take-profit that live at the broker,
    // so they protect the position even if this bot goes offline.
    submitBracketBuy({ symbol, qty, stop, take, clientOrderId }) {
      return req(tradeBase, "POST", "/v2/orders", {
        symbol,
        qty: String(qty),
        side: "buy",
        type: "market",
        time_in_force: "gtc",
        order_class: "bracket",
        take_profit: { limit_price: String(take) },
        stop_loss: { stop_price: String(stop) },
        client_order_id: clientOrderId,
      });
    },

    // Cancel any open orders for the symbol (e.g. its stop/target legs), then sell it.
    async closePosition(symbol) {
      const open = await req(tradeBase, "GET", `/v2/orders?status=open&limit=500&symbols=${enc(symbol)}`);
      for (const o of open || []) {
        try {
          await req(tradeBase, "DELETE", `/v2/orders/${enc(o.id)}`);
        } catch (e) {
          if (e.status !== 404 && e.status !== 422) throw e;
        }
      }
      // Give the cancellations a moment to release the held shares.
      await new Promise((r) => setTimeout(r, 1000));
      return req(tradeBase, "DELETE", `/v2/positions/${enc(symbol)}`);
    },
  };
}
