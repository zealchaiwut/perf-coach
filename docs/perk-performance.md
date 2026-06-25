# Peak Performance & Race Targeting — Design Doc (draft)

## The theory (what it's called)
The "train toward a point, dip, then rebound higher" curve is the **fitness–fatigue
model** (Banister impulse–response), and the rebound itself is **supercompensation**.

- Every session adds **fitness** (slow to build, slow to fade) AND **fatigue**
  (big immediate hit, fades faster).
- **Performance ≈ fitness − (k × fatigue).** Right after a hard session you are
  fitter but buried in fatigue, so measured performance dips. Fatigue clears faster
  than fitness, so performance rebounds ABOVE the starting point — if recovery is
  adequate.
- Push too hard / too often → fatigue stacks faster than it clears → performance
  slopes down and takes longer to recover (non-functional overreaching).
- The **peak** is when fatigue has decayed but fitness has not yet — exactly what a
  **taper** engineers. The apex of the reverse-parabola = race day.

This is the SAME CTL/ATL/TSB machinery already planned, reinterpreted as a curve:
- **CTL = Fitness** (~42-day average of daily load)
- **ATL = Fatigue** (~7-day average)
- **TSB = Form = CTL − ATL** → this IS the performance score / the curve we plot.

## The sweet spot (two scales)
- **Micro (per hard session):** stimulate → dip → rebound. Hit the next hard session
  at the rebound, not during the dip. Too soon, repeatedly = overreaching.
- **Macro (the block):** progressively load (TSB drifts negative, "buried"), then
  taper (TSB swings positive, "peaked"). Time the positive swing to land on race day.

## The race plan (worked example: Half PR)
Target: **Half marathon, sub-1:50, A-race ~mid-December.**
Principle: train the COMPONENTS of 1:50 without ever running a full 1:50 trial
(a max effort costs weeks of recovery). Specifically:
- Same goal pace, shorter distance (e.g. 15 km at goal pace), OR
- Longer distance, slightly slower (e.g. 1:55–1:57 long runs).
- Then **taper** so form peaks on race day.

## Why this is verifiable (the science loop)
It gives a **predicted vs. actual** test:
1. Model predicts TSB (form) PEAKS on a date if the taper is right.
2. Efficiency / pace-at-HR should trend up through the block and spike at taper.
3. Run the actual race. If the measured performance peak lines up with the predicted
   TSB peak → the model held FOR ME. If not, my personal fitness/fatigue time-constants
   are wrong and I retune them.
The generic ~42/~7-day constants are population defaults; logging real races calibrates
MY constants. One race calibrates; 2–3 cycles confirm reliability.

## What to build (capstone, after the data sprints)
A **Race Plan + Performance Curve** feature:
1. **Target race entity** — date, distance, goal time, goal pace (mirror the weight-goal
   pattern: start → target → date).
2. **Performance curve** = TSB over time, framed as the reverse-parabola (shaded
   "buried" when negative, "fresh/peaked" when positive). Mark today.
3. **Forward projection** — given planned load + taper, project where TSB lands on race
   day; show "on track / ahead / behind" the peak line.
4. **Taper guidance** — when to start backing off so the peak lands on the date.
5. **Specificity tracker** — progress toward the goal's COMPONENTS (goal-pace volume
   accumulated, longest continuous effort) without doing the full trial.
6. **Post-race calibration** — log actual result, compare to predicted peak, adjust
   personal fitness/fatigue constants. This closes the verification loop.

## Honest caveats (build it sound)
- TSB predicts READINESS, not finish time → validate against efficiency trend + the
  actual race, not as truth.
- Needs several weeks of consistent load before projections mean anything → show
  "building baseline" early.
- One race won't statistically prove the theory → frame as personal calibration.
- Model ignores sleep/stress/illness/heat → leave an HRV/sleep correction hook.

## Dependencies
Builds on: unified daily load → fitness model (CTL/ATL/TSB) → performance scores
→ THIS. Ship the performance-score & fitness-model sprints first.

## Open decisions
- Projection scope: forward-simulate planned sessions (needs a Plan input, deferred),
  OR start with "curve so far + taper recommendation" and add simulation later.
- Race entity: reuse a shared races/goal table mirroring the weight start→target→date
  pattern.