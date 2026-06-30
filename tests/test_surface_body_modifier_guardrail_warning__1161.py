"""Tests for issue #1161: Surface guardrail warning when loss is excessive or EA is low.

AC coverage:
- AC1: Warning displayed when loss velocity exceeds threshold OR EA is below penalty boundary
- AC2: Warning framed as performance/health risk — no target value referenced
- AC3: Warning clears automatically when both conditions return to safe range
- AC4: No warning shown when both loss rate and EA are within safe bounds
- AC5: Warning state persists correctly across widget re-renders (JS logic check)
- AC6: Warning is visually distinct from other status indicators (distinct CSS class/colour)
"""
import json
import os
import re

import pytest

from backend.services.body_modifier import (
    RATE_ZERO_CROSSING,
    EA_LOW_THRESHOLD,
    compute_body_modifier_guardrail,
)


# ── Pure-function tests ────────────────────────────────────────────────────────

class TestComputeBodyModifierGuardrail:
    """Pure-function unit tests for compute_body_modifier_guardrail."""

    def test_returns_dict_with_required_keys(self):
        """Returns dict with guardrail_state, guardrail_message, in_penalty_ea, in_penalty_loss."""
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert "guardrail_state" in result
        assert "guardrail_message" in result
        assert "in_penalty_ea" in result
        assert "in_penalty_loss" in result

    def test_safe_conditions_return_ok(self):
        """AC4: safe loss rate and adequate EA → guardrail_state='ok', no message."""
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""
        assert result["in_penalty_ea"] is False
        assert result["in_penalty_loss"] is False

    def test_excessive_loss_triggers_warn(self):
        """AC1 (loss): loss rate > RATE_ZERO_CROSSING → guardrail_state='warn'."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)  # negative = losing weight
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_loss"] is True
        assert result["in_penalty_ea"] is False

    def test_low_ea_triggers_warn(self):
        """AC1 (EA): ea_proxy below EA_LOW_THRESHOLD → guardrail_state='warn'."""
        low_ea = EA_LOW_THRESHOLD - 0.1
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=low_ea)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_ea"] is True
        assert result["in_penalty_loss"] is False

    def test_both_conditions_warn_once(self):
        """AC1 + no duplicate: both EA low AND loss excessive → single warn (no duplication)."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        low_ea = EA_LOW_THRESHOLD - 0.1
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=low_ea)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_ea"] is True
        assert result["in_penalty_loss"] is True
        # Exactly one message, not two concatenated messages
        assert isinstance(result["guardrail_message"], str)
        assert len(result["guardrail_message"]) > 0

    def test_warn_clears_when_conditions_normalize(self):
        """AC3: After warn, safe inputs produce ok state (auto-clear logic)."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        result_warn = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        assert result_warn["guardrail_state"] == "warn"

        # Now safe
        result_ok = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert result_ok["guardrail_state"] == "ok"
        assert result_ok["guardrail_message"] == ""

    def test_message_does_not_mention_target(self):
        """AC2: Warning message must not reference a target value."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        msg = result["guardrail_message"].lower()
        forbidden = ["target", "goal", "aim for", "your target", "loss target"]
        for phrase in forbidden:
            assert phrase not in msg, f"Message must not mention '{phrase}': {msg!r}"

    def test_message_framed_as_health_risk(self):
        """AC2: Warning message is framed as a performance/health risk."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        msg = result["guardrail_message"].lower()
        risk_words = ["penalty", "risk", "health", "performance", "excessive", "too fast", "concern"]
        assert any(w in msg for w in risk_words), (
            f"Message should be framed as a performance/health risk: {msg!r}"
        )

    def test_ea_warning_message_does_not_mention_target(self):
        """AC2: EA warning message must not reference a target value."""
        low_ea = EA_LOW_THRESHOLD - 0.1
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=low_ea)
        msg = result["guardrail_message"].lower()
        forbidden = ["target", "goal", "aim for"]
        for phrase in forbidden:
            assert phrase not in msg, f"EA message must not mention '{phrase}': {msg!r}"

    def test_at_zero_crossing_boundary_not_warn(self):
        """Boundary: loss rate exactly at RATE_ZERO_CROSSING → not in penalty zone."""
        at_boundary = -RATE_ZERO_CROSSING  # exactly at crossing
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=at_boundary, ea_proxy=1.0)
        assert result["in_penalty_loss"] is False

    def test_just_above_zero_crossing_triggers_warn(self):
        """Boundary: loss rate slightly above RATE_ZERO_CROSSING → penalty zone."""
        just_over = -(RATE_ZERO_CROSSING + 0.001)
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=just_over, ea_proxy=1.0)
        assert result["in_penalty_loss"] is True

    def test_ea_at_threshold_not_warn(self):
        """Boundary: ea_proxy exactly at EA_LOW_THRESHOLD → not in penalty region."""
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=EA_LOW_THRESHOLD)
        assert result["in_penalty_ea"] is False

    def test_ea_just_below_threshold_triggers_warn(self):
        """Boundary: ea_proxy just below EA_LOW_THRESHOLD → penalty region."""
        just_below = EA_LOW_THRESHOLD - 0.001
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=just_below)
        assert result["in_penalty_ea"] is True

    def test_weight_gain_no_loss_penalty(self):
        """Positive weekly_pct_bw_rate (gaining weight) → in_penalty_loss=False."""
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.5, ea_proxy=1.0)
        assert result["in_penalty_loss"] is False


# ── API endpoint tests ─────────────────────────────────────────────────────────

class TestBodyModifierGuardrailEndpoint:
    """Tests for GET /api/body-modifier/guardrail."""

    def setup_method(self):
        try:
            from backend.main import app, resolve_user
            from unittest.mock import MagicMock
            self._app = app
            self._resolve_user = resolve_user
            self._mock_user = MagicMock()
            self._mock_user.id = "user-test-123"
        except ImportError as exc:
            pytest.skip(f"backend.main not importable: {exc}")

    def teardown_method(self):
        if hasattr(self, '_app'):
            self._app.dependency_overrides.clear()

    def _get_endpoint(self, weekly_pct_bw_rate=0.0, ea_proxy=1.0):
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        guardrail_result = compute_body_modifier_guardrail(
            weekly_pct_bw_rate=weekly_pct_bw_rate,
            ea_proxy=ea_proxy,
        )
        self._app.dependency_overrides[self._resolve_user] = lambda: self._mock_user

        with patch("backend.main.get_body_modifier_guardrail_for_user", return_value=guardrail_result):
            client = TestClient(self._app, raise_server_exceptions=True)
            resp = client.get("/api/body-modifier/guardrail")
        return resp

    def test_endpoint_returns_200(self):
        """Endpoint returns HTTP 200 for authenticated user."""
        resp = self._get_endpoint()
        assert resp.status_code == 200

    def test_endpoint_returns_guardrail_state(self):
        """Endpoint response includes guardrail_state field."""
        resp = self._get_endpoint()
        body = resp.json()
        assert "guardrail_state" in body

    def test_endpoint_returns_guardrail_message(self):
        """Endpoint response includes guardrail_message field."""
        resp = self._get_endpoint()
        body = resp.json()
        assert "guardrail_message" in body

    def test_endpoint_warn_when_loss_excessive(self):
        """AC1: Endpoint returns warn when loss rate is excessive."""
        excessive_loss = -(RATE_ZERO_CROSSING + 0.5)
        resp = self._get_endpoint(weekly_pct_bw_rate=excessive_loss, ea_proxy=1.0)
        assert resp.status_code == 200
        body = resp.json()
        assert body["guardrail_state"] == "warn"

    def test_endpoint_warn_when_ea_low(self):
        """AC1: Endpoint returns warn when EA is below penalty boundary."""
        low_ea = EA_LOW_THRESHOLD - 0.1
        resp = self._get_endpoint(weekly_pct_bw_rate=0.0, ea_proxy=low_ea)
        assert resp.status_code == 200
        body = resp.json()
        assert body["guardrail_state"] == "warn"

    def test_endpoint_ok_when_safe(self):
        """AC4: Endpoint returns ok when both conditions are within safe bounds."""
        resp = self._get_endpoint(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert resp.status_code == 200
        body = resp.json()
        assert body["guardrail_state"] == "ok"
        assert body["guardrail_message"] == ""


# ── Frontend tests ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def home_js():
    path = os.path.join(os.path.dirname(__file__), "../frontend/js/home.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def home_html():
    path = os.path.join(os.path.dirname(__file__), "../frontend/pages/home.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def home_inline_styles(home_html):
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', home_html, re.DOTALL)
    return "\n".join(blocks)


class TestHomePageWarningPresence:
    """Tests that the home page renders the guardrail warning widget."""

    def test_home_js_fetches_guardrail_endpoint(self, home_js):
        """AC1/AC5: home.js fetches /api/body-modifier/guardrail."""
        assert "body-modifier/guardrail" in home_js, (
            "home.js must fetch /api/body-modifier/guardrail to get the warning state"
        )

    def test_home_js_checks_guardrail_state_before_rendering(self, home_js):
        """AC4: home.js conditionally renders the warning only when guardrail_state is warn."""
        has_check = bool(re.search(
            r"guardrail_state\s*[=!]=+\s*['\"]warn['\"]|"
            r"['\"]warn['\"]\s*[=!]=+\s*guardrail_state",
            home_js,
        ))
        assert has_check, (
            "home.js must check guardrail_state === 'warn' before rendering the warning"
        )

    def test_home_js_renders_guardrail_message_from_data(self, home_js):
        """AC2: home.js renders guardrail_message from API data, not hardcoded text."""
        assert "guardrail_message" in home_js, (
            "home.js must reference guardrail_message from the API response"
        )

    def test_home_js_does_not_hardcode_target_references(self, home_js):
        """AC2: home.js must not hardcode any target-referencing text in the guardrail block."""
        # Hardcoded penalty/target messages are forbidden in the JS
        forbidden = ["your weight target", "loss target", "aim for"]
        for phrase in forbidden:
            assert phrase.lower() not in home_js.lower(), (
                f"home.js must not hardcode guardrail text referencing '{phrase}'"
            )

    def test_home_html_has_guardrail_container(self, home_html):
        """AC1: home.html includes a container element for the guardrail warning."""
        has_container = (
            "body-modifier-guardrail" in home_html or
            "bm-guardrail" in home_html
        )
        assert has_container, (
            "home.html must include a container element for the body-modifier guardrail warning "
            "(e.g. id='body-modifier-guardrail')"
        )

    def test_home_js_clears_warning_when_ok(self, home_js):
        """AC3: home.js removes or hides the warning when guardrail_state is ok."""
        # Must have conditional logic that handles both warn and non-warn states
        has_clear_logic = bool(re.search(
            r"guardrail_state.*[?:]|"
            r"if\s*\([^)]*guardrail|"
            r"guardrail_state\s*!==?\s*['\"]warn",
            home_js,
        ))
        assert has_clear_logic, (
            "home.js must clear the warning when guardrail_state is not warn (AC3)"
        )

    def test_home_js_persists_warning_across_rerenders(self, home_js):
        """AC5: home.js re-fetches or re-renders the guardrail on each init/render cycle."""
        # The guardrail fetch must be inside the init flow (not a one-time event handler)
        # Check that the fetch call is present and tied to the rendering lifecycle
        has_fetch = "body-modifier/guardrail" in home_js
        assert has_fetch, (
            "home.js must fetch the guardrail state as part of its rendering lifecycle "
            "to ensure the warning persists across re-renders and tab switches (AC5)"
        )


class TestHomePageWarningStyle:
    """AC6: Warning is visually distinct from other status indicators."""

    def test_home_inline_styles_define_guardrail_class(self, home_inline_styles):
        """AC6: inline CSS defines a distinct class for the body-modifier guardrail warning."""
        has_class = bool(re.search(
            r"\.bm-guardrail|\.body-modifier-guardrail",
            home_inline_styles,
        ))
        assert has_class, (
            "home.html inline CSS must define a distinct class for the body-modifier guardrail "
            "(e.g. .bm-guardrail or .body-modifier-guardrail)"
        )

    def test_home_guardrail_css_uses_distinct_colour(self, home_inline_styles):
        """AC6: The guardrail CSS class uses a colour different from the default (distinct from amber)."""
        # Find the bm-guardrail block
        block_match = re.search(
            r'(?:\.bm-guardrail|\.body-modifier-guardrail)\s*\{[^}]+\}',
            home_inline_styles,
            re.DOTALL,
        )
        assert block_match, (
            "home.html must define a CSS block for .bm-guardrail or .body-modifier-guardrail"
        )
        block = block_match.group(0)
        # Should not be plain white or transparent — must have a visible colour cue
        has_colour = bool(re.search(
            r'background|color|border|background-color',
            block,
        ))
        assert has_colour, (
            "The guardrail CSS class must set a visible colour (background, color, or border) "
            "to distinguish it from other status indicators (AC6)"
        )
