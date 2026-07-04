"""Tests for issue #1189: De-duplicate intensity rolling-window aggregation and fix N+1 query.

Acceptance Criteria:
  AC1 - A shared helper encapsulates the duration-weighted rolling-window aggregation
  AC2 - Both get_intensity_distribution and get_polarized_check call the shared helper
  AC3 - WorkoutSplit records are eager-loaded (selectinload) in both endpoints
  AC4 - intensity-distribution returns numerically identical results after refactor
  AC5 - polarized-check returns numerically identical results after refactor
  AC6 - SQL query count does not scale with number of workouts (N+1 eliminated)
"""
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).parent.parent
MAIN_PY = ROOT / "backend" / "main.py"

# ---------------------------------------------------------------------------
# Helpers: extract function body from main.py source
# ---------------------------------------------------------------------------

def _read_main():
    return MAIN_PY.read_text()


def _extract_function_body(src: str, func_name: str) -> str:
    """Return the source text of a function definition (up to the next top-level def/class)."""
    pattern = rf"def {re.escape(func_name)}\b.*?(?=\n(?:@|\ndef |\nclass )|\Z)"
    m = re.search(pattern, src, re.DOTALL)
    assert m, f"Could not locate function '{func_name}' in main.py"
    return m.group(0)


# ---------------------------------------------------------------------------
# AC1 — shared helper function exists
# ---------------------------------------------------------------------------

class TestSharedHelperExists:

    def test_helper_function_defined(self):
        """AC1: _accumulate_intensity_window is defined in main.py."""
        src = _read_main()
        assert re.search(r"def _accumulate_intensity_window\b", src), (
            "main.py must define _accumulate_intensity_window"
        )

    def test_helper_computes_rolling_window(self):
        """AC1: The helper contains the rolling_window accumulation logic."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "total_dur" in body, "helper must accumulate total_dur"
        assert "total_low" in body, "helper must accumulate total_low"
        assert "rolling_window" in body, "helper must produce rolling_window output"

    def test_helper_returns_sessions_list(self):
        """AC1: The helper builds and returns the per-session data list."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "sessions_out" in body or "sessions" in body.lower(), (
            "helper must build the per-session output list"
        )

    def test_helper_handles_zero_duration(self):
        """AC1: Helper handles the case of no classifiable band data (returns None pcts)."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "total_dur == 0" in body or '"low_pct": None' in body, (
            "helper must guard against division-by-zero when no band data exists"
        )


# ---------------------------------------------------------------------------
# AC2 — both endpoints call the shared helper (no inline duplicated loop)
# ---------------------------------------------------------------------------

class TestEndpointsUseHelper:

    def test_intensity_distribution_calls_helper(self):
        """AC2: get_intensity_distribution calls _accumulate_intensity_window."""
        src = _read_main()
        body = _extract_function_body(src, "get_intensity_distribution")
        assert "_accumulate_intensity_window" in body, (
            "get_intensity_distribution must delegate to _accumulate_intensity_window"
        )

    def test_polarized_check_calls_helper(self):
        """AC2: get_polarized_check calls _accumulate_intensity_window."""
        src = _read_main()
        body = _extract_function_body(src, "get_polarized_check")
        assert "_accumulate_intensity_window" in body, (
            "get_polarized_check must delegate to _accumulate_intensity_window"
        )

    def test_intensity_distribution_has_no_inline_split_query(self):
        """AC2: get_intensity_distribution does not contain an inline WorkoutSplit query."""
        src = _read_main()
        body = _extract_function_body(src, "get_intensity_distribution")
        assert "query(WorkoutSplit)" not in body, (
            "get_intensity_distribution must not issue a WorkoutSplit query inline"
        )

    def test_polarized_check_has_no_inline_split_query(self):
        """AC2: get_polarized_check does not contain an inline WorkoutSplit query."""
        src = _read_main()
        body = _extract_function_body(src, "get_polarized_check")
        assert "query(WorkoutSplit)" not in body, (
            "get_polarized_check must not issue a WorkoutSplit query inline"
        )

    def test_helper_aggregation_loop_appears_once(self):
        """AC2: The total_low/total_mod/total_high accumulation appears only in the helper."""
        src = _read_main()
        # Count occurrences of the accumulation variable pattern outside the helper
        all_occurrences = len(re.findall(r"total_low\s*\+?=", src))
        helper_body = _extract_function_body(src, "_accumulate_intensity_window")
        helper_occurrences = len(re.findall(r"total_low\s*\+?=", helper_body))
        assert all_occurrences == helper_occurrences, (
            f"total_low accumulation appears {all_occurrences} times in main.py "
            f"but only {helper_occurrences} times in the helper — "
            "the loop was not fully deduplicated"
        )


# ---------------------------------------------------------------------------
# AC3 — WorkoutSplit records are eager-loaded via selectinload
# ---------------------------------------------------------------------------

class TestEagerLoading:

    def test_selectinload_available_in_main(self):
        """AC3: selectinload is imported/used in main.py."""
        src = _read_main()
        assert "selectinload" in src, (
            "main.py must use selectinload from sqlalchemy.orm"
        )

    def test_intensity_distribution_uses_selectinload(self):
        """AC3: get_intensity_distribution passes selectinload(Workout.splits) to the query."""
        src = _read_main()
        body = _extract_function_body(src, "get_intensity_distribution")
        assert "selectinload" in body, (
            "get_intensity_distribution must eager-load splits via selectinload"
        )

    def test_polarized_check_uses_selectinload(self):
        """AC3: get_polarized_check passes selectinload(Workout.splits) to the query."""
        src = _read_main()
        body = _extract_function_body(src, "get_polarized_check")
        assert "selectinload" in body, (
            "get_polarized_check must eager-load splits via selectinload"
        )

    def test_helper_uses_relationship_attribute_not_query(self):
        """AC6/AC3: The shared helper uses w.splits (relationship attr), not session.query."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "session.query(WorkoutSplit)" not in body, (
            "helper must not issue a per-workout DB query for splits"
        )
        assert ".splits" in body, (
            "helper must access splits via the pre-loaded relationship attribute"
        )


# ---------------------------------------------------------------------------
# AC4/AC5 — numerical identity: helper math produces the same results
# ---------------------------------------------------------------------------

class TestHelperMathCorrectness:
    """Verify the rolling-window weighted-average formula is preserved in the helper."""

    def test_helper_uses_duration_weighted_average(self):
        """AC4/AC5: helper computes duration-weighted average (dur * zone_pct)."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        # The weighted accumulation must multiply duration by zone percentage
        assert re.search(r"dur\s*\*\s*zones\[.low_pct.\]", body) or \
               re.search(r"total_low\s*\+=\s*dur\s*\*", body), (
            "helper must use duration-weighted sum: total_low += dur * zones['low_pct']"
        )

    def test_helper_rounds_to_two_decimal_places(self):
        """AC4/AC5: helper rounds output percentages to 2 decimal places (matches original)."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "round(" in body, (
            "helper must round rolling_window percentages to match original rounding"
        )
        # Check for round(..., 2) pattern
        assert re.search(r"round\(.*,\s*2\)", body), (
            "helper must round to 2 decimal places"
        )

    def test_rolling_window_formula_unchanged(self):
        """AC4/AC5: The formula total_zone/total_dur is preserved in the helper."""
        src = _read_main()
        body = _extract_function_body(src, "_accumulate_intensity_window")
        assert "total_dur" in body, "helper must divide by total_dur"
        assert "total_low" in body and "total_mod" in body and "total_high" in body, (
            "helper must accumulate all three intensity bands"
        )


# ---------------------------------------------------------------------------
# AC6 — query count: no per-workout query (structural verification)
# ---------------------------------------------------------------------------

class TestQueryCountConstant:

    def test_no_per_workout_split_query_in_either_endpoint(self):
        """AC6: Neither endpoint issues a per-workout WorkoutSplit query inside a loop."""
        src = _read_main()
        for func_name in ("get_intensity_distribution", "get_polarized_check"):
            body = _extract_function_body(src, func_name)
            assert "for w in workouts" not in body or "query(WorkoutSplit)" not in body, (
                f"{func_name} must not query WorkoutSplit inside the per-workout loop"
            )

    def test_workout_query_uses_options(self):
        """AC6: The Workout query in both endpoints uses .options() for eager loading."""
        src = _read_main()
        for func_name in ("get_intensity_distribution", "get_polarized_check"):
            body = _extract_function_body(src, func_name)
            assert ".options(" in body, (
                f"{func_name} must use .options(selectinload(...)) on the Workout query"
            )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

class TestSmoke:

    def test_main_py_compiles(self):
        """Smoke: backend/main.py passes py_compile after the refactor."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(MAIN_PY)],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"py_compile failed on backend/main.py:\n{result.stderr.decode()}"
        )
