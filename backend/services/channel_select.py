"""Pure channel-selection logic for merging two workout source streams.

The primary function :func:`select_channels` picks the best source per channel
when a workout has data from two different recording devices (e.g. a Garmin GPS
watch and a Stryd foot pod). It returns a merged channel map plus a per-channel
source-attribution map that records which device contributed each channel.

No database access occurs anywhere in this module. A thin caller,
:func:`apply_channel_selection`, handles all reads and writes.

Worked example::

    >>> garmin = {
    ...     "time_offset_seconds": [0, 1, 2],
    ...     "heart_rate_bpm": [145.0, 147.0, 146.0],
    ...     "latitude":  [1.2300, 1.2301, 1.2302],
    ...     "longitude": [103.80, 103.801, 103.802],
    ...     "altitude_m": [50.0, 51.0, 52.0],
    ... }
    >>> stryd = {
    ...     "time_offset_seconds": [0, 1, 2, 3],
    ...     "power_w": [255.0, 260.0, 258.0, 257.0],
    ...     "cadence_spm": [180.0, 182.0, 181.0, 183.0],
    ...     "heart_rate_bpm": [144.0, 146.0, 145.0, 147.0],
    ... }
    >>> merged, attribution, reason = select_channels(garmin, stryd, "garmin", "stryd")
    >>> reason is None       # full success
    True
    >>> attribution["power_w"]
    'stryd'
    >>> attribution["latitude"]
    'garmin'
    >>> attribution["heart_rate_bpm"]  # stryd has 4 samples vs garmin's 3 → longer wins
    'stryd'
    >>> attribution["cadence_spm"]     # only stryd provides cadence
    'stryd'
"""
from __future__ import annotations

from typing import Any

# GPS channels that must come from whichever source provides GPS coordinates.
_GPS_CHANNELS = frozenset({"latitude", "longitude", "altitude_m"})


def _has_gps(channels: dict) -> bool:
    """Return True if channels dict contains non-empty latitude data."""
    return bool(channels.get("latitude"))


def _apply_tiebreak(
    channel: str,
    a_vals: list,
    a_name: str,
    b_vals: list,
    b_name: str,
    rule: Any,
) -> tuple[str, list]:
    """Return (winning_source_name, winning_values) for a channel present in both sources.

    rule can be:
      - ``"longer"``   — whichever list has more samples wins (A wins on tie)
      - ``"prefer_a"`` — always pick source A
      - ``"prefer_b"`` — always pick source B
      - a dict mapping channel names to one of the above strings; falls back to
        ``"longer"`` for channels not listed
    """
    if isinstance(rule, dict):
        ch_rule = rule.get(channel, "longer")
    else:
        ch_rule = rule

    if ch_rule == "prefer_a":
        return a_name, a_vals
    if ch_rule == "prefer_b":
        return b_name, b_vals
    # Default: "longer" — more samples is better; A wins on tie
    if len(b_vals) > len(a_vals):
        return b_name, b_vals
    return a_name, a_vals


def select_channels(
    source_a_channels: dict | None,
    source_b_channels: dict | None,
    source_a_name: str,
    source_b_name: str,
    tiebreak_rule: Any = "longer",
) -> tuple[dict | None, dict | None, str | None]:
    """Select the best source per channel from two activity stream channel sets.

    Channel-selection rules (applied in order):

    1. **Fatal guard** — if either channel set is ``None`` or empty the whole
       result is ``None`` with an explanatory reason string.

    2. **power_w** — always taken from the Stryd source when Stryd is one of the
       two sources.  If neither source is Stryd, ``power_w`` is absent from the
       merged result, ``attribution["power_w"]`` is ``None``, and a non-``None``
       reason string is returned alongside the (partial) merged map.

    3. **GPS channels** (``latitude``, ``longitude``, ``altitude_m``) — taken
       from whichever source provides GPS data (non-empty ``latitude`` key).  If
       neither source has GPS these channels are simply omitted from the merged
       result — no error is raised.

    4. **All other channels** — resolved via *tiebreak_rule*:

       - ``"longer"`` *(default)* — the source with more samples wins; source A
         wins on a tie.
       - ``"prefer_a"`` — always pick source A.
       - ``"prefer_b"`` — always pick source B.
       - ``dict`` — per-channel overrides; keys are channel names, values are
         one of the three strings above; channels not listed fall back to
         ``"longer"``.

    Parameters
    ----------
    source_a_channels, source_b_channels:
        Dicts mapping channel name → list of numeric samples.  Pass only the
        actual channel arrays; metadata keys (``source``, ``sample_interval_seconds``)
        should be stripped by the caller before calling this function.
    source_a_name, source_b_name:
        Human-readable provider labels (e.g. ``"garmin"``, ``"stryd"``).  The
        string ``"stryd"`` (case-insensitive) activates the power_w rule.
    tiebreak_rule:
        Preference rule for non-special channels — see above.

    Returns
    -------
    (merged, attribution, reason) where:

    - ``merged`` is ``None`` on fatal failure, otherwise a dict of
      ``{channel_name: [values]}``.
    - ``attribution`` is ``None`` on fatal failure, otherwise a dict of
      ``{channel_name: source_name_or_none}``.
    - ``reason`` is ``None`` on full success, a non-empty string on fatal
      failure or on partial success (e.g. power_w absent because no Stryd source).

    Worked example::

        >>> garmin = {"heart_rate_bpm": [145, 147], "latitude": [1.23, 1.24], "longitude": [103.8, 103.81]}
        >>> stryd  = {"power_w": [255, 260], "heart_rate_bpm": [144, 146, 145]}
        >>> merged, attribution, reason = select_channels(garmin, stryd, "garmin", "stryd")
        >>> attribution["power_w"]
        'stryd'
        >>> attribution["latitude"]
        'garmin'
        >>> attribution["heart_rate_bpm"]  # stryd has 3 samples vs garmin's 2
        'stryd'
        >>> reason is None
        True
    """
    # ── 1. Fatal guard ────────────────────────────────────────────────────────
    if not source_a_channels:
        return None, None, f"source '{source_a_name}' channel set is missing or empty"
    if not source_b_channels:
        return None, None, f"source '{source_b_name}' channel set is missing or empty"

    merged: dict = {}
    attribution: dict = {}
    reason: str | None = None

    # ── Identify Stryd and GPS sources ───────────────────────────────────────
    stryd_channels: dict | None = None
    stryd_name: str | None = None
    gps_channels: dict | None = None
    gps_name: str | None = None

    for chans, name in [(source_a_channels, source_a_name), (source_b_channels, source_b_name)]:
        if name.lower() == "stryd" and stryd_channels is None:
            stryd_channels = chans
            stryd_name = name
        if _has_gps(chans) and gps_channels is None:
            gps_channels = chans
            gps_name = name

    # ── 2. power_w ────────────────────────────────────────────────────────────
    if stryd_channels is not None:
        power_vals = stryd_channels.get("power_w")
        if power_vals:
            merged["power_w"] = power_vals
            attribution["power_w"] = stryd_name
        else:
            attribution["power_w"] = None
            reason = "power_w absent from Stryd source channels"
    else:
        attribution["power_w"] = None
        reason = "power_w absent: neither source is Stryd"

    # ── 3. GPS channels ───────────────────────────────────────────────────────
    for ch in _GPS_CHANNELS:
        if gps_channels is not None:
            vals = gps_channels.get(ch)
            if vals:
                merged[ch] = vals
                attribution[ch] = gps_name
        # Absent when neither source has GPS — silently omitted (AC4)

    # ── 4. All other channels via tiebreak_rule ───────────────────────────────
    special = _GPS_CHANNELS | {"power_w"}
    all_channels = set(source_a_channels) | set(source_b_channels)

    for ch in all_channels:
        if ch in special:
            continue
        a_vals = source_a_channels.get(ch)
        b_vals = source_b_channels.get(ch)

        if a_vals and not b_vals:
            merged[ch] = a_vals
            attribution[ch] = source_a_name
        elif b_vals and not a_vals:
            merged[ch] = b_vals
            attribution[ch] = source_b_name
        elif a_vals and b_vals:
            winner_name, winner_vals = _apply_tiebreak(
                ch, a_vals, source_a_name, b_vals, source_b_name, tiebreak_rule
            )
            merged[ch] = winner_vals
            attribution[ch] = winner_name

    return merged, attribution, reason


# ─────────────────────────────────────────────────────────────────────────────
# Thin caller — all DB access lives here
# ─────────────────────────────────────────────────────────────────────────────

def apply_channel_selection(
    workout_id,
    session,
    tiebreak_rule: Any = "longer",
) -> tuple[bool, str | None]:
    """Read source streams for a workout, select channels, and persist merged result.

    Reads ``streams_payload`` from both ``strava_activities`` and
    ``stryd_activities`` linked to *workout_id*, runs :func:`select_channels`,
    and upserts the merged channel map (plus source-attribution) into
    ``activity_streams``.

    Prerequisites (AC10): the workout must have both ``strava_activity_pk`` and
    ``stryd_activity_pk`` set, and both activities must have a non-null
    ``streams_payload``.  When any prerequisite is unmet this function returns
    ``(False, reason)`` without writing anything.

    Parameters
    ----------
    workout_id:
        UUID of the workout row.
    session:
        Active SQLAlchemy session.  The caller is responsible for committing.
    tiebreak_rule:
        Forwarded to :func:`select_channels` — see its docstring.

    Returns
    -------
    ``(True, None)`` on success; ``(False, reason_string)`` when preconditions
    are not met or channel selection fails.
    """
    import logging
    _log = logging.getLogger(__name__)

    from backend.models import Workout, StravaActivity, StrydActivity
    from backend.services.activity_streams import (
        extract_strava_streams,
        extract_stryd_streams,
        write_activity_stream,
    )

    # ── AC10: verify both source streams exist ────────────────────────────────
    workout = session.query(Workout).filter(Workout.id == workout_id).first()
    if not workout:
        return False, f"workout {workout_id} not found"

    if not workout.strava_activity_pk or not workout.stryd_activity_pk:
        return False, "workout does not have both strava_activity_pk and stryd_activity_pk set"

    strava_act = (
        session.query(StravaActivity)
        .filter(StravaActivity.id == workout.strava_activity_pk)
        .first()
    )
    stryd_act = (
        session.query(StrydActivity)
        .filter(StrydActivity.id == workout.stryd_activity_pk)
        .first()
    )

    if not strava_act or not strava_act.streams_payload:
        return False, "Strava streams payload not yet ingested for this workout"
    if not stryd_act or not stryd_act.streams_payload:
        return False, "Stryd streams payload not yet ingested for this workout"

    # ── Extract channels from each source ────────────────────────────────────
    strava_row, strava_err = extract_strava_streams(strava_act.streams_payload, source="strava")
    if strava_err:
        return False, f"failed to extract Strava channels: {strava_err}"

    stryd_row, stryd_err = extract_stryd_streams(stryd_act.streams_payload, source="stryd")
    if stryd_err:
        return False, f"failed to extract Stryd channels: {stryd_err}"

    # Strip metadata keys — pass only channel arrays to select_channels
    _META = {"source", "sample_interval_seconds"}
    strava_chans = {k: v for k, v in strava_row.items() if k not in _META}
    stryd_chans = {k: v for k, v in stryd_row.items() if k not in _META}

    # ── Run pure channel selection ────────────────────────────────────────────
    merged, attribution, sel_reason = select_channels(
        strava_chans, stryd_chans, "strava", "stryd",
        tiebreak_rule=tiebreak_rule,
    )

    if merged is None:
        _log.warning(
            "channel_select failed — no merged stream written",
            extra={"workout_id": str(workout_id), "reason": sel_reason},
        )
        return False, sel_reason

    if sel_reason:
        _log.info(
            "channel_select partial success",
            extra={"workout_id": str(workout_id), "reason": sel_reason},
        )

    # ── Persist merged stream + attribution ───────────────────────────────────
    row_data: dict = {
        "source": "merged",
        "sample_interval_seconds": 1,
        "channel_attribution": attribution,
        **merged,
    }

    write_activity_stream(workout_id, row_data, session)
    return True, None
