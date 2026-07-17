# Database Schema

Source of truth: `backend/models.py`. Migrations in `alembic/versions/`.

All primary keys are UUID (`gen_random_uuid()`). All timestamps are `timestamptz`.

---

## users

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| name | varchar(100) | unique |
| email | varchar(255) | nullable |
| is_admin | bool | default false |
| is_active | bool | default true |
| password_hash | text | nullable (scrypt via auth.py) |
| avatar | bytea | nullable |
| avatar_mime | text | nullable |
| created_at | timestamptz | |

---

## weight_entries

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| entry_date | date | |
| entry_time | time | nullable |
| weight_kg | numeric(5,2) | |
| notes | text | nullable |
| source | varchar(20) | `manual`/`imported`/`backfill` |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Unique: `(user_id, entry_date, entry_time)` (nulls not distinct). Partial unique index `ix_weight_entries_user_date_null_time` on `(user_id, entry_date)` where `entry_time IS NULL` (Sprint 98 / #1210) — prevents duplicate same-date entries when no time is supplied (Postgres treats NULLs as distinct, so the base constraint alone did not catch this). Migration `4ad3bf3fff49`.

---

## weight_targets

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| start_weight_kg | numeric(5,2) | |
| start_date | date | |
| target_weight_kg | numeric(5,2) | |
| target_date | date | |
| status | varchar(20) | `active`/`achieved`/`abandoned`/`replaced` |
| ended_at | timestamptz | nullable |
| end_weight_kg | numeric(5,2) | nullable |
| notes | text | nullable |
| created_at / updated_at | timestamptz | |

Partial unique index: one active target per user.

---

## habits _(updated Sprint 50; v2 columns added Sprint 77; focus coaching fields added Sprint 84; section added Sprint 113 / #1506)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| name | varchar(200) | |
| habit_type | text | `binary` / `count` / `duration`; default `binary`; check constraint `ck_habits_habit_type_values` |
| target_value | numeric(12,4) | nullable — target quantity for `count`/`duration` habits |
| unit | varchar(50) | nullable — display unit (e.g. `min`, `reps`) |
| schedule_type | text | `daily` / `weekly` / `times_per_week`; default `daily`; check constraint `ck_habits_schedule_type_values` |
| schedule_target | int | nullable — e.g. number of times per week for `times_per_week` schedules |
| active | bool | default true — false = soft-deactivated without archiving |
| display_order | int | default 0 |
| created_at | timestamptz | |
| updated_at | timestamptz | nullable |
| description | text | nullable — legacy |
| tracking_type | varchar(50) | legacy; `daily_checkmark` / `weekly_count` / `minutes` / `quantity` |
| weekly_target | numeric(10,2) | nullable — legacy weekly target |
| auto_fill_source | varchar(100) | nullable — e.g. `zone2_minutes` to auto-fill from workouts |
| icon | varchar(100) | nullable |
| color | varchar(20) | nullable |
| sort_order | int | default 0 |
| is_archived | bool | default false |
| archived_at | timestamptz | nullable |
| minimum_version | text | nullable — minimum viable version of the habit for struggling days (focus coaching, Sprint 84) |
| anchor_event | text | nullable — existing action to pair the habit with as an implementation intention (focus coaching, Sprint 84) |
| section | text | NOT NULL, default `'general'` — `training` / `general`; groups habits in the UI (Sprint 113 / #1506); check constraint `ck_habits_section_values`. Migration `f2334eacc205_add_habit_section` |

---

## habit_logs _(updated Sprint 50; note column added Sprint 77)_

One row per log event. For `daily_checkmark` habits, one row per day (value=1). For other tracking types, rows are summed over `log_week_start` to compute weekly progress.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| habit_id | UUID FK→habits | CASCADE |
| user_id | UUID FK→users | CASCADE |
| log_date | date | |
| value | numeric(10,4) | default 1 |
| note | text | nullable — v2 per-log annotation |
| created_at | timestamptz | |
| updated_at | timestamptz | nullable |
| log_week_start | date | legacy — Monday of the week (Asia/Bangkok) |
| notes | text | nullable — legacy |
| source | varchar(50) | legacy — `manual` / `workout_save` / `auto_fill` / `manual_override` |

Unique: `(habit_id, log_date)`. Index: `(habit_id, log_week_start)`.

---

## workouts _(zone2_minutes added Sprint 50; tss_method added Sprint 64; power/NP/cadence/stride added Sprint 70; speed/endurance signal columns added Sprint 90; temperature/humidity added Sprint 96; flat_equivalent_pace added Sprint 98)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| workout_date | date | |
| name | varchar(200) | |
| workout_type | varchar(50) | |
| remarks | text | nullable |
| tss | float | nullable; ≥0 |
| tss_source | varchar(20) | nullable; `manual`/`calculated` |
| tss_method | varchar(20) | nullable; `power`/`pace`/`hr` — method used when TSS was auto-computed |
| source | varchar(20) | nullable; `manual`/`strava`/`stryd`/`both` |
| distance_km | numeric(8,3) | nullable; ≥0 |
| duration_seconds | int | nullable; ≥0 |
| avg_hr / max_hr | int | nullable; 20–250 |
| elevation_m | int | nullable |
| start_time | timestamptz | nullable |
| strava_activity_url | text | nullable |
| strava_activity_pk | UUID FK→strava_activities | SET NULL |
| stryd_activity_pk | UUID FK→stryd_activities | SET NULL |
| manual_overrides | jsonb | nullable |
| zone2_minutes | int | nullable — minutes spent in Zone 2 |
| avg_power | int | nullable — workout-level average power (watts) |
| max_power | int | nullable — workout-level max power (watts) |
| np | int | nullable — normalized power (watts), computed at ingest |
| avg_cadence_spm | int | nullable — average cadence (steps per minute) |
| avg_stride_m | numeric(4,2) | nullable — average stride length (metres) |
| speed_signal | float | nullable — best 1–6 min effort ratio vs threshold (Sprint 90 / #1048) |
| speed_signal_basis | varchar(20) | nullable — `power` / `pace` / `heart_rate` |
| speed_signal_window_seconds | int | nullable — duration of the best window used |
| speed_signal_source | text | nullable — descriptive computation path string |
| endurance_signal | float | nullable — aerobic durability score (0–100+); runs ≥ 40 min only (Sprint 90 / #1049) |
| decoupling_percent | float | nullable — `((e1 - e2) / e1) * 100`; positive = fade |
| efficiency_first_half | float | nullable — power/HR or speed/HR for first half of run |
| efficiency_second_half | float | nullable — same metric for second half |
| endurance_signal_source | varchar(20) | nullable — `power_hr` / `speed_hr` |
| temperature_c | float | nullable — ambient temperature (°C) for heat/humidity normalization (Sprint 96 / #1168) |
| humidity_pct | float | nullable — relative humidity (0–100) for heat/humidity normalization (Sprint 96 / #1168) |
| flat_equivalent_pace | float | nullable — flat-equivalent pace for treadmill activities, computed from `normalize_treadmill_signal` via the Minetti NGP formula; None for outdoor runs (Sprint 98 / #1219) |
| created_at | timestamptz | |

Child tables: `workout_exercises`, `workout_splits`.

---

## workout_exercises

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| workout_id | UUID FK→workouts | CASCADE |
| display_order | int | |
| name | varchar(200) | |
| sets / reps | int | nullable |
| weight_kg | numeric(6,2) | nullable |
| duration | varchar(50) | nullable |
| rpe | int | nullable; 1–10 |
| distance_km | numeric(8,3) | nullable |
| duration_seconds | int | nullable |
| avg_hr | int | nullable |
| created_at | timestamptz | |

---

## workout_splits _(lap_type added Sprint 63; power/cadence/stride added Sprint 70; lap_type tightened to NOT NULL Sprint 70; intensity_band added Sprint 93)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| workout_id | UUID FK→workouts | CASCADE |
| split_index | int | |
| distance_km | numeric(6,3) | |
| duration_seconds | int | |
| avg_hr | int | nullable |
| avg_power | int | nullable — split-level average power (watts) |
| cadence_spm | int | nullable — cadence in steps per minute |
| stride_length_m | numeric(4,2) | nullable — stride length in metres |
| lap_type | varchar(10) | NOT NULL; `auto` (1-km auto-split) or `manual`; default `auto`; check constraint enforces `IN ('auto', 'manual')` |
| intensity_band | varchar(20) | nullable — per-lap intensity band classified from power → pace → HR vs user thresholds; `easy` / `steady` / `tempo` / `threshold` / `hard`; persisted on PUT splits; check constraint `ck_workout_splits_intensity_band_values` (Sprint 93) |
| created_at / updated_at | timestamptz | |

Unique: `(workout_id, split_index)`. Checks: `ck_workout_splits_lap_type_values`, `ck_workout_splits_intensity_band_values`. Migration: `e3f1c0da097c` (intensity_band column).

---

## daily_metrics

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| metric_date | date | |
| resting_hr | int | nullable; 20–200 |
| hrv | int | nullable; 0–300 |
| sleep_hours | numeric(3,1) | nullable; 0–24 |
| sleep_quality | int | nullable; 1–5 |
| energy | int | nullable; 1–5 |
| mood | int | nullable; 1–5 |
| notes | text | nullable |
| created_at / updated_at | timestamptz | |

Unique: `(user_id, metric_date)`.

---

## daily_readiness

Computed from `daily_metrics` by the single canonical CV-based calculator
(`services/readiness/calculator.py` — weights HRV 40% / RHR 20% / sleep_quality
20% / energy 20%; HRV baseline 7d, RHR baseline 30d; Sprint 103 / #1348). Written
via `POST /api/readiness/compute` and also **auto-recomputed** whenever the
underlying `daily_metrics` row is created/updated and cleared when it is deleted
(Sprint 103 / #1349).

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| date | date | |
| score | numeric(5,2) | 0–100 |
| components | jsonb | |
| computed_at | timestamptz | |
| daily_metric_id | UUID FK→daily_metrics | SET NULL |

Unique: `(user_id, date)`.

---

## personal_records

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| track_key | varchar(100) | |
| track_name | varchar(200) | |
| track_type | varchar(10) | `time` / `weight` |
| value_numeric | numeric(12,4) | >0 |
| achieved_on | date | |
| source | varchar(100) | nullable |
| created_at / updated_at | timestamptz | |

---

## user_preferences _(updated Sprint 66; source columns added Sprint 65; strength_rpe_max added Sprint 71; ctl_days/atl_days added Sprint 75; threshold timestamps added Sprint 76)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE, unique |
| ftp_w | int | nullable |
| ftp_w_source | varchar(30) | nullable; `user_accepted` or `manual`; tracks how the threshold was set |
| ftp_w_updated_at | timestamptz | nullable — stamped when FTP is written via PATCH or suggestion accept |
| threshold_hr | int | nullable |
| max_hr | int | nullable — max heart rate (bpm); default 190 when null |
| threshold_hr_source | varchar(30) | nullable; `user_accepted` or `manual` |
| threshold_hr_updated_at | timestamptz | nullable — stamped when threshold HR is written via PATCH or suggestion accept |
| threshold_pace_seconds_per_km | int | nullable |
| threshold_pace_seconds_per_km_source | varchar(30) | nullable; `user_accepted` or `manual` |
| threshold_pace_seconds_per_km_updated_at | timestamptz | nullable — stamped when threshold pace is written via PATCH or suggestion accept |
| zone2_hr_min | int | nullable — Zone 2 lower HR bound; default 130 when null |
| zone2_hr_min_updated_at | timestamptz | nullable — stamped when Zone 2 min HR is written via PATCH |
| zone2_hr_max | int | nullable — Zone 2 upper HR bound; default 155 when null |
| zone2_hr_max_updated_at | timestamptz | nullable — stamped when Zone 2 max HR is written via PATCH |
| weekly_zone2_target_min | int | nullable — weekly Zone 2 minutes goal; default 150 when null |
| preferred_units | varchar(20) | `metric` (default) |
| timezone | varchar(100) | default `Asia/Bangkok` |
| week_start_day | int | default 1 (Monday) |
| display_name | varchar(100) | nullable |
| date_format | varchar(20) | default `YYYY-MM-DD` |
| strength_rpe_max | int | nullable — ceiling of the RPE scale used for strength TSS (e.g. 10 for standard RPE, 20 for Borg); required for session-RPE strength TSS calculation |
| ctl_days | int | nullable — personalised CTL time constant in days; falls back to population default (42) when null |
| atl_days | int | nullable — personalised ATL time constant in days; falls back to population default (7) when null |
| created_at / updated_at | timestamptz | |

`GET /api/user-preferences` returns both a `row` (stored overrides, null when unset) and a `defaults` object with system default values for all threshold fields. `PATCH /api/user-preferences` accepts any subset of the nullable columns; omitted fields are unchanged.

---

## strava_tokens

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE, unique |
| athlete_id | bigint | |
| access_token / refresh_token | text | |
| expires_at | timestamptz | |
| scope | varchar(255) | nullable |
| athlete_data | jsonb | nullable |
| created_at / updated_at | timestamptz | |

---

## strava_activities _(detail_payload and streams_payload added Sprint 63)_

Raw activities pulled from Strava. Reconciled into `workouts` by `reconcile.py`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| strava_activity_id | bigint | unique |
| start_time | timestamptz | indexed |
| activity_type | varchar(50) | |
| name | varchar(255) | |
| distance_km / duration_seconds | numeric/int | nullable |
| avg_hr / max_hr | int | nullable |
| elevation_m / avg_power_w / max_power_w | int | nullable |
| device_name / external_id | varchar | nullable |
| is_stryd_synced | bool | default false |
| raw_payload | jsonb | |
| detail_payload | jsonb | nullable — full `/activities/{id}` detail blob |
| streams_payload | jsonb | nullable — raw `/activities/{id}/streams` response; used by reconcile to populate `activity_streams` |
| synced_at | timestamptz | |

---

## stryd_activities _(streams_payload added Sprint 63; grade_percent added Sprint 98; manual_laps added Sprint 101)_

Raw activities from Stryd. Reconciled into `workouts` by `reconcile.py`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| stryd_activity_id | varchar(255) | unique |
| start_time | timestamptz | indexed |
| name | varchar(255) | nullable |
| distance_km / duration_seconds | numeric/int | nullable |
| avg_power_w / avg_hr | int | nullable |
| tss | int | nullable |
| form_metrics / power_zones / splits | jsonb | nullable |
| streams_payload | jsonb | nullable — raw per-point streams (timestamp_list, total_power_list, etc.); used by reconcile to populate `activity_streams` |
| raw_payload | jsonb | |
| grade_percent | float | nullable — treadmill incline extracted from the raw payload's `average_incline`; present only for treadmill activities, None for outdoor runs (Sprint 98 / #1219). Migration `4753105d42ae` |
| manual_laps | jsonb | nullable — computed at sync time by `compute_manual_laps`; avoids materialising `streams_payload` on the workout detail request path (Sprint 101 / #1295). Migration `c764aa719` |
| synced_at | timestamptz | |

---

## stryd_credentials

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE, unique |
| stryd_email | varchar(255) | |
| stryd_password_encrypted | text | Fernet-encrypted |
| session_token | text | nullable |
| session_token_expires_at | timestamptz | nullable |
| athlete_id | bigint | nullable |
| created_at / updated_at | timestamptz | |

---

## activity_streams _(added Sprint 63; channel_attribution added Sprint 63.1)_

Per-sample time-series channel data for a workout. One row per workout; absence of a row means no stream data exists for that workout (e.g. a manual strength session). Populated during Strava/Stryd reconcile from `strava_activities.streams_payload` or `stryd_activities.streams_payload`.

| column | type | notes |
|--------|------|-------|
| workout_id | UUID PK FK→workouts | CASCADE |
| sample_interval_seconds | int | nullable |
| source | varchar(20) | nullable; `strava`, `stryd`, or `merged` |
| time_offset_seconds | jsonb | nullable — array of integer offsets |
| power_w | jsonb | nullable — array of power samples (watts) |
| heart_rate_bpm | jsonb | nullable — array of HR samples |
| pace_seconds_per_km | jsonb | nullable — array of pace samples |
| cadence_spm | jsonb | nullable — array of cadence samples |
| altitude_m | jsonb | nullable — array of altitude samples |
| latitude | jsonb | nullable — array of GPS latitude samples |
| longitude | jsonb | nullable — array of GPS longitude samples |
| channel_attribution | jsonb | nullable — per-channel source map produced by `select_channels` when a workout has data from two devices, e.g. `{"power_w": "stryd", "latitude": "strava"}`; present only when `source = 'merged'` |

Check: `source IN ('strava', 'stryd', 'merged')`.

---

## sync_jobs

Persistent record of sync runs (Strava/Stryd). In-memory state machine is separate (`backend/services/sync_jobs.py`).

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| source | varchar(50) | e.g. `strava` |
| job_type | varchar(50) | |
| status | varchar(20) | `pending`/`running`/`done`/`failed` |
| started_at / completed_at | timestamptz | nullable |
| activities_fetched/created/updated/skipped | int | default 0 |
| error_message | text | nullable |
| since_date | date | nullable |
| parameters | jsonb | nullable |
| created_at / updated_at | timestamptz | |

---

## training_load_snapshots

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| snapshot_date | date | |
| tss_for_day | int | |
| ctl / atl / tsb | float | CTL=42d, ATL=7d, TSB=CTL−ATL |
| acwr | float | nullable |
| formula_version | text | nullable — cache-invalidation stamp; a mismatch forces a live recompute |
| ctl_days | int | nullable _(Sprint 105 / #1366)_ — EWMA time constant that produced the row; NULL = module default 42 |
| atl_days | int | nullable _(Sprint 105 / #1366)_ — EWMA time constant that produced the row; NULL = module default 7 |
| computed_at | timestamptz | |

Unique: `(user_id, snapshot_date)`. `ctl_days`/`atl_days` record the calibration used so that accepting a new calibration (`POST /api/races/{id}/calibrate/accept`) treats the existing rows as stale and recomputes the full snapshot history with the new constants (`recompute_user_snapshots()`).

---

## workout_feel

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| feel_date | date | |
| workout_id | UUID FK→workouts | SET NULL, nullable |
| rpe_1_to_10 | int | nullable; 1–10 |
| notes | text | nullable |
| created_at / updated_at | timestamptz | |

---

## google_oauth_credentials _(last_sync_at added Sprint 89)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE, unique |
| google_sub | varchar(255) | |
| email | varchar(255) | |
| email_verified | bool | |
| access_token | text | |
| refresh_token | text | nullable |
| expires_at | timestamptz | |
| id_token_payload | jsonb | nullable |
| last_sync_at | timestamptz | nullable — stamped after each Drive sleep sync run |
| created_at / updated_at | timestamptz | |

---

## sleep_imports

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| source | varchar(30) | `samsung_health`/`google_fit`/`manual_json`/`ocr_screenshot` |
| source_identifier | varchar(255) | nullable |
| import_date | date | |
| raw_data / parsed_data | jsonb | |
| import_status | varchar(20) | `pending`/`parsed`/`merged`/`rejected`/`failed` |
| error_message | text | nullable |
| created_at / updated_at | timestamptz | |

Unique: `(user_id, source, source_identifier)`.

---

## sleep_records _(added Sprint 89)_

Structured nightly sleep records imported from external sources (e.g. Health Sync CSV exported from Google Drive). One row per night per user. Idempotent upsert on `(user_id, external_id)`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| sleep_date | date | NOT NULL — date of the sleep night (the morning date) |
| start_at | timestamptz | NOT NULL |
| end_at | timestamptz | NOT NULL |
| total_sleep_minutes | int | NOT NULL |
| time_in_bed_minutes | int | NOT NULL |
| awake_minutes | int | nullable |
| light_minutes | int | nullable |
| deep_minutes | int | nullable |
| rem_minutes | int | nullable |
| sleep_score | int | nullable |
| sleep_efficiency | numeric(5,2) | nullable |
| source | text | NOT NULL; e.g. `health_sync_csv` |
| device | text | nullable |
| external_id | text | NOT NULL — dedup key; SHA-256 of `{user_id}:{sleep_date}:{start_at}` when the source has no native ID |
| created_at / updated_at | timestamptz | |

Unique: `(user_id, external_id)`. Index: `ix_sleep_records_user_sleep_date` on `(user_id, sleep_date)`.
Migrations: `ec0e2c456452` (initial table), `53b033936666` (make stage cols nullable).

---

## app_config

| column | type |
|--------|------|
| key | varchar(100) PK |
| value | text |
| updated_at | timestamptz |

---

## workout_templates

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| name | varchar(200) | |
| exercises | jsonb | |
| created_at | timestamptz | |

---

## races _(added Sprint 67; race_type added Sprint 69; actual_time_seconds added Sprint 74; calibration endpoints Sprint 75)_

User target race entries. `goal_pace_seconds_per_km` is derived from `goal_time_seconds / distance_km` at write time via `compute_goal_pace`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| name | varchar(200) | |
| race_date | date | |
| distance_km | numeric(8,3) | >0 |
| goal_time_seconds | int | nullable; >0 |
| goal_pace_seconds_per_km | int | nullable; derived from goal_time_seconds / distance_km |
| actual_time_seconds | int | nullable; recorded after the race via `POST /api/races/{id}/calibrate` |
| priority | varchar(10) | `A` / `B` / `C`; server default `'A'` (Sprint 98 / #684) |
| status | varchar(20) | `planned` / `done` / `abandoned`; server default `'planned'` (Sprint 98 / #684) |
| race_type | varchar(20) | `race` / `checkpoint`; default `race` — distinguishes A-race targets from intermediate checkpoints |
| created_at | timestamptz | |
| updated_at | timestamptz | auto-updated on write; server default `now()` (Sprint 98 / #797) |

Index: `ix_races_user_id`. Migrations: `ll2a3b4c5d6e` (initial), `mm3c4d5e6f7g` (race_type column), `nn4d5e6f7g8h` (merge head), `ba386d88fa17` (actual_time_seconds), `1c4afa2ab696` (priority/status server defaults), `f31dde78c681` (updated_at server default).

### Race calibration endpoints _(added Sprint 75)_

| method | path | description |
|--------|------|-------------|
| `POST` | `/api/races/{id}/calibrate` | Record `actual_time_seconds`, set `status='done'`, return fitness-constant calibration suggestions derived from training-load snapshots. Body: `{"actual_time_seconds": int}`. Response: `{race, suggestions}`. |
| `POST` | `/api/races/{id}/calibrate/accept` | Accept calibration suggestions and persist `ctl_days` / `atl_days` to `user_preferences`. Body: `{"ctl_days": int|null, "atl_days": int|null}`. Constants are written **only** when the user explicitly calls this endpoint — never auto-applied. |

---

## race_checkpoints _(added Sprint 74)_

Intermediate milestones within a target race. Auto-detection marks a checkpoint met when a run workout satisfies its targets; `met_override = true` freezes the state against future auto-detection.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| race_id | UUID FK→races | CASCADE |
| user_id | UUID FK→users | CASCADE |
| label | varchar(200) | display name of the checkpoint |
| target_date | date | inherited from the parent race at create time |
| target_distance_km | numeric(8,3) | nullable |
| target_pace_seconds_per_km | int | nullable |
| target_duration_seconds | int | nullable |
| met | bool | default false; set to true by auto-detection or manual override |
| met_override | bool | default false; true when `met` was set manually, blocking auto-detection |
| met_workout_id | UUID FK→workouts | SET NULL, nullable — workout that satisfied the checkpoint |
| created_at / updated_at | timestamptz | |

Indexes: `ix_race_checkpoints_race_id`, `ix_race_checkpoints_user_id`. Migration: `dd327d5ed495`.

---

## strength_personal_records _(added Sprint 74)_

Current best per `(user, exercise_key, rep_band_label)`. Updated in-place when a new PR is set; the previous value is preserved in `previous_weight_kg` / `previous_achieved_on`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| exercise_key | varchar(200) | normalised exercise identifier |
| exercise_name | varchar(200) | display name |
| rep_band_label | varchar(20) | e.g. `1RM`, `3–5 reps` |
| rep_band_min / rep_band_max | int | inclusive rep-count bounds for the band |
| weight_kg | numeric(6,2) | current best weight; >0 |
| reps | int | rep count at the current best; ≥1 |
| previous_weight_kg | numeric(6,2) | nullable — previous best before the current PR |
| previous_achieved_on | date | nullable |
| achieved_on | date | date the current PR was set |
| workout_id | UUID FK→workouts | SET NULL, nullable |
| exercise_id | UUID FK→workout_exercises | SET NULL, nullable |
| created_at / updated_at | timestamptz | |

Unique: `(user_id, exercise_key, rep_band_label)`. Migration: `a1607bab81de`.

---

## weight_plans _(added Sprint 79)_

Structured weight-goal plan for a user. One active plan per user at a time; creating a new plan deactivates any prior active plan atomically.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE; indexed |
| start_date | date | NOT NULL |
| start_weight_kg | numeric(6,2) | NOT NULL |
| goal_weight_kg | numeric(6,2) | NOT NULL |
| goal_date | date | nullable |
| target_rate_kg_per_week | numeric(4,2) | nullable; omit to let `compute_plan_line` derive rate from `goal_date` |
| phase | text | NOT NULL; default `'cut'`; `cut` / `bulk` / `maintain` |
| active | bool | NOT NULL; default `true`; false = deactivated (soft delete) |
| created_at | timestamptz | server default now() |
| updated_at | timestamptz | server default now(), onupdate now() |

Index: `ix_weight_plans_user_id`. Migration: `64d8ad2d9a42`.

---

## training_plans _(added Sprint 92)_

Per-user training plan configuration with ramp-up and taper-down parameters. One plan per user at a time is typical; multiple are allowed. Accessed via `POST /api/plans`, `GET /api/plans/{id}`, `PATCH /api/plans/{id}`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE; indexed |
| name | text | NOT NULL |
| ramp_rate | numeric(6,2) | nullable — weekly CTL ramp rate target |
| taper_start | numeric(6,2) | nullable — CTL value at which taper begins |
| taper_length | numeric(6,2) | nullable — taper duration in days |
| taper_shape | text | nullable; `linear` / `step` / `exponential`; check constraint `ck_training_plans_taper_shape` |
| created_at | timestamptz | server default now() |
| updated_at | timestamptz | server default now(), onupdate now() |

Index: `ix_training_plans_user_id`. Migration: `3f9e1b2c4a7d`.

---

## races_checkpoints _(added Sprint 92, schema-only)_

Standalone event table for named race or checkpoint entries used by the projection system. Distinct from `race_checkpoints` (which are milestones within an existing `races` row). The `type` column is constrained to `race` or `checkpoint`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| name | text | NOT NULL |
| date | date | NOT NULL |
| distance_km | numeric(8,3) | nullable |
| type | text | NOT NULL; `race` or `checkpoint`; check constraint `ck_races_checkpoints_type` |
| goal_time | int | nullable — goal finish time in seconds |

Migration: `017a12a2a6f5`.

---

## planned_load _(added Sprint 92, schema-only)_

One planned-TSS value per calendar date for projection planning. The `date` column is the primary key so each date has exactly one value.

| column | type | notes |
|--------|------|-------|
| date | date PK | |
| planned_tss | numeric(8,2) | NOT NULL |

Migration: `017a12a2a6f5`.

---

## strength_record_achievements _(added Sprint 74)_

Append-only log of every PR-beating event. Written at workout-ingest time; used to populate the achievements feed without re-deriving history on read.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| strength_record_id | UUID FK→strength_personal_records | CASCADE |
| exercise_key | varchar(200) | |
| exercise_name | varchar(200) | |
| rep_band_label | varchar(20) | |
| new_weight_kg | numeric(6,2) | the new record weight |
| previous_weight_kg | numeric(6,2) | nullable — prior best at the time of this achievement |
| previous_achieved_on | date | nullable |
| achieved_on | date | |
| workout_id | UUID FK→workouts | SET NULL, nullable |
| exercise_id | UUID FK→workout_exercises | SET NULL, nullable |
| set_index | int | nullable — which set within the exercise triggered the PR |
| created_at | timestamptz | |

Migration: `a1607bab81de`.

---

## strength_sessions _(added Sprint 94)_

A logged heavy-strength training session. Each row is one exercise entry; the UI groups entries by `session_date` to form a multi-exercise session view. Supports two load-capture patterns that may coexist in the same row: **sets × reps × load** (provide `sets`, `reps`, `load`) and **session-RPE × duration** (provide `session_rpe`, `duration_minutes`). CRUD via `GET/POST /api/strength-sessions`, `PUT/DELETE /api/strength-sessions/{id}`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| session_date | date | NOT NULL |
| exercise_name | varchar(200) | nullable; required by the API on create |
| sets | int | nullable; check `> 0` |
| reps | int | nullable; check `> 0` |
| load | numeric(8,2) | nullable; check `>= 0` |
| load_unit | varchar(10) | nullable; `kg` / `lbs`; check `ck_strength_sessions_load_unit_values` |
| session_rpe | int | nullable; 1–10; check `ck_strength_sessions_rpe_range` |
| duration_minutes | int | nullable; check `> 0` |
| created_at / updated_at | timestamptz | server default now() |

Index: `ix_strength_sessions_user_date` on `(user_id, session_date)`. Checks: `ck_strength_sessions_sets_positive`, `ck_strength_sessions_reps_positive`, `ck_strength_sessions_load_non_negative`, `ck_strength_sessions_rpe_range`, `ck_strength_sessions_duration_positive`, `ck_strength_sessions_load_unit_values`. Migrations: `6de228e34220` (initial table), `b1dc2caab43e` (add `exercise_name` / `load_unit`).

---

## plyo_sessions _(added Sprint 94)_

A plyometric training session with foot-contact volume tracking. Each row is one exercise entry; the UI groups entries by `session_date`. CRUD via `GET/POST /api/plyo-sessions`, `PUT/DELETE /api/plyo-sessions/{id}`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| session_date | date | NOT NULL |
| exercise_name | varchar(200) | nullable; required by the API on create |
| foot_contacts | int | NOT NULL; check `>= 0` |
| plyo_phase | varchar(20) | NOT NULL; `intro` / `build` / `maintain`; check `ck_plyo_sessions_plyo_phase_values` |
| created_at | timestamptz | nullable; server default now() |

Checks: `ck_plyo_sessions_foot_contacts_non_negative`, `ck_plyo_sessions_plyo_phase_values`. Migration: `6a4bc101eef3`.

---

## economy_ceiling_snapshots _(added Sprint 94)_

Per-user, per-date economy stimulus and lagged score-ceiling bonus, derived from `strength_sessions` and `plyo_sessions` by `backend/services/backfill_economy.py`. Idempotent upsert on `(user_id, snapshot_date)`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| snapshot_date | date | NOT NULL |
| economy_stimulus | float | NOT NULL; default 0.0; check `>= 0` |
| ceiling_bonus | float | NOT NULL; default 0.0; check `>= 0` |
| computed_at | timestamptz | server default now() |

Unique: `(user_id, snapshot_date)` (`uq_economy_ceiling_snapshots_user_date`). Index: `ix_economy_ceiling_snapshots_user_date` on `(user_id, snapshot_date)`. Checks: `ck_economy_ceiling_snapshots_stimulus_non_negative`, `ck_economy_ceiling_snapshots_bonus_non_negative`. Migration: `02ea347c3bd1`.

---

## user_banister_params _(added Sprint 96)_

Per-user fitted Banister impulse-response model parameters (τ₁, τ₂, k₁, k₂) with versioned history (`backend/services/banister_params.py`). Each fit is an immutable version snapshot — `save_banister_params` always inserts a new row and prior rows are never overwritten, giving a full audit trail of refits. Users with no stored fit fall back to population defaults (τ1=50.0, τ2=11.0, k1=1.0, k2=2.0).

| column | type | notes |
|--------|------|-------|
| id | int PK | autoincrement |
| user_id | UUID FK→users | CASCADE |
| tau1 | float | NOT NULL — fitness time constant (days) |
| tau2 | float | NOT NULL — fatigue time constant (days) |
| k1 | float | NOT NULL — fitness gain |
| k2 | float | NOT NULL — fatigue gain |
| fitted_at | timestamptz | NOT NULL |

---

## drive_sleep_connections

Per-user Google Drive OAuth connection used to pull sleep-export CSVs from a linked Drive folder (Settings → Integrations → Google Drive (Sleep)). One row per user (`user_id` unique).

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users, unique | CASCADE |
| refresh_token_encrypted | text | nullable |
| folder_id | text | nullable — Drive folder to watch |
| status | varchar(20) | NOT NULL, default `'not_connected'` |
| last_sync_at | timestamptz | nullable |
| created_at / updated_at | timestamptz | server default now() |

Migration: `6b7db3c38f43_add_drive_sleep_connections_table`.

---

## removed_activities

Tombstone for a synced Strava/Stryd activity the user removed from their log. Keyed by the external activity id so `reconcile.py` skips it on future syncs instead of recreating the workout; deleting the row (restore) lets the next reconcile rebuild it.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| source | varchar(10) | NOT NULL — `strava` \| `stryd` |
| external_id | varchar(255) | NOT NULL |
| workout_name | varchar(255) | nullable — snapshot for the Removed list |
| workout_date | date | nullable — snapshot for the Removed list |
| removed_at | timestamptz | NOT NULL, server default now() |

Unique: `(user_id, source, external_id)` (`uq_removed_activities_user_source_external`). Index: `ix_removed_activities_user` on `user_id`. Migration: `932ba10c0d09_add_removed_activities_tombstone_table`.

---

## athlete_duration_curves

Per-user cache of best-effort duration curves (best value achieved for each duration bucket, e.g. 5s/1min/5min/20min power or pace), keyed by `user_id` alone (one row per user, upserted in place as new bests arrive).

| column | type | notes |
|--------|------|-------|
| user_id | UUID PK, FK→users | CASCADE |
| curve_data | JSONB | NOT NULL, default `{}` — per-duration best-value entries (`best_value`, `workout_id`, `date`, `confidence`) |
| updated_at | timestamptz | server default now(), onupdate now() |

Migration: `kk1f2a3b4c5e_add_athlete_duration_curves_table`.

---

## summary_cache

Durable (L2) mirror of the in-memory `_SUMMARY_CACHE` (L1) in `backend/main.py`: one row per `(user_id, cache_key)`, invalidated when the stored `signature` no longer matches the recomputed signature. Persisting to Neon means a server restart (which wipes L1) doesn't force a cold recompute — the first request after restart reads straight from this table. `cache_key` values in use: `weekly`, `monthly:<...>`, `performance`.

| column | type | notes |
|--------|------|-------|
| user_id | UUID PK, FK→users | CASCADE |
| cache_key | text PK | |
| signature | text | NOT NULL |
| payload | JSONB | NOT NULL |
| updated_at | timestamptz | NOT NULL, server default now() |

Migration: `c348d3b407f6_add_summary_cache_table_for_durable_`.

---

## planned_sessions

A hand-entered planned training session for the Plan tab. Distinct from Projection's synthetic ramp/taper load model (`training_plans` / `planned_load`). Link-only: `matched_workout_id` points at the reconciled `workouts` row that fulfilled this planned session — the workout stays its own row and the Log tab is unchanged.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE; indexed |
| planned_date | date | NOT NULL; indexed |
| session_type | varchar(20) | NOT NULL — `run` \| `strength` \| `plyo` \| `rest` |
| name | varchar(200) | nullable |
| structure | JSONB | nullable — `blocks[]` for runs / `exercises[]` for strength·plyo; null for rest |
| notes | text | nullable |
| status | varchar(20) | NOT NULL, default `'planned'` — `planned` \| `missed` \| `needs_review` \| `done_auto` \| `done_manual` |
| matched_workout_id | UUID FK→workouts | SET NULL |
| created_at | timestamptz | server default now() |
| updated_at | timestamptz | nullable |

Index: `ix_planned_sessions_user_date` on `(user_id, planned_date)`. Migration: `6ce18fda0701_add_planned_sessions`.

Index: `ix_user_banister_params_user_fitted_at` on `(user_id, fitted_at)`. Migration: `5552a8d45c57`.

---

## llm_generations _(added Sprint 102)_

Durable cache for LLM-generated coaching text. One row per `(user_id, surface, input_signature)` — if a call with the same inputs is made again, the cached `payload` is returned without a new API call.

| column | type | notes |
|--------|------|-------|
| id | integer PK | autoincrement |
| user_id | UUID FK→users | CASCADE; indexed |
| surface | varchar(100) | NOT NULL — which coaching surface generated this (e.g. `readiness_explanation`, `weekly_summary`, `habit_insights`, `habit_nudges`, `plan_suggestions`) |
| input_signature | varchar(64) | NOT NULL — SHA-256 hex digest of the canonical input dict |
| payload | JSONB | NOT NULL — full LLM response payload |
| model | varchar(100) | NOT NULL — model id used (e.g. `llama-3.1-8b-instant`) |
| created_at | timestamptz | server default now() |

Unique: `(user_id, surface, input_signature)` (`uq_llm_generations_user_surface_sig`). Indexes: `ix_llm_generations_user_id` on `user_id`; `ix_llm_generations_user_surface_sig` on `(user_id, surface, input_signature)`. Migration: `54c084f3e59f_add_llm_generations_table`.

---

## verdict_history _(added Sprint 103)_

Durable snapshot of each day's training verdict and the inputs that produced it. Written (upserted, one row per `(user_id, verdict_date)`) whenever the verdict is computed for the *current* calendar day — historical dates are never overwritten. Lets the app record what it advised vs. what happened. Read via `GET /api/training/verdict-history?from=&to=`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| verdict_date | date | NOT NULL |
| verdict | varchar(20) | NOT NULL — `back_off` / `hold` / `build` |
| modifiers | jsonb | nullable — list of `{rule, value}` downgrade rules that fired (verdict v2) |
| readiness | float | nullable — today's readiness score at compute time |
| ctl | float | nullable |
| atl | float | nullable |
| tsb | float | nullable |
| acwr | float | nullable |
| created_at | timestamptz | server default now() |

Unique: `(user_id, verdict_date)` (`uq_verdict_history_user_date`). Index: `ix_verdict_history_user_date` on `(user_id, verdict_date DESC)`. Migration: `bf3b956dd2e0_add_verdict_history_table`.

---

## injury_log _(added Sprint 103 / #1350, migration only)_

Injury / illness / niggle tracking. The table migration landed this sprint to back verdict v2's active-injury downgrade rules (#1351 reads active rows — `ended_on IS NULL` — defensively). The full feature (ORM model, API, quick-log UI) is not yet built, so there is **no `InjuryLog` model in `backend/models.py`** yet.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| kind | varchar(20) | NOT NULL — `injury` / `illness` / `niggle` (check constraint) |
| body_area | varchar(100) | nullable |
| severity | int | NOT NULL — 1 / 2 / 3 (check constraint) |
| started_on | date | NOT NULL |
| ended_on | date | nullable; must be `>= started_on` when set (check constraint) |
| notes | text | nullable |
| created_at | timestamptz | server default now() |

Index: `ix_injury_log_user_started_on` on `(user_id, started_on)`. Migration: `1da954a27351bb1b_add_injury_log_table`.

---

## body_measurements _(added Sprint 104.2 / #1358)_

Periodic body-composition measurements (waist circumference and/or body-fat %). Captured via `POST/GET/PATCH/DELETE /api/body-measurements` (CSV export at `GET /api/exports/body-measurements`). Backs the lean-mass-driven protein target and cut guard (#1359): `current_lean_mass_kg` reads the latest `body_fat_pct` within 60 days to derive lean mass (`ewma_weight × (1 − bf%)`, source `measured`). Model: `BodyMeasurement` in `backend/models.py`.
## prediction_snapshots _(added Sprint 105 / #1362)_

Daily persisted projection forecast, kept for forecast-vs-actual accuracy evaluation. Written on the first projection computation of the day (`GET /api/plan/projection`); later same-day recomputes are no-ops (`ON CONFLICT DO NOTHING`), so the morning forecast is preserved. Read via `GET /api/projection/snapshots?from=&to=`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| measure_date | date | NOT NULL |
| waist_cm | numeric(5,1) | nullable |
| body_fat_pct | numeric(4,1) | nullable |
| source | varchar(20) | NOT NULL, default `'manual'` — `manual` / `imported` (check constraint `ck_body_measurements_source`) |
| notes | text | nullable |
| created_at | timestamptz | NOT NULL, server default now() |

Unique: `(user_id, measure_date)` (`uq_body_measurements_user_date`). Index: `ix_body_measurements_user_date` on `(user_id, measure_date)`. Migration: `da7cbe58ec60_add_body_measurements_table`.
| snapshot_date | date | NOT NULL |
| payload | jsonb | NOT NULL — per-race predicted finish times (with race ids), projected CTL at race date, peak CTL + peak week, `formula_version` |
| created_at | timestamptz | server default now() |

Unique: `(user_id, snapshot_date)` (`uq_prediction_snapshots_user_date`). Index: `ix_prediction_snapshots_user_date` on `(user_id, snapshot_date)`. Migration: `cea323ec2396_add_prediction_snapshots`.

---

## performance_score_history _(added Sprint 105 / #1361, #1365)_

Durable daily endurance/speed scores with formula-version stamps. Upserted (write-through) each time `GET /api/athletes/{id}/performance` computes scores, so there is a persisted absolute-scale series to compute block deltas from rather than the in-request relative `trend[]`. Read via `GET /api/performance/score-history?from=&to=` (defaults to the last 90 days); only rows matching the current formula version are returned so the caller never sees a mixed-version series.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| score_date | date | NOT NULL |
| endurance | float | nullable |
| speed | float | nullable |
| formula_version | text | NOT NULL |
| created_at | timestamptz | server default now() |

Unique: `(user_id, score_date, formula_version)` (`uq_performance_score_history_user_date_version`). Index: `ix_performance_score_history_user_date` on `(user_id, score_date)`. Migration: `129d863fa625_add_performance_score_history`.

---

## run_form_metrics _(added Sprint 106 / #1368)_

Per-run Stryd running-dynamics extracted from `stryd_activities.form_metrics` JSONB into a queryable, one-row-per-activity table. Upserted incrementally on every Stryd sync (`backend/services/sync_runner.py`) and via full historical backfill on the compute worker (`POST /internal/form-metrics/backfill`, job type `form_metrics_backfill`). Read via `GET /api/training/form-metrics?from=&to=` (per-run series + 28-day trailing rolling means). Model: `RunFormMetrics` in `backend/models.py`. Key mapping: `form_metrics["ground_contact_time_ms"]→gct_ms`, `["leg_spring_stiffness"]→lss_kn_m` (kN/m native), `["vertical_oscillation_cm"]→vertical_oscillation_cm`, `["cadence_spm"]→cadence_spm`, `stryd_activities.avg_power_w→power_w`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| workout_id | UUID FK→workouts | nullable, SET NULL |
| stryd_activity_pk | UUID FK→stryd_activities | NOT NULL, CASCADE |
| run_date | date | NOT NULL |
| gct_ms | numeric(8,2) | nullable — ground-contact time (ms) |
| lss_kn_m | numeric(8,4) | nullable — leg-spring stiffness (kN/m) |
| vertical_oscillation_cm | numeric(6,2) | nullable |
| cadence_spm | numeric(6,2) | nullable |
| power_w | numeric(6,1) | nullable |
| created_at | timestamptz | NOT NULL, server default now() |

Unique: `(stryd_activity_pk)` (`uq_run_form_metrics_stryd_activity_pk`). Index: `ix_run_form_metrics_user_run_date` on `(user_id, run_date)`. Migration: `3bd978fbbf19_add_run_form_metrics_table`.

---

## muscle_load_daily _(added Sprint 106 / #1367)_

Per-day TSS-weighted training load per muscle group per source, the ledger backing the muscle-load ACWR machinery. Written recompute-idempotently by `backend/services/muscle_load.py` `recompute_strength_load_for_date` (deletes existing rows for the `(user, date, source)` triple then re-inserts, so re-running never double-counts); triggered after every strength workout/session create/update/delete. Read (aggregated) via `GET /api/training/muscle-load?weeks=` — per-group acute 7d / chronic 28d / ACWR / classification, computed by `backend/services/muscle_load_acwr.py`. Model: `MuscleLoadDaily` in `backend/models.py`. Formula reference: `docs/calculations/muscle-load.md`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| load_date | date | NOT NULL |
| muscle_group | varchar(30) | NOT NULL |
| load | numeric(10,4) | NOT NULL |
| source | varchar(20) | NOT NULL — `strength` / `run` / `plyo` (check constraint `ck_muscle_load_daily_source`) |
| created_at | timestamptz | NOT NULL, server default now() |

Unique: `(user_id, load_date, muscle_group, source)` (`uq_muscle_load_daily_user_date_group_source`). Index: `ix_muscle_load_daily_user_date` on `(user_id, load_date)`. Migration: `a4cf1cbd5020_add_muscle_load_daily_table`.

---

## gap_findings _(added Sprint 107 / #1370)_

One persistent row per `(user_id, week_start, code)` emitted by the gap-analyzer rules engine (`backend/services/gap_analysis/`). Each row is a prioritized "what to improve" finding for a given ISO week. Written by `run_gap_analysis` on every call to `GET /api/training/gap-analysis`, which **upserts** on the unique key — `severity` / `recommendation` / `evidence` / `target` / `computed_at` are refreshed, but `status` is **preserved** so an athlete-accepted or dismissed finding survives recomputes. Athlete feedback (`POST /api/training/gap-analysis/{code}/status`, Sprint 108 / #1377) sets `status` and stamps the suppression columns below; the GET then partitions findings into visible / `muted` via `backend/services/gap_analysis/suppression.py`. Model: `GapFinding` in `backend/models.py`. Contract/formula reference: `docs/calculations/gap-analysis.md`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| week_start | date | NOT NULL — ISO Monday of the week the finding was computed for |
| code | varchar(80) | NOT NULL — stable rule id (e.g. `no_recent_plyo`, `intensity_too_hard`) |
| severity | int | NOT NULL — `1`=note / `2`=recommend / `3`=priority (check constraint `ck_gap_findings_severity`) |
| recommendation | text | NOT NULL — short imperative sentence for the athlete |
| evidence | jsonb | NOT NULL — list of `{metric, value, threshold, window}` objects |
| target | varchar(100) | nullable — muscle group or session type addressed |
| computed_at | timestamptz | NOT NULL — when the engine ran |
| status | varchar(20) | NOT NULL, default `'active'` — `active` / `accepted` / `dismissed` (check constraint `ck_gap_findings_status`) |
| dismissed_at | timestamptz | nullable — when the athlete dismissed this finding (Sprint 108 / #1377) |
| dismissed_severity | int | nullable — severity captured at dismissal; a later recompute at higher severity can re-surface the finding (Sprint 108 / #1377) |
| accepted_at | timestamptz | nullable — when the athlete accepted this finding (Sprint 108 / #1377) |
| accepted_evidence_hash | varchar(64) | nullable — hash of the evidence at accept time; the finding stays muted while the hash still matches (Sprint 108 / #1377) |
| created_at | timestamptz | NOT NULL, server default now() |

Unique: `(user_id, week_start, code)` (`uq_gap_findings_user_week_code`). Index: `ix_gap_findings_user_week_start` on `(user_id, week_start)`. Migrations: `2bbdfbb8ea10_add_gap_findings_table`, `8d14fe27be6b_add_suppression_columns_to_gap_findings`.

## performance_goals _(added Sprint 113 / #1501)_

One race goal per user; at most one active at a time. Managed by `backend/routers/coach.py`: `GET /api/coach/goal` returns the active goal, `PUT /api/coach/goal` deactivates the current active goal and inserts the new one. Model: `PerformanceGoal` in `backend/models.py`. Consumed by the coach-plan projection engine (`coach_projection.py`).

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| race_distance | varchar(20) | NOT NULL — `5k` / `10k` / `half` / `marathon`; check constraint `ck_performance_goals_race_distance_values` |
| target_time | int | NOT NULL — target finish time in seconds (validated > 0) |
| race_date | date | NOT NULL — validated as a future date on write |
| created_at | timestamptz | server default now() |
| active | bool | NOT NULL, default true — only one active goal per user (older goals set inactive on `PUT`) |

Index: `ix_performance_goals_user_id` on `(user_id)`. Migration: `f5413962c763_add_performance_goals_table`.

## weekly_coach_messages _(added Sprint 113 / #1504)_

One persisted weekly coaching message per `(user_id, for_week)` ISO week. Generated by `backend/services/weekly_coach_message.py` from `coach_plan.build_plan_state()` + projection outputs (deterministic text, optionally rephrased by an LLM warmth layer that falls back silently). The unique constraint enforces idempotency — re-running the weekly job for the same ISO week upserts the existing row. Read via `GET /api/coach/weekly-message` (latest) and `GET /api/coach/weekly-messages?limit=` (history, newest-first). CLI: `scripts/run_weekly_coach.py`. Model: `WeeklyCoachMessage` in `backend/models.py`.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| user_id | UUID FK→users | CASCADE |
| for_week | varchar(8) | NOT NULL — ISO week string `YYYY-Www` |
| generated_at | timestamptz | NOT NULL, server default now() |
| text | text | NOT NULL — composed weekly coaching message |
| plan_state_snapshot | jsonb | nullable — engine plan-state snapshot the message was built from |

Unique: `(user_id, for_week)` (`uq_weekly_coach_messages_user_week`). Index: `ix_weekly_coach_messages_user_generated_at` on `(user_id, generated_at)`. Migration: `5b2f59e19e14_add_weekly_coach_messages_table`.
