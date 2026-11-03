const $ = (id) => document.getElementById(id);
let state = null;
let refreshTimer = null;

const money = (n) =>
  n == null || Number.isNaN(n) ? "–" : n.toLocaleString(undefined, { style: "currency", currency: "USD" });
const signed = (n, suffix = "") => `${n >= 0 ? "+" : ""}${n.toFixed(2)}${suffix}`;
const time = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "–");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Requested-With": "dashboard" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error("Not logged in");
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showLogin() {
  clearInterval(refreshTimer);
  $("dash").classList.add("hidden");
  $("login").classList.remove("hidden");
  $("password").focus();
}

function showDash() {
  $("login").classList.add("hidden");
  $("dash").classList.remove("hidden");
  refresh();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => document.visibilityState === "visible" && refresh(), 15000);
}

async function refresh() {
  try {
    state = await api("GET", "/api/status");
    render();
  } catch (e) {
    if (e.message !== "Not logged in") banner(`Couldn't load: ${e.message}`);
  }
}

function banner(msg) {
  $("banner").textContent = msg || "";
  $("banner-wrap").classList.toggle("hidden", !msg);
}

function render() {
  const s = state;
  $("mode").textContent = s.mode === "live" ? "LIVE MONEY" : "PAPER";
  $("mode").className = `badge ${s.mode}`;
  $("market").textContent = s.marketOpen ? "Market open" : "Market closed";
  $("market").className = `badge ${s.marketOpen ? "open" : "closed"}`;

  banner(s.brokerError || s.haltedReason || (s.lastError ? `Last check failed: ${s.lastError}` : ""));

  if (s.account) {
    $("equity").textContent = money(s.account.equity);
    const diff = s.account.equity - s.account.lastEquity;
    const pct = s.account.lastEquity ? (diff / s.account.lastEquity) * 100 : 0;
    $("today").textContent = `${signed(diff)} (${signed(pct, "%")})`;
    $("today").className = `value ${diff >= 0 ? "up" : "down"}`;
    $("bp").textContent = money(s.account.buyingPower);
  }

  $("bot-state").textContent = s.paused ? "Paused" : s.haltedReason ? "Running (no new buys)" : "Running";
  $("toggle").textContent = s.paused ? "Resume" : "Pause";
  const opens = !s.marketOpen && s.nextOpen ? ` · Market opens ${time(s.nextOpen)}` : "";
  $("bot-times").textContent = `Last check ${time(s.lastRun)} · Next ${time(s.nextRun)}${opens}`;

  const pos = $("positions");
  pos.replaceChildren();
  if (!s.positions || s.positions.length === 0) pos.append(el("li", { class: "muted" }, "No open positions"));
  for (const p of s.positions || []) {
    pos.append(
      el(
        "li",
        {},
        el(
          "div",
          { class: "main" },
          el("div", { class: "sym" }, `${p.symbol} `, el("span", { class: "muted small" }, `${p.qty} @ ${money(p.avgEntry)}`)),
          el("div", { class: `small ${p.unrealizedPl >= 0 ? "up" : "down"}` }, `${money(p.price)} · ${signed(p.unrealizedPl)} (${signed(p.unrealizedPlPct, "%")})`),
          p.managed ? null : el("div", { class: "muted small" }, "Not managed by the bot")
        ),
        el("button", { class: "small", onclick: () => closeOne(p.symbol) }, "Sell")
      )
    );
  }

  const sig = $("signals");
  sig.replaceChildren();
  for (const sym of s.symbols) {
    const g = s.signals[sym];
    sig.append(
      el(
        "li",
        {},
        el(
          "div",
          { class: "main" },
          el("div", { class: "sym" }, sym, g?.indicators?.price ? el("span", { class: "muted small" }, ` ${money(g.indicators.price)}`) : null),
          el("div", { class: "muted small" }, g ? g.reason : "Not checked yet")
        ),
        el("span", { class: `tag ${g?.action || "hold"}` }, g?.action || "–")
      )
    );
  }

  const log = $("log");
  log.replaceChildren();
  if (s.log.length === 0) log.append(el("li", { class: "muted" }, "Nothing yet"));
  for (const e of s.log) {
    log.append(el("li", {}, el("span", { class: `tag ${e.type}` }, e.type), " ", el("span", { class: "muted small" }, time(e.time)), el("div", {}, e.message)));
  }

  const st = s.settings;
  $("settings").textContent =
    `Watching ${s.symbols.join(", ")} on ${st.timeframe} bars, checking every ${st.checkIntervalMinutes} min. ` +
    `Each buy uses up to ${st.maxPositionPct}% of equity, max ${st.maxOpenPositions} positions. ` +
    `Stop-loss ${st.stopLossPct}%, take-profit ${st.takeProfitPct}%. No new buys after a ${st.maxDailyLossPct}% daily loss. ` +
    `Signals: SMA ${st.fastPeriod}/${st.slowPeriod} crossover, RSI ${st.rsiPeriod} (buy below ${st.rsiMaxEntry}, sell above ${st.rsiExit}).`;
}

async function action(button, fn) {
  button.disabled = true;
  try {
    await fn();
    await refresh();
  } catch (e) {
    if (e.message !== "Not logged in") alert(e.message);
  } finally {
    button.disabled = false;
  }
}

function closeOne(symbol) {
  if (!confirm(`Sell all of ${symbol} at market price now?`)) return;
  api("POST", "/api/close", { symbol }).then(refresh, (e) => alert(e.message));
}

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-error").textContent = "";
  try {
    await api("POST", "/api/login", { password: $("password").value });
    $("password").value = "";
    showDash();
  } catch (e) {
    $("login-error").textContent = e.message;
  }
});

$("logout").addEventListener("click", async () => {
  await api("POST", "/api/logout").catch(() => {});
  showLogin();
});

$("toggle").addEventListener("click", (ev) =>
  action(ev.currentTarget, () => api("POST", state?.paused ? "/api/resume" : "/api/pause"))
);

$("run").addEventListener("click", (ev) => action(ev.currentTarget, () => api("POST", "/api/run")));

$("close-all").addEventListener("click", (ev) => {
  if (!confirm("Sell ALL of the bot's positions at market price and pause the bot?")) return;
  action(ev.currentTarget, () => api("POST", "/api/close-all"));
});

api("GET", "/api/status").then(
  (s) => {
    state = s;
    showDash();
  },
  () => showLogin()
);
