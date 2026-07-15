"""Tests for issue #1431: _fetch_perf_block_delta uses nearest row <= block_start.

Issue: _fetch_perf_block_delta filtered score_date == block_start (exact match).
Score history rows are written only when the user opens the performance tab, so
there is frequently no row exactly at block_start even when adequate history exists.
The pill was therefore hidden even though history spanned the whole block.

Fix: query score_date <= block_start ORDER BY score_date DESC — nearest row on or
before block_start (same formula_version), so the pill appears whenever history
reaches back far enough.

Acceptance Criteria (from issue #1431 body):
  AC1: When no row exists exactly at block_start but a row exists at block_start-1d
       (or earlier within the block), _fetch_perf_block_delta returns the delta
       (not None). Pill is visible.
  AC2: When the nearest row at or before block_start has a DIFFERENT formula_version,
       the function still returns None (version-mixing guard preserved).
  AC3: When a row exists exactly at block_start, behavior is unchanged (delta returned).
  AC4: Rows whose score_date is AFTER block_start are never used.
  AC5: Among multiple rows with score_date <= block_start, the one with the
       highest (most recent) score_date is chosen.
"""
import datetime
import pytest
from types import SimpleNamespace
from unittest import mock


TODAY = datetime.date(2026, 7, 13)
BLOCK_DAYS = 28  # BREAKDOWN_WINDOW_DAYS
BLOCK_START = TODAY - datetime.timedelta(days=BLOCK_DAYS)  # 2026-06-15


def _score_history_row(score_date, endurance=50.0, speed=40.0, formula_version="vdot-v11"):
    return SimpleNamespace(
        score_date=score_date,
        endurance=endurance,
        speed=speed,
        formula_version=formula_version,
    )


def _make_mock_session(row):
    """Return a mock SQLAlchemy session whose .query().filter().order_by().first() returns `row`."""
    mock_session = mock.MagicMock()
    mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = row
    return mock_session


# ─────────────────────────────────────────────────────────────────────────────
# AC1 – Nearest row before block_start is used instead of returning None
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1NearestRowUsed:
    """Pill is visible when history has a row at block_start-1d (no exact match)."""

    def test_row_one_day_before_block_start_returns_delta(self):
        """If only row is block_start-1d, delta must be returned (not None)."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        # Row at block_start - 1 day — no exact match at block_start
        row = _score_history_row(score_date=BLOCK_START - datetime.timedelta(days=1), endurance=50.0)
        mock_session = _make_mock_session(row)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is not None, (
            "block_delta must NOT be None when a history row exists at block_start-1d; "
            "pill should be visible"
        )
        assert result == pytest.approx(10.0, abs=0.01)

    def test_row_several_days_before_block_start_returns_delta(self):
        """If only row is block_start-7d, delta must be returned."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        row = _score_history_row(score_date=BLOCK_START - datetime.timedelta(days=7), endurance=45.0)
        mock_session = _make_mock_session(row)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is not None
        assert result == pytest.approx(15.0, abs=0.01)

    def test_no_row_at_all_still_returns_none(self):
        """When absolutely no history row exists, delta is still None (pill hidden)."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        mock_session = _make_mock_session(None)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is None, "block_delta must be None when no history row exists at all"


# ─────────────────────────────────────────────────────────────────────────────
# AC2 – Version-mixing guard preserved for nearest-row lookup
# ─────────────────────────────────────────────────────────────────────────────

class TestAC2VersionGuardPreserved:
    """Version-mixing guard still applies with <= lookup."""

    def test_nearest_row_with_old_formula_version_returns_none(self):
        """Nearest row before block_start with wrong formula_version → delta None."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        old_row = _score_history_row(
            score_date=BLOCK_START - datetime.timedelta(days=2),
            endurance=50.0,
            formula_version="vdot-v10",  # old version
        )
        mock_session = _make_mock_session(old_row)

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
            "Version-mixing guard must still apply: nearest row with old formula_version "
            "must produce None"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 – Exact match at block_start still works
# ─────────────────────────────────────────────────────────────────────────────

class TestAC3ExactMatchStillWorks:
    """Existing behavior: a row exactly at block_start still returns the delta."""

    def test_exact_match_at_block_start_returns_delta(self):
        """Row exactly at block_start continues to produce a valid delta."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        row = _score_history_row(score_date=BLOCK_START, endurance=50.0)
        mock_session = _make_mock_session(row)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=65.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result == pytest.approx(15.0, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# AC4 – Rows AFTER block_start are never used
# ─────────────────────────────────────────────────────────────────────────────

class TestAC4NoFutureRows:
    """The query must use score_date <= block_start, not score_date < today."""

    def test_query_uses_lte_filter_on_block_start(self):
        """The DB query must filter score_date <= block_start (not == and not >= today)."""
        import backend.main as m
        import inspect
        src = inspect.getsource(m._fetch_perf_block_delta)
        # The fix replaces == with <= in the score_date filter
        assert "<=" in src, (
            "_fetch_perf_block_delta must use score_date <= block_start (not ==)"
        )
        assert "score_date ==" not in src, (
            "_fetch_perf_block_delta must not use exact score_date == block_start equality"
        )

    def test_row_after_block_start_is_not_used(self):
        """A row at block_start+1d must NOT be used (simulated by query returning None)."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        # The fixed query excludes future rows — simulate by returning None
        mock_session = _make_mock_session(None)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# AC5 – Most recent row at or before block_start is selected
# ─────────────────────────────────────────────────────────────────────────────

class TestAC5MostRecentRowChosen:
    """Among multiple rows <= block_start, the one closest to block_start is used."""

    def test_closer_row_wins_over_older_row(self):
        """Simulates the query already returning the closest row (ORDER BY score_date DESC)."""
        import backend.main as m
        import uuid
        uid = uuid.uuid4()
        # Closest row (block_start-1d) returned by query — endurance=52
        closest_row = _score_history_row(
            score_date=BLOCK_START - datetime.timedelta(days=1),
            endurance=52.0,
        )
        mock_session = _make_mock_session(closest_row)

        result = m._fetch_perf_block_delta(
            session=mock_session,
            user_id=uid,
            today=TODAY,
            window_days=BLOCK_DAYS,
            current_score=60.0,
            current_formula_version="vdot-v11",
            score_type="endurance",
        )
        # 60.0 - 52.0 = 8.0
        assert result == pytest.approx(8.0, abs=0.01), (
            "Must use the closest row (highest score_date <= block_start)"
        )

    def test_query_orders_by_score_date_desc(self):
        """Source must sort by score_date DESC to pick the nearest row."""
        import backend.main as m
        import inspect
        src = inspect.getsource(m._fetch_perf_block_delta)
        assert "score_date" in src
        assert "desc" in src.lower(), (
            "_fetch_perf_block_delta must ORDER BY score_date DESC to pick nearest row"
        )
