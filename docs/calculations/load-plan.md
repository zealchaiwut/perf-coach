# Session Load Plan — Race-Anchored Weekly TSS Targets

**Purpose:** turn a ramp/hold/taper rule into a per-week target-TSS series
counting up to an A race, so the season chart, the weekly target card, and
Suggest-sessions all agree on one number per week.

## Load model (`backend/services/load_plan.py`)

Single pure function, `compute_load_plan(baseline, ramp_rate, hold_weeks,
taper_weeks, weeks_to_race, trailing_28d_avg, deload_enabled=False,
deload_start_week=4)`. No SQL,
no dates — the calling endpoint resolves the A race, `weeks_to_race`,
`baseline` (last completed week's **actual** TSS, never planned — a missed
week must lower future targets, not silently inflate them — capped against
chronic load, see "Baseline cap" below), and `trailing_28d_avg`.

```
build_weeks = weeks_to_race - taper_weeks
ramp_weeks  = build_weeks - hold_weeks
peak        = baseline * (1 + ramp_rate) ** (ramp_weeks + 1)

target(w) for w in 1..ramp_weeks              = baseline * (1 + ramp_rate) ** w
target(w) for w in ramp_weeks+1 .. build_weeks = peak                     # exactly hold_weeks weeks
target(w) for taper week i (0-indexed)         = peak * TAPER_CURVE[i]

if deload_enabled and phase == ramp
        and week_index % 4 == deload_start_week % 4:
    target(w) *= (1 - DELOAD_CUT_FRACTION)     # deload BEFORE the ceiling clamp

target(w) = min(target(w), ceiling(w))         # MOVING ceiling always wins — see below
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
- `ACWR_CEILING_MULT = 1.3` — mirrors `plan_suggestions.ACWR_HIGH_BOUND`,
  itself a mirror of `acwr.UPPER_BOUND` (1.3), **not** `acwr.HIGH_BOUND`
  (1.5). See "Known weaknesses" below.
- **Validation:** `ramp_weeks < 1` (i.e. `hold_weeks + taper_weeks >=
  weeks_to_race`) clamps `ramp_weeks = 0`, `peak = baseline`, and returns a
  `warning` string instead of negative ramp weeks (:151-162).
- **Counterintuitive, worth a UI tooltip:** raising `hold_weeks` *lowers*
  peak — it shortens the ramp for a fixed `weeks_to_race`.

### Moving ACWR ceiling (2026-07-09 fix)

The ceiling used to be a single static number
(`ACWR_CEILING_MULT * trailing_28d_avg`) applied unchanged to every future
week. Since the ramp is exponential, it typically overtakes that static
number within a few weeks — and every week after that clamped to the exact
same value, producing a chart that flatlines for a dozen weeks instead of
continuing to ramp. That's wrong: a static "today's chronic load" ceiling
doesn't account for the fact that, by the time the athlete is several weeks
into the plan, their OWN recent training load has moved too.

Each week's ceiling is now `ACWR_CEILING_MULT` times the mean of the trailing
4 weeks' ACTUAL (post-deload, post-clamp) `target_tss` in the series being
built — a real rolling 28-day chronic-load window, computed over the plan's
own sequence. The window is seeded with `[trailing_28d_avg] * 4` for the 4
"virtual" weeks before week 1 (we only have the real aggregate, not a
per-week breakdown, for history before the plan starts); after each week is
finalized, it's pushed into the window and the oldest value drops off. Each
`WeekTarget` now exposes its own `ceiling` (and `deload: bool`) so callers
don't need to recompute it — `GET /api/plan/week-load`'s `acwr_ceiling` and
`plan_suggestions.assemble_facts`'s `acwr_ceiling` both now read the target
week's own `ceiling` from the series instead of recomputing a static number
independently, so the season chart, the week card, and Suggest-sessions can
never disagree about what the guardrail is for a given week.

A deload week's cut value legitimately pulls the following weeks' ceiling
down a little — a real down week does lower rolling chronic load — but
because the ceiling keeps moving with the plan's own trajectory rather than
staying pinned to today, the ramp still climbs freely as long as no single
week jumps more than `ACWR_CEILING_MULT`× above its own trailing window.

### Deload — "cut 30% every 4th week" (`deload_enabled`, `deload_start_week`)

When on (`TrainingPlan.deload_enabled`, off by default), every 4th
`week_index` starting at `deload_start_week` (`TrainingPlan.deload_start_week`,
1–4, default 4 → weeks 4, 8, 12, ...; start 2 → weeks 2, 6, 10, ...) that
falls in the **ramp** phase is cut by `DELOAD_CUT_FRACTION = 0.30` before
the ceiling clamp. The start week is the athlete's pick of which week of
the 4-week cycle is the down week — someone already two weeks into a build
wants the next deload in two weeks, not re-zeroed to week 4 of the plan.
Hold weeks are never deloaded (2026-07 fix: taper immediately follows and
already IS the recovery reduction), and taper/race weeks are never cut
further — they already have their own down-curve.

The cut is a single down week, not a ramp reset: `target(w)` is always
computed directly from `baseline * (1 + ramp_rate) ** w` (or `peak` in hold),
never recursively from week `w-1`'s value, so week 5 resumes the ramp from
where week 4 *would have been* without the cut — exactly the "return to
before cut" behaviour a real deload week is supposed to have. (The moving
ceiling above still sees the cut value in its rolling window, which is
correct — it's real load history, even if intentionally reduced.)

### Baseline cap (2026-07-10 fix)

`baseline` (last completed week's actual TSS) is wrong when that week was
itself a spike — the ramp would then compound an overshoot that already
exists before the plan even starts. Example from a real report: CTL ≈ 32
implies chronic load ≈ 224 TSS/week, but the seeding week ran 316 TSS —
roughly 40% above chronic. Ramping 5%/week off 316 keeps that overshoot
alive for the whole build.

`compute_load_plan` now caps the baseline actually used for the ramp/peak
math: `baseline = min(raw_baseline, BASELINE_CAP_MULT * chronic_weekly)`,
where `chronic_weekly` is the SAME `trailing_28d_avg` already passed in for
the moving ceiling above — one number, two uses, never a second independent
"chronic load" estimate. `BASELINE_CAP_MULT = 1.15`, a named constant (not a
literal). The result exposes all four values so callers can render the cap
instead of hiding it:

```
raw_baseline     — last week's actual TSS, uncapped
baseline         — the value actually used for ramp/peak (may equal raw_baseline)
chronic_weekly   — == trailing_28d_avg; None if not enough history
baseline_capped  — True when baseline < raw_baseline
```

**The Session Load Plan card must say so plainly when `baseline_capped` is
true** — e.g. *"Baseline capped: last week (316) exceeded chronic load;
using 258."* A silent cap is worse than no cap: the athlete sees a lower
number than their own logged week and, without an explanation, reads it as
the ramp being broken rather than as a safety feature working as intended.

This is a **different guard** from the moving ACWR ceiling: the cap fixes
the ramp's *starting point* (once); the ceiling limits *each week* going
forward. Both apply — the cap runs first, then every downstream week
(including week 1) is still subject to its own moving ceiling.

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

`PUT /api/plan/rules` updates `ramp_rate`, `hold_weeks`, `taper_length`,
`deload_enabled`, `deload_start_week` on the athlete's existing `TrainingPlan` row
(`_resolve_or_create_plan`) — Plan and Performance tabs edit the **same**
row; this endpoint must never create a second one.

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
6. The moving ceiling's pre-week-1 seed (`[trailing_28d_avg] * 4`) assumes
   the 4 weeks before the plan started were each exactly at the aggregate
   average — a simplification, since only the aggregate (not a per-week
   breakdown) is available. Fine in practice (it only affects the first ~4
   weeks' ceiling before the rolling window is fully "real"), but not a
   precise reconstruction of actual history.

## ML-readiness

- Same blocking gap as ACWR/Guardrail: no injury/illness labels, so there's
  no way to learn whether a given ramp_rate/hold_weeks combination was
  actually safe for a given athlete — today's constants are heuristic.
- Once labels exist: the natural next step is per-athlete ramp_rate
  recommendation (rather than a fixed 5% default) from historical
  ramp-vs-outcome data.
