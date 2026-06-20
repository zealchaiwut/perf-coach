"""Checkpoint auto-detection service.

A checkpoint is "met" by a run when the run's measured performance satisfies
the checkpoint's target fields.  Evaluation rules are:

- A checkpoint with ``met_override = True`` is **never** altered by this
  function, regardless of run data.
- A **distance+pace checkpoint** (at least one of ``target_distance_km`` or
  ``target_pace_seconds_per_km`` is set) is satisfied when:

    * run distance >= ``target_distance_km``  (when a distance target is set)
    * AND run average pace <= ``target_pace_seconds_per_km * (1 + PACE_TOLERANCE_FRACTION)``
      (when a pace target is set)

  The tolerance is the named constant ``PACE_TOLERANCE_FRACTION``; it provides
  configurable slack for minor GPS/measurement drift.
- A **duration-only checkpoint** (``target_duration_seconds`` is set and no
  distance/pace targets) is satisfied when:

    * run duration >= ``target_duration_seconds``

This module is intentionally free of database access.  The caller
(``_run_checkpoint_autodetection`` in ``main.py``) is responsible for loading
checkpoints and persisting the updated ``met``/``met_workout_id`` fields.

Worked example
--------------
A 15.2 km run completed in 3860 seconds (≈ 254 s/km) against a checkpoint
``target_distance_km=15, target_pace_seconds_per_km=256``:

    run_pace = 3860 / 15.2 = 253.95 s/km
    pace_ceiling = 256 * (1 + 0.02) = 261.12 s/km
    253.95 <= 261.12  → pace OK
    15.2   >= 15.0    → distance OK
    → checkpoint IS met.

A 10 km run in 2700 seconds (270 s/km) against the same checkpoint:

    270 > 261.12  → pace too slow
    → checkpoint is NOT met.
"""

# Fraction above target pace still considered a match.
# At 0.02 (2 %) a target of 256 s/km accepts runs up to 261 s/km.
PACE_TOLERANCE_FRACTION: float = 0.02

# Workout-type strings that trigger checkpoint evaluation.
# Comparison is lower-cased before lookup.
RUN_WORKOUT_TYPES: frozenset = frozenset({"run", "running", "race"})


def is_run_workout(workout_type: str) -> bool:
    """Return True when *workout_type* identifies a run (case-insensitive)."""
    if not workout_type:
        return False
    wt = workout_type.lower()
    return wt in RUN_WORKOUT_TYPES or wt.startswith("run")


def average_pace_seconds_per_km(
    distance_km: float | None,
    duration_seconds: int | None,
) -> float | None:
    """Compute average pace in seconds per kilometre.

    Returns ``None`` when either argument is absent or *distance_km* is zero
    or negative (average pace is undefined for those inputs).

    :param distance_km: Run distance in kilometres.
    :param duration_seconds: Run elapsed time in seconds.
    :returns: Pace (float) or ``None``.
    """
    if distance_km is None or duration_seconds is None:
        return None
    if float(distance_km) <= 0:
        return None
    return duration_seconds / float(distance_km)


def evaluate_checkpoint(
    checkpoint,
    run_distance_km: float | None,
    run_duration_seconds: int | None,
    pace_tolerance_fraction: float = PACE_TOLERANCE_FRACTION,
) -> bool:
    """Evaluate whether *checkpoint* is satisfied by a single run.

    Pure function — no side effects, no DB access.  The caller persists
    ``met`` and ``met_workout_id`` when this returns ``True``.

    A checkpoint whose ``met_override`` is ``True`` always returns ``False``;
    it is protected from auto-detection regardless of run performance.

    **Decision tree**

    1. If ``met_override`` is ``True`` → ``False`` (protected).
    2. If ``target_duration_seconds`` is set *and* no distance/pace targets
       are set → duration-only rule:
       ``run_duration_seconds >= checkpoint.target_duration_seconds``.
    3. Otherwise (at least one distance or pace target) → distance+pace rule:
       * If ``target_distance_km`` is set:
         ``run_distance_km >= checkpoint.target_distance_km``.
       * If ``target_pace_seconds_per_km`` is set:
         ``run_pace <= checkpoint.target_pace_seconds_per_km * (1 + pace_tolerance_fraction)``.
    4. If no targets are set at all → ``False`` (nothing to evaluate).

    **Worked example** ::

        # 15.2 km in 3860 s (≈ 254 s/km) vs target_distance_km=15,
        # target_pace_seconds_per_km=256, PACE_TOLERANCE_FRACTION=0.02
        run_pace = 3860 / 15.2  # ≈ 253.9 s/km
        pace_ceiling = 256 * 1.02  # = 261.12 s/km
        # 253.9 <= 261.12 → pace OK; 15.2 >= 15.0 → distance OK → True

    :param checkpoint: Object with ``met_override``, ``target_distance_km``,
        ``target_pace_seconds_per_km``, and ``target_duration_seconds``.
    :param run_distance_km: GPS distance of the run in kilometres, or ``None``.
    :param run_duration_seconds: Elapsed time of the run in seconds, or ``None``.
    :param pace_tolerance_fraction: Fractional slack above target pace still
        accepted (defaults to ``PACE_TOLERANCE_FRACTION``).
    :returns: ``True`` if the checkpoint criteria are satisfied, else ``False``.
    """
    if checkpoint.met_override:
        return False

    has_distance_target = checkpoint.target_distance_km is not None
    has_pace_target = checkpoint.target_pace_seconds_per_km is not None
    has_duration_target = checkpoint.target_duration_seconds is not None

    # Duration-only path (no distance or pace targets present)
    if has_duration_target and not has_distance_target and not has_pace_target:
        if run_duration_seconds is None:
            return False
        return int(run_duration_seconds) >= int(checkpoint.target_duration_seconds)

    # Distance+pace path (at least one of the two is set)
    if has_distance_target or has_pace_target:
        if has_distance_target:
            if run_distance_km is None:
                return False
            if float(run_distance_km) < float(checkpoint.target_distance_km):
                return False

        if has_pace_target:
            run_pace = average_pace_seconds_per_km(run_distance_km, run_duration_seconds)
            if run_pace is None:
                return False
            pace_ceiling = float(checkpoint.target_pace_seconds_per_km) * (
                1 + pace_tolerance_fraction
            )
            if run_pace > pace_ceiling:
                return False

        return True

    # No targets set — nothing to evaluate
    return False
