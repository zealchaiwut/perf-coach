"""Stretch, plyo and the monthly benchmark — prefs-driven additions to a week.

Spec D5: stretch, plyo and drills move **out of habits into the plan**. A checkbox
asks the athlete to remember and then to confirm; a planned session that verifies
itself from a logged workout does neither. Habits keep their ``general`` section
as-is.

Why this is a post-pass, not surgery inside ``build_skeleton``
--------------------------------------------------------------
``plan_skeleton.build_skeleton`` is a deterministic engine with several callers
and a tested "same inputs ⇒ identical skeleton" contract. Threading three more
preferences through its budget maths risks changing existing weeks for everyone.

So this decorates the skeleton it is given: same slots, same TSS, with extras
attached. Callers opt in by calling it, and a caller that doesn't gets exactly
today's behaviour. When plyo lands as a standalone session it *does* claim a day,
which is the one case that changes a slot — and it only ever claims a day the
skeleton left as rest or easy.

What gets attached
------------------
========  ===================================================================
stretch   ``daily_extras`` on every non-rest day (and rest days too — mobility
          on a rest day is the point). Carries no TSS: it is not a session.
plyo      ``superset`` mode hangs it off a strength day; ``standalone`` takes
          its own slot. Off by default.
benchmark the month's first long run is flagged, so the correlation evidence in
          ``habit_evidence`` gets a fixed-effort signal to compare against
          instead of whatever the week happened to contain.
========  ===================================================================
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from typing import Any, Optional

# A plyo block is short; when it shares a day with strength it adds little.
PLYO_STANDALONE_TSS = 20
PLYO_SUPERSET_TSS = 8
PLYO_DURATION_MIN = 20
# Days the standalone plyo session may claim, in preference order: it wants to
# be fresh, so it goes as far from the long run as the week allows.
_PLYO_PREFERRED_DAYS = (1, 2, 3, 0, 4)


def _is_rest(slot: dict) -> bool:
    return (slot.get("workout_type") or "") == "rest"


def _is_locked(slot: dict) -> bool:
    return bool(slot.get("locked"))


def attach_stretch(slots: list[dict], stretch_daily_min: int) -> list[dict]:
    """Add a daily mobility extra to every day, including rest days.

    Carries no TSS — stretching is not a training session and must not consume
    the week's load budget. Zero or unset leaves the week untouched.
    """
    if not stretch_daily_min or stretch_daily_min <= 0:
        return slots
    for slot in slots:
        extras = list(slot.get("daily_extras") or [])
        extras.append({
            "kind": "stretch",
            "duration_minutes": int(stretch_daily_min),
            "target_tss": 0,
            "source": "prefs.stretch_daily_min",
        })
        slot["daily_extras"] = extras
    return slots


def attach_plyo(
    slots: list[dict],
    *,
    plyo_mode: str = "off",
    plyo_sessions_per_week: int = 0,
    rest_days: Optional[set[int]] = None,
) -> list[dict]:
    """Place plyo per the athlete's preference. ``off`` leaves the week alone."""
    mode = (plyo_mode or "off").lower()
    sessions = int(plyo_sessions_per_week or 0)
    if mode == "off" or sessions <= 0:
        return slots

    rest = set(rest_days or ())
    placed = 0

    if mode == "superset":
        # Hangs off a strength day: no new session, minimal added load.
        for slot in slots:
            if placed >= sessions:
                break
            if _is_locked(slot) or slot.get("workout_type") != "strength":
                continue
            extras = list(slot.get("daily_extras") or [])
            extras.append({
                "kind": "plyo",
                "duration_minutes": PLYO_DURATION_MIN,
                "target_tss": PLYO_SUPERSET_TSS,
                "source": "prefs.plyo_mode=superset",
            })
            slot["daily_extras"] = extras
            placed += 1
        return slots

    # Standalone: claim a day the skeleton left rest or easy, preferring midweek
    # so the session is fresh and far from the long run. If that weekday has no
    # slot at all (sparse history skeleton), invent a short plyo day there.
    by_day = {int(s["day_offset"]): s for s in slots}
    for day in _PLYO_PREFERRED_DAYS:
        if placed >= sessions:
            break
        if day in rest:
            continue
        slot = by_day.get(day)
        if slot is None:
            new_slot = {
                "day_offset": day,
                "workout_type": "plyo",
                "subtype": "plyo",
                "target_tss": PLYO_STANDALONE_TSS,
                "duration_minutes": PLYO_DURATION_MIN,
                "intent": "",
                "notes": None,
                "exercises": None,
                "blocks": None,
                "source": "prefs.plyo_mode=standalone",
            }
            slots.append(new_slot)
            by_day[day] = new_slot
            placed += 1
            continue
        if _is_locked(slot):
            continue
        if not _is_rest(slot) and not _is_easy_run_claimable(slot):
            continue
        slot.update({
            "workout_type": "plyo",
            "subtype": "plyo",
            "target_tss": PLYO_STANDALONE_TSS,
            "duration_minutes": PLYO_DURATION_MIN,
            "source": "prefs.plyo_mode=standalone",
            # Clear stale run content so Fill/Update builds plyo exercises.
            "intent": "",
            "notes": None,
            "exercises": None,
            "blocks": None,
        })
        placed += 1
    slots.sort(key=lambda s: int(s.get("day_offset") or 0))
    return slots


def _is_easy_run_claimable(slot: dict) -> bool:
    """Standalone plyo may replace rest or an easy/untagged run — never quality."""
    if (slot.get("workout_type") or "") != "run":
        return False
    sub = str(slot.get("subtype") or "").lower()
    return sub in ("", "easy", "easy_run")


def is_benchmark_week(week_start: _date) -> bool:
    """Whether this week holds the month's first long run.

    Monthly cadence, decided from the calendar rather than stored, so it can't
    drift out of sync with a job that didn't run.
    """
    return week_start.day <= 7


def attach_benchmark(slots: list[dict], week_start: _date) -> list[dict]:
    """Flag the week's long run as the monthly benchmark effort.

    A fixed route at a fixed effort once a month gives ``habit_evidence`` a clean
    signal to correlate against — without it, "HR drift on long runs" compares
    a flat 90-minute run to a hilly two-hour one and reports the terrain.
    """
    if not is_benchmark_week(week_start):
        return slots
    for slot in slots:
        if slot.get("subtype") == "long_run" and not _is_locked(slot):
            slot["benchmark"] = True
            hints = dict(slot.get("structure_hints") or {})
            hints["benchmark"] = "fixed route, fixed effort — comparable month to month"
            slot["structure_hints"] = hints
            break
    return slots


def apply_prefs_extras(
    skeleton: dict[str, Any],
    *,
    prefs: Optional[dict] = None,
    week_start: Optional[_date] = None,
    rest_days: Optional[set[int]] = None,
) -> dict[str, Any]:
    """Decorate a built skeleton with stretch, plyo and the monthly benchmark.

    Returns a new dict; the input skeleton is not mutated. With empty prefs and
    a non-benchmark week this is the identity function, which is what keeps
    existing callers unaffected.
    """
    prefs = prefs or {}
    slots = [dict(s) for s in (skeleton.get("slots") or [])]

    if week_start is None:
        raw = skeleton.get("week_start")
        week_start = _date.fromisoformat(raw) if isinstance(raw, str) else raw

    attach_stretch(slots, int(prefs.get("stretch_daily_min") or 0))
    plyo_mode = prefs.get("plyo_mode", "off")
    plyo_sessions = int(prefs.get("plyo_sessions_per_week") or 0)
    # Plyo / week alone should create short sessions. Mode=off with a positive
    # count used to no-op and left the UI looking broken; treat as standalone.
    if plyo_sessions > 0 and (plyo_mode or "off").lower() == "off":
        plyo_mode = "standalone"
    attach_plyo(
        slots,
        plyo_mode=plyo_mode,
        plyo_sessions_per_week=plyo_sessions,
        rest_days=rest_days,
    )
    if week_start is not None:
        attach_benchmark(slots, week_start)
    attach_mp_segment(slots, int(prefs.get("long_run_mp_segment_min") or 0))

    out = dict(skeleton)
    out["slots"] = slots
    return out


def attach_mp_segment(slots: list[dict], mp_min: int) -> list[dict]:
    """Stamp long_run.mp_segment_min onto the week's long-run slot for pattern fill."""
    mp_min = int(mp_min or 0)
    if mp_min <= 0:
        return slots
    for slot in slots:
        if slot.get("subtype") == "long_run" and not _is_locked(slot):
            hints = dict(slot.get("structure_hints") or {})
            hints["mp_segment_min"] = mp_min
            slot["structure_hints"] = hints
            slot["mp_segment_min"] = mp_min
            break
    return slots


def planned_extras_summary(slots: list[dict]) -> dict:
    """What the week actually asks for, for the export's plan block."""
    stretch_min = 0
    plyo_sessions = 0
    benchmark = False
    for slot in slots or []:
        if slot.get("benchmark"):
            benchmark = True
        if slot.get("workout_type") == "plyo":
            plyo_sessions += 1
        for extra in slot.get("daily_extras") or []:
            if extra.get("kind") == "stretch":
                stretch_min += int(extra.get("duration_minutes") or 0)
            elif extra.get("kind") == "plyo":
                plyo_sessions += 1
    return {
        "stretch_minutes_planned": stretch_min,
        "plyo_sessions_planned": plyo_sessions,
        "benchmark_week": benchmark,
    }
