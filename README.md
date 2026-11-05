# Blue

This repo holds two web apps:

- **Fit Day** (`fitness/`): stay in shape with a calorie tracker and daily tasks.
- **Math Climb** (`public/`): leveled math practice with an AI tutor.

## Fit Day

A fitness app that helps you stay in shape day by day.

- **Personal calorie goal**: enter your age, height, weight (kg/cm or lb/ft), activity level and goal (lose weight, stay in shape, build muscle). It works out your resting burn (Mifflin-St Jeor), a daily calorie goal and a protein goal.
- **Calorie tracker**: log food by meal with calories and optional protein, or tap a quick-add food. A ring shows how many calories you have left.
- **Tasks through the day**: a fresh plan every day, split into Morning, Midday, Afternoon and Evening, with a workout that fits your goal (Sundays are lighter rest days). Ticking off a workout adds its estimated calories burned to your budget. You can add your own tasks too.
- **Water tracker** (8 glasses), a **7-day calorie chart**, and a **streak** for days where you finish at least half your tasks.
- Works on phones and in dark mode. Your data stays in your browser (localStorage); nothing is sent anywhere.

To use it, open `fitness/index.html` in a browser, or run `npm start` and go to http://localhost:3000/fitness/.

The numbers are estimates, not medical advice.

---

# Math Climb

A web app for practicing math at five levels, with an AI tutor (Claude) that helps when you get stuck.

| Level | Topics |
|---|---|
| 1 · Beginner | Addition, subtraction |
| 2 · Elementary | Multiplication, division, word problems |
| 3 · Middle school | Adding fractions, percentages, negative numbers, order of operations |
| 4 · High school | Linear equations, quadratic equations, exponents |
| 5 · Advanced | Derivatives, systems of equations, definite integrals |

Features:

- An endless supply of randomly generated problems for each level and topic (or a mix of all topics)
- Instant answer checking: fractions, multiple roots in any order, and `x, y` pairs are all supported
- Score, current streak and best streak
- Built-in hints and a "show answer" button
- **AI tutor**: ask questions about the current problem. It sees the problem and your latest answer, and it guides you step by step rather than just handing over the answer. It also adjusts its language to the level you picked.

## Running it

Requires Node.js 18 or newer.

```bash
npm install
export ANTHROPIC_API_KEY=sk-ant-...   # needed only for the AI tutor
npm start
```

Then open http://localhost:3000.

Without an API key, practice, hints and answer checking still work. The tutor panel just explains that it isn't set up.

Optional environment variables:

- `PORT`: the server port (default `3000`)
- `TUTOR_MODEL`: the Claude model the tutor uses (default `claude-opus-5-5`)

## Project layout

```
server.js            Express server: serves the page and the /api/tutor endpoint (Claude API)
public/index.html    The page
public/app.js        UI logic: levels, scoring, tutor chat
public/problems.js   Problem generators and answer checking
public/style.css     Styles (light and dark mode)
fitness/             Fit Day: index.html, app.js (UI), logic.js (calculations, task plans), style.css
test/                Tests (npm test)
```
