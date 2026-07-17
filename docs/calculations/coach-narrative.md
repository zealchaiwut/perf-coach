# Coach narrative (Home Now / Focus / Dream / Reflection)

Deterministic **facts** → optional **LLM synthesizer** → validated Markdown
stored in `weekly_coach_messages`. The LLM may not invent TSS, unlock dates,
race times, or kg figures — only numerals present in `facts["required_numerals"]`.

## Pipeline

1. `build_coach_facts(user_id, today)` — specialists only (no LLM imports).
2. `coach_orch_langgraph.run` / plain retry — on the **compute worker**,
   provider is **`claude -p`** (`PERFCOACH_ROLE=worker` → `COACH_LLM=claude_cli`).
   Webapps default to `off` (deterministic only). Set `COACH_LLM=api` only if
   you intentionally want HTTP `complete_structured`.
3. `validation_errors(sections, facts)` — section min length, max total chars,
   numeral allowlist.
4. On failure / CLI missing → `compose_coach_narrative(facts)`.
5. Persist `text` + nested `plan_state_snapshot`:
   `{ plan_state, facts, source, sections, orch, attempts }`.

**Where it runs:** scheduled `weekly_coach` job on zeal-server (`docs/worker.md`).
Web Home Coach tab only reads `GET /api/coach/weekly-message`.

Env: `COACH_LLM`, `PERFCOACH_ROLE`, `COACH_ORCH`, `WORKER_WEEKLY_COACH_*`
(see `docs/llm-coaching.md`).

## Focus ranking (Phase 2)

`rank_focus_levers` scores candidates from load lock/availability, weight
measurement/deficit phase, gap advisories, and recent volume-mix flags
(missing long / quality). Top 2 are Focus; remainder become `focus_noise`.

## Dream (Phase 3)

## Dream (Phase 3)

## Dream (Phase 3)

Prefers Plan **A-race** + curated **milestones** (1–2 near-term B/C races —
half-or-longer preferred, not every race on the calendar) +
`race_checkpoints`. Also surfaces Performance-tab **Endurance / Speed** scores
from `SummaryCache`. Finish estimates for Dream /
`projection.current_trend_*` come from the **Performance race-day time_curve
SoT** (`race_finish_estimate.estimate_race_finish` — same tip as the race card),
**not** the legacy CTL √-ratio invent in `weekly_coach_message._estimate_current_trend`.
Scenarios include plan-compliance (A-race goal), that Performance estimate when
available, and an optional weight-cut heuristic:

- **~0.8% finish-time improvement per kg** lost (conservative; not a guarantee).
- Only emitted when `gap_kg ≥ 2` and a base finish seconds exist.
- Cap displayed cut at `min(6, gap_kg)` kg.

## Reflection (Phase 4)

Uses `daily_brief._assemble_recent_wrap` for planned vs completed sessions,
benchmarks from Focus #1/#2 tracking, and the next planned session CTA.
`facts["nudge"]` exposes Focus #1 + next_action for Hermes / Home Advisories.
