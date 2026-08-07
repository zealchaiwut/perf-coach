# Changelog

## Sprint 129.1 — code-review follow-up fixes (readiness baseline, plan-duration plumbing, projection/schema cleanups)

- #1390: readiness `rhr_baseline` now uses a 30-**day** RHR window instead of 7 days, matching how readiness scores RHR — `get_home_readiness` and `_build_readiness_block` compute `rhr_30d_avg` and pass it as `rhr_baseline`, and `rolling_baseline` gains an `rhr_30d_avg` field alongside the existing `rhr_7d_avg`
- #1479: populate `planned_duration_seconds` on run payloads — new `_planned_duration_map` helper in `main.py` maps each run workout to its matched `PlannedSession`'s parsed block duration (via `plan_matching._planned_duration_seconds`), wired into the signal-scores, as-of, athlete-performance, weekly-summary, and projection run payloads. This activates the previously-inert endurance plan-short guard in `running_performance.py`; a workout with no matched session (or no parseable block duration) is absent from the map, so the guard's absolute-only fallback is unchanged
- #1465: give the injured branch of `undertrained_area_under_ramp` a structured `deferred_recovery: true` evidence entry so consumers can distinguish "defer, you are injured" from "load this area" without parsing the recommendation text (the code and severity stay the same; only the evidence gains the flag)
- #1277: drop the legacy `half_equivalent` / `half_equivalent_seconds` keys from the projection payload and the `compute_half_equivalent` module alias in `projection.py` — only the `half_race_equivalent*` names remain after the #1176 rename
- #1515: `/api/brief/today` reads `schema_version` from `daily_brief.SCHEMA_VERSION` instead of hardcoding `3`, so the endpoint tracks the constant automatically
- #1518: update the stale "SCHEMA_VERSION 2" docstrings in `daily_brief.py` (module and `build_brief`) to "SCHEMA_VERSION 3" to match the shipped schema
- #1459: `/api/plan/today` (worker) empty-state response now includes the AC-specified `session_type: null` field when no session is planned
- #1319: call `_emit_startup_info()` at `llm.py` import time (and fix the negated `not ... in` env check) so the LLM-coaching startup log actually fires
- #1560: deduplicate the Half-Equivalent column block in `training-performance.js` into a shared `_halfEquivCol(r)` helper used by both the planned and completed race cards
- #1415: refresh the weekly fuel card after a sync-deficit — `fuel.js` now also calls `_fuelLoadWeek()` (in addition to `_fuelLoadToday()`) so the weekly projection reflects the new deficit

## Sprint 128 — code-review follow-up cleanup (dead-code & unused-parameter removal)

- #1519: remove the unused `atl` parameter from `_load_interpretation` in `daily_brief.py` — the interpretation label is derived only from `tsb` (and `ctl`), so the signature is now `_load_interpretation(ctl, tsb)` and `_assemble_form` no longer passes `atl`
- #1565: drop the private-prefixed `_REGISTRY` and `_RUN_FILTER` names from `gap_analysis/engine.py`'s `__all__` — a leading-underscore name marked private should not be re-exported, so `__all__` is now just `["GapAnalysisFinding", "run_gap_analysis"]`
- #1590: remove the redundant timeout resolution in `worker_client.delegate_sync` / `delegate_backfill` — the `_post` helper already resolves the default, so both now pass `timeout=timeout` directly instead of the `timeout if timeout is not None else get_worker_timeout()` ternary (the env-configurable default from #1306 is unchanged)
- #1531: remove the unused `todayStr` parameter from `_buildHabitRow` in `frontend/js/habits.js` and its call site in `renderDailyGrid`
- #1511: remove the dead `worker_url` plumbing from `scripts/export_brief.py` — the CLI no longer computes or threads a worker URL (the daily brief is assembled in-process); `_build_brief` is called with just `for_date`/`user_id`, and `--worker-url` remains an accepted no-op kept for backward compatibility
- #1309: trim the multi-paragraph docstring on `activity_streams_to_strava_dict` to a single summary line
- #1301: document the private SQLAlchemy attributes referenced in `tests/test_memory_config_hardening__1292.py` (test-only clarifying comment)
- #1552: remove the unused `import pytest` from `tests/test_curve_data_non_emptiness_check__993.py` (guarded by regression test `test_remove_unused_import_pytest__1552.py`)
- #1564: replace the hardcoded `/Users/zeal-server` absolute path in `tests/test_1466_consistent_run_matching.py`'s subprocess `cwd=` arguments with a dynamic `pathlib.Path(__file__).resolve().parents[1]`, so its five `subprocess.run` calls are portable across clone directories (guarded by regression test `test_1564_fix_hardcoded_cwd_in_test_1466.py`)

## Sprint 127 — code-review follow-up hardening (strava detail promotion, per-set strength TSS prefs, migration reversibility, observability)

- #1307: promote the four most-accessed Strava detail scalars to columns on `strava_activities` — `sync_strava_activities` now writes `laps`, `splits_metric`, `best_efforts`, and `calories` alongside `detail_payload` at sync time, and `_strava_source_dict` reads them from the promoted columns (falling back to `detail_payload` only for rows synced before the columns existed, detected via `laps IS NULL`). Avoids loading the large deferred `detail_payload` blob for these fields on new rows. Migration `ad22fdb94551`
- #769: add `scale_constant` and `max_tss` columns to `user_preferences` and a thin caller `get_strength_tss_per_set_for_workout` in `tss.py` — reads the two per-set strength-TSS preferences from the user's row and delegates to `calculate_strength_tss_per_set_with_prefs`. Neither value is given a hardcoded default; a null preference yields a null TSS result with a reason string. Migration `1a199ee7593e`
- #545: unify the `source` field in `_workout_list_dict` — the workout-list serializer now returns `source or tss_source or "manual"` instead of a bare `source`, matching the training-log list endpoint so a null `source` no longer leaks to clients
- #939: bound the `HabitLog` query in `GET /api/habits/adherence` to the last 60 days (`log_date >= today − 60d`), so adherence no longer scans a habit's entire log history
- #1305: log (not silence) DB errors in the `get_sync_status` `worker_job_runs` fallback — the bare `except: pass` now emits a `warning` with the exception instead of swallowing it
- #992: restore INFO log level for performance-observability logging in `get_athlete_performance` — the `performance score request` log entry is emitted at `INFO` (guarded by `isEnabledFor(INFO)`) instead of `DEBUG`, so it is visible under the default log level again
- #1386: implement `downgrade()` in the `verdict_history` migration (`bf3b956dd2e0`) — was a no-op; now idempotently drops the `ix_verdict_history_user_date` index and `verdict_history` table, making the migration reversible
- #1393: remove dead/duplicate code from `training_verdict.py` — deleted the redefined `READINESS_LOW_TODAY` / `READINESS_LOW_TREND` constants, the unused `_VERDICT_ORDER` map, and the unreferenced `_downgrade_one` helper
- #1563: add the missing assertion to `test_debug_log_emitted_on_value_error` (AC3 was previously unverified — the test asserted nothing)
- #1300: add a positive assertion to `test_worker_app_not_gated` to complement the negative string check for the worker refit scheduler
- #835: fix a hardcoded absolute path in `test_no_consistency_module_duplicates_met_rule` (made portable via a `conftest.py` glob translation) so the assertion is no longer a no-op in CI
- #1414: include `auto_periodize` in the fuel `get_today_payload` — the payload returned by `GET /api/fuel/today` (and the recomputed `PUT /api/fuel/settings` response) now carries the `auto_periodize` flag, so the HTTP test asserting it is no longer checking an absent field
- #1411: skip the week-phase resolver DB lookup when `auto_periodize` is off — `get_today_payload` / `get_week_payload` only call `_resolve_week_phase_from_db` when `auto_periodize` is on; when off, the phase is set directly to `("base", "Base week — full deficit")` without querying the DB
- #1550: exclude the stray skip-only `test_weekly_coach_double_fire__1543.py` (merged under #618 before #1543's implementation landed) from collection via a `conftest.py` `pytest_ignore_collect` guard, so `--collect-only` no longer raises on machines without UAT env vars set

## Sprint 126 — code-review follow-up fixes (form-metrics window, habit form, gap phrasing, chart/calendar state)

- #1443: form-metrics rolling mean is now a 28-**calendar-day** window, not a 28-**run** window — `_rolling_mean` in `main.py` computes each row's trailing simple mean over the inclusive `[date − 27d, date]` calendar window (accepting either a `datetime.date` or an ISO string) instead of the previous fixed 28-row window. The `GET /api/training/form-metrics` `rolling_means` now reflect calendar-day windows; the endpoint docstring/response notes were updated accordingly
- #1471: render LLM coach phrasing in the improvement (gap) panel — the gap-finding evidence line in `training-performance.js` now shows `f.phrasing` when `f.phrasing_source !== "template"`, falling back to `f.evidence_text` when the phrasing is template-sourced or absent
- #1282: remove the hidden `plan-modal-type` `<select>` from `training-log.html` (added by backend ticket #1028) — replaced the `hidden`/`aria-hidden` select with an off-screen but accessible select (`aria-label="Entry type"`), and split the single "+ Add" button into "+ Add Race" / "+ Add Checkpoint" buttons wired to `openModal(null, "race")` / `openModal(null, "checkpoint")`
- #868: binary+weekly habit no longer silently hardcodes `weekly_target=7` with no UI feedback — the habit form now disables the "weekly" schedule option for `binary` habits (`_sfUpdateVisibility` resets a stray weekly selection back to daily), and `_sfFormToApiPayload` defensively maps any binary habit to `daily_checkmark`
- #853: `_hcalInitialized` reset on user switch — the habits page `userChanged` handler now resets `_hcalInitialized = false` and `hcalFetchedRange = null` before reloading, so switching users no longer shows the previous user's stale habit-calendar data
- #1255: `_activeTapDate` cleared on every tooltip hide — `WeightChart._hideTooltip` now nulls `_activeTapDate` so any hide path (not just the tap-toggle path) resets tap state

## Sprint 125 — daily-brief consolidation & code-review follow-up hardening

- #1508: `docs/features/api.md` documented `GET /api/planned-sessions` with the old flat-array shape; corrected to the week-bundle object `{from, to, days:[...]}` where each day carries `planned`/`unplanned` arrays, plus the `actual` matched-workout summary, `estimated_tss`/`estimated_distance_km`, and `plan_warnings`/`candidates` fields
- #1509: `_build_brief` no longer duplicated in `scripts/export_brief.py` — the full assembly (including `_assemble_coach`) lives in `backend/services/daily_brief.py`; the CLI is now a thin wrapper delegating to the service (four-arg signature and helper re-imports preserved for existing test patches)
- #1510: consistent non-UUID `user_id` handling in daily-brief assembly — `_build_highlights_md` now guards the `uuid.UUID(...)` conversion and returns `""` for non-UUID ids instead of raising, matching the empty-plan behaviour elsewhere
- #1517: batch week-plan lookups into one query — new `_get_plans_for_date_range` fetches all `PlannedSession` rows for `[today, Sunday]` in a single date-range query and passes a `plan_cache` to `_assemble_week_plan`, replacing the per-day `_get_plan_for_date` calls
- #1523: coach_plan timeline phases no longer invert (`start_date > end_date`) for near-term / available-load inputs — the hold phase anchors to the previous day when load is already available (`unlock_date <= today`), and any inverted/zero-length phase is dropped before sorting
- #1529: promote `weekly_coach_message` private helpers to public API — `load_inputs_for_user`, `build_projection_info`, and `format_hms` are now public (back-compat `_`-prefixed aliases kept); `coach_facts` imports the public names instead of reaching into privates
- #1530: deduplicate the `_TARGET_CTL` constant — `weekly_coach_message` now imports it from `coach_plan` rather than redefining the same per-distance target-CTL map
- #1555: degraded advisories no longer embed raw exception text — the gap-analysis and training-verdict error advisories show fixed user-friendly text ("… temporarily unavailable.") instead of interpolating the exception
- #1516: converge `week_plan` on a single shape `{"days": [...]}` across API, service, and docs — `GET /api/brief/today` normalizes the service's list to the canonical dict, dropping the old `_build_week_plan` seven-day builder in `main.py`

## Sprint 124 — endurance recalibration, habit-streak semantics, API/frontend consolidation

- #1331: Recalibrate endurance training-run path — runs were under-reading vs race-demonstrated fitness. In `running_performance.py` the HR-extrapolation exponent goes `1.5 → 2.5` (k=1.5 mapped easy runs at ~140/155 bpm to ~408 s/km equivalent vs the 360 threshold, ~48 s/km pessimistic; k=2.5 lands typical aerobic sessions within ~5–10 pts of race fitness) and the durability factor softens from `1 − dec/50` to `1 − dec/100` (20% decoupling now costs 20% instead of 60%). Bumps the persisted performance-score `formula_version` `vdot-v12 → vdot-v13`
- #836: Align `'weekly'` schedule_type semantics in habit streaks — `compute_streak` previously routed both `times_per_week` and `weekly` through `_weekly_streak` (count-per-week logic). A new `_weekly_day_streak` handles `weekly` as a specific-weekday habit (`schedule_target` = weekday index 0–6): one period per calendar week on that weekday, today treated as pending when it falls on the target day and isn't yet logged — matching `compute_consistency`. `times_per_week` still uses `_weekly_streak`
- #1601: S2 — API unification: fold the Hermes surface into the main API. The `_extract_target` planned-session helper (distance/duration/intensity extractor), previously duplicated verbatim in `backend/worker_app.py` and `backend/services/daily_brief.py`, is consolidated to one canonical `extract_session_target` in `daily_brief.py`; `worker_app.py` now imports it (back-compat alias `_extract_target` kept in both). Response shapes unchanged
- #1603: S4 — Frontend consolidation: one shared lib for escaping, dates, and formatting. `formatDurationCompact` (`"3h 3m"`, `"45m"`) moves into `frontend/js/lib/training-format.js`; both `training-log.js` call sites now delegate to it (month headers gain the space, `"3h3m" → "3h 3m"`). Zone-2 HR-band defaults move to `window.Zone2` (`zone2-constants.js`), consumed by `run-detail-view.js` with a 130/155 fallback; the dead `RUN_DETAIL_ZONE2_HR_MIN/MAX` constants are removed. Adds `ui-states.js` loading-state to the habits day grid and to run-view/sessions/strength-view pages

## Sprint 123.1 — code-review follow-up hardening (perf, plan-draft ops, reconcile, dead code, docs)

- #1578: `/api/athletes/{id}/performance` cold-cache path bounded — the cache-miss branch of `get_athlete_performance` no longer loads the athlete's entire run history plus a per-workout splits query. Runs are now capped to a trailing window (`_RUN_HISTORY_CAP_DAYS = 400`, covering the 90-day scoring window plus buffer) and all splits for the qualifying runs load in a single `IN (...)` query instead of N sequential per-workout queries. Peak in-request memory on a 512 MB dyno stays ≤ ~1 MB for the runs list, resolving the OOM observed in the 2026-07-22 incident
- #1579: SCHEMA.md backfilled with 6 tables missing since the 2026-07-22 release — `daily_briefs`, `plan_drafts`, `training_preferences`, `preference_proposals`, `user_custom_presets`, `preference_import_audits` — and the `weekly_coach_messages` `for_date` column / `(user_id, for_date)` uniqueness change (migration `d35f3915950e`). Documents that `d35f3915950e` is effectively one-way (downgrade fails once multiple per-day rows exist for one ISO week) and that its dedup DELETE is unaudited
- #1580: Smoke suite now catches schema drift — new unauthenticated `GET /api/health/schema` returns `{repo_head, db_head}` comparing the repo's expected Alembic head against the live DB's stamped version, so the smoke suite can probe for migration drift and multiple-head conditions
- #1582: Daily coach dedupe key mismatch fixed — a post-sync job and a scheduled batch job waking on the same calendar day no longer both fire LLM generation for the same user. `_run_daily_coach_batch` now short-circuits per user via `_daily_coach_message_exists(db, user_id, today)` (checks `WeeklyCoachMessage` on `(user_id, for_date)`) and records `skip_already_generated`
- #1583: Plan-draft refresh/regen endpoints gated on `pipeline_enabled()` — `POST /api/plan/draft/refresh` and the slot-regen route now return `400` (`plan pipeline not enabled; set PLAN_PIPELINE=skeleton_v2`) when the pipeline is disabled instead of enqueueing no-op jobs, and `enqueue_plan_draft` returns `None` immediately when the pipeline is off
- #1584: Reconcile no longer leaves a stale `workout.np` — when stream ingest finds power samples but NP compute returns `None` (samples present but insufficient), `_ingest_streams` now clears `workout.np` instead of preserving the previous value
- #1585: Plan-draft slot-op hardening — `move`/`swap`/`add` in `plan_skeleton_ops` reject out-of-range day offsets (block with `day out of range 0-6`); `remove`'s TSS redistribution re-applies the per-slot floor so the ceiling clamp can't push a slot below it; `update_draft_slot` accepts an optional `draft_version` and returns `409 stale_draft` on mismatch; and `replan_remaining_budget` scopes matched-workout TSS to the requesting user (`w.user_id == user_id`)
- #1587: Training-plan/log button-state bugs fixed — apply-draft button re-enables after a successful apply, the week loader's error path calls `onDone()` so the view no longer sticks on "Loading…", and the training-log "Load older workouts" trigger guards against a double-fire
- #1588: Dead code cleanup — removed unused `llm.llm_transport()`, `main._trigger_curve_rebuild_background()`, and an unused `start_date` local / stale `selectinload` and `date` imports

## Pre-release hardening — PRD merge-review blocker fixes (2026-07-22)

- Session-poisoning fixes: `plan_prefs_accessor.get_plan_prefs`, `plan_suggestions.assemble_facts` (prefs fetch), and `coach_narrative.generate_brief` (daily-brief persist) all swallowed exceptions from code paths that write to the DB without rolling back the caller's session. A prefs carry-forward race or a `(user_id, brief_date)` unique-constraint race left the shared Postgres session in an aborted-transaction state, turning every subsequent query in that request/job into `InFailedSqlTransaction` — including a 500 on a plain `GET /api/coach/brief`. Each site now rolls back on failure
- LLM atom hardening in `coach_narrative`: atom fields are coerced with `str()` before validation (GLM's `json_object` mode does not enforce types — an int/list field previously crashed `.strip()`), and each plain-path generation attempt is wrapped in try/except so a malformed payload counts as a failed attempt and falls through to the deterministic `_fallback()` instead of crashing `generate_brief` and 500ing the brief endpoint
- Removed dead `frontend/js/preferences.js` (322 lines): never loaded by any page and none of its DOM ids exist — the live preferences UI is inline in `training-plan.js`; the old `/preferences` page is a redirect stub

## Sprint 122 — code-review follow-up hardening (goal envelope, snapshot/recompute guards, weight-plan validation, habit calendar range)

- #1524: `GET` and `PUT /api/coach/goal` now return the same envelope — `PUT` previously returned the bare goal dict while `GET` wraps it as `{"goal": {...}}`. `put_active_goal` in `backend/routers/coach.py` now returns `{"goal": _goal_dict(goal)}`, so a client can read the created goal from `.goal` after a write exactly as it does after a read. Validation/behaviour otherwise unchanged (README API tables updated)
- #1432: `recompute_user_snapshots` guarded in `accept_calibration` — the CTL/ATL preference write already commits before the snapshot recompute, so a recompute error no longer 500s the endpoint. The recompute is now wrapped in `try/except Exception` (returning `snapshots_recomputed: 0` on failure); stale snapshots self-heal on next read via the existing `ctl_days`/`atl_days` mismatch guard
- #1434: Dropped the hardcoded `formula_version="1"` at the `_build_snap` call site in `backend/routers/projection.py`, so the prediction snapshot uses `prediction_snapshot.FORMULA_VERSION` as its single source of truth instead of a literal that could silently drift from the module constant
- #1420: Prediction-snapshot write failures are now logged — the `try/except` around `_write_snap` in `backend/routers/projection.py` no longer swallows errors with a bare `pass`; it logs at WARNING with `exc_info=True`. Snapshot failures still never break the projection response
- #1308: `WorkerUnavailable` 503 detail body no longer leaks env-var names — `backend/services/worker_client.py::_post` raises a generic `"Worker configuration error"` when `WORKER_BASE_URL`/`WORKER_SHARED_SECRET` are unset, logging the specific missing variable server-side at WARNING instead of returning it in the client-facing detail
- #896: `compute_plan_line` guards against `plan.goal_date=None` — `backend/services/weight_plan.py::compute_plan_line` now returns `[]` immediately when the plan has no `goal_date`, rather than passing `None` into date interpolation
- #894: `validate_weight_plan_required` now also guards `start_date` — the validator (`backend/models.py`) takes an optional `start_date` argument and returns `(None, "start_date is required")` when it is missing, matching the existing start/goal-weight checks
- #850: Habit calendar fetch range covers the displayed week strip — `_refreshHabitCal` in `frontend/js/habits.js` expands the fetch range to the union of the visible month and the week strip when the week crosses a month boundary, so week-strip navigation no longer fetches only the month range and misses days in the adjacent month

## Sprint 121 — code-review follow-up hardening (verdict guards, goal projection, weekly-habit calendar, worker timeout)

- #1473: `back_off` verdict guard now fails closed on a verdict-computation error — `gap_add_to_plan` previously blocked load-adding sessions only when the verdict was explicitly `back_off`, so a `None` verdict (load data unavailable / computation failed) fell through and *allowed* the session. It now returns `409 {"code": "verdict_unavailable"}` when the verdict cannot be computed, disabling load-adding sessions until load data is available
- #1399: `verdict_history` index direction drift fixed — `VerdictHistory.__table_args__` now declares `ix_verdict_history_user_date` on `(user_id, verdict_date DESC)` to match the descending index the migration actually creates (`bf3b956dd2e0`), so the model is the accurate source of truth and future autogenerate runs don't spuriously re-create the index
- #901: already-at-goal mapped to a distinct reason — `build_arrival_projection_response` now returns `reason: "already_at_goal"` (with `recent_rate` carried through) when `project_arrival` reports "already at or past goal", instead of collapsing it into the generic `insufficient_data` bucket. Other non-projectable reasons still surface as `insufficient_data`
- #849: history-calendar day status excludes weekly habits — `computeDayStatus`, `computeAllHabitsDaySummary`, and `computeSingleHabitDayStatus` in `frontend/js/habits.js` now consider only `daily_checkmark` habits for daily met/not-met logic. Weekly habits (`weekly_count` / `weekly_minutes`), which aren't expected to be logged every day, return `no-data` for a missing log rather than polluting the daily calendar with false `not-met` marks
- #1306: worker HTTP timeout is env-configurable — `backend/services/worker_client.py` reads `WORKER_TIMEOUT_SECONDS` (default `10`, non-integer falls back to `10`) via new `get_worker_timeout()`, applied to `_post`, `delegate_sync`, and `delegate_backfill`. Lets slow home-server links raise the timeout to avoid spurious 503s on long backfill / sync-delegation calls

## Sprint 120 — PR-endpoint curve fix, cadence-drift easy-run isolation, gap-analysis run-matching, phase-chip gating & half-marathon equivalent

- #993: Run-PR endpoint now checks `curve_data` non-emptiness, not just row existence — `get_athlete_run_personal_records` computed `curve_populated` as `session.get(_AthleteDurationCurve, uid) is not None`, so an athlete whose earlier rebuild found no power data (leaving a row with `curve_data={}`) skipped the rebuild and logged `duration_curve_populated=True` despite having no usable curve. It now gates on `bool(curve_row and curve_row.curve_data)` both before and after `_rebuild_athlete_duration_curve`, so a row with empty `curve_data` is retried when the athlete has run history and the pre-detection log reflects the true populated state. Thresholds still come from `_DEFAULT_DURATION_LADDER` via `fetch_and_compute_curves` — no values hardcoded
- #1173: Half-marathon-equivalent surfaced on race/checkpoint cards — `projection_service.race_to_dict` now includes `half_marathon_equivalent_seconds` (computed via `riegel_half_equivalent(actual_time_seconds, distance_km)`, `None` when no finish time or distance), matching the field already present in `_race_dict`. `frontend/js/training-performance.js` renders a new "Half Equivalent" column (`21.1 km equiv.`) on both upcoming and completed race cards when the value is present, so results across distances can be compared apples-to-apples
- #1412: Phase chip suppressed when auto_periodize is off — `fuel.py` `get_today_payload`/`get_week_payload` now force `week_phase = "base"` / `week_phase_reason = "Base week — full deficit"` whenever `settings["auto_periodize"]` is false, and `frontend/js/fuel.js` hides `fuel-phase-chip` when `week_phase === 'base'`. Users who have not opted into auto-periodization no longer see a misleading taper/ramp phase chip
- #1463: `cadence_drift` now isolates easy runs from the cadence baseline — both the recent-28d and long-baseline windows are filtered to an easy-run intensity band (power within ±`CADENCE_EASY_POWER_BAND_WIDTH_W`/2 = ±25 W around the lower of the two windows' mean power, anchoring to the lighter-effort mix). Runs without `power_w` are excluded; the recent window must have ≥ `MIN_RUNS_PER_WINDOW` powered runs to anchor the band, and the long baseline falls back to all cadence-valid runs when it has no power data at all (e.g. Garmin-only imports). Prevents interval/hard efforts from polluting the cadence-drop comparison
- #1466: Consistent `workout_type` run-matching in gap-analysis input gathering — new module constant `_RUN_FILTER = "lower(workout_type) LIKE '%run%'"` in `gap_analysis/engine.py` (exported via `__all__`) now backs the weekly training-load query, which previously used exact `workout_type = 'run'` and silently dropped subtypes (`trail_run`, `long_run`) and mixed-case variants (`Run`). All single-table gather queries now share the same predicate
- #1413: Narrow broad `except` in ramp computation — `_resolve_week_phase_from_db` in `fuel.py` now catches only `ValueError` (with a debug-level log) instead of bare `except Exception: pass`, so real bugs in `compute_load_plan`/`get_weekly_volume` are no longer silently swallowed; only the expected data-absent error falls back to the base phase
- #1389: Readiness recompute failures no longer 500 a committed metric write — `create_daily_metric`, `patch_daily_metric`, and `upsert_daily_metric` now wrap `_readiness_compute_and_store` in `try/except Exception` with a warning log (`exc_info=True`); the metric write already succeeded and the HTTP response is unaffected

## Sprint 114 — Race-based goal fallback & weekly-coach scheduler fixes

- #1541: Race-based fallback for active-goal resolution — new shared resolver `backend/services/goal_resolution.py::resolve_active_goal(user_id, db)` returns the active `PerformanceGoal` unchanged when one exists, otherwise falls back to the nearest qualifying A-priority Race (`status ∈ {planned, active}`, non-null `goal_time_seconds`, ordered by `race_date` asc nulls-last) wrapped in a duck-typed `_RaceGoalAdapter` exposing `user_id`/`race_date`/`race_distance`/`target_time`; `race_distance` is derived by nearest-bucket mapping (5 km→`5k`, 10 km→`10k`, 21.0975 km→`half`, 42.195 km→`marathon`). This lets users who set their goal via an A-race in the Plan tab receive coach output (weekly message, Hermes daily-brief coach block) without a `PerformanceGoal` record. `weekly_coach_message.py::_load_inputs_for_user` and `scripts/export_brief.py::_load_goal_for_user` now call the shared resolver instead of querying `PerformanceGoal` directly; `backend/routers/coach.py` and the `performance_goals` table are untouched
- #1542: Unified next-race resolution in `build_coach_facts()` — the next race is now resolved exactly once via `_resolve_next_race()` (A-priority planned/active first, then any planned/active race, both ordered by `race_date` asc nulls-last) and passed into `_enrich_load_context()`, `_dream_block()`, and `_estimate_for_a_race()`; those call sites no longer run their own independent `Race` queries. Fixes the inconsistency where Now/Load facts (ceiling TSS, deload flag, distance-based CTL-target label) ignored a B/C-priority race and silently assumed a marathon while Dream and finish-time projection referenced that race — all three sections now describe one consistent plan
- #1543: Weekly-coach scheduler double-fire fix — `_scheduler_loop()` in `backend/worker_app.py` no longer re-enqueues `weekly_coach` at the second wake time on multi-wake days. New helper `job_queue.has_done(dedupe_key)` checks for an existing `done` row, and the scheduler skips enqueue when the ISO-week job already completed (`enqueue()` alone only dedupes against queued/running rows, not completed ones). A failed or still-queued/running first run is unaffected — the skip is conditional on a `done` terminal state only, so a failed 06:00 run does not block the 18:00 retry. The misleading "06:00 + 18:00 only run once" comment is corrected

## Sprint 113 — Deterministic coach plan (goal → levers → weekly message → Home card)

- #1501: `PerformanceGoal` model + goal-setup flow — new `performance_goals` table (one active race goal per user) and `backend/routers/coach.py` with `GET /api/coach/goal` (returns the active goal or `{"goal": null}`) and `PUT /api/coach/goal` (deactivates any existing active goal, then inserts the new one). Body validated via Pydantic: `race_distance` ∈ `{5k, 10k, half, marathon}`, `target_time` a positive integer (seconds), `race_date` ISO `YYYY-MM-DD` and strictly in the future. Migration `f5413962c763_add_performance_goals_table` (check constraint `ck_performance_goals_race_distance_values`, index `ix_performance_goals_user_id`)
- #1502: Deterministic coach-plan lever & phase engine — new `backend/services/coach_plan.py` (`build_plan_state()`) translating training-load and weight signals into structured coaching state: load/weight levers, periodization timeline (phase + ACWR-convergence simulation, capped at `ACWR_CONVERGENCE_WEEKS_CAP` weeks), interaction constraints (deficit capped to zero during ramp; ACWR lock at `1.30`), and lever ranking. Pure rule/math logic — zero LLM imports (enforced by a static test); consumed by the weekly-message and daily-brief surfaces
- #1503: Deterministic race-time projection — new `backend/services/coach_projection.py` mapping recent running efforts to two finish-time forecasts: `current_predicted_sec` (Riegel projection from the best recent effort, exponent `1.06`, weight-adjusted to present body mass) and `plan_predicted_sec` (extends the current prediction through the coach-plan CTL ramp to race week via the CTL→pace model and target-weight adjustment). Confidence band narrows with more qualifying efforts (`max(BAND_MIN_SEC, BAND_BASE_SEC / sqrt(n_efforts))` scaled to race distance). No LLM calls
- #1504: Weekly coach-message generation + API — new `backend/services/weekly_coach_message.py` composes a structured 5-element weekly message from `coach_plan.build_plan_state()` + projection outputs (`compose_deterministic_message()` is pure; `_build_message()` tries an LLM warmth-rephrase layer and falls back to the deterministic text silently on any failure), persisted one-per-ISO-week in the new `weekly_coach_messages` table (upsert on `(user_id, for_week)`). New read routes `GET /api/coach/weekly-message` (latest) and `GET /api/coach/weekly-messages?limit=` (history, newest-first, 1–52). CLI runner `scripts/run_weekly_coach.py` generates messages for users. Migration `5b2f59e19e14_add_weekly_coach_messages_table`
- #1506: Habits split into Training and General sections — new `habits.section` column (`training` | `general`, default `general`, check constraint `ck_habits_section_values`), surfaced through all habit serializers (`_habit_dict`, `_habit_dict_v2`, `_habit_log`/week views, Home habits block) and accepted/validated on `POST`/`PATCH /api/habits` (422 on an invalid value). Habits UI (`frontend/js/habits.js`, `frontend/js/home-strip-habits.js`, `frontend/css/habits.css`) groups habits under Training vs General headers. Migration `f2334eacc205_add_habit_section` (adds the column, backfills existing rows to `general`, then sets NOT NULL + default)
- #1505: Coach card surfaced on Home dashboard — new `frontend/js/home-coach-card.js` registers `home-coach-card` in the gridstack REGISTRY (mobile 1-col, tablet 4-col, desktop 4-col spans) and fetches `/api/coach/goal` + `/api/coach/weekly-message` in parallel; renders goal line, projection banner, lever-status pills, Now-directive sentence, and a collapsible "Full message" section with `esc()`-escaped content. Skeleton state shown while both API calls are in-flight; quiet unavailable state (no error, no spinner) when no active goal is set, pointing to the Race goal card. `scripts/export_brief.py` gains `_assemble_coach()` (+ `_load_goal_for_user`, `_build_plan_state_for_user`, `_coach_lever_strings` helpers) that returns `{directive, projection, levers}` from the coach-plan engine when an active goal exists, or None otherwise; `_build_brief()` includes the `coach` key only when the result is non-None. `SCHEMA_VERSION` bumped 2 → 3 (minor addition, all pre-existing fields unchanged). `npx impeccable detect` passes with zero new violations

## Sprint 112 — Daily-brief shared service, SCHEMA_VERSION 3 contract & Hermes API reference

- #1496: Daily-brief assembly extracted into a shared service — new `backend/services/daily_brief.py` is now the single source of truth for building the Hermes coaching brief. It assembles the payload (today/tomorrow sessions, form CTL/ATL/TSB/ramp/flags/interpretation, recent-window adherence + load trend + weekly `highlights_md`, weight status, and gap-analysis/verdict/weight advisories) with **no HTTP calls** — plan data comes from the `PlannedSession` model directly, weight status from `compute_weight_status`, load from `training_load`, findings from the gap-analysis engine. Public entrypoint `build_brief(user_id, for_date)`; `scripts/export_brief.py` is now a thin CLI wrapper that calls it instead of duplicating the aggregation logic
- #1497: Brief contract enriched to `schema_version: 3` — the `form` block gains an `acwr` field (rounded 4dp, null when unavailable), and a new top-level `week_plan` array lists the remaining days of the current Asia/Bangkok week after tomorrow (through Sunday), each entry carrying `date` / `day` / `session_type` / `intensity` / `duration_min` / `planned`. `week_plan` is empty when tomorrow falls on a weekend or past this week's Sunday
- #1500: Hermes external-agent API reference — new `docs/features/api.md` documents the perf-coach endpoints called by the Hermes coaching assistant: authentication (session cookie for main-app port 9000, `Authorization: Bearer` token for worker port 9100), query parameters, response shapes (including the `GET /api/brief/today` daily-brief payload), and integration examples. Linked from the README API section
- #1499: Daily Brief widget cards on the Home grid — a new authenticated `GET /api/brief/today` endpoint returns the `build_brief` payload (stamped `schema_version: 3`) plus a `week_plan.days` array (7 days from today, each with `date` / `day` / `planned` / `session_type` / `duration_min`), and three new GridStack cards (`home-brief-form-card`, `home-brief-week-plan-card`, `home-brief-advisories-card`) registered in `frontend/js/home-grid.js` render from a **single** `GET /api/brief/today` fetch in `home.js init()`. Form card shows CTL/ATL/TSB (JetBrains Mono) + an ACWR pill coloured by `form.flags.acwr_state` (`--green-soft`/`--amber-soft`/`--red-soft`) and the `form.interpretation` line; Week Plan card lists each day as `Day  type  duration` (rest days as `Rest`); Advisories card renders `advisories[].text` bullets (warn-severity prefixed with a glyph, `(none)` when empty). Each card shows a skeleton while in-flight and degrades to a quiet "unavailable" message on fetch failure, leaving the rest of the Home page (including the Weight card) unaffected

## Sprint 111 — Hermes brief exporter & authenticated worker feel-entry write route

- #1483: Hermes brief exporter — new `scripts/export_brief.py` aggregates today/tomorrow planned sessions (from the worker `GET /api/plan/today`), form metrics (CTL/ATL/TSB/ramp/guardrail flags/interpretation from `training_load_snapshots`), recent-window adherence + load trend + weekly `highlights_md`, and gap-analysis/verdict advisories into a versioned (`schema_version: 1`) `perfcoach_brief.latest.json` snapshot. Written atomically (tempfile + `os.replace`) behind a `perfcoach_brief.lock` file lock so readers never see a partial file and concurrent runs exit with a clear error. Flags: `--date YYYY-MM-DD` (default today Asia/Bangkok), `--dry-run` (print to stdout, no file/lock I/O), `--env uat|prd`, `--user`, `--output`, `--worker-url`; exits non-zero with a stderr message when a data source (worker/DB) is unavailable. `actions` is a reserved empty list
- #1484: Authenticated `POST /feel-entry` write route on the compute worker (`backend/worker_app.py`, port 9100) — lets Hermes log session-feel/RPE into `workout_feel` without touching the webapp's own `POST /api/feel` route or auth flow. Guarded by a static bearer token (`Authorization: Bearer <WORKER_API_TOKEN>`; 401 on missing/wrong token, 503 when the env var is unset). Same validation as the webapp route: `feel_date` required (400 if missing/invalid), `rpe_1_to_10` an integer 1–10 when present, `notes` capped at 10,000 chars, at least one of RPE/notes required. On success inserts the row, runs the same `auto_link_feel_entries` logic (links to the same-day workout when exactly one exists; still succeeds with `workout_id: null` otherwise), and returns 201 with the full record. User resolution matches the read API (`?user=` → `WORKER_READ_API_USER` env → single active user). The webapp `POST /api/feel` route is unchanged. Documented in `docs/worker.md`

## Sprint 110 — Follow-up fixes: readiness cleanup, perf-card sparkline & block-delta, endurance guards, and the base_neglected gap rule

- #1272: Migration `145b95d5baf0` downgrade fix — `downgrade()` no longer relies on a module-level `_lap_type_was_added` flag to decide whether to drop `workout_splits.lap_type`. That flag never survived a real `alembic downgrade` (each run is a fresh process, so it was always re-initialised to `False`), so downgrade now deterministically reverts `lap_type` to nullable rather than conditionally dropping the column
- #1388: Nulling all wellness inputs via PATCH no longer leaves a stale `daily_readiness` row — when the readiness recompute job (`services/readiness/job.py`) finds all scored inputs are null (`result is None`), it now deletes any existing `daily_readiness` row for that user+date so the previous score is not left behind after the metrics are cleared
- #1395: `_upsert_verdict_history` no longer swallows exceptions silently — the best-effort verdict-history write now logs a warning with traceback (`exc_info=True`) on failure instead of a bare `pass`; the write remains non-fatal to the caller
- #1396: Readiness delete runs in the same transaction as the metric delete — `DELETE /api/daily-metrics/{uid}/{date}` no longer commits the metric delete and then opens a second session to clear `daily_readiness`; both deletes now share one session/commit, so a failure between them can no longer leave a stale readiness row
- #1430: Score-card sparkline wired to persisted history — the Endurance/Speed performance score cards render a sparkline from the persisted `history_trend` / `history_trend_dates` when present, falling back to the in-request `trend` / `trend_dates` only when history is absent (`frontend/js/training-performance.js`, `frontend/pages/training-log.html`)
- #1431: Block-delta pill uses the nearest prior score row — `_fetch_perf_block_delta` now selects the most recent `performance_score_history` row with `score_date <= block_start` (ordered by `score_date` desc, then `created_at` desc) instead of requiring an exact `today − 28d` match, so the delta pill is no longer hidden when the block-start day has no score row
- #1433: Endurance "cut materially short of plan" guard implemented — `compute_endurance_score` now excludes a run from the endurance pool when `planned_duration_seconds` is present and the session completed less than `PLAN_SHORT_CUT_RATIO` (75%) of it, catching long-plan sessions abandoned early even when they still exceed the absolute 40-minute minimum; sessions with `duration_seconds=None` remain excluded (no lap-level fallback)
- #1445: strength→non-strength workout edit no longer leaves stale `muscle_load_daily` rows — `PATCH /api/workouts/{id}` now recomputes strength muscle load when `"strength"` is in either the old or the new `workout_type` (previously only when the new type was strength), so switching a workout away from strength clears its stale contribution
- #1464: `base_neglected` Endurance gap rule — new load-mix rule (`backend/services/gap_analysis/rules/load_mix.py`) that fires (severity 2) when the Endurance score has decayed by more than `ENDURANCE_DECAY_THRESHOLD` (10 pts) over 8 weeks **and** easy-volume runs (runs with a null `speed_signal`) average fewer than `EASY_RUNS_MIN_PER_WEEK` (2/week) over 3 weeks; mirrors `speed_neglected` but anchored to Endurance with easy-run volume as evidence. The engine gathers new `endurance_score_history_8w` and `easy_runs_3w` inputs, an "Easy aerobic run" add-to-plan template is registered, and the finding is downgraded to severity 1 under a `back_off` verdict. Reference: `docs/calculations/gap-analysis.md`

## Sprint 109.1 — Worker read API (Hermes)

- #1449: Worker read API 1/5 — new read-only `GET /api/training/load?date=&user=` on the compute worker (port 9100) returns CTL/ATL/TSB/ACWR plus the persisted verdict for a date, reading from `training_load_snapshots` and `verdict_history` with no recomputation. If no snapshot exists for the requested date it returns the latest row ≤ that date (with its actual `snapshot_date`); 404 only when the user has no snapshots at all, `verdict` null when no verdict row for the date. `date` defaults to today (Asia/Bangkok); 422 on a non-`YYYY-MM-DD` date
- #1451: Worker read API 3/5 — new read-only `GET /api/plan/today?date=&user=` returns today's planned session(s) from `planned_sessions`, always HTTP 200 with `"planned": false` and an empty `sessions` list when nothing is planned so Hermes always gets a narratable answer; multiple sessions on one date come back as a list, each with `session_type` / `name` / `target` (distance/duration/intensity extracted from the session structure) / `note` / `status`
- #1453: Worker read API 5/5 — documented the read-only Hermes API in `docs/worker.md` (new "Read API (Hermes)" section): shared conventions (user resolution `?user=` → `WORKER_READ_API_USER` → single active user → 400; date defaults to Asia/Bangkok; no `X-Worker-Secret` — the tailnet/localhost binding is the access boundary, deliberate contrast with the secret-gated `/internal/*` routes) plus per-endpoint request/response examples. These routes are never deployed to Render

## Sprint 108 — Gap-finding coaching layer: improvement panel, LLM phrasing, add-to-plan, feedback, and muscle-aware planning

- #1374: Improvement panel — `GET /api/training/gap-analysis` now enriches each finding with human-readable `evidence_text`, a `has_template` flag (an add-to-plan template exists) and a `load_adding` flag, and returns findings ordered for a top-3 "what to improve" panel (severity desc, then code asc via `sort_findings_for_panel`). New `backend/services/gap_analysis/evidence_text.py`; rendered as the Improvement panel on the training performance tab (`frontend/js/training-performance.js`)
- #1375: LLM coach phrasing for gap findings — each finding gains a `phrasing` string (coach-voice one-liner) plus a `phrasing_source` (`llm` / `template`), produced by `backend/services/gap_analysis/phrasing.py` following the existing Groq pattern with a deterministic per-code template fallback (`templates.py`); fail-safe — a missing/errored LLM call always falls back to the template, never breaks the response
- #1376: One-tap add-to-plan — new `POST /api/training/gap-analysis/{code}/add-to-plan` creates a concrete `planned_sessions` row for a target date from the finding's code template (`get_template`). 201 with the planned-session dict; 404 when no template exists for the code; 409 when an identical gap-generated session already exists that week or when the current verdict is `back_off` and the template adds training load; 422 on a bad date. Surfaced as an "Add to plan" action on each panel finding
- #1377: Finding feedback (accept / dismiss with suppression window) — new `POST /api/training/gap-analysis/{code}/status` sets a finding `accepted` / `dismissed` / `active` (restore). Adds four suppression columns to `gap_findings` (`dismissed_at`, `dismissed_severity`, `accepted_at`, `accepted_evidence_hash`; migration `8d14fe27be6b`). The gap-analysis GET now partitions findings into `findings` (visible) and `muted` via `backend/services/gap_analysis/suppression.py`: a dismissal is honored until its window lapses or the evidence changes materially (`evidence_hash`), and an accepted finding whose evidence hash still matches stays muted. Response also carries the current `verdict`
- #1382: Muscle balance view — per-muscle-group load-state card on the training performance tab (`frontend/js/training-performance.js`), reading `GET /api/training/muscle-load` and rendering each group's acute/chronic/ACWR and classification (`overused` / `elevated` / `balanced` / `detraining` / `untrained` / `injured`) with a weekly series and per-source breakdown
- #1383: Muscle-aware planning guard — new `POST /api/training/plan-check` scores a planned-session draft (`session_type` + optional `structure`) against the user's current muscle-group classifications and returns `warnings` (a dominant group at/over the share threshold that is `overused` or `injured`) plus `suggestions` (untrained priority groups a strength session could target). Always 200 — informational, never blocking. Engine in `backend/services/plan_guard.py` (footprint estimator + `exercise_catalog` lookup); the training-plan editor (`frontend/js/training-plan.js`) attaches inline `plan_warnings` to each still-planned session. Formula reference: `docs/calculations/muscle-load.md`

## Sprint 107 — Gap analyzer: findings engine + run-economy, load-mix, and structural rules

- #1370: Gap analyzer core — new `gap_findings` table (one persistent row per `(user_id, week_start, code)`, migration `2bbdfbb8ea10`) and a rules engine under `backend/services/gap_analysis/`. Each finding carries a stable `code`, `severity` (1=note / 2=recommend / 3=priority), a short `recommendation`, machine-readable `evidence` (`[{metric, value, threshold, window}]`), an optional `target` (muscle group or session type), and a `status` (`active` / `accepted` / `dismissed`). Rules are pure functions registered with a `requires=[...]` input list; the engine gathers inputs from existing services, skips (never crashes on) rules whose inputs are absent or that raise — listing them in `skipped_rules` — and upserts findings preserving `status` on recompute. New `GET /api/training/gap-analysis` runs the engine for the session user (this ISO week) and returns `{week_start, computed_at, findings, skipped_rules}`. Contract/formula reference: `docs/calculations/gap-analysis.md`
- #1371: Gap analyzer rules A (run economy) — three rules over `run_form_metrics` and structural dose: `no_recent_plyo` / `plyo_deficit` (no plyometric work vs. `last_plyo_days_ago`), `gct_lengthening` (ground-contact time trending up across recent vs. prior/baseline windows), and `cadence_drift` (cadence drifting down). Each emits `evidence` with the observed metric, threshold, and lookback window
- #1372: Gap analyzer rules B (load mix) — three rules: `intensity_too_hard` (duration-weighted run-split distribution over 28 days skewed too far into high intensity, from `workout_splits.intensity_band`), `aerobic_durability_gap` (average long-run aerobic decoupling over 28 days above tolerance, from `workouts.decoupling_percent`), and `speed_neglected` (speed score falling over 56 days from `performance_score_history`, or too few speed/quality sessions in 21 days). Load-mix rules downgrade to severity 1 when the current `training_verdict` is `back_off`
- #1373: Gap analyzer rules C (structural) — three rules driven by injury history and muscle volume: `recurrent_niggle_area` (repeated injuries in the same body area over the last 90 days from `injury_log`), `undertrained_area_under_ramp` (priority muscle group with low chronic volume from `muscle_load_daily` while running TSS is ramping in `training_load`), and `strength_lapsed` (no recent strength work vs. `last_strength_days_ago`). Rules see `other_findings_codes` (codes of findings that fired earlier this run) so later rules can suppress themselves to avoid redundant recommendations

## Sprint 106 — Muscle-load ledger, run form metrics, structural dose stats

- #1367: Muscle-load ledger 1/3 — new `muscle_load_daily` table (`load_date` / `muscle_group` / `load` / `source ∈ {strength,run,plyo}`, one row per user+date+group+source, migration `a4cf1cbd5020`) records TSS-weighted daily load per muscle group. `backend/services/muscle_load.py` `recompute_strength_load_for_date` distributes each strength workout's TSS across muscle groups via `exercise_catalog` ratios and is recompute-idempotent (deletes + re-inserts the `(user, date, source)` rows, so re-running never double-counts). Fired automatically after every strength workout/session create/update/delete (`POST/PATCH/DELETE /api/workouts` and `/api/strength-sessions*`); failures are logged and never break the request. Backfill CLI `scripts/backfill_muscle_load.py`
- #1368: Run form metrics — new `run_form_metrics` table (`gct_ms` / `lss_kn_m` / `vertical_oscillation_cm` / `cadence_spm` / `power_w`, one row per `stryd_activity_pk`, migration `3bd978fbbf19`) extracts per-run Stryd running-dynamics out of `stryd_activities.form_metrics` JSONB into a queryable table. `backend/services/run_form_metrics_service.py` upserts rows incrementally on every Stryd sync (`sync_runner.py`; extraction failures never fail a sync) and supports a full historical backfill via the compute worker (`POST /internal/form-metrics/backfill`, worker job type `form_metrics_backfill`). New `GET /api/training/form-metrics?from=&to=` returns the per-run series plus 28-day trailing rolling means per metric (default last 90 days; 422 on bad/inverted range or range > 365 days)
- #1369: Structural dose stats — new `GET /api/training/structural-dose?weeks=` (1–52, default 8) returns per-week plyo and strength dose stats: plyo session count, foot contacts, dominant plyo phase, and de-duplicated `strength_days` (a date counts once whether it appears in `strength_sessions`, strength `workouts`, or both), plus `last_plyo_days_ago` / `last_strength_days_ago` recency and a 4-week `foot_contact_trend` (`rising`/`flat`/`falling`). Pure engine in `backend/services/structural_dose.py`
- #1380: Muscle-load ledger 3/3 — new `GET /api/training/muscle-load?weeks=` (1–52, default 8) computes per-muscle-group acute (7d) / chronic (28d) load and ACWR from `muscle_load_daily` (uncoupled variant, `CHRONIC_FLOOR = 5.0`), classifying each group `overused` (>1.5) / `elevated` (1.3–1.5) / `balanced` (0.8–1.3) / `detraining` (<0.8) / `untrained` (near-zero chronic on a priority group: calf, hamstring, glute, hip) / `inactive`, and marking groups touched by an active injury as `injured`. Response also carries a weekly-series for charting, per-group `source_breakdown`, and an `unclassified` list of exercise names with no catalog entry. Engine in `backend/services/muscle_load_acwr.py`; formula reference `docs/calculations/muscle-load.md`

## Sprint 104.2 — Body-measurement logging & plateau/diet-break detection

- #1358: Body measurements (waist & body-fat) — new `body_measurements` table (`waist_cm` / `body_fat_pct` nullable, one row per user + date, migration `da7cbe58ec60`) with CRUD endpoints `POST /api/body-measurements` (upsert by date), `GET /api/body-measurements?from=&to=`, `PATCH /api/body-measurements/{id}`, `DELETE /api/body-measurements/{id}`, plus CSV export `GET /api/exports/body-measurements`. Validation returns 422 unless at least one of waist (40–200 cm) or body-fat (3–60 %) is present. The Weight page gains a compact entry control (waist, optional bf%), a waist trend rendered against the weight series, and a "last measured N days ago" hint when nothing was logged in 7+ days. Unblocks the lean-mass-driven protein target (#1359)
- #1356: Plateau & diet-break detection — the weekly cut review (`GET /api/fuel/weekly-review`) adds a new `plateau` recommendation. Detection (in `backend/services/cut_review.py`): EWMA weekly rate better than −0.1 kg/wk (`PLATEAU_RATE_THRESHOLD_KG`) for ≥ 21 consecutive days (`PLATEAU_MIN_DAYS`) while an active cut plan exists AND logged intake was at/under budget on ≥ 70% of logged days in the window. The payload carries `plateau_days`, and the `action` text deep-links the fuel calibrate flow or suggests a 14-day diet break (set deficit to 0). Precedence is `insufficient_data` > `slow_down` > `plateau` > the rest, so plateau never overrides the higher-priority guards. Rendered on the Weight page (`frontend/js/fuel.js`)

## Sprint 104.1 — Weight-page north star: power-to-weight, weekly cut review, lean-mass-driven protein & cut guard

- #1355: Weekly cut review — new `GET /api/fuel/weekly-review` compares the trailing EWMA loss rate against the active plan's `target_rate_kg_per_week` and returns a deterministic `recommendation` (first-match-wins: `insufficient_data` / `slow_down` / `on_track` / `check_logging` / `recalibrate_maintenance` / `increase_deficit` / `ease_off`) plus `action` text, the `actual_rate_kg_per_week` / `plan_rate_kg_per_week` / `logging_adherence_pct` / `avg_intake_vs_budget_kcal` it was derived from, and an optional `suggested_deficit_delta_kcal` (±100 kcal step, clamped to `DEFICIT_KCAL_MAX`). Logic lives in `backend/services/cut_review.py` (pure `compute_cut_recommendation` + DB-backed `get_weekly_review`); the body-modifier %BW/wk guardrail takes absolute priority (`slow_down`), a fuel-logging adherence below 70% over 7 days yields `check_logging`, and fewer than 4 weigh-ins in 14 days yields `insufficient_data`. Surfaced on the Weight page
- #1359: Lean-mass-driven protein target and cut guard — lean mass is now derived at request time (`current_lean_mass_kg` in `backend/services/fuel.py`, precedence: latest `body_measurements.body_fat_pct` within 60 days → `ewma_weight × (1 − bf%)` → source `measured`; else `fuel_settings.lean_mass_kg` → `setting`; else `ewma_weight × 0.76` → `estimated`). When the source is `measured`, the protein target is computed from lean body mass (`lean_mass_kg × protein_g_per_kg`) instead of total weight; `lean_mass_kg` and `lean_mass_source` are exposed in the fuel payload. The weekly cut review adds a deterministic `losing_lean_mass` guard (`compute_losing_lean_mass_flag`) that fires when measured lean mass falls > 0.3 kg across the window. Ships the new `body_measurements` table (`waist_cm` / `body_fat_pct`, one row per user + date)
- #1360: Power-to-weight trend — new `GET /api/weight/power-to-weight?range=7D|30D|90D|6M|1Y|ALL` returns a dense daily W/kg series (`date`, `power_w`, `weight_kg` EWMA, `w_per_kg`) built from the user's threshold power (`ftp_w` in `user_preferences`) applied flat across the range (`power_basis: "flat_current"`); returns `available: false` when no FTP is configured, and `422` on an unknown range token. Pure series builder in `backend/services/power_to_weight.py`; surfaced as the north-star Power-to-weight card on the Weight page

## Sprint 104 — Fuel deficit linked to the weight plan, deficit periodization by training week phase

- #1354: Link weight plan to fuel deficit — the active `WeightPlan.target_rate_kg_per_week` now implies a daily calorie deficit (`abs(rate) × 7700 / 7`, rounded to nearest 10, clamped 0–750; `fuel.implied_deficit_kcal`). `GET /api/fuel/settings` now returns the active-plan linkage fields `plan_rate_kg_per_week`, `implied_deficit_kcal`, `deficit_gap_kcal`, and `consistency` (`aligned` when `|gap| ≤ 100`, else `mismatch`, or `no_plan`); the Weight page shows a mismatch banner with both numbers and a one-tap **Sync** button that calls the new `POST /api/fuel/settings/sync-deficit` (sets `deficit_kcal` to the implied value; 409 when no active plan)
- #1357: Deficit periodization — the fuel budget now respects the current training week phase. New `backend/services/fuel_periodize.py` resolves a phase (precedence race > taper > ramp > base) from planned A/B races, the training plan's taper window, and the load plan's current-week target TSS vs. the trailing-28d weekly average (ramp = target ≥ 1.1×): race/taper → maintenance (0 deficit), ramp → half deficit, base → full configured deficit. Gated by a new `auto_periodize` toggle on `fuel_settings` (default on); `GET /api/fuel/today` and `GET /api/fuel/week` now return `week_phase`, `week_phase_reason`, and `effective_deficit_kcal`, surfaced as a phase chip on the Weight page. The EA-floor hard stop is applied on top, unchanged
## Sprint 105 — Prediction snapshots, persisted score history + block deltas, closing the CTL/ATL calibration loop

- #1362: Prediction snapshots — persist the morning projection forecast once per day to a new `prediction_snapshots` table (first write of the day wins; same-day recomputes are no-ops) for forecast-vs-actual accuracy evaluation; payload holds per-race predicted finish times (with race ids), projected CTL at race date, and peak CTL + peak week; read back via `GET /api/projection/snapshots?from=&to=`
- #1361/#1365: Persisted performance score history + honest block deltas — new `performance_score_history` table stores daily endurance/speed scores with a `formula_version` stamp (write-through on each performance compute); score-card block-delta pills are now computed on the absolute scale from this persisted history (today − score at block start, same formula version only) instead of the misleading in-request relative `trend[]`, and hide when history doesn't reach back to block start; new `GET /api/performance/score-history?from=&to=` returns the persisted series (last 90 days by default, current formula version only)
- #1366: Close the CTL/ATL calibration loop — `training_load_snapshots` now records the `ctl_days`/`atl_days` that produced each row, so a snapshot computed with different constants is treated as a cache miss; accepting a calibration (`POST /api/races/{id}/calibrate/accept`) now backfills the full snapshot history with the new time constants immediately (`recompute_user_snapshots()`) and returns `snapshots_recomputed`. Removes the old "custom calibration always bypasses the cache" workaround
- #1363: Score re-anchor A — TDD test suite for absolute VDOT anchoring + Speed score (tests only; implementation to follow)
- #1364: Score re-anchor B — endurance aborted-session guard: sessions with `duration_seconds` at or below `MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS` (2400 s / 40 min) are now excluded from the endurance/durability signal in `compute_endurance_score`, so a cut-short interval session can no longer raise Endurance (mirrors the 40-min minimum in `endurance_signal.py`). Adds `backend/services/formula_versions.py` (shared version constants) and bumps the persisted performance-score `formula_version` from `vdot-v11` to `vdot-v12` so history rows are written under the new version

## Sprint 103 — Readiness unification & auto-recompute, verdict v2 (readiness + injuries), verdict history, today recommendation

- #1348: Unify readiness behind the single canonical CV-based calculator (`services/readiness/calculator.py`) across all four readiness surfaces (`GET /api/home/readiness`, the home-summary readiness block, `GET /trends/summary`, and the compute job) — weights HRV 40% / RHR 20% / sleep_quality 20% / energy 20%, HRV baseline 7d, RHR baseline 30d; replaces the legacy sleep_hours/HRV/RHR/mood/energy formula. `ReadinessResult` now also returns per-signal `raw_scores`
- #1349: Auto-recompute readiness when daily metrics change — `POST/PATCH/PUT /api/daily-metrics` recompute and upsert that day's `daily_readiness`; `DELETE` clears it
- #1351: Verdict v2 — today's readiness score, the 7-day readiness trend, and active `injury_log` entries deterministically downgrade the load-only back_off/hold/build verdict (downgrade-only, never promote); each fired rule is recorded in a new `modifiers` list on the verdict and surfaced in the weekly-summary narrative. Ships the backing `injury_log` table migration (partial #1350; no ORM model/API/UI yet)
- #1352: Today recommendation — `GET /api/training/today-recommendation` combines today's planned session, today's readiness score, and the current training-load verdict into a deterministic `keep` / `downgrade` / `rest` / `no_plan` call with a one-line reason and optional `apply_patch` (pure engine in `backend/services/today_recommendation.py`); surfaced as a Today's recommendation card on the home page with a one-tap "convert to easy" apply for downgrades
- #1353: Persist the daily verdict + inputs to a new `verdict_history` table (upsert per user+date, today's computation only); read back via `GET /api/training/verdict-history?from=&to=`

## Sprint 102 — LLM coaching layer: Groq client, habit insights, readiness narrative, weekly summary, plan suggestions

- #1311: Groq LLM client service: httpx provider, JSON-schema output, llm_generations cache table, fail-safe off by default
- #1312: Coaching text via Groq: habit insights + nudges LLM-phrased with coaching_voice template fallback
- #1313: Readiness explanation: LLM 'why this score' narrative with rule-based fallback
- #1314: Weekly summary narrative: coach-style weekly report from load/guardrail/PR facts
- #1315: Training plan suggestions: LLM-proposed next-week sessions, validated + one-tap add, never auto-applied

## Sprint 101 — Query tightening, worker delegation, stream slimming, session hygiene

- #1294: Per-workout session hygiene in duration-curve rebuild and signal/TSS backfill loops
- #1295: Serve workout detail from downsampled activity_streams instead of decoding raw streams_payload per request
- #1296: Stryd calendar sync: stop materializing full lifetime per-point streams in one json.loads
- #1297: Route heavy paths (full syncs, performance backfill, threshold-save rebuilds) to compute worker
- #1298: Query tightening: date-bound + column-only loads for scores/PR/weekly/reconcile; drop avatar bytes from resolve_user

## Sprint 100 — Memory config hardening and deferred JSONB payload columns

- #1292: Memory config hardening for Render free tier (pool_size 10→3, max_overflow 20→2, sync pool workers 3→1, BANISTER_REFIT_ENABLED=0 on web dynos)
- #1293: Defer JSONB payload columns on StravaActivity, StrydActivity, ActivityStream to eliminate bulk-loading of large blobs on list queries

## Sprint 98.2 — Follow-up hardening: taper achievability fix, backfill count alignment, BKK-time guardrail, speed-score warning UI

- #685: Use the target_form parameter in the taper_recommendation achievability check (previously required but unused)
- #1028: Derive runs_processed from the recompute_user_running_tss return value so the count matches workouts actually processed in backfill
- #1212: Use today_bangkok() instead of date.today() for the body_modifier guardrail window
- #1218: Surface the speed-score low-data warning and confidence band in the UI
## Sprint 98.3 — Follow-up hardening: session-signal 40-min boundary fix

- #1093: Align `_compute_session_signals` 40-min threshold to use `<=` (matching `compute_endurance_signal`), so a run of exactly 2400 s reports "run under 40 min" instead of "insufficient data"

## Sprint 98.1 — Follow-up hardening: atomic session submit, Riegel consolidation, migration/backfill fixes

- #542: Pin Chart.js CDN to a specific version (4.4.4) in training-log.html
- #557: Add exc_info=True to autofill recompute warning in duplicate_workout
- #558: Remove pytest.skip stubs from test_default_recent_workout_type__525.py
- #797: Add backing migration for the races.updated_at server default (now())
- #1027: Return canonical 404 shape (top-level state key) from performance endpoint on missing athlete
- #1081: Guard compute_and_store_speed_signal against non-run workout types
- #1086: Emit WARNING in _filter_trailing_window for runs with unparseable workout_date
- #1123: Fix monthly digest form chip to use fitness_ctl_change/form_recovered
- #1176: Consolidate duplicate Riegel logic and the RIEGEL_EXPONENT constant into riegel.py
- #1196: Atomic batch submit for strength and plyo sessions (no partial save on per-exercise failure)
- #1209: Clarify body-modifier delta vs multiplier unit mismatch

## Sprint 98 — Follow-up hardening: treadmill NGP wiring, plan-router API prefix, schema defaults, and bug fixes

- #541: Dedicated endpoint for volume chart weekly aggregations
- #551: Add SRI hash to Chart.js CDN script in training-log.html
- #614: Validate strava_activity_url scheme before injecting into href in run-view
- #616: Remove hardcoded fallback thresholds from get_user_thresholds in tss.py
- #684: Move race priority/status defaults to DB schema or require caller to supply them
- #751: Primary A-race selection may pick past race in training-plan.js
- #752: Delete failure silently ignored in deleteEditing (training-plan.js)
- #762: Fix downgrade() lap_type column handling in migration 145b95d5baf0
- #780: Guard _update_duration_curves with try/except in reconcile_workouts
- #796: fetch_and_detect_records uses overall-average pace curve, not per-duration bests
- #800: Test file for unverified #705 in sprint branch may break test collection
- #804: Standardise zone vocabulary: buried/neutral/fresh vs accumulated_fatigue/optimal/freshness
- #815: Use per-user timezone in performance tab date helpers
- #1026: Sanitize error reason in performance endpoint error response
- #1041: Align backfill run-count filter with performance endpoint's exact workout_type match
- #1042: Avoid leaking raw exception messages in performance endpoint error response
- #1083: backfill_signals_for_athlete returns success dict on commit failure
- #1120: Weekly summary re-queries workouts instead of reusing volume service
- #1121: Monthly summary 424 trigger mismatches AC description
- #1136: plan router: _check_plan_access equates plan_id with user_id
- #1137: plan router: _resolve_user duplicates auth logic from main.py
- #1138: plan router routes missing /api/ prefix
- #1177: Reconcile plan_id convention between race and projection routes
- #1187: Reconcile polarized-split default high band bound (10 vs 15)
- #1188: Derive intensity rolling-window bar label from selected range
- #1189: De-duplicate intensity rolling-window aggregation and fix N+1 query
- #1197: Economy ceiling bonus params on projected_ctl_to_score_ceiling are never supplied by callers
- #1208: Wire body modifier into production score/projection pipeline
- #1210: Same-date weight upsert can still create duplicates
- #1213: weight_ewma docstring drift: default span and alpha<=0 handling
- #1219: Wire normalize_treadmill_signal into the activity-signal pipeline

## Sprint 96 — Banister impulse-response model, environmental normalization, and calibration surfacing

- #1162: Recalibrate score ceiling on B race entry
- #1163: Implement post-race confidence band tightening
- #1164: Track qualifying-signal density for speed score
- #1165: Surface calibration status: recency, sufficiency, and confidence
- #1166: Build fit-data collector with minimum-data gate
- #1168: Normalize training load for heat and humidity
- #1169: Normalize treadmill incline and NGP into activity signals
- #1170: Add periodic refit with versioning and rollback
- #1203: Implement Banister parameter fitting function with data gate and fallback
- #1204: Add per-user Banister parameter storage with versioned history
- #1205: Implement held-out MSE validation comparing fitted vs population Banister params

## Sprint 95 — Bodyweight EWMA trend, energy-availability proxy, and body-composition modifier

- #1153: Add daily bodyweight logging by date
- #1154: Compute bodyweight trend via EWMA smoothing
- #1155: Compute weekly percent bodyweight rate of change from EWMA
- #1157: Compute energy availability proxy and flag low state
- #1158: Model body-modifier sign-flip around deficit threshold
- #1159: Wire body modifier into power-to-weight score term
- #1160: Build weight-trend view with EWMA and weekly rate
- #1161: Surface guardrail warning when loss is excessive or EA is low

## Sprint 94 — Strength & plyo session logging and the economy ceiling model

- #1142: Add strength session logging table and model
- #1143: Add plyometric session logging with foot-contacts
- #1144: Add strength and plyo session CRUD API
- #1145: Build strength and plyo session entry UI
- #1146: Compute economy stimulus from strength and plyo load
- #1147: Model delayed ceiling lift via lagged stimulus ramp
- #1148: Wire economy ceiling bonus into projection score-ceiling hook
- #1149: Backfill economy model across historical sessions
- #1150: Show economy contribution in projection/score view
- #1151: Make economy priors tunable via config

## Sprint 93 — Intensity-band classification, distribution chart, and polarized-split check

- #1128: Classify each lap by intensity band
- #1129: Aggregate session time-in-band into low/moderate/high percentages
- #1130: Add rolling intensity distribution over trailing windows
- #1131: Add polarized-split target-band deviation check
- #1133: Build intensity-distribution stacked bar chart
- #1134: Add polarized-check indicator for on-target vs grey-zone

## Sprint 92 — Training plan model, projection engine, and race time-curve chart

- #1099: Add migration for races_checkpoints and planned_load tables
- #1100: Add races/checkpoints CRUD API to plan router
- #1101: Add ramp and taper parameters to plan model
- #1102: Generate planned-load schedule from ramp/taper params
- #1103: Build plan editor UI for races and checkpoints
- #1104: Add ramp/taper controls with schedule preview to plan editor
- #1105: Scaffold projection.py and roll CTL/ATL/TSB forward
- #1106: Map projected CTL to Endurance/Speed score ceiling
- #1107: Derive expressible score from TSB form factor
- #1108: Convert expressible score to estimated race finish time
- #1109: Add Riegel cross-distance equivalence for race entries
- #1110: Add widening confidence band to projection horizon
- #1111: Add B-race tightening hook to confidence band
- #1112: Expose training projection via plan API endpoint
- #1113: Render projected time-curve chart with confidence band
- #1114: Assemble projection screen with markers and scores
## Sprint 91 — Weekly/monthly summaries, rate guardrail, and summary digest card

- #1055: Add weekly summary aggregation endpoint
- #1056: Add monthly summary endpoint with supercompensation detection
- #1057: Add rate guardrail and stressor ramp check
- #1058: Add summary digest card to Log tab with weekly/monthly toggle
- #1060: Surface guardrail warning in summary cards

## Sprint 89 — Google Drive / Health Sync sleep file import

- #1032: Add sleep_records table and idempotent Alembic migration
- #1034: Parse Health Sync sleep CSV into sleep_records
- #1035: Add scheduled and on-demand sleep file sync from Google Drive
- #1038: Backfill historical sleep data on first Google Drive connect

## Sprint 88.1 — Lap classification order, frontend four-state rendering, and thresholds editor polish

- #1019: Classify laps before scoring in performance endpoint (fixes classification order so band is assigned before score computation)
- #1021: Render four explicit performance states in frontend (scored / needs_thresholds / building_baseline / error driven by top-level state field)
- #1022: Settings thresholds editor writes FTP, threshold heart rate, threshold pace (pace input now accepts numeric sec/km; blank inputs when no value stored)

## Sprint 88 — Performance state field, diagnostic logging, backfill pipeline, and fitness chart fix

- #1018: Add diagnostic INFO logging to performance endpoint (runs_considered, laps_with_band, threshold flags per request)
- #1020: Return explicit top-level state field from performance endpoint (scored / needs_thresholds / building_baseline / error)
- #1023: Add POST /api/performance/backfill and full backfill pipeline to recompute historical run TSS and duration curve
- #1024: Fix Fitness Fatigue Form chart building_baseline propagation from endurance/speed score readiness

## Sprint 87.5 — Same-as-last button state-ownership refactor

- #509: [follow-up] Remove side effect from _updateSameAsLastBtn (state mutation)

## Sprint 87.4 — Weight-page unit toggle follow-ups and main.py import cleanup

- #506: [follow-up] Move ZoneInfo and func imports to top-level in main.py
- #510: [follow-up] Remove dead variable _cardBEntryNotes in weight.js
- #512: [follow-up] _applyUnit() does not convert stepper displayed value on unit switch

## Sprint 87.2 — Weight timezone fix, chart tap-toggle, and inline-edit listener cleanup

- #505: [follow-up] Unify list_weight_entries default range to Bangkok timezone
- #536: [follow-up] Weight chart tap-to-show: touchend hides tooltip immediately
- #537: [follow-up] Weight inline-edit: remove onEscape listener explicitly on save success

## Sprint 86 — Habits timezone fix, weight validation, range-token clarity, and test coverage

- #450: Memoize autofill computation per source in GET /api/habits/week
- #451: Fix Bangkok timezone in best_streak() for consistency
- #452: Extract backfill window validation as reusable FastAPI dependency
- #453: Extract habits.html inline CSS to frontend/css/habits.css
- #470: Document habit tracking_type immutability constraint in slide-over PATCH path
- #471: Add comprehensive date parsing validation tests for habit log endpoint
- #472: Add type-safe weight computation tests for project_hit_date
- #473: Replace magic-number timedeltas with RANGE_OFFSETS constant in weight-chart endpoint
- #474: Verify WeightEntry.entry_date index exists for range=ALL queries
- #475: Document --accent WCAG contrast and add verification tests for log button
- #477: Validate goal vs start weight before saving target in _saveEditPanel
- #503: Remove dead user_id query param from calendar.js weight-entries GETs
- #504: Remove user_id from calendar.js weight-entries POST body
- #476: Add visual regression tests for progress card bar positioning

## Sprint 85 — Performance score states, PR reason strings, logging observability, and duration-curve gap fix

- #927: Add observability to diagnose null performance scores
- #928: Classify laps before scoring in performance endpoint
- #929: Surface needs_thresholds state when athlete has no thresholds set
- #930: Render four distinct score-card states on Performance tab
- #984: Add structured INFO logging to PR endpoint caller
- #985: Fix duration curve data gap: lap classification and threshold population
- #986: Return explicit reason string for uncomputable personal records
- #987: Add unit tests for PR endpoint caller: logging and empty-curve branch

## Sprint 83 — Performance observability, needs-thresholds state, auto-detected PRs, and lap-classification backfill

- #910: Add observability to diagnose null performance scores
- #911: Classify laps before scoring in performance endpoint
- #912: Surface needs_thresholds state in performance endpoint
- #913: Fix empty Personal Records for athletes with run history
- #914: Backfill lap classification and trigger recompute on threshold save

## Sprint 80 — Weight goal projection and what-if simulation

- #874: Add pure function compute_planned_series(plan, as_of_date)
- #876: Add pure function to project goal arrival date
- #877: Add simulate_what_if pure function for weight projection
- #878: Add projection endpoint for arrival date and rate
- #879: Add what-if simulation endpoint for goal rate preview
## Sprint 81 — Habit-outcome alignment function

- #881: Add align_habit_and_outcome pure function with lag support

## Sprint 79 — Weight plans table, plan-line recompute, and CRUD endpoints

- #861: Add weight_plans table: migration and SQLAlchemy models
- #863: Add recompute_plan_from_progress pure function
- #864: Add CRUD endpoints for user weight plan

## Sprint 78.1 — Create and Edit Habit form

- #832: Build Create and Edit Habit Form (Slide-Over/Modal)

## Sprint 78 — Habits page shell, Today quick-log, and history calendar

- #827: Build Habits page shell and Today quick-log surface
- #828: Wire Today quick-log writes with upsert and streak refresh
- #829: Add Habits history calendar with day-status cells
- #830: Add habit filter to history calendar view


## Sprint 77 — Habits v2 schema, streak/consistency services, and summary endpoint

- #821: Add habits and habit_logs migrations and SQLAlchemy models
- #822: Add is_period_met pure function for habit completion logic
- #823: Add compute_streak pure function for habit streaks
- #824: Add compute_consistency pure function for habit schedule adherence
- #826: Add habits summary endpoint with streaks and consistency

## Sprint 76 — Training > Performance sub-tab and settings thresholds/zones enhancements

- #810: Add Settings section for training thresholds and zones
- #811: Implement Training > Performance sub-tab with real data

## Sprint 75 — Performance curve, form projection, taper guidance, race readiness summary, and post-race calibration

- #709: Add performance_curve pure function to fitness model
- #710: Add forward form projection to target date
- #711: Add taper_recommendation function for race date guidance
- #712: Add peak-tracking and race-specificity progress functions
- #713: Add race-readiness summary endpoint with timeline_markers
- #714: Add post-race calibration of personal fitness constants

## Sprint 74 — Strength PR detection, race checkpoints, and run auto-detection

- #704: Add personal-record detection from run history
- #705: Add PR storage, on-ingest comparison, and records feed
- #706: Add races table, Alembic migration, and SQLAlchemy model
- #707: Add race_checkpoints table and SQLAlchemy model
- #708: Add CRUD and auto-detection for races and checkpoints

## Sprint 73 — Fitness model, ACWR, running performance scores, and performance chart

- #697: Add readiness endpoint exposing CTL, ATL, TSB tiles
- #698: Add fitness, fatigue, and form (CTL/ATL/TSB) model
- #701: Add Endurance and Speed Running Performance Scores
- #702: Add compute_acwr training-load guidance function
- #703: Add performance chart time-series API endpoint

## Sprint 72 — Per-workout duration curves, athlete daily load, and threshold accept-flow

- #692: Suggest thresholds automatically from duration curve
- #693: Add unified daily training load series endpoint
- #694: Compute power and pace duration curves per workout
- #695: Aggregate and expose per-athlete best-effort duration curve
- #696: Add accept-suggestion flow for thresholds

## Sprint 71 — Lap classifier rewrite, session profile improvements, and strength TSS with configurable RPE max

- #678: Add lap intensity classification for session-profile detection
- #681: Add interval and set detection to session-profile
- #682: Implement detect_session_profile with precedence and data-quality gate
- #683: Expose detected session profile on full workout endpoint
- #688: Add strength TSS via session-RPE method
- #689: Add per-set RPE refinement method for strength TSS

## Sprint 70 — Activity streams, normalized power, running TSS, and golden test fixture

- #665: Add power, cadence, stride, and lap-type columns via Alembic migration
- #667: Ingest activity streams on Strava and Stryd sync
- #668: Select stream channels when workout merges two sources
- #669: Add compute_normalized_power pure function
- #671: Compute and store normalized power during workout ingestion
- #672: Add golden test fixture for workout metric calculations
- #673: Add pure function for TSS calculation via power
- #674: Add pure running TSS pace calculation function
- #675: Add pure HR-based TSS calculation function

## Sprint 69 — Run view redesign, Strength detail, Training Plan tab, and Settings UI

- #643: Convert Log Workout to slide-over panel
- #644: Build STRENGTH body for Log-workout slide-over
- #646: Redesign Run detail view header and load block
- #647: Add Session Profile and Laps to Run Detail View
- #648: Add route strip to Run view and redesign Strength detail
- #650: Build Training > Plan Sub-Tab with Race Plan UI
- #651: Add Settings UI for Training Thresholds and Zone Ranges

## Sprint 68.1 — Mobile week-strip and close button polish

- #639: Add mobile week-strip to Training Log sub-tab
- #642: Change Training Log close button to grey

## Sprint 68 — Training page sub-tabs, Readiness widget, and Weekly Volume chart

- #636: Add Log/Plan/Performance sub-tabs to Training page
- #637: Build Training Log sub-tab with filter and search
- #640: Add Readiness Widget to Training Log Sub-Tab
- #641: Add Weekly Volume & Load Chart to Training Log

## Sprint 67 — Race targets, fitness projections, and race readiness endpoint

- #604: Add races table and SQLAlchemy model
- #605: Add CRUD endpoints for user race targets
- #606: Add performance_curve pure function to fitness model
- #607: Add forward form projection to a target date
- #608: Add taper_recommendation function for race-day form targeting
- #609: Add peak-line on-track assessment to form tracking
- #610: Add race specificity progress tracker function
- #611: Add GET /api/races/{id}/readiness combined endpoint

## Sprint 66.1 — Dual source badges, compact sync controls, and weight chart redesign

- #601: Show both Strava and Stryd badges on merged workouts (has_strava/has_stryd on training-log and workout-list responses)
- #602: Add compact sync controls with real last-sync times to Settings → Integrations
- #633: Redesign weight trend chart with three-zone axes (BMI zones, moving average, custom SVG v8)

## Sprint 66 — Performance Thresholds settings expansion and Zone 2 habit provisioning

- #596: Add Max HR field to Performance Thresholds settings (user_preferences.max_hr, default 190 bpm)
- #597: Add Threshold Pace, Zone 2 HR band, and Weekly Zone 2 Target to Settings (user_preferences)
- #598: Use user-preference HR band for Zone 2 detection in Run view (replaces hardcoded 130–155 bpm)
- #599: Add 'Track Zone 2' opt-in button to provision a Zone 2 habit from Settings (with server-side duplicate guard)

## Sprint 65 — Strength TSS, duration curves, threshold suggestions, and daily load series

- #588: Compute power and pace duration curves per workout
- #590: Add auto-threshold suggestion from duration curve
- #591: Add accept-suggestion flow for threshold values
- #592: Add session-RPE TSS method for strength sessions
- #593: Implement per-set RPE refinement for strength TSS
- #594: Combine Strength TSS Calculation into Single Service
- #595: Add unified daily training load series

## Sprint 64 — Running TSS persistence, lap classification, and session profile detection

- #581: Add compute_running_tss service with priority-based method selection
- #582: Persist and expose computed running TSS on workouts
- #583: Classify lap intensity bands for session-profile detection
- #584: Add phase grouping for session profile detection
- #585: Add interval and set detection to session-profile pipeline
- #586: Implement detect_session_profile with precedence and data-quality gate
- #587: Expose detected session profile on full workout endpoint

## Sprint 63.1 — Activity streams table and channel selection

- #572: Add activity_streams table and SQLAlchemy model
- #574: Select stream channels when merging two workout sources

## Sprint 63 — Activity streams, running TSS, normalized power, Run View/Builder

- #567: Add Run View and Run Builder screens with Stryd/lap support
- #568: Add running TSS computation service
- #573: Ingest activity streams on Strava and Stryd sync
- #575: Add compute_normalized_power pure calculation function
- #576: Store normalized power on workout record at ingest
- #577: Add golden fixture and regression tests for workout metrics
- #578: Add pure power-branch running TSS calculation
- #580: Add HR-based TSS pure function for running

## Sprint 61.1 — Training-log detail panel a11y and dead-UI removal

- #529: Remove dead UI and fix a11y in detail panel

## Sprint 61 — Training log charts, mobile polish, Strava source parity, JS refactor

- #527: Show workout metrics and badges on mobile viewports
- #528: Surface training load and weekly volume chart on log
- #530: Normalize Strava source attribution across list and detail
- #531: Extract shared JS module for training format helpers

## Sprint 60 — Training log UX: quick-add modal, week-strip, duplicate workout, split authoring

- #522: Add inline quick-add modal for workout logging
- #523: Make week-strip day pills interactive and accessible
- #524: Add repeat-last and duplicate workout to log
- #525: Default new workout type to most recent selection
- #526: Add manual split authoring to training log detail panel

## Sprint 59.1 — Weight chart body metrics + CSS cleanup

- #520: Add body metrics and selectable moving average window
- #517: Move inline styles to styles.css, remove dead CSS

## Sprint 59 — Weight page polish: mobile, performance, streak

- #515: Fix weight chart unreadable on mobile touch devices
- #516: Fix dead chart zones and stale width comment
- #518: Fix inline-edit flicker and heavy cancel on weight rows
- #519: Reduce _reload() from 5–6 calls to targeted partial reloads
- #521: Add logging streak and adherence indicator to weight page

## Sprint 56 — Weight page redesign v2 + habits polish

- #454: Allow Users to Edit Habits After Creation
- #455: Fix 500 error when saving today's habit count
- #456: Expand Habit Icon Library and Increase Icon Size
- #457: Extend active-target endpoint with plan math
- #458: Extend weight-chart endpoint with plan, milestones, and coach data
- #459: Rebuild weight-page hero: current + log-today cards
- #460: Rebuild progress card with stat-row and plan-aware milestones
- #461: Add slide-in Edit-target panel, remove /weight/targets page
- #463: Migrate weight page to gradient design language
- #464: Rebuild weight trend chart as custom SVG

## Sprint 55 — Home redesign v7

- #436: Investigate home page widgets and confirm API readiness
- #437: Build GET /api/home/summary aggregator endpoint
- #438: Add habit quick-check strip and log-today action to home page
- #439: Add home weight widget with stepper quick-log
- #440: Add Readiness tile, Training card, and Sleep card to home page
- #441: Add Performance PRs and Recent Workouts cards
- #442: Assemble home layout with gradient design language
- #443: Home redesign: actionable habit checks + weight quick-log, two-up summary grid, single-call load — docs updated, dead widget code removed, cross-links audited, smoke verification recorded

## Sprint 54 — Habits redesign

- #428: Migrate habits page to gradient design language (Inter Tight / JetBrains Mono, floating cards)
- #429: Add `GET /api/habits/week` single-batch endpoint
- #430: Add streaks and last-week summary to habits week API
- #431: Enforce Bangkok backfill window and add increment-log mode
- #432: Build habits page hero — 7-segment week wheel + stats cards
- #433: Build daily habits grid with tap-to-check, totals, and day score row
- #434: Build weekly habits card with auto-sync badges and manual log chip
- #435: Habits redesign: week wheel, daily grid with day scores, weekly habits with workout auto-sync — polish pass, docs, dead code removal, and smoke verification

## Sprint 53.1 — Weight redesign cleanup

- #427: Weight page redesign: plan-vs-actual tracking, milestone chart, stepper quick-log, coach strip — docs updated, Chart.js dead code removed, purge script added

## Sprint 53 — Weight page redesign

- #420: Investigate Weight Page and Add Plan Math to Active-Target
- #421: Extend weight-chart endpoint with plan series and milestones
- #422: Rebuild weight page hero with 2-card layout
- #423: Rebuild weight trend chart as custom SVG
- #424: Rebuild progress card with stat-row and plan-aware milestones
- #425: Rebuild recent entries as compact side-by-side card
- #426: Migrate weight page to home design language

Features shipped in Sprint 53:
- Weight page migrated to home gradient design language (Inter Tight / JetBrains Mono, gradient background, floating cards)
- Weight page hero rebuilt as 2-card layout: current weight hero + recent-entries side panel
- Custom SVG trend chart replacing Chart.js dependency; renders actuals, 7-day MA, and plan overlay
- Progress card rebuilt with stat-row and plan-aware milestones (25 % / 50 % / 75 % / goal)
- `GET /api/weight-chart` extended with `plan_series`, `future_milestones`, `today_marker`, `logged_today`, `today_delta_kg`
- `GET /api/weight-targets/active` extended with `plan_today_kg`, `gap_kg`, `gap_direction`, `gap_basis`, `milestones`
- `backend/services/weight_plan.py` — plan math service: `plan_at`, `compute_gap`, `generate_milestones`

## Sprint 52 — Mobile fast-log & code quality

- #394: Mobile-optimise daily metrics fast-log flow — new fast-log form on home page with stepper inputs, segmented energy/mood pills, 800ms auto-save debounce, and "Log today" CTA banner
- #397: Fix empty catch blocks in home.js — add inline comments to all bare `catch (_) {}` blocks
- #398: Use parameterised SQL in Alembic migration v5j6k7l8m9n0 — wrap `op.execute()` SQL in `sa.text()`
- #399: Document broad `except Exception` in strava_sync.py — explain why broad catch is required to prevent stuck jobs
- #400: Reduce DOM-coupling in Strava sync controls — extract `_stravaHistoryOpen`, `_stravaSinceDateValue`, `_stravaShowPreview` state variables
- #401: Add `--user_id` argument to `scripts/run_strava_sync.py` CLI runner; falls back to first Strava-token user when omitted
- #402: Rename `sbadge2` to `sbadgeStryd` in training-log.js
- #405: Fix Bangkok timezone in `currentMonday()` in home-habits widget — derive week boundary from Asia/Bangkok date, not browser local timezone

## Sprint 51 — Weight tracking shipping polish

- #407: Add weight_targets table and WeightTarget model
- #408: Add CRUD endpoints for weight entries
- #409: Add weight target management endpoints with state transitions
- #410: Add /api/weight-chart endpoint with 7-day moving average
- #412: Build weight page frontend (desktop + mobile)
- #413: Build weight target management page (/weight/targets)
- #414: Add CSV export endpoints and wire Export buttons
- #415: Final polish — weight tracking docs, links, empty states

Features shipped in Sprint 51:
- Weight tracking end-to-end: log weigh-ins, 7-day moving average chart, progress toward goal target, milestone timeline, CSV export
- Weight target management: set/edit/end targets, pace tracking, projected completion date, history with filter pills
- `docs/features/weight-tracking.md` reference — data model, all API endpoints, moving-average math, status_label thresholds, projection math, known limitations
- Visual mockups committed at `docs/mockups/weight-tracking-*.html` and `docs/mockups/weight-target-management-desktop.html`
- Empty-state hardening: no NaN/undefined on zero entries; graceful no-history state on /weight/targets
- Chart.js CDN loading placeholder; date validation rejects future dates >1 day ahead

## Sprint 50 — MVP daily-use foundation

- #383: MVP investigation and root-cause analysis of daily-use friction
- #384: zone2_minutes tracking on workouts
- #385: Unified habits schema (auto-fill sources, weekly targets, archive)
- #386: Habit logs table and API
- #387: Habits CRUD API
- #388: Habit log progress API
- #389: Auto-fill linked habits on workout save
- #390: Mobile workout logging form (390px, touch-friendly)
- #391: Weekly habits-and-targets progress widget on home page
- #392: Habits management page with CRUD, reorder, archive, and starter habits
- #393: MVP polish — Bangkok time, /api/healthz, docs

Features shipped in Sprint 50:
- Habits unified system: auto-fill from zone2_minutes and workouts, weekly targets, archive/restore
- zone2_minutes tracking: workout field, API, auto-fill to Zone 2 habit
- Mobile workout logging form: full 390px flow for runs, lifts, and other workouts
- Mobile daily metrics: quick-entry card on home, mobile-optimised form
- Weekly habits home widget: Mon–Sun grid, streak badges, Bangkok-timezone week boundary
- Bangkok timezone: all day-boundary and week-start calculations use Asia/Bangkok
- `/api/healthz` endpoint for Render health checks

## Sprint 49

### Strava activity sync

Full Strava sync pipeline delivered across sprint 49:

- #370: Strava OAuth connect / callback / disconnect / token-refresh flow
- #371: `strava_activities` cache table and pull worker
- #372: Reconcile Strava activities into `workouts` rows
- #373: `GET /api/sync/strava/dry-run` preview endpoint
- #374: `sync_jobs` table and SyncJob model
- #375: Strava activity sync orchestrator service (`sync_strava_activities`)
- #376: Background sync job registry and in-memory state machine
- #377: `GET /api/sync/strava/dry-run` integration (phase 2)
- #378: Stryd power data — TSS formula routing and workout enrichment
- #379: Strava sync controls UI — settings panel, preview, polling, home banner
- #380: Sync-status visibility, history UI, CLI runner, scheduled-sync placeholder, docs
- #381: Strava E2E polish — training-log `is_stryd_synced`, data-quality endpoint, settings panel docs
- #382: `POST /api/sync/strava` trigger endpoint with job tracking and polling URL

Features included in this sprint:
- Manual sync from Settings → Integrations → Strava (date picker, preview, run)
- Real-time sync-progress polling in the settings panel and nav status bar
- `GET /api/sync/history` endpoint returning paginated SyncJob history with duration
- Collapsible sync history panel in Settings (last 5 jobs, status badges, counters)
- Scheduled sync placeholder (coming soon) in Settings
- `scripts/run_strava_sync.py` CLI runner for cron or ad-hoc use
- Deduplication via upsert on `strava_activity_id` (idempotent re-runs)
- Sync history docs at `docs/integrations/strava.md`

## Sprint 48

- #356: Add user_preferences table with per-user FTP and thresholds
- #357: Add GET and PATCH user preferences endpoints
- #358: Verify and remediate personal_records table and endpoints
- #359: Add bulk insert and history endpoints for personal records
- #360: Build settings page shell with section navigation
- #361: Build profile section in settings page
- #362: Build performance thresholds settings section
- #363: Build personal records section in settings page
- #364: Settings Integrations and About sections
- #365: Cross-link settings, polish nav, and add integration tests

## Sprint 47

- #347: Audit home page widgets and document data dependencies
- #348: Add GET /api/home/recent-workouts endpoint
- #349: Add GET /api/home/weight-summary endpoint
- #350: Add GET /api/home/personal-records endpoint for PR widget
- #351: Add GET /api/home/readiness daily readiness endpoint
- #352: Add GET /api/home/weekly-summary endpoint
- #353: Wire Home Page Weight Widget to Real API
- #354: Wire PR and Readiness widgets to real API endpoints
- #355: Wire weekly summary widget and polish home page

## Sprint 44

- #339: Build weight page frontend with hero strip, chart, progress, milestones, and recent entries
- #340: Build weight target management page at /weight/targets with active target card, milestone timeline, history, and export
- #341: Add CSV export endpoints for weight entries and targets
- #342: Weight tracking feature polish — docs, empty states, loading placeholder, date validation, home page link, and CHANGELOG

## Sprint 36

- #262: Add load_context to training-log endpoint and load docs

## Sprint 19

- #151: Build training log page shell, week strip, and filter bar
- #152: Render grouped workout list with week summaries and rest days
- #153: Build Training Log detail panel with prev/next nav
- #154: Add CSV export and commit training log mockups

## Sprint 16

- #121: Add distance, duration, heart rate, and elevation to workouts
- #122: Rename /training_log to GET /api/training-log and populate real fields
- #123: Build Training Log page shell and top action bar
- #124: Build week strip navigation on Training Log page
- #125: Add filter bar to Training Log page
- #126: Render grouped workout list with weekly summaries on Training Log
- #127: Add rest-day rows to Training Log
- #128: Add CSV Export to Training Log Page
- #129: Polish Training Log: skeletons, errors, edit actions, mobile
- #130: Add Training Log workout detail side panel

## Sprint 11

- #56: Build Training Log page — shell, week strip, filter bar, and workout list
- #57: Show rest days in Training Log with daily_metrics data
- #66: Add Trends page shell with date-range picker
- #67: Add GET /trends/summary aggregation endpoint
- #68: Add Readiness-Over-Time Chart with 7-Day Rolling Average
- #71: Add TSS and readiness correlation overlay chart
- #72: Add weekly digest summary card to home dashboard
- #73: Add HRV and RHR trend chart with baseline band
- #74: Add Sleep, Energy, and Mood Trend Chart

## Sprint 82.2 — Habit adherence analytics and nudges

- #886: Add build_nudges pure function for habit adherence coaching
- #889: Add compute_adherence_breakdown pure function for habit stats
- #890: Add detect_slipping_habits pure function for trend detection
- #892: Build Habits page adherence and nudges UI









































































































































































































## Sprint 84 — Coaching voice, focus-aware habits, compact run view, and weekly check-in

- #915: Compact run detail view for higher information density
- #916: Add Snapshot mode to Run detail view
- #920: Apply coaching copy to habit logging surfaces; `GET /api/habits/summary` now returns `week_done` and `total_logs` per habit
- #922: Add shared coaching voice module (`backend/services/coaching_voice.py`) for consistent tone across all coaching surfaces
- #923: Apply coaching copy to weight chart surfaces; verdict banner references 7-day trend with concrete next-lever; projection line framed as forward path; what-if panel headline frames scenario as still-winnable; `frontend/js/lib/weight-voice.js` is the single copy source
- #925: Add focus-aware coaching: slipping warnings, minimum version, anchoring, keystone; adds `minimum_version` and `anchor_event` columns to `habits`
- #926: Build standalone weekly check-in view (`/weekly-check-in`); new `GET /api/weekly-check-in` endpoint






























































































