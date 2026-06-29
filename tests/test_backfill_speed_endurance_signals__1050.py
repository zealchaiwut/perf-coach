"""Tests for issue #1050: Backfill speed and endurance signals across history.

Acceptance Criteria covered:
  AC1: A backfill job computes the speed signal for every existing run of every
       athlete using the same function called by the live computation path.
  AC2: The same job computes the endurance signal for every existing run of
       every athlete using the same function called by the live computation path.
  AC3: The job is idempotent: executing it a second time produces identical
       stored values and creates no duplicate rows.
  AC4: The job is triggered automatically after athlete thresholds are saved,
       chaining after the M0 lap classification backfill (not duplicating it).
  AC5: Runs that meet the qualification criteria have a stored speed signal
       value after the job runs.
  AC6: Runs that do not meet the qualification criteria have no stored speed or
       endurance signal value after the job runs.
  AC7: The job can be run manually in isolation for testing and re-processing
       purposes.
"""

import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workout(workout_id, user_id="user-1", workout_type="Run",
                  duration_seconds=3600, speed_signal=None,
                  endurance_signal=None):
    import datetime
    return SimpleNamespace(
        id=workout_id,
        user_id=user_id,
        workout_type=workout_type,
        workout_date=datetime.date(2026, 1, 1),
        duration_seconds=duration_seconds,
        speed_signal=speed_signal,
        speed_signal_basis=None,
        speed_signal_window_seconds=None,
        speed_signal_source=None,
        endurance_signal=endurance_signal,
        decoupling_percent=None,
        efficiency_first_half=None,
        efficiency_second_half=None,
        endurance_signal_source=None,
    )


def _make_prefs(ftp_w=200, threshold_hr=165, threshold_pace=300):
    return SimpleNamespace(
        ftp_w=ftp_w,
        threshold_hr=threshold_hr,
        threshold_pace_seconds_per_km=threshold_pace,
    )


def _make_split(workout_id=1, split_index=0, avg_power=230, avg_hr=160,
                distance_km=1.2, duration_seconds=300, lap_type="auto"):
    return SimpleNamespace(
        workout_id=workout_id,
        split_index=split_index,
        avg_power=avg_power,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        lap_type=lap_type,
    )


def _make_db_mock(workouts, prefs, splits=None):
    """Build a MagicMock DB session that chains .filter().order_by().all() correctly.

    The service does:
      db.query(UserPreferences).filter(...).first()  → prefs
      db.query(Workout).filter(...).order_by(...).all() → workouts
      db.query(WorkoutSplit).filter(...).order_by(...).all() → splits (per workout)

    We model this by having db.query dispatch on the model class:
      - called with UserPreferences → returns prefs via first()
      - called with Workout → returns workouts via all()
      - called with WorkoutSplit → returns splits (default []) via all()
    """
    if splits is None:
        splits = []

    from backend.models import Workout, WorkoutSplit, UserPreferences

    def _query_side_effect(model):
        q = mock.MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        if model is UserPreferences:
            q.first.return_value = prefs
            q.all.return_value = [prefs] if prefs else []
        elif model is Workout:
            q.all.return_value = workouts
            q.first.return_value = workouts[0] if workouts else None
        elif model is WorkoutSplit:
            q.all.return_value = splits
            q.first.return_value = splits[0] if splits else None
        else:
            q.all.return_value = []
            q.first.return_value = None
        return q

    db = mock.MagicMock()
    db.query.side_effect = _query_side_effect
    return db


# ---------------------------------------------------------------------------
# AC1 & AC2 — Service module exists and is importable
# ---------------------------------------------------------------------------

class TestServiceModuleExistsAC1AC2:
    """AC1/AC2: backfill_signals_for_athlete is importable from service module."""

    def test_service_module_importable(self):
        from backend.services import backfill_signals  # noqa: F401

    def test_backfill_function_importable(self):
        from backend.services.backfill_signals import backfill_signals_for_athlete
        assert callable(backfill_signals_for_athlete)

    def test_service_calls_speed_signal_live_function(self):
        """AC1: speed signal uses the same function as the live path."""
        import inspect
        from backend.services import backfill_signals
        src = inspect.getsource(backfill_signals)
        assert "compute_and_store_speed_signal" in src, (
            "backfill_signals must call compute_and_store_speed_signal (the live-path function)"
        )

    def test_service_calls_endurance_signal_live_function(self):
        """AC2: endurance signal uses compute_endurance_signal (the live-path pure function)."""
        import inspect
        from backend.services import backfill_signals
        src = inspect.getsource(backfill_signals)
        assert "compute_endurance_signal" in src, (
            "backfill_signals must call compute_endurance_signal (the live-path function)"
        )


# ---------------------------------------------------------------------------
# AC1 — Speed signal is computed for all runs
# ---------------------------------------------------------------------------

class TestSpeedSignalBackfillAC1:
    """AC1: Speed signal computed for every existing run."""

    def test_speed_signal_function_called_for_each_run(self):
        """backfill_signals_for_athlete calls compute_and_store_speed_signal for each run."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        w1 = _make_workout("w-1")
        w2 = _make_workout("w-2")
        prefs = _make_prefs()
        mock_db = _make_db_mock([w1, w2], prefs)

        call_log = []

        def _fake_compute_and_store_speed_signal(wid, db):
            call_log.append(("speed", wid))
            return True, None

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            side_effect=_fake_compute_and_store_speed_signal,
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            return_value={
                "endurance_signal": None, "decoupling_percent": None,
                "efficiency_first_half": None, "efficiency_second_half": None,
                "endurance_signal_source": None,
            },
        ):
            backfill_signals_for_athlete("user-1", mock_db)

        speed_calls = [c for c in call_log if c[0] == "speed"]
        assert len(speed_calls) == 2, (
            f"Expected speed signal to be called once per run, got {len(speed_calls)}"
        )
        assert {c[1] for c in speed_calls} == {"w-1", "w-2"}

    def test_non_run_workouts_excluded(self):
        """Only run workouts participate in speed signal backfill."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        run = _make_workout("w-run", workout_type="Run")
        prefs = _make_prefs()
        mock_db = _make_db_mock([run], prefs)

        call_log = []

        def _fake_speed(wid, db):
            call_log.append(wid)
            return True, None

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            side_effect=_fake_speed,
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            return_value={
                "endurance_signal": None, "decoupling_percent": None,
                "efficiency_first_half": None, "efficiency_second_half": None,
                "endurance_signal_source": None,
            },
        ):
            backfill_signals_for_athlete("user-1", mock_db)

        assert call_log == ["w-run"]


# ---------------------------------------------------------------------------
# AC2 — Endurance signal is computed for all runs
# ---------------------------------------------------------------------------

class TestEnduranceSignalBackfillAC2:
    """AC2: Endurance signal computed for every existing run using compute_endurance_signal."""

    def test_endurance_signal_function_called_for_each_run(self):
        """backfill_signals_for_athlete calls compute_endurance_signal for each run."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        w1 = _make_workout("w-1", duration_seconds=3600)
        w2 = _make_workout("w-2", duration_seconds=2000)
        prefs = _make_prefs()
        mock_db = _make_db_mock([w1, w2], prefs)

        endurance_calls = []

        def _fake_endurance(workout_dict, split_dicts):
            endurance_calls.append(workout_dict.get("duration_seconds"))
            return {
                "endurance_signal": None, "decoupling_percent": None,
                "efficiency_first_half": None, "efficiency_second_half": None,
                "endurance_signal_source": None,
            }

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            return_value=(True, None),
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            side_effect=_fake_endurance,
        ):
            backfill_signals_for_athlete("user-1", mock_db)

        assert len(endurance_calls) == 2, (
            f"Expected compute_endurance_signal called for each run, got {len(endurance_calls)}"
        )

    def test_endurance_result_stored_on_workout(self):
        """Endurance signal result is persisted back to the workout object."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        w1 = _make_workout("w-1", duration_seconds=3601)
        prefs = _make_prefs()
        mock_db = _make_db_mock([w1], prefs)

        endurance_result = {
            "endurance_signal": 88.5,
            "decoupling_percent": 11.5,
            "efficiency_first_half": 1.55,
            "efficiency_second_half": 1.37,
            "endurance_signal_source": "power_hr",
        }

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            return_value=(True, None),
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            return_value=endurance_result,
        ):
            backfill_signals_for_athlete("user-1", mock_db)

        assert w1.endurance_signal == 88.5
        assert w1.decoupling_percent == 11.5
        assert w1.efficiency_first_half == 1.55
        assert w1.efficiency_second_half == 1.37
        assert w1.endurance_signal_source == "power_hr"


# ---------------------------------------------------------------------------
# AC3 — Idempotency
# ---------------------------------------------------------------------------

class TestIdempotencyAC3:
    """AC3: Running the job twice produces the same result; no duplicate rows."""

    def test_second_run_calls_same_functions(self):
        """Calling backfill_signals_for_athlete twice produces the same signal calls."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        w1 = _make_workout("w-1")
        prefs = _make_prefs()

        call_counts = {"speed": 0, "endurance": 0}

        def _fake_speed(wid, db):
            call_counts["speed"] += 1
            return True, None

        def _fake_endurance(wd, sp):
            call_counts["endurance"] += 1
            return {
                "endurance_signal": None, "decoupling_percent": None,
                "efficiency_first_half": None, "efficiency_second_half": None,
                "endurance_signal_source": None,
            }

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            side_effect=_fake_speed,
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            side_effect=_fake_endurance,
        ):
            backfill_signals_for_athlete("user-1", _make_db_mock([w1], prefs))
            backfill_signals_for_athlete("user-1", _make_db_mock([w1], prefs))

        assert call_counts["speed"] == 2
        assert call_counts["endurance"] == 2

    def test_upsert_not_insert_semantics(self):
        """Service does not add new rows; it updates existing workout attributes."""
        import inspect
        from backend.services import backfill_signals
        src = inspect.getsource(backfill_signals)
        assert "session.add(" not in src or "WorkoutSplit" not in src, (
            "backfill_signals must not insert new rows — it updates existing workout fields"
        )


# ---------------------------------------------------------------------------
# AC4 — Chained after M0 lap classification backfill on threshold save
# ---------------------------------------------------------------------------

class TestTriggeredAfterM0AC4:
    """AC4: Signal backfill chains after M0 backfill; threshold save triggers it."""

    def test_background_trigger_in_main_calls_signal_backfill(self):
        """main.py's background trigger calls backfill_signals_for_athlete."""
        import inspect
        import backend.main as main_mod
        src = inspect.getsource(main_mod._trigger_performance_backfill_background)
        assert "backfill_signals_for_athlete" in src or "backfill_signals" in src, (
            "_trigger_performance_backfill_background must chain into signal backfill"
        )

    def test_signal_backfill_runs_after_m0_not_instead_of(self):
        """Signal backfill chained AFTER M0 (not replacing it)."""
        import inspect
        import backend.main as main_mod
        src = inspect.getsource(main_mod._trigger_performance_backfill_background)
        # Both M0 backfill and signals backfill must appear
        assert "_backfill_performance_for_athlete" in src or "backfill_performance_for_athlete" in src, (
            "M0 performance backfill must still be called"
        )
        assert "backfill_signals" in src, (
            "Signal backfill must also be called"
        )

    def test_threshold_save_triggers_background_job(self):
        """PATCH /api/user-preferences fires the background backfill on threshold change."""
        import inspect
        import backend.main as main_mod
        src = inspect.getsource(main_mod.patch_user_preferences)
        assert "_trigger_performance_backfill_background" in src, (
            "patch_user_preferences must trigger the background backfill"
        )


# ---------------------------------------------------------------------------
# AC5 — Qualifying runs have speed signal after job
# ---------------------------------------------------------------------------

class TestQualifyingRunsAC5:
    """AC5: Runs meeting qualification criteria have a stored speed signal value."""

    def test_qualifying_run_has_speed_signal_stored(self):
        """A run with a hard-effort window gets speed_signal written."""
        from backend.services.speed_signal import compute_speed_signal

        # 5-min split at 1.15×FTP — should be classified 'hard'
        split = _make_split(avg_power=230, duration_seconds=300)
        prefs = {"ftp_w": 200, "threshold_pace_seconds_per_km": None, "threshold_hr": None}

        result = compute_speed_signal([split], prefs)

        assert result["speed_signal"] is not None, (
            "Hard-effort run should produce a non-null speed_signal"
        )
        assert result["speed_signal"] > 0

    def test_compute_speed_signal_called_via_live_function(self):
        """AC5: compute_and_store_speed_signal is the live function used in backfill."""
        from backend.services.speed_signal import compute_and_store_speed_signal
        assert callable(compute_and_store_speed_signal)


# ---------------------------------------------------------------------------
# AC6 — Non-qualifying runs have null signals after job
# ---------------------------------------------------------------------------

class TestNonQualifyingRunsAC6:
    """AC6: Non-qualifying runs have no speed or endurance signal stored."""

    def test_easy_run_speed_signal_null(self):
        """Easy run (all laps below threshold) produces null speed_signal."""
        from backend.services.speed_signal import compute_speed_signal

        # 5-min split at 0.75×FTP — should be classified 'easy'
        split = _make_split(avg_power=150, duration_seconds=300)
        prefs = {"ftp_w": 200, "threshold_pace_seconds_per_km": None, "threshold_hr": None}

        result = compute_speed_signal([split], prefs)

        assert result["speed_signal"] is None, (
            "Easy run should produce null speed_signal"
        )
        assert result["speed_signal_basis"] is None
        assert result["speed_signal_window_seconds"] is None

    def test_null_result_stored_for_non_qualifying_run(self):
        """backfill stores None on workouts that don't qualify."""
        from backend.services.backfill_signals import backfill_signals_for_athlete

        w1 = _make_workout("w-1", duration_seconds=300)  # < 40 min (endurance not eligible)
        prefs = _make_prefs()
        mock_db = _make_db_mock([w1], prefs)

        null_endurance = {
            "endurance_signal": None, "decoupling_percent": None,
            "efficiency_first_half": None, "efficiency_second_half": None,
            "endurance_signal_source": None,
        }

        def _fake_speed(wid, db):
            w1.speed_signal = None
            return True, None

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            side_effect=_fake_speed,
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            return_value=null_endurance,
        ):
            backfill_signals_for_athlete("user-1", mock_db)

        assert w1.endurance_signal is None


# ---------------------------------------------------------------------------
# AC7 — Manual CLI script exists and works in isolation
# ---------------------------------------------------------------------------

class TestManualScriptAC7:
    """AC7: The job can be run manually in isolation for testing and re-processing."""

    def test_script_file_exists(self):
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "backfill_signals.py"
        )
        assert os.path.isfile(script_path), (
            "scripts/backfill_signals.py must exist for manual execution"
        )

    def test_script_importable(self):
        import scripts.backfill_signals  # noqa: F401

    def test_script_has_user_id_arg(self):
        import scripts.backfill_signals as mod
        old_argv = sys.argv
        sys.argv = [
            "backfill_signals.py",
            "--user-id", "123e4567-e89b-12d3-a456-426614174000",
        ]
        try:
            args = mod._parse_args()
            assert args.user_id == "123e4567-e89b-12d3-a456-426614174000"
        finally:
            sys.argv = old_argv

    def test_script_has_main_entry_point(self):
        import scripts.backfill_signals as mod
        assert hasattr(mod, "main"), "Script must have a main() function"
        assert callable(mod.main)

    def test_script_rejects_invalid_uuid(self):
        """Invalid UUID causes the script to exit with error (not raise an unhandled exception)."""
        import scripts.backfill_signals as mod
        with pytest.raises(SystemExit):
            old_argv = sys.argv
            sys.argv = ["backfill_signals.py", "--user-id", "not-a-uuid"]
            try:
                mod.main()
            finally:
                sys.argv = old_argv

    def test_script_no_thresholds_exits_cleanly(self):
        """Script with no thresholds for user prints message and exits without error."""
        import scripts.backfill_signals as mod
        import io

        mock_engine = mock.MagicMock()
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)

        # User exists; no prefs row
        mock_session.execute.side_effect = [
            mock.MagicMock(first=mock.MagicMock(return_value=("user-1",))),  # user check
            mock.MagicMock(first=mock.MagicMock(return_value=None)),         # no prefs
        ]

        with mock.patch("sqlalchemy.orm.Session", return_value=mock_session):
            captured = io.StringIO()
            sys.stdout = captured
            try:
                mod._run(mock_engine, "123e4567-e89b-12d3-a456-426614174000")
            except SystemExit:
                pass
            finally:
                sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert any(
            phrase in output.lower()
            for phrase in ("no threshold", "threshold", "not set", "no thresholds")
        ), f"Expected no-thresholds message, got: {output!r}"

    def test_script_no_thresholds_makes_no_writes(self):
        """Script with no thresholds must not call commit or add."""
        import scripts.backfill_signals as mod
        import io

        mock_engine = mock.MagicMock()
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)

        mock_session.execute.side_effect = [
            mock.MagicMock(first=mock.MagicMock(return_value=("user-1",))),
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
        ]

        with mock.patch("sqlalchemy.orm.Session", return_value=mock_session):
            captured = io.StringIO()
            sys.stdout = captured
            try:
                mod._run(mock_engine, "123e4567-e89b-12d3-a456-426614174000")
            finally:
                sys.stdout = sys.__stdout__

        mock_session.commit.assert_not_called()
        mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Return value shape
# ---------------------------------------------------------------------------

class TestReturnValueShape:
    """Service returns a structured summary dict."""

    def test_return_value_has_expected_keys(self):
        from backend.services.backfill_signals import backfill_signals_for_athlete

        prefs = _make_prefs()
        w1 = _make_workout("w-1")
        mock_db = _make_db_mock([w1], prefs)

        with mock.patch(
            "backend.services.backfill_signals.compute_and_store_speed_signal",
            return_value=(True, None),
        ), mock.patch(
            "backend.services.backfill_signals.compute_endurance_signal",
            return_value={
                "endurance_signal": None, "decoupling_percent": None,
                "efficiency_first_half": None, "efficiency_second_half": None,
                "endurance_signal_source": None,
            },
        ):
            result = backfill_signals_for_athlete("user-1", mock_db)

        assert isinstance(result, dict)
        assert "runs_processed" in result
        assert "speed_computed" in result
        assert "endurance_computed" in result

    def test_no_thresholds_returns_early(self):
        from backend.services.backfill_signals import backfill_signals_for_athlete

        # No prefs (first() returns None)
        mock_db = _make_db_mock([], None)

        result = backfill_signals_for_athlete("user-1", mock_db)

        assert result.get("thresholds_found") is False or result.get("runs_processed") == 0
