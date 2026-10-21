import express from "express";
import Anthropic from "@anthropic-ai/sdk";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3000;
const MODEL = process.env.TUTOR_MODEL || "claude-opus-5-5";

const app = express();
app.use(express.json({ limit: "100kb" }));
app.use(express.static(path.join(here, "public")));

// The client is created lazily so the practice part of the app still works
// without an API key; only the AI tutor needs one.
let client = null;
function getClient() {
  if (!client) client = new Anthropic();
  return client;
}

const LEVEL_AUDIENCE = {
  1: "a young child (about 6-8 years old) learning basic addition and subtraction",
  2: "an elementary school student (about 8-10 years old) learning multiplication and division",
  3: "a middle school student learning fractions, percentages, negatives and order of operations",
  4: "a high school student learning algebra (linear equations, quadratics, exponents)",
  5: "an advanced student learning calculus basics and systems of equations",
};

function systemPrompt(level) {
  const audience = LEVEL_AUDIENCE[level] || "a student";
  return `You are a friendly, patient math tutor inside a practice app. You are talking with ${audience}.

How to help:
- Guide the student toward the answer step by step. Prefer hints and guiding questions over giving the final answer right away.
- If the student asks directly for the answer, or has already tried and is stuck, it is fine to show a full worked solution.
- If the student shares a wrong answer, point out kindly where the mistake is likely to be.
- Use words and examples suited to the student's age. Keep replies short (a few sentences or a short numbered list).
- Write math in plain text (for example 3/4, x^2, sqrt(9)); do not use LaTeX.
- Stay on math. If asked about something unrelated, gently steer back to the problem.`;
}

app.get("/api/status", (_req, res) => {
  const configured = Boolean(
    process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN,
  );
  res.json({ aiAvailable: configured });
});

app.post("/api/tutor", async (req, res) => {
  const { level, problem, userAnswer, history } = req.body ?? {};
  if (!problem || !Array.isArray(history) || history.length === 0) {
    return res.status(400).json({ error: "Missing problem or message." });
  }

  // Keep only well-formed turns, and only the most recent ones.
  const turns = history
    .filter(
      (m) =>
        (m.role === "user" || m.role === "assistant") &&
        typeof m.content === "string" &&
        m.content.trim(),
    )
    .slice(-20)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }));
  while (turns.length && turns[0].role !== "user") turns.shift();
  if (!turns.length || turns[turns.length - 1].role !== "user") {
    return res.status(400).json({ error: "The last message must come from the student." });
  }

  const context =
    `Current problem: ${problem}` +
    (userAnswer ? `\nThe student's latest answer: ${userAnswer}` : "");
  turns[0] = { role: "user", content: `${context}\n\n${turns[0].content}` };

  try {
    const response = await getClient().beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: "low" },
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: systemPrompt(Number(level)),
      messages: turns,
    });

    if (response.stop_reason === "refusal") {
      return res.json({
        reply: "Sorry, I can't help with that one. Let's get back to the math problem!",
      });
    }
    const reply = response.content
      .filter((b) => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();
    res.json({ reply: reply || "Hmm, I couldn't think of a reply. Try asking again?" });
  } catch (err) {
    if (err instanceof Anthropic.AuthenticationError) {
      return res.status(503).json({ error: "The AI tutor isn't set up yet (missing or invalid API key)." });
    }
    if (err instanceof Anthropic.RateLimitError) {
      return res.status(429).json({ error: "The tutor is busy right now. Please try again in a moment." });
    }
    if (err instanceof Anthropic.APIError) {
      console.error("Anthropic API error:", err.status, err.message);
      return res.status(502).json({ error: "The tutor had a problem answering. Please try again." });
    }
    if (err instanceof Error && /credential|api key|auth/i.test(err.message)) {
      return res.status(503).json({ error: "The AI tutor isn't set up yet (missing API key)." });
    }
    console.error(err);
    res.status(500).json({ error: "Something went wrong." });
  }
});

app.listen(PORT, () => {
  console.log(`Math practice app running at http://localhost:${PORT}`);
});
