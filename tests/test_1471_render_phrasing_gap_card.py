"""Tests for issue #1471: Render LLM coach phrasing in the improvement panel.

AC: _buildGapCard renders f.phrasing in the evidence line, falling back to
f.evidence_text when phrasing_source === "template" or phrasing is empty.

Since _buildGapCard is JavaScript, these tests verify:
1. The API response includes both `phrasing` and `phrasing_source` fields so the
   frontend has the data it needs to implement the fallback logic.
2. When phrasing_source is "template", phrasing equals the deterministic
   evidence_text (so the JS fallback is transparent — same string either way).
3. The phrasing_source field is always "llm" or "template" (never None or other).
"""
from __future__ import annotations

import uuid



# ── helpers ───────────────────────────────────────────────────────────────────

def _make_finding(code="no_recent_plyo", evidence=None):
    return {
        "code": code,
        "severity": 2,
        "recommendation": "Add plyometrics.",
        "evidence": evidence or [
            {"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}
        ],
        "target": None,
    }


# ── AC: API response includes phrasing + phrasing_source on every finding ─────

class TestPhrasingFieldsInAPIResponse:
    """The API enriches each finding with phrasing + phrasing_source so the
    frontend _buildGapCard can apply the fallback without a second request."""

    def test_get_finding_phrasing_returns_both_fields(self):
        """get_finding_phrasing always returns {phrasing, phrasing_source}."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()
        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert "phrasing" in result, "phrasing field must be present"
        assert "phrasing_source" in result, "phrasing_source field must be present"

    def test_phrasing_source_is_valid_literal(self):
        """phrasing_source is exactly 'llm' or 'template' — never None or other."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()
        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] in ("llm", "template"), (
            f"phrasing_source must be 'llm' or 'template', got {result['phrasing_source']!r}"
        )

    def test_phrasing_is_non_empty_string(self):
        """phrasing is always a non-empty string (never None or '')."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()
        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert isinstance(result["phrasing"], str)
        assert result["phrasing"], "phrasing must not be empty"


# ── AC: Fallback logic — when phrasing_source is "template", phrasing matches evidence_text

class TestTemplateFallbackEquality:
    """When phrasing_source is 'template', phrasing equals the deterministic
    evidence_text. This means the JS fallback condition
    `phrasing_source === 'template'` correctly degrades to evidence_text with
    no visible change."""

    def test_template_source_phrasing_equals_evidence_text(self):
        """phrasing matches render_evidence_text when phrasing_source is 'template'."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        evidence = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]
        finding = _make_finding(code="no_recent_plyo", evidence=evidence)

        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        # LLM is parked; phrasing_source is always "template"
        assert result["phrasing_source"] == "template"
        expected = render_evidence_text("no_recent_plyo", evidence, None)
        assert result["phrasing"] == expected, (
            "When phrasing_source='template', phrasing must equal evidence_text "
            "so the JS fallback is transparent"
        )

    def test_template_source_for_strength_lapsed(self):
        """Template fallback works for a different finding code too."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        evidence = [{"metric": "days_since_strength", "value": 28, "threshold": 21, "window": "21d"}]
        finding = {
            "code": "strength_lapsed",
            "severity": 2,
            "recommendation": "Do a strength session this week.",
            "evidence": evidence,
            "target": None,
        }

        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"
        expected = render_evidence_text("strength_lapsed", evidence, None)
        assert result["phrasing"] == expected


# ── AC: JS rendering logic — documented as a contract test ────────────────────

class TestRenderingContract:
    """Documents the expected JS rendering logic as a Python contract.

    The JS change in _buildGapCard is:
        var evidenceText = (f.phrasing && f.phrasing_source !== 'template')
            ? f.phrasing
            : (f.evidence_text || '');

    This class mirrors that logic in Python to confirm what the backend delivers
    produces the expected output under both conditions.
    """

    def _js_evidence_text(self, finding_dict: dict) -> str:
        """Mirror of the JS fallback logic in _buildGapCard."""
        phrasing = finding_dict.get("phrasing", "")
        source = finding_dict.get("phrasing_source", "template")
        evidence_text = finding_dict.get("evidence_text", "")
        if phrasing and source != "template":
            return phrasing
        return evidence_text

    def test_template_source_falls_back_to_evidence_text(self):
        """phrasing_source='template' → JS uses evidence_text."""
        f = {
            "phrasing": "Coach voice text.",
            "phrasing_source": "template",
            "evidence_text": "35 days since last plyo (threshold 28).",
        }
        assert self._js_evidence_text(f) == "35 days since last plyo (threshold 28)."

    def test_llm_source_uses_phrasing(self):
        """phrasing_source='llm' → JS uses phrasing (not evidence_text)."""
        f = {
            "phrasing": "You haven't done plyometrics in 35 days.",
            "phrasing_source": "llm",
            "evidence_text": "35 days since last plyo (threshold 28).",
        }
        assert self._js_evidence_text(f) == "You haven't done plyometrics in 35 days."

    def test_empty_phrasing_falls_back_to_evidence_text(self):
        """Empty phrasing → JS falls back to evidence_text even when source is 'llm'."""
        f = {
            "phrasing": "",
            "phrasing_source": "llm",
            "evidence_text": "35 days since last plyo (threshold 28).",
        }
        assert self._js_evidence_text(f) == "35 days since last plyo (threshold 28)."

    def test_missing_phrasing_falls_back_to_evidence_text(self):
        """Missing phrasing key → JS falls back to evidence_text."""
        f = {
            "phrasing_source": "template",
            "evidence_text": "35 days since last plyo (threshold 28).",
        }
        assert self._js_evidence_text(f) == "35 days since last plyo (threshold 28)."
