// Web server: the phone dashboard and its password-protected API.
import http from "node:http";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "./config.js";
import { createAlpaca } from "./alpaca.js";
import { createStore } from "./store.js";
import { createNotifier } from "./notify.js";
import { Bot } from "./bot.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(here, "..", "public");
const SESSION_HOURS = 24 * 7;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".webmanifest": "application/manifest+json",
  ".svg": "image/svg+xml",
};

export function createApp({ bot, broker, password }) {
  const secret = crypto.randomBytes(32);
  const failures = new Map(); // ip -> { count, until }
  let globalFails = { count: 0, until: 0 }; // backstop in case IPs are spoofed

  const sign = (payload) => crypto.createHmac("sha256", secret).update(payload).digest("base64url");
  const makeToken = () => {
    const exp = String(Date.now() + SESSION_HOURS * 3600e3);
    return `${exp}.${sign(exp)}`;
  };
  const validToken = (token) => {
    if (!token) return false;
    const [exp, sig] = token.split(".");
    if (!exp || !sig || Number(exp) < Date.now()) return false;
    const a = Buffer.from(sig);
    const b = Buffer.from(sign(exp));
    return a.length === b.length && crypto.timingSafeEqual(a, b);
  };
  const passwordMatches = (given) => {
    const a = crypto.createHash("sha256").update(String(given)).digest();
    const b = crypto.createHash("sha256").update(password).digest();
    return crypto.timingSafeEqual(a, b);
  };

  const cookie = (req, name) => {
    for (const part of (req.headers.cookie || "").split(";")) {
      const [k, ...v] = part.trim().split("=");
      if (k === name) return v.join("=");
    }
    return null;
  };

  const send = (res, status, body, headers = {}) => {
    res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers });
    res.end(JSON.stringify(body));
  };

  const readJson = (req) =>
    new Promise((resolve, reject) => {
      let data = "";
      req.on("data", (c) => {
        data += c;
        if (data.length > 10000) {
          reject(new Error("Body too large"));
          req.destroy();
        }
      });
      req.on("end", () => {
        try {
          resolve(data ? JSON.parse(data) : {});
        } catch {
          reject(new Error("Invalid JSON"));
        }
      });
      req.on("error", reject);
    });

  const serveStatic = (req, res) => {
    const urlPath = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const rel = urlPath === "/" ? "index.html" : urlPath.slice(1);
    const file = path.normalize(path.join(publicDir, rel));
    if (!file.startsWith(publicDir + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404).end("Not found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": MIME[path.extname(file)] || "application/octet-stream",
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-cache",
    });
    fs.createReadStream(file).pipe(res);
  };

  async function handleApi(req, res, route) {
    const ip = req.headers["x-forwarded-for"]?.split(",")[0].trim() || req.socket.remoteAddress;
    const secure = req.headers["x-forwarded-proto"] === "https" || req.socket.encrypted;

    // Basic CSRF protection: state-changing calls must come from our own page.
    if (req.method === "POST" && req.headers["x-requested-with"] !== "dashboard") {
      return send(res, 403, { error: "Forbidden" });
    }

    if (route === "POST /api/login") {
      const f = failures.get(ip);
      if ((f && f.count >= 5 && f.until > Date.now()) || (globalFails.count >= 30 && globalFails.until > Date.now())) {
        return send(res, 429, { error: "Too many attempts. Try again in 15 minutes." });
      }
      const body = await readJson(req);
      if (!passwordMatches(body.password || "")) {
        const next = f && f.until > Date.now() ? f.count + 1 : 1;
        failures.set(ip, { count: next, until: Date.now() + 15 * 60e3 });
        globalFails = { count: globalFails.until > Date.now() ? globalFails.count + 1 : 1, until: Date.now() + 15 * 60e3 };
        return send(res, 401, { error: "Wrong password" });
      }
      failures.delete(ip);
      const attrs = `HttpOnly; SameSite=Strict; Path=/; Max-Age=${SESSION_HOURS * 3600}${secure ? "; Secure" : ""}`;
      return send(res, 200, { ok: true }, { "Set-Cookie": `session=${makeToken()}; ${attrs}` });
    }

    if (route === "POST /api/logout") {
      return send(res, 200, { ok: true }, { "Set-Cookie": "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0" });
    }

    if (!validToken(cookie(req, "session"))) return send(res, 401, { error: "Not logged in" });

    switch (route) {
      case "GET /api/status": {
        const status = bot.status();
        try {
          const [account, positions, clock] = await Promise.all([broker.getAccount(), broker.getPositions(), broker.getClock()]);
          status.account = {
            equity: Number(account.equity),
            lastEquity: Number(account.last_equity),
            cash: Number(account.cash),
            buyingPower: Number(account.buying_power),
          };
          status.positions = positions.map((p) => ({
            symbol: p.symbol,
            qty: Number(p.qty),
            avgEntry: Number(p.avg_entry_price),
            price: Number(p.current_price),
            marketValue: Number(p.market_value),
            unrealizedPl: Number(p.unrealized_pl),
            unrealizedPlPct: Number(p.unrealized_plpc) * 100,
            managed: bot.config.symbols.includes(p.symbol),
          }));
          status.marketOpen = clock.is_open;
          status.nextOpen = clock.next_open;
          status.nextClose = clock.next_close;
        } catch (e) {
          status.brokerError = e.message;
        }
        return send(res, 200, status);
      }
      case "POST /api/pause":
        bot.setPaused(true);
        return send(res, 200, { ok: true });
      case "POST /api/resume":
        bot.setPaused(false);
        return send(res, 200, { ok: true });
      case "POST /api/run": {
        const result = await bot.tick();
        return send(res, 200, result);
      }
      case "POST /api/close": {
        const { symbol } = await readJson(req);
        if (!/^[A-Z.]{1,10}$/.test(symbol || "")) return send(res, 400, { error: "Bad symbol" });
        await bot.closeOne(symbol);
        return send(res, 200, { ok: true });
      }
      case "POST /api/close-all": {
        bot.setPaused(true);
        const n = await bot.closeAll();
        return send(res, 200, { ok: true, closed: n });
      }
      default:
        return send(res, 404, { error: "Not found" });
    }
  }

  return http.createServer(async (req, res) => {
    res.setHeader("X-Frame-Options", "DENY");
    res.setHeader("Referrer-Policy", "no-referrer");
    const pathname = new URL(req.url, "http://x").pathname;
    if (pathname.startsWith("/api/")) {
      try {
        await handleApi(req, res, `${req.method} ${pathname}`);
      } catch (e) {
        send(res, 500, { error: e.message });
      }
    } else if (req.method === "GET") {
      serveStatic(req, res);
    } else {
      res.writeHead(405).end();
    }
  });
}

function main() {
  let config;
  try {
    config = loadConfig();
  } catch (e) {
    console.error(`Config error: ${e.message}`);
    process.exit(1);
  }
  if (!config.alpaca.keyId || !config.alpaca.secretKey) {
    console.error("Missing ALPACA_KEY_ID / ALPACA_SECRET_KEY. See trading-bot/README.md for setup.");
    process.exit(1);
  }
  if (config.dashboardPassword.length < 10) {
    console.error("Set DASHBOARD_PASSWORD to something at least 10 characters long; it protects your trading account.");
    process.exit(1);
  }

  const broker = createAlpaca(config.alpaca);
  const store = createStore(config.dataDir);
  const bot = new Bot({ config, broker, store, notify: createNotifier(config.ntfyTopic) });
  const server = createApp({ bot, broker, password: config.dashboardPassword });
  server.listen(config.port, () => {
    console.log(`Dashboard on http://localhost:${config.port} (${config.alpaca.paper ? "PAPER" : "LIVE"} trading)`);
    bot.start();
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
