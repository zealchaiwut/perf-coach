# Strava + Stryd → Unified Workout Sync

_Plan captured 2026-06-17. Build order, gaps, what is overnight-sprintable._

## Goal

Sync both Strava and Stryd into the DB for a real user, reconcile the same run
into one workout, verify via API, redesign + build the run-workout screen,
compute TSS, and surface Zone-2 minutes into the habits graph against a weekly
target.

## Current state (2026-06-17)

| Capability | Status |
|---|---|
| Strava OAuth + capture (detail/streams JSONB) | ✅ built (PR #565) |
| Stryd connect / status / disconnect (encrypted creds) | ✅ built |
| Stryd `athlete_id` type (UUID string, was BigInteger) | ✅ fixed (migration `cc3d4e5f6a7b`) |
| **Stryd activity PULL/sync** | ✅ built — `stryd_sync.py`, `POST /api/stryd/sync`, verified live (184 activities) |
| Stryd sync history + data-quality endpoints | ✅ built (`/api/sync/stryd/latest`, `/api/sync/stryd/data-quality`) |
| Reconcile (link strava+stryd → 1 workout, ±5 min) | ✅ built, proven on live data (183 linked) |
| `GET /api/workouts/{id}/full` union JSON | ✅ built (PR #565) |
| TSS engine (`tss.py`) | ✅ exists; Stryd `stress` flows through reconcile. Compute fallback needs athlete thresholds |
| `zone2_minutes` → habits plumbing | ✅ exists; Stryd gives `seconds_in_zones` per activity |
| **zone2_minutes COMPUTE** | ❌ not wired from synced data yet |
| Workout detail UI consuming `/full` | ❌ panel renders core only |

## Stryd API — verified live (2026-06-17)

- Signin: `POST https://www.stryd.com/b/email/signin` → `{token, id (UUID), user_name, …}`.
- Calendar: `GET https://www.stryd.com/b/api/v1/users/{athlete_id}/calendar?srtDate=MM-DD-YYYY&endDate=MM-DD-YYYY`
  → `{"activities": [ … ]}`.
- Real field names: id (int64), `average_power`, `average_heart_rate`, `stress`
  (= TSS), `average_leg_spring`, `average_ground_time`, `average_oscillation`,
  `average_cadence`, `average_vertical_ratio`, `average_stride_length`, `ftp`
  (= critical power), `zones[]`, **`seconds_in_zones`** (time-in-zone), `lap_events`,
  and full per-point `*_list` streams (HR/power/GPS/cadence/…).
- Per-point `*_list` arrays are stripped from the cached `raw_payload` (re-fetchable);
  summary + zones + seconds_in_zones + laps + form are kept.

## Remaining build, mapped to the 6 goals

- ① Sync — ✅ done (Strava + Stryd both pull; UI Sync buttons + log pane).
- ② Reconcile → one workout — ✅ done.
- ③ Verify via API — ✅ `/full`.
- ④ Run-workout screen consuming `/full` — together + design (laps, splits,
  HR/pace/power charts, GPS map, Stryd dynamics).
- ⑤ TSS — wire `tss.py` into reconcile (Stryd `stress` → power → pace → HR →
  duration). Needs athlete thresholds (FTP/CP, threshold HR/pace, max HR).
- ⑥ Zone-2 → habits — compute `zone2_minutes` (Stryd `seconds_in_zones` or HR
  stream). Needs weekly target design.

## Overnight-sprintable vs together

Together first: detail-screen design+wire (④), threshold + weekly-target design (⑤⑥).
Overnight sprint (after decisions): TSS auto-compute + tests (⑤), zone2 compute +
tests (⑥), habits weekly-target surfacing, reconcile dedup hardening.

## Decisions needed before sprint
1. Thresholds: FTP/critical power, threshold HR, max HR, threshold pace → `athlete_settings`.
2. Weekly Zone-2 target: number + where set + graph treatment.
3. TSS precedence when Stryd disagrees with computed (assumed Stryd wins).
