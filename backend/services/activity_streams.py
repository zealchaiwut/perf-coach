"""Pure stream-processing functions for activity_streams ingestion.

All computation lives here as pure, documented functions. Database writes
are performed only in the thin caller layer (reconcile.py).

The ``activity_streams`` table stores one row per workout.  Each channel is a
JSONB array whose index corresponds to the sample at that time offset:

    time_offset_seconds[i] → all channel arrays[i] are the values at offset i

Downsampling
------------
Both Strava and Stryd may record at higher than 1 Hz.  All streams are
reduced to **at most one sample per second** before storing.  This module
uses the **first-sample-in-window** method (see :func:`downsample_to_1hz`).

Channel mapping
---------------
Strava stream key      → activity_streams column
──────────────────────────────────────────────────
time                   → time_offset_seconds (already seconds from start)
heartrate              → heart_rate_bpm
watts                  → power_w
cadence                → cadence_spm
altitude               → altitude_m
velocity_smooth (m/s)  → pace_seconds_per_km  (1000 / v)
latlng                 → latitude, longitude  (split from pairs)

Stryd stream key       → activity_streams column
──────────────────────────────────────────────────
timestamp_list         → used to derive time_offset_seconds
heart_rate_list        → heart_rate_bpm
total_power_list       → power_w
cadence_list           → cadence_spm
speed_list (m/s)       → pace_seconds_per_km  (1000 / v)
"""
from __future__ import annotations

import logging as _logging
from typing import Optional

_log = _logging.getLogger(__name__)


# ── Core downsampling ─────────────────────────────────────────────────────────

def downsample_to_1hz(
    timestamps: list,
    values: list,
) -> list[tuple[int, float]]:
    """Reduce a time series to at most one sample per second.

    Method: **first-sample-in-window**. For each 1-second bucket whose key
    is ``int(floor(t))``, only the first encountered (t, v) pair is kept.

    Worked example::

        Input:  timestamps = [0, 0.2, 0.4, 1.0, 1.2, 1.8]
                values     = [10,  11,  12,  20,  21,  22]

        Windows and first hits:
          bucket 0 → t=0.0  first seen → value 10  ✓
          bucket 0 → t=0.2  already have bucket 0   ✗
          bucket 0 → t=0.4  already have bucket 0   ✗
          bucket 1 → t=1.0  first seen → value 20  ✓
          bucket 1 → t=1.2  already have bucket 1   ✗
          bucket 1 → t=1.8  already have bucket 1   ✗

        Output: [(0, 10.0), (1, 20.0)]

    Non-numeric values are silently dropped. Output is sorted by bucket key.
    """
    seen: dict[int, tuple[int, float]] = {}
    for t, v in zip(timestamps, values):
        if not isinstance(v, (int, float)):
            continue
        try:
            bucket = int(t)
        except (TypeError, ValueError):
            continue
        if bucket not in seen:
            seen[bucket] = (bucket, float(v))
    return [seen[k] for k in sorted(seen)]


def _aligned_arrays(
    time_data: list,
    value_data: list,
) -> tuple[list[int], list[float]]:
    """Return parallel (time_offsets, values) arrays after downsampling.

    Both are integer/float lists safe for JSONB serialisation.
    """
    samples = downsample_to_1hz(time_data, value_data)
    if not samples:
        return [], []
    ts_list, val_list = zip(*samples)
    return list(ts_list), list(val_list)


# ── Strava stream extraction ──────────────────────────────────────────────────

def extract_strava_streams(
    streams_payload: Optional[dict],
    source: str = "strava",
) -> tuple[Optional[dict], Optional[str]]:
    """Parse a Strava streams payload into an ``activity_streams`` row dict.

    Returns ``(row_dict, None)`` on success; ``(None, reason)`` when required
    inputs are absent or unusable.  Channels absent from the payload are
    silently skipped (their column will be absent from the returned dict).

    Parameters
    ----------
    streams_payload:
        Response from ``GET /activities/{id}/streams?key_by_type=true``.
        Expected keys: ``time`` (offsets in seconds), ``heartrate``, ``watts``,
        ``cadence``, ``altitude``, ``velocity_smooth``, ``latlng``.
    source:
        Provider label stored in the ``source`` column ('strava' or 'stryd').
    """
    if streams_payload is None:
        return None, "stream payload is required"

    time_stream = streams_payload.get("time")
    time_data: Optional[list] = None
    if isinstance(time_stream, dict):
        time_data = time_stream.get("data")
    if not time_data:
        return None, "time stream is absent — cannot compute time offsets"

    row: dict = {"source": source, "sample_interval_seconds": 1}

    # Downsample the time axis itself to get the stored offsets
    time_offsets, _ = _aligned_arrays(time_data, time_data)
    if time_offsets:
        row["time_offset_seconds"] = time_offsets

    # Scalar channels (each produces one parallel array)
    scalar_map = {
        "heartrate": "heart_rate_bpm",
        "watts": "power_w",
        "cadence": "cadence_spm",
        "altitude": "altitude_m",
    }
    for strava_key, col in scalar_map.items():
        ch = streams_payload.get(strava_key)
        if not isinstance(ch, dict) or not ch.get("data"):
            continue
        try:
            _, vals = _aligned_arrays(time_data, ch["data"])
            if vals:
                row[col] = vals
        except Exception as exc:
            _log.warning(
                "strava channel skipped",
                extra={"channel": strava_key, "reason": str(exc)},
            )

    # velocity_smooth (m/s) → pace_seconds_per_km
    vel = streams_payload.get("velocity_smooth")
    if isinstance(vel, dict) and vel.get("data"):
        try:
            pace_vals: list[Optional[float]] = []
            for v in vel["data"]:
                if isinstance(v, (int, float)) and v > 0:
                    pace_vals.append(round(1000.0 / v, 2))
                else:
                    pace_vals.append(None)
            _, paced = _aligned_arrays(time_data, pace_vals)
            if paced:
                row["pace_seconds_per_km"] = paced
        except Exception as exc:
            _log.warning(
                "strava channel skipped",
                extra={"channel": "velocity_smooth", "reason": str(exc)},
            )

    # latlng → latitude / longitude
    latlng = streams_payload.get("latlng")
    if isinstance(latlng, dict) and latlng.get("data"):
        try:
            lats = [p[0] if isinstance(p, (list, tuple)) and len(p) >= 2 else None for p in latlng["data"]]
            lngs = [p[1] if isinstance(p, (list, tuple)) and len(p) >= 2 else None for p in latlng["data"]]
            _, lat_vals = _aligned_arrays(time_data, lats)
            _, lng_vals = _aligned_arrays(time_data, lngs)
            if lat_vals:
                row["latitude"] = lat_vals
            if lng_vals:
                row["longitude"] = lng_vals
        except Exception as exc:
            _log.warning(
                "strava channel skipped",
                extra={"channel": "latlng", "reason": str(exc)},
            )

    return row, None


# ── Stryd stream extraction ───────────────────────────────────────────────────

def extract_stryd_streams(
    streams_payload: Optional[dict],
    source: str = "stryd",
) -> tuple[Optional[dict], Optional[str]]:
    """Parse Stryd per-point streams into an ``activity_streams`` row dict.

    Returns ``(row_dict, None)`` on success; ``(None, reason)`` on invalid
    input.  Channels absent from the payload are silently skipped.

    Parameters
    ----------
    streams_payload:
        Full per-activity response from ``GET /activities/{id}``, which
        contains ``timestamp_list``, ``heart_rate_list``, ``total_power_list``,
        ``cadence_list``, ``speed_list``, etc.
        Epoch milliseconds are auto-normalised to seconds
        (if timestamp > 1e12, divide by 1000).
    source:
        Provider label stored in the ``source`` column ('stryd' or 'strava').
    """
    if streams_payload is None:
        return None, "stream payload is required"

    raw_ts = streams_payload.get("timestamp_list") or []
    if not raw_ts:
        return None, "timestamp_list is required for Stryd streams"

    # Normalise epoch milliseconds → seconds
    norm_ts: list[float] = []
    for t in raw_ts:
        if isinstance(t, (int, float)):
            norm_ts.append(t / 1000.0 if t > 1e12 else float(t))

    if not norm_ts:
        return None, "no valid timestamps in timestamp_list"

    # Convert absolute timestamps to offsets from the first sample
    t0 = norm_ts[0]
    offsets = [t - t0 for t in norm_ts]

    row: dict = {"source": source, "sample_interval_seconds": 1}

    # Store the time offsets
    time_offsets, _ = _aligned_arrays(offsets, offsets)
    if time_offsets:
        row["time_offset_seconds"] = time_offsets

    # Scalar channels
    scalar_map = {
        "heart_rate_list": "heart_rate_bpm",
        "total_power_list": "power_w",
        "cadence_list": "cadence_spm",
    }
    for stryd_key, col in scalar_map.items():
        raw = streams_payload.get(stryd_key)
        if not raw:
            continue
        try:
            _, vals = _aligned_arrays(offsets, raw)
            if vals:
                row[col] = vals
        except Exception as exc:
            _log.warning(
                "stryd channel skipped",
                extra={"channel": stryd_key, "reason": str(exc)},
            )

    # speed_list (m/s) → pace_seconds_per_km
    speed_list = streams_payload.get("speed_list") or []
    if speed_list:
        try:
            pace_vals: list[Optional[float]] = []
            for v in speed_list:
                if isinstance(v, (int, float)) and v > 0:
                    pace_vals.append(round(1000.0 / v, 2))
                else:
                    pace_vals.append(None)
            _, paced = _aligned_arrays(offsets, pace_vals)
            if paced:
                row["pace_seconds_per_km"] = paced
        except Exception as exc:
            _log.warning(
                "stryd channel skipped",
                extra={"channel": "speed_list", "reason": str(exc)},
            )

    return row, None


# ── Conversion helper: stored row → Strava-format streams dict ───────────────

def activity_streams_to_strava_dict(stream_row) -> dict:
    """Convert a stored ActivityStream row to Strava raw-streams dict format."""
    if stream_row is None:
        return {}

    def _get(attr):
        v = getattr(stream_row, attr, None)
        return v if isinstance(v, list) and v else None

    out: dict = {}

    ts = _get("time_offset_seconds")
    if ts:
        out["time"] = {"data": ts}

    pw = _get("power_w")
    if pw:
        out["watts"] = {"data": pw}

    hr = _get("heart_rate_bpm")
    if hr:
        out["heartrate"] = {"data": hr}

    # pace_seconds_per_km → velocity_smooth (m/s): v = 1000 / pace
    pace = _get("pace_seconds_per_km")
    if pace:
        vel = [round(1000.0 / p, 4) if p and p > 0 else None for p in pace]
        out["velocity_smooth"] = {"data": vel}

    cad = _get("cadence_spm")
    if cad:
        out["cadence"] = {"data": cad}

    alt = _get("altitude_m")
    if alt:
        out["altitude"] = {"data": alt}

    lat = _get("latitude")
    lng = _get("longitude")
    if lat and lng and len(lat) == len(lng):
        out["latlng"] = {"data": list(zip(lat, lng))}

    return out


# ── Database write helper ─────────────────────────────────────────────────────

def write_activity_stream(workout_id, row_data: dict, session) -> bool:
    """Upsert one ``activity_streams`` row for the given workout.

    Uses INSERT … ON CONFLICT (workout_id) DO UPDATE so re-syncing is
    idempotent — the arrays are overwritten with freshly-downsampled data.
    Returns True if a row was written, False if row_data was empty/None.
    """
    if not row_data:
        return False

    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    from backend.models import ActivityStream

    vals = {"workout_id": workout_id, **row_data}
    update_cols = {k: v for k, v in row_data.items()}

    stmt = (
        _pg_insert(ActivityStream)
        .values(**vals)
        .on_conflict_do_update(
            index_elements=["workout_id"],
            set_=update_cols,
        )
    )
    session.execute(stmt)
    return True
