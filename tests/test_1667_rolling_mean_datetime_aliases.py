"""Tests for issue #1667: _rolling_mean reuses module-level datetime aliases.

Acceptance criterion: _rolling_mean must NOT contain a function-local
`import datetime` statement; instead it must use the module-level _date and
_timedelta aliases already imported at backend/main.py:14.
"""
import inspect

import pytest

from backend.main import _rolling_mean


def test_no_local_datetime_import():
    """AC: _rolling_mean must not contain a function-local `import datetime` statement."""
    src = inspect.getsource(_rolling_mean)
    assert "import datetime" not in src, (
        "_rolling_mean contains a function-local 'import datetime' statement; "
        "it should use the module-level _date / _timedelta aliases instead."
    )


def test_function_still_correct_after_refactor():
    """Sanity: after alias refactor the function returns the same correct results."""
    import datetime

    values = [
        (datetime.date(2026, 1, 1), 100.0),
        (datetime.date(2026, 1, 10), 110.0),
        (datetime.date(2026, 1, 28), 120.0),  # 27 days from first → still in window
        (datetime.date(2026, 3,  2), 200.0),  # 60 days from first → new cluster
    ]
    result = _rolling_mean(values)
    # First entry: only itself
    assert result[0] == pytest.approx(100.0, abs=0.01)
    # Second: (100 + 110) / 2
    assert result[1] == pytest.approx(105.0, abs=0.01)
    # Third: all three within 27-day span of first → (100 + 110 + 120) / 3
    assert result[2] == pytest.approx(110.0, abs=0.01)
    # Fourth: 60 days from first; only itself in 28-day window
    assert result[3] == pytest.approx(200.0, abs=0.01)


def test_string_dates_still_work_after_refactor():
    """Sanity: ISO-string run_date inputs continue to work after alias refactor."""
    values = [
        ("2026-06-01", 180.0),
        ("2026-06-10", 190.0),
    ]
    result = _rolling_mean(values)
    assert result[0] == pytest.approx(180.0, abs=0.01)
    assert result[1] == pytest.approx(185.0, abs=0.01)
