# Session Load Plan — Race-Anchored Weekly TSS Targets

**Purpose:** turn a ramp/hold/taper rule into a per-week target-TSS series
counting up to an A race, so the season chart, the weekly target card, and
Suggest-sessions all agree on one number per week.

## Load model (`backend/services/load_plan.py`)

Single pure function, `compute_load_plan(baseline, ramp_rate, hold_weeks,
taper_weeks, weeks_to_race, trailing_28d_avg)`. No SQL, no dates — the
calling endpoint resolves the A race, `weeks_to_race`, `baseline` (last
completed week's **actual** TSS, never planned — a missed week must lower
future targets, not silently inflate them), and `trailing_28d_avg`.

```
build_weeks = weeks_to_race - taper_weeks
ramp_weeks  = build_weeks - hold_weeks
peak        = baseline * (1 + ramp_rate) ** (ramp_weeks + 1)

target(w) for w in 1..ramp_weeks              = baseline * (1 + ramp_rate) ** w
target(w) for w in ramp_weeks+1 .. build_weeks = peak                     # exactly hold_weeks weeks
target(w) for taper week i (0-indexed)         = peak * TAPER_CURVE[i]
target(w) = min(target(w), ACWR_CEILING_MULT * trailing_28d_avg)          # ceiling always wins
```

- The `+ 1` exponent on `peak` is deliberate: without it the ramp's last week
  equals peak, so a 4-week hold renders 5 bars at peak. With it, the ramp
  tops out strictly below peak and the hold block is exactly `hold_weeks`
  long (load_plan.py:1-50 docstring has the full worked example).
- `TAPER_CURVE = [0.75, 0.60, 0.40]` (load_plan.py:64) — a documented
  constant, not a magic number; no equivalent existed before this module.
  Interpolated via `_taper_fractions` (:98-118) when `taper_weeks != 3`.
  TODO: make configurable per plan; today every plan shares one curve.
- **The final taper week's `phase` is `"race"`, not `"taper"`** — it's the
  week containing race day, and the UI renders it as a distinct color (see
  the mock's pink "Race week" bar). The other taper weeks stay `"taper"`.
- `ACWR_CEILING_MULT = 1.3` (:71-77) — mirrors
  `plan_suggestions.ACWR_HIGH_BOUND`, itself a mirror of `acwr.UPPER_BOUND`
  (1.3), **not** `acwr.HIGH_BOUND` (1.5). See "Known weaknesses" below.
- **Validation:** `ramp_weeks < 1` (i.e. `hold_weeks + taper_weeks >=
  weeks_to_race`) clamps `ramp_weeks = 0`, `peak = baseline`, and returns a
  `warning` string instead of negative ramp weeks (:151-162).
- **Counterintuitive, worth a UI tooltip:** raising `hold_weeks` *lowers*
  peak — it shortens the ramp for a fixed `weeks_to_race`.

## A-race resolution and endpoints (`backend/main.py`)

`GET /api/plan/load-plan` resolves the user's A race as **the next
upcoming, `status="planned"`, `priority="A"` race** — the same convention
`plan_suggestions.assemble_facts` already uses (`Race.race_date > today,
status == "planned", priority == "A"`), not the broader "any status/date"
convention `_compute_plan_bundle`/`GET /api/projection` use for their own
"primary race" concept. A race that already happened or isn't confirmed
can't be ramped/taper toward — but be aware this means the Plan tab's A
race and the Projection/Performance tab's "primary race" can theoretically
diverge (e.g. a past A race still shown as primary elsewhere). No A race ⇒
`204` and the UI shows "Set a goal race to generate weekly targets."

`baseline` comes from `get_weekly_volume` (training_load.py) for the most
recently **completed** ISO week (Bangkok time, matching
`plan_suggestions`'s `today_bangkok()` convention). `trailing_28d_avg` is
the mean of the last 4 weekly TSS totals from the same daily-load series
`compute_acwr`/`plan_suggestions` already build — not a new computation.

`PUT /api/plan/rules` updates `ramp_rate`, `hold_weeks`, `taper_length` on
the athlete's existing `TrainingPlan` row (`_resolve_or_create_plan`) — Plan
and Performance tabs edit the **same** row; this endpoint must never create
a second one.

## Known weaknesses

1. `ACWR_CEILING_MULT` (1.3) mirrors `acwr.UPPER_BOUND`, not
   `acwr.HIGH_BOUND` (1.5) — the "high risk" threshold used everywhere else
   in the app. This is an inherited discrepancy from `plan_suggestions.py`,
   not introduced here; worth reconciling in a follow-up rather than
   silently fixing (changes what "hits the ceiling" means for existing
   Suggest-sessions behavior).
2. Two different "find the A race" conventions coexist in the codebase (see
   above) — this module picks the future/planned-only one deliberately, but
   a reader landing on `_compute_plan_bundle`'s broader version first may
   assume they're the same race.
3. `ramp_rate` was repurposed from an absolute TSS/week value (the old
   client-only schedule preview in training-plan.js) to a fraction. Any
   pre-existing non-zero/non-null values were backfilled to `0.05` by the
   migration rather than converted — there was no reliable way to convert
   "TSS/week" to "%/week" without knowing the athlete's baseline at the time
   the value was set.
4. `TAPER_CURVE` interpolation for `taper_weeks` far from 3 (e.g. 1 or 6) is
   linear-in-index over 3 control points — reasonable for small deviations,
   untested for extreme values.
5. Not cached; computed live per request (matches ACWR's own "not cached"
   note in acwr-guardrail.md).

## ML-readiness

- Same blocking gap as ACWR/Guardrail: no injury/illness labels, so there's
  no way to learn whether a given ramp_rate/hold_weeks combination was
  actually safe for a given athlete — today's constants are heuristic.
- Once labels exist: the natural next step is per-athlete ramp_rate
  recommendation (rather than a fixed 5% default) from historical
  ramp-vs-outcome data.
