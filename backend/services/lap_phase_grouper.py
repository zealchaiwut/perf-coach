"""Phase grouper for session profile detection.

group_laps_into_phases is the pure core: it accepts a list of classified lap
objects (the merged output of classify_laps + original lap data) and a config
object, and returns one phase dict per contiguous same-band block.

No database access happens here.  A thin caller layer reads splits and
classifications from the DB and passes plain dicts in.

Labeling rules (applied in priority order):
    1.  A low-intensity block (easy or steady) that begins at the first lap
        position is labeled "Warm-up".
    2.  A low-intensity block (easy or steady) that ends at the last lap
        position is labeled "Cool-down".
    3.  A single uninterrupted block whose band is tempo or threshold and
        whose total duration reaches TEMPO_MIN_DURATION_SECONDS (about 8
        minutes) OR whose total distance reaches TEMPO_MIN_DISTANCE_KM
        (about 2 km) — whichever threshold is met first — is labeled "Tempo".
    4.  All other contiguous same-band blocks are labeled by their band name
        (generic grouping).

Interval detection is explicitly excluded: laps that would form alternating
high/low patterns are passed through as separate generic-band phases.

Each returned phase object contains:
    label                     — see labeling rules above
    lap_indexes               — ordered list of 0-based indexes into the
                                input classified_laps list
    distance_km               — sum of lap distance_km values
    duration_seconds          — sum of lap duration_seconds values
    avg_pace_seconds_per_km   — total_duration / total_distance, or None
                                when total_distance is zero
    avg_hr                    — arithmetic mean of lap avg_hr values that are
                                not None, or None when none are present
    avg_power                 — arithmetic mean of lap avg_power values that
                                are not None, or None when none are present
    band                      — the common band shared by all laps in this
                                phase

On success the function returns (phases, None).
On invalid input the function returns (None, reason_str) without raising.

Worked example
--------------
Input laps (after classify_laps + merge with original split data):

    [
        {"band": "easy",  "distance_km": 1.5, "duration_seconds": 450, ...},
        {"band": "tempo", "distance_km": 2.5, "duration_seconds": 600, ...},
        {"band": "easy",  "distance_km": 1.0, "duration_seconds": 360, ...},
    ]

Config (using LapPhaseConfig defaults):
    TEMPO_MIN_DURATION_SECONDS = 480   # about 8 minutes
    TEMPO_MIN_DISTANCE_KM      = 2.0   # about 2 km

Result phases:

    Phase 0 — Warm-up block (lap 0, easy, begins at position 0):
        label="Warm-up", band="easy", lap_indexes=[0],
        distance_km=1.5, duration_seconds=450,
        avg_pace_seconds_per_km=300.0

    Phase 1 — Sustained tempo block (lap 1, 2.5 km ≥ 2.0 km threshold):
        label="Tempo", band="tempo", lap_indexes=[1],
        distance_km=2.5, duration_seconds=600,
        avg_pace_seconds_per_km=240.0

    Phase 2 — Cool-down block (lap 2, easy, ends at last position):
        label="Cool-down", band="easy", lap_indexes=[2],
        distance_km=1.0, duration_seconds=360,
        avg_pace_seconds_per_km=360.0
"""

_LOW_INTENSITY_BANDS = frozenset({"easy", "steady"})
_TEMPO_BANDS = frozenset({"tempo", "threshold"})


class LapPhaseConfig:
    """Default thresholds for phase labeling.

    TEMPO_MIN_DURATION_SECONDS: about 8 minutes — a sustained effort shorter
        than this does not earn the Tempo label.
    TEMPO_MIN_DISTANCE_KM: about 2 km — a sustained effort covering less
        distance than this does not earn the Tempo label.
    Either threshold being met is sufficient.
    """

    TEMPO_MIN_DURATION_SECONDS = 480  # about 8 minutes
    TEMPO_MIN_DISTANCE_KM = 2.0       # about 2 km


def _get(lap, key):
    """Retrieve a value from a lap dict or object attribute."""
    if isinstance(lap, dict):
        return lap.get(key)
    return getattr(lap, key, None)


def _validate_laps(classified_laps):
    """Return (True, None) when input is valid; (False, reason_str) otherwise."""
    if classified_laps is None:
        return False, "classified_laps is null"
    if len(classified_laps) == 0:
        return False, "classified_laps is empty"
    required = ("band", "distance_km", "duration_seconds")
    for idx, lap in enumerate(classified_laps):
        for field in required:
            if _get(lap, field) is None and field in ("band",):
                return False, f"lap at index {idx} is missing required field '{field}'"
            if _get(lap, field) is None and field in ("distance_km", "duration_seconds"):
                # distinguish truly absent from legitimately zero
                val = _get(lap, field)
                if isinstance(lap, dict) and field not in lap:
                    return False, f"lap at index {idx} is missing required field '{field}'"
                if not isinstance(lap, dict) and not hasattr(lap, field):
                    return False, f"lap at index {idx} is missing required field '{field}'"
    return True, None


def _group_consecutive(classified_laps):
    """Group consecutive same-band laps into (band, [indexes]) tuples."""
    groups = []
    for idx, lap in enumerate(classified_laps):
        band = _get(lap, "band")
        if groups and groups[-1][0] == band:
            groups[-1][1].append(idx)
        else:
            groups.append((band, [idx]))
    return groups


def _aggregate(laps, indexes):
    """Compute aggregated metrics for a set of lap indexes."""
    total_distance = sum(_get(laps[i], "distance_km") or 0.0 for i in indexes)
    total_duration = sum(_get(laps[i], "duration_seconds") or 0.0 for i in indexes)

    hr_values = [
        _get(laps[i], "avg_hr")
        for i in indexes
        if _get(laps[i], "avg_hr") is not None
    ]
    power_values = [
        _get(laps[i], "avg_power")
        for i in indexes
        if _get(laps[i], "avg_power") is not None
    ]

    avg_pace = total_duration / total_distance if total_distance > 0 else None
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
    avg_power = sum(power_values) / len(power_values) if power_values else None

    return total_distance, total_duration, avg_pace, avg_hr, avg_power


def _label_group(band, indexes, total_distance, total_duration, group_idx, n_groups, config):
    """Determine the display label for a single group.

    Priority:
    1. Low-intensity block at position 0 → Warm-up
    2. Low-intensity block at last position → Cool-down
    3. Tempo/threshold block meeting either size threshold → Tempo
    4. Anything else → band name
    """
    is_first = group_idx == 0
    is_last = group_idx == n_groups - 1

    if is_first and band in _LOW_INTENSITY_BANDS:
        return "Warm-up"

    if is_last and band in _LOW_INTENSITY_BANDS:
        return "Cool-down"

    if band in _TEMPO_BANDS:
        # First threshold reached wins — check duration first, then distance
        meets_duration = total_duration >= config.TEMPO_MIN_DURATION_SECONDS
        meets_distance = total_distance >= config.TEMPO_MIN_DISTANCE_KM
        if meets_duration or meets_distance:
            return "Tempo"

    return band


def group_laps_into_phases(classified_laps, config):
    """Group consecutive classified laps into labeled session phases.

    Parameters
    ----------
    classified_laps:
        List of dicts (or objects with attributes) produced by merging the
        output of classify_laps with the original split data.  Each element
        must contain at minimum: band (str), distance_km (float),
        duration_seconds (float).  Optional: avg_hr (float|None),
        avg_power (float|None).
    config:
        An object exposing TEMPO_MIN_DURATION_SECONDS (about 8 minutes) and
        TEMPO_MIN_DISTANCE_KM (about 2 km).  Use LapPhaseConfig for defaults.

    Returns
    -------
    (phases, None)     on success, where phases is a list of phase dicts.
    (None, reason_str) when input is null, empty, or has missing required
                       fields; never raises.

    See module docstring for phase dict fields and labeling rules.
    """
    valid, reason = _validate_laps(classified_laps)
    if not valid:
        return None, reason

    groups = _group_consecutive(classified_laps)
    n_groups = len(groups)
    phases = []

    for group_idx, (band, indexes) in enumerate(groups):
        total_distance, total_duration, avg_pace, avg_hr, avg_power = _aggregate(
            classified_laps, indexes
        )
        label = _label_group(
            band, indexes, total_distance, total_duration, group_idx, n_groups, config
        )
        phases.append(
            {
                "label": label,
                "lap_indexes": indexes,
                "distance_km": total_distance,
                "duration_seconds": total_duration,
                "avg_pace_seconds_per_km": avg_pace,
                "avg_hr": avg_hr,
                "avg_power": avg_power,
                "band": band,
            }
        )

    return phases, None
