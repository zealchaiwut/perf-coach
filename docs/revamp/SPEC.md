# Revamp specification — Phase 0 contract

This document is the shared vocabulary and review rules for the perf-coach desktop
revamp. Later phases and issues must not redefine these terms.

See also [README.md](README.md) (mock vs issue rule) and [INDEX.md](INDEX.md) (screen map).

## Glossary

| Term | Definition |
|------|------------|
| **Week** | Monday 00:00 through Sunday 23:59, **Asia/Bangkok**. Never server-local midnight. |
| **Coach session** | A running session supplied by the human coach, locked in the planner. |
| **Support session** | Strength, plyo, mobility, or drills — planned by the athlete in the app. |
| **Session status** | One of `planned`, `done`, `missed`, `skipped`. |
| **Unplanned** | A `done` session with no matching planned item. |
| **Overall score** | Endurance or Speed computed across **all** qualifying runs (the athlete-level number on Performance). |
| **Race-specific score** | The same axis scored **for one race distance** (projection / race card context). |
| **Session signal** | What a **single session** contributed to a score axis, with a reason when it did not contribute. |

## Mock versus issue

- The **mock** owns layout, hierarchy, copy tone, colours, and spacing.
- The **issue** owns numbers, formulas, and business rules. If they disagree, **the issue wins**.
- Mock numbers are illustrative; do not copy them into fixtures or seed data.
- Details: [README.md § How issues should use the mocks](README.md#how-issues-should-use-the-mocks).

## Revamp feature flag

| Surface | Name | How to enable locally |
|---------|------|------------------------|
| Environment | `REVAMP_UI=1` | Set in `.env` (webapp reads at startup). When unset or `0`, all `/v2/*` routes return **404**. |
| Per-user override (optional) | `users.revamp_ui_enabled` | Reserved for P0-7; until the column exists, only the env flag applies. |

Old navigation and routes are unchanged when the flag is off. When on, the legacy nav shows one link into `/v2/home`; the v2 shell shows one link back.

## Definition of done (revamp issues)

Every revamp implementation issue is done when:

1. **Behind the flag** — no visible change with `REVAMP_UI` off.
2. **Mock parity** — matches the named mock region at **1440 px** wide (preview under `docs/revamp/mocks/preview/`).
3. **Phase 0 readers** — session TSS, weekly rollup, and scores come only from the sanctioned readers (`session_tss`, `weekly_rollup`, score reader module), not ad-hoc queries.
4. **States** — empty, loading, and error states are implemented.
5. **Accessibility** — keyboard reachable; visible focus rings; touch targets ≥ 44 px where interactive.
6. **Tests** — pytest (or contract tests where applicable) for every rule stated in the issue.
7. **No regressions** — existing pages and API shapes unchanged when the flag is off.

## Phase checkpoint procedure

At the end of each phase:

1. Open each relevant preview in `docs/revamp/mocks/preview/` beside the running page (flag on).
2. Record layout, copy, or number mismatches as **follow-up GitHub issues** labelled `revamp` and the phase label (e.g. `phase-0`).
3. For Phase 0, the checkpoint is **data agreement** first (see issue #1826); pixels second (components page vs mocks).