# The lean program

Lose fat without losing fitness, on a program built for how adherence actually
behaves. The design premise is that motivation decays predictably, so the app
**lowers its demands when the athlete slips instead of escalating**. A cut the app
pauses is a cut that wasn't failed.

Everything here is code. The only LLM in the loop is the consult, which happens
outside perf-coach by design.

> Status: **Phases 0 and 1 complete.** Phases 2–4 are specified in the sprint
> plan and not yet built. This document describes what exists and marks the rest.

## Governing decisions

| # | Decision |
|---|---|
| D1 | Deficit is the target; diet quality and protein are the mechanism. Structural, not managed |
| D6 | Three goal habits only: weigh-in, protein-first, long-run fuel |
| D7 | Never a food nudge. Weight nudge only, morning window, one per day, silent when there's nothing to ask |
| D8 | Weekly verdicts only. No daily verdicts, no streaks anywhere near food |
| D9 | `CHANGES TO APPLY` is stored in the app DB — not Notion, not a local file |
| D11 | 7 consecutive days without a weigh-in → tracking pauses |
| D12 | All of this is code. The only LLM is the consult, outside the app |

## Phase 0 — the persistent loop *(built)*

Phase 1 is the more satisfying build, but without Phase 0 the same conversation
happens in October with no way to know whether anything worked.

### The decision log

| Piece | Where |
|---|---|
| `decisions` table | `backend/models.py` → `Decision`, migration `a87e213dedbb` |
| Endpoints | `backend/routers/decisions.py` |
| Log view | `/decisions` → `frontend/pages/decisions.html` + `frontend/js/decisions.js` |
| Export block | `coach_export._assemble_decisions` |

**There is no parser, deliberately.** A consult produces a `CHANGES TO APPLY`
block; that block is pasted into one textarea and stored verbatim as `raw_text`.
A parser is a project; a textarea is an afternoon, and the value is in having the
history at all.

`raw_text` is immutable. Only the outcome fields (`applied`, `outcome_note`,
`review_on`, `tags`) can be patched, so what the consult actually said can't be
rewritten after the answer is known.

| Route | Purpose |
|---|---|
| `POST /api/decisions` | Store one pasted change list. 201 with the stored row |
| `GET /api/decisions?limit=` | Newest-first log — the view and the export both read this |
| `PATCH /api/decisions/{id}` | Record how it turned out (`outcome_note`, `applied`, `review_on`, `tags`) |
| `DELETE /api/decisions/{id}` | Remove a mis-pasted entry |

A decision with no review date is one nobody ever checks, so `review_on` defaults
to two weeks out. The export computes `due_for_review` — a review date that has
passed with no outcome recorded is the single most actionable thing in the block.

### The consult template

`coach_export.CONSULT_TEMPLATE` + `build_consult_blob()`, served at
`GET /api/coach/consult`. A second template over the **same** payload the daily
message uses — that's the reason both live server-side and versioned.

Where the daily message is one-way and short, the consult is a dialogue: it asks
two or three questions, waits for answers, then emits a change list capped at one
or two changes. Its rules extend the daily ones with four that matter for this
program:

- a `paused` tracking state means don't push on weight data — ask about training
- an active auto-pause is deliberate; support it, don't undo it
- read `decisions[]` first and don't re-propose what was declined or is running
- food suggestions come from `volume_plays[]` — don't invent a meal plan

Unlike the daily paste, the consult does **not** stamp `last_coach_export_at`. A
check-in is a conversation, not the daily message; consuming that signal would
silence the next day's season check.

### `volume_plays`

A `pref_catalog` field (`list[str]`, ≤10 items, ≤80 chars each) holding the
athlete's own high-volume dishes. The consult suggests *from* this list. A recipe
database is out of scope — this is a list of dish names and nothing more.

### Export additions

`SCHEMA_VERSION` 1 → 2, `PROMPT_VERSION` → `coach-paste-v2`, plus the new
`CONSULT_PROMPT_VERSION`. New top-level blocks:

```jsonc
"decisions":    [ {decided_on, days_ago, raw_text, tags, applied,
                   outcome_note, review_on, due_for_review} ],   // last 10
"volume_plays": [ "…" ]
```

### Acceptance

A consult produces a change list → pasted into one field → appears in the next
export, dated → the following consult references it by date.
`tests/test_lean_program__decisions.py::test_round_trip_consult_to_export_references_it_by_date`.

## Phase 1 — the daily floor *(built)*

Daily lives in Discord, not in the app. The app is the weekly surface and the
system of record; it does not need to be opened every day and is not designed to
be.

### Where the Discord part actually runs

**perf-coach never talks to Discord.** Hermes polls a notify endpoint and
delivers. This mirrors the existing `plan_draft_notify` contract so there is one
pattern for morning-window nudges rather than two:

| Piece | Where |
|---|---|
| Weight write | `POST /weight-entry` on the worker (`backend/worker_app.py`), bearer `WORKER_API_TOKEN` |
| Nudge payload | `GET /api/weight/nudge` on the worker |
| State machine | `backend/services/tracking_state.py` |
| Weigh-in autofill | `habit_autofill` source `weight.logged` (migration `1fff1ada408b`) |

Everything else in the lean program rests on the write endpoint. It upserts on
`(user, date)` with a null `entry_time`, so replying twice in one morning
*corrects* the number rather than creating a second row — which is what "reply
87.6" should mean. Entries are stored with `source='imported'`.

### The weigh-in habit ticks itself

`auto_fill_source = 'weight.logged'` fills the habit from the weight entry. A
number replied in Discord **is** the habit; asking for a confirmation tap in the
app is exactly the kind of demand this program removes. The autofill is
best-effort — a habit that failed to tick must never cost the athlete the
weigh-in itself.

### Tracking state

```
        ACTIVE ──── 7 consecutive days, no weigh-in ────► PAUSED
          ▲                                                 │
          └──── 3 weigh-ins within 7 days ──────────────────┘
```

- **ACTIVE** — daily nudge, cut diagnosis on, rate shown.
- **PAUSED** — nudge drops to **weekly, not to nothing** (lower demand, not
  abandonment). Copy: *"weight tracking paused — training continues."* No cut
  verdicts, no rate claims, nothing red, no catch-up guilt. Training is
  unaffected.

**Derived, never stored** — a pure function over weigh-in dates, so it cannot go
stale behind a job that didn't run, and all four consumers (nudge, `cut_review`,
weight card, `meta.tracking_state` in the export) compute the same answer.

The state machine is **simulated over the timeline**, not judged from the last
few days in isolation. That distinction is load-bearing: a stateless reading
can't tell "was paused, then logged once" from "has been logging", so a single
Tuesday weigh-in would silently restart the daily nudge. The thresholds are
asymmetric on purpose (7 days out, 3 weigh-ins back) so the state can't chatter.

### The nudge

One message type. **Weight only, never food** — a food nudge is the fastest way
to make a daily prompt something the athlete mutes, and a muted app can't help.
Silent when today is already logged: the nudge exists to ask for a number, not to
confirm one. `deliver_now` is true only inside the BKK morning window
(06:00–08:00, deliberately earlier than the 07:00–09:00 plan-draft window —
the weigh-in happens before breakfast) with the cadence satisfied.

Silence is the correct output most mornings, and the endpoint says so rather than
inventing something to say.

### Export addition

`meta.tracking_state` and `meta.paused_since`, so a pasted coach knows not to nag
about data the app deliberately stopped asking for (consult rule 3).

### Acceptance

Reply `87.6` in Discord → entry stored, habit ticked, nudge silent next morning.
Miss 7 days → nudge goes weekly and the copy changes; log 3 in a week → back to
ACTIVE. `tests/test_lean_program__weight_write.py`,
`tests/test_lean_program__tracking_state.py`.

## Phases 2–4 *(specified, not built)*

| Phase | Contents |
|---|---|
| 2 — structural deficit | Deficit set once and verified weekly, `fuel_periodize` enabled, carb floor on quality days, `cut_review` re-gated to weight-trend-only, body-fat storage + lean-mass guard, auto-pause triggers |
| 3 — habits & week composition | Three goal habits, stretch/plyo/drills moved into the plan, monthly benchmark effort, correlation evidence instead of streaks |
| 4 — sprints & the hypothesis | Calibration sprint flag, maintenance recalibration, target weight as a hypothesis rather than a fixed number |

Two guardrail families gate all of it, and none of them involve an LLM:

**Always on** — EA floor (`30 × lean_mass_kg + burn`), `budget >= bmr_estimate`,
max deficit 500 kcal/day (reject > 750), protein 2.0 g/kg, a carb floor on quality
days independent of the deficit, rate cap −0.5 %BW/week, never the biggest deficit
on the biggest training day, cut window closes at week 10, ACWR ceiling
independent of any weight goal.

**Auto-pause the deficit** (copy always says *eat more*, never "try harder") —
niggle or illness logged, CTL falling while the deficit is on, endurance/speed
declining 2+ weeks, RHR rising or sleep degrading, lean-mass trend falling 3+
weeks.

**Tracking-state degradation** — `ACTIVE` → `PAUSED` after 7 consecutive days with
no weigh-in; back to `ACTIVE` after 3 weigh-ins within 7 days. Derived from
weigh-in dates by a pure function, never stored, so it can't go stale.

## Open items

- Discord nudge window: **assumed 06:00–08:00 BKK** and implemented as
  `_WEIGHT_NUDGE_START_HOUR` / `_WEIGHT_NUDGE_END_HOUR` in `worker_app.py` — two
  constants to change if it should follow the actual wake time instead.
- Body-fat scale: assume the weekly reading is typed by hand; auto-import is a
  bonus, not a dependency.
- Whether the Sunday consult and the Sunday prefs reconfirm merge into one
  touchpoint (default: yes).

## Out of scope

Continuous calorie or macro tracking; any daily food verdict; parsing a consult
reply back into the app; a Notion integration beyond an optional later one-way
mirror; any LLM inside perf-coach; body-composition targets or peer-percentile
leanness goals; a recipe database.
