"""Strength TSS calculation module.

Exposes two public functions:

- :func:`calculate_strength_tss` — pure function computing session-RPE-based
  TSS from session-level or set-level RPE data and user preferences.
- :func:`calculate_strength_tss_per_set` — pure function computing TSS from
  per-set reps and RPE data (per-set method, issue #593).
- :func:`get_strength_tss_for_workout` — thin caller that reads user_preferences
  and workout set data from the database and delegates to calculate_strength_tss.

Worked example (three sets)
---------------------------
Inputs: [
  { reps: 5, rpe: 8 },
  { reps: 5, rpe: 9 },
  { reps: 3, rpe: 10 }
]

Set 1 stress: 5 × (8 ÷ 10) × (8 ÷ 10) = 5 × 0.64 = 3.20
Set 2 stress: 5 × (9 ÷ 10) × (9 ÷ 10) = 5 × 0.81 = 4.05
Set 3 stress: 3 × (10 ÷ 10) × (10 ÷ 10) = 3 × 1.00 = 3.00

Raw sum: 3.20 + 4.05 + 3.00 = 10.25
Scaled sum: 10.25 × STRENGTH_TSS_SCALE (e.g. 5.85) ≈ 59.96
Clamped: min(59.96, STRENGTH_TSS_MAX) = 59.96
tss (whole number): 60
"""

# ── Thresholds ──────────────────────────────────────────────────────────────

# Scaling factor: multiply raw set-stress sum by this to produce a TSS value
# where a representative hard 45-minute session yields TSS between 50 and 70.
STRENGTH_TSS_SCALE = 5.85

# Maximum TSS value: clamp scaled sum to this value before rounding.
# Prevents extremely high rep counts or RPE combinations from producing
# unreasonably large TSS values.
STRENGTH_TSS_MAX = 150


# ── Public API ──────────────────────────────────────────────────────────────

def calculate_strength_tss_per_set(sets: list) -> dict:
    """Compute strength TSS from per-set reps and RPE data.

    This is a pure function: it reads only the arguments supplied, performs no
    I/O, and raises no exceptions for missing or empty data.

    Parameters
    ----------
    sets:
        List of set objects. Each must contain (as dict keys)
        ``reps`` (int) and ``rpe`` (int, 1–10). May be None or an empty list.

    Returns
    -------
    On success, a dict with the following keys:

    ``tss``
        Computed Training Stress Score (whole integer).
    ``method``
        String "per_set" on success, "none" on invalid input.
    ``debug``
        Dict containing:
        ``per_set_contributions`` (array of set_stress values, one per set),
        ``raw_sum`` (float, sum of per_set_contributions),
        ``scaled_sum`` (float, raw_sum × STRENGTH_TSS_SCALE),
        ``clamped`` (float, min(scaled_sum, STRENGTH_TSS_MAX)).

    When there is not enough data to produce a result, returns::

        {"tss": null, "method": "none", "debug": {"reason": "<message>"}}

    Worked example (three sets)
    ---------------------------
    Inputs: [
      { reps: 5, rpe: 8 },
      { reps: 5, rpe: 9 },
      { reps: 3, rpe: 10 }
    ]

    Set 1 stress: 5 × (8 ÷ 10) × (8 ÷ 10) = 5 × 0.64 = 3.20
    Set 2 stress: 5 × (9 ÷ 10) × (9 ÷ 10) = 5 × 0.81 = 4.05
    Set 3 stress: 3 × (10 ÷ 10) × (10 ÷ 10) = 3 × 1.00 = 3.00

    Raw sum: 3.20 + 4.05 + 3.00 = 10.25
    Scaled sum: 10.25 × STRENGTH_TSS_SCALE (e.g. 5.85) ≈ 59.96
    Clamped: min(59.96, STRENGTH_TSS_MAX) = 59.96
    tss (whole number): 60
    """
    # Guard: empty set list
    if not sets:
        return {
            "tss": None,
            "method": "none",
            "debug": {"reason": "no sets provided"},
        }

    # Validate all sets have required fields
    for i, s in enumerate(sets):
        if "reps" not in s or s["reps"] is None:
            return {
                "tss": None,
                "method": "none",
                "debug": {"reason": f"set {i} missing reps"},
            }
        if "rpe" not in s or s["rpe"] is None:
            return {
                "tss": None,
                "method": "none",
                "debug": {"reason": f"set {i} missing rpe"},
            }

    # Calculate per-set stress
    per_set_contributions = []
    for s in sets:
        reps = s["reps"]
        rpe = s["rpe"]
        rpe_fraction = rpe / 10.0
        set_stress = reps * rpe_fraction * rpe_fraction
        per_set_contributions.append(set_stress)

    # Sum and scale
    raw_sum = sum(per_set_contributions)
    scaled_sum = raw_sum * STRENGTH_TSS_SCALE
    clamped = min(scaled_sum, STRENGTH_TSS_MAX)
    tss = round(clamped)

    return {
        "tss": tss,
        "method": "per_set",
        "debug": {
            "per_set_contributions": per_set_contributions,
            "raw_sum": raw_sum,
            "scaled_sum": scaled_sum,
            "clamped": clamped,
        },
    }


# ── Session-RPE method (issue #688) ─────────────────────────────────────────

def calculate_strength_tss(session_rpe, duration_minutes, set_data, user_preferences) -> dict:
    """Compute session-RPE Training Stress Score (TSS) for a strength session.

    Pure function: performs no database access. All configurable values are
    read from user_preferences; none are hardcoded.

    Parameters
    ----------
    session_rpe:
        Athlete's whole-session RPE on the configured RPE scale, or None.
        When None, a derived value is computed from set_data if available.
    duration_minutes:
        Total session duration in minutes (int or float), or None. Required
        for any TSS result; returns tss=null when absent.
    set_data:
        Optional list of set records (dicts or objects) each with ``rpe``
        and ``reps`` keys. Used to derive session RPE via a reps-weighted
        average when session_rpe is not supplied. Entries missing either
        ``rpe`` or ``reps`` are silently excluded.
    user_preferences:
        Object (or dict) with attribute ``strength_rpe_max`` — the ceiling
        of the RPE scale in use (e.g. 10 for standard RPE, 20 for Borg).
        If strength_rpe_max is None the function returns tss=null.

    Returns
    -------
    dict with exactly four keys:

        tss (int or None):
            Rounded Training Stress Score, or None when a required input
            is absent.

        method (str):
            ``"session_rpe"`` when TSS was computed; ``"none"`` otherwise.

        estimated (bool):
            Always True.

        debug (dict):
            Diagnostic values. On success contains:
              session_rpe_source — ``"direct"`` or ``"derived"``
              session_rpe        — RPE value used in the calculation
              duration_minutes   — duration used
              session_intensity  — session_rpe divided by strength_rpe_max
            On failure contains:
              reason — human-readable string describing what is missing.

    Formula
    -------
    Step 1 — Read strength_rpe_max from user_preferences.
        This is the ceiling of the RPE scale (configurable per user).

    Step 2 — Resolve session RPE.
        Use session_rpe directly (source: ``"direct"``). If absent but
        set_data contains at least one entry with both rpe and reps, compute
        a reps-weighted average across valid sets (source: ``"derived"``).

    Step 3 — Compute session intensity (SI).
        SI = session_rpe divided by strength_rpe_max.
        Maps the RPE value to a 0–1 intensity ratio.

    Step 4 — Compute TSS.
        TSS = SI times SI times (duration_minutes divided by 60) times 100.
        Round to the nearest whole integer.

    Worked examples
    ---------------
    Example 1 — 60 minutes at RPE 10 (strength_rpe_max=10) → tss=100:
        SI = 10 / 10 = 1.0
        TSS = 1.0 * 1.0 * (60 / 60) * 100 = 100

    Example 2 — 60 minutes at RPE 7 (strength_rpe_max=10) → tss=49:
        SI = 7 / 10 = 0.7
        TSS = 0.7 * 0.7 * (60 / 60) * 100 = 49
    """
    def _null(reason):
        return {"tss": None, "method": "none", "estimated": True, "debug": {"reason": reason}}

    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Read configurable RPE scale ceiling from user_preferences
    rpe_max = _get(user_preferences, "strength_rpe_max")
    if rpe_max is None:
        return _null("strength_rpe_max not configured in user_preferences")

    # Guard: duration required
    if duration_minutes is None:
        return _null("duration_minutes is missing; cannot compute TSS")

    # Resolve effective session RPE
    effective_rpe = session_rpe
    rpe_source = "direct"

    if effective_rpe is None:
        valid_sets = []
        for s in (set_data or []):
            rpe_val = _get(s, "rpe")
            reps_val = _get(s, "reps")
            if rpe_val is not None and reps_val is not None:
                valid_sets.append((rpe_val, reps_val))

        if valid_sets:
            total_reps = sum(r for _, r in valid_sets)
            if total_reps > 0:
                effective_rpe = sum(rpe * reps for rpe, reps in valid_sets) / total_reps
                rpe_source = "derived"

    if effective_rpe is None:
        return _null("session_rpe is missing and no valid per-set RPE data to derive it from")

    session_intensity = effective_rpe / rpe_max
    tss = round(session_intensity * session_intensity * (duration_minutes / 60) * 100)

    return {
        "tss": tss,
        "method": "session_rpe",
        "estimated": True,
        "debug": {
            "session_rpe_source": rpe_source,
            "session_rpe": effective_rpe,
            "duration_minutes": duration_minutes,
            "session_intensity": session_intensity,
        },
    }


def get_strength_tss_for_workout(workout_id, user_id, db) -> dict:
    """Thin caller: read user_preferences and set data from DB, delegate to calculate_strength_tss.

    This is the only function in this module that performs database access.
    All TSS logic lives in calculate_strength_tss.
    """
    import json
    from sqlalchemy import text

    prefs_row = db.execute(
        text("SELECT strength_rpe_max FROM user_preferences WHERE user_id = :uid"),
        {"uid": str(user_id)},
    ).fetchone()

    import types
    prefs = types.SimpleNamespace(
        strength_rpe_max=prefs_row[0] if prefs_row else None,
    )

    feel_row = db.execute(
        text("SELECT rpe_1_to_10 FROM workout_feel WHERE workout_id = :wid LIMIT 1"),
        {"wid": str(workout_id)},
    ).fetchone()
    session_rpe = feel_row[0] if feel_row else None

    workout_row = db.execute(
        text("SELECT duration_seconds FROM workouts WHERE id = :wid"),
        {"wid": str(workout_id)},
    ).fetchone()
    duration_minutes = None
    if workout_row and workout_row[0] is not None:
        duration_minutes = workout_row[0] / 60

    ex_rows = db.execute(
        text("SELECT rpe, reps, sets_json FROM workout_exercises WHERE workout_id = :wid"),
        {"wid": str(workout_id)},
    ).fetchall()

    set_data = []
    for rpe, reps, sets_json in ex_rows:
        if sets_json:
            try:
                for s in json.loads(sets_json):
                    set_data.append({"rpe": s.get("rpe"), "reps": s.get("reps")})
            except (json.JSONDecodeError, AttributeError):
                pass
        elif rpe is not None and reps is not None:
            set_data.append({"rpe": rpe, "reps": reps})

    return calculate_strength_tss(session_rpe, duration_minutes, set_data, prefs)
