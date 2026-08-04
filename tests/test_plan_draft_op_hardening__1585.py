"""Plan draft op hardening (issue #1585).

Four AC items:
AC1 - day bounds validated: move/swap/add reject day_offset outside 0-6.
AC2 - TSS floor holds under ACWR ceiling in remove(redistribute).
AC3 - update_draft_slot() has draft_version optimistic-concurrency guard (409 on stale).
AC4 - workout fetch in partial_skeleton_budget is user-scoped (no cross-user read).

AC1 and AC2 are pure unit tests (no DB needed).
AC3 and AC4 use a real Postgres DB (DATABASE_URL_UAT); they are auto-marked
`integration` by tests/conftest.py and skipped when Postgres is unavailable.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch


from backend.services import plan_skeleton_ops as ops
from backend.services.plan_draft import draft_version_token


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_sessions(days_tss: dict[int, float]) -> list[dict]:
    return [
        {
            "slot_id": str(uuid.uuid4()),
            "day_offset": d,
            "workout_type": "run",
            "subtype": "easy_run",
            "target_tss": tss,
            "duration_minutes": 30,
            "locked": False,
        }
        for d, tss in days_tss.items()
    ]


# ── AC1: day bounds 0-6 ───────────────────────────────────────────────────────

class TestDayBoundsValidation:
    """move/swap/add must reject day values outside 0-6."""

    def test_move_rejects_day_below_zero(self):
        sessions = _make_sessions({0: 40, 3: 50})
        slot_id = sessions[0]["slot_id"]
        result = ops.move(sessions, slot_id=slot_id, to_day=-1)
        assert result["blocked"] is True

    def test_move_rejects_day_above_six(self):
        sessions = _make_sessions({0: 40, 3: 50})
        slot_id = sessions[0]["slot_id"]
        result = ops.move(sessions, slot_id=slot_id, to_day=7)
        assert result["blocked"] is True

    def test_move_rejects_day_99(self):
        sessions = _make_sessions({0: 40, 3: 50})
        slot_id = sessions[0]["slot_id"]
        result = ops.move(sessions, slot_id=slot_id, to_day=99)
        assert result["blocked"] is True

    def test_swap_rejects_day_below_zero(self):
        sessions = _make_sessions({0: 40, 3: 50})
        result = ops.swap(sessions, day_a=-1, day_b=3)
        assert result["blocked"] is True

    def test_swap_rejects_day_above_six(self):
        sessions = _make_sessions({0: 40, 3: 50})
        result = ops.swap(sessions, day_a=0, day_b=7)
        assert result["blocked"] is True

    def test_add_rejects_day_below_zero(self):
        sessions = _make_sessions({3: 50})
        result = ops.add(sessions, day=-1, kind="easy_run")
        assert result["blocked"] is True

    def test_add_rejects_day_above_six(self):
        sessions = _make_sessions({3: 50})
        result = ops.add(sessions, day=7, kind="easy_run")
        assert result["blocked"] is True

    def test_move_accepts_valid_day(self):
        sessions = _make_sessions({0: 40, 5: 0})
        sessions[1]["workout_type"] = "rest"
        slot_id = sessions[0]["slot_id"]
        result = ops.move(sessions, slot_id=slot_id, to_day=5, confirm_warnings=True)
        assert result["blocked"] is False

    def test_swap_accepts_valid_days(self):
        sessions = _make_sessions({0: 40, 3: 50})
        result = ops.swap(sessions, day_a=0, day_b=3, confirm_warnings=True)
        assert result["blocked"] is False

    def test_add_accepts_valid_day(self):
        sessions = _make_sessions({3: 50})
        result = ops.add(sessions, day=6, kind="easy_run", confirm_warnings=True)
        assert result["blocked"] is False


# ── AC2: TSS floor holds under ACWR ceiling ───────────────────────────────────

class TestTSSFloorUnderCeiling:
    """remove(redistribute) floor=15 must not be violated by ceiling cap."""

    def _run_remove_redistribute(self, *, old_tss: float, acwr_ceiling: float | None, dropped_tss: float):
        slots = [
            {
                "slot_id": "keep",
                "day_offset": 1,
                "workout_type": "run",
                "subtype": "easy_run",
                "target_tss": old_tss,
                "duration_minutes": 30,
                "locked": False,
            },
            {
                "slot_id": "drop",
                "day_offset": 3,
                "workout_type": "run",
                "subtype": "easy_run",
                "target_tss": dropped_tss,
                "duration_minutes": 40,
                "locked": False,
            },
        ]
        return ops.remove(slots, slot_id="drop", mode="redistribute", acwr_ceiling=acwr_ceiling)

    def test_floor_holds_when_ceiling_would_push_below_floor(self):
        # old=12, tight ceiling → ceiling cap would clip below 15 without fix
        result = self._run_remove_redistribute(old_tss=12.0, acwr_ceiling=13.0, dropped_tss=30.0)
        assert result["blocked"] is False
        keep = next(s for s in result["slots"] if s.get("slot_id") == "keep")
        assert keep["target_tss"] >= ops._PER_SLOT_TSS_FLOOR

    def test_floor_holds_when_ceiling_equals_current_sum(self):
        # room=0 → add=0; slot should remain >= floor regardless
        result = self._run_remove_redistribute(old_tss=20.0, acwr_ceiling=20.0, dropped_tss=30.0)
        assert result["blocked"] is False
        keep = next(s for s in result["slots"] if s.get("slot_id") == "keep")
        assert keep["target_tss"] >= ops._PER_SLOT_TSS_FLOOR

    def test_floor_holds_normal_redistribute_no_ceiling(self):
        result = self._run_remove_redistribute(old_tss=20.0, acwr_ceiling=None, dropped_tss=30.0)
        assert result["blocked"] is False
        keep = next(s for s in result["slots"] if s.get("slot_id") == "keep")
        assert keep["target_tss"] >= ops._PER_SLOT_TSS_FLOOR

    def test_floor_holds_when_old_already_below_floor(self):
        result = self._run_remove_redistribute(old_tss=5.0, acwr_ceiling=6.0, dropped_tss=20.0)
        keep = next(s for s in result["slots"] if s.get("slot_id") == "keep")
        assert keep["target_tss"] >= ops._PER_SLOT_TSS_FLOOR

    def test_floor_does_not_apply_to_rest_slots(self):
        slots = [
            {"slot_id": "rest", "day_offset": 1, "workout_type": "rest",
             "subtype": "rest", "target_tss": 0, "duration_minutes": 0, "locked": False},
            {"slot_id": "drop", "day_offset": 3, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 40, "duration_minutes": 40, "locked": False},
        ]
        result = ops.remove(slots, slot_id="drop", mode="redistribute", acwr_ceiling=5.0)
        rest = next(s for s in result["slots"] if s.get("slot_id") == "rest")
        assert rest["target_tss"] == 0


# ── AC3: update_draft_slot version guard (unit, no real DB) ──────────────────

def _make_mock_row(version: int = 1) -> MagicMock:
    """Build a mock PlanDraft row for testing version guard logic."""
    row = MagicMock()
    row.updated_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    row.facts_signature = "a" * 32
    row.payload = {
        "version": version,
        "sessions": [
            {
                "slot_id": "slot-a",
                "day_offset": 2,
                "workout_type": "run",
                "target_tss": 40,
                "duration_minutes": 30,
                "intent": "Easy run",
                "source": "template",
            }
        ],
        "slots": [],
    }
    return row


class TestUpdateDraftSlotVersionGuard:
    """update_draft_slot must reject stale draft_version tokens."""

    def _call_update(self, row, draft_version, day_offset=2, patch=None):
        from backend.services.plan_draft import update_draft_slot
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        if patch is None:
            patch = {"intent": "Updated"}
        return update_draft_slot(db, "user-1", date(2026, 8, 3), day_offset, patch=patch, draft_version=draft_version)

    def test_correct_version_passes(self):
        row = _make_mock_row()
        token = draft_version_token(row)
        result = self._call_update(row, token)
        # Should not be a stale_draft error; result is the updated payload dict
        assert not (isinstance(result, dict) and result.get("error") == "stale_draft")

    def test_wrong_version_returns_stale_draft(self):
        row = _make_mock_row()
        result = self._call_update(row, "wrong:token:abc123456789")
        assert isinstance(result, dict)
        assert result.get("error") == "stale_draft"
        assert result.get("status_code") == 409

    def test_none_version_skips_guard(self):
        """Callers omitting draft_version are never rejected (backwards compat)."""
        row = _make_mock_row()
        result = self._call_update(row, None)
        assert not (isinstance(result, dict) and result.get("error") == "stale_draft")

    def test_no_draft_returns_none(self):
        from backend.services.plan_draft import update_draft_slot
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = update_draft_slot(db, "u", date(2026, 8, 3), 2, patch={"intent": "x"}, draft_version="tok")
        assert result is None

    def test_stale_response_includes_fresh_token(self):
        """The 409 response must include the current token so the client can retry."""
        row = _make_mock_row()
        good_token = draft_version_token(row)
        result = self._call_update(row, "stale:token:old")
        assert result.get("draft_version") == good_token


# ── AC4: workout fetch is user-scoped (unit, no real DB) ─────────────────────

class TestReplanRemainingBudgetWorkoutScope:
    """replan_remaining_budget must not count TSS from another user's Workout."""

    def _make_db_mock(self, *, workout_owner_id, requesting_user_id, workout_tss: float):
        from backend.models import PlannedSession, Workout

        workout_id = uuid.uuid4()
        week = date(2026, 7, 28)

        mock_workout = MagicMock(spec=Workout)
        mock_workout.tss = workout_tss
        mock_workout.user_id = workout_owner_id

        mock_ps = MagicMock(spec=PlannedSession)
        mock_ps.planned_date = week
        mock_ps.status = "done_auto"
        mock_ps.matched_workout_id = workout_id

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [mock_ps]
        db.get.return_value = mock_workout
        return db, week

    def _call(self, db, user_id, week):
        from backend.services.plan_draft import replan_remaining_budget

        prefs = {"preferred_rest_days": [], "strength_emphasis": False, "notes": ""}
        facts = {"trailing_28d_weekly_avg_tss": 0}
        budget_stub = {
            "target_before_safety": 300.0, "weekly_target": 300.0,
            "acwr_ceiling": 400.0, "logged_tss_so_far": 0.0,
            "remaining_tss": 300.0, "open_slot_count": 5,
            "per_open_slot_tss": 60.0, "source": "stub",
            "phase": None, "taper_applied": False,
        }
        with patch("backend.services.plan_draft.get_plan_prefs", return_value=prefs):
            with patch("backend.services.plan_draft.assemble_facts", return_value=facts):
                with patch("backend.services.plan_draft._load_history_rows", return_value=[]):
                    with patch("backend.services.plan_skeleton.weekly_budget", return_value=budget_stub):
                        with patch("backend.services.plan_skeleton.build_skeleton", return_value={"sessions": []}):
                            with patch("backend.services.plan_draft.apply_prefs_extras", return_value={"sessions": []}):
                                return replan_remaining_budget(db, user_id, week, today=date(2026, 8, 4))

    def test_cross_user_workout_tss_not_counted(self):
        """Workout owned by user B must not appear in user A's matched_actual_tss."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        db, week = self._make_db_mock(
            workout_owner_id=user_b,
            requesting_user_id=user_a,
            workout_tss=80.0,
        )
        result = self._call(db, user_a, week)
        assert result["matched_actual_tss"] == 0.0

    def test_own_workout_tss_is_counted(self):
        """Workout owned by the requesting user must be counted in matched_actual_tss."""
        user_a = uuid.uuid4()
        db, week = self._make_db_mock(
            workout_owner_id=user_a,
            requesting_user_id=user_a,
            workout_tss=75.0,
        )
        result = self._call(db, user_a, week)
        assert result["matched_actual_tss"] > 0.0
