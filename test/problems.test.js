import { test } from "node:test";
import assert from "node:assert/strict";
import { LEVELS, makeProblem, checkAnswer } from "../public/problems.js";

test("every topic generates problems its own answer passes", () => {
  for (const [level, lvl] of Object.entries(LEVELS)) {
    for (const topic of Object.keys(lvl.topics)) {
      for (let i = 0; i < 300; i++) {
        const p = makeProblem(Number(level), topic);
        assert.ok(p.question && p.hint, `${level}/${topic} missing text`);
        assert.ok(checkAnswer(p, p.display), `${level}/${topic}: "${p.display}" rejected for "${p.question}"`);
        assert.ok(!/NaN|undefined/.test(p.question), p.question);
      }
    }
  }
});

test("wrong answers are rejected", () => {
  assert.equal(checkAnswer({ answer: 12 }, "13"), false);
  assert.equal(checkAnswer({ answer: 12 }, ""), false);
  assert.equal(checkAnswer({ answer: 12 }, "abc"), false);
});

test("fractions must be simplified but equivalent forms work", () => {
  const p = { answer: { n: 7, d: 6 } };
  assert.equal(checkAnswer(p, "7/6"), true);
  assert.equal(checkAnswer(p, "14/12"), false);
  assert.equal(checkAnswer({ answer: { n: 2, d: 1 } }, "2"), true);
});

test("quadratic roots in any order, systems as x, y", () => {
  assert.equal(checkAnswer({ answer: [3, -2] }, "-2, 3"), true);
  assert.equal(checkAnswer({ answer: [3, -2] }, "3"), false);
  assert.equal(checkAnswer({ answer: { pair: [1, -4] } }, "x=1, y=-4"), true);
  assert.equal(checkAnswer({ answer: { pair: [1, -4] } }, "-4, 1"), false);
  assert.equal(checkAnswer({ answer: 5 }, "x = 5"), true);
});
