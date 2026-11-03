// Tiny JSON-file store for the bot's settings and activity log.
import fs from "node:fs";
import path from "node:path";

const MAX_LOG = 300;

export function createStore(dir) {
  const file = dir ? path.join(dir, "state.json") : null;
  let state = { paused: false, log: [] };

  if (file) {
    try {
      state = { ...state, ...JSON.parse(fs.readFileSync(file, "utf8")) };
    } catch {
      // first run, or unreadable file: start fresh
    }
  }

  function save() {
    if (!file) return;
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(file + ".tmp", JSON.stringify(state));
      fs.renameSync(file + ".tmp", file);
    } catch (e) {
      console.error("Could not save state:", e.message);
    }
  }

  return {
    get paused() {
      return state.paused;
    },
    setPaused(v) {
      state.paused = Boolean(v);
      save();
    },
    log(type, message, extra = {}) {
      const entry = { time: new Date().toISOString(), type, message, ...extra };
      state.log.unshift(entry);
      state.log.length = Math.min(state.log.length, MAX_LOG);
      console.log(`[${entry.time}] ${type.toUpperCase()} ${message}`);
      save();
      return entry;
    },
    recentLog(n = 50) {
      return state.log.slice(0, n);
    },
  };
}
