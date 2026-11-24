import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function loadToday() {
  const sandbox = {
    window: null,
    document: {
      getElementById() { return null; },
      addEventListener() {},
    },
    AppCommon: {
      escapeHtml(s) {
        return String(s)
          .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
      },
    },
  };
  sandbox.window = sandbox;
  const ctx = createContext(sandbox);
  runInContext(readFileSync(join(ROOT, "frontend/js/m/today.js"), "utf8"), ctx);
  return ctx;
}

function htmlOf(kindBundle) {
  const ctx = loadToday();
  const root = { innerHTML: "" };
  ctx.MToday.render(root, kindBundle);
  return root.innerHTML;
}

const BASE = {
  today: { date: "2026-11-24", block_name: "Osaka block", plan_phase: "build wk 1" },
  sessions: [],
  recent_runs: [{
    name: "Morning Run",
    date: "2026-11-22",
    duration_seconds: 3763,
    distance_km: 9,
    pace_sec_per_km: 418,
    tss: 87,
  }],
  body: null,
};

test("strength variant uses bundle TSS and gym deep link", () => {
  const html = htmlOf({
    ...BASE,
    sessions: [{
      id: "s-a",
      date: "2026-11-24",
      name: "Strength A · economy",
      session_type: "strength",
      exercises: [
        { name: "Pogo hops", sets: [{ reps: 20 }] },
        { name: "SL deadlift", sets: [{ kg: 12, reps: 8 }] },
        { name: "Calf raise", sets: [{ kg: 20, reps: 12 }] },
        { name: "Hold", sets: [{ hold: "45s" }] },
        { name: "Stretch", sets: [] },
      ],
      estimated_tss: 38,
      duration_minutes: 45,
    }],
  });
  assert.match(html, /TODAY · STRENGTH/);
  assert.match(html, /Strength A · economy/);
  assert.match(html, /≈38 TSS/);
  assert.match(html, /5 exercises/);
  assert.match(html, /\/m\/gym\/s-a/);
  assert.match(html, /Ready offline/);
  assert.doesNotMatch(html, /data-today-kind="run"/);
});

test("run variant has Details, not gym", () => {
  const html = htmlOf({
    ...BASE,
    sessions: [{
      id: "r1",
      date: "2026-11-24",
      name: "Easy run 40 min",
      session_type: "run",
      estimated_tss: 38,
      duration_minutes: 40,
      exercises: [],
    }],
  });
  assert.match(html, /TODAY · RUN/);
  assert.match(html, /Details/);
  assert.doesNotMatch(html, /\/m\/gym\//);
  assert.match(html, /≈38 TSS/);
});

test("rest variant", () => {
  const html = htmlOf({
    ...BASE,
    sessions: [{
      id: "rest",
      date: "2026-11-24",
      name: "Rest",
      session_type: "rest",
      exercises: [],
    }],
  });
  assert.match(html, /TODAY · REST/);
  assert.match(html, /Rest day|Rest/);
  assert.doesNotMatch(html, /Start session/);
});

test("nothing planned", () => {
  const html = htmlOf({ ...BASE, sessions: [] });
  assert.match(html, /Nothing planned/);
  assert.match(html, /data-today-kind="empty"/);
  assert.doesNotMatch(html, /Start session/);
});

test("body card hidden when bundle.body is null", () => {
  const html = htmlOf({ ...BASE, body: null });
  assert.doesNotMatch(html, /id="m-body-card"/);
});

test("values come from the bundle, not a client TSS formula", () => {
  const src = readFileSync(join(ROOT, "frontend/js/m/today.js"), "utf8");
  assert.match(src, /estimated_tss/);
  assert.doesNotMatch(src, /MTss/);
});
