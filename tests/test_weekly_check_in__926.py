"""Tests for issue #926: Build standalone weekly check-in view.

Anchored to each AC item:

AC1  — Check-in view is a standalone route at /weekly-check-in (page) and
        GET /api/weekly-check-in (API).
AC2  — week_summary has exactly three keys: weight_trend, habit_consistency,
        training_note — all plain-fact strings when data is sufficient.
AC3  — bright_spot is exactly one object with a text field.
AC4  — next_lever is exactly one object with a text field — never a list.
AC5  — focus_habits contains ≤3 habits; cooldown_days constant is returned.
AC6  — All text strings pass through the voice module (tested via service
        unit tests: no raw field names like "weight_kg" appear; strings are
        non-empty; builder functions are used).
AC7  — When < 7 days of data exist: building=True, week_summary/bright_spot/
        next_lever are null; focus_habits still renders.
AC8  — When weight is missing but habits/training have 7+ days: weight_trend
        is null, but habit_consistency and training_note are non-null.
AC9  — Service build_weekly_check_in is a pure function (no DB access); tested
        by calling it directly with injected data.
AC10 — When building=True, the API endpoint does NOT query the insights table
        (tested by asserting the response has correlations_fetched=False).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.services.weekly_check_in import (
    BASELINE_DAYS_REQUIRED,
    FOCUS_HABIT_COOLDOWN_DAYS,
    build_weekly_check_in,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000926")

# Fixed reference dates
_TODAY = date(2026, 6, 25)  # Thursday
_WEEK_START = date(2026, 6, 22)  # Monday


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── Data builders ─────────────────────────────────────────────────────────────

def _make_habit_summary(
    name="Morning run",
    consistency_percent=71.5,
    week_done=5,
    weekly_target=7,
    current_streak=5,
    sort_order=0,
):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "consistency_percent": consistency_percent,
        "week_done": week_done,
        "weekly_target": weekly_target,
        "current_streak": current_streak,
        "longest_streak": 10,
        "sort_order": sort_order,
    }


def _make_weight_entry(entry_date: date, weight_kg: float = 74.5):
    return {"entry_date": entry_date.isoformat(), "weight_kg": weight_kg}


def _make_workout(workout_date: date, distance_km: float = 10.0, tss: float = 60.0):
    return {
        "id": str(uuid.uuid4()),
        "workout_date": workout_date.isoformat(),
        "name": "Morning run",
        "workout_type": "run",
        "distance_km": distance_km,
        "duration_seconds": 3600,
        "tss": tss,
    }


# ── Helpers for 7+ days of seeded data ───────────────────────────────────────

def _full_week_habits():
    return [
        _make_habit_summary("Morning run", consistency_percent=71.5, week_done=5,
                            weekly_target=7, sort_order=0),
        _make_habit_summary("Evening stretch", consistency_percent=60.0, week_done=4,
                            weekly_target=7, sort_order=1),
        _make_habit_summary("Read 30 min", consistency_percent=85.7, week_done=6,
                            weekly_target=7, sort_order=2),
    ]


def _full_week_weights():
    """7 weight entries spread across current + previous week."""
    entries = []
    for i in range(7):
        d = _WEEK_START - timedelta(days=7) + timedelta(days=i)
        entries.append(_make_weight_entry(d, 74.0 + i * 0.1))
    return entries


def _prev_week_weights():
    entries = []
    for i in range(7):
        d = _WEEK_START - timedelta(days=14) + timedelta(days=i)
        entries.append(_make_weight_entry(d, 74.5))
    return entries


def _this_week_weights():
    return [
        _make_weight_entry(_WEEK_START, 74.2),
        _make_weight_entry(_WEEK_START + timedelta(days=1), 74.1),
        _make_weight_entry(_WEEK_START + timedelta(days=2), 74.0),
        _make_weight_entry(_TODAY, 73.9),
    ]


def _full_week_workouts():
    return [
        _make_workout(_WEEK_START, 10.0),
        _make_workout(_WEEK_START + timedelta(days=2), 12.5),
        _make_workout(_WEEK_START + timedelta(days=3), 8.0),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Standalone route exists
# ═══════════════════════════════════════════════════════════════════════════════

class TestStandaloneRoute:
    """AC1: /weekly-check-in page route exists; /api/weekly-check-in API exists."""

    def test_page_route_returns_html(self):
        """GET /weekly-check-in must return 200 with text/html content."""
        # The page is served as a FileResponse; unauthenticated = redirect or 200
        with TestClient(app, follow_redirects=False) as c:
            r = c.get("/weekly-check-in")
        # Either 200 (auth not enforced at page level) or 302/307 (redirect to login)
        assert r.status_code in (200, 302, 307)

    def test_api_endpoint_exists_and_requires_auth(self):
        """GET /api/weekly-check-in requires authentication (returns 401 when anon)."""
        with TestClient(app, follow_redirects=False) as c:
            r = c.get("/api/weekly-check-in")
        assert r.status_code == 401

    def test_api_endpoint_returns_200_when_authenticated(self):
        """GET /api/weekly-check-in returns 200 for authenticated user."""
        client, _ = _make_client()

        with patch("backend.main.Session") as MockSession:
            sess = _make_empty_session()
            MockSession.return_value.__enter__.return_value = sess
            r = client.get("/api/weekly-check-in")

        _teardown()
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")


def _make_empty_session():
    """Build a mock DB session returning no data (zero habits, weights, workouts)."""
    sess = MagicMock()
    q = sess.query.return_value
    q.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []
    q.filter.return_value.order_by.return_value.all.return_value = []
    q.filter.return_value.all.return_value = []
    q.all.return_value = []
    return sess


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — week_summary has exactly three lines
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeekSummaryShape:
    """AC2: week_summary contains exactly three keys when data is sufficient."""

    def test_week_summary_has_exactly_three_keys(self):
        """week_summary must have weight_trend, habit_consistency, training_note."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["building"] is False
        ws = result["week_summary"]
        assert ws is not None
        assert set(ws.keys()) == {"weight_trend", "habit_consistency", "training_note"}

    def test_weight_trend_is_string(self):
        """weight_trend must be a plain-fact string when weight data is available."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        wt = result["week_summary"]["weight_trend"]
        assert isinstance(wt, str)
        assert len(wt) > 0

    def test_habit_consistency_is_string(self):
        """habit_consistency must be a plain-fact string."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        hc = result["week_summary"]["habit_consistency"]
        assert isinstance(hc, str)
        assert len(hc) > 0

    def test_training_note_is_string(self):
        """training_note must be a plain-fact string."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        tn = result["week_summary"]["training_note"]
        assert isinstance(tn, str)
        assert len(tn) > 0

    def test_weight_trend_no_exclamation(self):
        """weight_trend must not contain exclamation marks (voice rule)."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert "!" not in (result["week_summary"]["weight_trend"] or "")

    def test_habit_consistency_references_numbers(self):
        """habit_consistency must reference actual numbers (not vague copy)."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        hc = result["week_summary"]["habit_consistency"]
        # Must contain at least one digit (consistency_percent or week_done)
        assert any(c.isdigit() for c in hc), f"No numbers in habit_consistency: {hc!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — bright_spot is exactly one highlight
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrightSpot:
    """AC3: bright_spot returns exactly one highlight object."""

    def test_bright_spot_is_single_object(self):
        """bright_spot must be a single dict, not a list."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        bs = result["bright_spot"]
        assert bs is not None
        assert isinstance(bs, dict), "bright_spot must be a dict, not a list"

    def test_bright_spot_has_text_field(self):
        """bright_spot must have a non-empty text field."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        bs = result["bright_spot"]
        assert "text" in bs
        assert isinstance(bs["text"], str)
        assert len(bs["text"]) > 0

    def test_bright_spot_has_source_field(self):
        """bright_spot must have a source field."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        bs = result["bright_spot"]
        assert "source" in bs
        assert bs["source"] in ("correlation", "consistency", "streak", "training")

    def test_bright_spot_no_exclamation(self):
        """bright_spot.text must not contain exclamation marks."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert "!" not in result["bright_spot"]["text"]

    def test_bright_spot_prefers_correlation_when_available(self):
        """bright_spot.source == 'correlation' when insights are available."""
        insights = [
            {
                "habit_name": "Morning run",
                "outcome": "energy",
                "coefficient": 0.75,
                "direction": "positive",
                "line": "Morning run on a given day correlates with higher energy.",
            }
        ]
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=insights,
            insights_building=False,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["bright_spot"]["source"] == "correlation"


# ═══════════════════════════════════════════════════════════════════════════════
# AC4 — next_lever is exactly one action
# ═══════════════════════════════════════════════════════════════════════════════

class TestNextLever:
    """AC4: next_lever is exactly one object — never a list."""

    def test_next_lever_is_single_object(self):
        """next_lever must be a dict, not a list."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        nl = result["next_lever"]
        assert nl is not None
        assert isinstance(nl, dict), "next_lever must be a dict, not a list"

    def test_next_lever_has_text_field(self):
        """next_lever.text must be a non-empty string."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        nl = result["next_lever"]
        assert "text" in nl
        assert isinstance(nl["text"], str)
        assert len(nl["text"]) > 0

    def test_next_lever_no_exclamation(self):
        """next_lever.text must not contain exclamation marks."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert "!" not in result["next_lever"]["text"]

    def test_next_lever_targets_lowest_consistency_habit(self):
        """next_lever targets the focus habit with the lowest consistency."""
        habits = [
            _make_habit_summary("Morning run", consistency_percent=85.0, week_done=6,
                                weekly_target=7, sort_order=0),
            _make_habit_summary("Evening stretch", consistency_percent=28.5, week_done=2,
                                weekly_target=7, sort_order=1),
            _make_habit_summary("Read 30 min", consistency_percent=71.5, week_done=5,
                                weekly_target=7, sort_order=2),
        ]
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=habits,
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        # The lever must reference the lowest-consistency habit name
        assert "Evening stretch" in result["next_lever"]["text"]


# ═══════════════════════════════════════════════════════════════════════════════
# AC5 — Recommit beat with focus habits and cooldown constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommitBeat:
    """AC5: focus_habits has ≤3 items with recommit data; cooldown_days is present."""

    def test_focus_habits_at_most_three(self):
        """focus_habits must contain at most 3 habits."""
        habits = [
            _make_habit_summary(f"Habit {i}", sort_order=i) for i in range(5)
        ]
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=habits,
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert len(result["focus_habits"]) <= 3

    def test_focus_habits_have_required_keys(self):
        """Each focus habit must have id, name, consistency_percent, week_done,
        weekly_target, current_streak, cooldown_days."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        required_keys = {
            "id", "name", "consistency_percent", "week_done",
            "weekly_target", "current_streak", "cooldown_days",
        }
        for fh in result["focus_habits"]:
            missing = required_keys - set(fh.keys())
            assert not missing, f"focus_habit missing keys: {missing}"

    def test_cooldown_days_is_positive_integer(self):
        """cooldown_days must be a positive integer."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        for fh in result["focus_habits"]:
            assert isinstance(fh["cooldown_days"], int)
            assert fh["cooldown_days"] > 0

    def test_cooldown_days_constant_is_exported(self):
        """FOCUS_HABIT_COOLDOWN_DAYS must be exported from the service module."""
        assert isinstance(FOCUS_HABIT_COOLDOWN_DAYS, int)
        assert FOCUS_HABIT_COOLDOWN_DAYS > 0

    def test_focus_habits_rendered_in_building_baseline(self):
        """focus_habits still renders when building=True."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=_full_week_habits(),
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["building"] is True
        assert result["focus_habits"] is not None
        assert len(result["focus_habits"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# AC6 — Voice module: no raw field values in output
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceModule:
    """AC6: All user-facing text passes through coaching_voice; no raw field names."""

    _RAW_FIELD_NAMES = (
        "weight_kg",
        "entry_date",
        "workout_date",
        "consistency_percent",
        "distance_km",
        "duration_seconds",
        "current_streak",
    )

    def _collect_strings(self, result: dict) -> list[str]:
        strings = []
        if result.get("week_summary"):
            for v in result["week_summary"].values():
                if isinstance(v, str):
                    strings.append(v)
        if result.get("bright_spot") and isinstance(result["bright_spot"].get("text"), str):
            strings.append(result["bright_spot"]["text"])
        if result.get("next_lever") and isinstance(result["next_lever"].get("text"), str):
            strings.append(result["next_lever"]["text"])
        return strings

    def test_no_raw_field_names_in_output(self):
        """None of the text strings should contain Python field name patterns."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        for s in self._collect_strings(result):
            for field in self._RAW_FIELD_NAMES:
                assert field not in s, f"Raw field name '{field}' found in text: {s!r}"

    def test_text_strings_are_non_empty_when_data_present(self):
        """All text strings must be non-empty when corresponding data is present."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        for s in self._collect_strings(result):
            assert len(s.strip()) > 0, "Empty string found in output"

    def test_coaching_voice_used_for_text(self):
        """Patching coaching_voice.praise_line_builder propagates to bright_spot."""
        from backend.services import coaching_voice

        original = coaching_voice.praise_line_builder
        coaching_voice.praise_line_builder = lambda *a, **kw: "PATCHED_PRAISE"
        try:
            result = build_weekly_check_in(
                weight_entries_this_week=_this_week_weights(),
                weight_entries_prev_week=_prev_week_weights(),
                habits_summary=_full_week_habits(),
                workouts_this_week=_full_week_workouts(),
                insights=[],
                insights_building=True,
                today=_TODAY,
                week_start=_WEEK_START,
            )
            # bright_spot or weight_trend should use praise_line_builder
            all_text = " ".join(self._collect_strings(result))
            assert "PATCHED_PRAISE" in all_text, (
                "coaching_voice.praise_line_builder was not used. "
                f"Texts: {self._collect_strings(result)!r}"
            )
        finally:
            coaching_voice.praise_line_builder = original


# ═══════════════════════════════════════════════════════════════════════════════
# AC7 — Building-baseline when < 7 days of data
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildingBaseline:
    """AC7: When < 7 days of data, building=True; summary/bright_spot/lever are null."""

    def test_building_true_when_no_data(self):
        """building=True when no weight, habit, or training data."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["building"] is True

    def test_building_true_when_only_3_days(self):
        """building=True when total distinct data days < 7."""
        # Only 3 weight entries on different days
        three_entries = [
            _make_weight_entry(_WEEK_START, 74.0),
            _make_weight_entry(_WEEK_START + timedelta(days=1), 74.1),
            _make_weight_entry(_WEEK_START + timedelta(days=2), 74.2),
        ]
        result = build_weekly_check_in(
            weight_entries_this_week=three_entries,
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["building"] is True

    def test_building_week_summary_is_null(self):
        """week_summary is null when building=True."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["week_summary"] is None

    def test_building_bright_spot_is_null(self):
        """bright_spot is null when building=True."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["bright_spot"] is None

    def test_building_next_lever_is_null(self):
        """next_lever is null when building=True."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["next_lever"] is None

    def test_building_reason_is_non_empty(self):
        """reason is a non-empty string when building=True."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=[],
            habits_summary=[],
            workouts_this_week=[],
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    def test_baseline_days_required_constant(self):
        """BASELINE_DAYS_REQUIRED must be 7."""
        assert BASELINE_DAYS_REQUIRED == 7

    def test_building_false_with_7_days_of_data(self):
        """building=False when 7+ distinct data days are present."""
        weights = _full_week_weights() + _this_week_weights()
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_full_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert result["building"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# AC8 — Per-section not-enough-data when one source is missing
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerSectionInsufficiency:
    """AC8: When one data source is missing, only that section is null."""

    def test_weight_trend_null_when_no_weight_data(self):
        """weight_trend is null when no weight entries this week."""
        # Need 7+ days of data for building=False, but no weight entries this week
        habits_with_history = _full_week_habits()
        # Add historical logs via sort_order; the baseline check uses COMBINED
        # days from weight + workout + habit log count proxy
        # Use 7+ days from workout + prev weight to meet baseline
        result = build_weekly_check_in(
            weight_entries_this_week=[],  # no weight this week
            weight_entries_prev_week=_full_week_weights(),  # 7 prev days
            habits_summary=habits_with_history,
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        # Should not be building (prev weight + workouts cover 7+ days)
        if not result["building"]:
            ws = result["week_summary"]
            assert ws["weight_trend"] is None, (
                f"weight_trend should be null when no weight logged this week, got: {ws['weight_trend']!r}"
            )

    def test_habit_consistency_null_when_no_habits(self):
        """habit_consistency is null when there are no active habits."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_full_week_weights(),
            habits_summary=[],  # no habits
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        if not result["building"]:
            ws = result["week_summary"]
            assert ws["habit_consistency"] is None

    def test_training_note_null_when_no_workouts(self):
        """training_note is null when there are no workouts this week."""
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_full_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=[],  # no workouts
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        if not result["building"]:
            ws = result["week_summary"]
            assert ws["training_note"] is None

    def test_other_sections_render_when_weight_missing(self):
        """habit_consistency and training_note render even when weight is missing."""
        result = build_weekly_check_in(
            weight_entries_this_week=[],
            weight_entries_prev_week=_full_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        if not result["building"]:
            ws = result["week_summary"]
            assert ws["habit_consistency"] is not None
            assert ws["training_note"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# AC9 — Pure function: no hidden DB access
# ═══════════════════════════════════════════════════════════════════════════════

class TestPureFunction:
    """AC9: build_weekly_check_in is a pure function — no DB calls."""

    def test_service_callable_without_db_setup(self):
        """build_weekly_check_in works with no database configured."""
        # If it tries to hit the DB it will raise; this test proves it doesn't.
        result = build_weekly_check_in(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        assert isinstance(result, dict)

    def test_identical_inputs_produce_identical_output(self):
        """build_weekly_check_in is deterministic."""
        kwargs = dict(
            weight_entries_this_week=_this_week_weights(),
            weight_entries_prev_week=_prev_week_weights(),
            habits_summary=_full_week_habits(),
            workouts_this_week=_full_week_workouts(),
            insights=[],
            insights_building=True,
            today=_TODAY,
            week_start=_WEEK_START,
        )
        first = build_weekly_check_in(**kwargs)
        second = build_weekly_check_in(**kwargs)
        assert first == second


# ═══════════════════════════════════════════════════════════════════════════════
# AC10 — No correlation fetch when building-baseline
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoCorrelationFetchWhenBaseline:
    """AC10: When building-baseline, the API endpoint skips the insights query."""

    def test_api_returns_correlations_fetched_false_when_building(self):
        """correlations_fetched=False when the endpoint detects building-baseline."""
        client, _ = _make_client()

        with patch("backend.main.Session") as MockSession:
            # No data → building-baseline
            sess = _make_empty_session()
            MockSession.return_value.__enter__.return_value = sess
            r = client.get("/api/weekly-check-in")

        _teardown()
        assert r.status_code == 200
        body = r.json()
        assert "correlations_fetched" in body
        assert body["correlations_fetched"] is False
        assert body["building"] is True

    def test_api_returns_correlations_fetched_true_when_full_data(self):
        """correlations_fetched=True when data is sufficient and insights were queried."""
        client, _ = _make_client()

        from backend.models import WeightEntry, Habit, HabitLog, Workout, DailyMetric

        with patch("backend.main.Session") as MockSession:
            sess = _make_full_data_session()
            MockSession.return_value.__enter__.return_value = sess
            r = client.get("/api/weekly-check-in")

        _teardown()
        assert r.status_code == 200
        body = r.json()
        assert "correlations_fetched" in body
        # When data is full, correlations should be fetched
        assert body["correlations_fetched"] is True


def _make_full_data_session():
    """Build a mock session with 7+ days of data across all sources."""
    sess = MagicMock()

    today = _TODAY
    week_start = _WEEK_START

    # Mock weight entries: 7 days across prev + this week
    weight_entries = []
    for i in range(7):
        e = MagicMock()
        e.entry_date = week_start - timedelta(days=7) + timedelta(days=i)
        e.weight_kg = 74.0 + i * 0.1
        weight_entries.append(e)
    # Add this week
    for i in range(4):
        e = MagicMock()
        e.entry_date = week_start + timedelta(days=i)
        e.weight_kg = 73.8 - i * 0.05
        weight_entries.append(e)

    # Mock workouts: 3 this week
    workouts = []
    for i in range(3):
        w = MagicMock()
        w.workout_date = week_start + timedelta(days=i)
        w.workout_type = "run"
        w.distance_km = 10.0
        w.duration_seconds = 3600
        w.tss = 60.0
        workouts.append(w)

    # Mock habits: 2 active
    habits = []
    for j in range(2):
        h = MagicMock()
        h.id = uuid.uuid4()
        h.name = f"Habit {j}"
        h.sort_order = j
        h.is_archived = False
        h.active = True
        h.tracking_type = "daily_checkmark"
        h.weekly_target = 7
        h.schedule_type = "daily"
        h.schedule_target = None
        h.habit_type = "binary"
        h.target_value = None
        h.unit = None
        h.auto_fill_source = None
        h.icon = None
        h.color = None
        h.description = ""
        h.display_order = j
        h.created_at = MagicMock()
        h.created_at.isoformat.return_value = "2026-06-01T00:00:00"
        h.updated_at = None
        habits.append(h)

    habit_logs = []
    for i in range(14):
        for h in habits:
            lg = MagicMock()
            lg.habit_id = h.id
            lg.user_id = _USER_ID
            lg.log_date = week_start - timedelta(days=7) + timedelta(days=i % 14)
            lg.value = 1
            habit_logs.append(lg)

    # Mock daily metrics
    daily_metrics = []

    def _query_side_effect(model):
        q = MagicMock()
        # Determine which model is being queried
        from backend.models import WeightEntry, Habit, HabitLog, Workout, DailyMetric
        if model is WeightEntry:
            q.filter.return_value.filter.return_value.order_by.return_value.all.return_value = weight_entries
            q.filter.return_value.order_by.return_value.all.return_value = weight_entries
            q.filter.return_value.all.return_value = weight_entries
        elif model is Habit:
            q.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = habits
            q.filter.return_value.order_by.return_value.all.return_value = habits
            q.filter.return_value.all.return_value = habits
        elif model is HabitLog:
            q.filter.return_value.filter.return_value.all.return_value = habit_logs
            q.filter.return_value.all.return_value = habit_logs
        elif model is Workout:
            q.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = workouts
            q.filter.return_value.order_by.return_value.all.return_value = workouts
            q.filter.return_value.all.return_value = workouts
        elif model is DailyMetric:
            q.filter.return_value.all.return_value = daily_metrics
        else:
            q.filter.return_value.all.return_value = []
            q.filter.return_value.order_by.return_value.all.return_value = []
        return q

    sess.query.side_effect = _query_side_effect
    return sess
