# Muscle-Load Ledger

## Purpose

Every training session that generates TSS contributes TSS-weighted stress to the
muscle groups it uses. The ledger answers "which muscles are overused / undertrained"
across an arbitrary look-back window. The **ACWR view** (next sprint) reads from this
table; this document is the contract for writers.

## Ledger Table: `muscle_load_daily`

| Column         | Type                | Notes                                          |
|----------------|---------------------|------------------------------------------------|
| `id`           | UUID PK             | auto                                           |
| `user_id`      | UUID FK → users     | session user; CASCADE on delete                |
| `load_date`    | Date                | calendar date of the training session          |
| `muscle_group` | VARCHAR(30)         | one of the canonical groups below              |
| `load`         | NUMERIC(10,4)       | TSS units contributed to this group            |
| `source`       | VARCHAR(20)         | `strength` | `run` | `plyo`                    |
| `created_at`   | TIMESTAMPTZ         | last write timestamp                           |

**Unique constraint:** `(user_id, load_date, muscle_group, source)` — one row per
group per source per day per user.

### Idempotency

Writers are **replace-on-recompute**: before inserting new rows for
`(user, date, source)`, the writer deletes all existing rows with that triple.
This means running the writer twice for the same date produces identical results —
no double-counting.

---

## Canonical Muscle Groups

| Canonical group | Covered catalog parts                                                |
|-----------------|----------------------------------------------------------------------|
| `calf`          | calves, calf, soleus, gastrocnemius                                  |
| `quad`          | quads, quad, quadriceps                                              |
| `hamstring`     | hamstrings, hamstring                                                |
| `glute`         | glutes, glute, gluteus, gluteus maximus                              |
| `hip`           | hip, hip flexors, hip flexor                                         |
| `core`          | core, abs, abdominals, obliques, oblique                             |
| `back`          | back, lats, latissimus, latissimus dorsi, rhomboids, rhomboid,       |
|                 | traps, trapezius, lower back, erector spinae                         |
| `shoulder`      | shoulders, shoulder, deltoids, delts, rotator cuff                   |
| `chest`         | chest, pecs, pectorals, pectoral                                     |
| `arm`           | biceps, triceps, forearms, forearm, arms, arm, brachialis            |
| `other`         | anything not in the above mapping (never dropped)                    |

Parts are normalised to lowercase before lookup. Unknown parts fall to `other`.

---

## Strength Distribution Math

**Input:** strength workout / session with total TSS = *T*, exercises *e₁…eₙ*.

### Step 1 — Exercise volumes

For each exercise *i*:

```
volume_i = sets_i × reps_i × weight_kg_i
```

**Fallback constants** (named in `backend/services/muscle_load.py`):

| Situation                     | Substitute                          |
|-------------------------------|-------------------------------------|
| `weight_kg` absent            | treat weight as 1 (sets × reps)     |
| `reps` absent                 | `DEFAULT_REPS = 10`                 |
| sets, reps, weight all absent | `volume_i = 0` → equal-share below  |

### Step 2 — Exercise shares

```
total_volume = Σ volume_i

share_i = volume_i / total_volume   (if total_volume > 0)
        = 1 / n                     (equal share when all volumes == 0)
```

### Step 3 — Muscle-group distribution

For each exercise *i* and its catalog `body_parts` list `{part_k, ratio_k}`:

```
group = normalize_part(part_k)          # canonical group or "other"
muscle_load[group] += T × share_i × ratio_k
```

Groups are summed across all exercises for the day. A muscle group that appears
in multiple exercises accumulates contributions from each.

### Worked example

Calf raises 3×12×40 kg and squats 3×8×80 kg; total TSS = 40.

| Exercise      | sets | reps | weight | volume |
|---------------|------|------|--------|--------|
| calf raises   | 3    | 12   | 40     | 1 440  |
| squats        | 3    | 8    | 80     | 1 920  |
| **total**     |      |      |        | **3 360** |

Shares: calf_raises = 1440/3360 ≈ 0.4286; squats = 1920/3360 ≈ 0.5714

Catalog (example):
- calf raises → [{part: "calves", ratio: 1.0}]
- squats → [{part: "quads", ratio: 0.5}, {part: "glutes", ratio: 0.3}, {part: "hamstrings", ratio: 0.2}]

Loads:
- `calf`      = 40 × 0.4286 × 1.0          ≈ 17.14
- `quad`      = 40 × 0.5714 × 0.5          ≈ 11.43
- `glute`     = 40 × 0.5714 × 0.3          ≈  6.86
- `hamstring` = 40 × 0.5714 × 0.2          ≈  4.57

Sum ≈ 40.0 ✓

---

## Strength Session TSS Estimation

`StrengthSession` rows do not store TSS directly. The writer estimates it:

1. **RPE × duration (preferred):** collect all rows for the user/date, average
   their `session_rpe` values, sum `duration_minutes`. Then:
   ```
   IF = session_rpe / 10
   TSS = IF² × (total_duration_minutes / 60) × 100
   ```
2. **Duration-only fallback (IF = 0.7):** when no RPE is recorded but duration
   exists. Consistent with the `duration_only` convention in `tss.md`.
3. **Zero:** when no RPE and no duration are available.

---

## Sources

| Source     | Populated by                           |
|------------|----------------------------------------|
| `strength` | strength-type `workouts` + `strength_sessions` |
| `run`      | run-type workouts (next ticket)        |
| `plyo`     | `plyo_sessions` (next ticket)          |

---

## Unclassified Exercises

Exercises not found in `exercise_catalog` contribute no load to any group.
Their names are surfaced in the `GET /api/training/muscle-load` response via
an `unclassified: [names]` field so the user can prompt a catalog classification.

---

## ACWR Read Layer (issue #1380)

### Endpoint

`GET /api/training/muscle-load?weeks=N` (default N=8, range 1–52).
Derives `acute_7d`, `chronic_28d`, `acwr`, and classification for each
canonical group from `muscle_load_daily`. Session-user scoped; anonymous → 401.

### Math

Mirrors `backend/services/acwr.py` (uncoupled rolling-window variant):

```
acute_7d    = Σ daily_load for days [today−6 … today]
chronic_28d = mean( weekly_total(days −35…−29),
                    weekly_total(days −28…−22),
                    weekly_total(days −21…−15),
                    weekly_total(days −14…−8) )
acwr        = acute_7d / chronic_28d   (null when chronic_28d < CHRONIC_FLOOR)
```

Daily load is the sum across all sources (strength + run + plyo).
The acute window is **excluded** from chronic — the same "uncoupled" variant
used in `acwr.py`.

### Classification constants (`backend/services/muscle_load_acwr.py`)

| Constant         | Value | Meaning                                          |
|------------------|-------|--------------------------------------------------|
| `CHRONIC_FLOOR`  | 5.0   | Weekly chronic below this → ACWR undefined       |
| `OVERUSED_BOUND` | 1.5   | acwr > 1.5 → **overused** (= acwr.HIGH_BOUND)   |
| `ELEVATED_BOUND` | 1.3   | acwr > 1.3 → **elevated** (= acwr.UPPER_BOUND)  |
| `DETRAINING_BOUND`| 0.8  | acwr < 0.8 → **detraining** (= acwr.LOWER_BOUND)|

Classification logic (checked in order):

1. `chronic < CHRONIC_FLOOR` → **untrained** (priority group) or **inactive**
2. `acwr > OVERUSED_BOUND` → **overused**
3. `acwr > ELEVATED_BOUND` → **elevated**
4. `acwr >= DETRAINING_BOUND` → **balanced**
5. otherwise → **detraining**

**Priority groups** (lower-body focus; flagged `untrained` when chronic is
near zero): `calf`, `hamstring`, `glute`, `hip`.

Non-priority groups with near-zero chronic are classified `inactive`
(informational; not flagged as a training gap).

### Injury tagging

Active `injury_log` entries (started_on ≤ today AND ended_on IS NULL or ≥
today) whose `body_area` maps to a canonical group via `BODY_AREA_TO_GROUP`
(in `muscle_load_acwr.py`) cause that group's payload entry to carry
`"injured": true`. The classification is still computed — the tag rides
alongside so downstream consumers (gap-analyzer rules, planner) can defer.

---

## Planning Guard: Footprint Estimator (issue #1383)

`backend/services/plan_guard.py` provides a **pure** footprint estimator for
planned sessions and a plan-check function used by `POST /api/training/plan-check`.

### Footprint estimation per session type

The estimator returns per-group **shares** (0–1) that mirror the same profiles
used by the ledger writers — there is exactly one model.

| Session type | Profile used | Notes |
|---|---|---|
| `run` | `RUN_PROFILE` (flat baseline) | No elevation tilt applied (planned sessions carry no elevation data) |
| `plyo` | `PLYO_PROFILE` | calf 70%, quad 15%, glute 15% |
| `strength` | `distribute_strength_tss` with notional TSS=100 | Requires catalog lookup; returns empty when no exercises or catalog unavailable |
| `rest` / `stretch` | — | Returns empty dict (no load) |

### Plan-check logic

`check_session(session_type, footprint, group_stats)` compares the footprint
against the live classifications from `GET /api/training/muscle-load`.

**Warnings** — for each group whose share ≥ `DOMINANT_SHARE_THRESHOLD` (0.15):

- `classification == "overused"` → warn
- `injured == True` (any classification) → warn
- `"elevated"` alone does NOT warn

**Suggestions** — for `strength` sessions only:
- Untrained priority groups (calf/hamstring/glute/hip) not injured and not
  already dominantly targeted by the session.

### Endpoint

`POST /api/training/plan-check`

```json
// request
{ "session_type": "plyo", "structure": null }

// response
{
  "warnings":    [{"muscle_group": "calf", "classification": "overused", "message": "..."}],
  "suggestions": [{"muscle_group": "hamstring", "reason": "..."}]
}
```

Always 200 — warnings are informational, never blocking.
