"""Tests for issue #1413: Narrow broad except in ramp computation (backend unit tests)

This test verifies that the except handler in _resolve_week_phase_from_db
catches only ValueError (expected data-absent conditions) and lets other
exceptions propagate, avoiding silent swallowing of real bugs.
"""
import logging
import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from backend.services.fuel import _resolve_week_phase_from_db


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session."""
    return Mock()


@pytest.fixture
def test_date():
    """Use a fixed test date (Saturday, not in taper, no race within 7 days)."""
    # June 15, 2024 is a Saturday
    return date(2024, 6, 15)


@pytest.fixture
def user_id():
    return 123


def _setup_race_and_plan_mocks(mock_db, test_date):
    """Setup mocks so the try-except block is entered (a_race exists, not in taper, no race within 7 days)."""
    # Mock race within 7 days: None (so race_within_7d = False)
    race_7d_query = Mock()
    race_7d_query.filter.return_value.first.return_value = None

    # Mock A-race (needed to enter try-except block): exists and is far away
    a_race = Mock()
    a_race.race_date = test_date + timedelta(days=30)  # 30 days away, not in taper or within 7 days
    a_race_query = Mock()
    a_race_query.filter.return_value.order_by.return_value.first.return_value = a_race

    # Mock training plan
    plan = Mock()
    plan.taper_length = 3.0
    plan.ramp_rate = 0.05
    plan.hold_weeks = 4
    plan_query = Mock()
    plan_query.filter.return_value.first.return_value = plan

    # Setup mock_db.query to return the right query object based on arguments
    def query_side_effect(model):
        if hasattr(model, '__name__'):
            model_name = model.__name__
        else:
            model_name = str(model)

        if 'Race' in str(model_name):
            # Return a_race_query for first Race query (race within 7 days)
            # and return a_race_query for second Race query (A-race)
            # We'll handle this via sequential returns
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                return race_7d_query
            else:
                return a_race_query
        elif 'TrainingPlan' in str(model_name):
            return plan_query
        return Mock()

    mock_db.query.side_effect = query_side_effect
    return plan, a_race


class TestRampComputationExceptionHandling:
    """Test that only ValueError is caught in ramp computation; other exceptions propagate."""

    def test_value_error_caught_and_logged(self, mock_db, test_date, user_id, caplog):
        """AC: ValueError in ramp computation is caught; debug log emitted; phase falls back to base."""
        plan, a_race = _setup_race_and_plan_mocks(mock_db, test_date)

        # Patch daily_tss_series to raise ValueError (simulates missing training data)
        with patch('backend.services.fuel.daily_tss_series', side_effect=ValueError("No TSS data for date range")):
            with caplog.at_level(logging.DEBUG, logger='backend.services.fuel'):
                phase, reason, trailing_avg = _resolve_week_phase_from_db(user_id, test_date, mock_db)

        # Phase should fall back to "base" when ramp is skipped
        assert phase == "base"
        # Debug log should contain the skip message
        assert any("ramp computation skipped" in record.message for record in caplog.records)
        # trailing_28d_weekly_avg should be None (not computed due to ValueError)
        assert trailing_avg is None

    def test_runtime_error_propagates(self, mock_db, test_date, user_id):
        """AC: RuntimeError in ramp computation is NOT caught; it propagates to caller."""
        plan, a_race = _setup_race_and_plan_mocks(mock_db, test_date)

        # Patch daily_tss_series to raise RuntimeError (a real bug, not data-absence)
        with patch('backend.services.fuel.daily_tss_series', side_effect=RuntimeError("Database connection failed")):
            # RuntimeError should propagate, not be caught
            with pytest.raises(RuntimeError, match="Database connection failed"):
                _resolve_week_phase_from_db(user_id, test_date, mock_db)

    def test_attribute_error_propagates(self, mock_db, test_date, user_id):
        """AC: AttributeError in ramp computation is NOT caught; it propagates."""
        plan, a_race = _setup_race_and_plan_mocks(mock_db, test_date)

        # Patch daily_tss_series to raise AttributeError (a bug in the computation logic)
        with patch('backend.services.fuel.daily_tss_series', side_effect=AttributeError("'NoneType' object has no attribute 'tss'")):
            # AttributeError should propagate, not be caught
            with pytest.raises(AttributeError, match="'NoneType' object"):
                _resolve_week_phase_from_db(user_id, test_date, mock_db)

    def test_type_error_propagates(self, mock_db, test_date, user_id):
        """AC: TypeError in ramp computation is NOT caught; it propagates."""
        plan, a_race = _setup_race_and_plan_mocks(mock_db, test_date)

        # Patch daily_tss_series to raise TypeError (a computation bug)
        with patch('backend.services.fuel.daily_tss_series', side_effect=TypeError("unsupported operand type(s) for +: 'str' and 'int'")):
            # TypeError should propagate, not be caught
            with pytest.raises(TypeError, match="unsupported operand"):
                _resolve_week_phase_from_db(user_id, test_date, mock_db)

    def test_value_error_when_get_weekly_volume_raises(self, mock_db, test_date, user_id):
        """AC: ValueError from get_weekly_volume is caught; ramp computation is skipped."""
        plan, a_race = _setup_race_and_plan_mocks(mock_db, test_date)

        # Setup daily_tss_series to return valid data
        with patch('backend.services.fuel.daily_tss_series', return_value=[(test_date, 100.0)]):
            # Patch get_weekly_volume to raise ValueError
            with patch('backend.services.fuel.get_weekly_volume', side_effect=ValueError("No workouts in week")):
                with patch('backend.services.fuel._log.debug') as mock_log:
                    phase, reason, trailing_avg = _resolve_week_phase_from_db(user_id, test_date, mock_db)

            # Phase should fall back to "base"
            assert phase == "base"
            # Debug log should have been called
            mock_log.assert_called_once()
            assert "ramp computation skipped" in str(mock_log.call_args)
