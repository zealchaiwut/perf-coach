import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function load() {
  const sandbox = { window: null, Date, Math };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const ctx = createContext(sandbox);
  runInContext(readFileSync(join(ROOT, "frontend/js/m/timer.js"), "utf8"), ctx);
  return ctx.MTimer;
}

test("odd/even EMOM assigns the right exercise per minute", () => {
  const MTimer = load();
  const steps = MTimer.emomSteps([
    { name: "KB swing", emom: { minute_rule: "odd" } },
    { name: "Step-up", emom: { minute_rule: "even" } },
  ], 8);
  assert.equal(steps.length, 8);
  assert.equal(steps[0].payload.name, "KB swing");
  assert.equal(steps[1].payload.name, "Step-up");
  assert.equal(steps[6].payload.name, "KB swing");
});

test("pause then resume keeps remaining time (fake clock)", () => {
  const MTimer = load();
  let now = 1_000_000;
  const eng = new MTimer.Engine([{ label: "WORK", kind: "work", seconds: 40 }], null, () => now);
  eng.start();
  now += 10_000;
  assert.equal(Math.round(eng.stepRemaining() / 1000), 30);
  eng.pause();
  now += 90_000;
  assert.equal(Math.round(eng.stepRemaining() / 1000), 30);
  eng.resume();
  now += 5_000;
  assert.equal(Math.round(eng.stepRemaining() / 1000), 25);
});

test("screen lock of 90s advances the minute", () => {
  const MTimer = load();
  let now = 0;
  const steps = MTimer.emomSteps([{ name: "A", emom: { minute_rule: "every" } }], 8);
  const eng = new MTimer.Engine(steps, null, () => now);
  eng.start();
  now += 90_000;
  eng.tick();
  assert.equal(eng.i, 1);
});

test("cue fires at 3s remaining", () => {
  const MTimer = load();
  let now = 0;
  const cues = [];
  const eng = new MTimer.Engine([{ label: "W", kind: "work", seconds: 10 }], null, () => now);
  eng.onCue = (i) => cues.push(i);
  eng.start();
  now += 7_000;
  eng.tick();
  assert.deepEqual(cues, [0]);
});

test("40/20 × 6 alternates A and B", () => {
  const MTimer = load();
  const steps = MTimer.intervalSteps([{ name: "Dead bug" }, { name: "Climber" }], 6, 40, 20);
  assert.equal(steps.length, 12);
  assert.equal(steps[0].kind, "work");
  assert.equal(steps[0].payload.name, "Dead bug");
  assert.equal(steps[2].payload.name, "Climber");
  assert.equal(steps[1].kind, "rest");
});
