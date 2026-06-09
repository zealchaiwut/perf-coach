# User Settings

The Settings page (`/settings`) is the central place where users configure their profile,
performance thresholds, personal records, and third-party integrations.

## Sidebar Sections

### Profile
Displays and edits the user's basic information: display name, timezone, and week start day.
Changes are persisted immediately via `PATCH /api/user-preferences`.

### Performance Thresholds
Stores the physiological baselines used in TSS (Training Stress Score) calculations:

| Field | Description | Range |
|-------|-------------|-------|
| FTP (W) | Functional Threshold Power in watts | 50–600 |
| Threshold HR | Heart rate at lactate threshold (bpm) | 100–220 |
| Threshold pace | Pace at lactate threshold (seconds/km) | 180–540 |

**How thresholds affect TSS calculations:** The backend service (`backend/services/tss.py`)
reads `ftp_w` from `user_preferences` when computing normalized power and intensity factor
for ride activities. If `ftp_w` is null the service falls back to a global default of 280 W.
Similarly, `threshold_hr` and `threshold_pace_seconds_per_km` drive HR-based and
pace-based TSS estimation for run and cardio activities.

Setting accurate thresholds ensures the readiness score, training load, and TSB
(Training Stress Balance) charts reflect real physiological stress rather than default estimates.

### Personal Records
Tracks best-ever performances across canonical athletic disciplines:

- **Running:** Half Marathon, Marathon, 10K, 5K
- **Strength:** Squat 1RM, Deadlift 1RM, Bench Press 1RM, Overhead Press 1RM
- Custom tracks are supported via a free-text "Other" option.

Records are stored in the `personal_records` table (one row per PR entry, multiple entries
per track to capture progression history). The Performance widget on `/home` reads the most
recent entry per track and compares it against workout history to show improvement.

### Integrations
Connect third-party services to automatically pull workout data:

- **Strava** (OAuth 2.0): Connects via `/api/strava/connect`. Once linked, the sync button
  in the training log triggers a background job that pulls ride/run activities.
- **Stryd** (credential-based): Connects via `/api/stryd/connect` using an encrypted
  API key (Fernet). Pulls running power data.

Disconnect is available via the respective "Disconnect" buttons, which call
`DELETE /api/strava/disconnect` or `DELETE /api/stryd/disconnect`.

### About
Shows app version, environment (UAT/PRD), and basic documentation links.

## Future Planned Additions

The following features are planned but not yet implemented:

- **Google OAuth** (`/api/google/connect`): OAuth 2.0 login via Google for passwordless
  authentication. The OAuth flow and callback handler exist in `main.py` but are gated
  behind the `GOOGLE_OAUTH_ENABLED` env flag (off by default).
- **Unit preferences:** Toggle between metric (kg, km, watts) and imperial (lb, mi) display
  across all dashboard pages.
- **Avatar upload:** Profile photo upload to replace the initials avatar. The
  `GET/PUT /api/users/{id}/avatar` endpoints exist; the settings UI upload form is pending.

## Navigation

From any page, the gear icon (⚙) in the top navigation bar right-actions area links to
`/settings`. The Personal Records widget on `/home` also links directly to
`/settings#personal-records`, and a contextual banner on `/home` links to
`/settings#thresholds` when any threshold field is unset.
