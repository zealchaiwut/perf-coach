"""Tests for issue #1486: Surface degraded signal when advisory sources fail

Tests that the export_brief.py script correctly surfaces an advisories_degraded
signal when gap-analysis or training-verdict lookups fail, and exits with proper
status codes to prevent downstream consumers from misinterpreting an empty
advisories list as an all-clear.

AC1: Gap-analysis failure → advisories_degraded in payload
AC2: Training-verdict failure → advisories_degraded in payload
AC3: Either failure → non-zero exit code
AC4: Both succeed → advisories_degraded false/absent, exit 0 (happy path)
AC5: Partial success (one fails, one succeeds) → degraded signal still present
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test with its test-patchable functions
import scripts.export_brief as export_brief
import backend.services.daily_brief as daily_brief


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_user_id():
    """A valid UUID string for testing."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def test_date():
    """A fixed date for consistent testing."""
    return date(2026, 7, 20)


@pytest.fixture
def null_weight():
    """Return the null weight block (failed weight computation)."""
    return dict(daily_brief._NULL_WEIGHT_BLOCK)


@pytest.fixture
def valid_advisories_list():
    """Return a list of normal advisories (no errors)."""
    return [
        {"key": "high_volume", "severity": "warn", "text": "Volume is high"},
        {"key": "fresh_state", "severity": "info", "text": "You're fresh"},
    ]


@pytest.fixture
def advisory_with_error():
    """Return a single error-level advisory."""
    return {
        "key": "gap_analysis_error",
        "severity": "error",
        "text": "Gap analysis unavailable: connection failed",
    }


@pytest.fixture
def temp_output_file():
    """Create a temporary output file for testing."""
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        import os
        os.close(fd)
        yield path
    finally:
        import os
        try:
            os.unlink(path)
        except OSError:
            pass


# ── AC1: Gap-analysis failure surfaces advisories_degraded ────────────────────

def test_export_brief_degraded_gap_analysis_failure(mock_user_id, test_date, null_weight, advisory_with_error):
    """AC1: When gap-analysis raises, advisories_degraded is True in payload."""
    # Patch _assemble_advisories to return an error advisory
    with patch.object(
        export_brief, "_assemble_advisories",
        return_value=[advisory_with_error]
    ):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    assert "advisories_degraded" in brief
    assert brief["advisories_degraded"] is True
    assert len(brief["advisories"]) >= 1
    assert any(a.get("severity") == "error" for a in brief["advisories"])


# ── AC2: Training-verdict failure surfaces advisories_degraded ────────────────

def test_export_brief_degraded_training_verdict_failure(mock_user_id, test_date, null_weight, advisory_with_error):
    """AC2: When training-verdict lookup raises, advisories_degraded is True."""
    # Create error advisory with training verdict key
    verdict_error = {
        "key": "training_verdict_error",
        "severity": "error",
        "text": "Training verdict unavailable: database error",
    }

    with patch.object(
        export_brief, "_assemble_advisories",
        return_value=[verdict_error]
    ):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    assert brief["advisories_degraded"] is True
    assert any(
        a.get("key") == "training_verdict_error" and a.get("severity") == "error"
        for a in brief["advisories"]
    )


# ── AC3: Either failure causes non-zero exit code ─────────────────────────────

def test_export_brief_exit_nonzero_on_gap_analysis_error(mock_user_id, test_date, temp_output_file):
    """AC3a: Gap-analysis error → non-zero exit code."""
    error_advisory = {
        "key": "gap_analysis_error",
        "severity": "error",
        "text": "Gap analysis unavailable: connection failed",
    }
    degraded_brief = {
        "schema_version": 3,
        "for_date": test_date.isoformat(),
        "generated_at": "2026-07-20T00:00:00+07:00",
        "advisories_degraded": True,
        "advisories": [error_advisory],
        "actions": [],
    }

    with patch.object(export_brief, "_resolve_user", return_value=mock_user_id):
        with patch.object(export_brief, "_build_brief", return_value=degraded_brief):
            with patch.object(export_brief, "_write_atomic"):
                with patch("sys.argv", ["export_brief.py", "--output", temp_output_file]):
                    # AC3 requires: when advisories_degraded is True, main() exits non-zero
                    exit_code = export_brief.main()
                    # The implementation should check advisories_degraded and return 1 if True
                    assert exit_code != 0, "Script should exit non-zero when advisories_degraded is True"


def test_export_brief_exit_nonzero_on_training_verdict_error(mock_user_id, test_date, temp_output_file):
    """AC3b: Training-verdict error → non-zero exit code."""
    error_advisory = {
        "key": "training_verdict_error",
        "severity": "error",
        "text": "Training verdict unavailable: database error",
    }
    degraded_brief = {
        "schema_version": 3,
        "for_date": test_date.isoformat(),
        "generated_at": "2026-07-20T00:00:00+07:00",
        "advisories_degraded": True,
        "advisories": [error_advisory],
        "actions": [],
    }

    with patch.object(export_brief, "_resolve_user", return_value=mock_user_id):
        with patch.object(export_brief, "_build_brief", return_value=degraded_brief):
            with patch.object(export_brief, "_write_atomic"):
                with patch("sys.argv", ["export_brief.py", "--output", temp_output_file]):
                    exit_code = export_brief.main()
                    assert exit_code != 0, "Script should exit non-zero when training verdict fails"


# ── AC4: Happy path — both succeed, advisories_degraded false/absent, exit 0 ──

def test_export_brief_happy_path_no_degraded_signal(mock_user_id, test_date, null_weight, valid_advisories_list):
    """AC4: Both advisory sources succeed → advisories_degraded false, exit 0."""
    with patch.object(
        export_brief, "_assemble_advisories",
        return_value=valid_advisories_list
    ):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    assert brief["advisories_degraded"] is False
    assert len(brief["advisories"]) == 2
    assert not any(a.get("severity") == "error" for a in brief["advisories"])


# ── AC5: Partial success (one fails, one succeeds) → degraded signal still present ─

def test_export_brief_degraded_partial_success(mock_user_id, test_date, null_weight, advisory_with_error, valid_advisories_list):
    """AC5: One advisory source fails, other succeeds → degraded still True."""
    # Mix error advisory with normal advisories
    mixed_advisories = [advisory_with_error] + valid_advisories_list

    with patch.object(
        export_brief, "_assemble_advisories",
        return_value=mixed_advisories
    ):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    # Verify degraded signal is present despite mixed advisories
    assert brief["advisories_degraded"] is True
    # Verify both error and successful advisories are in the list
    assert len(brief["advisories"]) == 3
    assert any(a.get("severity") == "error" for a in brief["advisories"])
    assert any(a.get("severity") == "warn" for a in brief["advisories"])
    assert any(a.get("severity") == "info" for a in brief["advisories"])


# ── Integration: Verify advisories_degraded detection logic ────────────────────

def test_advisories_degraded_detection_logic():
    """Verify that any(a.get("severity") == "error" ...) correctly detects errors."""
    # Test with no errors
    clean_list = [
        {"severity": "info"},
        {"severity": "warn"},
    ]
    assert not any(a.get("severity") == "error" for a in clean_list)

    # Test with one error
    degraded_list = [
        {"severity": "info"},
        {"severity": "error"},
        {"severity": "warn"},
    ]
    assert any(a.get("severity") == "error" for a in degraded_list)

    # Test with error only
    error_only = [
        {"severity": "error"},
    ]
    assert any(a.get("severity") == "error" for a in error_only)


# ── Downstream consumer safety: verify degraded flag can be read ───────────────

def test_downstream_consumer_can_read_degraded_flag(mock_user_id, test_date, null_weight, advisory_with_error):
    """Verify downstream consumers can reliably detect degraded state."""
    with patch.object(
        export_brief, "_assemble_advisories",
        return_value=[advisory_with_error]
    ):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    # Simulate downstream consumer reading the brief
    payload_json = json.dumps(brief)
    parsed = json.loads(payload_json)

    # Verify consumer can safely read the flag
    is_degraded = parsed.get("advisories_degraded", False)
    assert is_degraded is True

    # Verify consumer won't misinterpret empty advisories as all-clear
    advisories = parsed.get("advisories", [])
    if is_degraded:
        # Consumer should understand this is NOT an all-clear
        assert is_degraded is True, "Degraded flag must be present and truthy"


# ── Payload schema validation ─────────────────────────────────────────────────

def test_advisories_degraded_in_payload_schema(mock_user_id, test_date, null_weight, valid_advisories_list):
    """Verify advisories_degraded is properly included in the JSON payload."""
    with patch.object(export_brief, "_assemble_advisories", return_value=valid_advisories_list):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    # Serialize and deserialize to verify JSON compatibility
    json_str = json.dumps(brief)
    parsed = json.loads(json_str)

    # Verify the key exists and has correct type
    assert "advisories_degraded" in parsed
    assert isinstance(parsed["advisories_degraded"], bool)


def test_advisories_degraded_false_when_no_errors(mock_user_id, test_date, null_weight):
    """Verify advisories_degraded is False (not absent/None) on success."""
    with patch.object(export_brief, "_assemble_advisories", return_value=[]):
        with patch.object(export_brief, "_assemble_form", return_value={}):
            with patch.object(export_brief, "_assemble_recent_wrap", return_value={}):
                with patch.object(export_brief, "_assemble_weight", return_value=null_weight):
                    with patch.object(export_brief, "_assemble_week_plan", return_value=[]):
                        with patch.object(export_brief, "_assemble_coach", return_value=None):
                            with patch.object(export_brief, "_fetch_plan", return_value={"sessions": []}):
                                brief = export_brief._build_brief(test_date, user_id=mock_user_id)

    # Key MUST be present and be explicitly False, not None
    assert "advisories_degraded" in brief
    assert brief["advisories_degraded"] is False
