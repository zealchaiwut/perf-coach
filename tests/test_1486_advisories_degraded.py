"""Tests for issue #1486 — silent gap-analysis/verdict failures produce an all-clear brief.

Acceptance criteria derived from the issue:
  AC1: When run_gap_analysis raises, _assemble_advisories includes an error sentinel
       entry with severity="error" and key containing "gap_analysis".
  AC2: When _gather_training_verdict raises, _assemble_advisories includes an error
       sentinel entry with severity="error" and key containing "training_verdict".
  AC3: When both sources fail, both error sentinels are present.
  AC4: When both sources succeed, no error sentinel entries are in the result.
  AC5: _build_brief (in export_brief) sets advisories_degraded=True when
       _assemble_advisories returns entries with severity="error".
  AC6: _build_brief sets advisories_degraded=False (or absent) when
       _assemble_advisories returns only non-error entries.
  AC7: The valid findings from a partial failure (one source ok, one fails) are
       still present alongside the error sentinel — degraded does not mean empty.
"""
from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _import_daily_brief():
    """Import (or reload) backend.services.daily_brief with minimal mocks."""
    stubs = {
        "sqlalchemy": MagicMock(),
        "sqlalchemy.orm": MagicMock(),
        "backend": MagicMock(),
        "backend.db": MagicMock(),
    }
    for name, mock in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = mock

    import backend.services.daily_brief as svc
    return svc


def _import_export_brief():
    """Import (or reload) scripts.export_brief module."""
    import scripts.export_brief as m
    return m


@pytest.fixture
def svc():
    return _import_daily_brief()


@pytest.fixture
def m():
    return _import_export_brief()


# ── AC1: gap-analysis exception → error sentinel ─────────────────────────────

def test_gap_analysis_failure_adds_error_sentinel(svc):
    """AC1: run_gap_analysis raising → error sentinel with severity='error'."""
    with patch("backend.services.gap_analysis.engine.run_gap_analysis",
               side_effect=RuntimeError("db unavailable")), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict",
               return_value=None):

        result = svc._assemble_advisories(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 7, 14),
            {},
        )

    error_entries = [a for a in result if a.get("severity") == "error"]
    assert len(error_entries) >= 1

    gap_error = next((a for a in error_entries if "gap_analysis" in a.get("key", "")), None)
    assert gap_error is not None, "Expected an error sentinel with 'gap_analysis' in key"
    assert gap_error["severity"] == "error"
    assert gap_error["text"]  # non-empty error text


# ── AC2: training-verdict exception → error sentinel ─────────────────────────

def test_training_verdict_failure_adds_error_sentinel(svc):
    """AC2: _gather_training_verdict raising → error sentinel with severity='error'."""
    mock_result = {"findings": []}
    with patch("backend.services.gap_analysis.engine.run_gap_analysis",
               return_value=mock_result), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict",
               side_effect=RuntimeError("verdict unavailable")):

        result = svc._assemble_advisories(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 7, 14),
            {},
        )

    error_entries = [a for a in result if a.get("severity") == "error"]
    assert len(error_entries) >= 1

    verdict_error = next(
        (a for a in error_entries if "training_verdict" in a.get("key", "")), None
    )
    assert verdict_error is not None, "Expected an error sentinel with 'training_verdict' in key"
    assert verdict_error["severity"] == "error"
    assert verdict_error["text"]


# ── AC3: both sources fail → both sentinels present ──────────────────────────

def test_both_sources_fail_adds_two_sentinels(svc):
    """AC3: both gap_analysis and verdict failure → two distinct error sentinels."""
    with patch("backend.services.gap_analysis.engine.run_gap_analysis",
               side_effect=RuntimeError("gap gone")), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict",
               side_effect=RuntimeError("verdict gone")):

        result = svc._assemble_advisories(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 7, 14),
            {},
        )

    error_entries = [a for a in result if a.get("severity") == "error"]
    keys = [a.get("key", "") for a in error_entries]
    assert any("gap_analysis" in k for k in keys), "Missing gap_analysis error sentinel"
    assert any("training_verdict" in k for k in keys), "Missing training_verdict error sentinel"


# ── AC4: both sources succeed → no error sentinel ────────────────────────────

def test_no_error_sentinel_when_sources_succeed(svc):
    """AC4: normal run → zero error-severity entries in result."""
    mock_result = {"findings": [
        {"code": "X", "severity": 1, "recommendation": "ok"},
    ]}
    with patch("backend.services.gap_analysis.engine.run_gap_analysis",
               return_value=mock_result), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict",
               return_value=None):

        result = svc._assemble_advisories(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 7, 14),
            {},
        )

    error_entries = [a for a in result if a.get("severity") == "error"]
    assert error_entries == [], f"Unexpected error entries: {error_entries}"


# ── AC5: _build_brief → advisories_degraded=True when source fails ────────────

def test_build_brief_sets_advisories_degraded_true_on_failure(m):
    """AC5 (export_brief): advisories_degraded=True in payload when a source fails."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-14"}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0,
                 "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    degraded_advisories = [
        {"key": "gap_analysis_error", "severity": "error", "text": "Gap analysis unavailable"},
    ]

    with patch.object(m, "_fetch_plan", return_value=fake_plan), \
         patch.object(m, "_assemble_form", return_value=fake_form), \
         patch.object(m, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(m, "_assemble_advisories", return_value=degraded_advisories):

        brief = m._build_brief(date(2026, 7, 14), "http://localhost:9100", "uid", None)

    assert brief.get("advisories_degraded") is True, (
        f"Expected advisories_degraded=True; got {brief.get('advisories_degraded')!r}"
    )


# ── AC6: _build_brief → advisories_degraded=False when all sources succeed ───

def test_build_brief_sets_advisories_degraded_false_on_success(m):
    """AC6 (export_brief): advisories_degraded=False in payload when no source fails."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-14"}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0,
                 "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    good_advisories = [
        {"key": "some_finding", "severity": "info", "text": "Everything looks fine"},
    ]

    with patch.object(m, "_fetch_plan", return_value=fake_plan), \
         patch.object(m, "_assemble_form", return_value=fake_form), \
         patch.object(m, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(m, "_assemble_advisories", return_value=good_advisories):

        brief = m._build_brief(date(2026, 7, 14), "http://localhost:9100", "uid", None)

    assert brief.get("advisories_degraded") is False, (
        f"Expected advisories_degraded=False; got {brief.get('advisories_degraded')!r}"
    )


# ── AC7: partial failure → valid findings still present ──────────────────────

def test_valid_findings_preserved_alongside_error_sentinel(svc):
    """AC7: one source fails, other succeeds → both real findings AND error sentinel present."""
    mock_result = {"findings": [
        {"code": "volume_low", "severity": 2, "recommendation": "Increase weekly volume"},
    ]}
    with patch("backend.services.gap_analysis.engine.run_gap_analysis",
               return_value=mock_result), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict",
               side_effect=RuntimeError("verdict service down")):

        result = svc._assemble_advisories(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 7, 14),
            {},
        )

    real_findings = [a for a in result if a.get("severity") != "error"]
    error_findings = [a for a in result if a.get("severity") == "error"]

    assert any(a.get("key") == "volume_low" for a in real_findings), (
        "Real gap-analysis finding should still be in result"
    )
    assert len(error_findings) >= 1, "Error sentinel should be present for the failed source"


# ── daily_brief._build_brief also sets advisories_degraded ───────────────────

def test_daily_brief_build_brief_sets_degraded_flag(svc):
    """_build_brief in daily_brief also includes advisories_degraded in payload."""
    degraded_advisories = [
        {"key": "gap_analysis_error", "severity": "error", "text": "broken"},
    ]

    with patch.object(svc, "_assemble_advisories", return_value=degraded_advisories), \
         patch.object(svc, "_assemble_form", return_value={}), \
         patch.object(svc, "_assemble_recent_wrap", return_value={}), \
         patch.object(svc, "_assemble_weight", return_value={}), \
         patch.object(svc, "_assemble_week_plan", return_value=[]), \
         patch.object(svc, "_get_plan_for_date", return_value={}), \
         patch.object(svc, "_plan_to_session", return_value={}):

        brief = svc._build_brief(date(2026, 7, 14), user_id="uid")

    assert brief.get("advisories_degraded") is True
