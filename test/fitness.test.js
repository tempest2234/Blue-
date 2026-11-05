import { test } from "node:test";
import assert from "node:assert/strict";
import "../fitness/logic.js";

const L = globalThis.FitLogic;
const base = { sex: "female", age: 30, heightCm: 165, weightKg: 65, activity: "moderate", goal: "maintain" };

test("BMR matches Mifflin-St Jeor", () => {
  assert.equal(L.bmr(base), 10 * 65 + 6.25 * 165 - 5 * 30 - 161);
  assert.equal(L.bmr({ ...base, sex: "male" }), 10 * 65 + 6.25 * 165 - 5 * 30 + 5);
});

test("calorie target follows the goal and never drops below the floor", () => {
  const keep = L.calorieTarget(base);
  assert.equal(keep, Math.round((L.bmr(base) * 1.55) / 10) * 10);
  assert.ok(L.calorieTarget({ ...base, goal: "lose" }) < keep);
  assert.ok(L.calorieTarget({ ...base, goal: "gain" }) > keep);
  const tiny = { ...base, age: 80, heightCm: 140, weightKg: 40, activity: "sedentary", goal: "lose" };
  assert.equal(L.calorieTarget(tiny), 1200);
  assert.equal(L.calorieTarget({ ...tiny, sex: "male" }), 1500);
});

test("profile validation", () => {
  assert.ok(L.validProfile(base));
  assert.ok(!L.validProfile(null));
  assert.ok(!L.validProfile({ ...base, age: 8 }));
  assert.ok(!L.validProfile({ ...base, goal: "fly" }));
  assert.ok(!L.validProfile({ ...base, weightKg: NaN }));
});

test("unit conversions", () => {
  assert.ok(Math.abs(L.lbToKg(150) - 68.04) < 0.01);
  assert.ok(Math.abs(L.kgToLb(L.lbToKg(180)) - 180) < 1e-9);
  assert.equal(L.inToCm(70), 177.8);
});

test("daily tasks are stable per day, cover every slot, and match the goal", () => {
  for (const goal of Object.keys(L.GOALS)) {
    const p = { ...base, goal };
    for (const key of L.lastDays(30, new Date(2026, 10, 5))) {
      const a = L.generateTasks(key, p);
      assert.deepEqual(a, L.generateTasks(key, p));
      assert.equal(a.length, 6);
      for (const s of L.SLOTS) assert.ok(a.some((t) => t.slot === s.id), `${key} missing ${s.id}`);
      assert.equal(new Set(a.map((t) => t.id)).size, a.length);
      const workout = a.find((t) => t.slot === "afternoon");
      assert.ok(workout.kcal > 0);
    }
  }
  // 2026-11-08 is a Sunday: rest day.
  assert.match(L.generateTasks("2026-11-08", base).find((t) => t.slot === "afternoon").text, /Rest day/);
});

test("totals add food, protein and burned calories from finished tasks", () => {
  const day = {
    foods: [{ kcal: 300, protein: 20 }, { kcal: 150 }],
    tasks: [{ done: true, kcal: 120 }, { done: false, kcal: 200 }, { done: true, kcal: 0 }],
  };
  assert.deepEqual(L.totals(day), { eaten: 450, protein: 20, burned: 120, done: 2, taskCount: 3 });
  assert.deepEqual(L.totals(undefined), { eaten: 0, protein: 0, burned: 0, done: 0, taskCount: 0 });
});

test("lastDays crosses month boundaries", () => {
  assert.deepEqual(L.lastDays(3, new Date(2026, 2, 1)), ["2026-02-27", "2026-02-28", "2026-03-01"]);
});
