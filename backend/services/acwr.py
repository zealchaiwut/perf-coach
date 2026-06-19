"""
Acute:Chronic Workload Ratio (ACWR) — training-load guidance function.

This module provides a single pure function, ``compute_acwr``, that classifies
an athlete's current training load relative to their recent training history.
All database work belongs to the calling layer; this module contains no SQL,
file access, or network calls.

Math
----
Acute load is the sum of daily load values over the most recent seven days.

Chronic load is the mean of four consecutive weekly totals, each spanning seven
days, covering approximately the last twenty-eight days.

The ratio is acute load divided by chronic load.  When chronic load is zero the
ratio is undefined and the function returns a null result with an explanatory
reason.

Worked example
--------------
An acute seven-day total of three hundred fifty divided by a chronic weekly
average of three hundred yields a ratio of approximately one point one seven,
which falls in the productive band.  In numeric terms: three hundred fifty
divided by three hundred equals one point one six repeating, which lies between
the lower bound of zero point eight and the upper bound of one point three.
"""

from __future__ import annotations

# ── Classification thresholds ─────────────────────────────────────────────────
# Below this ratio the athlete is undertraining relative to their chronic load.
LOWER_BOUND: float = 0.8
# Above this ratio (and at or below HIGH_BOUND) the load is elevated but within
# an acceptable range.
UPPER_BOUND: float = 1.3
# Above this ratio the acute spike is large enough to significantly raise injury
# risk.
HIGH_BOUND: float = 1.5

# ── Minimum history requirement ───────────────────────────────────────────────
# Fewer than this many days of data means the chronic baseline is not yet
# established.
_MIN_DAYS: int = 28

_GUIDANCE = {
    "detraining": (
        "Current acute load is well below your chronic baseline. "
        "Consider gradually increasing training volume to maintain fitness adaptations."
    ),
    "productive": (
        "Training load is in the optimal range. "
        "Continue current training stress to build fitness while managing injury risk."
    ),
    "high_risk": (
        "Acute load spike is significantly above chronic baseline. "
        "Reduce training volume immediately to lower injury risk."
    ),
}


def compute_acwr(daily_load_series) -> dict:
    """Compute the Acute:Chronic Workload Ratio and return a guidance object.

    This is a pure function: given the same input it always returns the same
    output.  It performs no database access, file reads, or network calls.

    Parameters
    ----------
    daily_load_series:
        An ordered sequence of numeric daily load values, most recent last.
        Must be iterable and have a length.  Values should be non-negative
        numbers; non-numeric values are treated as zero.

    Returns
    -------
    dict with exactly four keys:

    ``ratio``
        The computed ACWR (acute divided by chronic), or None when the ratio
        cannot be computed.

    ``band``
        One of four strings: ``"detraining"``, ``"productive"``,
        ``"high_risk"``, or ``"baseline_forming"``.  None when input is
        invalid.

    ``guidance``
        A plain-language string advising the athlete on their current load
        status.  None when the band is ``"baseline_forming"`` or input is
        invalid.

    ``debug``
        Dict with numeric fields ``acute_load``, ``chronic_load``,
        ``lower_bound``, ``upper_bound``, and ``high_bound``.

    On invalid input (None, non-iterable, or non-sequence) an additional
    ``reason`` key is included and ``ratio``/``band`` are None.

    On zero chronic load an additional ``reason`` key is included and
    ``ratio`` is None.

    Worked example
    --------------
    An acute seven-day total of three hundred fifty divided by a chronic
    weekly average of three hundred yields a ratio of approximately one point
    one seven, which falls in the productive band.
    """
    # ── Input validation ──────────────────────────────────────────────────────
    if daily_load_series is None:
        return {
            "ratio": None,
            "band": None,
            "guidance": None,
            "debug": _debug(None, None),
            "reason": "daily_load_series is None; a sequence of numeric daily load values is required",
        }

    try:
        n = len(daily_load_series)
        series = list(daily_load_series)
    except TypeError:
        return {
            "ratio": None,
            "band": None,
            "guidance": None,
            "debug": _debug(None, None),
            "reason": "daily_load_series must be a sequence with a length; received an unsupported type",
        }

    # ── Baseline forming ──────────────────────────────────────────────────────
    if n < _MIN_DAYS:
        return {
            "ratio": None,
            "band": "baseline_forming",
            "guidance": None,
            "debug": _debug(None, None),
        }

    # ── Compute acute and chronic loads ───────────────────────────────────────
    def _safe_float(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    vals = [_safe_float(v) for v in series]

    acute = sum(vals[-7:])

    # Chronic uses up to four weekly windows that fall BEFORE the acute window.
    # Each window is seven days; the oldest possible window is days[-35:-28].
    # For a 28-day series only three prior windows exist; for 35+ days all four
    # are available.  Python silently returns an empty slice for out-of-bounds
    # negative indices, so the filter below handles short series cleanly.
    prior_week_windows = [
        vals[-35:-28],
        vals[-28:-21],
        vals[-21:-14],
        vals[-14:-7],
    ]
    prior_week_totals = [sum(w) for w in prior_week_windows if w]
    chronic = sum(prior_week_totals) / len(prior_week_totals) if prior_week_totals else 0.0

    # ── Guard against zero chronic load ───────────────────────────────────────
    if chronic == 0.0:
        return {
            "ratio": None,
            "band": None,
            "guidance": None,
            "debug": _debug(acute, chronic),
            "reason": "chronic load is zero; cannot compute a meaningful ratio",
        }

    ratio = acute / chronic

    # ── Classify ──────────────────────────────────────────────────────────────
    # The four bands span: detraining (below lower), productive (lower to high),
    # and high_risk (above high).  UPPER_BOUND marks the top of the ideal range
    # within productive but does not define a separate band.
    if ratio < LOWER_BOUND:
        band = "detraining"
    elif ratio > HIGH_BOUND:
        band = "high_risk"
    else:
        band = "productive"

    return {
        "ratio": ratio,
        "band": band,
        "guidance": _GUIDANCE[band],
        "debug": _debug(acute, chronic),
    }


def _debug(acute_load, chronic_load) -> dict:
    """Build the debug sub-dict with load values and the current bound constants."""
    return {
        "acute_load": acute_load,
        "chronic_load": chronic_load,
        "lower_bound": LOWER_BOUND,
        "upper_bound": UPPER_BOUND,
        "high_bound": HIGH_BOUND,
    }
