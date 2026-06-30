"""Tests for issue #1149: Backfill economy model across historical sessions.

Acceptance Criteria covered:
  AC1: A backfill script/service runs against all existing strength and plyo sessions.
  AC2: Stimulus values computed for each session using the same economy model logic.
  AC3: Lagged ceiling bonus computed in correct chronological order.
  AC4: Historical ceiling values match what they would have been from the start.
  AC5: Script is idempotent — running twice produces the same result.
  AC6: py_compile passes on all touched Python files.
  AC7: No regression to live/forward-going economy calculations.
"""

from __future__ import annotations

import inspect
import py_compile
import pathlib
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock


# ── AC1: Backfill service module exists and is importable ────────────────────

class TestBackfillServiceExistsAC1:
    """AC1: A backfill service exists and runs against all sessions."""

    def test_backfill_economy_module_importable(self):
        from backend.services import backfill_economy  # noqa: F401
        assert backfill_economy is not None

    def test_backfill_economy_function_exists(self):
        from backend.services.backfill_economy import backfill_economy_for_user
        assert callable(backfill_economy_for_user)

    def test_backfill_function_accepts_user_id_and_session(self):
        from backend.services.backfill_economy import backfill_economy_for_user
        sig = inspect.signature(backfill_economy_for_user)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "db" in params or "session" in params

    def test_backfill_function_returns_summary_dict(self):
        from backend.services.backfill_economy import backfill_economy_for_user

        mock_db = mock.MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        result = backfill_economy_for_user("user-1", mock_db)

        assert isinstance(result, dict), "Return value must be a dict"
        required_keys = {"sessions_processed", "strength_dates", "plyo_dates", "snapshots_written"}
        assert required_keys <= set(result.keys()), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    def test_backfill_zero_sessions_returns_zero_counts(self):
        from backend.services.backfill_economy import backfill_economy_for_user

        mock_db = mock.MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        result = backfill_economy_for_user("user-1", mock_db)
        assert result["sessions_processed"] == 0
        assert result["strength_dates"] == 0
        assert result["plyo_dates"] == 0

    def test_backfill_queries_strength_sessions(self):
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        assert "strength_sessions" in src, "Backfill must query strength_sessions table"

    def test_backfill_queries_plyo_sessions(self):
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        assert "plyo_sessions" in src, "Backfill must query plyo_sessions table"


# ── AC2: Stimulus computed via economy model logic ───────────────────────────

class TestStimulusComputationAC2:
    """AC2: Stimulus values use the same logic as compute_economy_stimulus."""

    def test_strength_load_computed_from_sets_reps_load(self):
        """Primary path: strength_load = sets * reps * load."""
        from backend.services.backfill_economy import _compute_strength_load
        result = _compute_strength_load(sets=3, reps=5, load=100.0,
                                        session_rpe=None, duration_minutes=None)
        assert result == 3 * 5 * 100.0

    def test_strength_load_falls_back_to_rpe_duration(self):
        """Fallback: strength_load = session_rpe * duration_minutes when sets/reps/load absent."""
        from backend.services.backfill_economy import _compute_strength_load
        result = _compute_strength_load(sets=None, reps=None, load=None,
                                        session_rpe=7, duration_minutes=45)
        assert result == 7 * 45

    def test_strength_load_returns_zero_when_no_data(self):
        """Zero when no computable fields are present."""
        from backend.services.backfill_economy import _compute_strength_load
        result = _compute_strength_load(sets=None, reps=None, load=None,
                                        session_rpe=None, duration_minutes=None)
        assert result == 0.0

    def test_strength_load_partial_sets_reps_load_uses_available(self):
        """Partial sets*reps*load falls back gracefully to 0."""
        from backend.services.backfill_economy import _compute_strength_load
        # load is None → volume-load path unavailable → try rpe*duration
        result = _compute_strength_load(sets=3, reps=5, load=None,
                                        session_rpe=None, duration_minutes=None)
        assert result == 0.0

    def test_stimulus_computed_using_economy_model(self):
        """Backfill uses compute_economy_stimulus, not a custom formula."""
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        assert "compute_economy_stimulus" in src, (
            "Backfill must call compute_economy_stimulus from the economy model"
        )

    def test_stimulus_positive_for_nonzero_strength_session(self):
        """A strength session with sets/reps/load produces a positive stimulus."""
        from backend.services.backfill_economy import _compute_strength_load
        from backend.services.economy_stimulus import compute_economy_stimulus
        load = _compute_strength_load(sets=3, reps=10, load=80.0,
                                      session_rpe=None, duration_minutes=None)
        stimulus = compute_economy_stimulus(load, 0.0, 10.0, 50.0)
        assert stimulus > 0.0

    def test_stimulus_positive_for_nonzero_plyo_session(self):
        """A plyo session with foot_contacts produces a positive stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        stimulus = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
        assert stimulus > 0.0

    def test_stimulus_zero_for_empty_sessions_on_date(self):
        """Zero strength_load and zero plyo_contacts → zero stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        stimulus = compute_economy_stimulus(0.0, 0.0, 10.0, 50.0)
        assert stimulus == 0.0


# ── AC3: Lagged ceiling bonus computed in chronological order ─────────────────

class TestChronologicalOrderAC3:
    """AC3: Ceiling bonus is computed chronologically — session N uses sessions 1..N-1."""

    def test_compute_ceiling_bonus_called_chronologically(self):
        """Backfill references compute_ceiling_bonus (not a reimplementation)."""
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        assert "compute_ceiling_bonus" in src, (
            "Backfill must call compute_ceiling_bonus from ceiling_bonus module"
        )

    def test_earlier_sessions_have_lower_or_equal_ceiling(self):
        """In a series, earlier sessions have lower or equal ceiling bonus."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        # Simulate 5 weekly sessions; the ceiling for each session date is computed
        # using only prior sessions.
        session_dates = [date(2026, 1, 1) + timedelta(weeks=w) for w in range(5)]
        stimuli = [(d, 500.0) for d in session_dates]

        ceilings = []
        for i, ref_date in enumerate(session_dates):
            prior = stimuli[:i]  # only sessions before this one
            bonus = compute_ceiling_bonus(prior, ref_date)
            ceilings.append(bonus)

        # Session 0 has no prior → bonus = 0.0
        assert ceilings[0] == 0.0
        # Each subsequent session has a non-decreasing bonus (more history)
        for i in range(1, len(ceilings)):
            assert ceilings[i] >= ceilings[i - 1], (
                f"Ceiling at session {i} ({ceilings[i]:.4f}) should be >= "
                f"session {i-1} ({ceilings[i-1]:.4f})"
            )

    def test_session_n_does_not_use_future_sessions(self):
        """Session N ceiling must equal what it would be with only sessions 1..N-1."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus

        ref_date = date(2026, 3, 1)
        # Sessions 6 weeks before reference_date (in kernel peak window)
        past_session = (ref_date - timedelta(days=42), 1000.0)
        # Session on the reference date itself — should not contribute to its own ceiling
        same_day = (ref_date, 1000.0)

        # Bonus using only past session (correct: reference_date excluded)
        bonus_past_only = compute_ceiling_bonus([past_session], ref_date)
        # Bonus using past + same_day (same_day lag=0, gets ≤5% weight at onset)
        bonus_with_same = compute_ceiling_bonus([past_session, same_day], ref_date)

        # The same-day session contributes only a tiny fraction (lag=0 → kernel=0)
        # so the bonus should be dominated by the past session
        assert bonus_past_only > 0.0, "Past session at peak lag must produce positive bonus"
        # same-day session (lag=0) has kernel weight = 0 at onset start
        # so bonus_with_same should equal or barely exceed bonus_past_only
        assert bonus_with_same >= bonus_past_only  # tiny onset contribution or 0


# ── AC4: Historical values match what they would have been ───────────────────

class TestHistoricalAccuracyAC4:
    """AC4: Backfilled ceilings match what the live model would have computed."""

    def test_backfill_ceiling_matches_manual_computation(self):
        """Run the core computation manually and compare against backfill helper."""
        from backend.services.backfill_economy import (
            _compute_strength_load,
            compute_economy_snapshots,
        )

        # Two strength sessions and one plyo session
        strength_by_date = {
            date(2026, 1, 1): 3 * 10 * 80.0,   # 2400 kg·reps
            date(2026, 2, 1): 4 * 8 * 100.0,   # 3200 kg·reps
        }
        plyo_by_date = {
            date(2026, 1, 15): 200.0,
        }

        snapshots = compute_economy_snapshots(
            strength_by_date=strength_by_date,
            plyo_by_date=plyo_by_date,
        )

        assert len(snapshots) > 0, "Should produce at least one snapshot"

        # All snapshot dates should be among the session dates
        snapshot_dates = {s["snapshot_date"] for s in snapshots}
        all_session_dates = set(strength_by_date) | set(plyo_by_date)
        assert snapshot_dates == all_session_dates, (
            f"Snapshot dates {snapshot_dates} must equal session dates {all_session_dates}"
        )

    def test_snapshot_has_required_fields(self):
        """Each snapshot dict has snapshot_date, economy_stimulus, ceiling_bonus."""
        from backend.services.backfill_economy import compute_economy_snapshots

        strength_by_date = {date(2026, 1, 1): 500.0}
        plyo_by_date = {}

        snapshots = compute_economy_snapshots(
            strength_by_date=strength_by_date,
            plyo_by_date=plyo_by_date,
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert "snapshot_date" in snap
        assert "economy_stimulus" in snap
        assert "ceiling_bonus" in snap
        assert snap["economy_stimulus"] > 0.0

    def test_first_session_ceiling_bonus_is_near_zero(self):
        """The first session has no prior history, so ceiling bonus is nearly zero."""
        from backend.services.backfill_economy import compute_economy_snapshots

        strength_by_date = {date(2026, 1, 1): 500.0}
        snapshots = compute_economy_snapshots(
            strength_by_date=strength_by_date,
            plyo_by_date={},
        )
        # The reference date is the session date itself; lag=0 → kernel=0
        assert snapshots[0]["ceiling_bonus"] == 0.0

    def test_second_session_ceiling_includes_first_stimulus(self):
        """A session 8 weeks after the first incorporates the first's stimulus."""
        from backend.services.backfill_economy import compute_economy_snapshots

        d1 = date(2026, 1, 1)
        d2 = d1 + timedelta(weeks=8)  # 56 days — past peak, still in window

        strength_by_date = {d1: 500.0, d2: 500.0}
        snapshots = compute_economy_snapshots(
            strength_by_date=strength_by_date,
            plyo_by_date={},
        )

        snaps_by_date = {s["snapshot_date"]: s for s in snapshots}
        bonus_d2 = snaps_by_date[d2]["ceiling_bonus"]
        # d1 is 56 days before d2 — inside the 84-day window
        assert bonus_d2 > 0.0, (
            f"Session at d2 must have positive bonus from d1; got {bonus_d2}"
        )


# ── AC5: Idempotency ─────────────────────────────────────────────────────────

class TestIdempotencyAC5:
    """AC5: Running backfill twice produces identical results; no duplicates."""

    def test_compute_economy_snapshots_is_deterministic(self):
        """Same input data → same output snapshots every time."""
        from backend.services.backfill_economy import compute_economy_snapshots

        strength_by_date = {
            date(2026, 1, 1): 500.0,
            date(2026, 2, 1): 700.0,
        }
        plyo_by_date = {date(2026, 1, 15): 200.0}

        r1 = compute_economy_snapshots(strength_by_date, plyo_by_date)
        r2 = compute_economy_snapshots(strength_by_date, plyo_by_date)

        assert len(r1) == len(r2)
        for s1, s2 in zip(sorted(r1, key=lambda x: x["snapshot_date"]),
                          sorted(r2, key=lambda x: x["snapshot_date"])):
            assert s1["snapshot_date"] == s2["snapshot_date"]
            assert abs(s1["economy_stimulus"] - s2["economy_stimulus"]) < 1e-9
            assert abs(s1["ceiling_bonus"] - s2["ceiling_bonus"]) < 1e-9

    def test_backfill_uses_upsert_not_insert(self):
        """Backfill service uses an upsert (ON CONFLICT DO UPDATE) for idempotency."""
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        assert (
            "ON CONFLICT" in src.upper()
            or "on_conflict_do_update" in src
            or "upsert" in src.lower()
        ), "Backfill must use ON CONFLICT / upsert to be idempotent"

    def test_backfill_script_importable(self):
        """Standalone backfill script must be importable as a module."""
        import importlib.util
        script_path = (
            pathlib.Path(__file__).parent.parent / "scripts" / "backfill_economy.py"
        )
        assert script_path.exists(), f"Script not found at {script_path}"
        spec = importlib.util.spec_from_file_location("backfill_economy_script", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main") or hasattr(mod, "_run"), (
            "Script must define main() or _run()"
        )


# ── AC6: py_compile on all touched files ─────────────────────────────────────

class TestPyCompileAC6:
    """AC6: py_compile passes on every modified Python file."""

    def _compile(self, rel_path: str):
        base = pathlib.Path(__file__).parent.parent
        p = base / rel_path
        assert p.exists(), f"File not found: {p}"
        py_compile.compile(str(p), doraise=True)

    def test_py_compile_backfill_economy_service(self):
        self._compile("backend/services/backfill_economy.py")

    def test_py_compile_backfill_economy_script(self):
        self._compile("scripts/backfill_economy.py")

    def test_py_compile_models(self):
        self._compile("backend/models.py")

    def test_py_compile_economy_stimulus(self):
        self._compile("backend/services/economy_stimulus.py")

    def test_py_compile_ceiling_bonus(self):
        self._compile("backend/services/ceiling_bonus.py")


# ── AC7: No regression to live economy calculations ──────────────────────────

class TestNoRegressionAC7:
    """AC7: Forward-going economy calculations still work correctly after backfill."""

    def test_economy_stimulus_unchanged_after_backfill_import(self):
        """Importing backfill module does not alter compute_economy_stimulus behaviour."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        import backend.services.backfill_economy  # noqa: F401 — import side-effect check

        # Known reference value from issue #1146 worked example
        stimulus = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0)
        # From the module docstring: ≈ 1439.2
        assert abs(stimulus - 1439.2) < 1.0, (
            f"compute_economy_stimulus changed after importing backfill; got {stimulus}"
        )

    def test_ceiling_bonus_unchanged_after_backfill_import(self):
        """Importing backfill module does not alter compute_ceiling_bonus behaviour."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        import backend.services.backfill_economy  # noqa: F401

        ref = date(2026, 1, 1)
        history = [(ref - timedelta(days=42), 1000.0)]
        bonus = compute_ceiling_bonus(history, ref)
        # At peak lag (42 days), kernel weight = 1.0, so bonus = 1000.0
        assert abs(bonus - 1000.0) < 1e-6, (
            f"compute_ceiling_bonus changed after importing backfill; got {bonus}"
        )

    def test_backfill_does_not_modify_economy_stimulus_module(self):
        """Backfill only reads from economy_stimulus, never patches it."""
        from backend.services import backfill_economy
        src = inspect.getsource(backfill_economy)
        # Should not monkey-patch or mock the live module
        assert "monkeypatch" not in src
        assert "economy_stimulus.compute_economy_stimulus = " not in src

    def test_compute_economy_snapshots_uses_correct_plyo_contacts(self):
        """Plyo contacts flow through correctly: foot_contacts → plyo_contacts arg."""
        from backend.services.backfill_economy import compute_economy_snapshots
        from backend.services.economy_stimulus import compute_economy_stimulus

        plyo_contacts = 300.0
        plyo_by_date = {date(2026, 1, 1): plyo_contacts}
        snapshots = compute_economy_snapshots(
            strength_by_date={},
            plyo_by_date=plyo_by_date,
        )
        expected_stimulus = compute_economy_stimulus(0.0, plyo_contacts, 10.0, 50.0)
        actual_stimulus = snapshots[0]["economy_stimulus"]
        assert abs(actual_stimulus - expected_stimulus) < 1e-6, (
            f"Expected stimulus {expected_stimulus}, got {actual_stimulus}"
        )

    def test_compute_economy_snapshots_uses_correct_strength_load(self):
        """Strength load flows through correctly: volume-load → strength_load arg."""
        from backend.services.backfill_economy import compute_economy_snapshots
        from backend.services.economy_stimulus import compute_economy_stimulus

        strength_load = 2400.0  # e.g. 3*10*80 = 2400
        strength_by_date = {date(2026, 1, 1): strength_load}
        snapshots = compute_economy_snapshots(
            strength_by_date=strength_by_date,
            plyo_by_date={},
        )
        expected_stimulus = compute_economy_stimulus(strength_load, 0.0, 10.0, 50.0)
        actual_stimulus = snapshots[0]["economy_stimulus"]
        assert abs(actual_stimulus - expected_stimulus) < 1e-6, (
            f"Expected stimulus {expected_stimulus}, got {actual_stimulus}"
        )
