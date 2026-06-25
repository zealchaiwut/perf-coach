# MVP Daily-Use Flow Test

## What this documents

End-to-end timing and observations from testing the complete daily-use flow on
mobile (390px / Chrome DevTools mobile emulation). Run before each sprint-50
merge to `master`.

## Target

Full flow (open → log metrics → log workout → verify Zone 2 habit progress)
must complete in **< 2 minutes** on mobile.

## Flow steps

1. Open app at 390px width.  
   Expected: home shows today's "Log today" prompt (Bangkok-midnight boundary).

2. Tap **Log today** → fill RHR, HRV, sleep hours, sleep quality, energy, mood,
   weight → tap **Save**.  
   Expected: returns to home without error; prompt is no longer shown.

3. Tap **Log workout** → fill in a run with `zone2_minutes` → tap **Save**.  
   Expected: returns to home; weekly habits widget shows increased Zone 2 minutes
   progress.

4. Observe weekly habits widget.  
   Expected: Zone 2 bar reflects the workout; week starts on Bangkok Monday; no
   `undefined` or `NaN` shown in any cell.

## Timing log

| Date | Device / emulation | Total time | Notes |
|------|--------------------|------------|-------|
| 2026-06-10 | Chrome DevTools 390px | ~55 s | Smooth on UAT; step 3 is fastest with saved template |

## Observations and rough edges

- Mobile tap targets on habit cells are comfortable at 390px.
- "Log today" prompt correctly appears on a fresh day (Bangkok midnight rollover
  verified by checking at 00:01 BKK / 17:01 UTC).
- Weekly habit widget renders instantly; no flash of `undefined`.
- Training log empty state displays correctly for a fresh user.
- Starter habit buttons appear immediately for a user with no habits.

## PRD smoke test

Run after each deployment to `master`:

1. Open `https://perf-coach.onrender.com` (or PRD URL) on mobile.
2. `curl https://perf-coach.onrender.com/api/healthz` — expect HTTP 200,
   `{"ok": true, "version": "...", "env": "prd"}`.
3. Repeat the flow steps above.
4. Document any PRD-specific issues in the **PRD issues** table below.

### PRD issues

_None yet._
