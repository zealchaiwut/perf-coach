"""Weight-tracking state — ACTIVE or PAUSED, derived from weigh-in dates alone.

Why this exists
---------------
Adherence decays; that's normal and predictable. An app that escalates when the
athlete slips — louder nudges, red days, catch-up guilt — is an app that gets
muted, and a muted app can't help. So the program **lowers its demands** instead:
after a week with no weigh-ins the tracking state flips to PAUSED, the nudge drops
to weekly, and every cut verdict goes quiet until data comes back.

A cut the app pauses is a cut the athlete didn't fail. That framing is the whole
point, and it only works if the copy on the other side of the flip is genuinely
softer — see ``PAUSED_COPY``.

State machine
-------------
::

        ACTIVE ──── RESUME_MISSES consecutive days, no weigh-in ────► PAUSED
          ▲                                                            │
          └──── RESUME_ENTRIES weigh-ins within RESUME_WINDOW days ────┘

**Derived, never stored.** A pure function over weigh-in dates, so the state can't
go stale behind a background job that didn't run, and any caller — the nudge
sender, ``cut_review``, the weight card, the coach export — computes the same
answer from the same rows.

Hysteresis
----------
The thresholds are deliberately asymmetric: 7 missed days to pause, but 3 weigh-ins
inside a week to resume. One lone weigh-in after a fortnight off does NOT flip the
state back — otherwise a single Tuesday morning restarts the daily nudge, the
athlete goes quiet again on Wednesday, and the app oscillates between nagging and
silence. Resuming should mean "I'm actually back", not "I stepped on the scale
once".

Four consumers read this: the nudge sender (cadence + copy), ``cut_review`` (a
gate — no rate claims without data), the weight card (copy), and the coach export
(``meta.tracking_state``, so a pasted coach knows not to nag about deliberately
paused data).
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from typing import Iterable, Optional
from backend.utils.time import today_bangkok

ACTIVE = "active"
PAUSED = "paused"

# Consecutive days with no weigh-in before tracking pauses (spec D11).
PAUSE_AFTER_MISSED_DAYS = 7
# Weigh-ins required inside RESUME_WINDOW_DAYS to come back to ACTIVE.
RESUME_ENTRIES = 3
RESUME_WINDOW_DAYS = 7

# Copy lives with the state so the two can't drift. The paused line must never
# imply fault, ask for catch-up, or mention food.
ACTIVE_COPY = "weight tracking on"
PAUSED_COPY = "weight tracking paused — training continues."

# Nudge cadence per state. Paused does not mean silent forever; it means one
# gentle weekly ask instead of a daily one.
NUDGE_CADENCE = {ACTIVE: "daily", PAUSED: "weekly"}


def _normalize(weigh_in_dates: Iterable) -> list[_date]:
    """Unique dates, ascending. Two weigh-ins on one day are one day of data."""
    seen: set[_date] = set()
    for raw in weigh_in_dates or []:
        if raw is None:
            continue
        d = raw if isinstance(raw, _date) else _date.fromisoformat(str(raw))
        seen.add(d)
    return sorted(seen)


def compute_tracking_state(weigh_in_dates: Iterable, today: _date) -> dict:
    """Return the current tracking state for a set of weigh-in dates.

    Parameters
    ----------
    weigh_in_dates:
        Every weigh-in date on record (``datetime.date`` or ISO string). Order
        and duplicates don't matter. Dates after ``today`` are ignored.
    today:
        The day being evaluated.

    Returns
    -------
    dict with keys:
        ``state``            — ``"active"`` | ``"paused"``
        ``paused_since``     — ISO date the pause began, else None
        ``last_weigh_in``    — ISO date of the most recent weigh-in, else None
        ``days_since_last``  — int, or None when there has never been one
        ``entries_last_7d``  — weigh-in days inside the resume window
        ``nudge_cadence``    — ``"daily"`` | ``"weekly"``
        ``copy``             — the line to show for this state
        ``logged_today``     — whether today already has a weigh-in

    A user with no weigh-ins at all is ACTIVE, not PAUSED: nothing has decayed
    yet, and the first nudge is exactly what should reach them.
    """
    dates = [d for d in _normalize(weigh_in_dates) if d <= today]

    window_start = today - _timedelta(days=RESUME_WINDOW_DAYS - 1)
    entries_last_7d = sum(1 for d in dates if d >= window_start)
    logged_today = bool(dates) and dates[-1] == today

    if not dates:
        return {
            "state": ACTIVE,
            "paused_since": None,
            "last_weigh_in": None,
            "days_since_last": None,
            "entries_last_7d": 0,
            "nudge_cadence": NUDGE_CADENCE[ACTIVE],
            "copy": ACTIVE_COPY,
            "logged_today": False,
        }

    last = dates[-1]
    days_since_last = (today - last).days

    # The machine has MEMORY: "paused, then logged once" is not the same as
    # "has been logging", even though both can show a recent weigh-in. So walk
    # the timeline and apply the transitions in order rather than judging the
    # last few days in isolation — that shortcut is what lets a single Tuesday
    # weigh-in silently restart the daily nudge.
    date_set = set(dates)
    state = ACTIVE
    paused_since: Optional[str] = None
    day = dates[0]
    while day <= today:
        prior = [d for d in dates if d <= day]
        if state == ACTIVE:
            if prior and (day - prior[-1]).days >= PAUSE_AFTER_MISSED_DAYS:
                state = PAUSED
                paused_since = day.isoformat()
        else:
            window_from = day - _timedelta(days=RESUME_WINDOW_DAYS - 1)
            recent = sum(1 for d in date_set if window_from <= d <= day)
            if recent >= RESUME_ENTRIES:
                state = ACTIVE
                paused_since = None
        day += _timedelta(days=1)

    return {
        "state": state,
        "paused_since": paused_since,
        "last_weigh_in": last.isoformat(),
        "days_since_last": days_since_last,
        "entries_last_7d": entries_last_7d,
        "nudge_cadence": NUDGE_CADENCE[state],
        "copy": PAUSED_COPY if state == PAUSED else ACTIVE_COPY,
        "logged_today": logged_today,
    }


def state_for_user(db, user_id, today: Optional[_date] = None) -> dict:
    """``compute_tracking_state`` over a user's stored weigh-ins.

    Thin DB wrapper so the four consumers don't each hand-roll the query. The
    lookback covers the resume window plus the pause threshold with room to
    spare — older rows can't change the answer.
    """
    from backend.models import WeightEntry

    today = today or today_bangkok()
    lookback_start = today - _timedelta(days=90)

    rows = (
        db.query(WeightEntry.entry_date)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= lookback_start,
            WeightEntry.entry_date <= today,
        )
        .all()
    )
    return compute_tracking_state([r[0] for r in rows], today)


def should_nudge(state: dict, today: _date) -> bool:
    """Whether a weight nudge should go out today.

    Silent when today is already logged — the nudge exists to ask for a number,
    not to confirm one. Paused users get one ask per week (Monday), not none:
    the point is a lower demand, not abandonment.
    """
    if state.get("logged_today"):
        return False
    if state.get("state") == PAUSED:
        return today.weekday() == 0
    return True
