# Integrations Architecture

## Data Model Overview

### Cache Tables

**`strava_activities`** — raw activity records fetched from the Strava API.
Each row corresponds to one Strava activity. Fields include `strava_activity_id`, `start_time`, `activity_type`, `name`, `distance_km`, `duration_seconds`, `avg_hr`, `max_hr`, `elevation_m`, `avg_power_w`, `max_power_w`, `device_name`, `external_id`, `is_stryd_synced`, and `raw_payload` (full Strava API response as JSONB).

**`stryd_activities`** — raw activity records fetched from the Stryd API.
Each row corresponds to one Stryd activity. Fields include `stryd_activity_id`, `start_time`, `name`, `distance_km`, `duration_seconds`, `avg_power_w`, `avg_hr`, `tss`, `form_metrics`, `power_zones`, `splits`, and `raw_payload`.

Both tables are **append-only caches** — they are never used as the source of truth for display. The `workouts` table is the unified view.

### Unified View: `workouts`

`workouts` is the canonical table for all training data regardless of source. Each workout row may carry foreign-key references to both cache tables:

- `strava_activity_pk` → `strava_activities.id` (nullable, `ON DELETE SET NULL`)
- `stryd_activity_pk` → `stryd_activities.id` (nullable, `ON DELETE SET NULL`)

These FKs allow joining back to raw provider data but are not required for display. A workout can exist with neither FK (manually entered) or with one or both FKs (synced from integrations).

### `source` Field Semantics

The `source` column on `workouts` records which integration(s) contributed data:

| Value | Meaning |
|---|---|
| `manual` | Entered manually, no integration data |
| `strava` | Imported from Strava only |
| `stryd` | Imported from Stryd only |
| `strava,stryd` or `stryd,strava` | Merged from both providers |

## `compute_best_values` Priority Order

When a workout has data from both Stryd and Strava, `compute_best_values` (in `backend/services/workout_merge.py`) resolves conflicts using the following priority:

1. **Power** (`avg_power_w`) — Stryd is authoritative (running pod measures directly)
2. **TSS** — Stryd preferred when available; falls back to workout-level `tss` field
3. **Distance / Duration / HR** — Stryd preferred; falls back to Strava; falls back to workout-level fields
4. **Name** — Stryd name preferred when present; falls back to Strava; falls back to manual `workouts.name`

`manual_overrides` (JSONB column on `workouts`) can override any computed field on a per-workout basis.

## Deduplication

Activities from Strava and Stryd are matched using a **±5-minute start-time tolerance**. If a Strava activity and a Stryd activity have `start_time` values within 5 minutes of each other, they are considered the same physical workout and merged into a single `workouts` row with both `strava_activity_pk` and `stryd_activity_pk` populated.

Activities outside the 5-minute window are treated as separate workouts.

## Connection / Credential Storage

- `strava_tokens` — OAuth tokens for Strava (one row per user). Includes `access_token`, `refresh_token`, `expires_at`, `scope`, and `athlete_data`.
- `stryd_credentials` — Stryd email/password (Fernet-encrypted) and active session token (one row per user).

See `strava.md` and `stryd.md` for setup instructions.
