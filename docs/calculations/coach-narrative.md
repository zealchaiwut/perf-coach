# Coach narrative (Home Now / Focus / Dream / Reflection)

Deterministic **facts** → optional **LLM synthesizer** → validated Markdown
stored in `weekly_coach_messages`. The LLM may not invent TSS, unlock dates,
race times, or kg figures — only numerals present in `facts["required_numerals"]`.

## Pipeline

1. `build_coach_facts(user_id, today)` — specialists only (no LLM imports).
2. `coach_orch_langgraph.run` / plain retry — default provider is
   **`claude -p`** (`COACH_LLM=claude_cli`, Claude.ai subscription). Set
   `COACH_LLM=api` to use `llm.complete_structured` instead.
3. `validation_errors(sections, facts)` — section min length, max total chars,
   numeral allowlist.
4. On failure / CLI missing → `compose_coach_narrative(facts)`.
5. Persist `text` + nested `plan_state_snapshot`:
   `{ plan_state, facts, source, sections, orch, attempts }`.

Env: `COACH_LLM=claude_cli|api`, `COACH_ORCH=langgraph|plain`,
`COACH_CLAUDE_MODEL` (see `docs/llm-coaching.md`).

## Focus ranking (Phase 2)

`rank_focus_levers` scores candidates from load lock/availability, weight
measurement/deficit phase, gap advisories, and recent volume-mix flags
(missing long / quality). Top 2 are Focus; remainder become `focus_noise`.

## Dream (Phase 3)

Prefers Plan **A-race** + `race_checkpoints`. Scenarios include plan-compliance
finish, current CTL trend, and an optional weight-cut heuristic:

- **~0.8% finish-time improvement per kg** lost (conservative; not a guarantee).
- Only emitted when `gap_kg ≥ 2` and a base finish seconds exist.
- Cap displayed cut at `min(6, gap_kg)` kg.

## Reflection (Phase 4)

Uses `daily_brief._assemble_recent_wrap` for planned vs completed sessions,
benchmarks from Focus #1/#2 tracking, and the next planned session CTA.
`facts["nudge"]` exposes Focus #1 + next_action for Hermes / Home Advisories.
