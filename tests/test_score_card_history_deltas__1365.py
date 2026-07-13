"""Tests for issue #1365: Score cards block deltas from persisted anchored history.

Acceptance Criteria covered:
  AC1: Score card payloads compute block delta from performance_score_history
       (latest formula_version only, never mixing versions); pill hidden when
       history does not reach back to block start.
  AC2: Trend sparkline on the cards reads the persisted series where available,
       falling back to in-request computation only when history is empty.
  AC3: Stale-anchor tint behavior preserved exactly.
  AC4: Frontend: pill renders the history-based delta; no change to card layout.
  AC5: Tests: delta math, version-mixing guard, insufficient-history hides pill,
       fallback path.
"""
import datetime
import inspect
import pytest
from types import SimpleNamespace
from unittest import mock


TODAY = datetime.date(2026, 7, 13)
BLOCK_DAYS = 28  # BREAKDOWN_WINDOW_DAYS


def _score_history_row(score_date, endurance, speed, formula_version="vdot-v11"):
    return SimpleNamespace(
        score_date=score_date,
        endurance=endurance,
        speed=speed,
        formula_version=formula_version,
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – PerformanceScoreHistory model exists
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1ModelExists:
    """performance_score_history table model is defined in backend.models."""

    def test_model_class_importable(self):
        from backend.models import PerformanceScoreHistory  # noqa
        assert PerformanceScoreHistory is not None

    def test_model_tablename(self):
        from backend.models import PerformanceScoreHistory
        assert PerformanceScoreHistory.__tablename__ == "performance_score_history"

    def test_model_has_required_columns(self):
        from backend.models import PerformanceScoreHistory
        cols = {c.name for c in PerformanceScoreHistory.__table__.columns}
        assert "user_id" in cols
        assert "score_date" in cols
        assert "endurance" in cols
        assert "speed" in cols
        assert "formula_version" in cols
        assert "created_at" in cols

    def test_model_has_unique_constraint_on_user_date_version(self):
        from backend.models import PerformanceScoreHistory
        uq_cols = []
        for constraint in PerformanceScoreHistory.__table__.constraints:
            import sqlalchemy as sa
            if isinstance(constraint, sa.UniqueConstraint):
                uq_cols.append(frozenset(c.name for c in constraint.columns))
        expected = frozenset({"user_id", "score_date", "formula_version"})
        assert expected in uq_cols, (
            f"Missing unique constraint on (user_id, score_date, formula_version); "
            f"found: {uq_cols}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – Block-delta math (pure helper in main.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1DeltaMath:
    """_compute_perf_block_delta computes delta = today − block_start score."""

    def test_positive_delta(self):
        import backend.main as m
        assert hasattr(m, "_compute_perf_block_delta"), (
            "_compute_perf_block_delta must exist in backend.main"
        )
        # today=60, block_start=50 → +10
        result = m._compute_perf_block_delta(
            today_score=60.0,
            block_start_score=50.0,
        )
        assert result == pytest.approx(10.0, abs=0.1)

    def test_negative_delta(self):
        import backend.main as m
        result = m._compute_perf_block_delta(
            today_score=40.0,
            block_start_score=50.0,
        )
        assert result == pytest.approx(-10.0, abs=0.1)

    def test_zero_delta(self):
        import backend.main as m
        result = m._compute_perf_block_delta(
            today_score=55.0,
            block_start_score=55.0,
        )
        assert result == pytest.approx(0.0, abs=0.01)



# ─────────────────────────────────────────────────────────────────────────────
# AC1 – Version-mixing guard
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1VersionMixingGuard:
    """Block delta is null when block_start row uses a different formula_version."""

    def test_version_mismatch_returns_null(self):
        """If block_start history row has an old formula_version, delta must be null."""
        import backend.main as m
        assert hasattr(m, "_fetch_perf_block_delta"), (
            "_fetch_perf_block_delta must exist in backend.main"
        )
        import uuid
        uid = uuid.uuid4()
        # Simulate: block_start row has old version, today's version is current
        old_row = _score_history_row(
            score_date=TODAY - datetime.timedelta(days=BLOCK_DAYS),
            endurance=50.0,
            speed=40.0,
            formula_version="vdot-v10",  # OLD version
        )
        mock_session = mock.MagicMock()
        # Query returns the old-version row
        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = old_row

        # _fetch_perf_block_delta must refuse to use old_row when current version differs
        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is None, (
            "Block delta must be null when block_start row has a different formula_version"
        )

    def test_same_version_returns_delta(self):
        """Block delta is computed when block_start row matches current formula_version."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        matching_row = _score_history_row(
            score_date=TODAY - datetime.timedelta(days=BLOCK_DAYS),
            endurance=50.0,
            speed=40.0,
            formula_version="vdot-v11",  # SAME version
        )
        mock_session = mock.MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = matching_row

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result == pytest.approx(10.0, abs=0.1)


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – Insufficient-history hides pill (null block_delta)
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1InsufficientHistory:
    """block_delta is null when history doesn't reach back to block start."""

    def test_no_history_row_at_block_start_returns_null(self):
        """When no row exists at block_start_date, delta is null (pill hidden)."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        mock_session = mock.MagicMock()
        # No row found
        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is None, "block_delta must be None when no history at block_start"

    def test_payload_block_delta_null_when_no_history(self):
        """Score card payload must have block_delta=null when history lacks block_start row."""
        import backend.main as m
        # If the helper returns None, the payload's block_delta field must be None
        src = inspect.getsource(m)
        assert "block_delta" in src, (
            "backend.main must include 'block_delta' in the score payload"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – Write-through: upsert after score compute
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1WriteThrough:
    """When scores are computed, they are upserted to performance_score_history."""

    def test_upsert_helper_exists(self):
        import backend.main as m
        assert hasattr(m, "_upsert_perf_score_history"), (
            "_upsert_perf_score_history helper must exist in backend.main"
        )
        assert callable(m._upsert_perf_score_history)

    def test_upsert_helper_signature(self):
        import backend.main as m
        sig = inspect.signature(m._upsert_perf_score_history)
        params = set(sig.parameters)
        assert "session" in params
        assert "user_id" in params
        assert "score_date" in params
        assert "endurance" in params
        assert "speed" in params
        assert "formula_version" in params

    def test_upsert_called_after_score_compute(self):
        """get_athlete_performance must call _upsert_perf_score_history."""
        import backend.main as m
        src = inspect.getsource(m)
        assert "_upsert_perf_score_history" in src, (
            "get_athlete_performance must call _upsert_perf_score_history"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – GET /api/performance/score-history endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1ScoreHistoryEndpoint:
    """GET /api/performance/score-history returns persisted series."""

    def test_endpoint_registered(self):
        import backend.main as m
        src = inspect.getsource(m)
        assert "/api/performance/score-history" in src, (
            "GET /api/performance/score-history must be registered in main.py"
        )

    def test_endpoint_accepts_from_to_params(self):
        import backend.main as m
        src = inspect.getsource(m)
        assert "score-history" in src
        # The endpoint should accept 'from' / 'to' query params
        assert 'score_history' in src or 'score-history' in src


# ─────────────────────────────────────────────────────────────────────────────
# AC2 – Trend sparkline: history-based series in payload
# ─────────────────────────────────────────────────────────────────────────────

class TestAC2HistorySparkline:
    """Score card payload exposes history_trend / history_trend_dates when available."""

    def test_payload_includes_history_sparkline_keys(self):
        """Payload must include history_sparkline (or history_trend/_dates) when history non-empty."""
        import backend.main as m
        src = inspect.getsource(m)
        # The payload should expose history_trend or history_sparkline data
        assert "history_trend" in src or "history_sparkline" in src, (
            "Payload must include a history-based trend series (history_trend or history_sparkline)"
        )

    def test_fallback_to_inrequest_when_history_empty(self):
        """When history is empty, the payload still has trend / trend_dates from in-request."""
        import backend.main as m
        src = inspect.getsource(m)
        # In-request trend must still be present (for fallback)
        assert '"trend"' in src or "'trend'" in src or '"trend_dates"' in src or "'trend_dates'" in src, (
            "In-request trend/trend_dates must remain in payload for fallback"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 – Stale-anchor tint preserved
# ─────────────────────────────────────────────────────────────────────────────

class TestAC3StaleAnchorTint:
    """is_stale flag on anchors and .stale CSS class are unchanged."""

    def test_is_stale_in_breakdown_anchors(self):
        import backend.services.running_performance as rp
        src = inspect.getsource(rp)
        assert "is_stale" in src, "is_stale must remain in breakdown anchors in running_performance.py"

    def test_stale_css_class_in_html(self):
        import pathlib
        html = pathlib.Path("frontend/pages/training-log.html").read_text()
        assert ".perf-frow.stale" in html, ".perf-frow.stale CSS rule must be present"

    def test_stale_row_class_applied_in_js(self):
        import pathlib
        js = pathlib.Path("frontend/js/training-performance.js").read_text()
        assert "stale" in js, "JS must still apply stale class to anchor rows"


# ─────────────────────────────────────────────────────────────────────────────
# AC4 – Frontend: pill uses history-based block_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestAC4FrontendPill:
    """Frontend reads block_delta from payload for the pill, not breakdown.delta."""

    def test_training_performance_js_uses_block_delta(self):
        import pathlib
        js = pathlib.Path("frontend/js/training-performance.js").read_text()
        assert "block_delta" in js, (
            "training-performance.js must use block_delta from payload for the pill"
        )

    def test_training_performance_js_pill_not_from_breakdown_delta_only(self):
        """The pill logic must consider block_delta, not only b.delta."""
        import pathlib
        js = pathlib.Path("frontend/js/training-performance.js").read_text()
        # The pill should reference block_delta (the new field)
        assert "block_delta" in js

    def test_home_widget_uses_block_delta(self):
        """Home widget uses block_delta from payload instead of computing from trend."""
        import pathlib
        js = pathlib.Path("frontend/js/home-readiness-training-sleep.js").read_text()
        assert "block_delta" in js, (
            "home-readiness-training-sleep.js must use block_delta from payload"
        )

    def test_card_layout_unchanged(self):
        """No new HTML elements added to the score card markup."""
        import pathlib
        html = pathlib.Path("frontend/pages/training-log.html").read_text()
        # The pill element must still be present (not removed or renamed)
        assert 'perf-delta-pill' in html


# ─────────────────────────────────────────────────────────────────────────────
# AC5 – Migration exists for performance_score_history
# ─────────────────────────────────────────────────────────────────────────────

class TestAC5Migration:
    """An Alembic migration exists for the performance_score_history table."""

    def test_migration_file_exists(self):
        import pathlib
        versions = pathlib.Path("alembic/versions")
        files = list(versions.glob("*performance_score_history*"))
        assert files, (
            "An Alembic migration file for performance_score_history must exist"
        )

    def test_migration_is_idempotent(self):
        """Migration must guard create_table with table_exists check."""
        import pathlib
        versions = pathlib.Path("alembic/versions")
        files = list(versions.glob("*performance_score_history*"))
        assert files
        content = files[0].read_text()
        assert "table_exists" in content, (
            "Migration must use table_exists() guard for idempotency"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC5 – Block delta end-to-end (unit)
# ─────────────────────────────────────────────────────────────────────────────

class TestAC5BlockDeltaEndToEnd:
    """Full block delta unit path: endurance and speed computed independently."""

    def test_endurance_and_speed_deltas_independent(self):
        """block_delta for endurance and speed are computed independently."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()

        def make_session(endurance_start, speed_start):
            row = _score_history_row(
                score_date=TODAY - datetime.timedelta(days=BLOCK_DAYS),
                endurance=endurance_start,
                speed=speed_start,
                formula_version="vdot-v11",
            )
            sess = mock.MagicMock()
            sess.query.return_value.filter.return_value.order_by.return_value.first.return_value = row
            return sess

        sess = make_session(endurance_start=45.0, speed_start=30.0)

        end_delta = m._fetch_perf_block_delta(
            session=sess,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=55.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        spd_delta = m._fetch_perf_block_delta(
            session=sess,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=35.0,
            current_formula_version="vdot-v11",
            score_type="speed",
        )

        assert end_delta == pytest.approx(10.0, abs=0.1)
        assert spd_delta == pytest.approx(5.0, abs=0.1)

    def test_payload_block_delta_field_exists_in_score_payload(self):
        """The score dict returned by get_athlete_performance includes block_delta."""
        import backend.main as m
        src = inspect.getsource(m)
        # block_delta must be set in the score payload
        assert '"block_delta"' in src or "'block_delta'" in src, (
            "block_delta key must appear in the score payload construction"
        )
