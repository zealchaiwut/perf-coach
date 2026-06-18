# Regenerating Golden Expected Outputs

This document explains when and how to regenerate
`tests/fixtures/golden_run_expected.json`, the hand-verified expected-outputs
file for the workout-metrics regression test suite (issue #577).

---

## When to regenerate

**Regenerate only when you have intentionally changed a metric formula.**

Correct reasons to regenerate:
- You improved the normalized-power algorithm (e.g. changed the rolling-window
  duration or the fourth-power exponent on purpose).
- You replaced the formula with a more accurate standard (e.g. switched to the
  official TrainingPeaks NP definition).

**Do NOT regenerate to fix a failing test.** If `tests/test_golden_metrics__577.py`
fails, that is the regression suite doing its job — a formula change silently
altered an output. Investigate the diff first. Only regenerate after you have
confirmed the new value is correct.

---

## The exact command

```bash
make regen-golden
```

This runs `python scripts/regen_golden.py`, which:
1. Loads `tests/fixtures/golden_run.json` (the static fixture — never modified).
2. Runs every currently implemented metric calculation.
3. Overwrites `tests/fixtures/golden_run_expected.json` with the new values.

To preview the new values without writing the file:

```bash
python scripts/regen_golden.py --dry-run
```

---

## Required peer-review step

After regenerating, **a second engineer must manually verify the new expected
values before the PR is merged**:

1. Open `tests/fixtures/golden_run_expected.json` and read the new
   `normalized_power.value` and `normalized_power.final_value_exact`.
2. Spot-check by hand: look at the fixture's power stream in
   `tests/fixtures/golden_run.json` and confirm the reported NP is plausible
   for the effort profile (e.g. for a ~265 W mean-power run, an NP of ~268 W
   is reasonable — NP is always ≥ mean power for variable efforts).
3. Optionally run `python scripts/regen_golden.py --dry-run` locally to
   reproduce the value independently.
4. Leave a PR review comment explicitly stating you verified the new expected
   values (e.g. _"Confirmed: NP 268 → 271 W is consistent with the formula
   change in commit abc1234"_).

This step is non-optional. A regenerated expected-outputs file without a
peer-verification comment will not be merged.

---

## The static fixture

`tests/fixtures/golden_run.json` is **static and must not be modified** to fix
a failing test. It represents a single known-good workout that all metric
formulas are validated against. Changing the fixture invalidates all previously
hand-verified expected values and breaks the audit trail.

If the fixture itself needs updating (e.g. to add a new stream channel for a
new metric), treat that as a separate ticket, regenerate expected outputs after
the fixture change, and get the full peer-review.
