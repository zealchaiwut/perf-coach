"""Rolling intensity distribution over configurable trailing windows.

compute_rolling_intensity_distribution is a pure function: no database calls,
no side effects.  It accepts a list of session records (each carrying a date,
duration, and low/moderate/high intensity values) and produces a
duration-weighted rolling distribution for every calendar date in the covered
range [min_session_date, max_session_date].

Output values per date sum to 1.0 within floating-point tolerance.
Dates whose trailing window contains no sessions return None for all three
bands.

Default windows: 7 days and 28 days.
"""

from collections import defaultdict
from datetime import date, timedelta


def compute_rolling_intensity_distribution(sessions, windows=(7, 28)):
    """Compute duration-weighted rolling intensity distribution.

    Args:
        sessions: iterable of dicts (or objects with matching attributes),
            each with:
                date        str "YYYY-MM-DD" or datetime.date
                duration    positive numeric weight (e.g. seconds)
                low         low-intensity value (fraction or percentage)
                moderate    moderate-intensity value (same scale)
                high        high-intensity value (same scale)
            Within each session low + moderate + high should equal 1.0
            (or 100 if using percentages).
        windows: sequence of trailing-window sizes in calendar days.
            Default is (7, 28).

    Returns:
        dict mapping ISO date string ("YYYY-MM-DD") to a dict keyed by
        window size (int).  Each window-size value is a dict::

            {"low": float|None, "moderate": float|None, "high": float|None}

        Values are in the same scale as the input (fractions or percentages)
        and sum to 1.0 (or 100) within floating-point tolerance.  None
        indicates that no sessions existed in the trailing window.

        Only dates in the closed range [min_session_date, max_session_date]
        are included in the output.  Calendar dates with no sessions of their
        own are still included; their distribution is computed from sessions
        that fall in the trailing window ending on that date.
    """
    if not sessions:
        return {}

    normalised = _normalise(sessions)
    normalised.sort(key=lambda r: r[0])

    min_date = normalised[0][0]
    max_date = normalised[-1][0]

    by_date = defaultdict(list)
    for row in normalised:
        by_date[row[0]].append(row)

    windows = tuple(windows)
    result = {}
    current = min_date
    while current <= max_date:
        date_str = current.isoformat()
        result[date_str] = {}
        for window in windows:
            window_start = current - timedelta(days=window - 1)
            total_dur = 0.0
            w_low = 0.0
            w_mod = 0.0
            w_high = 0.0
            for row in normalised:
                d, dur, low, mod, high = row
                if d < window_start:
                    continue
                if d > current:
                    break
                total_dur += dur
                w_low  += dur * low
                w_mod  += dur * mod
                w_high += dur * high
            if total_dur == 0.0:
                result[date_str][window] = {"low": None, "moderate": None, "high": None}
            else:
                result[date_str][window] = {
                    "low":      w_low  / total_dur,
                    "moderate": w_mod  / total_dur,
                    "high":     w_high / total_dur,
                }
        current += timedelta(days=1)

    return result


def _normalise(sessions):
    """Convert session records to (date, dur, low, mod, high) tuples."""
    rows = []
    for s in sessions:
        if isinstance(s, dict):
            d    = s["date"]
            dur  = s["duration"]
            low  = s["low"]
            mod  = s["moderate"]
            high = s["high"]
        else:
            d    = s.date
            dur  = s.duration
            low  = s.low
            mod  = s.moderate
            high = s.high
        if isinstance(d, str):
            d = date.fromisoformat(d)
        rows.append((d, float(dur), float(low), float(mod), float(high)))
    return rows
