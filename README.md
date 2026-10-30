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

## Character editor (bonus page)

`public/character/index.html` is a standalone, rigged 2D anime character with physics, at http://localhost:3000/character/ (or open the file directly in a browser; it needs no server).

- **Rig**: bone hierarchy with two-bone IK legs (feet stay planted, knees bend when she lands or is pushed down), FK arms, and a head and eyes that follow the cursor
- **Physics**: spring-mass jiggle on the chest, a pleated skirt hem that sways, and verlet hair strands and ribbons with adjustable stiffness and wind
- **Interaction**: drag to pick her up and drop her, click her head for a head pat, Hop / Dance buttons (Space hops), and "Show rig" to see the bones and physics points
- **Editor**: color pickers for every material plus presets, sliders for bust, waist, hips, leg and hair length, hair styles, poses, expressions, and "Save PNG". Settings persist in the browser.
