"""prediction_snapshot — write and query projection forecast snapshots (issue #1362).

One snapshot per user per day; the first computation of the day wins.
Later same-day recomputes hit ON CONFLICT DO NOTHING so the morning
forecast is preserved for forecast-vs-actual accuracy evaluation.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text as _text
from sqlalchemy.orm import Session

from backend.db import engine

FORMULA_VERSION = "1"


def build_snapshot_payload(
    *,
    race_projections: list[dict],
    ctl_series: list[float],
    start_date: date,
    races_meta: list[dict],
    formula_version: str = FORMULA_VERSION,
) -> dict:
    """Assemble the compact payload stored in prediction_snapshots.payload.

    Parameters
    ----------
    race_projections:
        List of race dicts from build_plan_projection_payload['races'], each
        expected to contain at minimum ``estimated_finish_seconds``, ``date``,
        and ``race_id`` (injected by the router before calling here).
    ctl_series:
        The projected CTL list (one float per day) returned by
        build_plan_projection_payload.
    start_date:
        The anchor date of the projection (start_date+1 is day 0 of the series).
    races_meta:
        Original race dicts from list_races (have ``id`` and ``date``).
    formula_version:
        Opaque version tag for the projection formula so future analysis can
        segment by formula change.

    Returns
    -------
    dict with keys:
        ``races``            — list[{race_id, date, predicted_finish_seconds, projected_ctl}]
        ``peak_ctl``         — float (max value in ctl_series)
        ``peak_week``        — str ISO week (YYYY-Www) of the day with peak CTL
        ``formula_version``  — str
    """
    # Build a date→CTL lookup from the series
    date_to_ctl: dict[date, float] = {}
    for i, ctl_val in enumerate(ctl_series):
        day = start_date + timedelta(days=i + 1)
        date_to_ctl[day] = ctl_val

    # Build a race_id lookup keyed by ISO date string
    race_id_by_date: dict[str, str] = {}
    for rm in races_meta:
        race_id_by_date[str(rm["date"])] = str(rm["id"])

    races_out = []
    for rp in race_projections:
        race_date_str = str(rp.get("date", ""))
        race_id = rp.get("race_id") or race_id_by_date.get(race_date_str)
        if not race_id:
            continue

        try:
            rd = date.fromisoformat(race_date_str)
        except (ValueError, TypeError):
            continue

        projected_ctl = date_to_ctl.get(rd)
        races_out.append({
            "race_id": str(race_id),
            "date": race_date_str,
            "predicted_finish_seconds": rp.get("estimated_finish_seconds"),
            "projected_ctl": round(projected_ctl, 4) if projected_ctl is not None else None,
        })

    if ctl_series:
        peak_ctl = max(ctl_series)
        peak_idx = ctl_series.index(peak_ctl)
        peak_date = start_date + timedelta(days=peak_idx + 1)
        yr, wk, _ = peak_date.isocalendar()
        peak_week = f"{yr}-W{wk:02d}"
    else:
        peak_ctl = None
        peak_week = None

    return {
        "races": races_out,
        "peak_ctl": peak_ctl,
        "peak_week": peak_week,
        "formula_version": formula_version,
    }


def maybe_write_prediction_snapshot(
    user_id: uuid.UUID | str,
    snapshot_date: date,
    payload: dict,
) -> None:
    """Persist a prediction snapshot for user_id on snapshot_date.

    Uses INSERT … ON CONFLICT DO NOTHING so the first computation of the day
    wins and later same-day recomputes are silently ignored.
    """
    with Session(engine) as db:
        db.execute(
            _text(
                "INSERT INTO prediction_snapshots (user_id, snapshot_date, payload) "
                "VALUES (:uid, :d, :payload::jsonb) "
                "ON CONFLICT (user_id, snapshot_date) DO NOTHING"
            ),
            {
                "uid": str(user_id),
                "d": snapshot_date,
                "payload": _json_dumps(payload),
            },
        )
        db.commit()


def list_snapshots(
    user_id: uuid.UUID | str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict]:
    """Return prediction snapshots for user_id optionally filtered by date range."""
    with Session(engine) as db:
        query = _text(
            "SELECT snapshot_date, payload, created_at "
            "FROM prediction_snapshots "
            "WHERE user_id = :uid "
            + ("AND snapshot_date >= :from_date " if from_date else "")
            + ("AND snapshot_date <= :to_date " if to_date else "")
            + "ORDER BY snapshot_date"
        )
        params: dict[str, Any] = {"uid": str(user_id)}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date

        rows = db.execute(query, params).fetchall()

    return [
        {
            "snapshot_date": str(row.snapshot_date),
            "payload": row.payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj)
