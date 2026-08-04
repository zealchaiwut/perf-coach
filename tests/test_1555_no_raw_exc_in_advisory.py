"""Tests for issue #1555 — degraded advisory must not embed raw exception text.

AC1: When gap_analysis raises, the advisory text is a fixed friendly message,
     not f"Gap analysis unavailable: {exc}".
AC2: When training_verdict raises, the advisory text is a fixed friendly message,
     not f"Training verdict unavailable: {exc}".
AC3: The raw exception detail is NOT present in any advisory text field.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest


_USER_ID = uuid.uuid4()
_DATE = date(2026, 8, 4)
_SENTINEL = "SUPER_SECRET_DB_PASSWORD_LEAKED"


def _run_assemble(gap_exc=None, verdict_exc=None):
    """Call _assemble_advisories with controlled exceptions."""
    from backend.services.daily_brief import _assemble_advisories

    def _fake_gap(*a, **kw):
        if gap_exc is not None:
            raise gap_exc
        return {"findings": []}

    def _fake_verdict(*a, **kw):
        if verdict_exc is not None:
            raise verdict_exc
        return None

    with (
        patch(
            "backend.services.gap_analysis.engine.run_gap_analysis",
            side_effect=_fake_gap,
        ),
        patch(
            "backend.services.gap_analysis.engine._gather_training_verdict",
            side_effect=_fake_verdict,
        ),
    ):
        return _assemble_advisories(_USER_ID, _DATE, weight={})


# AC1 — gap_analysis exception produces a fixed text, not the raw exc message
def test_gap_analysis_error_advisory_text_is_fixed():
    exc = RuntimeError(f"connection refused: {_SENTINEL}")
    advisories = _run_assemble(gap_exc=exc)

    gap_advisories = [a for a in advisories if a.get("key") == "gap_analysis_error"]
    assert len(gap_advisories) == 1, "Expected exactly one gap_analysis_error advisory"

    text = gap_advisories[0]["text"]
    assert _SENTINEL not in text, (
        f"Raw exception detail leaked into advisory text: {text!r}"
    )
    assert str(exc) not in text, (
        f"Raw exception string leaked into advisory text: {text!r}"
    )


# AC2 — training_verdict exception produces a fixed text, not the raw exc message
def test_training_verdict_error_advisory_text_is_fixed():
    exc = RuntimeError(f"authentication failed: {_SENTINEL}")
    advisories = _run_assemble(verdict_exc=exc)

    verdict_advisories = [
        a for a in advisories if a.get("key") == "training_verdict_error"
    ]
    assert len(verdict_advisories) == 1, "Expected exactly one training_verdict_error advisory"

    text = verdict_advisories[0]["text"]
    assert _SENTINEL not in text, (
        f"Raw exception detail leaked into advisory text: {text!r}"
    )
    assert str(exc) not in text, (
        f"Raw exception string leaked into advisory text: {text!r}"
    )


# AC3 — no advisory's text field contains the raw exception string
def test_no_advisory_leaks_raw_exc():
    gap_exc = RuntimeError(f"gap-{_SENTINEL}")
    verdict_exc = RuntimeError(f"verdict-{_SENTINEL}")

    advisories = _run_assemble(gap_exc=gap_exc, verdict_exc=verdict_exc)

    for advisory in advisories:
        text = advisory.get("text", "")
        assert _SENTINEL not in text, (
            f"Raw exception detail leaked in advisory {advisory['key']!r}: {text!r}"
        )
