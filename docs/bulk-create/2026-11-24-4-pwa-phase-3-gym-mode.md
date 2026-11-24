# PWA phase 3: gym mode

**Date:** 2026-11-24
**Sprint label:** sprint-153
**Default labels:** pwa, pwa-phase-3, manual
**Status:** posted

## Context

Phase 3 is gym mode at /m/gym/{session_id}: a full-screen, offline session player for strength sessions. It covers:

- sections from the structured session format (PWA P0-2);
- straight sets and supersets;
- timed blocks (EMOM, 40/20 intervals, holds) on a shared timer engine;
- swap and reorder;
- a finish screen that queues the session and syncs it back as a new session version, with strength TSS and anchors recomputed on the server.

Builds on Phases 0–2.

Mocks: `docs/pwa/mocks/source/` (390x844). Gym mode uses the dark ink background `#0b1530` with lime `#e4ff52` actions.

**Implementation note:** issues are implemented manually in Cursor, not by Commander agents. Each issue body is the Cursor prompt. The `manual` label marks them as hand-implemented; Commander only dispatches tickets passed to it explicitly, so do not include them in a dispatch call.

**Conventions:**
- The mock owns layout; the issue owns rules.
- Fully offline: every gym-mode screen works offline. Every tap writes to IndexedDB session_state at once (PWA P1-3), and the finished session goes to the outbox as one session_log op (PWA P0-4).
- Stack: vanilla JS. Touch targets at least 44 px, with large steppers (48–52 px). No keyboard needed for normal logging.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (notes added in the issue bodies where reality differs):
- P3-1 to P3-6: all referenced mocks exist (`GymOverview`, `GymExercise`, `GymSuperset`, `GymEmom`, `Gym4020`, `GymHold`, `GymSwap`, `GymFinish`). `/m/gym`, `frontend/js/m/` and the bundle fields (`last_numbers`, `swap_history`, `library`, `anchors`) do not exist yet (Phases 0 and 1).
- P3-7: `strength_tss.py` exists with `from_exercises` and `from_effort_time` (and `strength_tss_block`), used by `session_tss`. Python fixtures for the shared-fixture test do not exist yet.
- P3-8: `session_template_overrides` does not exist yet (expected). `plan_pattern_fill.py` is the generator. Settings › Plan is `frontend/pages/v2-settings-plan.html` with `frontend/js/v2-settings-plan.js`.

## Issues

### PWA3-1

```
Title: [PWA P3-1] Gym session overview by section and session state

Mock
docs/pwa/mocks/source/GymOverview.dc.html.

Scope
- /m/gym/{session_id} reads the session from the bundle.
- Header: back, GYM MODE · OFFLINE READY, session name, and an Edit button that opens reorder.
- A mono summary: sections, exercises, minutes, estimated TSS.
- Sections in order, each with a numbered uppercase header (1 · WARM-UP, 3 · SUPERSET A, 4 · EMOM 8 MIN) and a right-aligned format line (straight, rest 90 s; 3 rounds, rest 90 s after A2; and a lime timer mark for emom, interval and hold).
- Rows per format:
  - straight: name and planned scheme, plus a Last: line from last_numbers (and anchor when it's an anchor lift);
  - superset: the A1/A2 rows grouped in one card;
  - emom: odd/even rows grouped;
  - interval: a single row with A ⇄ B and 40/20 × N;
  - hold: a row with N × S s hold;
  - a swap hint from swap_history (You swapped this for step-ups last 2 times).
- A sticky primary button: Start · {first section}. Tapping a row starts at that exercise.
- Session state model in session_state: started_at, current position (section, exercise, set or round, minute or interval), per-set results, and the edit log (swaps, order changes, added or removed sets).
  - Restored on reopen, so killing the app resumes at the same spot.
  - Sets the session-active flag that blocks app updates.
- Note: /m/gym and the bundle fields last_numbers and swap_history do not exist yet (Phases 0 and 1).

Acceptance criteria
- Each format renders from a fixture session.
- Kill and reopen resumes at the same position with all results.
- Works in airplane mode.

Depends on: PWA0-2, PWA1-3, PWA2-1
```

### PWA3-2

```
Title: [PWA P3-2] Straight-set logger with rest timer and RPE

Mock
docs/pwa/mocks/source/GymExercise.dc.html.

Scope
- Header:
  - back to the overview;
  - progress across exercises (one bar segment per exercise, done in lime);
  - elapsed session time.
- Exercise name (24 px) and a line with the scheme, equipment and anchor tag.
- Rest banner after a done set:
  - a mono countdown from rest_after_seconds (default 90 s), with Skip;
  - it uses the timer engine from PWA3-4, but can ship first with a simple timestamp countdown and be swapped later.
- Set rows:
  - done sets in green with kg × reps;
  - the current set as a white card with kg and reps steppers (48 px buttons, kg step 2 kg, configurable per exercise later) and a Done set N button;
  - upcoming sets muted.
- Holds and time sets show seconds instead of reps.
- RPE chips 6–10 per exercise.
- Action row: Swap, + Set, Skip, Note.
- Next bar with the next exercise and its scheme.
- Every change writes to session_state at once.

Acceptance criteria
- Pre-filled values equal the planned set. Changing kg or reps affects only the current set and later sets of the same exercise (not earlier ones).
- Done starts the rest countdown.
- RPE and notes persist in session_state.
- All controls are at least 44 px.

Depends on: PWA3-1
```

### PWA3-3

```
Title: [PWA P3-3] Superset logger (A1/A2 rounds)

Mock
docs/pwa/mocks/source/GymSuperset.dc.html.

Scope
- Header: SECTION n OF m · SUPERSET A, Round r of R, and the rest rule.
- Round progress: one bar per round (done green, current lime, upcoming dim).
- The done exercise of the round as a green row. The active exercise as a white card with its steppers and Done A2 · start 90 s rest. No rest between A1 and A2 unless the section sets one.
- A rounds grid: rows R1…Rn, columns A1, A2, … Cells are done, now or upcoming. Tapping a done cell edits it.
- Actions: Swap, + Round, RPE (per exercise inside the superset), Next.

Acceptance criteria
- A 3-round A1/A2 fixture logs 6 entries in the right order.
- Rest starts only after the last exercise of a round.
- + Round adds a round with the previous round's values.
- Editing a past cell updates session_state.

Depends on: PWA3-2
```

### PWA3-4

```
Title: [PWA P3-4] Timer engine and EMOM player

Mock
docs/pwa/mocks/source/GymEmom.dc.html.

Scope
- frontend/js/m/timer.js: one engine for every timed block.
  - Timestamp-based: it stores started_at, paused_at and accumulated pause in session_state and computes the remaining time from Date.now(). It never trusts setInterval ticks. So it stays correct after the screen locks, the tab is backgrounded, or the app is killed and reopened.
  - Phases: a list of steps (label, kind work or rest, seconds, payload).
  - API: start, pause, resume, reset, skip, previous, and onStep / onTick callbacks.
  - Cues: 3-2-1 beeps before each step change (Web Audio, short tones) and navigator.vibrate where supported, with a mute toggle in the header.
  - Screen Wake Lock while running, re-acquired on visibilitychange.
- EMOM player:
  - builds its minutes from section emom fields (minute_rule odd, even or every);
  - a large ring counting down the current minute, with MINUTE m OF M, the time left and the minute's exercise and target underneath;
  - a strip of minute pills (done green, current outlined lime, upcoming dim) and a next line;
  - a Didn't finish the reps? stepper that edits the current minute's reps;
  - Reset / Pause (primary lime) / End.
- Each finished minute writes reps done to session_state.
- Note: there is no JS test harness in the repo yet (see the Phase 1 store issue), so the engine unit tests need the harness added there first.

Acceptance criteria
- An 8-minute odd/even fixture produces the right exercise per minute.
- Locking the phone for 90 s and returning shows the correct minute and time.
- Pause and resume keep the total time correct.
- Cues fire 3 s before each minute (testable with a fake clock).
- Unit tests on the engine with a fake clock.

Depends on: PWA3-1
```

### PWA3-5

```
Title: [PWA P3-5] 40/20 interval player and hold stopwatch

Mock
docs/pwa/mocks/source/Gym4020.dc.html and GymHold.dc.html.

Scope
- Interval player (section format interval) on the PWA3-4 engine:
  - the work phase is a full lime panel: WORK · INTERVAL i OF N, an 84 px mono countdown, the exercise name and a phase progress bar;
  - under it, a blue rest card: THEN REST 0:20 and the next exercise. During rest, the big panel switches to blue with the rest countdown;
  - an interval strip with exercise initials;
  - Previous / Pause / Skip controls;
  - exercises alternate in the order listed in the section.
- Hold stopwatch (section format hold):
  - counts up by default (count_mode up) from a 3-2-1 start;
  - a target bar with a tick at target_seconds that turns green when passed, showing +S over;
  - a big red Stop · save m:ss button that saves the actual held time;
  - Countdown mode as an option;
  - a beep at the target;
  - a list of holds done, where tapping a saved time lets you correct it.
- Both write their results to session_state: intervals completed, and held seconds per hold.

Acceptance criteria
- A 40/20 × 6 fixture alternates A and B, with the correct phase colours.
- A hold of 51 s against a 45 s target saves 51.
- Both survive a screen lock (engine tests).
- Correcting a saved hold time updates session_state.

Depends on: PWA3-4
```

### PWA3-6

```
Title: [PWA P3-6] Swap and reorder sheet (offline)

Mock
docs/pwa/mocks/source/GymSwap.dc.html.

Scope
- A bottom sheet from Swap: the section and muscle label, the title Swap {exercise}, and close.
- A search over the bundle library: name and aliases, offline, debounced.
- Same muscles suggestions from library muscles. Mark the user's most frequent replacement from swap_history as USUAL, and list it first.
- A Keep {scheme} switch: on keeps the planned sets, off starts from the replacement's last_numbers.
- An Order row of section chips that can be reordered by press-and-drag. Exercises can also move between sections of the same format.
- The primary button reads Swap to {name}.
- Swaps and reorders go to the session_state edit log.

Acceptance criteria
- Search works in airplane mode.
- USUAL appears for a fixture history.
- Keep on and off produce the right pre-filled sets.
- Reordering persists and shows in the overview.
- The edit log records each change.

Depends on: PWA3-1
```

### PWA3-7

```
Title: [PWA P3-7] Finish screen, queue session_log, sync back

Mock
docs/pwa/mocks/source/GymFinish.dc.html.

Scope
- SESSION DONE with the session name.
- Tiles: time, sets done over planned, and TSS est.
  - The estimate is computed on the phone with the same formula as the server strength TSS (port strength_tss from_exercises / from_effort_time into one shared JS function with tests against the Python values).
  - Mark it est. until the sync replaces it with the server value.
- A whole-session RPE chip row.
- Strength anchors card: for anchor lifts done today, share of target before → after, using the bundle anchors. Note that Strength updates after sync.
- Changed from the plan: a list built from the edit log (swaps, kg changes, added or removed sets). A checkbox Use these in future {session} sessions, default on, saved into the op payload as apply_to_future.
- Done queues one session_log op (PWA0-4) with everything from session_state, clears the session-active flag and returns to Today.
- A sync bar: Saved on this phone · syncs when the server is up · Sync now. After sync, Today shows the server TSS.
- Note: backend/services/strength_tss.py has from_exercises and from_effort_time (and strength_tss_block, used by session_tss). The shared fixture file for the 5 fixture sessions does not exist yet.

Acceptance criteria
- The JS strength TSS estimate equals the Python result for 5 fixture sessions (shared fixture file).
- The op payload contains every set, hold, interval and EMOM minute result, plus swaps, order, RPE and notes.
- After sync, the server session version matches the payload, and the strength TSS replaces the estimate in the next bundle.

Depends on: PWA3-2, PWA3-3, PWA3-4, PWA3-5, PWA3-6, PWA0-4
```

### PWA3-8

```
Title: [PWA P3-8] Generator learns from gym edits (apply_to_future)

Why
When the user ticks Use these in future sessions, the next generated session of the same template should reflect the swaps and load changes.

Scope
- Store accepted edits per user and template in a new table session_template_overrides (user_id, template_key, exercise_key, override json: replacement exercise, kg delta or absolute kg, added sets; updated_at).
- On sync of a session_log with apply_to_future, upsert the overrides from the edit log.
- plan_pattern_fill applies the overrides when generating that template (swap the exercise, start from the new kg, keep the added sets), then its normal progression.
- Settings › Plan shows the active overrides per template, with remove.
- Note: session_template_overrides does not exist yet. The generator is backend/services/plan_pattern_fill.py. Settings › Plan is frontend/pages/v2-settings-plan.html with frontend/js/v2-settings-plan.js.

Acceptance criteria
- After a synced session with a swap and a +2 kg change, the next generated session of that template uses the swap and the new kg (pytest).
- Removing an override restores the template.
- Without apply_to_future, nothing is stored.

Depends on: PWA3-7
```
