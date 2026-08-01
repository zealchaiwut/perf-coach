# Pre-production review — status

Working doc for the S1–S6 programme (#1600–#1606) that came out of the
ten-agent review. Tracks what is usable today, what shipped, and what is left.

**Branch:** `develop`. Nothing here has been merged to `master`.
**Last updated:** 2026-08-02, session complete.

**The whole programme discussed overnight is now merged to `develop`: all nine
original PRs, S5 (#1604), and six UX-judgment-call items the product owner
decided on directly.** Fifteen PRs total (#1626–#1640), all merged by the
orchestrating session after independent re-verification (tests re-run against
CI's own artifacts, not agent summaries trusted — see §2b and §2c for what that
caught). S5 specifically required the product owner's direct, live authorization
before proceeding — see §3.2 and §2c for why a relayed approval wasn't enough
the first time.

"Verified" here means "does what it claims, CI green, no regressions" — for the
UX items, several were also visually confirmed in-browser (Playwright, against
a disposable mock account) before merge, noted per item in §2c.

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

## 2b. The overnight pass (2026-08-02) — all nine merged

Nine branches, each off `develop`, each in its own worktree. Every diff below
was verified by re-running the tests independently rather than trusting the
implementing agent's summary — twice that caught something the summary had
wrong (see "what the summaries got wrong" below).

| PR | Ticket | What |
|---|---|---|
| #1627 | #1596 | Ask-AI consolidated onto one path — the other branch was unreachable |
| #1628 | §3.3 | Three current-weight algorithms unified on `_weight_rollup` |
| #1629 | #1602 §3.1 | What-if button wired for real, two orphan endpoints given callers, two orphan pages linked |
| #1630 | #1602 §3.5 | The reachability gate |
| #1626 | UX | Mock-athlete seeder + Playwright harness (additive only — merge first) |
| #1631 | UX | Paste-loop fixes — invisible `/decisions` header, dead copy-button spinner, missing aria-label |
| #1632 | UX | Plan-week fixes — a stray `*/` killing ~140 CSS rules, Home showing a real 18 km run as "Rest", ACWR permanently "–" |
| #1633 | UX | Track+sync fixes — calendar day-click modal never opened, Sleep Hours `step:0.5` rejected its own data, stale sync spinner |
| #1634 | #1606 | S6 test-suite remainder — SQLite-fallback split + 9 real bugs found and fixed, see §3.5 |

### Merge order — all nine landed

**#1629 and #1630 interacted by design**, and both are merged now. #1630's
gate carried a ratchet baseline of known orphans; #1629 fixed five of them
(`/projection`, `/strength-view`, and the what-if / arrival-projection /
adherence-nudges endpoints). Those five baseline entries went stale on purpose
once #1629 landed — the gate's own staleness assertion is the instruction to
delete the entry, not a conflict — and were deleted before #1630 merged.

Two post-merge corrections were needed and are already on `develop`: a new
Stryd-unreachable test needed a real session (`19f84f7d`), and #1634 had removed
8 `BASELINE_FAILURES.txt` entries that don't hold in CI's no-live-services
environment — restored in `0aa7cda4`. One is a hardcoded machine-specific path
in `test_1466`; the other four are real-DB admin-auth tests CI cannot run. Worth
noting the pattern: **a baseline shrunk against a local environment that has a
live server and DB will over-claim against CI, which has neither.**

### What the summaries got wrong

Two of the six agent reports contained a claim that did not survive checking.
Both were caught by re-running the work, not by reading the summary:

- **#1628 initially made its own headline goal false.** The ticket was "make
  `compute_gap`'s `basis` label truthful everywhere". After unification, the
  single-reading case was labelled `avg_wide` — an average of one number is
  not an average, and the *old* code had labelled that same case `latest_entry`,
  which was accurate. So the first cut was less truthful than what it replaced,
  on exactly the data shape this account is in right now (tracking paused, one
  weigh-in on 2026-07-22). Fixed with a distinct `single_entry` label.

- The review doc itself was wrong about **`/weight/targets`** — see §3.1.

### Two environment hazards, both hit more than once

- **Worktrees share one `.git`, therefore one stash stack.** Two agents
  collided on it; one briefly had another's uncommitted frontend changes
  applied into its tree. No work was lost, but `stash@{0}` is now an orphaned
  labelled snapshot left in place deliberately. Do not use `git stash` when
  parallel worktrees are live — copy files instead.
- **The shared scratchpad directory is not isolated per agent.** A file written
  by one agent was silently overwritten by another between tool calls. Anything
  load-bearing (a test baseline, a before/after capture) belongs inside the
  agent's own worktree. This one is nastier than the stash collision because it
  fails silently and the corrupted result still looks plausible.
- Also worth an explicit check next time: one orchestrator's worktree tooling
  defaulted its branches to `master` rather than `develop` — 73 commits apart.
  Caught mid-flight and rebased, but nothing would have flagged it.

---

## 2c. S5, and the six UX-judgment-call items (2026-08-02, later the same night)

Six PRs, on top of the nine above, all reviewed one at a time (not in
parallel — the product owner asked for that explicitly, after the earlier
batch showed how much conflict-risk touching the same files concurrently
creates) and merged after CI confirmed green on each:

| PR | Ticket | What |
|---|---|---|
| #1635 | S5 (#1604) | Schema consolidation — see below, the big one |
| #1636 | UX | `/trends` enabled, `/calendar` deleted outright (not just hidden), nav overflow at 1440px fixed |
| #1637 | UX | Dead `/weight/targets` route deleted (redirect stub removed, not just exempted) |
| #1638 | UX | Explanatory tooltips for CTL/ATL/TSB/ACWR on Home + Training Log (`/trends` doesn't actually display these four, so tooltips went where the metrics really are) |
| #1639 | UX | Home gets a forward-looking "Today's plan" card; "Recent workouts" relocated, not removed |
| #1640 | UX | Coach-export pre-copy explanation + persisted in-flight status (the loading spinner itself already existed from earlier tonight — the missing piece was the explanation and a toast that didn't auto-dismiss before the ~12s build finished) |

### S5 — merged as #1635

Required the product owner's **direct, live authorization** in this same
conversation before proceeding. The first attempt — this session relaying "the
human decided X" to the ticket-implementing agent — was correctly refused; see
§2b's "environment hazards" for the fuller reasoning (an agent's report of a
human's approval isn't verifiable consent for an irreversible action, and that
refusal was the right call, not overcaution to route around). Once the human
gave the instruction directly, it proceeded.

What shipped, beyond §3.2's decisions table:
- `habit_type` now derives from `tracking_type` **when `tracking_type` is
  supplied** (100% of real frontend traffic) — applying it unconditionally
  would have broken ~15 tests pinning a legacy v2-only creation path that never
  sends `tracking_type`. Documented deviation from the original ticket text,
  not a shortcut.
- `weight_plans` is gone, not deprecated — merged into `weight_targets` (new
  `phase` and `target_rate_kg_per_week` columns), `/api/weight-plans/*` removed
  outright. Both migrations already applied to and verified against the live
  UAT database as part of the work, not just written.
- The `ensure_goal_habits` race condition (flagged in §3.6 below) is closed:
  two partial unique indexes on `habits`, matched to `_find`'s actual lookup
  order, plus a migration-time dedup of the three UAT duplicate groups that had
  already formed (earliest row kept, logs re-pointed, losers archived not
  deleted).
- Found and fixed in passing: `goal_arrival_caller.resolve_arrival_projection()`
  called `datetime.today_bangkok()` — the stdlib module, which has no such
  attribute — so `GET /api/weight-targets/arrival-projection` 500'd on every
  real call. Pre-existing, unrelated to this ticket's diff, found while
  checking that file for coupling to the old table split (it had none, but
  this bug was sitting in the same function).

One CI-only regression caught post-merge-attempt and fixed before landing:
removing `/api/weight-plans/*` made three `tests/test_reachability_gate__1602.py`
baseline entries stale (the routes they were tracking no longer exist), and a
local run flagged 9 more `BASELINE_FAILURES.txt` entries as "now passing" that
did **not** hold against CI's actual artifact — same false-positive pattern as
#1634 (SQLite-fallback skips get miscounted as passes locally; CI has no live
Postgres or admin secret and genuinely still fails them). Only the 3 real ones
were touched.

### The 85-orphaned-routes finding — triaged, not resolved

§3.5 already noted the reachability gate found 85 more orphaned API routes than
this doc's own §3.1 sweep. Discussed with the product owner and bucketed:

1. **~35 clearly dead/superseded routes** (duplicates like `/api/healthz` vs
   `/api/health`; routes superseded by a consolidated one that's actually
   called, like the five `/api/home/*` siblings replaced by
   `/api/home/summary`) — **decision: delete in a dedicated follow-up ticket,
   not done tonight.**
2. **5 parked coach-message routes** (`/api/coach/{daily-message,
   daily-messages, goal, weekly-message, weekly-messages}`) — matches
   CLAUDE.md's existing "parked, pending deletion after a quiet release" plan
   already. No new decision needed.
3. **`/api/weight-plans*` (3 routes)** — resolved automatically by S5 (#1635)
   removing the table and routes entirely.
4. **~25 routes with no UI ever built** (`/api/feel` — all 5 routes, zero UI
   path found anywhere; 3 of the CSV export buttons never wired;
   `/api/users/me/avatar` has no upload/delete UI; `/api/preferences/*`;
   sleep-import manual-sync routes; etc.) — **decision: the product owner will
   review this list directly** in `tests/test_reachability_gate__1602.py`'s
   `_BASELINE_ORPHANS_API` (each entry has its own one-line reason, grouped by
   cluster) rather than have it triaged blind. Not acted on.

### The rest of §3.6's "found overnight" items — resolved by decision, not code alone

- **Habits race condition** — fixed, see S5 above.
- **`/weight/targets` dead route** — deleted (#1637), not left exempted.
- **`/trends` / `/calendar`** — `/trends` enabled, no known reason found to
  keep it hidden. `/calendar` **deleted outright**, per the product owner:
  "I don't think we will use it from now" — stronger than the original
  finding's framing of this as just a mistaken "Coming soon" flag.
- **Avatar 404s** — still backlogged, decision confirmed explicitly: real gap,
  `has_avatar` field needed, too large a ripple for a polish pass, dedicated
  ticket later.
- **Worker tokens** (§3.6's other deferred item) — still backlogged, decision
  confirmed explicitly: real security gap, but breaking Hermes a second time
  needs deliberate sequencing in its own session, not decided at this hour.

### The four "UX judgment calls" — all resolved

All four items listed at the end of §3.6 were discussed one at a time with the
product owner and all four were approved: tooltips (#1638), Home focal point
(#1639), export loading state (#1640), nav overflow (#1636, bundled with the
trends/calendar work since both touch `nav.js`).

### Process note

Six items done strictly sequentially this time (branch off latest `develop`,
implement, verify, merge, *then* branch the next one off the now-updated
`develop`) rather than the earlier batch's worktree-parallel approach — by
explicit instruction, after the earlier batch's file-overlap conflicts
(`js/user.js` double-included, a stale `/preferences` pin between two
already-merged PRs) made the tradeoff clear. Slower, but zero merge conflicts
across all six. Two agents also got stuck reporting "still waiting" on a
background test run after actually finishing (once genuinely idle waiting on
an unnecessary live-DB pass, once with a stale status report after already
having pushed) — resolved by checking the worktree/PR directly rather than
trusting the self-report a third time.

---

## 3. What is left

Ordered as intended. Decisions already taken are recorded so tomorrow does not
re-litigate them.

### 3.1 — S3 remainder (#1602) — DONE, merged as #1629

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

**Correction — `/weight/targets` was never an orphan.** Listing it above with
`/projection` and `/strength-view` was a misdiagnosis in this doc. AC #461
consolidated that standalone page into `weight.html`'s own "Edit target"
slide-in panel, and `test_weight_page_frontend__412.py::
test_b_manage_target_links_to_weight_targets` pins the removal:

    assert "/weight/targets" not in WEIGHT_HTML

So adding the link back is a regression, not a fix. PR #1629 left it alone;
#1630's gate records it as a permanent exemption rather than a baseline orphan.

Note this is a *third* category, not the `/run-builder` one: that page has zero
entry points anywhere in the frontend, deliberately. The route still exists and
serves a page nothing can reach — **a deletion candidate, listed in §3.6 rather
than acted on**, because §4 of this doc is about what happens when a route gets
deleted on a hunch.

**What actually shipped in #1629:** the what-if button now calls
`POST /api/weight-targets/{goal_id}/what-if` (note: POST — this doc previously
implied GET) and renders the simulation; `arrival-projection` and
`adherence-nudges` have real callers; `/projection` and `/strength-view` have
entry points. Verified independently: 12 pre-existing failures in
`test_weight_page_frontend__412.py` on the branch vs **14 on `develop`** — no
regressions, and it incidentally fixed two.

### 3.2 — S5 schema consolidation (#1604) — DONE, merged as #1635

Was deliberately not implemented during the first overnight pass — the brief
had excluded it pending your decision on its open questions, and a relayed
"the human approved it" was correctly refused as insufficient authorization for
a live-DB migration (see §2c and §2b's environment-hazards item on this). You
resolved the two open questions directly, then gave direct live authorization
to proceed; see §2c for what shipped and the one deviation from spec.

Decisions taken:

| Item | Decision |
|---|---|
| `habits.habit_type` vs `tracking_type` | **Derive `habit_type` from `tracking_type` at write.** `tracking_type` is the survivor — it carries all behaviour. Backfill existing rows. No API break. Shipped: derivation applies when `tracking_type` is supplied (100% of real traffic) — see §2c for why not unconditionally. |
| `weight_targets` vs `weight_plans` | **Merge into one table with a `phase` column.** Shipped: `weight_plans` retired outright, `weight_targets` gains `phase` + `target_rate_kg_per_week`. |
| `fuel_settings.lean_mass_kg` | **Decided: keep as a labelled manual override.** Already correctly labelled via `fuel.current_lean_mass_kg()`'s `source` field — no code change needed, comment added confirming it's intentional. |
| Two lean-mass derivations reaching `coach_export` | **Decided: label, don't merge.** They answer different questions (fueling point-estimate vs. a fallback-free trend guard) and can legitimately disagree — comment added explaining why, no behavior change. |

### 3.3 — Unify the three "current weight" algorithms — DONE, merged as #1628

Decision taken: **unify on `_weight_rollup`'s rule** — ≥2 entries in 7d else a
wider average, never a single raw entry. The most conservative of the three, so
a number is never driven by one noisy weigh-in. `compute_gap`'s `basis` label
stays and becomes truthful everywhere.

**Your numbers on Home and Weight may shift slightly on first load after this.**
That is the expected consequence, not a bug.

Currently pinned as *still divergent* by
`tests/test_s2_remainder__1601.py::test_three_current_weight_algorithms_still_exist`
— that test fails when the fix lands, which is the signal to delete it.

**Shipped in #1628.** The pinned test is deleted, as intended. Three things
came out of it that this section did not anticipate:

- **`basis` is an API-visible contract change, not just a label.**
  `latest_entry` no longer exists as a value. The set is now `avg_7d` /
  `avg_wide` / `single_entry` / `None`. Nothing in the frontend branches on the
  string (`weight.js` derives the basis arithmetically), so the blast radius
  looks small — but anything else reading it sees values it has never seen.

- **`_ROLLUP_LOOKBACK_DAYS` is 55.** The old fallback capped at "latest entry
  within 14 days"; the unified rule averages up to 55 days back. On sparse data
  that is a materially wider number than "a wider average" suggests.

- **"Never a single raw entry" was not actually true**, and that is why the
  `single_entry` label had to be invented. With exactly one reading in the
  55-day lookback, the wide-average branch averages one value and returns it
  raw. The rule is still the most conservative of the three and still the right
  standard — but the invariant it was chosen for has an edge case, and the
  label now says so instead of hiding it. This is the case this account is in
  today.

The `_ma` count held up: the two definitions (`main.py:2450`, `:3448`) were
byte-identical, so "three algorithms" was accurate.

### 3.4 — Sleep import: set the folder ID

Not code. `HEALTH_SYNC_DRIVE_FOLDER_ID` must be set to the Drive folder Health
Sync exports into (the last path segment of the folder's URL). Until then
`list_drive_sleep_files` returns `[]` and logs a warning.

This is deliberate: unset, it used to match **every CSV in your Drive** and hand
each one to the sleep parser. Harmless while the parser was a stub; not now.

### 3.5 — S3's gate, S6, and #1596

- **The reachability gate** — **DONE, PR #1630.** 381 tests. It covers routes
  (all three registration paths: decorators, `add_api_route`, and
  `APIRouter`/`include_router` — a decorator-only scan misses the shims, which
  is how `/weight/targets` stayed invisible). Baseline is ratchet-only and
  asserts its own entries are still genuinely orphaned, so a stale entry fails
  rather than rotting.

  **It found 85 more orphaned API routes than §3.1 listed.** §3.1's sweep was
  itself a grep sweep, so this doc's own "greps undercount, ratchet tests find
  the rest" verdict applied to this doc. The 85 are in the ratchet baseline,
  each with a reason; they are not all bugs, but none of them has a caller.

- **S6** (#1606) — the remaining test-suite work. The ratchet, `pytest.ini`,
  `requirements-dev.txt` and CI gate are already in. Left: the SQLite-fallback
  split (do **not** try to make SQLite work — `JSONB`/`UUID` are load-bearing)
  and the remaining `AssertionError` triage.

  **DONE, merged as #1634** (was in flight when an earlier draft of this doc
  was written). SQLite-fallback split landed (a `pytest_runtest_call` hook
  converts Postgres-schema-gap errors to skips on the fallback, registered as
  `requires_postgres`), plus a genuine triage pass: 540→379 offline failures,
  9 real bugs found and fixed (unguarded migration `drop_table`/`drop_index`
  calls, tests never exercising their `athlete_id` path param, unauthenticated
  Strava/Stryd status tests, a formula deleted by #1348 still asserted
  elsewhere, a mock-signature mismatch breaking 32 tests across two files).
  ~15 backend test files still un-triaged, all ratchet-recorded in
  `BASELINE_FAILURES.txt` so nothing regresses silently. The triage target
  remains that file, a shrink-only ratchet with a regeneration script at
  `scripts/check_test_regressions.py` — success is shrinking it, not reaching
  zero.

  Also: `pytest-timeout` was missing from `.venv` for most of this session, so
  local runs printed `Unknown config option: timeout` and `pytest.ini`'s 60s
  hang-guard was inert. Installed (2.3.1) before the session ended; CI was
  never affected — `.github/workflows/tests.yml:38` installs
  `requirements-dev.txt`. Noted only because a local run from earlier in the
  night had no hang-guard behind it.

- **#1596** — **DONE, PR #1627**, and "it works either way today" was true only
  in a sense that made it worth fixing. The two branches were not a live fork:
  a stricter `plan_slot.py` implementation was layered *in front* of the older
  #1417 budget-pinning one a week later without removing it, and returns first
  for every pinned call. So the older branch — its prompt budget rule,
  `_budget_errors`, and its force-stamp retry — had been **unreachable** ever
  since. `_budget_errors` was a function that could only ever be called with
  both arguments `None` and therefore always returned `[]`. Net −96 lines. Its
  own test had been failing in `BASELINE_FAILURES.txt` the whole time, pinning
  the shadowed behaviour.

### 3.6 — Deferred, needs your call

- **Per-user worker tokens.** The worker token proves the caller is Hermes,
  never *which* athlete, so a holder can read any user via `?user=`. Closing it
  breaks Hermes a second time, on top of the bearer-on-GETs change already
  pending from #1615. Sequencing two breaking changes to a live bot is yours.
  Pinned by `test_the_worker_token_is_still_a_service_credential`. **Discussed
  directly — confirmed backlog**, real gap, needs its own deliberate session,
  not decided at this hour.
- **Frontend `new Date()` in-browser semantics** — now resolved for "today"
  (§2), but if you ever want the app to follow the *device* rather than Bangkok,
  that is a product reversal, not a bug fix.

#### Found overnight — status per item (see §2c for what shipped)

- **`habits` has no unique constraint, and `ensure_goal_habits` is a
  check-then-insert.** **RESOLVED — fixed in S5 (#1635).** Its docstring claims idempotency; it isn't. Three agents
  hitting the UAT database concurrently made two requests pass the existence
  check at once and both insert. **Confirmed in the UAT DB**: the `uxmock` user
  now has two each of "Morning weigh-in", "Protein first" and "Long-run fuel".
  The real `zeal` account is unaffected. It never self-heals — `_find` returns
  the first match, so the count looks stable and it looks idempotent again.
  Reproduces with two browser tabs, or web + worker together.

  This belongs with S5 (#1604), which is already writing a migration on this
  table. Two details for whoever does it, because the obvious fix is wrong:

  1. A unique constraint on `(user_id, auto_fill_source)` **would not catch
     "Protein first"** — its `auto_fill_source` is `NULL`, and Postgres treats
     NULLs as distinct. `_find` falls back to matching on `name` for exactly
     that row.
  2. A plain `UNIQUE (user_id, name)` **would break archiving**. `_find`
     filters `is_archived = false`, so an athlete archiving a habit and making
     a new one with the same name is legitimate. It needs to be a *partial*
     unique index (`WHERE is_archived = false`).

  And `ensure_goal_habits` needs to catch the resulting `IntegrityError` and
  refetch, rather than trusting the pre-check.

- **`/weight/targets` is a route nothing can reach.** **RESOLVED — deleted
  outright in #1637**, not left exempted. Decided directly rather than left
  flagged, unlike the §4 caution this doc originally applied to it.

- **`/trends` and `/calendar` are marked "Coming soon" and disabled in
  `nav.js`, but both are fully working, data-rich pages.** **RESOLVED —
  `/trends` enabled (#1636), `/calendar` deleted outright** per explicit
  product decision ("I don't think we will use it from now"), not left
  disabled or exempted.

- **Avatar 404s on every page** for users without one. **Still open —
  confirmed backlog**, needs a `has_avatar` field to fix properly; explicitly
  decided to defer to a dedicated ticket rather than take the ripple tonight.

- **The 85-orphaned-route finding from the reachability gate.** **Triaged, not
  resolved** — see §2c for the four-bucket breakdown and what's still pending
  (a follow-up deletion ticket for ~40 routes; you reviewing ~25 "no UI ever
  built" candidates directly in the gate file).

#### UX judgment calls — all four resolved, see §2c

1. ~~No tooltip or help affordance anywhere for CTL / ATL / TSB / ACWR.~~
   **Done — #1638.**
2. ~~Home has no forward-looking "today's session" focal point.~~ **Done —
   #1639, "Recent workouts" relocated not removed.**
3. ~~The coach export gives no pre-copy explanation or size preview.~~
   **Done — #1640.** (The ~12s export time itself was explicitly left alone —
   a performance investigation, not a UX fix, and out of scope.)
4. ~~The nav overflows at 1440px on `/calendar` and `/trends`.~~ **Done —
   #1636**, and the root cause turned out broader than either page
   specifically (see §2c).

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
