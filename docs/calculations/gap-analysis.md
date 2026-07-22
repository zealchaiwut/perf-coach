# Gap Analysis — Engine Contract

_Issue #1370 — sprint 107_

The gap analyzer turns a user's training data into prioritized "what to improve" findings. This document is the contract: finding schema, severity semantics, rule registry, and how to add a new rule.

---

## Finding Schema

Every finding is one row in `gap_findings` and is also returned in the API payload.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `string(80)` | Stable string id for the rule that fired. Never changes — used for dedup and accept/dismiss in sprint 108. Examples: `no_recent_plyo`, `muscle_imbalance`. |
| `severity` | `int 1\|2\|3` | 1 = note, 2 = recommend, 3 = priority |
| `recommendation` | `text` | Short imperative sentence for the athlete. No metadata, no units prose. |
| `evidence` | `jsonb list` | Machine-readable list of `{metric, value, threshold, window}` objects. No natural-language prose here — callers render text from the fields. |
| `target` | `string(100) \| null` | Muscle group or session type the finding addresses (e.g. `"plyo"`, `"glutes"`). Null when finding is general. |
| `week_start` | `date` | ISO Monday of the week the finding was computed for. |
| `status` | `string` | `active` (default) \| `accepted` \| `dismissed`. Set by the athlete in sprint 108; recomputing never overwrites status. |
| `computed_at` | `timestamptz` | When the engine ran. |

### Evidence shape

```json
[
  {
    "metric":    "days_since_plyo",
    "value":     35,
    "threshold": 28,
    "window":    "28d"
  }
]
```

- `metric` — stable key consumers can translate
- `value` — the observed value (may be `null` if the metric was never recorded)
- `threshold` — the boundary that triggered the finding
- `window` — human-readable lookback window for context

---

## Severity Semantics

| Level | Label | Meaning |
|-------|-------|---------|
| 1 | note | Low urgency; athlete should be aware but no immediate action required. |
| 2 | recommend | Moderate gap; act in the next 1–2 weeks. |
| 3 | priority | High-impact gap; act this week. |

---

## Persistence (gap_findings table)

Unique key: `(user_id, week_start, code)`.

Recomputing the same week **upserts**: `severity`, `recommendation`, `evidence`, `target`, and `computed_at` are refreshed. **`status` is preserved** — an athlete-accepted finding survives recomputes.

---

## Rule Registry

Rules live in `backend/services/gap_analysis/rules/`. Each rule is a pure function:

```python
def my_rule(inputs: dict) -> GapAnalysisFinding | None:
    ...
```

- **Pure**: no DB calls, no side effects. Inputs are pre-gathered by the engine.
- **Returns `None`** when the finding does not apply (athlete is within tolerance).
- **Returns a `GapAnalysisFinding`** when a gap is detected.

Rules are registered in `backend/services/gap_analysis/engine.py` via `_REGISTRY.register(requires=[...])`:

```python
_REGISTRY.register(requires=["structural_dose"])(my_rule)
```

`requires` is the list of input keys the rule needs from the inputs dict. If any required key is absent, the engine **skips** the rule and lists it in `skipped_rules` — it never crashes the run.

### Available inputs (sprint 107)

| Key | Source | Contents |
|-----|--------|----------|
| `structural_dose` | `backend/services/structural_dose.py` | `last_plyo_days_ago`, `last_strength_days_ago`, weekly plyo/strength buckets |
| `form_metrics` | `run_form_metrics` table (issue #1368) | `recent_runs` (0–28d), `prior_runs` (28–56d), `long_baseline_runs` (56–180d) — each a list of `{run_date, lss_kn_m, gct_ms, cadence_spm, power_w}` |
| `training_verdict` | `training_verdict.compute_verdict` (issue #1372) | `"back_off"` \| `"hold"` \| `"build"` — load-mix rules downgrade to severity 1 when `"back_off"` |
| `intensity_4w` | `workout_splits.intensity_band` (issue #1372) | `{low_pct, moderate_pct, high_pct}` — duration-weighted run-split distribution over 28 days; `None` when no classified splits exist |
| `long_run_decoupling_4w` | `workouts.decoupling_percent` (issue #1372) | `{avg_decoupling_pct, count}` — average aerobic decoupling for long runs (>40 min) over 28 days |
| `speed_score_history_8w` | `performance_score_history` (issue #1372) | `{oldest_speed, newest_speed, formula_version, count}` — speed score endpoints over 56 days at the latest formula_version; `None` when < 2 rows |
| `quality_sessions_3w` | `workouts.speed_signal` (issue #1372) | `{count, window_weeks}` — run workouts with a non-null `speed_signal` over 21 days |
| `injury_log` | `injury_log` table (issue #1350, #1373) | List of `{body_area, severity, started_on, ended_on}` for the last 90 days |
| `muscle_volume` | `muscle_load_daily` table (issue #1367, #1373) | List of `{week_start, muscle_group, weekly_load}` for the last 8 weeks |
| `training_load` | `workouts` table (issue #1373) | `{"weekly": [{week_start, running_tss}]}` for the last 8 weeks |
| `muscle_load_ledger` | `muscle_load_acwr.compute()` (issue #1381) | `{groups: {group: {acute_7d, chronic_28d, acwr, classification, injured, source_breakdown, trending_up, weeks_untrained}}, history_weeks}` — per-muscle-group load stats; `None` / absent when fewer than 4 weeks of muscle load data exist |
| `week_start` | engine | `datetime.date` — always present |
| `other_findings_codes` | registry (runtime, #1373) | List of `code` strings for findings that fired *before* the current rule. Injected by the registry so late rules can suppress themselves. |
| `claimed_groups` | registry (runtime, #1381) | `set[str]` of target group strings already claimed by a higher-priority rule. Pack D rules skip any group in this set to enforce one finding per group per week. |

Future sprints will add: `intensity_distribution`, `scores`.


---

## Adding a New Rule

1. Create `backend/services/gap_analysis/rules/my_rule.py`:

```python
from typing import Optional
from backend.services.gap_analysis.schemas import GapAnalysisFinding

def my_rule(inputs: dict) -> Optional[GapAnalysisFinding]:
    dose = inputs["structural_dose"]
    # ... compute ...
    return GapAnalysisFinding(
        code="my_rule",
        severity=2,
        recommendation="Do something specific.",
        evidence=[{"metric": "...", "value": ..., "threshold": ..., "window": "..."}],
        target="glutes",
        week_start=inputs["week_start"],
    )
```

2. Register it in `backend/services/gap_analysis/engine.py` inside `_register_builtin_rules()`:

```python
from backend.services.gap_analysis.rules.my_rule import my_rule
_REGISTRY.register(requires=["structural_dose"])(my_rule)
```

3. Write tests in `tests/test_<issue>_<slug>.py` covering:
   - Rule fires when threshold is exceeded
   - Rule is silent when athlete is within tolerance
   - Evidence shape (metric name, threshold value)
   - Rule registered in `_REGISTRY`

---

## API

`GET /api/training/gap-analysis`

Auth: session cookie required (401 if anonymous).

Response:

```json
{
  "week_start":   "2026-07-07",
  "computed_at":  "2026-07-13T08:42:00Z",
  "findings": [
    {
      "code":           "no_recent_plyo",
      "severity":       1,
      "recommendation": "Schedule a plyometric session this week to maintain reactive strength.",
      "evidence":       [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
      "target":         "plyo"
    }
  ],
  "skipped_rules": []
}
```

`skipped_rules` lists rule function names whose inputs were unavailable or that raised an exception — for observability, not user display.

---

## Reference Rule: no_recent_plyo

File: `backend/services/gap_analysis/rules/no_recent_plyo.py`

Fires when `structural_dose.last_plyo_days_ago` is `None` (never recorded) or `> 28`.

- `code`: `no_recent_plyo`
- `severity`: 1 (note)
- `evidence metric`: `days_since_plyo`
- `threshold`: 28 days
- `target`: `plyo`

---

## Run-Economy Rules (issue #1371)

### plyo_deficit

File: `backend/services/gap_analysis/rules/plyo_deficit.py`

Both conditions must be true for the finding to fire:

1. **LSS flat or falling**: 28-day mean LSS (`lss_kn_m`) improved by **strictly less than**
   `LSS_IMPROVEMENT_THRESHOLD_PCT` (1.0 %) vs the prior 28-day window.
2. **Plyo dose inadequate**: Average plyo sessions per week over the last
   `PLYO_DOSE_WINDOW_WEEKS` (4) weeks is **below** `PLYO_SESSIONS_PER_WEEK_MIN` (1.0).

Returns `None` when either 28-day window has fewer than `MIN_RUNS_PER_WINDOW` (3) runs
with valid LSS data.

Recommendation references the last logged `plyo_phase`; defaults to `"intro"` when
no phase is on record.

| Constant | Value | Meaning |
|----------|-------|---------|
| `LSS_IMPROVEMENT_THRESHOLD_PCT` | 1.0 | Minimum LSS gain (%) to be considered "improving" |
| `PLYO_SESSIONS_PER_WEEK_MIN` | 1.0 | Sessions/week needed to clear the dose check |
| `PLYO_DOSE_WINDOW_WEEKS` | 4 | Weeks used to compute average plyo frequency |
| `MIN_RUNS_PER_WINDOW` | 3 | Minimum valid-LSS runs required per window |

- `code`: `plyo_deficit`
- `severity`: 2 (recommend)
- `evidence metrics`: `lss_recent_mean`, `lss_prior_mean`, `lss_improvement_pct`, `plyo_sessions_per_week`
- `target`: `plyo`

---

### gct_lengthening

File: `backend/services/gap_analysis/rules/gct_lengthening.py`

Fires when ground contact time (GCT) has lengthened at comparable running intensity.

**Pace-band control**: only runs whose power is within `±(GCT_EASY_POWER_BAND_WIDTH_W / 2)`
of the recent window's mean power are included in both windows. This prevents slow recovery
runs (lower power → naturally higher GCT) from false-triggering the finding.

Returns `None` when:
- Either raw window has fewer than `MIN_RUNS_PER_WINDOW` (3) runs with valid GCT + power.
- After band filtering, either window falls below `MIN_RUNS_PER_WINDOW`.

| Constant | Value | Meaning |
|----------|-------|---------|
| `GCT_RISE_THRESHOLD_MS` | 5.0 | Minimum GCT rise (ms) to fire |
| `GCT_EASY_POWER_BAND_WIDTH_W` | 50.0 | Total intensity control band width (Watts) |
| `MIN_RUNS_PER_WINDOW` | 3 | Minimum runs required per filtered window |

- `code`: `gct_lengthening`
- `severity`: 2 (recommend)
- `evidence metrics`: `gct_recent_mean_ms`, `gct_prior_mean_ms`, `gct_rise_ms`, `power_band_center_w`
- `target`: `plyo`

---

### cadence_drift

File: `backend/services/gap_analysis/rules/cadence_drift.py`

Fires when the recent 28-day mean cadence has dropped more than `CADENCE_DRIFT_THRESHOLD_PCT`
below the long baseline (days 57–180).

Both windows are first filtered to easy-run intensity (issue #1463): only runs whose `power_w`
falls within ±`CADENCE_EASY_POWER_BAND_WIDTH_W`/2 (±25 W) of a band centre are kept. The band
centre is anchored to the lower of the two windows' mean power, so an interval block in either
window cannot drag the band into hard-effort territory. Runs without `power_w` are excluded; the
recent window must have ≥ `MIN_RUNS_PER_WINDOW` powered runs to anchor the band. When the long
baseline has no power data at all (e.g. Garmin-only imports), it falls back to all cadence-valid
runs (graceful degradation).

Returns `None` when either window has fewer than `MIN_RUNS_PER_WINDOW` (3) runs after easy-run
filtering, or when the recent window lacks that many powered runs.

| Constant | Value | Meaning |
|----------|-------|---------|
| `CADENCE_DRIFT_THRESHOLD_PCT` | 2.0 | Drop (%) required to fire |
| `CADENCE_BASELINE_WINDOW_DAYS` | 180 | Length of the long baseline window (days) |
| `CADENCE_EASY_POWER_BAND_WIDTH_W` | 50.0 | Width (W) of the easy-run intensity band; runs within ±half are kept |
| `MIN_RUNS_PER_WINDOW` | 3 | Minimum valid runs required per window after easy-run filtering |

- `code`: `cadence_drift`
- `severity`: 1 (note)
- `evidence metrics`: `cadence_recent_mean_spm`, `cadence_baseline_mean_spm`, `cadence_drop_pct`
- `target`: `run_form`

---

## Load-Mix Rules (issue #1372)

These rules diagnose what *kind* of running is missing. They all share one guardrail:
**when the current training verdict is `back_off`, each rule downgrades its severity from 2 to 1
and appends `" (deferred while backing off)"` to its recommendation** so the gap analyzer never
contradicts the load guardrail.

### intensity_too_hard

File: `backend/services/gap_analysis/rules/load_mix.py`

Fires when the 4-week duration-weighted hard-zone share exceeds the polarized target upper bound.
Reuses `check_polarized_split` from `polarized_split.py` — thresholds are **not** redefined here.
Only fires on a `high` band `above` deviation; grey-zone excess alone does not trigger it.

| Constant | Value | Meaning |
|----------|-------|---------|
| `HIGH_TARGET_UPPER_BOUND_PCT` | 20.0 | Imported from `_DEFAULT_BOUNDS["high"][1]` |

- `code`: `intensity_too_hard`
- `severity`: 2 (recommend) → 1 when verdict is `back_off`
- `evidence metrics`: `high_pct_4w`, `low_pct_4w`, `moderate_pct_4w`
- `target`: `easy_volume`

### aerobic_durability_gap

Fires when average aerobic decoupling on long runs (> 40 min) exceeds the threshold over a
4-week window, provided at least `LONG_RUN_MIN_COUNT` long runs have stored decoupling data.

| Constant | Value | Meaning |
|----------|-------|---------|
| `LONG_RUN_MIN_SECONDS` | 2400 | Minimum run duration to qualify as a long run (40 min) |
| `LONG_RUN_MIN_COUNT` | 2 | Minimum long-run sample required before the rule fires |
| `DECOUPLING_THRESHOLD_PCT` | 5.0 | Average decoupling % that triggers the finding |

- `code`: `aerobic_durability_gap`
- `severity`: 2 (recommend) → 1 when verdict is `back_off`
- `evidence metrics`: `avg_decoupling_pct_4w`, `long_run_count_4w`
- `target`: `long_run`

### speed_neglected

Fires when the Speed score (latest `formula_version` from `performance_score_history`) has
decayed by more than `SPEED_DECAY_THRESHOLD` over 8 weeks **and** quality sessions (runs with
a non-null `speed_signal`) average fewer than `QUALITY_SESSIONS_MIN_PER_WEEK` per week over
the past 3 weeks.  Mirrors the pattern of `base_neglected` (for Endurance with volume
evidence), with the quality-session count as volume evidence.

| Constant | Value | Meaning |
|----------|-------|---------|
| `SPEED_DECAY_THRESHOLD` | 10.0 | Points drop (oldest − newest) required to fire |
| `QUALITY_SESSIONS_WINDOW_WEEKS` | 3 | Rolling window for quality session count |
| `QUALITY_SESSIONS_MIN_PER_WEEK` | 1.0 | Minimum quality sessions/week to suppress the rule |

- `code`: `speed_neglected`
- `severity`: 2 (recommend) → 1 when verdict is `back_off`
- `evidence metrics`: `speed_score_decay_8w`, `speed_score_newest`, `quality_sessions_3w`
- `target`: `speed`

### base_neglected

File: `backend/services/gap_analysis/rules/load_mix.py` (issue #1464)

Fires when the Endurance score (latest `formula_version` from `performance_score_history`) has
decayed by more than `ENDURANCE_DECAY_THRESHOLD` over 8 weeks **and** easy-volume runs (runs
with a null `speed_signal`, i.e. non-quality sessions) average fewer than
`EASY_RUNS_MIN_PER_WEEK` per week over the past 3 weeks.  Mirrors `speed_neglected` but
anchored to the Endurance score with easy-run volume as the evidence.

Input keys:
- `endurance_score_history_8w` — gathered by `_gather_endurance_score_8w` in `engine.py`;
  reads the `endurance` column from `performance_score_history`.
- `easy_runs_3w` — gathered by `_gather_easy_runs_3w` in `engine.py`; counts runs with
  `speed_signal IS NULL` over the past 3 weeks.

| Constant | Value | Meaning |
|----------|-------|---------|
| `ENDURANCE_DECAY_THRESHOLD` | 10.0 | Points drop (oldest − newest) required to fire |
| `EASY_RUNS_WINDOW_WEEKS` | 3 | Rolling window for easy run count |
| `EASY_RUNS_MIN_PER_WEEK` | 2.0 | Minimum easy runs/week to suppress the rule |

- `code`: `base_neglected`
- `severity`: 2 (recommend) → 1 when verdict is `back_off`
- `evidence metrics`: `endurance_score_decay_8w`, `endurance_score_newest`, `easy_runs_3w`
- `target`: `easy_volume`

---

## Structural Rules (issue #1373)

### recurrent_niggle_area

File: `backend/services/gap_analysis/rules/recurrent_niggle_area.py`

Fires when any muscle group (resolved from `body_area` via `BODY_AREA_TO_MUSCLE_GROUP`) has
`>= RECURRENT_NIGGLE_MIN_COUNT` injury-log entries within the last `RECURRENT_NIGGLE_WINDOW_DAYS`
days. Fires for the group with the highest count; ties broken alphabetically.

**Body area → muscle group mapping**: `BODY_AREA_TO_MUSCLE_GROUP` in
`backend/services/muscle_load.py`. Examples: `left_calf` / `right_calf` → `calf`;
`left_hamstring` / `right_hamstring` → `hamstring`; `left_glute` / `right_glute` → `glute`.

| Constant | Value | Meaning |
|----------|-------|---------|
| `RECURRENT_NIGGLE_WINDOW_DAYS` | 90 | Lookback window for counting entries |
| `RECURRENT_NIGGLE_MIN_COUNT` | 2 | Minimum entries for same group to fire |

- `code`: `recurrent_niggle_area`
- `severity`: 3 (priority)
- `evidence metrics`: `niggle_count`, `most_recent_entry_date`
- `target`: canonical muscle group (e.g. `calf`)

---

### undertrained_area_under_ramp

File: `backend/services/gap_analysis/rules/undertrained_area_under_ramp.py`

Fires when **both** conditions hold for a lower-body priority muscle group
(`LOWER_BODY_PRIORITY_GROUPS = {calf, hamstring, glute}`):

1. **Zero strength volume**: The group has `weekly_load = 0` in `muscle_load_daily` for
   `>= ZERO_VOLUME_WEEKS_THRESHOLD` (4) consecutive trailing weeks.
2. **TSS is ramping**: The 4-week average running TSS has risen by more than
   `TSS_RAMP_THRESHOLD` (10 %) vs the prior 2-week average.

**Active severe injury guard**: If an active (ended_on=None) injury of severity
`>= ACTIVE_INJURY_SEVERITY_THRESHOLD` (2) maps to the same muscle group, the loading
recommendation is suppressed and a recovery-deferring message is surfaced instead.

| Constant | Value | Meaning |
|----------|-------|---------|
| `LOWER_BODY_PRIORITY_GROUPS` | `{calf, hamstring, glute}` | Groups monitored for this rule |
| `ZERO_VOLUME_WEEKS_THRESHOLD` | 4 | Trailing weeks of zero volume required |
| `TSS_RAMP_THRESHOLD` | 10.0 | Minimum TSS increase (%) to confirm ramp |
| `TSS_RAMP_WINDOW_WEEKS` | 4 | Total weeks for TSS ramp comparison |
| `ACTIVE_INJURY_SEVERITY_THRESHOLD` | 2 | Injury severity that suppresses loading advice |

- `code`: `undertrained_area_under_ramp`
- `severity`: 2 (recommend)
- `evidence metrics`: `zero_volume_weeks`, `tss_ramp_pct`, `running_tss_recent_mean`
- `target`: canonical muscle group

---

### strength_lapsed

File: `backend/services/gap_analysis/rules/strength_lapsed.py`

Fires when no strength sessions at all were recorded in the last `STRENGTH_LAPSED_DAYS`
(21) days. Acts as a general fallback reminder.

**Suppression**: automatically suppressed when `recurrent_niggle_area` or
`undertrained_area_under_ramp` already fired in the same run — those rules provide specific
actionable advice and stacking a generic reminder adds no value.

The registry injects `other_findings_codes` into inputs as rules execute in order, so
`strength_lapsed` (registered last) can check this list.

| Constant | Value | Meaning |
|----------|-------|---------|
| `STRENGTH_LAPSED_DAYS` | 21 | Days without strength session to fire |

- `code`: `strength_lapsed`
- `severity`: 1 (note)
- `evidence metrics`: `days_since_strength`
- `target`: `null` (general finding)

---

## Muscle Balance Rules (issue #1381)

File: `backend/services/gap_analysis/rules/muscle_balance.py`

These rules translate per-muscle-group ACWR classifications (computed by `muscle_load_acwr.py`,
issue #1380) into actionable findings. All thresholds are **imported** from `muscle_load_acwr`
— never redefined here.

**Dedup with pack C**: the registry injects a `claimed_groups` set. When `recurrent_niggle_area`
(pack C, issue #1373) fires for a group, that group is added to `claimed_groups`. Both rules here
skip any group already claimed, enforcing "one finding per group per week max".

**Insufficient history**: both rules require `muscle_load_ledger` in inputs. If the user has
fewer than 4 weeks of muscle-load data, `_gather_muscle_load_ledger` returns `None` and the
engine omits the key → both rules appear in `skipped_rules` instead of firing.

### muscle_overused

Fires for every group classified as `overused` or `elevated` that is not already claimed.

| Condition | Severity |
|-----------|----------|
| `overused` + `trending_up` | 3 (priority) |
| `overused` (not trending) | 2 (recommend) |
| `elevated` | 2 (recommend) |

**Injured interaction**: an injured group with `overused` or `elevated` classification still fires
— the recommendation becomes rest-flavored ("rest it completely") rather than reduce-load-flavored.

| Constant | Source | Value | Meaning |
|----------|--------|-------|---------|
| `OVERUSED_BOUND` | `muscle_load_acwr` | 1.5 | ACWR above which group is overused |
| `ELEVATED_BOUND` | `muscle_load_acwr` | 1.3 | ACWR above which group is elevated |

- `code`: `muscle_overused.{group}` (e.g. `muscle_overused.calf`)
- `severity`: 3 or 2 (see table)
- `evidence metrics`: `acwr`, `acute_7d`, `chronic_28d`, `main_source`, `source_share_{main_source}`
- `target`: the muscle group string (e.g. `"calf"`)

### muscle_untrained

Fires for untrained priority groups and detraining groups not already claimed.

| Condition | Severity | Code prefix |
|-----------|----------|-------------|
| Priority group (`calf`/`hamstring`/`glute`/`hip`) classified `untrained` ≥ 4 consecutive weeks | 2 (recommend) | `muscle_untrained.{group}` |
| Any group classified `detraining` | 1 (note) | `muscle_detraining.{group}` |

**Injured suppression**: if a group is `injured`, `muscle_untrained` is suppressed for it even if
classified `untrained` or `detraining` — consistent with the principle that gap analyzer never
prescribes loading an actively injured area.

| Constant | Source | Value | Meaning |
|----------|--------|-------|---------|
| `UNTRAINED_MIN_WEEKS` | `muscle_balance` | 4 | Consecutive weeks near-zero load before untrained fires |
| `PRIORITY_GROUPS` | `muscle_load_acwr` | `{calf, hamstring, glute, hip}` | Groups for which `untrained` becomes severity 2 |

- `code`: `muscle_untrained.{group}` or `muscle_detraining.{group}`
- `severity`: 2 or 1 (see table)
- `evidence metrics` (untrained): `weeks_untrained`, `classification`
- `evidence metrics` (detraining): `classification`, `chronic_28d`, `acwr`
- `target`: the muscle group string

---

## Add-to-plan Templates (issue #1376)

File: `backend/services/gap_analysis/templates.py`

Templates still define what a finding *means* as a session (type, name, notes,
load_adding) and power `POST /api/training/gap-analysis/{code}/add-to-plan` for
pipeline / Suggest flows. The **What to improve** Plan-tab panel is a
**reviewer** surface only (Mute / Done) — it no longer shows "+ Add to plan" or
"Ask AI"; week materialization happens via Suggest sessions / the draft
pipeline, which tags `planned_sessions.structure` with `{"_gap_code": "<code>"}`
when using this endpoint.

**Session template registry** (`get_template(code)` in `templates.py`):

| Rule code | session_type | name | Prescription (notes) | load_adding |
|-----------|-------------|------|----------------------|-------------|
| `plyo_deficit` | plyo | Plyometric intro session | 2×[10 pogo jumps, 10 low box jumps] | yes |
| `no_recent_plyo` | plyo | Plyo re-entry session | 2×[10 pogo, 10 low box jumps] | yes |
| `gct_lengthening` | strength | Calf capacity strength block | Eccentric calf raises 3×12 each side, 3 s lowering | yes |
| `cadence_drift` | run | Cadence-focus easy run | Z1-Z2, target ≥170 spm | yes |
| `aerobic_durability_gap` | run | Aerobic long run | ≥110 min Z1-Z2, monitor decoupling / fuel | yes |
| `speed_neglected` | run | Speed interval session | 6×400 m at 5 km effort, 90 s recovery | yes |
| `base_neglected` | run | Easy aerobic run | 30–60 min easy pace (Z1-Z2), conversational effort | yes |
| `strength_lapsed` | strength | General strength session | Full-body, 3×8–10, moderate load after break | yes |
| `undertrained_area_under_ramp` | strength | Targeted strength block | 3×10–12, controlled tempo | yes |
| `muscle_untrained.{group}` | strength | Targeted strength: {group} | Eccentric 3×12–15, moderate load | yes |
| `muscle_detraining.{group}` | strength | Maintenance strength: {group} | 2×12–15, light load | yes |
| `muscle_overused.*` | — | (no template) | Reducing load rule — no add-to-plan action | — |
| `intensity_too_hard` | — | (no template) | Reducing rule — no add-to-plan action | — |
| `recurrent_niggle_area` | — | (no template) | Recovery rule — no add-to-plan action | — |

**Verdict guard**: when `training_verdict == "back_off"`, add-to-plan for any
`load_adding=True` template is rejected by the server (HTTP 409 with
`code: "back_off"`).

**Duplicate guard**: a second add-to-plan for the same `code` within the same
calendar week returns HTTP 409 (`code: "already_planned_this_week"`, with
`planned_date` / `session_id`) when the existing session already meets the
preset floors. If the existing row is a hollow stub (old templates with
`structure: null`, or below duration/TSS floors), the endpoint **upgrades it
in place** on the requested date (HTTP 200, `upgraded: true`) instead of 409.

**Endpoint**: `POST /api/training/gap-analysis/{code}/add-to-plan`
- Body: `{"date": "YYYY-MM-DD"}`
- Response: 201 with the created `planned_session` dict (or 200 when upgrading)
