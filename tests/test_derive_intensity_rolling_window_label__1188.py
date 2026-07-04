"""Tests for issue #1188: Derive intensity rolling-window bar label from selected range.

Acceptance Criteria anchored:
  AC1 - Bar label is derived from selected range, not hardcoded '28-day avg'
  AC2 - Tooltip label is derived from selected range, not hardcoded '28-day rolling window'
  AC3 - When a non-28-day range is selected, labels reflect the actual day count
  AC4 - When exactly 28 days selected, labels read '28-day avg' / '28-day rolling window'
  AC5 - Day count computed from from/to params, not a static constant
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).parent.parent
TRENDS_JS = ROOT / "frontend" / "js" / "trends.js"


# ---------------------------------------------------------------------------
# AC1 — Bar label no longer hardcoded as '28-day avg'
# ---------------------------------------------------------------------------

class TestBarLabelNotHardcoded:

    def test_28_day_avg_not_hardcoded_as_string_literal(self):
        """AC1: '28-day avg' must not appear as a bare string literal in labels array."""
        src = TRENDS_JS.read_text()
        # The old code was: labels.push('28-day avg');
        # After fix it must be a dynamic expression, not a quoted '28'
        assert "'28-day avg'" not in src, (
            "trends.js must not hardcode '28-day avg' — derive label from the date range"
        )

    def test_bar_label_uses_dynamic_day_count(self):
        """AC1/AC5: trends.js builds the rolling-window label from a day count variable."""
        src = TRENDS_JS.read_text()
        # After the fix, the label push should reference a variable (dayCount, days, etc.)
        # and not be a bare string.  We expect something like:
        #   labels.push(dayCount + '-day avg');
        # or template literal: labels.push(`${dayCount}-day avg`)
        assert re.search(
            r"labels\.push\s*\(\s*(?:[a-zA-Z_]\w*\s*\+\s*['\"]|`\$\{)",
            src,
        ), "trends.js must push a dynamically-constructed rolling-window label"


# ---------------------------------------------------------------------------
# AC2 — Tooltip label no longer hardcoded as '28-day rolling window'
# ---------------------------------------------------------------------------

class TestTooltipLabelNotHardcoded:

    def test_28_day_rolling_window_not_hardcoded(self):
        """AC2: '28-day rolling window' must not appear as a bare string literal."""
        src = TRENDS_JS.read_text()
        assert "'28-day rolling window'" not in src, (
            "trends.js must not hardcode '28-day rolling window' — derive from date range"
        )

    def test_tooltip_title_callback_uses_dynamic_label(self):
        """AC2/AC5: The tooltip title callback references the same derived label."""
        src = TRENDS_JS.read_text()
        # The tooltip callback at sessionCount+1 must return a dynamic label, not '28'
        # Check that the tooltip section does NOT contain '28-day'
        assert "28-day rolling window" not in src, (
            "Tooltip title callback must not contain the literal '28-day rolling window'"
        )


# ---------------------------------------------------------------------------
# AC3 — Non-28-day ranges produce accurate labels
# ---------------------------------------------------------------------------

class TestDerivedDayCountPattern:

    def test_day_count_computed_via_date_arithmetic(self):
        """AC3/AC5: Day count is derived by arithmetic on from/to Date objects."""
        src = TRENDS_JS.read_text()
        # Look for date subtraction (milliseconds to days) or similar arithmetic
        # Common patterns:
        #   Math.round((...) / 86400000)
        #   / (1000 * 60 * 60 * 24)
        #   getTime() - getTime()
        #   parseInt(... / 86400)
        assert re.search(
            r"(?:86400000|1000\s*\*\s*60\s*\*\s*60\s*\*\s*24|getTime\(\)|\.getTime|dayCount)",
            src,
        ), (
            "trends.js must compute day count from the date range using date arithmetic"
        )

    def test_no_hardcoded_28_in_label_context(self):
        """AC3: No standalone '28' appears adjacent to 'avg' or 'rolling' in the source."""
        src = TRENDS_JS.read_text()
        assert not re.search(r"\b28\b.{0,20}(?:avg|rolling)", src), (
            "trends.js must not contain '28' near 'avg' or 'rolling' as a hardcoded label"
        )


# ---------------------------------------------------------------------------
# AC4 — 28-day default still produces correct labels (regression guard)
# ---------------------------------------------------------------------------

class TestDefaultCasePreserved:

    def test_day_count_suffix_pattern_present(self):
        """AC4: The '-day avg' and '-day rolling window' suffix patterns still exist."""
        src = TRENDS_JS.read_text()
        # The dynamic label concatenates with these suffixes
        assert "-day avg" in src, "'-day avg' suffix must still appear in trends.js"
        assert "-day rolling window" in src, (
            "'-day rolling window' suffix must still appear in trends.js"
        )


# ---------------------------------------------------------------------------
# AC5 — Day count derived from from/to params, not static constant
# ---------------------------------------------------------------------------

class TestDayCountDerivedFromParams:

    def test_renderIntensityChart_accepts_window_or_day_count(self):
        """AC5: renderIntensityChart signature or body references win/from/to/dayCount."""
        src = TRENDS_JS.read_text()
        # The function must accept or use date range information
        # Either via a third parameter, or via the win object computed upstream
        assert re.search(
            r"function\s+renderIntensityChart\s*\(\s*\w+\s*,\s*\w+\s*(?:,\s*\w+)?",
            src,
        ), (
            "renderIntensityChart should accept a third parameter (win, dayCount, etc.) "
            "for the date range"
        )

    def test_day_count_variable_defined_before_label_push(self):
        """AC5: A day-count variable is defined/assigned before building the labels."""
        src = TRENDS_JS.read_text()
        # Look for dayCount (or similar) being assigned before labels.push
        assert re.search(r"(?:dayCount|daysDiff|rangeSize|numDays)\s*=", src), (
            "trends.js must assign a day-count variable derived from the date range"
        )


# ---------------------------------------------------------------------------
# Syntax guard
# ---------------------------------------------------------------------------

class TestSyntax:

    def test_trends_js_no_syntax_error(self):
        """trends.js must still pass node --check after the change."""
        result = subprocess.run(
            ["node", "--check", str(TRENDS_JS)],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"node --check failed on trends.js:\n{result.stderr.decode()}"
        )
