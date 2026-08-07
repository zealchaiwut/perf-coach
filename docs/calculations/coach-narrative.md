# Coach narrative (Home Now / Focus / Dream / Reflection)

Deterministic **facts** → optional **LLM synthesizer** → validated Markdown
stored in `weekly_coach_messages`. The LLM may not invent TSS, unlock dates,
race times, or kg figures — only numerals present in `facts["required_numerals"]`.

## Pipeline

1. `build_coach_facts(user_id, today)` — specialists only (no LLM imports).
2. `weekly_coach_message._call_llm_narrative` — on the **compute worker**,
   rewrites the deterministic prose using `LLM_COACH_ENABLED` + provider API key
   (GLM → Cerebras → Groq). Webapps only read the stored message; they never
   invoke the rephrase.
3. `_numbers_preserved(original, rephrased)` — discards any rephrase whose
   numerals drift from the deterministic input.
4. On failure / disabled → deterministic text from `compose_deterministic_message`.
5. Persist `text` + nested `plan_state_snapshot`:
   `{ plan_state, facts, source, sections, orch, attempts }`.

**Where it runs:** scheduled `daily_coach` job on zeal-server (`docs/worker.md`);
`weekly_coach` is a dispatch alias.
Web Home Coach tab only reads `GET /api/coach/daily-message`.

Env: `LLM_COACH_ENABLED`, `LLM_PROVIDER`, `PERFCOACH_ROLE`, `WORKER_DAILY_COACH_ENABLED`
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
