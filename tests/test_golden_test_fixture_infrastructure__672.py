"""Tests for issue #672: Golden test fixture infrastructure for workout metrics.

This file focuses on the technical acceptance criteria and infrastructure validation,
complementing test_golden_workout_fixture__672.py which checks structural completeness.

Acceptance criteria covered:
  AC1  — fixture exists with realistic data (≥3 laps, required streams, ≥20 min duration)
  AC2  — expected-outputs file has required schema (np with formula_version, tss, detected_profile)
  AC3  — meta/comment block documents fixture source and verification
  AC4  — functional metric assertions via test_golden_metrics__577.py
  AC5  — placeholder fields handled without crashes
  AC6  — regeneration docs exist with peer-review requirement
  AC7  — CI workflow runs on PRs and fails on regressions
  AC8  — fixture is realistic (varied pace, varied power, edge case handling)
"""

import json
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run.json"
EXPECTED_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run_expected.json"
REGEN_DOC_PATH = REPO_ROOT / "docs" / "REGENERATING_GOLDEN.md"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "golden-metrics.yml"


@pytest.fixture(scope="module")
def golden_run():
    """Load the static golden run fixture."""
    with FIXTURE_PATH.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_expected():
    """Load the hand-verified expected-outputs file."""
    with EXPECTED_PATH.open() as f:
        return json.load(f)


# ── AC1: Fixture completeness ─────────────────────────────────────────────────

def test_ac1_fixture_file_exists():
    """AC1: Fixture file must exist at tests/fixtures/golden_run.json."""
    assert FIXTURE_PATH.exists(), f"Missing fixture: {FIXTURE_PATH}"


def test_ac1_fixture_has_at_least_three_laps(golden_run):
    """AC1: Fixture must contain at least 3 laps for varied-effort testing."""
    laps = golden_run.get("laps", [])
    assert len(laps) >= 3, f"Expected ≥3 laps, got {len(laps)}"


def test_ac1_fixture_has_required_stream_channels(golden_run):
    """AC1: Fixture must include time, distance, HR, pace, and cadence streams."""
    streams = golden_run.get("streams", {})
    required = {"time_offset_seconds", "power_w", "heart_rate_bpm",
                "cadence_spm", "pace_seconds_per_km"}
    missing = required - set(streams.keys())
    assert not missing, f"Missing stream channels: {missing}"


def test_ac1_fixture_duration_at_least_twenty_minutes(golden_run):
    """AC1: Fixture must represent a realistic workout ≥20 minutes."""
    duration_seconds = golden_run.get("metadata", {}).get("duration_seconds", 0)
    assert duration_seconds >= 1200, (
        f"Duration {duration_seconds}s ({duration_seconds/60:.0f} min) is < 20 min"
    )


# ── AC2: Expected-outputs schema ──────────────────────────────────────────────

def test_ac2_expected_file_exists():
    """AC2: Expected-outputs file must exist at tests/fixtures/golden_run_expected.json."""
    assert EXPECTED_PATH.exists(), f"Missing expected-outputs: {EXPECTED_PATH}"


def test_ac2_normalized_power_has_value_and_formula_version(golden_expected):
    """AC2: normalized_power entry must have a non-null value and formula_version."""
    np_entry = golden_expected.get("normalized_power", {})
    assert "value" in np_entry, "normalized_power missing 'value' field"
    assert np_entry["value"] is not None, "normalized_power.value must not be null"
    assert "formula_version" in np_entry, (
        "normalized_power must include 'formula_version' to document which "
        "algorithm produced the stored value"
    )
    assert np_entry["formula_version"], "formula_version must not be empty"


def test_ac2_tss_and_detected_profile_entries_exist(golden_expected):
    """AC2: Both tss and detected_profile keys must exist (may be placeholder or implemented)."""
    assert "tss" in golden_expected, "expected-outputs must have a 'tss' key"
    assert "detected_profile" in golden_expected, (
        "expected-outputs must have a 'detected_profile' key"
    )


# ── AC3: Meta/comment documentation ───────────────────────────────────────────

def test_ac3_expected_has_meta_or_comment_block(golden_expected):
    """AC3: Expected-outputs must have a top-level meta or comment block."""
    has_comment = "_comment" in golden_expected
    has_meta = "meta" in golden_expected
    assert has_comment or has_meta, (
        "golden_run_expected.json must include a '_comment' or 'meta' block "
        "documenting the fixture source (device, date, verification steps)"
    )


def test_ac3_meta_mentions_verification(golden_expected):
    """AC3: The meta/comment block must mention manual verification."""
    comment_text = (
        golden_expected.get("_comment", "") or
        str(golden_expected.get("meta", ""))
    )
    has_verification = "verif" in comment_text.lower() or "hand" in comment_text.lower()
    assert has_verification, (
        "The meta/comment block must mention manual verification "
        "to establish an audit trail"
    )


# ── AC5: Placeholder handling ─────────────────────────────────────────────────

def test_ac5_tss_entry_safe_to_access(golden_expected):
    """AC5: tss entry must be safe to access regardless of null/implemented state."""
    entry = golden_expected.get("tss")
    assert entry is not None, "tss entry must exist"
    # Entry may be {value: null, ...} or {value: integer, ...}
    if isinstance(entry, dict):
        value = entry.get("value")
        assert value is None or isinstance(value, (int, float)), (
            f"tss.value must be null or numeric; got {type(value)}"
        )


def test_ac5_detected_profile_entry_safe_to_access(golden_expected):
    """AC5: detected_profile entry must be safe to access."""
    entry = golden_expected.get("detected_profile")
    assert entry is not None, "detected_profile entry must exist"
    assert isinstance(entry, dict), "detected_profile must be a JSON object"


# ── AC6: Regeneration documentation ───────────────────────────────────────────

def test_ac6_regenerating_doc_exists():
    """AC6: docs/REGENERATING_GOLDEN.md must exist and be complete."""
    assert REGEN_DOC_PATH.exists(), (
        f"Missing regeneration guide: {REGEN_DOC_PATH}"
    )


def test_ac6_regen_doc_has_command():
    """AC6: Doc must include the exact regeneration command."""
    text = REGEN_DOC_PATH.read_text()
    has_make = "regen-golden" in text
    has_script = "regen_golden.py" in text
    assert has_make or has_script, (
        "REGENERATING_GOLDEN.md must include the command to regenerate "
        "(e.g. `make regen-golden` or `python scripts/regen_golden.py`)"
    )


def test_ac6_regen_doc_requires_peer_review():
    """AC6: Doc must require peer review of new expected values."""
    text = REGEN_DOC_PATH.read_text()
    has_review_req = any(
        word in text.lower()
        for word in ("second engineer", "peer", "review", "manual verify")
    )
    assert has_review_req, (
        "REGENERATING_GOLDEN.md must explain that a second engineer "
        "must manually verify new expected values"
    )


# ── AC7: CI workflow gate ─────────────────────────────────────────────────────

def test_ac7_ci_workflow_exists():
    """AC7: .github/workflows/golden-metrics.yml must exist."""
    assert CI_WORKFLOW_PATH.exists(), (
        f"Missing CI workflow: {CI_WORKFLOW_PATH}"
    )


def test_ac7_ci_workflow_triggers_on_pull_request():
    """AC7: Workflow must trigger on pull_request events."""
    import yaml

    with CI_WORKFLOW_PATH.open() as f:
        workflow = yaml.safe_load(f)

    # PyYAML parses `on:` as True; check both key forms
    triggers = workflow.get("on") or workflow.get(True) or {}
    if isinstance(triggers, bool):
        triggers = {}

    assert "pull_request" in triggers, (
        "golden-metrics.yml must trigger on pull_request"
    )


def test_ac7_ci_workflow_runs_tests():
    """AC7: Workflow must run pytest on the golden tests."""
    text = CI_WORKFLOW_PATH.read_text()
    assert "pytest" in text, "CI workflow must run pytest"


def test_ac7_ci_does_not_suppress_failures():
    """AC7: Workflow must fail on regression (no || true suppression)."""
    text = CI_WORKFLOW_PATH.read_text()
    has_suppress = "|| true" in text or "|| exit 0" in text
    assert not has_suppress, (
        "CI workflow must not suppress test failures with '|| true' or '|| exit 0'"
    )


# ── AC8: Fixture realism ──────────────────────────────────────────────────────

def test_ac8_fixture_has_varied_pace(golden_run):
    """AC8: Laps must show meaningfully varied pace (≥10% variation)."""
    laps = golden_run.get("laps", [])
    if not laps:
        pytest.skip("No laps to validate")

    paces = [lap.get("avg_pace_seconds_per_km", 0) for lap in laps]
    paces = [p for p in paces if p > 0]
    if len(paces) < 2:
        pytest.skip("Insufficient pace data")

    slowest = max(paces)
    fastest = min(paces)
    variation = (slowest - fastest) / slowest if slowest > 0 else 0
    assert variation >= 0.10, (
        f"Pace variation {variation:.1%} is too small; "
        "fixture should have ≥10% variation across laps"
    )


def test_ac8_fixture_has_varied_power(golden_run):
    """AC8: Laps must show varied power output (≥10% variation)."""
    laps = golden_run.get("laps", [])
    if not laps:
        pytest.skip("No laps to validate")

    powers = [lap.get("avg_power_w", 0) for lap in laps]
    powers = [p for p in powers if p > 0]
    if len(powers) < 2:
        pytest.skip("Insufficient power data")

    min_power = min(powers)
    max_power = max(powers)
    variation = max_power / min_power if min_power > 0 else 0
    assert variation >= 1.10, (
        f"Power variation ratio {variation:.2f} is too small; "
        "fixture should have ≥10% variation across laps"
    )


def test_ac8_fixture_documents_edge_cases(golden_run):
    """AC8: Fixture should handle edge cases (zero-cadence) or document why absent."""
    metadata = golden_run.get("metadata", {})
    description = metadata.get("description", "").lower()
    cadence_stream = golden_run.get("streams", {}).get("cadence_spm", [])

    has_zero_cadence = any(v == 0 for v in cadence_stream)
    documents_continuous = any(
        word in description for word in ("continuous", "no rest", "threshold")
    )

    assert has_zero_cadence or documents_continuous, (
        "Fixture should either include a zero-cadence segment or document "
        "why it's absent (e.g., 'continuous threshold run')"
    )
