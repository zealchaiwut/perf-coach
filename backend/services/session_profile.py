"""Session profile detector for the workout analysis pipeline.

detect_session_profile is the pure orchestrator: it accepts a splits container
and a preferences dict, runs a data-quality gate and a threshold gate, then
delegates to classify_laps, group_laps_into_phases, and detect_intervals /
detect_sets to produce a complete session profile.

No database access happens inside this module.  A thin caller layer loads
workout splits and user_preferences from the DB and passes plain dicts in.

Precedence contract (CALLER RESPONSIBILITY)
-------------------------------------------
Before calling this function, the caller MUST check whether a declared builder
structure already exists for the session (e.g. a manually authored phase plan
stored on the workout record).  When a builder structure exists, the caller
MUST use it directly and MUST NOT call detect_session_profile at all.
detect_session_profile is only for sessions where no builder structure is
present and the phase profile must be inferred from lap data.

Data-quality gate
-----------------
When splits.lap_type is neither "manual" nor a device-structured non-uniform
lap set, detect_session_profile returns immediately with confident=False, a
flat list of classify_laps-coloured laps (no phase names), reps_detected=null,
sets_detected=null, basis="none", and debug.reason describing why detection was
skipped.  Uniform auto 1 km splits do not carry enough structure for meaningful
phase grouping.

No usable threshold gate
------------------------
When none of the threshold keys in prefs (ftp_w, threshold_hr,
threshold_pace_seconds_per_km) has a non-null value, detect_session_profile
returns immediately with confident=False, basis="none", a flat phase list, and
debug.reason = "set your threshold to detect session phases".

Worked example
--------------
Input:
    splits = {
        "laps": [
            SimpleNamespace(avg_power=150, duration_seconds=360, distance_km=1.5),  # easy
            SimpleNamespace(avg_power=190, duration_seconds=600, distance_km=2.5),  # tempo
            SimpleNamespace(avg_power=150, duration_seconds=300, distance_km=1.0),  # easy
        ],
        "lap_type": "manual",
    }
    prefs = {"ftp_w": 200, "threshold_hr": None, "threshold_pace_seconds_per_km": None}

Result:
    {
        "phases": [
            {"label": "Warm-up", "band": "easy", ...},
            {"label": "Tempo",   "band": "tempo", ...},
            {"label": "Cool-down", "band": "easy", ...},
        ],
        "reps_detected": None,
        "sets_detected": None,
        "basis": "power",
        "confident": True,
        "debug": {
            "laps": [
                {"ratio": 0.75, "band": "easy"},
                {"ratio": 0.95, "band": "tempo"},
                {"ratio": 0.75, "band": "easy"},
            ]
        },
    }
"""

from backend.services.lap_classifier import classify_laps
from backend.services.lap_phase_grouper import group_laps_into_phases, LapPhaseConfig
from backend.services.interval_detector import detect_intervals, detect_sets

# lap_types treated as auto uniform splits that carry no useful phase structure
_AUTO_LAP_TYPES = frozenset({"auto_1km", "auto_1mi", "auto_km", "auto_mile"})

_MISSING_INPUT = {
    "phases": [],
    "reps_detected": None,
    "sets_detected": None,
    "basis": "none",
    "confident": False,
}


def _get(d, key):
    """Read a key from a dict or attribute from an object.

    Example:
        input:  d={"laps": [1, 2]}, key="laps"  → result: [1, 2]
        input:  d=SimpleNamespace(lap_type="manual"), key="lap_type"  → result: "manual"
        input:  d={"a": 1}, key="missing"  → result: None
    """
    if isinstance(d, dict):
        return d.get(key)
    return getattr(d, key, None)


def _flat_phase_list(classified, laps):
    """Build a flat list — one entry per lap — with no phase grouping names.

    Each entry carries the lap-level colour (band) assigned by classify_laps
    but does not group laps into named phases like Warm-up or Tempo.
    Used when the data-quality gate rejects the splits for full analysis.

    Example:
        input:  classified=[{"band": "easy", "ratio": 0.75}],
                laps=[SimpleNamespace(avg_power=150, ...)]
        result: [{"label": "easy", "band": "easy", "lap_index": 0, "ratio": 0.75}]
    """
    result = []
    for i, (cls, lap) in enumerate(zip(classified, laps)):
        result.append({
            "label": cls.get("band"),  # colour only; no named phase label
            "band": cls.get("band"),
            "lap_index": i,
            "ratio": cls.get("ratio"),
        })
    return result


def _derive_basis(classified):
    """Return the dominant basis string from a list of lap classifications.

    Chooses the basis that appeared most among laps that successfully produced
    a non-none band.  Falls back to 'none' when all laps returned basis='none'.
    When counts are equal, the priority order power then pace then hr is used
    so that the highest-quality threshold always wins.

    Example:
        input:  classified=[{"basis": "power"}, {"basis": "power"}, {"basis": "pace"}]
        result: "power"   (power appears most and also wins on priority)

        input:  classified=[{"basis": "none"}, {"basis": "none"}]
        result: "none"    (no usable basis found)
    """
    counts = {}
    for c in classified:
        b = c.get("basis", "none")
        if b != "none":
            counts[b] = counts.get(b, 0) + 1
    if not counts:
        return "none"
    # Return the basis with the highest lap count; 'power' beats 'pace' beats
    # 'hr' when counts are equal, preserving the priority order.
    for preferred in ("power", "pace", "hr"):
        if preferred in counts:
            return preferred
    return max(counts, key=counts.get)


def detect_session_profile(splits, prefs):
    """Detect the phase structure of a workout session from its laps and prefs.

    Accepts a splits container (dict or object with 'laps' list and 'lap_type'
    string) and a preferences dict (keys: ftp_w, threshold_hr,
    threshold_pace_seconds_per_km).

    Returns a dict with exactly these keys:
        phases          list of phase dicts in lap order
        reps_detected   integer count of hard reps, or None
        sets_detected   integer count of interval sets, or None
        basis           "power" | "pace" | "hr" | "none"
        confident       True when both gates passed and detection ran; else False
        debug           dict with at minimum a "laps" list and/or "reason" string

    Missing or null splits/prefs are handled gracefully — no exception is raised.

    Precedence contract (see module docstring): the caller must check for a
    declared builder structure first.  When a builder structure exists, the
    caller uses it directly without calling this function.  detect_session_profile
    is never called for sessions that already have a builder structure.

    Worked example: see module docstring.
    """
    # Guard: missing or null arguments never raise — return a safe default dict
    if splits is None:
        return {**_MISSING_INPUT, "debug": {"reason": "missing input: splits"}}
    if prefs is None:
        return {**_MISSING_INPUT, "debug": {"reason": "missing input: prefs"}}

    laps = _get(splits, "laps")
    lap_type = _get(splits, "lap_type") or ""

    # Data-quality gate: uniform auto splits lack the structural variety needed
    # for meaningful phase grouping — detection is skipped for these lap types
    if lap_type in _AUTO_LAP_TYPES:
        reason = "pure auto 1 km splits — phase detection skipped"
        # Still classify laps for colour-coded display, even without phase names
        if laps:
            classified = classify_laps(laps, prefs)
            flat = _flat_phase_list(classified, laps)
            debug_laps = [
                {"ratio": c.get("ratio"), "band": c.get("band")} for c in classified
            ]
        else:
            flat = []
            debug_laps = []
        return {
            "phases": flat,
            "reps_detected": None,
            "sets_detected": None,
            "basis": "none",
            "confident": False,
            "debug": {"reason": reason, "laps": debug_laps},
        }

    # No usable threshold gate: when no threshold key has a non-null value,
    # phase detection cannot proceed because there is no numeric reference point
    ftp_w = _get(prefs, "ftp_w")
    threshold_hr = _get(prefs, "threshold_hr")
    threshold_pace = _get(prefs, "threshold_pace_seconds_per_km")
    # At least one threshold value must be non-null to continue
    has_threshold = ftp_w is not None or threshold_hr is not None or threshold_pace is not None
    if not has_threshold:
        flat = []
        if laps:
            # Produce flat coloured list even without a threshold (all basis=none)
            classified = classify_laps(laps, prefs)
            flat = _flat_phase_list(classified, laps)
        return {
            "phases": flat,
            "reps_detected": None,
            "sets_detected": None,
            "basis": "none",
            "confident": False,
            "debug": {"reason": "set your threshold to detect session phases"},
        }

    # Both gates passed — run full detection pipeline
    if not laps:
        # Empty lap list: nothing to detect but not an error state
        return {
            "phases": [],
            "reps_detected": None,
            "sets_detected": None,
            "basis": "none",
            "confident": False,
            "debug": {"reason": "no laps in splits"},
        }

    # Step 1: classify each lap with the per-athlete thresholds from prefs;
    # the result carries ratio, band, and basis for every lap
    classified = classify_laps(laps, prefs)

    # Build per-lap debug entries so callers can inspect the reasoning
    debug_laps = [
        {"ratio": c.get("ratio"), "band": c.get("band")} for c in classified
    ]

    # Derive overall basis from whichever threshold was used most across laps
    basis = _derive_basis(classified)

    # Step 2: merge classification results with original lap data so the phase
    # grouper receives every field it needs (band + distance + duration + hr/power)
    merged_laps = []
    for i, (cls, lap) in enumerate(zip(classified, laps)):
        merged = {
            "band": cls.get("band"),
            "distance_km": _get(lap, "distance_km"),
            "duration_seconds": _get(lap, "duration_seconds"),
            "avg_hr": _get(lap, "avg_hr"),
            "avg_power": _get(lap, "avg_power"),
        }
        merged_laps.append(merged)

    # Step 3: group consecutive same-band laps into named phases (Warm-up,
    # Tempo, Cool-down, or generic band name) using LapPhaseConfig defaults
    phases, phase_reason = group_laps_into_phases(merged_laps, LapPhaseConfig())
    if phases is None:
        # Phase grouper rejected the input — degrade gracefully to flat list
        return {
            "phases": _flat_phase_list(classified, laps),
            "reps_detected": None,
            "sets_detected": None,
            "basis": basis,
            "confident": False,
            "debug": {"reason": phase_reason or "phase grouping failed", "laps": debug_laps},
        }

    # Step 4: attempt interval detection — looks for repeating hard/easy cycles
    reps_detected = None
    sets_detected = None
    interval_phase, _ = detect_intervals(merged_laps)
    if interval_phase is not None:
        # Interval pattern found — refine by splitting on long recoveries
        updated_phase, _ = detect_sets(interval_phase, merged_laps)
        if updated_phase is not None:
            reps_detected = updated_phase.get("reps_detected")
            sets_detected = updated_phase.get("sets_detected")

    return {
        "phases": phases,
        "reps_detected": reps_detected,
        "sets_detected": sets_detected,
        "basis": basis,
        "confident": True,
        "debug": {"laps": debug_laps},
    }
