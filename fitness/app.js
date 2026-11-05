// Fit Day: UI. All data stays in this browser (localStorage).
(function () {
  const L = globalThis.FitLogic;
  const STORE_KEY = "fitday:v1";
  const WATER_GOAL = 8;
  const $ = (sel) => document.querySelector(sel);

  // ---------- storage ----------
  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const data = JSON.parse(raw);
        if (data && typeof data === "object") return { profile: data.profile || null, days: data.days || {} };
      }
    } catch (_) { /* storage blocked or bad JSON: start fresh */ }
    return { profile: null, days: {} };
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* ignore */ }
  }

  let state = load();
  let currentTab = "today";

  function todayKey() { return L.dateKey(new Date()); }

  // Today's record, created (with a fresh task plan) the first time it is needed.
  function today() {
    const key = todayKey();
    if (!state.days[key]) {
      state.days[key] = { foods: [], water: 0, tasks: L.generateTasks(key, state.profile) };
      save();
    }
    return state.days[key];
  }

  // ---------- helpers ----------
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v != null) node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  const fmt = (n) => Math.round(n).toLocaleString();
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  function currentSlot() {
    const h = new Date().getHours();
    if (h < 10) return "morning";
    if (h < 14) return "midday";
    if (h < 18) return "afternoon";
    return "evening";
  }

  // ---------- tabs ----------
  function showTab(tab) {
    currentTab = tab;
    for (const b of document.querySelectorAll("#tabs button")) {
      b.classList.toggle("active", b.dataset.tab === tab);
    }
    for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== `view-${tab}`;
    render();
    window.scrollTo(0, 0);
  }

  // ---------- render ----------
  function render() {
    $("#today-label").textContent = new Date().toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric",
    });
    const hasProfile = L.validProfile(state.profile);
    $("#tabs").hidden = !hasProfile;
    if (!hasProfile) {
      for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== "view-profile";
      renderProfile();
      return;
    }
    if (currentTab === "today") renderToday();
    if (currentTab === "food") renderFood();
    if (currentTab === "tasks") renderTasks();
    if (currentTab === "profile") renderProfile();
  }

  function renderToday() {
    const day = today();
    const goal = L.calorieTarget(state.profile);
    const t = L.totals(day);
    const budget = goal + t.burned;
    const remaining = budget - t.eaten;

    $("#remaining-num").textContent = fmt(Math.abs(remaining));
    $("#remaining-label").textContent = remaining >= 0 ? "kcal left" : "kcal over";
    const ring = $("#ring-fg");
    const circ = 2 * Math.PI * 52;
    const frac = Math.min(1, budget ? t.eaten / budget : 0);
    ring.style.strokeDasharray = `${circ}`;
    ring.style.strokeDashoffset = `${circ * (1 - frac)}`;
    ring.classList.toggle("over", remaining < 0);

    $("#t-goal").textContent = fmt(goal);
    $("#t-eaten").textContent = fmt(t.eaten);
    $("#t-burned").textContent = fmt(t.burned);
    $("#t-protein").textContent = `${fmt(t.protein)} / ${L.proteinTarget(state.profile)} g`;

    // Water
    const water = $("#water");
    water.replaceChildren();
    for (let i = 0; i < WATER_GOAL; i++) {
      water.append(el("button", {
        class: `glass${i < day.water ? " full" : ""}`,
        "aria-label": `Glass ${i + 1}${i < day.water ? " (drunk)" : ""}`,
        onclick: () => {
          day.water = i < day.water ? i : i + 1;
          save();
          if (day.water === WATER_GOAL) toast("Water goal reached! 💧");
          renderToday();
        },
      }));
    }
    $("#water-label").textContent = `${day.water} / ${WATER_GOAL} glasses`;

    // Tasks
    $("#tasks-progress").textContent = `${t.done} of ${t.taskCount} done`;
    $("#tasks-bar").style.width = `${t.taskCount ? (t.done / t.taskCount) * 100 : 0}%`;
    const order = L.SLOTS.map((s) => s.id);
    const nowIdx = order.indexOf(currentSlot());
    const pending = day.tasks
      .filter((x) => !x.done)
      .sort((a, b) => {
        // Current and later slots first, earlier (missed) slots after.
        const ra = (order.indexOf(a.slot) - nowIdx + 4) % 4;
        const rb = (order.indexOf(b.slot) - nowIdx + 4) % 4;
        return ra - rb;
      })
      .slice(0, 3);
    const list = $("#next-tasks");
    list.replaceChildren();
    if (!pending.length) {
      list.append(el("li", { class: "empty" }, "All done for today. Great work! 🎉"));
    } else {
      for (const task of pending) list.append(taskItem(task, renderToday, true));
    }

    renderWeek(goal);
  }

  function renderWeek(goal) {
    const keys = L.lastDays(7);
    const values = keys.map((k) => L.totals(state.days[k]).eaten);
    const max = Math.max(goal * 1.3, ...values, 1);
    const week = $("#week");
    week.replaceChildren();
    week.style.setProperty("--goal-pos", `${(goal / max) * 100}%`);
    keys.forEach((k, i) => {
      const [y, m, d] = k.split("-").map(Number);
      const label = new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short" });
      const v = values[i];
      week.append(el("div", { class: "col", title: `${label}: ${fmt(v)} kcal` },
        el("div", { class: "col-track" },
          el("div", { class: `col-fill${v > goal ? " over" : ""}`, style: `height:${(v / max) * 100}%` })),
        el("span", { class: "col-val" }, v ? fmt(v) : "–"),
        el("span", { class: "col-day" }, label)));
    });

    // Streak: consecutive days (ending today or yesterday) with at least half the tasks done.
    let streak = 0;
    const days = L.lastDays(365);
    let i = days.length - 1;
    const good = (k) => {
      const t = L.totals(state.days[k]);
      return t.taskCount > 0 && t.done / t.taskCount >= 0.5;
    };
    if (!good(days[i])) i--; // today isn't over yet
    while (i >= 0 && good(days[i])) { streak++; i--; }
    $("#streak").textContent = streak
      ? `🔥 ${streak}-day streak of finishing at least half your tasks`
      : "Finish at least half of today's tasks to start a streak.";
  }

  function taskItem(task, rerender, showSlot) {
    const slot = L.SLOTS.find((s) => s.id === task.slot);
    return el("li", { class: `task${task.done ? " done" : ""}` },
      el("label", {},
        el("input", {
          type: "checkbox",
          checked: task.done,
          onchange: (e) => {
            task.done = e.target.checked;
            save();
            if (task.done) toast(task.kcal ? `Nice! +${task.kcal} kcal burned` : "Nice work! ✅");
            rerender();
          },
        }),
        el("span", { class: "task-text" }, task.text),
      ),
      el("span", { class: "task-meta" },
        showSlot && slot ? el("span", { class: "pill" }, slot.label) : null,
        task.kcal ? el("span", { class: "pill burn" }, `${task.kcal} kcal`) : null,
        task.custom ? el("button", {
          class: "icon", "aria-label": "Delete task",
          onclick: () => {
            const day = today();
            day.tasks = day.tasks.filter((x) => x !== task);
            save();
            rerender();
          },
        }, "✕") : null,
      ));
  }

  function renderTasks() {
    const day = today();
    const t = L.totals(day);
    $("#tasks-count").textContent = `${t.done} of ${t.taskCount} done`;
    const now = currentSlot();
    const wrap = $("#slots");
    wrap.replaceChildren();
    for (const slot of L.SLOTS) {
      const tasks = day.tasks.filter((x) => x.slot === slot.id);
      wrap.append(el("div", { class: `slot${slot.id === now ? " now" : ""}` },
        el("h3", {}, slot.label, " ", el("span", { class: "muted small" }, slot.time),
          slot.id === now ? el("span", { class: "pill now-pill" }, "Now") : null),
        el("ul", { class: "task-list" },
          tasks.length ? tasks.map((x) => taskItem(x, renderTasks, false))
            : el("li", { class: "empty" }, "Nothing here."))));
    }
  }

  function renderFood() {
    const day = today();
    const goal = L.calorieTarget(state.profile);
    const t = L.totals(day);
    $("#food-total").textContent = `${fmt(t.eaten)} / ${fmt(goal + t.burned)} kcal`;

    const chips = $("#quick-foods");
    if (!chips.childElementCount) {
      for (const f of L.QUICK_FOODS) {
        chips.append(el("button", {
          type: "button", class: "chip",
          onclick: () => addFood({ name: f.name, kcal: f.kcal, protein: f.protein, meal: guessMeal() }),
        }, `${f.name} · ${f.kcal}`));
      }
    }

    const list = $("#food-list");
    list.replaceChildren();
    if (!day.foods.length) {
      list.append(el("p", { class: "empty" }, "Nothing logged yet. Add your first meal above."));
      return;
    }
    for (const meal of ["breakfast", "lunch", "dinner", "snack"]) {
      const items = day.foods.filter((f) => f.meal === meal);
      if (!items.length) continue;
      const sum = items.reduce((s, f) => s + f.kcal, 0);
      list.append(el("div", { class: "meal" },
        el("div", { class: "row-between" },
          el("h3", {}, meal[0].toUpperCase() + meal.slice(1)),
          el("span", { class: "muted" }, `${fmt(sum)} kcal`)),
        el("ul", { class: "food-items" }, items.map((f) =>
          el("li", {},
            el("span", {}, f.name),
            el("span", { class: "food-right" },
              f.protein ? el("span", { class: "muted small" }, `${f.protein} g protein`) : null,
              el("strong", {}, `${fmt(f.kcal)}`),
              el("button", {
                class: "icon", "aria-label": `Remove ${f.name}`,
                onclick: () => {
                  day.foods = day.foods.filter((x) => x.id !== f.id);
                  save();
                  renderFood();
                },
              }, "✕")))))));
    }
  }

  function guessMeal() {
    const h = new Date().getHours();
    if (h < 11) return "breakfast";
    if (h < 15) return "lunch";
    if (h >= 17 && h < 22) return "dinner";
    return "snack";
  }

  function addFood(f) {
    const day = today();
    day.foods.push({ id: uid(), ...f });
    save();
    toast(`Added ${f.name} (${f.kcal} kcal)`);
    renderFood();
  }

  // ---------- profile ----------
  const form = $("#profile-form");

  function setUnits(units) {
    document.body.classList.toggle("imperial", units === "imperial");
    form.querySelector(".weight-label").textContent = units === "imperial" ? "Weight (lb)" : "Weight (kg)";
    form.heightCm.required = units !== "imperial";
    form.heightFt.required = units === "imperial";
  }

  function fillProfileForm() {
    const p = state.profile;
    if (!p) return;
    const units = p.units || "metric";
    form.units.value = units;
    form.sex.value = p.sex;
    form.age.value = p.age;
    form.activity.value = p.activity;
    form.goal.value = p.goal;
    if (units === "imperial") {
      const totalIn = p.heightCm / 2.54;
      form.heightFt.value = Math.floor(totalIn / 12);
      form.heightIn.value = Math.round((totalIn % 12) * 10) / 10;
      form.weight.value = Math.round(L.kgToLb(p.weightKg) * 10) / 10;
    } else {
      form.heightCm.value = p.heightCm;
      form.weight.value = p.weightKg;
    }
    setUnits(units);
  }

  function renderProfile() {
    const has = L.validProfile(state.profile);
    $("#profile-title").textContent = has ? "Your profile" : "Let's set up your plan";
    $("#profile-intro").hidden = has;
    $("#profile-summary").hidden = !has;
    if (!has) return;
    const p = state.profile;
    const rows = [
      ["Resting burn (BMR)", `${fmt(L.bmr(p))} kcal`],
      ["Daily calorie goal", `${fmt(L.calorieTarget(p))} kcal`],
      ["Daily protein goal", `${L.proteinTarget(p)} g`],
      ["Goal", L.GOALS[p.goal].label],
    ];
    $("#numbers").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  }

  for (const [k, v] of Object.entries(L.ACTIVITY)) $("#activity-select").append(el("option", { value: k }, v.label));
  for (const [k, v] of Object.entries(L.GOALS)) $("#goal-select").append(el("option", { value: k }, v.label));
  for (const s of L.SLOTS) $("#slot-select").append(el("option", { value: s.id }, `${s.label} (${s.time})`));
  $("#activity-select").value = "light";
  $("#goal-select").value = "maintain";

  form.addEventListener("change", (e) => {
    if (e.target.name === "units") setUnits(e.target.value);
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const units = form.units.value;
    const num = (v) => parseFloat(v);
    const heightCm = units === "imperial"
      ? L.inToCm(num(form.heightFt.value) * 12 + (num(form.heightIn.value) || 0))
      : num(form.heightCm.value);
    const weightKg = units === "imperial" ? L.lbToKg(num(form.weight.value)) : num(form.weight.value);
    const profile = {
      units,
      sex: form.sex.value,
      age: Math.round(num(form.age.value)),
      heightCm: Math.round(heightCm * 10) / 10,
      weightKg: Math.round(weightKg * 10) / 10,
      activity: form.activity.value,
      goal: form.goal.value,
    };
    if (!L.validProfile(profile)) {
      $("#profile-error").textContent = "Please check your details: age 13–100, a realistic height and weight.";
      return;
    }
    $("#profile-error").textContent = "";
    const isNew = !L.validProfile(state.profile);
    const goalChanged = state.profile && state.profile.goal !== profile.goal;
    state.profile = profile;
    // A new goal means a new plan for today (keep any custom tasks and finished ones).
    const key = todayKey();
    if (goalChanged && state.days[key]) {
      const day = state.days[key];
      const keep = day.tasks.filter((t) => t.custom || t.done);
      day.tasks = [...L.generateTasks(key, profile).filter((t) => !keep.some((k) => k.id === t.id)), ...keep];
    }
    save();
    toast(isNew ? "Plan ready! Here's your day." : "Profile saved");
    showTab(isNew ? "today" : "profile");
  });

  $("#reset-btn").addEventListener("click", () => {
    if (!confirm("Delete your profile and every day you've logged? This can't be undone.")) return;
    state = { profile: null, days: {} };
    try { localStorage.removeItem(STORE_KEY); } catch (_) { /* ignore */ }
    form.reset();
    setUnits("metric");
    currentTab = "today";
    render();
  });

  // ---------- food & task forms ----------
  $("#food-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const name = f.food.value.trim();
    const kcal = Math.round(parseFloat(f.kcal.value));
    if (!name || !(kcal >= 0)) return;
    const protein = Math.round(parseFloat(f.protein.value)) || 0;
    addFood({ name, kcal, protein, meal: f.meal.value });
    f.food.value = "";
    f.kcal.value = "";
    f.protein.value = "";
    f.food.focus();
  });

  $("#task-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const text = f.text.value.trim();
    if (!text) return;
    today().tasks.push({
      id: `custom-${uid()}`, slot: f.slot.value, text,
      kcal: Math.max(0, Math.round(parseFloat(f.kcal.value)) || 0),
      done: false, custom: true,
    });
    save();
    f.text.value = "";
    f.kcal.value = "";
    toast("Task added");
    renderTasks();
  });

  // ---------- wiring ----------
  for (const b of document.querySelectorAll("#tabs button")) {
    b.addEventListener("click", () => showTab(b.dataset.tab));
  }
  document.addEventListener("click", (e) => {
    const go = e.target.closest("[data-goto]");
    if (go) showTab(go.dataset.goto);
  });
  // Pick up a new day (fresh tasks) if the page stays open past midnight.
  document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });

  $("#profile-form").units.value = "metric";
  fillProfileForm();
  setUnits(state.profile?.units || "metric");
  if (L.validProfile(state.profile)) showTab("today");
  else render();
})();
