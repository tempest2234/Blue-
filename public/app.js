import { LEVELS, makeProblem, checkAnswer } from "./problems.js";

const $ = (id) => document.getElementById(id);

const state = {
  level: null,
  topic: "",
  problem: null,
  lastAnswer: "",
  solved: false,
  score: 0,
  attempted: 0,
  streak: 0,
  best: Number(safeGet("best") || 0),
  chat: [],
  aiBusy: false,
};

function safeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function renderLevels() {
  const box = $("levels");
  box.innerHTML = "";
  for (const [num, lvl] of Object.entries(LEVELS)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "level";
    btn.setAttribute("aria-pressed", String(state.level === Number(num)));
    btn.innerHTML = `Level ${num}: ${lvl.name}<small>${lvl.description}</small>`;
    btn.onclick = () => selectLevel(Number(num));
    box.appendChild(btn);
  }
}

function renderTopics() {
  const sel = $("topic");
  sel.innerHTML = "";
  sel.disabled = !state.level;
  if (!state.level) return;
  sel.add(new Option("Mixed (all topics)", ""));
  for (const [key, t] of Object.entries(LEVELS[state.level].topics)) sel.add(new Option(t.name, key));
  sel.value = state.topic;
}

function renderStats() {
  $("score").textContent = state.score;
  $("attempted").textContent = state.attempted;
  $("streak").textContent = state.streak;
  $("best").textContent = state.best;
}

function selectLevel(level) {
  state.level = level;
  state.topic = "";
  safeSet("level", level);
  renderLevels();
  renderTopics();
  nextProblem();
}

function nextProblem() {
  if (!state.level) return;
  state.problem = makeProblem(state.level, state.topic);
  state.solved = false;
  state.lastAnswer = "";
  state.chat = [];
  $("question").textContent = state.problem.question;
  $("answer").value = "";
  $("answer").disabled = false;
  $("feedback").textContent = "";
  $("feedback").className = "feedback";
  $("hint").hidden = true;
  renderChat();
  $("answer").focus();
}

function submitAnswer(e) {
  e.preventDefault();
  if (!state.problem || state.solved) return;
  const value = $("answer").value.trim();
  if (!value) return;
  state.lastAnswer = value;
  const fb = $("feedback");
  if (checkAnswer(state.problem, value)) {
    state.solved = true;
    state.score++;
    state.attempted++;
    state.streak++;
    if (state.streak > state.best) {
      state.best = state.streak;
      safeSet("best", state.best);
    }
    fb.textContent = pick(["Correct! 🎉", "Nice work! ✅", "You got it! 🌟", "Great job! 💪"]);
    fb.className = "feedback good";
    $("answer").disabled = true;
    $("next-btn").focus();
  } else {
    state.attempted++;
    state.streak = 0;
    fb.textContent = "Not quite. Try again, use a hint, or ask the tutor.";
    fb.className = "feedback bad";
  }
  renderStats();
}

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function showHint() {
  if (!state.problem) return;
  $("hint").textContent = "💡 " + state.problem.hint;
  $("hint").hidden = false;
}

function showAnswer() {
  if (!state.problem) return;
  if (!state.solved) {
    state.streak = 0;
    renderStats();
  }
  state.solved = true;
  $("answer").disabled = true;
  $("feedback").textContent = `The answer is ${state.problem.display}. Ask the tutor if you'd like to see why.`;
  $("feedback").className = "feedback";
}

function renderChat() {
  const box = $("chat");
  box.innerHTML = "";
  for (const m of state.chat) {
    const div = document.createElement("div");
    div.className = `msg ${m.role}${m.error ? " error" : ""}`;
    div.textContent = m.content;
    box.appendChild(div);
  }
  if (state.aiBusy) {
    const div = document.createElement("div");
    div.className = "msg assistant";
    div.textContent = "Thinking…";
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

async function askTutor(text) {
  text = text.trim();
  if (!text || state.aiBusy) return;
  if (!state.problem) {
    state.chat.push({ role: "assistant", content: "Pick a level first so we have a problem to work on!", error: true });
    renderChat();
    return;
  }
  state.chat.push({ role: "user", content: text });
  state.aiBusy = true;
  setChatEnabled(false);
  renderChat();
  const problemAtSend = state.problem;

  try {
    const res = await fetch("/api/tutor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        level: state.level,
        problem: state.problem.question,
        userAnswer: state.lastAnswer,
        history: state.chat.filter((m) => !m.error).map(({ role, content }) => ({ role, content })),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (problemAtSend !== state.problem) return; // moved on to another problem
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    state.chat.push({ role: "assistant", content: data.reply });
  } catch (err) {
    if (problemAtSend !== state.problem) return;
    state.chat.push({ role: "assistant", content: err.message || "Couldn't reach the tutor.", error: true });
  } finally {
    state.aiBusy = false;
    setChatEnabled(true);
    renderChat();
  }
}

function setChatEnabled(on) {
  $("chat-input").disabled = !on;
  document.querySelectorAll("#chat-form button, .chip").forEach((b) => (b.disabled = !on));
}

async function checkAiStatus() {
  try {
    const res = await fetch("/api/status");
    const { aiAvailable } = await res.json();
    if (!aiAvailable) {
      $("tutor-status").textContent =
        "The AI tutor needs an Anthropic API key on the server (set ANTHROPIC_API_KEY). Practice still works without it.";
    }
  } catch { /* server unreachable; errors show when asking */ }
}

$("answer-form").addEventListener("submit", submitAnswer);
$("hint-btn").addEventListener("click", showHint);
$("show-btn").addEventListener("click", showAnswer);
$("next-btn").addEventListener("click", nextProblem);
$("topic").addEventListener("change", (e) => {
  state.topic = e.target.value;
  nextProblem();
});
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("chat-input");
  askTutor(input.value);
  input.value = "";
});
document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => askTutor(chip.dataset.q)));

renderLevels();
renderTopics();
renderStats();
checkAiStatus();
const savedLevel = Number(safeGet("level"));
if (LEVELS[savedLevel]) selectLevel(savedLevel);
