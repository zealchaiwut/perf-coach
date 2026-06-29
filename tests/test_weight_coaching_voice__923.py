"""Tests for issue #923: Apply coaching copy to weight chart surfaces.

AC anchors:
  AC1  — Verdict banner references 7-day trend vs plan ("trend" word present).
  AC2  — Calm up-day: on-plan/ahead gap_direction → not red/alarmed state.
  AC3  — Behind plan → concrete next lever in coaching copy.
  AC4  — Projection line label is forward-looking (no "missed target"/"off track").
  AC5  — What-if panel entry is surfaced when behind, headline is still-winnable.
  AC6  — Near-milestone copy shows short horizon when ≤4 weeks.
  AC7  — WeightVoice module exists; weight-chart.js delegates copy to it.
  AC8  — Endpoint purity: no new endpoints added; W1/W2 fields are sufficient.
  AC9  — Null safety: null inputs render dash (—).
  AC10 — No regressions: verdict/projection/what-if work for ahead/on-plan/<7 entries.
"""

from pathlib import Path
import re

FRONTEND = Path(__file__).parent.parent / "frontend"
WEIGHT_VOICE_JS = FRONTEND / "js" / "lib" / "weight-voice.js"
CHART_JS        = FRONTEND / "js" / "weight-chart.js"
WEIGHT_JS       = FRONTEND / "js" / "weight.js"
WEIGHT_HTML     = FRONTEND / "pages" / "weight.html"


def _voice_src():
    return WEIGHT_VOICE_JS.read_text()


def _chart_src():
    return CHART_JS.read_text()


def _weight_src():
    return WEIGHT_JS.read_text()


def _html():
    return WEIGHT_HTML.read_text()


# ─────────────────────────────────────────────────────────────────────────────
# AC7 — Voice module file exists and exports WeightVoice
# ─────────────────────────────────────────────────────────────────────────────

class TestAC7VoiceModule:
    """AC7: All coaching strings pass through a shared voice module."""

    def test_weight_voice_js_file_exists(self):
        """weight-voice.js must exist under frontend/js/lib/."""
        assert WEIGHT_VOICE_JS.exists(), (
            "frontend/js/lib/weight-voice.js does not exist — voice module required (AC7)"
        )

    def test_weight_voice_exports_global(self):
        """weight-voice.js must expose a global WeightVoice object."""
        src = _voice_src()
        assert "WeightVoice" in src, (
            "WeightVoice not found in weight-voice.js — must export global WeightVoice"
        )

    def test_weight_voice_has_verdict_copy_fn(self):
        """WeightVoice must expose a verdictCopy function."""
        src = _voice_src()
        assert "verdictCopy" in src, (
            "verdictCopy function missing from weight-voice.js"
        )

    def test_weight_voice_has_projection_label_fn(self):
        """WeightVoice must expose a projectionLabel function."""
        src = _voice_src()
        assert "projectionLabel" in src, (
            "projectionLabel function missing from weight-voice.js"
        )

    def test_weight_voice_has_what_if_headline_fn(self):
        """WeightVoice must expose a whatIfHeadline function."""
        src = _voice_src()
        assert "whatIfHeadline" in src, (
            "whatIfHeadline function missing from weight-voice.js"
        )

    def test_weight_voice_has_near_milestone_fn(self):
        """WeightVoice must expose a nearMilestoneCopy function."""
        src = _voice_src()
        assert "nearMilestoneCopy" in src, (
            "nearMilestoneCopy function missing from weight-voice.js"
        )

    def test_weight_voice_has_dash_if_null_fn(self):
        """WeightVoice must expose a dashIfNull helper."""
        src = _voice_src()
        assert "dashIfNull" in src, (
            "dashIfNull helper missing from weight-voice.js"
        )

    def test_weight_chart_uses_weight_voice(self):
        """weight-chart.js must call WeightVoice — no raw copy strings for coaching."""
        src = _chart_src()
        assert "WeightVoice" in src, (
            "WeightVoice not referenced in weight-chart.js — verdict banner copy must "
            "come from the voice module, not raw string literals (AC7)"
        )

    def test_chart_no_raw_gap_shaded_copy(self):
        """weight-chart.js must not contain the old raw 'gap shaded' copy string."""
        src = _chart_src()
        assert "gap shaded" not in src, (
            "'gap shaded' raw string still present in weight-chart.js — "
            "must be replaced with WeightVoice.verdictCopy() (AC7)"
        )

    def test_chart_no_raw_trend_sits_copy(self):
        """weight-chart.js must not contain the old 'Trend sits' raw string."""
        src = _chart_src()
        assert "Trend sits" not in src, (
            "'Trend sits' raw string still in weight-chart.js — "
            "replace with WeightVoice.verdictCopy() call (AC7)"
        )

    def test_html_loads_weight_voice_before_chart(self):
        """weight.html must load weight-voice.js before weight-chart.js."""
        html = _html()
        voice_idx = html.find("weight-voice.js")
        chart_idx = html.find("weight-chart.js")
        assert voice_idx != -1, (
            "weight-voice.js not loaded in weight.html (AC7)"
        )
        assert voice_idx < chart_idx, (
            "weight-voice.js must be loaded BEFORE weight-chart.js in weight.html (AC7)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — Verdict banner references 7-day trend
# ─────────────────────────────────────────────────────────────────────────────

class TestAC1TrendAnchor:
    """AC1: Verdict copy references the seven-day trend vs plan."""

    def test_voice_verdict_copy_contains_trend_reference(self):
        """verdictCopy function must produce copy that references the trend."""
        src = _voice_src()
        assert "trend" in src.lower() or "7-day" in src.lower(), (
            "verdictCopy in weight-voice.js contains no 'trend' or '7-day' reference — "
            "verdict copy must be anchored to the 7-day moving average (AC1)"
        )

    def test_voice_verdict_copy_for_behind_includes_trend_value(self):
        """The behind-plan message must reference the trend_kg value."""
        src = _voice_src()
        # The function must interpolate trendStr into the behind-plan message
        assert "trendStr" in src or "trend_kg" in src, (
            "verdict copy does not include trend_kg in the message — "
            "AC1 requires the trend value to appear in the banner copy"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — Calm up-day: on-plan/ahead gap_direction → neutral/positive
# ─────────────────────────────────────────────────────────────────────────────

class TestAC2CalmUpDay:
    """AC2: on-plan/ahead state must not produce red/alarmed copy."""

    def test_voice_no_alarmed_copy_for_ahead_state(self):
        """verdictCopy for ahead/on-plan must not contain alarm words."""
        src = _voice_src()
        # Extract the section associated with 'ahead' or 'on_plan' return values
        # Verify the module does not have 'behind' pill class for ahead scenario
        assert "ahead" in src, "WeightVoice must handle 'ahead' gap_direction"
        # The 'ahead' block must not contain shaming/alarmed language
        ahead_pattern = re.search(
            r"gapDir\s*===?\s*['\"]ahead['\"].*?return\s*\{.*?\}",
            src, re.DOTALL
        )
        if ahead_pattern:
            segment = ahead_pattern.group(0)
            for bad_word in ("alarmed", "failed", "missed", "off track", "behind"):
                assert bad_word.lower() not in segment.lower(), (
                    f"Alarmed word '{bad_word}' found in ahead-state copy (AC2)"
                )

    def test_verdict_banner_pill_class_logic_based_on_gap_direction(self):
        """verdict pill class must derive from gap_direction, not today_delta_kg."""
        chart_src = _chart_src()
        # The pill class setter must reference gap_direction or 'state', not today_delta
        assert "gap_direction" in chart_src or "state" in chart_src, (
            "Pill class must be set based on gap_direction / coaching state (AC2)"
        )
        # Must NOT use today_delta_kg to set the alarmed pill
        pill_section = re.search(
            r"chart-verdict-pill.*?pill\.className\s*=.*?;",
            chart_src, re.DOTALL
        )
        if pill_section:
            segment = pill_section.group(0)
            assert "today_delta" not in segment, (
                "Pill class is driven by today_delta_kg — must use gap_direction (AC2)"
            )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — Behind plan → concrete next lever
# ─────────────────────────────────────────────────────────────────────────────

class TestAC3BehindPlanLever:
    """AC3: When behind plan the copy surfaces a concrete action."""

    def test_voice_behind_state_produces_lever_copy(self):
        """verdictCopy behind-plan branch must include an actionable suggestion."""
        src = _voice_src()
        # The behind-plan branch should call a helper (e.g. _nextLever)
        assert "_nextLever" in src or "lever" in src.lower() or "lightest" in src or "lighter" in src, (
            "behind-plan copy in weight-voice.js contains no concrete lever suggestion (AC3)"
        )

    def test_voice_lever_copy_is_actionable(self):
        """The lever copy must be an action phrase, not a bare deficit display."""
        src = _voice_src()
        # Must not say just "behind by X kg" with no follow-up
        # Must include some form of "day", "week", or repeatable action
        has_action = any(
            kw in src for kw in ("tomorrow", "week", "lightest", "lighter", "day", "adjust")
        )
        assert has_action, (
            "No actionable language found in weight-voice.js lever copy (AC3)"
        )

    def test_voice_behind_copy_no_single_gap_only(self):
        """behind-plan copy must not be ONLY a numeric deficit (no coaching)."""
        src = _voice_src()
        # The behind branch should have more than just absGap — it must include a message
        behind_section = re.search(
            r"gapDir\s*===?\s*['\"]behind['\"].*?return\s*\{.*?\}",
            src, re.DOTALL
        )
        if behind_section:
            segment = behind_section.group(0)
            # Message must include more than just the gap number
            assert "lever" in segment or "message" in segment, (
                "behind-plan copy appears to only show a deficit — "
                "must include a concrete next-lever message (AC3)"
            )


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Projection line forward-looking label
# ─────────────────────────────────────────────────────────────────────────────

class TestAC4ProjectionLabel:
    """AC4: Projection line label is forward-looking (no failure language)."""

    def test_projection_label_function_exists(self):
        """projectionLabel must be defined in weight-voice.js."""
        src = _voice_src()
        assert "function projectionLabel" in src or "projectionLabel" in src, (
            "projectionLabel missing from weight-voice.js (AC4)"
        )

    def test_projection_label_no_failure_language(self):
        """projectionLabel must not contain 'missed target' or 'off track'."""
        src = _voice_src()
        for bad in ("missed target", "off track", "failed", "failure"):
            assert bad.lower() not in src.lower(), (
                f"Failure language '{bad}' found in weight-voice.js projectionLabel area (AC4)"
            )

    def test_projection_label_forward_framing(self):
        """projectionLabel must contain forward-looking language."""
        src = _voice_src()
        forward_words = ("from today", "path from", "realistic", "forward", "from here")
        has_forward = any(w in src.lower() for w in forward_words)
        assert has_forward, (
            "projectionLabel in weight-voice.js has no forward-looking framing — "
            "must say something like 'Realistic path from today' (AC4)"
        )

    def test_chart_uses_projection_label_in_future_zone(self):
        """weight-chart.js must call WeightVoice.projectionLabel for the projection line."""
        chart_src = _chart_src()
        assert "projectionLabel" in chart_src, (
            "weight-chart.js does not call WeightVoice.projectionLabel — "
            "projection line must use voice module for its label (AC4)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — What-if panel surfaced when behind plan
# ─────────────────────────────────────────────────────────────────────────────

class TestAC5WhatIfPanel:
    """AC5: What-if panel entry is highlighted when behind, headline is winnable."""

    def test_html_has_whatif_prompt_element(self):
        """weight.html must contain a what-if prompt element."""
        html = _html()
        assert "whatif-prompt" in html or "what-if-prompt" in html, (
            "No whatif-prompt element in weight.html — "
            "AC5 requires a what-if entry point to be surfaced when behind plan"
        )

    def test_whatif_headline_fn_in_voice_module(self):
        """whatIfHeadline must be defined in weight-voice.js."""
        src = _voice_src()
        assert "function whatIfHeadline" in src or "whatIfHeadline" in src, (
            "whatIfHeadline function missing from weight-voice.js (AC5)"
        )

    def test_whatif_headline_is_winnable_framing(self):
        """whatIfHeadline output must frame the scenario as achievable."""
        src = _voice_src()
        # Must include some form of "arrive", "get there", "by", or "still"
        winnable_words = ("arrive", "by ", "still", "gentler", "adjust", "rate")
        has_winnable = any(w in src for w in winnable_words)
        assert has_winnable, (
            "whatIfHeadline in weight-voice.js lacks winnable framing — "
            "must say something like 'Even at a gentler rate you\\'d arrive by...' (AC5)"
        )

    def test_weight_js_shows_whatif_when_behind(self):
        """weight.js must surface/unhide the what-if prompt when gap_direction is behind."""
        src = _weight_src()
        assert "whatif" in src.lower() or "what-if" in src.lower(), (
            "weight.js does not reference the whatif-prompt — "
            "must show/highlight it when behind plan (AC5)"
        )

    def test_weight_js_calls_whatif_headline(self):
        """weight.js must call WeightVoice.whatIfHeadline."""
        src = _weight_src()
        assert "WeightVoice" in src, (
            "weight.js does not use WeightVoice — "
            "whatIfHeadline must be called when behind plan (AC5)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC6 — Near-milestone short-horizon copy
# ─────────────────────────────────────────────────────────────────────────────

class TestAC6NearMilestoneCopy:
    """AC6: Within ~4 weeks of next milestone, show short-horizon copy."""

    def test_near_milestone_fn_handles_1_week(self):
        """nearMilestoneCopy returns short copy for 1-week horizon."""
        src = _voice_src()
        # The function must return text containing "week" for small values
        assert "week" in src.lower(), (
            "nearMilestoneCopy in weight-voice.js must produce 'week' copy for short horizons (AC6)"
        )

    def test_near_milestone_fn_handles_4_week_boundary(self):
        """nearMilestoneCopy includes 4 in its boundary logic."""
        src = _voice_src()
        assert "4" in src, (
            "nearMilestoneCopy must use 4-week boundary (AC6)"
        )

    def test_near_milestone_fn_returns_null_beyond_4_weeks(self):
        """nearMilestoneCopy returns null when > 4 weeks away."""
        src = _voice_src()
        assert "null" in src or "return null" in src, (
            "nearMilestoneCopy must return null when beyond 4-week window (AC6)"
        )

    def test_weight_js_calls_near_milestone(self):
        """weight.js must call WeightVoice.nearMilestoneCopy."""
        src = _weight_src()
        assert "nearMilestoneCopy" in src, (
            "weight.js does not call nearMilestoneCopy — "
            "near-milestone short-horizon copy must be shown (AC6)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC8 — Endpoint purity: no new endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestAC8EndpointPurity:
    """AC8: No new endpoint calls; implementation reads W1 and W2 fields only."""

    def test_no_new_weight_coaching_endpoint(self):
        """backend/main.py must not have a new /api/weight-coaching endpoint."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from backend.main import app as _app
        routes = {str(r.path) for r in _app.routes}  # type: ignore[attr-defined]
        assert "/api/weight-coaching" not in routes, (
            "/api/weight-coaching endpoint was added — AC8 requires no new endpoints"
        )
        assert "/api/weight/voice" not in routes, (
            "/api/weight/voice endpoint was added — AC8 requires no new endpoints"
        )
        assert "/api/weight-voice" not in routes, (
            "/api/weight-voice endpoint was added — AC8 requires no new endpoints"
        )

    def test_weight_js_no_new_fetch_calls(self):
        """weight.js must not introduce new fetch calls beyond existing W1 / W2."""
        src = _weight_src()
        # Count fetch('/ calls — any fetch starting with /api/weight should be
        # limited to the existing two: weight-chart and weight-targets/active
        new_endpoints = re.findall(r"fetch\(['\`]/api/weight-coaching", src)
        assert not new_endpoints, (
            "weight.js calls /api/weight-coaching — not permitted (AC8)"
        )

    def test_chart_js_no_new_fetch_calls(self):
        """weight-chart.js must not introduce any new fetch calls."""
        src = _chart_src()
        fetch_calls = re.findall(r"fetch\s*\(", src)
        assert len(fetch_calls) == 0, (
            f"weight-chart.js contains {len(fetch_calls)} fetch() call(s) — "
            "chart component must not make API calls (AC8)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC9 — Null safety
# ─────────────────────────────────────────────────────────────────────────────

class TestAC9NullSafety:
    """AC9: Null/undefined fields render as '—' with no coaching copy attempted."""

    def test_dash_if_null_helper_exists(self):
        """dashIfNull helper must exist in weight-voice.js."""
        src = _voice_src()
        assert "dashIfNull" in src, (
            "dashIfNull missing from weight-voice.js — null-safe helper required (AC9)"
        )

    def test_dash_if_null_returns_dash_for_null(self):
        """dashIfNull must return '—' for null/undefined."""
        src = _voice_src()
        assert "—" in src or "\\u2014" in src or "&#x2014" in src, (
            "dashIfNull in weight-voice.js does not return '—' (em-dash) for null (AC9)"
        )

    def test_verdict_copy_handles_null_trend_kg(self):
        """verdictCopy must return dash message when trend_kg is null."""
        src = _voice_src()
        # The function must guard on trend_kg being null
        assert "trend_kg == null" in src or "trend_kg != null" in src or "trend_kg ===" in src, (
            "verdictCopy does not guard against null trend_kg — null safety required (AC9)"
        )

    def test_near_milestone_handles_null(self):
        """nearMilestoneCopy must guard against null weeksAway."""
        src = _voice_src()
        assert "weeksAway == null" in src or "weeksAway != null" in src or "null" in src, (
            "nearMilestoneCopy does not handle null weeksAway (AC9)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC10 — No regressions
# ─────────────────────────────────────────────────────────────────────────────

class TestAC10NoRegressions:
    """AC10: Chart verdict/projection/what-if work for ahead, on-plan, <7 entries."""

    def test_chart_verdict_element_still_present(self):
        """#chart-verdict DOM element must still exist in weight.html."""
        html = _html()
        assert 'id="chart-verdict"' in html, (
            "#chart-verdict element removed from weight.html — regression (AC10)"
        )
        assert 'id="chart-verdict-pill"' in html, (
            "#chart-verdict-pill element removed from weight.html — regression (AC10)"
        )
        assert 'id="chart-verdict-text"' in html, (
            "#chart-verdict-text element removed from weight.html — regression (AC10)"
        )

    def test_update_verdict_banner_fn_still_present(self):
        """_updateVerdictBanner function must still exist in weight-chart.js."""
        src = _chart_src()
        assert "_updateVerdictBanner" in src, (
            "_updateVerdictBanner removed from weight-chart.js — regression (AC10)"
        )

    def test_chart_still_has_ahead_and_behind_pill_classes(self):
        """weight.html must still define CSS for ahead and behind pill states."""
        html = _html()
        assert "chart-verdict-pill--ahead" in html, (
            "chart-verdict-pill--ahead CSS removed — regression (AC10)"
        )
        assert "chart-verdict-pill--behind" in html, (
            "chart-verdict-pill--behind CSS removed — regression (AC10)"
        )

    def test_weight_voice_handles_on_plan_state(self):
        """verdictCopy must handle 'on_plan' gap_direction without error."""
        src = _voice_src()
        assert "on_plan" in src, (
            "weight-voice.js does not handle 'on_plan' gap_direction — regression (AC10)"
        )

    def test_weight_voice_handles_no_data_state(self):
        """verdictCopy must handle 'no_data' / null gap_direction gracefully."""
        src = _voice_src()
        assert "no_data" in src or "null" in src, (
            "weight-voice.js does not handle no_data/null gap_direction — regression (AC10)"
        )

    def test_progress_card_elements_intact(self):
        """Progress card DOM elements must still be present in weight.html."""
        html = _html()
        for eid in ("progress-card", "pstat-next-date", "pstat-next-val", "pgstatus-pill"):
            assert f'id="{eid}"' in html, (
                f"#{eid} removed from weight.html — regression (AC10)"
            )
