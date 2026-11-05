// Fit Day: calculations and daily task generation.
// A plain script (no import/export) so the app also works when index.html is
// opened straight from disk. Everything is published on globalThis.FitLogic.
(function () {
  const ACTIVITY = {
    sedentary: { label: "Mostly sitting (little exercise)", factor: 1.2 },
    light: { label: "Light (exercise 1-3 days a week)", factor: 1.375 },
    moderate: { label: "Moderate (exercise 3-5 days a week)", factor: 1.55 },
    active: { label: "Very active (exercise 6-7 days a week)", factor: 1.725 },
  };

  const GOALS = {
    lose: { label: "Lose weight", adjust: -500 },
    maintain: { label: "Stay in shape", adjust: 0 },
    gain: { label: "Build muscle", adjust: 300 },
  };

  const lbToKg = (lb) => lb * 0.45359237;
  const kgToLb = (kg) => kg / 0.45359237;
  const inToCm = (inch) => inch * 2.54;

  // Mifflin-St Jeor resting energy expenditure.
  function bmr({ sex, age, heightCm, weightKg }) {
    const base = 10 * weightKg + 6.25 * heightCm - 5 * age;
    return sex === "male" ? base + 5 : base - 161;
  }

  function validProfile(p) {
    return Boolean(
      p &&
        (p.sex === "male" || p.sex === "female") &&
        p.age >= 13 && p.age <= 100 &&
        p.heightCm >= 100 && p.heightCm <= 250 &&
        p.weightKg >= 30 && p.weightKg <= 300 &&
        ACTIVITY[p.activity] && GOALS[p.goal],
    );
  }

  // Daily calorie target, rounded to 10. Never goes below a safe floor.
  function calorieTarget(p) {
    const tdee = bmr(p) * ACTIVITY[p.activity].factor;
    const floor = p.sex === "male" ? 1500 : 1200;
    const target = Math.max(floor, tdee + GOALS[p.goal].adjust);
    return Math.round(target / 10) * 10;
  }

  // Grams of protein a day.
  function proteinTarget(p) {
    const perKg = p.goal === "maintain" ? 1.2 : 1.6;
    return Math.round(p.weightKg * perKg);
  }

  // Calories burned: MET x body weight (kg) x hours.
  function burned(met, weightKg, minutes) {
    return Math.round((met * weightKg * minutes) / 60);
  }

  function dateKey(d = new Date()) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function lastDays(n, from = new Date()) {
    const out = [];
    for (let i = n - 1; i >= 0; i--) {
      const d = new Date(from.getFullYear(), from.getMonth(), from.getDate() - i);
      out.push(dateKey(d));
    }
    return out;
  }

  // Small seeded random so a given day always gets the same plan.
  function seeded(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return function () {
      h += 0x6d2b79f5;
      let t = h;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const SLOTS = [
    { id: "morning", label: "Morning", time: "6–10 am" },
    { id: "midday", label: "Midday", time: "10 am–2 pm" },
    { id: "afternoon", label: "Afternoon", time: "2–6 pm" },
    { id: "evening", label: "Evening", time: "6–10 pm" },
  ];

  // Task pools. met + minutes means the task burns calories when done.
  const POOL = {
    morning: [
      { text: "Drink a full glass of water when you wake up" },
      { text: "5-minute full-body stretch", met: 2.3, minutes: 5 },
      { text: "10-minute brisk walk outside", met: 4.3, minutes: 10 },
      { text: "Eat a breakfast with protein (eggs, yogurt, oats)" },
      { text: "2 rounds: 10 squats, 10 push-ups, 20 s plank", met: 5, minutes: 6 },
    ],
    midday: [
      { text: "15-minute walk after lunch", met: 3.5, minutes: 15 },
      { text: "Take the stairs instead of the lift today", met: 4, minutes: 5 },
      { text: "Stand up and move for 2 minutes every hour" },
      { text: "Add a portion of vegetables to your lunch" },
      { text: "Desk stretch: neck, shoulders and hips (5 min)", met: 2.3, minutes: 5 },
    ],
    afternoon: {
      lose: [
        { text: "30-minute brisk walk or easy jog", met: 6, minutes: 30 },
        { text: "20-minute HIIT: 40 s on / 20 s off", met: 8, minutes: 20 },
        { text: "30-minute bike ride", met: 7, minutes: 30 },
        { text: "25-minute circuit: squats, lunges, burpees, mountain climbers", met: 7, minutes: 25 },
      ],
      maintain: [
        { text: "30-minute jog or brisk walk", met: 6, minutes: 30 },
        { text: "25-minute bodyweight workout", met: 5, minutes: 25 },
        { text: "30-minute yoga flow", met: 3, minutes: 30 },
        { text: "30 minutes of a sport you enjoy", met: 6, minutes: 30 },
      ],
      gain: [
        { text: "Strength: 4 x 10 squats, 4 x 10 push-ups, 3 x 12 rows", met: 5, minutes: 35 },
        { text: "Strength: 4 x 8 lunges each leg, 4 x 10 dips, 3 x 30 s plank", met: 5, minutes: 30 },
        { text: "Strength: 4 x 12 glute bridges, 4 x 8 pike push-ups, 3 x 10 pull-ups or rows", met: 5, minutes: 35 },
        { text: "Full-body weights session", met: 6, minutes: 40 },
      ],
    },
    evening: [
      { text: "10-minute stretch or foam roll", met: 2.3, minutes: 10 },
      { text: "Prep a healthy lunch for tomorrow" },
      { text: "No screens 30 minutes before bed" },
      { text: "Aim for 7–9 hours of sleep tonight" },
      { text: "Log everything you ate today" },
    ],
  };

  const REST_AFTERNOON = { text: "Rest day: 20-minute easy walk", met: 3, minutes: 20 };

  function pick(list, rand, count) {
    const copy = list.slice();
    const out = [];
    while (out.length < count && copy.length) {
      out.push(copy.splice(Math.floor(rand() * copy.length), 1)[0]);
    }
    return out;
  }

  // The plan for one day: 2 morning, 1 midday, 1 workout, 2 evening tasks.
  // Sundays are lighter rest days.
  function generateTasks(key, profile) {
    const rand = seeded(`${key}:${profile.goal}`);
    const [y, m, d] = key.split("-").map(Number);
    const isRestDay = new Date(y, m - 1, d).getDay() === 0;
    const chosen = {
      morning: pick(POOL.morning, rand, 2),
      midday: pick(POOL.midday, rand, 1),
      afternoon: isRestDay ? [REST_AFTERNOON] : pick(POOL.afternoon[profile.goal], rand, 1),
      evening: pick(POOL.evening, rand, 2),
    };
    const tasks = [];
    for (const slot of SLOTS) {
      chosen[slot.id].forEach((t, i) => {
        tasks.push({
          id: `${slot.id}-${i}`,
          slot: slot.id,
          text: t.text,
          kcal: t.met ? burned(t.met, profile.weightKg, t.minutes) : 0,
          done: false,
        });
      });
    }
    return tasks;
  }

  function totals(day) {
    const foods = day?.foods ?? [];
    const tasks = day?.tasks ?? [];
    const eaten = foods.reduce((s, f) => s + (Number(f.kcal) || 0), 0);
    const protein = foods.reduce((s, f) => s + (Number(f.protein) || 0), 0);
    const burnedKcal = tasks.filter((t) => t.done).reduce((s, t) => s + (t.kcal || 0), 0);
    const done = tasks.filter((t) => t.done).length;
    return { eaten, protein, burned: burnedKcal, done, taskCount: tasks.length };
  }

  const QUICK_FOODS = [
    { name: "Banana", kcal: 105, protein: 1 },
    { name: "Apple", kcal: 95, protein: 0 },
    { name: "2 eggs", kcal: 156, protein: 13 },
    { name: "Greek yogurt (170 g)", kcal: 100, protein: 17 },
    { name: "Oatmeal (1 cup cooked)", kcal: 160, protein: 6 },
    { name: "Chicken breast (150 g)", kcal: 248, protein: 46 },
    { name: "Rice (1 cup cooked)", kcal: 205, protein: 4 },
    { name: "Slice of bread", kcal: 80, protein: 3 },
    { name: "Peanut butter (2 tbsp)", kcal: 190, protein: 8 },
    { name: "Salad with dressing", kcal: 150, protein: 3 },
    { name: "Protein shake", kcal: 160, protein: 25 },
    { name: "Handful of almonds", kcal: 165, protein: 6 },
  ];

  globalThis.FitLogic = {
    ACTIVITY, GOALS, SLOTS, QUICK_FOODS,
    lbToKg, kgToLb, inToCm,
    bmr, validProfile, calorieTarget, proteinTarget, burned,
    dateKey, lastDays, generateTasks, totals,
  };
})();
