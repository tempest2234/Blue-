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
test/                Tests for the generators and checker (npm test)
```

## Also in this repo

- [`trading-bot/`](trading-bot/README.md): an automated stock trading bot (Alpaca) with a phone dashboard
