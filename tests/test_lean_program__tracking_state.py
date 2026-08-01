"""Phase 1 — tracking state and the weight nudge (lean-program spec §4, §6, §12).

The design premise is that adherence decays, so the app must lower its demands
when the athlete slips instead of escalating. These tests pin the two halves of
that:

- the **state machine** — 7 missed days pauses, 3 weigh-ins in 7 resumes, and one
  lone weigh-in does not flip it back and forth;
- the **nudge** — exactly one message type, weight only, silent when already
  logged, and copy that never implies fault.

Spec §12 asks for a static test asserting the nudge sender has one message type
referencing weight only. That is here, and it reads the source rather than the
runtime, because the failure it guards against is somebody *adding* a second
message later.
"""
from __future__ import annotations

import datetime
import inspect
import re

import pytest

from backend.services import tracking_state as ts
from backend.services.tracking_state import (
    ACTIVE,
    PAUSE_AFTER_MISSED_DAYS,
    PAUSED,
    RESUME_ENTRIES,
    RESUME_WINDOW_DAYS,
    compute_tracking_state,
    should_nudge,
)

TODAY = datetime.date(2026, 7, 30)  # Thursday


def _days_ago(*offsets: int) -> list:
    return [TODAY - datetime.timedelta(days=n) for n in offsets]


# ── ACTIVE → PAUSED ──────────────────────────────────────────────────────────

def test_seven_consecutive_missed_days_pauses():
    """Spec D11 — the documented trigger."""
    state = compute_tracking_state(_days_ago(PAUSE_AFTER_MISSED_DAYS), TODAY)
    assert state["state"] == PAUSED


def test_six_missed_days_does_not_pause():
    """The boundary matters: pausing a day early reads as the app giving up."""
    state = compute_tracking_state(_days_ago(PAUSE_AFTER_MISSED_DAYS - 1), TODAY)
    assert state["state"] == ACTIVE


def test_paused_state_reports_when_the_pause_began():
    state = compute_tracking_state(_days_ago(10), TODAY)
    assert state["state"] == PAUSED
    expected = (
        TODAY - datetime.timedelta(days=10) + datetime.timedelta(days=PAUSE_AFTER_MISSED_DAYS)
    )
    assert state["paused_since"] == expected.isoformat()


def test_active_state_has_no_paused_since():
    assert compute_tracking_state(_days_ago(0, 1, 2), TODAY)["paused_since"] is None


# ── PAUSED → ACTIVE ──────────────────────────────────────────────────────────

def test_three_weigh_ins_within_seven_days_resumes():
    """Coming back from a long gap: the recent data wins over the old silence."""
    state = compute_tracking_state(_days_ago(40, 39, 38, 0, 2, 4), TODAY)
    assert state["entries_last_7d"] >= RESUME_ENTRIES
    assert state["state"] == ACTIVE


def test_one_lone_weigh_in_after_a_long_gap_does_not_resume():
    """Spec §12 explicitly: one weigh-in must not flip the state back and forth.
    Otherwise a single Tuesday restarts the daily nudge, the athlete goes quiet
    again on Wednesday, and the app oscillates between nagging and silence."""
    state = compute_tracking_state(_days_ago(40, 39, 38, 0), TODAY)
    assert state["entries_last_7d"] == 1
    assert state["state"] == PAUSED


def test_two_weigh_ins_in_the_window_still_paused():
    state = compute_tracking_state(_days_ago(40, 39, 0, 3), TODAY)
    assert state["entries_last_7d"] == 2
    assert state["state"] == PAUSED


def test_resume_needs_the_entries_inside_the_window():
    """Three weigh-ins spread over a month is not "I'm back"."""
    state = compute_tracking_state(_days_ago(30, 20, 10), TODAY)
    assert state["state"] == PAUSED


def test_the_thresholds_are_asymmetric_on_purpose():
    """Hysteresis: harder to resume than to pause, so the state doesn't chatter."""
    assert RESUME_ENTRIES < PAUSE_AFTER_MISSED_DAYS
    assert RESUME_WINDOW_DAYS == 7


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_a_brand_new_user_is_active_not_paused():
    """Nothing has decayed yet, and the first nudge is exactly what should reach
    them."""
    state = compute_tracking_state([], TODAY)
    assert state["state"] == ACTIVE
    assert state["last_weigh_in"] is None
    assert state["days_since_last"] is None


def test_two_weigh_ins_on_one_day_count_as_one_day():
    state = compute_tracking_state([TODAY, TODAY, TODAY], TODAY)
    assert state["entries_last_7d"] == 1


def test_iso_strings_are_accepted():
    state = compute_tracking_state(["2026-07-30", "2026-07-29"], TODAY)
    assert state["last_weigh_in"] == "2026-07-30"


def test_future_dated_entries_are_ignored():
    future = TODAY + datetime.timedelta(days=5)
    state = compute_tracking_state([future] + _days_ago(10), TODAY)
    assert state["state"] == PAUSED
    assert state["last_weigh_in"] == (TODAY - datetime.timedelta(days=10)).isoformat()


def test_none_entries_are_skipped():
    state = compute_tracking_state([None, TODAY], TODAY)
    assert state["last_weigh_in"] == TODAY.isoformat()


def test_logged_today_is_reported():
    assert compute_tracking_state([TODAY], TODAY)["logged_today"] is True
    assert compute_tracking_state(_days_ago(1), TODAY)["logged_today"] is False


# ── Nudge cadence and silence ────────────────────────────────────────────────

def test_active_state_nudges_daily():
    state = compute_tracking_state(_days_ago(1, 2, 3), TODAY)
    assert state["nudge_cadence"] == "daily"
    assert should_nudge(state, TODAY) is True


def test_already_logged_today_is_silent():
    """Spec §12 — the nudge exists to ask for a number, not to confirm one."""
    state = compute_tracking_state(_days_ago(0, 1, 2), TODAY)
    assert should_nudge(state, TODAY) is False


def test_paused_state_drops_to_weekly_not_to_nothing():
    """Lower demand, not abandonment."""
    state = compute_tracking_state(_days_ago(20), TODAY)
    assert state["nudge_cadence"] == "weekly"
    monday = datetime.date(2026, 7, 27)
    assert should_nudge(state, monday) is True
    assert should_nudge(state, datetime.date(2026, 7, 28)) is False


# ── Copy ─────────────────────────────────────────────────────────────────────

def test_paused_copy_says_training_continues():
    state = compute_tracking_state(_days_ago(20), TODAY)
    assert state["copy"] == "weight tracking paused — training continues."


@pytest.mark.parametrize(
    "banned", ["fail", "failed", "behind", "catch up", "try harder", "streak", "missed"]
)
def test_paused_copy_never_implies_fault(banned):
    """A cut the app pauses is a cut the athlete didn't fail — the copy has to
    carry that, or the pause reads as a scolding."""
    assert banned not in ts.PAUSED_COPY.lower()


@pytest.mark.parametrize("food_word", ["eat", "calorie", "food", "diet", "deficit", "meal"])
def test_no_state_copy_mentions_food(food_word):
    """Spec D7 — never a food nudge."""
    assert food_word not in ts.PAUSED_COPY.lower()
    assert food_word not in ts.ACTIVE_COPY.lower()


# ── Static guard: one message type, weight only (spec §12) ───────────────────

def _nudge_source() -> str:
    import backend.worker_app as worker

    return inspect.getsource(worker.weight_nudge)


def test_nudge_sender_has_exactly_one_message_field():
    """Two message types is how a food nudge gets added later without anyone
    noticing."""
    source = _nudge_source()
    assignments = re.findall(r'^\s*message\s*=\s*"', source, re.MULTILINE)
    # One per branch (active / paused), assigned to the same single field.
    assert source.count('"message":') == 1
    assert len(assignments) == 2


@pytest.mark.parametrize(
    "food_word", ["calorie", "kcal", "protein", "food", "eat ", "meal", "deficit", "diet"]
)
def test_nudge_message_never_mentions_food(food_word):
    source = _nudge_source()
    messages = re.findall(r'^\s*message\s*=\s*"([^"]*)"', source, re.MULTILINE)
    assert messages, "expected the nudge to define its message inline"
    for msg in messages:
        assert food_word not in msg.lower(), f"food word {food_word!r} in nudge copy: {msg}"


def test_nudge_message_asks_for_the_number():
    source = _nudge_source()
    messages = re.findall(r'^\s*message\s*=\s*"([^"]*)"', source, re.MULTILINE)
    assert any("number" in m.lower() for m in messages)


def test_nudge_window_is_the_morning():
    import backend.worker_app as worker

    assert 0 <= worker._WEIGHT_NUDGE_START_HOUR < worker._WEIGHT_NUDGE_END_HOUR <= 12


def test_weight_nudge_window_starts_before_the_plan_draft_window():
    """The weigh-in happens before breakfast; the draft nudge doesn't. Two
    windows, deliberately staggered."""
    import backend.worker_app as worker

    assert worker._WEIGHT_NUDGE_START_HOUR < 7
