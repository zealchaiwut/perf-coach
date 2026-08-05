# Operator guide — running the lean program

How to actually use Priority 1 (coach export + paste loop) and Priority 3 (the
lean program).

Written 2026-07-30, revised 2026-07-31. Companion to
`docs/features/lean-program.md` (what was built and why) and
`docs/features/coach-export.md` (the export contract). This file is the runbook:
what to click, what to curl, and what to expect.

> **Revised 2026-07-31.** PRs #1593 and #1594 shipped three columns whose readers
> were built and tested but which nothing in the API could set: the goal habits
> were never created, and `body_fat_pct` and `fuelled` had no write path. §1.3,
> §6 and §9 described them as working. They work now — see §11 for what changed.

---

## 0. Deploy

PRs #1593 and #1594 are merged. **Migrations run themselves** — `render.yaml` has
`preDeployCommand: alembic upgrade head` on both services, so there is no manual
DB step.

Five migrations land, in this order:

| Revision | Adds |
|---|---|
| `a87e213dedbb` | `decisions` table |
| `1fff1ada408b` | `weight.logged` autofill source |
| `c76739716276` | `weight_entries.body_fat_pct` |
| `37e30b89c6cd` | `workouts.fuelled` + `long_run.fuelled` source |
| `13f189e87eec` | `calibration_sprints` table |

Sanity check after deploy:

```bash
python3 scripts/check_migrations.py     # single head: 13f189e87eec
curl -s https://<host>/api/coach/export | jq '.meta.schema_version'   # → 4
```

---

## 1. One-time setup (~15 minutes)

### 1.1 Tell it who you are

**Settings → Profile.** Three fields matter:

- **Date of birth** — without it `athlete.age` exports as `null`
- **Height** — same, for `height_cm`
- **Athlete context** (200 chars) — the only free-text identity field

Example context:

> 6 years running, returning from a calf strain, 5–7 h/week, hates track work

This is what stops every fresh chat from asking who you are. Keep it to facts a
coach would want on day one. It is deliberately **separate** from plan-prefs
`notes`, which are scheduling instructions ("no Tuesday mornings").

### 1.2 Set your dish list and plan prefs

No UI for `volume_plays` yet — API only. One call sets everything:

```bash
curl -X PUT https://<host>/api/preferences \
  -b cookies.txt -H 'Content-Type: application/json' \
  -d '{
    "payload": {
      "volume_plays": [
        "oyakodon with extra cabbage",
        "kimchi jjigae",
        "tom yum with tofu",
        "cold soba + edamame"
      ],
      "stretch_daily_min": 10,
      "plyo_mode": "superset",
      "plyo_sessions_per_week": 1,
      "rest_days": [2, 6]
    }
  }'
```

| Field | Bounds | Effect |
|---|---|---|
| `volume_plays` | ≤10 items, ≤80 chars | consult suggests food FROM this list |
| `stretch_daily_min` | 0–60 | mobility block on every day of the plan |
| `plyo_mode` | `off` / `superset` / `standalone` | where plyo lands |
| `plyo_sessions_per_week` | 0–2 | how many |
| `rest_days` | 0=Mon … 6=Sun | preferred rest |

`superset` hangs plyo off a strength day (adds ~8 TSS). `standalone` claims its
own midweek day (~20 TSS) — it will never take your long run or a quality
session.

### 1.3 Create the three goal habits

**Open the Habits page once.** That call creates them automatically:

| Habit | How it gets satisfied |
|---|---|
| Morning weigh-in | autofills from a weight entry, logged anywhere |
| Protein first | one tap — the only one the program asks for |
| Long-run fuel | autofills from a long run marked `fuelled` (§6.1) |

If you already have a habit with one of those names, it is **adopted**, not
duplicated — your history survives.

Verify it took:

```bash
curl -s https://<host>/api/coach/export -b cookies.txt | jq '.habits.goal_habits'
# → ["weigh_in", "protein_first", "long_run_fuel"]
```

An empty list here means the bootstrap didn't run — load the Habits page again.

### 1.4 Wire Discord (Hermes side)

perf-coach never talks to Discord. Hermes polls; perf-coach answers.

On the worker, set `WORKER_API_TOKEN`. Then Hermes does two things:

**Each morning, ask whether to nudge:**

```bash
curl -s https://<worker>:9100/api/weight/nudge
```

```json
{
  "tracking_state": "active",
  "nudge_cadence": "daily",
  "logged_today": false,
  "in_window": true,
  "deliver_now": true,
  "message": "morning — what's the number?"
}
```

**Deliver only when `deliver_now` is true.** Silence is the correct output most
mornings — already logged, outside the window, or paused and it isn't Monday.

**On your reply, write the number:**

```bash
curl -X POST https://<worker>:9100/weight-entry \
  -H "Authorization: Bearer $WORKER_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"weight_kg": 87.6}'
```

Replying twice in one morning **corrects** the number rather than making a second
row. The weigh-in habit ticks itself off that entry.

On the one morning a week you also take a body-fat reading, send both together:

```bash
  -d '{"weight_kg": 87.6, "body_fat_pct": 21.4}'
```

Omitting `body_fat_pct` leaves any existing reading alone — the six other
mornings can't wipe the week's number.

**Nudge window is 06:00–08:00 Bangkok** — `_WEIGHT_NUDGE_START_HOUR` and
`_WEIGHT_NUDGE_END_HOUR` in `backend/worker_app.py`. Deliberately earlier than
the 07:00–09:00 plan-draft window, because the weigh-in happens before breakfast.
Two constants to change if you'd rather it followed your wake time.

---

## 2. The rhythm

| Cadence | You do | Ask level |
|---|---|---|
| Daily, morning | reply one number | one line |
| Daily | protein each meal + the two swaps | zero — nothing to log |
| Weekly | body-fat reading, standardized conditions (§6) | one number |
| Weekly | fuel the long run from minute 40, then mark it (§6.1) | it's training + one curl |
| **1–2× / week** | **the consult** | ~10 min |
| Sunday | prefs reconfirm + next week's plan | 2 taps |
| Monthly | calibration sprint, 5–7 days | bounded, visible end |
| Monthly | benchmark effort (fixed route/effort) | it's training |

**The app is not a daily habit and doesn't need to be.** Daily lives in Discord.
Judgment lives in the consult. The app is the weekly surface and the system of
record.

---

## 3. The consult loop — the part that does the work

### The four steps

1. **Get the blob.**
   - Daily message: **Copy for Claude** button in the nav bar.
   - Check-in (asks questions, ends in a change list):
     `curl -s https://<host>/api/coach/consult -b cookies.txt | pbcopy`

2. **Paste into a fresh Claude chat.** Answer its two or three questions. It
   waits for your answers before proposing anything.

3. **It emits a change list:**

   ```
   CHANGES TO APPLY
   prefs:    plyo_sessions_per_week  0 → 1
   skeleton: move long run Sat → Sun
   habits:   protein-first, every meal
   review:   weight trend + endurance score, 2 weeks
   ```

4. **Paste that block into `/coach`.** One textarea, right below the "Start a
   check-in" card. Save. (`/decisions` still works — it now redirects here.)

### Step 4 is the one that matters

Skipping it is what makes October's conversation identical to July's. The next
export carries the last 10 decisions with `days_ago` and a `due_for_review` flag,
so the following consult **opens by checking whether the last change worked**
instead of proposing something new on top.

When you learn the answer, hit **Record outcome** on that decision. `raw_text` is
immutable — what the consult said stays what it said — but the outcome is yours
to fill in later.

### Two templates, one payload

| Route | Shape |
|---|---|
| `GET /api/coach/export/paste` | daily message — one-way, short, four sections |
| `GET /api/coach/consult` | check-in — dialogue, ends in a change list |
| `GET /api/coach/export` | the raw JSON, for inspection |

Both templates run over the **same** export payload. Add `?window=30` to shorten.

---

## 4. Monthly calibration sprint

A **measurement week, never a diet.** 5–7 days, once a month, end date visible
from the moment it starts.

```bash
# open it
curl -X POST https://<host>/api/calibration-sprint \
  -b cookies.txt -H 'Content-Type: application/json' -d '{"days": 7}'

# check the countdown any time
curl -s https://<host>/api/calibration-sprint -b cookies.txt | jq

# close it (recalibrates maintenance)
curl -X POST https://<host>/api/calibration-sprint/close -b cookies.txt
```

Log your food for those days — that's the whole ask. On close:

- **≥5 logged days** → maintenance recalculates, `maintenance_source` flips to
  `measured`, `base_kcal` updates.
- **<5 days** → completed, **not failed**. The copy names the shortfall and moves
  on. There is no penalty state.

Log DQS servings in notes during the sprint and paste them into the consult.
That stays manual on purpose until two sprints have actually happened.

`abandon=true` on close ends it early without recalibrating.

---

## 5. What to expect — and what silence means

**Silence is the design, not a bug.** Every one of these is deliberate:

| You'll see nothing when | Because |
|---|---|
| already weighed in today | the nudge asks for a number, not confirmation |
| <6 weeks of habit data | a comparison needs weeks with AND without the habit |
| <30 paired days for the hypothesis | fewer can't locate a weight band |
| <4 populated weight bands | the range you've trained at is too narrow |
| <4 composition readings | bioimpedance is ±5 points; 3 readings show nothing |

The alternative to silence is a confident-sounding number built on nothing, which
is worse.

**Miss a week and the app gets quieter, not louder.** 7 consecutive days without
a weigh-in → nudge drops to weekly, cut verdicts go silent, nothing turns red,
copy reads *"weight tracking paused — training continues."* Three weigh-ins in a
week brings it back. One lone weigh-in deliberately does **not** — otherwise it
oscillates between nagging and silence.

**If the deficit pauses, eat more.** Five triggers can pause it:

| Trigger | Fires when |
|---|---|
| injury / illness | an open entry in the injury log |
| CTL falling | down ≥2 TSS/day over 14 days while cutting |
| scores declining | endurance or speed down 2+ weeks |
| recovery degrading | RHR up ≥3 bpm or sleep down ≥0.75 h vs baseline |
| lean mass falling | 4-week lean-mass average down 0.7 kg vs the previous 4 weeks |

Every message says **eat more**. None of them says "try harder" — that's enforced
in code, not convention.

---

## 6. Body composition — the weekly reading

Bioimpedance is bad at absolute body fat (±5 points) and acceptable at
**direction** under standardized conditions. Direction is its only job: answering
what weight alone can't — *fat or lean mass?*

Standardize or the number is noise: **same morning, post-bathroom, pre-food, same
weekday.**

Record it on the weigh-in as `body_fat_pct` (3–70, else 422). Three ways in —
use whichever fits the morning:

```bash
# with the Discord number (§1.4) — the usual path
curl -X POST https://<worker>:9100/weight-entry \
  -H "Authorization: Bearer $WORKER_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"weight_kg": 87.6, "body_fat_pct": 21.4}'

# upsert today's entry directly
curl -X PUT https://<host>/api/weight-entries/by-date \
  -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"entry_date": "2026-07-31", "weight_kg": 87.6, "body_fat_pct": 21.4}'

# add a reading to an entry already logged
curl -X PATCH https://<host>/api/weight-entries/<id> \
  -b cookies.txt -H 'Content-Type: application/json' -d '{"body_fat_pct": 21.4}'
```

Omitting the field never touches an existing reading; sending explicit `null` on
PATCH clears it. Lean mass is derived, never stored. There is **no target and no
goal line** — the trend is a guard, and its one job is to pause the deficit if
lean mass falls for three weeks.

Check it landed:

```bash
curl -s https://<host>/api/coach/export -b cookies.txt | jq '.body.composition'
```

### 6.1 Marking a long run as fuelled

The long-run-fuel habit reads `workouts.fuelled` and ticks itself. Nothing sets
it automatically — Strava and Stryd don't know whether you took a gel — so mark
it after the run:

```bash
curl -X PATCH https://<host>/api/workouts/<workout_id> \
  -b cookies.txt -H 'Content-Type: application/json' -d '{"fuelled": true}'
```

Tri-state on purpose: `null` means **unknown**, not "no". The habit only ticks on
a literal `true`, so every run logged before this existed stays unknown rather
than being back-dated to unfuelled. Only runs of 90+ minutes are considered.

Still API-only (§9) — this is the one daily-ish action without a button.

---

## 7. Weight as a hypothesis

```bash
curl -s https://<host>/api/weight-hypothesis -b cookies.txt | jq
```

It reports the weight band where **your own** scores were highest, with a
confidence level that never reaches "high", and a sentence ending *"not proof
that the weight caused it."*

There is no `target_kg` and there never will be. "As lean as I can" has no
stopping rule, which is what makes it dangerous. If the answer comes back 85 kg
rather than 79 — that's the finding, not a failure.

Your existing `WeightTarget` row is untouched; nothing was deleted. The
hypothesis replaces *relying* on it.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `meta.tracking_state: "paused"` | 7 days without a weigh-in. Log 3 in a week. |
| Export block missing, `meta.degraded` non-empty | that block's source raised; the entry names which |
| `athlete.age: null` | set date of birth in Settings → Profile |
| `volume_plays: []` | set via `PUT /api/preferences` (§1.2) |
| `habits.evidence: []` | needs 6+ weeks with *and* without the habit |
| `hypothesis.readable: false` | check `reason` — usually too few days or too narrow a range |
| Nudge never fires | check `in_window` and `logged_today` on `/api/weight/nudge` |
| `habits.goal_habits: []` | open the Habits page once — that call creates them (§1.3) |
| Weigh-in habit not ticking | it autofills; if a weight entry exists for that date and the habit is still blank, the recompute failed — check the server log for `weigh-in autofill recompute failed` |
| Long-run fuel never ticks | the run needs `fuelled: true` **and** 90+ minutes (§6.1) |
| `body.composition` empty | needs 4+ readings; confirm they saved with `GET /api/weight-entries` |
| cut review says `check_logging` | in structural mode this means **weigh-ins**, not food |

---

## 9. Still API-only

Working today over HTTP, no UI:

- `volume_plays` editing
- calibration sprint start / close / countdown
- the weight hypothesis view

**Now on screen** (was API-only):

| Was | Now |
|---|---|
| marking a long run `fuelled` | a tri-state control on the workout form |
| `body_fat_pct` on the weigh-in | accepted on create / upsert / patch, and by Hermes |
| the consult blob | icon button beside **Copy for Claude** |
| `/decisions` | a nav item (now `/coach` — the whole consult loop, one page) |
| applying a consult's prefs change | Plan → Suggest sessions → edit the prefs fields, then Save preferences |
| paused weight tracking | stated on the Weight page |
| habit correlation evidence | rendered on the Habits page |

Worth building next, in my order of preference: **the sprint countdown** (a
bounded thing with a visible end date is exactly what wants to be visible), then
**the hypothesis band**.

---

## 10. Open decisions for you

1. **Nudge window** — I assumed 06:00–08:00 BKK. Wake-time-relative instead?
2. **Body-fat auto-import** — a write path exists now (§6); still typed by hand.
   Does your scale export?
3. **Sunday consult + prefs reconfirm** — spec default was "merge into one
   touchpoint"; not merged yet.
4. **Three guardrails still deferred** — biggest deficit off the biggest training
   day, cut window closing at week 10, and an ACWR-independence test. All need
   the plan pipeline rather than the fuel model.
5. **The migration-guard convention test** — `test_ac3_add_column_guarded` fails
   for 60 of 65 migrations including two of mine. Either the checker is obsolete
   or the convention changed; worth a decision either way.
6. **`tests/test_lean_mass_protein__1359.py` doesn't collect** — it imports
   `compute_losing_lean_mass_flag` from `backend.services.cut_review`, which no
   longer exports it. Pre-dates the fixes below and is unrelated to them, but
   it's a real broken test on `develop`. Rename or restore the export?

---

## 11. What the 2026-07-31 revision fixed

Three columns shipped with readers and no writers. Each was fully implemented
and fully tested behind the API, and unreachable through it:

| Was | Now |
|---|---|
| `ensure_goal_habits()` had **zero callers** — the three goal habits were never created | `GET /api/habits` bootstraps them, so §1.3 is true |
| `weight_entries.body_fat_pct` was read by `body_composition` but absent from every weight-entry input model | accepted on create / by-date upsert / patch, and on the worker's `/weight-entry` (§6) |
| `workouts.fuelled` was read by `habit_autofill` but absent from every workout input model | accepted on workout create and patch (§6.1) |

A fourth fell out of the first: `main.py`'s weight writes never recomputed habit
autofill — only the worker's Discord path did — so a weigh-in logged in the app
left the habit unticked. Create, upsert and delete now all recompute.

No migration: every column already existed. Only the write paths were missing.
Pinned by `tests/test_lean_program__write_paths.py`, which asserts the
connections rather than the components.
