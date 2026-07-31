# Pre-production review — status

Working doc for the S1–S6 programme (#1600–#1606) that came out of the
ten-agent review. Tracks what is usable today, what shipped, and what is left.

**Branch:** `develop`. Nothing here has been merged to `master`.
**Last updated:** 2026-08-01, end of session.

---

## 1. What you can do right now

All three scenarios work. Verified live against the UAT Neon database with the
real `zeal` account — 26 of 27 endpoints returned 200, and the one that didn't
was a POST-only route probed with a GET, not a defect.

| Scenario | State | Evidence |
|---|---|---|
| **1 — track + sync** | works | 9/9 endpoints; Strava **and** Stryd both report `connected: true` |
| **2 — plan the week** | works | `/api/plan/computed`, `week-load`, `draft-status`, `planned-sessions`, `preferences`, CTL/ATL/TSB all live |
| **3 — paste loop + guardrails** | works | paste export renders **26,254 chars**, every schema-v4 block present |

`goal_habits` and `evidence` are in the export, nested under `habits` rather
than at the top level.

### What is blocking *you*, not the code

Three fields shipped this week have **zero rows**:

```
workouts with fuelled set      0   (of 1030 workouts)
drills_minutes set             0
weight_entries with body_fat   0
```

So the habit-evidence block returns `[]`. That is correct behaviour —
`build_user_evidence` returns only *readable* comparisons, because saying "not
enough data yet" three times is worse than silence. It fills in once there are
a few fuelled and unfuelled long runs to compare.

Also live: `tracking.state = "paused"`, last weigh-in **2026-07-22**. The app is
correctly quiet. The cut guardrails need weigh-ins before they say anything.

**Sleep import is dormant by design.** It stays off until
`HEALTH_SYNC_DRIVE_FOLDER_ID` is set to your Health Sync export folder — see
§3.4.

---

## 2. Shipped this session (merged to `develop`)

| PR | What |
|---|---|
| #1620 | S2 mechanical remainder — avatar auth, feel-date parity, one pace calc, phantom endpoint removed from docs |
| #1621 | S1 — Bangkok time explicit in backend code, plus the lint rule that keeps it |
| #1623 | #1622 — session auth declared via `Depends`, not called inline |
| #1624 | S4 — one escaper and one "today" for the whole frontend |
| #1625 | S3 part 1 — sleep import connected to the parser that already existed |

### Things that turned out bigger than the tickets said

Worth knowing, because the same undercount is likely elsewhere:

- **#1622 was 4 routers, not 1** — and the OpenAPI half of the ticket was wrong.
  Converting to `Depends` did *not* make auth visible, because `resolve_user`
  reads `request.cookies` by hand. **Every** authenticated route in the app read
  as public in `/openapi.json`, not just the 30 inline ones. Fixed app-wide with
  a declared `APIKeyCookie` scheme. This matters for §3.5: the reachability gate
  inspects the running app, and would have been handed ~300 false
  "unauthenticated" endpoints.

- **S4 was 28 escaper definitions, not 17**, and **11 files** asking the device
  what day it is, not 2. Two were genuine holes: `training.js`'s `escapeAttr`
  did not escape `&` at all (a stored `&lt;script&gt;` rendered as a live tag),
  and several used `toISOString()`, which is UTC and so reported *yesterday*
  during Bangkok mornings.

- **S1's AST-based ratchet found 8 sites every previous grep sweep missed**, all
  behind local aliases (`_date_cls`, `_d2`, `_d`). Two sit in the weekly verdict
  path; one decides Strava lookback depth.

The pattern: greps undercount, ratchet tests find the rest. Write the test
first next time.

---

## 3. What is left

Ordered as intended. Decisions already taken are recorded so tomorrow does not
re-litigate them.

### 3.1 — S3 remainder (#1602) ← resume here

The reachability sweep. Each item below re-verified today, not taken from the
ticket.

**The what-if button is a decoy.** `weight.js:401` — `#whatif-open-btn` just
unhides the edit panel and focuses the goal-weight input. `/api/weight-targets/
{goal_id}/what-if` is fully implemented and tested with **zero** frontend
callers. Worse than missing: the user clicks a button labelled for a simulation
and silently gets the ordinary edit-goal form.

**Two endpoints have no caller** (both confirmed zero frontend references):
- `GET /api/weight-targets/arrival-projection` — projected arrival date, backed
  by `goal_arrival.py`, tested by `test_arrival_projection_endpoint__878.py`
- `GET /api/adherence-nudges` — slipping-habit detection, backed by
  `habit_nudges.py` + `habit_adherence.py`

**Four pages have no entry point.** Measured by cross-referencing registered
routes against `nav.js`'s `LINKS` *and* every `href` in the frontend:

```
/preferences     (redirect shim → /training-log?tab=plan#prefs — arguably fine)
/projection
/strength-view
/weight/targets
```

`/run-builder` and `/run-view` are reachable via in-page links, so they are not
orphaned despite being absent from the nav.

### 3.2 — S5 schema consolidation (#1604)

Decisions taken:

| Item | Decision |
|---|---|
| `habits.habit_type` vs `tracking_type` | **Derive `habit_type` from `tracking_type` at write.** `tracking_type` is the survivor — it carries all behaviour. Backfill existing rows. No API break. |
| `weight_targets` vs `weight_plans` | **Merge into one table with a `phase` column.** The larger of the two options; rewrites both API surfaces, both repos, and every consumer (`coach_export`, `coach_facts`, `goal_arrival_caller`, `fuel`, `cut_review`). |
| `fuel_settings.lean_mass_kg` | not yet decided — keep as a labelled manual override, or drop and always derive |
| Two lean-mass derivations reaching `coach_export` | not yet decided |

### 3.3 — Unify the three "current weight" algorithms

Decision taken: **unify on `_weight_rollup`'s rule** — ≥2 entries in 7d else a
wider average, never a single raw entry. The most conservative of the three, so
a number is never driven by one noisy weigh-in. `compute_gap`'s `basis` label
stays and becomes truthful everywhere.

**Your numbers on Home and Weight may shift slightly on first load after this.**
That is the expected consequence, not a bug.

Currently pinned as *still divergent* by
`tests/test_s2_remainder__1601.py::test_three_current_weight_algorithms_still_exist`
— that test fails when the fix lands, which is the signal to delete it.

### 3.4 — Sleep import: set the folder ID

Not code. `HEALTH_SYNC_DRIVE_FOLDER_ID` must be set to the Drive folder Health
Sync exports into (the last path segment of the folder's URL). Until then
`list_drive_sleep_files` returns `[]` and logs a warning.

This is deliberate: unset, it used to match **every CSV in your Drive** and hand
each one to the sleep parser. Harmless while the parser was a stub; not now.

### 3.5 — S3's gate, S6, and #1596

- **The reachability gate** (#1602's highest-leverage item): no endpoint,
  column, or job handler ships without a grep-verified caller. Do it *after* the
  sweep above, so it starts from a clean baseline. Now unblocked by #1622's
  OpenAPI fix.
- **S6** (#1606) — the remaining test-suite work. The ratchet, `pytest.ini`,
  `requirements-dev.txt` and CI gate are already in. Left: the SQLite-fallback
  split (do **not** try to make SQLite work — `JSONB`/`UUID` are load-bearing)
  and the remaining `AssertionError` triage.
- **#1596** — Ask-AI's two branches behind one endpoint. Consolidation, not a
  bug; it works either way today.

### 3.6 — Deferred, needs your call

- **Per-user worker tokens.** The worker token proves the caller is Hermes,
  never *which* athlete, so a holder can read any user via `?user=`. Closing it
  breaks Hermes a second time, on top of the bearer-on-GETs change already
  pending from #1615. Sequencing two breaking changes to a live bot is yours.
  Pinned by `test_the_worker_token_is_still_a_service_credential`.
- **Frontend `new Date()` in-browser semantics** — now resolved for "today"
  (§2), but if you ever want the app to follow the *device* rather than Bangkok,
  that is a product reversal, not a bug fix.

---

## 4. A correction worth carrying forward

I recommended **deleting** the Google Drive sleep integration, on the stated
grounds that the parser did not exist and I would need a sample CSV from you.
That was wrong. `services/health_sync/sleep_csv_parser.py` — 340 lines, 29
passing tests, complete with Drive fetch and token refresh — had been on disk
the whole time. You chose "remove" against a false picture.

It surfaced only because the deletion sweep hit a test importing the module I
had just claimed did not exist.

The root cause is worth remembering, because it is this codebase's dominant
defect class in its purest form. The stub's docstring read *"full parsing is
implemented in Ticket 3."* Ticket 3 **is** #1034 — it *was* implemented. It
landed in top-level `services/`; the stub lives in `backend/services/`. One
import was never written, and a complete OAuth flow, folder picker, hourly
scheduler and first-connect backfill all fed a function that returned `[]`.

**Before recommending a deletion, search for the thing you are claiming does not
exist.** Three tickets of working, tested code sat one import away from the user.
