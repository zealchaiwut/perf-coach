"""Compute manual/device laps for a Stryd activity from its per-point streams.

Stryd does NOT return a precomputed `laps` array. Manual lap presses are stored
only as boundary unix-timestamps (`lap_timestamp_list` / `lap_events`). To show
them in the UI we slice the aligned per-point streams (timestamp / distance / HR
/ power / cadence / stride) at those boundaries and aggregate each segment.

Returns a list of lap dicts shaped for the frontend's normalizeStrydLap():
    {index, distance_km, duration_seconds, avg_hr, avg_power, cadence_spm,
     stride_length_m}
Empty list when there are no lap markers or no usable streams.
"""
from __future__ import annotations

from typing import Any


def _avg_nonzero(values: list) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float)) and v > 0]
    if not nums:
        return None
    return sum(nums) / len(nums)


def compute_manual_laps(streams: dict | None) -> list[dict[str, Any]]:
    if not isinstance(streams, dict):
        return []

    ts = streams.get("timestamp_list")
    if not isinstance(ts, list) or len(ts) < 2:
        return []

    boundaries = streams.get("lap_timestamp_list") or streams.get("lap_events")
    if not isinstance(boundaries, list) or not boundaries:
        return []

    dist = streams.get("distance_list") or []          # cumulative metres
    hr = streams.get("heart_rate_list") or []
    power = streams.get("total_power_list") or streams.get("power_list") or []
    cadence = streams.get("cadence_list") or []
    stride = streams.get("stride_length_list") or []

    n = len(ts)

    def at(arr, i):
        return arr[i] if isinstance(arr, list) and 0 <= i < len(arr) else None

    # Segment edges: run start, each lap-press, then run end. Drop any markers
    # outside the recording window and keep them ordered/unique.
    start_t, end_t = ts[0], ts[-1]
    marks = sorted({int(b) for b in boundaries if start_t < int(b) < end_t})
    edges = [start_t] + marks + [end_t]

    laps: list[dict[str, Any]] = []
    for li in range(len(edges) - 1):
        seg_start, seg_end = edges[li], edges[li + 1]
        # Skip degenerate segments (e.g. a final lap press landing on the very
        # end of the recording produces a sub-second, ~0 m sliver).
        if seg_end - seg_start < 3:
            continue
        # Index range [i0, i1] of points within this segment.
        i0 = next((i for i in range(n) if ts[i] >= seg_start), None)
        if i0 is None:
            continue
        i1 = i0
        for i in range(i0, n):
            if ts[i] <= seg_end:
                i1 = i
            else:
                break
        if i1 <= i0:
            continue

        d0, d1 = at(dist, i0), at(dist, i1)
        dist_km = (d1 - d0) / 1000.0 if (d0 is not None and d1 is not None and d1 >= d0) else None
        avg_hr = _avg_nonzero(hr[i0:i1 + 1])
        avg_power = _avg_nonzero(power[i0:i1 + 1])
        avg_cad = _avg_nonzero(cadence[i0:i1 + 1])
        avg_stride = _avg_nonzero(stride[i0:i1 + 1])

        laps.append({
            "index": len(laps) + 1,
            "distance_km": round(dist_km, 3) if dist_km is not None else None,
            "duration_seconds": int(seg_end - seg_start),
            "avg_hr": round(avg_hr) if avg_hr is not None else None,
            "avg_power": round(avg_power) if avg_power is not None else None,
            "cadence_spm": round(avg_cad) if avg_cad is not None else None,
            "stride_length_m": round(avg_stride, 2) if avg_stride is not None else None,
        })

    return laps
