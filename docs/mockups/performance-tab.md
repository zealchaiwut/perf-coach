# Performance Sub-tab — Visual Reference (issue #811)

This document is the approved visual reference for the Training > Performance sub-tab layout.

## Layout (desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  [Log]  [Plan]  [Performance]   ← gradient pill tabs               │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐  ┌──────────────────────────┐
│  ENDURANCE               │  │  SPEED                   │
│                          │  │                          │
│  ◯ (ring, 0–100)  72     │  │  ◯ (ring, 0–100)  58     │
│                  ↑ impr. │  │                  → flat  │
│              ___/  spark │  │         ____/     spark  │
└──────────────────────────┘  └──────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Fitness · Fatigue · Form                  [30D] [90D] [6M] [1Y]  │
│  CTL = fitness (42-day), ATL = fatigue (7-day), TSB = form.        │
│                                                                     │
│  ↑ CTL ──────────────────────────────────────────────────────────  │
│    ATL ···················────────────────────────────────────────  │
│    TSB ────────────────────────────────····──────────────────────  │
│                                          ↑ today                   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Training Load Ratio (ACWR)                                        │
│                                                                     │
│  Ratio   1.12    [ optimal ]                                       │
│  Training load is in the optimal range. Continue current stress.   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Personal Records                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ 5K       │  │ 10K      │  │ Half     │  │ Full     │          │
│  │ 18:45    │  │ 40:12    │  │ 1:28:30  │  │ 3:05:00  │          │
│  │ 2026-03  │  │ 2025-11  │  │ 2025-09  │  │ 2025-04  │          │
│  │ View →   │  │ View →   │  │ View →   │  │ View →   │          │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

## States

### Building-baseline (score card)
Ring and sparkline are hidden; a "Building baseline" notice replaces them.
No number is shown, no partial ring fill is rendered.

### Building-baseline (fitness chart)
A "Building baseline — keep training to see the fitness chart." message is shown
in place of the canvas.

### ACWR baseline forming
Ratio and guidance are suppressed; a "Baseline forming" note is shown instead.
Requires at least 28 days of training load history.

### Null field
Any null value renders as `—`; no fabricated number or zero is shown.

### Missing threshold
When `preferences` are absent, each affected score card shows a quiet inline hint:
"Set your threshold in Settings to compute this score."

## Endpoints used

| Section           | Endpoint                                        |
|-------------------|-------------------------------------------------|
| Score cards       | `GET /api/athletes/{id}/performance`            |
| Fitness chart     | `GET /api/performance/chart`                    |
| ACWR              | Computed client-side from `GET /api/athletes/{id}/daily-load` |
| Personal records  | `GET /api/personal-records`                     |

## Design tokens

All colors use existing gradient-theme CSS variables:
`--bg-1`, `--bg-2`, `--shell-1`, `--shell-2`, `--card-bg`, `--card-border`,
`--card-shadow`, `--card-radius`, `--text-primary`, `--text-secondary`,
`--text-tertiary`, `--green`, `--green-soft`, `--red`, `--red-soft`,
`--amber`, `--amber-soft`, `--mono`.

No new color tokens were introduced.
