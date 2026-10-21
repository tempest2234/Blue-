// Problem generators and answer checking. Runs in the browser and in Node (tests).

const rand = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const randNonZero = (min, max) => {
  let n = 0;
  while (n === 0) n = rand(min, max);
  return n;
};
const pick = (arr) => arr[rand(0, arr.length - 1)];
const gcd = (a, b) => (b === 0 ? Math.abs(a) : gcd(b, a % b));

function fraction(n, d) {
  if (d < 0) [n, d] = [-n, -d];
  const g = gcd(n, d) || 1;
  return { n: n / g, d: d / g };
}
const fracText = ({ n, d }) => (d === 1 ? `${n}` : `${n}/${d}`);
const signed = (n) => (n < 0 ? `- ${-n}` : `+ ${n}`);
// Formats a coefficient in front of a variable: 1x -> x, -1x -> -x.
const coef = (n, v) => (n === 1 ? v : n === -1 ? `-${v}` : `${n}${v}`);

export const LEVELS = {
  1: {
    name: "Beginner",
    description: "Addition and subtraction",
    topics: {
      add: {
        name: "Addition",
        make() {
          const a = rand(1, 50), b = rand(1, 50);
          return { question: `${a} + ${b} = ?`, answer: a + b, hint: "Add the ones first, then the tens." };
        },
      },
      subtract: {
        name: "Subtraction",
        make() {
          const a = rand(5, 99), b = rand(1, a);
          return { question: `${a} − ${b} = ?`, answer: a - b, hint: "Count back from the bigger number, or think: what plus " + b + " makes " + a + "?" };
        },
      },
    },
  },
  2: {
    name: "Elementary",
    description: "Multiplication and division",
    topics: {
      multiply: {
        name: "Multiplication",
        make() {
          const a = rand(2, 12), b = rand(2, 12);
          return { question: `${a} × ${b} = ?`, answer: a * b, hint: `${a} × ${b} means adding ${a} together ${b} times.` };
        },
      },
      divide: {
        name: "Division",
        make() {
          const b = rand(2, 12), q = rand(2, 12);
          return { question: `${b * q} ÷ ${b} = ?`, answer: q, hint: `Which number times ${b} gives ${b * q}?` };
        },
      },
      word: {
        name: "Word problems",
        make() {
          const boxes = rand(3, 9), each = rand(3, 12);
          const item = pick(["apples", "pencils", "stickers", "cookies"]);
          return {
            question: `There are ${boxes} boxes with ${each} ${item} in each box. How many ${item} are there in total?`,
            answer: boxes * each,
            hint: "Equal groups means multiplication.",
          };
        },
      },
    },
  },
  3: {
    name: "Middle school",
    description: "Fractions, percentages, negatives, order of operations",
    topics: {
      fractions: {
        name: "Adding fractions",
        make() {
          const d1 = rand(2, 9), d2 = rand(2, 9);
          const n1 = rand(1, d1 - 1), n2 = rand(1, d2 - 1);
          const ans = fraction(n1 * d2 + n2 * d1, d1 * d2);
          return {
            question: `${n1}/${d1} + ${n2}/${d2} = ? (simplest form, e.g. 7/6)`,
            answer: ans,
            display: fracText(ans),
            hint: "Find a common denominator first, then add the numerators.",
          };
        },
      },
      percent: {
        name: "Percentages",
        make() {
          const p = pick([5, 10, 15, 20, 25, 30, 40, 50, 75]);
          const base = rand(1, 20) * 20;
          return { question: `What is ${p}% of ${base}?`, answer: (p * base) / 100, hint: `${p}% means ${p} out of every 100. Try finding 10% or 1% first.` };
        },
      },
      negatives: {
        name: "Negative numbers",
        make() {
          const a = rand(-20, 20), b = rand(-20, 20);
          const op = pick(["+", "−", "×"]);
          const ans = op === "+" ? a + b : op === "−" ? a - b : a * b;
          const bt = b < 0 ? `(${b})` : `${b}`;
          return { question: `${a} ${op} ${bt} = ?`, answer: ans, hint: "Subtracting a negative is the same as adding. A negative times a negative is positive." };
        },
      },
      order: {
        name: "Order of operations",
        make() {
          const a = rand(2, 9), b = rand(2, 9), c = rand(2, 9), d = rand(1, 9);
          if (Math.random() < 0.5) {
            return { question: `${a} + ${b} × ${c} − ${d} = ?`, answer: a + b * c - d, hint: "Multiply before you add or subtract." };
          }
          return { question: `(${a} + ${b}) × ${c} − ${d} = ?`, answer: (a + b) * c - d, hint: "Do what's inside the parentheses first." };
        },
      },
    },
  },
  4: {
    name: "High school",
    description: "Algebra: equations, quadratics, exponents",
    topics: {
      linear: {
        name: "Linear equations",
        make() {
          const a = randNonZero(-9, 9), x = rand(-10, 10), b = rand(-20, 20);
          return {
            question: `Solve for x: ${coef(a, "x")} ${signed(b)} = ${a * x + b}`,
            answer: x,
            hint: "Get the x term alone on one side, then divide by its coefficient.",
          };
        },
      },
      quadratic: {
        name: "Quadratic equations",
        make() {
          const r1 = rand(-9, 9), r2 = rand(-9, 9);
          const b = -(r1 + r2), c = r1 * r2;
          let eq = "x^2";
          if (b !== 0) eq += ` ${b < 0 ? "-" : "+"} ${coef(Math.abs(b), "x")}`;
          if (c !== 0) eq += ` ${signed(c)}`;
          const roots = r1 === r2 ? [r1] : [r1, r2];
          return {
            question: `Solve: ${eq} = 0 (give all solutions, separated by commas)`,
            answer: roots,
            display: roots.join(", "),
            hint: `Find two numbers that multiply to ${c} and add up to ${b}.`,
          };
        },
      },
      exponents: {
        name: "Exponents",
        make() {
          const base = rand(2, 5), m = rand(1, 3), n = rand(1, 3);
          if (Math.random() < 0.5) {
            return { question: `${base}^${m} × ${base}^${n} = ? (as a number)`, answer: base ** (m + n), hint: "When multiplying powers with the same base, add the exponents." };
          }
          const e = rand(2, 4);
          return { question: `${base}^${e} = ?`, answer: base ** e, hint: `Multiply ${base} by itself ${e} times.` };
        },
      },
    },
  },
  5: {
    name: "Advanced",
    description: "Calculus basics and systems of equations",
    topics: {
      derivative: {
        name: "Derivatives",
        make() {
          const a = randNonZero(-5, 5), b = rand(-9, 9), c = rand(-9, 9), x0 = rand(-4, 4);
          let f = coef(a, "x^3");
          if (b !== 0) f += ` ${b < 0 ? "-" : "+"} ${coef(Math.abs(b), "x^2")}`;
          if (c !== 0) f += ` ${c < 0 ? "-" : "+"} ${coef(Math.abs(c), "x")}`;
          return {
            question: `f(x) = ${f}. Find f'(${x0}).`,
            answer: 3 * a * x0 * x0 + 2 * b * x0 + c,
            hint: "Use the power rule: the derivative of x^n is n·x^(n−1). Then plug in the value.",
          };
        },
      },
      system: {
        name: "Systems of equations",
        make() {
          const x = rand(-8, 8), y = rand(-8, 8);
          let a1, b1, a2, b2;
          do {
            a1 = randNonZero(-5, 5); b1 = randNonZero(-5, 5);
            a2 = randNonZero(-5, 5); b2 = randNonZero(-5, 5);
          } while (a1 * b2 - a2 * b1 === 0);
          const eq = (a, b) => `${coef(a, "x")} ${b < 0 ? "-" : "+"} ${coef(Math.abs(b), "y")} = ${a * x + b * y}`;
          return {
            question: `Solve the system:  ${eq(a1, b1)}  and  ${eq(a2, b2)}  (answer as x, y)`,
            answer: { pair: [x, y] },
            display: `${x}, ${y}`,
            hint: "Multiply one equation so a variable cancels when you add or subtract them (elimination).",
          };
        },
      },
      integral: {
        name: "Definite integrals",
        make() {
          const k = rand(1, 4), lo = rand(0, 2), hi = lo + rand(1, 3);
          // ∫ (k+1)·x^k dx from lo to hi = hi^(k+1) − lo^(k+1): always a whole number.
          const c = k + 1;
          return {
            question: `Evaluate the integral of ${coef(c, `x^${k}`).replace("^1", "")} dx from ${lo} to ${hi}.`,
            answer: hi ** c - lo ** c,
            hint: `An antiderivative of x^n is x^(n+1)/(n+1). Evaluate at ${hi}, then subtract the value at ${lo}.`,
          };
        },
      },
    },
  },
};

export function makeProblem(level, topicKey) {
  const topics = LEVELS[level].topics;
  const key = topicKey && topics[topicKey] ? topicKey : pick(Object.keys(topics));
  const p = topics[key].make();
  return { ...p, level, topic: key, display: p.display ?? String(p.answer) };
}

function parseNumber(text) {
  const t = text.trim().replace(/^x\s*=\s*/i, "").replace(/−/g, "-");
  const frac = t.match(/^(-?\d+)\s*\/\s*(-?\d+)$/);
  if (frac) {
    const d = Number(frac[2]);
    return d === 0 ? NaN : Number(frac[1]) / d;
  }
  return t === "" ? NaN : Number(t);
}

const close = (a, b) => Math.abs(a - b) < 1e-9;

export function checkAnswer(problem, input) {
  const text = String(input).trim();
  if (!text) return false;
  const ans = problem.answer;

  if (Array.isArray(ans)) {
    // Unordered set of solutions.
    const got = text.split(/[,;]|\band\b/).map((s) => parseNumber(s)).filter((n) => !Number.isNaN(n));
    const want = [...new Set(ans)];
    const uniq = [...new Set(got)];
    return uniq.length === want.length && want.every((w) => uniq.some((g) => close(g, w)));
  }
  if (ans && ans.pair) {
    const nums = text.replace(/[xy]\s*=/gi, "").replace(/[()]/g, "").split(/[,;]|\s+/).filter(Boolean).map(parseNumber);
    return nums.length === 2 && close(nums[0], ans.pair[0]) && close(nums[1], ans.pair[1]);
  }
  if (ans && typeof ans === "object" && "n" in ans) {
    // Fractions must be in simplest form; whole numbers are accepted too.
    const m = text.replace(/−/g, "-").match(/^(-?\d+)\s*\/\s*(-?\d+)$/);
    if (m) {
      const n = Number(m[1]), d = Number(m[2]);
      if (d === 0 || gcd(n, d) !== 1) return false;
      const f = fraction(n, d);
      return f.n === ans.n && f.d === ans.d;
    }
    return ans.d === 1 && close(parseNumber(text), ans.n);
  }
  return close(parseNumber(text), ans);
}
