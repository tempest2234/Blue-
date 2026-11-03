// Optional push notifications to your phone via ntfy.sh (free app, no account needed).
export function createNotifier(topic) {
  if (!topic) return async () => {};
  return async (title, message) => {
    try {
      await fetch(`https://ntfy.sh/${encodeURIComponent(topic)}`, {
        method: "POST",
        headers: { Title: title },
        body: message,
        signal: AbortSignal.timeout(10000),
      });
    } catch (e) {
      console.error("Notification failed:", e.message);
    }
  };
}
