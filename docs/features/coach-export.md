# Coach export — the paste-to-Claude loop

One button in the global nav copies a complete, paste-ready blob (prompt template
+ 90-day JSON) to the clipboard, so a fresh Claude session can produce the daily
coach message. There is no LLM call anywhere in this feature: it is pure assembly
over services that already exist, so it cannot fail at 3am and it costs nothing.

The loop is deliberately **one-way**. Nothing parses a reply back into the app;
insights are applied by hand.

## Where things live

| Piece | File |
|---|---|
| Payload assembly | `backend/services/coach_export.py` — `build_export(user_id, window_days=90)` |
| Prompt template + blob | same module — `PROMPT_TEMPLATE`, `build_paste_blob(export)` |
| Endpoints | `backend/routers/coach.py` |
| Nav button + clipboard + toast | `frontend/js/nav.js` (`_copyForClaude`) |
| Athlete identity fields | Settings → Profile (`frontend/pages/settings.html`), stored on `users` |
| Weight-trend rate + CI | `backend/services/weight_trend_rate.py` (new; see `docs/calculations/weight-trend-rate.md`) |

## Endpoints

| Route | Returns |
|---|---|
| `GET /api/coach/export?window=90` | the JSON payload alone — inspection, Hermes, tests |
| `GET /api/coach/export/paste?window=90` | `text/plain`, the complete blob (template + JSON) |

Both are identity-scoped via `resolve_user`; anonymous requests get 401. `window`
accepts 7–365 days and returns 422 outside that range.

The paste endpoint is a **single request** on purpose. The client never assembles
the blob, so a half-fetched response can never be pasted as if it were whole. It
also stamps `users.last_coach_export_at`, which the next export reports as
`meta.previous_export_date` so the coach message can skip a season re-check when
nothing moved. The stamp happens only after the blob is built — a failed export
must not consume that signal — and a stamping failure never costs the athlete the
copy.

## The rule that makes it safe

Export **conclusions with evidence**, not raw material to re-derive.

- `fitness`, `performance`, `body` and `goal` are **canonical** — computed by
  perf-coach.
- `training.sessions` are **context** — they explain *why* a canonical number
  moved, and are never a source for *what* it is.

Rule 1 of the prompt template states this to the reader. Without it a fresh model
computes its own CTL and its own weight trend and contradicts the app — the same
divergence class as CTL/ATL and Speed-declining-vs-↑+5.

The corollary for anyone extending the exporter: **never emit a number the app
didn't compute.** If a field would have to be derived inline here, it belongs in
a service first. `weight_trend_rate.py` exists because of exactly that rule —
`body.rate_kg_per_week ± ci` and `body.readable` had no owner before it.
Formatting is not deriving: pace from stored distance and duration, age from a
stored birth date, and `M:SS` from stored seconds are all fine.

## Payload shape

```jsonc
{
  "meta":        { schema_version, prompt_version, generated_at, timezone, window_days,
                   previous_export_date, data_freshness, note, acwr_null_note, degraded },
  "athlete":     { age, height_cm, mass_kg, mass_source, weekly_hours_recent, context },
  "goal":        { race{…, weeks_out, goal_time, current_estimate, estimate_band_min},
                   body{target_kg, target_date, needed_rate_kg_per_week, intent},
                   checkpoints[] },
  "constraints": { acwr_ceiling_weekly_tss, acwr_high_bound, current_verdict, verdict_reason,
                   max_weekly_ramp_pct, ea_floor_kcal_rest_day, max_deficit_kcal_per_day,
                   protein_g_per_day, taper_window_days, preferred_rest_days,
                   max_consecutive_training_days, note },
  "fitness":     { as_of, ctl, atl, tsb, acwr, chronic_weekly_tss,
                   ctl_target_for_goal, ctl_gap, weekly_series[13] },
  "performance": { state, endurance{score, delta_28d, direction, decomposition, anchors[3]},
                   speed{…same} },
  "body":        { trend_kg, last_weigh_in, rate_kg_per_week, ci_kg_per_week, state,
                   readable, readable_note, coverage_pct_45d, needed_rate_kg_per_week,
                   weigh_ins[] },
  "training":    { weekly_rollups[13], skipped_planned[], sessions[] },
  "races":       { past[], upcoming[] },
  "habits":      { week_start, items[], adherence_4w_pct },
  "plan":        { today, week[7], week_planned_tss, week_logged_tss_so_far },
  "findings":    [ {code, severity, evidence, load_adding} ]
}
```

Session rows are flat, one line each:

```json
{"date":"2026-07-25","dow":"Sat","type":"run","name":"Moderate long run","duration_min":118,
 "distance_km":15.1,"avg_pace_per_km":"7:49","avg_hr":146,"tss":97,"zone2_min":118}
```

Strength/plyo rows carry `exercises` (a count) instead of distance and pace.
There is **no `structure` blob** — it triples the payload and adds nothing a
coach message can use. `_render_json` compacts leaf objects onto one line while
keeping the block structure indented, which is why the renderer isn't a plain
`json.dumps(indent=2)`.

Size at 90 days is roughly 30k chars / 7.5k tokens. Revisit only past ~15k
tokens; the test suite fails the build past 60k chars.

## Field sources

Everything is read from the service that owns it. Nothing is recomputed.

| Block | Source |
|---|---|
| `fitness.*`, `weekly_series` | `training_load.current_load` + `get_snapshot_series` — the same rows the readiness card reads |
| `fitness.ctl_target_for_goal` | `coach_plan._TARGET_CTL` (shared with the lever ranking) |
| `constraints.acwr_ceiling_weekly_tss` | chronic weekly TSS × `load_plan.ACWR_CEILING_MULT`, matching `plan_suggestions` |
| `constraints.current_verdict` | `training_verdict.compute_verdict` |
| `constraints.ea_floor_*`, `max_deficit`, `protein_g` | `fuel.py` (`compute_budget` with zero burn = the rest-day floor, `DEFICIT_KCAL_MAX`, `compute_targets`) |
| `constraints.taper_window_days`, ramp % | the `training_plans` row, falling back to `load_plan.TAPER_CURVE` |
| `constraints.preferred_rest_days` | `plan_prefs_accessor.get_plan_prefs` |
| `goal.race`, `checkpoints` | `goal_resolution.resolve_active_goal` + the `races` / `race_checkpoints` rows |
| `goal.race.current_estimate` | `_race_readiness_impl`'s projection series (the Performance-tab engine), falling back to `race_finish_estimator.blended_scores_estimate` when the goal has no Race row |
| `performance.*` | `get_athlete_performance` — the canonical cached compute behind the Performance tab and `/api/performance/score-breakdown` |
| `body.*` | `weight_trend_rate.compute_trend_rate` + `weight_plan.compute_required_pace_kg_per_week` |
| `training.sessions`, rollups | `workouts` (reconciled) + `training_load.get_weekly_volume` |
| `training.skipped_planned` | `planned_sessions.status` — the `missed*` states `plan_matching` already assigned |
| `plan.*` | `PlannedSession` + `training_load.estimate_planned_session_metrics` |
| `habits.*` | `habit_adherence.build_adherence_payload` |
| `findings` | `get_gap_analysis`, **visible only** — muted/suppressed items are excluded |

### Derived, not stated

- `athlete.mass_kg` is the **weight trend**, not the last weigh-in.
- `athlete.weekly_hours_recent` comes from the last 8 weeks of logged sessions.
  "I train 5–7 h/week" is aspiration; the number in the data is fact.
- `athlete.context` is the only free-text identity field, edited in Settings →
  Profile and capped at 200 characters. Keep it **separate** from plan-prefs
  `notes`, which are scheduling instructions.
- `constraints.max_consecutive_training_days` is the longest cyclic run of
  non-rest weekdays implied by `preferred_rest_days`. `null` when no rest days
  are set — there is then no stored preference to read a bound from.

### Two honesty rules worth knowing

**ACWR cold start.** `weekly_series[].acwr_end` is `null` until a full 28-day
chronic window exists. A partial window yields ratios like 4.0 that read as a
spike that never happened. `meta.acwr_null_note` explains this in the payload.

**Spans must agree.** Weekly rollups and `plan.week_logged_tss_so_far` are
clamped to today, matching the `sessions` window. Without the clamp a
future-dated workout (pre-logged session, timezone edge) lands in the rollup but
not in the session list, and the export contradicts itself.

## Degradation

Every block is assembled behind `_safe`: a block whose source raises returns its
null shape and the failure is recorded in `meta.degraded`. A partial export is
still worth pasting; a 500 is not. What never happens is guessing a value to fill
a hole — the template's rule 2 ("null means unknown") is what covers the gap.

## Versioning

`SCHEMA_VERSION` (payload) and `PROMPT_VERSION` (template) move together and both
appear in the blob. Bump both when the payload shape changes. A template that
references a field the payload no longer carries is a bug —
`tests/test_coach_export__blob.py` asserts both directions of that parity.

The template contains **no facts**, only behaviour: the five rules, the four
sections, the style, and a pointer to read identity from `athlete` / `goal`. A
test fails the build if any two-digit or decimal number appears in it.

## Tests

| File | Covers |
|---|---|
| `test_coach_export__blob.py` | template-before-data, fence round trip, version pairing, template ↔ payload parity, one-line session rows |
| `test_coach_export__self_consistency.py` | rollup/session sums, decomposition invariant, canonical parity, ACWR cold start, constraints, anchors titled by `run_id` |
| `test_coach_export__body_honesty.py` | CI-includes-zero → `flat`, low coverage → `readable: false` |
| `test_coach_export__empty_states.py` | brand-new user, no race / weigh-ins / findings / plan; `meta.degraded` |
| `test_coach_export__endpoints.py` | both routes, window validation, 401 scoping, export-timestamp stamping |
| `test_coach_export__athlete_identity_fields.py` | the three `users` columns and their validation |

## Later (deliberately not now)

- **Hermes reuse.** Once the template proves itself, Hermes can call
  `GET /api/coach/export/paste` and deliver the message daily via Discord. Same
  template, same payload — that is why both live server-side and versioned.
- A trimmed daily payload (reusing `daily_brief.build_brief`) if the 90-day blob
  turns out to be overkill for a morning read.
- Parsing anything back into the app — excluded by design.
