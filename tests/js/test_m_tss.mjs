import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const fixtures = JSON.parse(readFileSync(join(ROOT, "tests/fixtures/strength_tss_sessions.json"), "utf8"));

function load() {
  const sandbox = { window: null, Math };
  sandbox.window = sandbox;
  const ctx = createContext(sandbox);
  runInContext(readFileSync(join(ROOT, "frontend/js/m/tss.js"), "utf8"), ctx);
  return ctx.MTss;
}

test("JS fromExercises matches shared fixtures", () => {
  const MTss = load();
  fixtures.forEach(function (fix) {
    if (!Object.prototype.hasOwnProperty.call(fix, "expect_exercises_tss")) return;
    const got = MTss.fromExercises(fix.exercises);
    assert.equal(got.tss, fix.expect_exercises_tss, fix.name);
  });
});

test("JS fromEffortTime matches shared fixtures", () => {
  const MTss = load();
  fixtures.forEach(function (fix) {
    if (fix.expect_effort_tss == null) return;
    const got = MTss.fromEffortTime(fix.duration_min, fix.effort);
    assert.equal(got.tss, fix.expect_effort_tss, fix.name);
  });
});
