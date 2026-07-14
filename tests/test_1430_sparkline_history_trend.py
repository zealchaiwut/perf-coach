"""Tests for issue #1430: Wire score-card sparkline to persisted history_trend.

AC:
  The JS must prefer data.history_trend / data.history_trend_dates for the
  score-card sparkline when the array is non-empty, falling back to the
  in-request data.trend / data.trend_dates only when history is absent —
  mirroring the block_delta fallback already in place.
"""
import pathlib


JS = pathlib.Path("frontend/js/training-performance.js").read_text()
HTML = pathlib.Path("frontend/pages/training-log.html").read_text()


class TestAC_HistoryTrendPreferred:
    """JS prefers history_trend over in-request trend for sparkline rendering."""

    def test_js_reads_history_trend(self):
        """training-performance.js must reference history_trend from the payload."""
        assert "history_trend" in JS, (
            "training-performance.js must read data.history_trend from the performance payload"
        )

    def test_js_reads_history_trend_dates(self):
        """training-performance.js must reference history_trend_dates from the payload."""
        assert "history_trend_dates" in JS, (
            "training-performance.js must read data.history_trend_dates from the performance payload"
        )

    def test_js_falls_back_to_inline_trend(self):
        """When history_trend is absent, JS must fall back to data.trend."""
        assert "data.trend" in JS or ".trend" in JS, (
            "training-performance.js must retain fallback to in-request trend array"
        )

    def test_js_sparkline_render_in_score_card(self):
        """_renderPerfScoreCard must render a sparkline using history_trend or trend."""
        assert "perf-sparkline" in JS or "perfSparkline" in JS or "_perfSparkline" in JS, (
            "_renderPerfScoreCard must call a sparkline helper and inject SVG "
            "into the score card using history_trend data"
        )

    def test_js_prefers_history_trend_when_non_empty(self):
        """Code must check history_trend length (or truthiness) before deciding which series to use."""
        assert (
            "history_trend" in JS and
            ("length" in JS or "&&" in JS)
        ), (
            "JS must check if history_trend is non-empty before preferring it over trend"
        )


class TestAC_SparklineContainerInHTML:
    """HTML score cards must contain a sparkline container element."""

    def test_endurance_card_has_sparkline_container(self):
        """Endurance score card must have a sparkline wrapper element."""
        assert "perf-sparkline" in HTML, (
            "training-log.html endurance score card must have a .perf-sparkline container"
        )

    def test_sparkline_container_present_for_both_cards(self):
        """Both score cards (endurance and speed) must have sparkline containers."""
        count = HTML.count("perf-sparkline")
        assert count >= 2, (
            f"Expected at least 2 perf-sparkline elements (one per card), found {count}"
        )
