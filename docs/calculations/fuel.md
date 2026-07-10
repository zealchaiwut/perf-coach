# Fuel — Daily Calorie Budget + Weekly Projection

**Purpose:** turn training load (logged or planned) into a daily calorie
budget and macro targets, and project the week's total deficit — so the
Weight tab's "Fuel today" and "Fuel week" cards agree on one number per day,
the same way the Plan tab's Session Load Plan agrees with Suggest-sessions.

## Every number here is an estimate, not a fact

Maintenance was falsified once for this athlete: five weeks of flat weight
proved actual intake was ~700 kcal/day above what a Mifflin-St Jeor-style
estimate predicted. Every budget number in this feature is derived from a
`fuel_settings.base_kcal` that starts as a guess (`maintenance_source =
'estimated'`) and stays a guess until the calibrate flow (below) runs and
sets it to `'measured'`. The UI must never present a computed budget as
authoritative — the derivation chain (`base + burn − deficit = budget`) is
always visible, and the `estimated`/`measured` chip is never hidden.

## Food coefficients (`backend/services/fuel.py::FOOD`)

Per gram, COOKED weight (except eggs: per egg; oil: per teaspoon):

```python
FOOD = {
    "meat":  {"kcal": 1.65, "p": 0.310, "c": 0.000, "f": 0.036},
    "rice":  {"kcal": 1.30, "p": 0.027, "c": 0.280, "f": 0.003},
    "egg":   {"kcal": 70.0, "p": 6.300, "c": 0.400, "f": 5.000},
    "fruit": {"kcal": 0.60, "p": 0.008, "c": 0.150, "f": 0.002},
    "oil":   {"kcal": 45.0, "p": 0.000, "c": 0.000, "f": 5.000},
}
```

- **Meat and rice are COOKED weight.** Raw→cooked is a ~25% error on the
  biggest protein source — the UI states this in the block header, not a
  tooltip.
- **Eggs are a count, never grams** (`1 egg ≈ 50 g` in the row's sub-label).
- Every row's coefficient is printed in its sub-label (e.g. `165 kcal · 31 g
  P per 100 g`) — the arithmetic is never hidden.
- These are approximations (±10-15% error), deliberately chosen over a food
  database for a 5-row benchmark.

**Note on the originating spec's worked example:** the spec's Part 4 test
list states `200 g meat + 350 g rice + 2 eggs + 200 g fruit + 1 tsp oil` ⇒
`1,090 kcal, 72 g P`. The kcal figure matches this coefficient table exactly
(`330 + 455 + 140 + 120 + 45 = 1090`); the protein figure does not — the same
inputs against the same table give **85.6 g P** (`62 + 9.45 + 12.6 + 1.6 =
85.65`), not 72 g. Per this repo's own precedent ("if the code and doc
disagree, fix the code and say so" — see acwr-guardrail.md), the explicit,
heavily-annotated coefficient block is trusted as ground truth over the
prose example, since it's the one meant to be copied verbatim and is
internally self-consistent (its own kcal math checks out). The test suite
asserts 85.6 g, not 72 g — flagging here rather than silently "fixing" the
number to match a possibly-mistyped example.

## Burn estimate (`training_burn_kcal`)

```python
run_kcal   = weight_kg * distance_km * run_kcal_per_kg_per_km   # ~1.0 kcal/kg/km, per-user override
other_kcal = duration_min * MET_TABLE[workout_type] * weight_kg / 60
```

Distance × mass is preferred over any device-reported calorie figure —
watch/Stryd burn numbers are consistently optimistic. `MET_TABLE` (approx.,
no per-user override yet — see "Known weaknesses"):

| workout_type | MET |
|---|---|
| `lift` / `strength` | 5.0 |
| `plyo` | 8.0 |
| `bike` | 8.0 |
| `wod` | 8.0 |
| `rest` | 0.0 |
| unrecognized (fallback) | 5.0 |

Workout-type strings are normalized the same way the frontend's
`training-format.js::normalizeType` does (`run(ning)?|race` → `run`,
`lift|strength` → `lift`, `bike|ride|cycl` → `bike`, `wod|crossfit` → `wod`)
— a Python-side mirror of that regex, kept in `fuel.py::_normalize_type`
rather than imported (no shared Python/JS module exists to import from).

For planned sessions with no distance, run distance is estimated via the
SAME `training_load.estimate_planned_session_metrics` +
`estimate_historical_pace_and_tss` baseline already used by the Plan tab's
planned-session cards — not a second independent estimator. Non-run planned
duration comes from `training_load._planned_duration_minutes` (imported
directly; no service-to-service cycle risk since `training_load.py` doesn't
import `fuel.py`).

## Past vs. future (`backend/services/fuel.py::_day_sessions_and_burn`)

**Past days use logged workouts. Today and future days use the plan.** A
skipped session must not keep granting calories it never earned.

- `date < today` → burn from `workouts` (logged).
- `date == today` → planned, UNLESS a workout is already logged today, in
  which case that takes over (the session is done, use the real number).
- `date > today` → `planned_sessions`, falling back to the rest-day budget
  (`day_type = "rest"`, `burn = 0`) when no non-rest session is planned.
- A past day whose planned session has no matching workout (no
  `matched_workout_id`, `status` not `done_*`) reports `session_status =
  "skipped"` and its burn is `0` — the day gets the rest-day budget, not the
  budget the plan promised.

`day_type` (`rest | lift | easy_run | long_run`) is derived from the same
sessions: any run session ≥ 75 minutes (mirrors
`training_load._RUN_DURATION_BUCKETS`'s "long" bucket) → `long_run`; any
shorter run → `easy_run`; any non-run, non-rest session with no run → `lift`;
nothing → `rest`.

## Budget (`compute_budget`)

```python
raw_budget    = base_kcal + burn - deficit_kcal
ea_floor_kcal = ea_floor * lean_mass_kg + burn      # minimum intake to hold EA >= 30
budget        = max(raw_budget, ea_floor_kcal)
deficit_applied = base_kcal + burn - budget         # may be < deficit_kcal
```

**The energy-availability floor is a hard stop, not a warning.** `EA =
(intake − burn) / lean_mass`. Below ~30 kcal/kg, recovery, endocrine
function, and bone health degrade (RED-S). When the floor binds, the
service reduces the deficit itself (`deficit_reduced: true`) — the biggest
deficit must never land on the biggest training day, and the UI must never
ask the athlete to choose between the guideline and the plan; it states the
reduction plainly (*"Deficit reduced 400 → 300 because today is your
longest session."*).

Macro targets (`compute_targets`):

```python
protein_g = round(weight_kg * protein_g_per_kg)   # fixed · 2 g/kg, identical on rest and long-run days
fat_g     = settings.fat_g                        # constant — where the deficit comes from
carbs_g   = max(0, (budget - protein_g*4 - fat_g*9) / 4)   # the dial — scales with training load
```

## Suggestion (`compute_suggestion`)

Fill protein first, then carbs; round to plate-sized portions (25 g meat /
50 g rice increments); if the raw suggestion exceeds the remaining budget,
scale both down proportionally. Never renders a negative portion. When
`remaining <= 0`: *"Budget spent — fine on a long-run day if protein is
met."*

## Calibrate (`calibrate`, §1.5)

```python
predicted_delta_kg = sum(eaten - (base + burn)) / 7700
actual_delta_kg    = weekly_avg_weight_end - weekly_avg_weight_start
error_kcal_per_day = (predicted_delta_kg - actual_delta_kg) * 7700 / days
new_base_kcal      = base_kcal - error_kcal_per_day
```

Requires ≥14 days of history AND ≥10 logged `fuel_entries` rows in that
window; otherwise returns `needs_more_data` with the actual counts (never a
guess from insufficient data). Uses the first and last **calendar week**
(≤7 entries) of weight data on each end, not single days — daily weight is
mostly glycogen and water and would produce garbage. On success, sets
`fuel_settings.maintenance_source = 'measured'`.

## Data model

- `fuel_settings` — one row per user (`UniqueConstraint(user_id)`):
  `weight_kg`, `lean_mass_kg` (nullable, fallback `weight_kg * 0.76`),
  `base_kcal`, `maintenance_source` (`estimated | measured`),
  `deficit_kcal` (default 300, max 750), `protein_g_per_kg` (default 2.0,
  range 0.25-2.5), `fat_g` (default 70), `ea_floor` (default 30.0),
  `run_kcal_per_kg_per_km` (default 1.0).
- `fuel_entries` — one row per user per day (`UniqueConstraint(user_id,
  entry_date)`, upsert via `ON CONFLICT DO UPDATE` — two `PUT`s for the same
  date produce one row): `meat_g`, `rice_g`, `eggs`, `fruit_g`, `oil_tsp`,
  plus `other_kcal`/`other_protein_g`/`other_carbs_g`/`other_fat_g` for the
  preset buttons (Standard meal / Post-run feed / Snack / Reset).

## Endpoints (`backend/routers/fuel.py`)

| Endpoint | Reads | Writes |
|---|---|---|
| `GET /api/fuel/today?date=` | snapshot for one date | — |
| `PUT /api/fuel/entry` | — | upserts today's `fuel_entries` row, returns recomputed `GET` payload |
| `PUT /api/fuel/settings` | — | updates `fuel_settings` (422 on out-of-range `deficit_kcal`/`protein_g_per_kg`) |
| `POST /api/fuel/calibrate` | last ~3 weeks of `weight_entries` + `fuel_entries` | sets `base_kcal` + `maintenance_source` on success |
| `GET /api/fuel/week?week_start=` | 7 days, mixed logged/planned per §"Past vs. future" | — |

## Known weaknesses

1. `MET_TABLE` has no per-user override (unlike `run_kcal_per_kg_per_km`,
   which is a `fuel_settings` column) — every athlete gets the same lift/bike
   MET regardless of their actual intensity.
2. `_normalize_type` duplicates `training-format.js::normalizeType`'s regex
   in Python rather than sharing one implementation — same class of drift
   risk as any other cross-language duplication in this codebase.
3. The protein figure in the originating spec's own worked test example
   doesn't match its own coefficient table (see "Food coefficients" above) —
   flagged, not silently reconciled.
4. Calibrate's weekly-average window uses whatever `weight_entries` exist in
   the first/last ≤7 days of the lookback range, not a strict Monday-Sunday
   ISO week — fine for a rough correction, not a precise weekly boundary.
5. Not cached; `GET /api/fuel/today` and `/week` recompute burn (including a
   fresh `estimate_historical_pace_and_tss` baseline query) live per request,
   matching ACWR/Session-Load-Plan's own "not cached" precedent.

## ML-readiness

- Same blocking gap as readiness/ACWR: no logged "actual outcome" beyond
  weight trend — no way to learn a better MET table or per-athlete
  `run_kcal_per_kg_per_km` without more calibrate history over time.
- Once several calibrate runs exist per athlete, the natural next step is
  trending `base_kcal` corrections over time rather than a single fixed
  measured value.
