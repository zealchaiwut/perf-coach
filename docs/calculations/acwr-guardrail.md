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

## Known weaknesses

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
