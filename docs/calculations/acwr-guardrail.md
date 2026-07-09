# ACWR & Guardrail — Injury-Risk Heuristics

**Purpose:** warn when training load ramps too fast (acute:chronic workload
ratio) or when multiple stressors rise together (guardrail).

## ACWR (`backend/services/acwr.py`)

- Acute = last-7-day TSS sum; chronic = mean of up to 4 **prior** 7-day
  totals (days −35…−8; the acute week is excluded — an "uncoupled" variant)
  (acwr.py:62-193, chronic at :149-163).
- Bands: <0.8 detraining, >1.5 high_risk (`LOWER_BOUND=0.8`,
  `HIGH_BOUND=1.5`; `UPPER_BOUND=1.3` defined but unused for banding,
  :33-39). <28 days of data ⇒ `baseline_forming`.
- Note: frontend also computes ACWR client-side from raw daily-load series
  (`training-performance.js:459-478`) — one concept, two homes.

## Guardrail (`backend/services/guardrail.py`)

- Warn when ACWR high_risk OR ≥2 of 3 stressors rose >20 % week-over-week
  (`STRESSOR_RAMP_THRESHOLD_PCT=20`, :46).
- Stressors (:189-321): weekly run TSS; plyo session count
  (`workout_type LIKE '%plyo%'`); weight-loss kg/week (first-vs-last entry).
- Zero baseline + any positive current = "sharp rise" (:49-63).

## Verdict thresholds (`backend/services/training_verdict.py`)

The deterministic `back_off` / `hold` / `build` verdict for the weekly coach
report and the Plan tab (see `docs/calculations/load-plan.md`) uses its own
named thresholds, checked in this order:

| Constant | Value | Fires when |
|---|---|---|
| `ACWR_BACK_OFF_THRESHOLD` | 1.5 | `acwr > 1.5` → `back_off` (mirrors `acwr.HIGH_BOUND`) |
| `ACWR_HOLD_THRESHOLD` | 1.3 | `acwr > 1.3` → `hold` (mirrors `acwr.UPPER_BOUND`) |
| `ATL_CTL_HOLD_RATIO` | 1.25 | `atl > 1.25 × ctl` → `hold` — catches a fresh spike ACWR's 28-day chronic window hasn't caught up to yet |
| `TSB_HOLD_FLOOR` | −25 | `tsb < −25` → `hold` — stricter than `training_load.FORM_BURIED_CEILING` (−10), which is a routine-fatigue label, not a hold trigger |

The `ATL_CTL_HOLD_RATIO` and `TSB_HOLD_FLOOR` checks only apply once
`ctl > _MIN_CTL_FOR_HOLD_GUARDS` (15.0). Below that floor the athlete is
cold-starting — a brand-new user, or anyone returning after a long break —
and CTL (42-day EWMA) hasn't had time to reflect any real fitness yet, while
ATL (7-day EWMA) reacts to the first workout immediately. Without the floor,
literally every new user's first logged workout would trip `hold`, which is
the same perpetual-flatline failure this whole fix removes, just moved from
the old static ceiling to the verdict layer. The ACWR checks don't need this
guard: `compute_acwr` already returns `None` during its own `baseline_forming`
window (see above), and both ACWR branches are gated on `is not None`.

Anything not caught by the above is `build`. The convergence estimate
(`expected_ctl_in_3w`, `weeks_to_converge`, `converge_date`) attached to a
non-`build` verdict is a **separate, simpler** approximation — it projects
CTL toward ATL under a "hold current load steady" assumption using the
ATL:CTL ratio, not a re-simulation of the real windowed ACWR (which would
need per-day load assumptions the verdict function isn't given). Label it as
an estimate wherever it's surfaced; do not present it as a forecast.

**ACWR's injury-predictive validity is contested in the sports-science
literature** — the rolling-average variant used here (see "Known weaknesses"
below) is specifically the one most criticized. The verdict and any report
text derived from it should read as a load-management flag ("this is
outside your recent normal range"), never as a medical diagnosis or an
injury prediction.

## Known weaknesses

0. **No override mechanism exists yet for the verdict.** The athlete has no
   way to say "I know the verdict says hold, I'm doing this anyway" and have
   that logged. Spec intent (subjective signals — sleep, resting HR, morning
   legs — can outweigh a load-only verdict): when an override UI is built,
   log `{verdict, user_action, date}` per override so the thresholds
   (`ACWR_BACK_OFF_THRESHOLD` etc.) can eventually be evaluated against real
   outcomes — an easily-ignored rule with no feedback loop gets ignored on
   exactly the days it matters. **TODO**, not built in this pass.
1. Rolling-average ACWR is the variant most criticized in the literature —
   EWMA-ACWR is preferred, and the codebase already computes EWMAs everywhere
   else.
2. Zero-baseline rule fires on the athlete's first-ever plyo session.
3. Weight-loss rate from two endpoint samples is noisy; `weight_ewma_rate.py`
   exists but is not used here.
4. Not cached; computed live.

## ML-readiness

- **Blocking gap: injury/illness labels are not collected at all.** This is
  the single most valuable missing log in the app. Without "was injured /
  sick / missed planned sessions" events, no learned risk model is possible.
- Once labels exist: survival analysis or binary classification over rolling
  load features (EWMA-ACWR, monotony, strain, readiness trend, weight-loss
  EWMA rate).
- Until then, cheap wins are heuristic: EWMA-ACWR, weight EWMA rate, min
  session count before plyo ramp warnings.
