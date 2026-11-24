# PWA phase 5: body (weigh-in, trend weight, Zone 2)

**Date:** 2026-11-24
**Sprint label:** sprint-154
**Default labels:** pwa, pwa-phase-5, manual
**Status:** posted

## Context

Phase 5 adds a light body tracker to the phone:

- a one-tap weigh-in that works offline;
- the smoothed trend weight with a 4-week change;
- Zone 2 minutes this week against a target.

It shows as a card on Today (/m/today) and a Body screen (/m/body). This is a tracker, not a weight programme. Builds on Phases 0–2.

Mocks: `docs/pwa/mocks/source/` (390x844).

**Implementation note:** issues are implemented manually in Cursor, not by Commander agents. Each issue body is the Cursor prompt. The `manual` label marks them as hand-implemented; Commander only dispatches tickets passed to it explicitly, so do not include them in a dispatch call.

**Conventions:**
- The mock owns layout; the issue owns rules.
- One reader per number: trend weight comes only from `weight_ewma` (the same reader power-to-weight uses); Zone 2 minutes come only from `workouts.easy_minutes` (time at or below the Zone 2 HR ceiling); no second calculation on the phone, except a clearly marked local estimate for an unsynced weigh-in.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (notes added in the issue bodies where reality differs):
- P5-1: `body_log_store.py` exists; the weigh-in writer is `patch_body_log(session, user_id, metric_date, weight_kg=...)`, which upserts a `WeightEntry`. `weight_ewma.py` exists with `compute_ewma`; power-to-weight reads trend mass through `axis_strength.fetch_trend_mass` and `trend_mass_from_entries`. `body_log_weight_card.py` exists (`weight_card_payload`, served by `GET /api/home/weight-card`). `Body.dc.html` exists.
- P5-2: `Workout.easy_minutes` exists (Integer, nullable). A separate `Workout.zone2_minutes` column also exists; the issue keeps `easy_minutes` as the only reader. A weekly Zone 2 target preference already exists as `UserPreferences.weekly_zone2_target_min` (default 150 in `main.py`), so the new `zone2_weekly_target_min` is not needed: reuse the existing field. The Zone 2 HR ceiling preference is `zone2_hr_max` (with `zone2_hr_min`).

## Issues

### PWA5-1

```
Title: [PWA P5-1] Offline weigh-in and trend weight in the bundle

Mock
docs/pwa/mocks/source/Body.dc.html (weigh-in card and trend chart).

Scope
- Backend:
  - support the weigh_in op in POST /api/mobile/sync (date, kg; one per date, the newest wins), writing through the existing body log store (body_log_store or its current equivalent);
  - bundle.body gains trend_kg (from weight_ewma), change_28d_kg, last_weigh_in (date, kg) and the last 56 days of weigh-ins plus trend points for the chart.
- Body screen /m/body:
  - Weigh-in card: the date and a timing hint (morning, after the toilet); a large stepper in 0.1 kg steps starting from the last weigh-in; tap the number to type; Save weigh-in, which queues the op.
  - Trend card: an 8-week chart with dots for weigh-ins and a line for the trend, plus the current trend and the 4-week change (green when down, neutral otherwise; no judgement copy).
- Deep link /m/body/weigh-in focuses the stepper.
- After an offline save, show the new dot at once and mark the trend est. until the next bundle brings the server trend.
- Note: the weigh-in writer is patch_body_log in backend/services/body_log_store.py (upserts a WeightEntry per date). weight_ewma.py exposes compute_ewma; power-to-weight reads trend mass through axis_strength.fetch_trend_mass. body_log_weight_card.py (weight_card_payload) already builds a weight card for GET /api/home/weight-card.

Acceptance criteria
- A weigh-in saved offline appears at once and syncs later as one op.
- A second weigh-in on the same date replaces the first.
- Bundle trend_kg equals weight_ewma for the fixture user (pytest).
- Power-to-weight still reads the same trend (no regression test failures).

Depends on: PWA0-3, PWA0-4, PWA1-3
```

### PWA5-2

```
Title: [PWA P5-2] Zone 2 minutes this week with a target

Mock
docs/pwa/mocks/source/Body.dc.html (Zone 2 card) and the Body card in Main.dc.html.

Scope
- New preference: zone2_weekly_target_min (default 150), editable in Settings › Profile.
- bundle.body gains zone2_week: per day of the current Bangkok week, logged minutes from workouts.easy_minutes; planned easy-run minutes for the remaining days (from planned sessions); total and target.
- Body screen Zone 2 card:
  - the total over the target in mono;
  - 7 day bars (logged solid navy, planned dashed, no-run days a stub) with M–S labels;
  - a caption naming the HR ceiling in use (from user preferences) and that minutes come from synced runs.
- Today Body card (PWA P2-1 placeholder): trend weight with its 4-week change, and Zone 2 this week over the target with a thin progress bar. Weigh in › links to /m/body/weigh-in.
- Note: a weekly Zone 2 target preference already exists as UserPreferences.weekly_zone2_target_min (default 150 in backend/main.py), so reuse it instead of adding zone2_weekly_target_min, and keep its name. The HR ceiling preference is zone2_hr_max. workouts.easy_minutes exists; a separate workouts.zone2_minutes column also exists, but use only easy_minutes here.

Acceptance criteria
- Zone 2 totals equal the sum of easy_minutes for the week (pytest).
- Planned minutes show dashed and don't count in the total.
- Changing the target updates the next bundle.
- The Today card hides cleanly when there is no weight data and no runs.

Depends on: PWA5-1, PWA2-1
```
