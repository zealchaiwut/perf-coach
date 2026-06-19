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

Unique: `(user_id, entry_date, entry_time)` (nulls not distinct).

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

## habits _(updated Sprint 50)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| name | varchar(200) | |
| description | text | nullable |
| tracking_type | varchar(50) | `daily_checkmark` / `weekly_count` / `minutes` / `quantity` |
| weekly_target | numeric(10,2) | nullable — target value for the week |
| unit | varchar(50) | nullable — display unit (e.g. `min`, `reps`) |
| auto_fill_source | varchar(100) | nullable — e.g. `zone2_minutes` to auto-fill from workouts |
| icon | varchar(100) | nullable |
| color | varchar(20) | nullable |
| sort_order | int | default 0 |
| is_archived | bool | default false |
| created_at | timestamptz | |
| updated_at | timestamptz | nullable |
| display_order | int | legacy compat column |
| archived_at | timestamptz | legacy compat column |

---

## habit_logs _(updated Sprint 50)_

One row per log event. For `daily_checkmark` habits, one row per day (value=1). For other tracking types, rows are summed over `log_week_start` to compute weekly progress.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| habit_id | UUID FK→habits | CASCADE |
| user_id | UUID FK→users | CASCADE |
| log_date | date | |
| log_week_start | date | Monday of the week (Asia/Bangkok) |
| value | numeric(10,4) | default 1 |
| notes | text | nullable |
| source | varchar(50) | `manual` / `workout_save` / `auto_fill` / `manual_override` |
| created_at | timestamptz | |
| updated_at | timestamptz | nullable |

Unique: `(habit_id, log_date)`. Index: `(habit_id, log_week_start)`.

---

## workouts _(zone2_minutes added Sprint 50; tss_method added Sprint 64)_

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

## workout_splits _(lap_type added Sprint 63)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| workout_id | UUID FK→workouts | CASCADE |
| split_index | int | |
| distance_km | numeric(6,3) | |
| duration_seconds | int | |
| avg_hr | int | nullable |
| avg_power | int | nullable |
| cadence_spm | int | nullable |
| stride_length_m | numeric(4,2) | nullable |
| lap_type | varchar(10) | nullable; `auto` (1-km auto-split) or `manual`; default `auto` |
| created_at / updated_at | timestamptz | |

Unique: `(workout_id, split_index)`.

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

Computed from `daily_metrics` via `POST /api/readiness/compute`.

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

## user_preferences _(updated Sprint 66; source columns added Sprint 65)_

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE, unique |
| ftp_w | int | nullable |
| ftp_w_source | varchar(30) | nullable; `user_accepted` or `manual`; tracks how the threshold was set |
| threshold_hr | int | nullable |
| max_hr | int | nullable — max heart rate (bpm); default 190 when null |
| threshold_hr_source | varchar(30) | nullable; `user_accepted` or `manual` |
| threshold_pace_seconds_per_km | int | nullable |
| threshold_pace_seconds_per_km_source | varchar(30) | nullable; `user_accepted` or `manual` |
| zone2_hr_min | int | nullable — Zone 2 lower HR bound; default 130 when null |
| zone2_hr_max | int | nullable — Zone 2 upper HR bound; default 155 when null |
| weekly_zone2_target_min | int | nullable — weekly Zone 2 minutes goal; default 150 when null |
| preferred_units | varchar(20) | `metric` (default) |
| timezone | varchar(100) | default `Asia/Bangkok` |
| week_start_day | int | default 1 (Monday) |
| display_name | varchar(100) | nullable |
| date_format | varchar(20) | default `YYYY-MM-DD` |
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

## stryd_activities _(streams_payload added Sprint 63)_

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
| computed_at | timestamptz | |

Unique: `(user_id, snapshot_date)`.

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

## google_oauth_credentials

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

## races _(added Sprint 67; race_type added Sprint 69)_

User target race entries. `goal_pace_seconds_per_km` is derived from `goal_time_seconds / distance_km` at write time.

| column | type | notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users | CASCADE |
| name | varchar(200) | |
| race_date | date | |
| distance_km | numeric(8,3) | >0 |
| goal_time_seconds | int | nullable; >0 |
| goal_pace_seconds_per_km | int | nullable; derived from goal_time_seconds / distance_km |
| priority | varchar(10) | `A` / `B` / `C` |
| status | varchar(20) | `planned` / `done` / `abandoned` |
| race_type | varchar(20) | `race` / `checkpoint`; default `race` — distinguishes A-race targets from intermediate checkpoints |
| created_at | timestamptz | |
| updated_at | timestamptz | nullable |

Index: `ix_races_user_id`. Migrations: `ll2a3b4c5d6e` (initial), `mm3c4d5e6f7g` (race_type column), `nn4d5e6f7g8h` (merge head).
