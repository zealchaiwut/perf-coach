# Weight tab revamp — Pass 0 audit

Findings recorded before Pass 1 so the three-rate bug cannot recur unnoticed.

## The three rates (pre-revamp)

| # | UI surface | Computation | Window / method | File:line (approx) |
|---|---|---|---|---|
| 1 | Header subtitle `trending ↑ X kg/wk` | `stats.delta_7d_kg` — **raw** last weigh-in minus weigh-in ≤7d earlier | 7 calendar days, unsmoothed | `frontend/js/weight.js` ~180–186; produced in `backend/main.py` `/api/weight-chart` ~2003–2008 |
| 2 | Current-weight card `EWMA TREND ↑ +Y kg/wk` | `stats.weekly_rate_ewma_kg` — EWMA\[today\] − EWMA\[today−7\] | 7 day two-point EWMA difference (`DEFAULT_SPAN=14` → α≈0.133) | `frontend/js/lib/weight-current-card.js` ~111–123; `backend/main.py` ~1963–1973 |
| 3 | Weekly cut review `ACTUAL RATE` | `%BW` EWMA change via `compute_weekly_pct_bw_rate_of_change`, × first weight in window | 21d EWMA seed, 7d % rate | `backend/services/cut_review.py` `get_weekly_review` ~401–414 |

**Canonical (Pass 1):** `backend/services/weight_stats.weight_stats` — OLS slope on EWMA (α=0.18) over `window_days` (default 30), with 95% CI; `readable` iff `coverage_pct ≥ 70` and `entries_used ≥ 21`. Built on `weight_trend_rate.compute_trend_rate` (coach export keeps its own 40%/5 defaults via kwargs).

Regression: `tests/test_weight_stats__revamp.py` asserts chart `stats.rate` and cut-review `actual_rate` share the same kg/wk for identical inputs.

## Other locations noted

| Item | Location | Notes |
|---|---|---|
| `_computeStreak` / `_computeAdherence` / `renderStreakAndAdherence` | `frontend/js/weight.js` ~118–156 | Streak removed in Pass 6; adherence renamed to coverage |
| `MIN_ADHERENCE_PCT = 70` | `backend/services/cut_review.py` ~42 | Fuel-log gate; structural mode already bypassed in lean program — Pass 1 adds `insufficient_coverage` on weigh-in coverage instead |
| Goal/plan coupling (`behind plan`, `0%` progress) | `frontend/js/weight.js` `renderProgress` ~259–380; `#progress-card` in `weight.html` | Driven by `WeightTarget` plan_today / gap / progress_pct — removed from tab in Pass 5 |
| Decisions | `backend/models.Decision`, `/api/decisions` (`backend/routers/decisions.py`) | **Exists** — timeline markers can consume it; do not rebuild |
| Hypothesis API | `GET /api/weight-hypothesis` | **Exists** — Pass 5 consumes |
| Existing trend-rate module | `backend/services/weight_trend_rate.py` + `docs/calculations/weight-trend-rate.md` | Coach export consumer; extended with kwargs rather than forked math |

## Chart domain bug (Pass 4 motivation)

`weight-chart.js` historically includes goal / raw outliers in the y-domain, which can squash a ~0.5 kg month of EWMA movement when a distant goal (e.g. 75 kg vs 88 kg trend) is plotted. Pass 4 domain is trend-only ±0.35 kg, snapped to 0.5; goal line omitted when outside domain.
