"""Calibration sprints — a bounded measurement week, never a diet.

The framing is the feature
--------------------------
Five to seven days of deliberate logging, once a month, **with the end date
visible from the moment it starts**. That bound is not a detail: an open-ended
"just track your food for a while" is precisely the shape of the five attempts
that already failed. A sprint the athlete can see the end of is one they finish.

So the copy here says *measurement*, never *diet*, and ``assert_measurement_copy``
enforces that at import — the same trick ``deficit_guard`` uses for its eat-more
contract, for the same reason.

What it produces
----------------
A maintenance recalibration. ``fuel.calibrate`` already does the arithmetic; it
just refused to run without 14 days and 10 fuel entries, which no structural-
deficit athlete will ever have. A sprint supplies a deliberate 5-7 day burst
instead, and ``SPRINT_MIN_LOGGED_DAYS`` is what the recalibration needs.

Nothing here logs food, prescribes intake, or scores adherence. It opens a
window, counts the days that landed in it, and closes on its own date.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta, timezone as _tz
from typing import Optional

from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# Sprint length bounds. Shorter than 5 days can't recalibrate; longer than 7
# stops being a sprint and starts being a diet.
MIN_SPRINT_DAYS = 5
MAX_SPRINT_DAYS = 7
DEFAULT_SPRINT_DAYS = 7
# Logged days needed before the sprint can produce a maintenance number.
SPRINT_MIN_LOGGED_DAYS = 5
# Monthly cadence: a new sprint is due this many days after the last one started.
SPRINT_CADENCE_DAYS = 28

STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_ABANDONED = "abandoned"

_BANNED_WORDS = ("diet", "cut harder", "restrict", "cheat", "willpower", "discipline")


def assert_measurement_copy(message: str) -> str:
    """A sprint is a measurement week. Copy that frames it as a diet is a bug."""
    lowered = message.lower()
    for word in _BANNED_WORDS:
        if word in lowered:
            raise ValueError(f"sprint copy must not say {word!r}: {message!r}")
    return message


COPY = {
    "active": "Measurement week — log what you already eat. Ends {end_date}, {days_remaining} to go.",
    "ready": "Measurement week done — enough days logged to update your maintenance estimate.",
    "short": "Measurement week ended with {logged_days} days logged; {needed} are needed to update maintenance.",
    "idle": "No measurement week running.",
    "due": "A measurement week is due — 5 to 7 days of logging, then it closes itself.",
}

for _template in COPY.values():  # fail at import, not in front of the athlete
    assert_measurement_copy(_template)


class SprintError(ValueError):
    """Invalid sprint request — bad length, or one already running."""


def _today() -> _date:
    from backend.utils.time import today_bangkok

    return today_bangkok()


def start_sprint(
    db: Session,
    user_id,
    *,
    start_date: Optional[_date] = None,
    days: int = DEFAULT_SPRINT_DAYS,
    today: Optional[_date] = None,
):
    """Open a measurement window. Raises SprintError if one is already running."""
    from backend.models import CalibrationSprint

    today = today or _today()
    start_date = start_date or today

    if not (MIN_SPRINT_DAYS <= days <= MAX_SPRINT_DAYS):
        raise SprintError(
            f"a sprint runs {MIN_SPRINT_DAYS}-{MAX_SPRINT_DAYS} days, got {days}"
        )
    if start_date > today + _timedelta(days=7):
        raise SprintError("a sprint cannot start more than a week ahead")

    if active_sprint(db, user_id, today) is not None:
        raise SprintError("a measurement week is already running")

    sprint = CalibrationSprint(
        id=_uuid.uuid4(),
        user_id=user_id,
        start_date=start_date,
        # Inclusive of the start day: a 7-day sprint spans start..start+6.
        end_date=start_date + _timedelta(days=days - 1),
        status=STATUS_ACTIVE,
        logged_days=0,
    )
    db.add(sprint)
    db.flush()
    return sprint


def active_sprint(db: Session, user_id, today: Optional[_date] = None):
    """The sprint covering today, if any. Past its end date is not active."""
    from backend.models import CalibrationSprint

    today = today or _today()
    return (
        db.query(CalibrationSprint)
        .filter(
            CalibrationSprint.user_id == user_id,
            CalibrationSprint.status == STATUS_ACTIVE,
            CalibrationSprint.start_date <= today,
            CalibrationSprint.end_date >= today,
        )
        .order_by(CalibrationSprint.start_date.desc())
        .first()
    )


def latest_sprint(db: Session, user_id):
    from backend.models import CalibrationSprint

    return (
        db.query(CalibrationSprint)
        .filter(CalibrationSprint.user_id == user_id)
        .order_by(CalibrationSprint.start_date.desc())
        .first()
    )


def count_logged_days(db: Session, user_id, start: _date, end: _date) -> int:
    """Days inside the window with a fuel entry carrying real intake."""
    from backend.models import FuelEntry

    rows = (
        db.query(FuelEntry)
        .filter(
            FuelEntry.user_id == user_id,
            FuelEntry.entry_date >= start,
            FuelEntry.entry_date <= end,
        )
        .all()
    )
    from backend.services.fuel import compute_food_totals

    return sum(1 for row in rows if (compute_food_totals(row) or {}).get("kcal", 0) > 0)


def sprint_status(db: Session, user_id, today: Optional[_date] = None) -> dict:
    """Everything a surface needs: countdown, progress, and what happens next.

    ``days_remaining`` counts the end date itself, so the last day of a sprint
    reads "1 to go" rather than "0" — the athlete still has that day to log.
    """
    today = today or _today()
    sprint = active_sprint(db, user_id, today)

    if sprint is None:
        latest = latest_sprint(db, user_id)
        due = True
        next_due_date = None
        if latest is not None:
            next_due = latest.start_date + _timedelta(days=SPRINT_CADENCE_DAYS)
            next_due_date = next_due.isoformat()
            due = today >= next_due
        return {
            "active": False,
            "start_date": None,
            "end_date": None,
            "days_remaining": None,
            "logged_days": 0,
            "min_logged_days": SPRINT_MIN_LOGGED_DAYS,
            "can_recalibrate": False,
            "due": due,
            "next_due_date": next_due_date,
            "message": COPY["due"] if due else COPY["idle"],
        }

    logged = count_logged_days(db, user_id, sprint.start_date, min(today, sprint.end_date))
    days_remaining = (sprint.end_date - today).days + 1

    return {
        "active": True,
        "start_date": sprint.start_date.isoformat(),
        "end_date": sprint.end_date.isoformat(),
        "days_remaining": days_remaining,
        "logged_days": logged,
        "min_logged_days": SPRINT_MIN_LOGGED_DAYS,
        "can_recalibrate": logged >= SPRINT_MIN_LOGGED_DAYS,
        "due": False,
        "next_due_date": None,
        "message": COPY["active"].format(
            end_date=sprint.end_date.isoformat(),
            days_remaining=(
                "1 day" if days_remaining == 1 else f"{days_remaining} days"
            ),
        ),
    }


def close_sprint(
    db: Session,
    user_id,
    *,
    today: Optional[_date] = None,
    abandon: bool = False,
) -> dict:
    """End the sprint and, when enough days landed, recalibrate maintenance.

    A sprint that fell short is **completed, not failed** — the copy names the
    shortfall and moves on. There is no penalty state, because a measurement
    that didn't take is not a moral event.
    """
    from backend.models import CalibrationSprint

    today = today or _today()
    sprint = (
        db.query(CalibrationSprint)
        .filter(
            CalibrationSprint.user_id == user_id,
            CalibrationSprint.status == STATUS_ACTIVE,
        )
        .order_by(CalibrationSprint.start_date.desc())
        .first()
    )
    if sprint is None:
        return {"closed": False, "reason": "no sprint running"}

    logged = count_logged_days(db, user_id, sprint.start_date, min(today, sprint.end_date))
    sprint.logged_days = logged
    sprint.completed_at = _datetime.now(_tz.utc)

    if abandon:
        sprint.status = STATUS_ABANDONED
        sprint.result_note = "ended early"
        db.flush()
        return {"closed": True, "status": STATUS_ABANDONED, "logged_days": logged}

    sprint.status = STATUS_COMPLETED

    if logged < SPRINT_MIN_LOGGED_DAYS:
        sprint.result_note = COPY["short"].format(
            logged_days=logged, needed=SPRINT_MIN_LOGGED_DAYS
        )
        db.flush()
        return {
            "closed": True,
            "status": STATUS_COMPLETED,
            "logged_days": logged,
            "recalibrated": False,
            "message": sprint.result_note,
        }

    result = recalibrate_from_sprint(db, user_id, sprint, today=today)
    sprint.result_base_kcal = result.get("new_base_kcal")
    sprint.result_note = result.get("message") or COPY["ready"]
    db.flush()
    return {
        "closed": True,
        "status": STATUS_COMPLETED,
        "logged_days": logged,
        "recalibrated": bool(result.get("recalibrated")),
        **result,
    }


def recalibrate_from_sprint(db: Session, user_id, sprint, today: Optional[_date] = None) -> dict:
    """Run ``fuel.calibrate`` over the sprint window and persist the result.

    The stock calibrate demands 14 days and 10 fuel entries — thresholds no
    structural-deficit athlete will ever reach, which is why this feature stalls
    at ``insufficient_data`` without a sprint. The sprint supplies a deliberate
    burst instead, so the minimums are relaxed to the sprint's own bounds.
    """
    from backend.models import FuelEntry, FuelSettings, WeightEntry
    from backend.services import fuel as fuel_svc

    today = today or _today()
    start = sprint.start_date
    end = min(sprint.end_date, today)

    weight_rows = (
        db.query(WeightEntry.entry_date, WeightEntry.weight_kg)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= start,
            WeightEntry.entry_date <= end,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    weight_entries = [(r[0], float(r[1])) for r in weight_rows]

    settings_row = fuel_svc.get_or_create_settings(user_id, db=db)
    settings = fuel_svc.settings_to_dict(settings_row)

    fuel_rows = (
        db.query(FuelEntry)
        .filter(
            FuelEntry.user_id == user_id,
            FuelEntry.entry_date >= start,
            FuelEntry.entry_date <= end,
        )
        .order_by(FuelEntry.entry_date.asc())
        .all()
    )

    triples = []
    for row in fuel_rows:
        eaten = (fuel_svc.compute_food_totals(row) or {}).get("kcal", 0)
        if not eaten:
            continue
        burn_info = fuel_svc.training_burn_kcal(
            user_id, row.entry_date, settings["weight_kg"],
            settings["run_kcal_per_kg_per_km"], today=today, db=db,
        )
        triples.append(
            (row.entry_date, eaten, settings["base_kcal"], burn_info["burn"])
        )

    if len(weight_entries) < MIN_SPRINT_DAYS or len(triples) < SPRINT_MIN_LOGGED_DAYS:
        return {
            "recalibrated": False,
            "message": COPY["short"].format(
                logged_days=len(triples), needed=SPRINT_MIN_LOGGED_DAYS
            ),
        }

    try:
        result = fuel_svc.calibrate(
            weight_entries,
            triples,
            min_days=MIN_SPRINT_DAYS,
            min_entries=SPRINT_MIN_LOGGED_DAYS,
        )
    except Exception as exc:
        _log.warning("sprint recalibration failed: %s", exc)
        return {"recalibrated": False, "message": f"could not recalibrate: {exc}"}

    settings_row.base_kcal = result["new_base_kcal"]
    settings_row.maintenance_source = "measured"
    db.flush()

    return {
        "recalibrated": True,
        "new_base_kcal": result["new_base_kcal"],
        "maintenance_source": "measured",
        "actual_delta_kg": result["actual_delta_kg"],
        "predicted_delta_kg": result["predicted_delta_kg"],
        "message": COPY["ready"],
    }
