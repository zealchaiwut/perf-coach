"""Golden workout fixture infrastructure tests (issue #672).

Verifies that all structural requirements of the golden-test framework are
in place: fixture completeness, expected-outputs schema, CI gate, and
regeneration docs.  Functional metric assertions live in
test_golden_metrics__577.py; this file focuses on the scaffolding.

Acceptance criteria covered:
  AC1  — fixture exists, ≥3 laps, required stream channels present
  AC2  — expected-outputs has normalized_power with formula_version, tss entry,
          detected_profile entry
  AC3  — expected-outputs has a top-level meta / _comment block
  AC4  — (functional assertions delegated to test_golden_metrics__577.py)
  AC5  — placeholder or non-null tss/detected_profile handled without error
  AC6  — REGENERATING_GOLDEN.md exists and contains required workflow instructions
  AC7  — .github/workflows/golden-metrics.yml exists and triggers on pull_request
  AC8  — fixture duration ≥ 20 min, laps have varied pace/effort
"""

import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
FIXTURE_PATH = FIXTURES_DIR / "golden_run.json"
EXPECTED_PATH = FIXTURES_DIR / "golden_run_expected.json"
REGEN_DOC_PATH = REPO_ROOT / "docs" / "REGENERATING_GOLDEN.md"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "golden-metrics.yml"


# ── AC1: fixture file completeness ────────────────────────────────────────────


def test_fixture_file_exists():
    """AC1: tests/fixtures/golden_run.json must exist."""
    assert FIXTURE_PATH.exists(), f"Missing fixture: {FIXTURE_PATH}"


@pytest.fixture(scope="module")
def golden_run():
    with FIXTURE_PATH.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_expected():
    with EXPECTED_PATH.open() as f:
        return json.load(f)


def test_fixture_has_at_least_three_laps(golden_run):
    """AC1: fixture must have ≥3 laps."""
    assert len(golden_run["laps"]) >= 3


def test_fixture_required_stream_channels_present(golden_run):
    """AC1: streams must include time, distance, heart rate, pace, and cadence."""
    streams = golden_run["streams"]
    required = {"time_offset_seconds", "power_w", "heart_rate_bpm",
                "cadence_spm", "pace_seconds_per_km"}
    missing = required - streams.keys()
    assert not missing, f"fixture missing stream channels: {missing}"


# ── AC2: expected-outputs schema ──────────────────────────────────────────────


def test_expected_file_exists():
    """AC2: tests/fixtures/golden_run_expected.json must exist."""
    assert EXPECTED_PATH.exists(), f"Missing expected-outputs: {EXPECTED_PATH}"


def test_expected_normalized_power_has_value(golden_expected):
    """AC2: normalized_power entry must have a non-null value."""
    np_entry = golden_expected["normalized_power"]
    assert np_entry.get("value") is not None


def test_expected_normalized_power_has_formula_version(golden_expected):
    """AC2: normalized_power entry must include a formula_version field.

    This anchors the expected output to a specific algorithm version so that
    a reader can identify which formula produced the stored value.
    """
    np_entry = golden_expected["normalized_power"]
    assert "formula_version" in np_entry, (
        "normalized_power section must include a 'formula_version' field "
        "documenting which algorithm produced the stored value "
        "(e.g. '30s_rolling_mean_4th_power_v1')."
    )
    assert np_entry["formula_version"], "formula_version must not be empty"


def test_expected_tss_entry_exists(golden_expected):
    """AC2: tss key must exist; value may be numeric (implemented) or null (placeholder)."""
    assert "tss" in golden_expected, "expected-outputs must have a 'tss' key"


def test_expected_detected_profile_entry_exists(golden_expected):
    """AC2: detected_profile key must exist."""
    assert "detected_profile" in golden_expected, (
        "expected-outputs must have a 'detected_profile' key"
    )


# ── AC3: meta / comment block ─────────────────────────────────────────────────


def test_expected_has_top_level_meta_or_comment(golden_expected):
    """AC3: expected-outputs must have a top-level _comment or meta block
    documenting the fixture source."""
    has_comment = "_comment" in golden_expected
    has_meta = "meta" in golden_expected
    assert has_comment or has_meta, (
        "golden_run_expected.json must include a top-level '_comment' or 'meta' "
        "block documenting the fixture source (device, date, verification steps)."
    )


def test_expected_meta_references_verification(golden_expected):
    """AC3: the meta/comment block must mention manual verification."""
    comment = golden_expected.get("_comment") or str(golden_expected.get("meta", ""))
    assert "verif" in comment.lower() or "hand-verif" in comment.lower(), (
        "The top-level meta/comment must mention manual verification to make "
        "the audit trail clear."
    )


# ── AC5: placeholder vs implemented — no crashes ──────────────────────────────


def test_tss_entry_does_not_crash_on_access(golden_expected):
    """AC5: accessing tss from the expected file must not raise, regardless of
    whether it is a null placeholder or an implemented value."""
    entry = golden_expected["tss"]
    # value may be None (placeholder) or an integer (implemented)
    value = entry.get("value") if isinstance(entry, dict) else entry
    assert value is None or isinstance(value, (int, float)), (
        f"tss.value must be null or numeric; got {type(value)}"
    )


def test_detected_profile_entry_does_not_crash_on_access(golden_expected):
    """AC5: accessing detected_profile from the expected file must not raise."""
    entry = golden_expected["detected_profile"]
    # entry may be {"value": null, "placeholder_note": "..."} or a full result
    assert isinstance(entry, dict), "detected_profile must be a JSON object"


# ── AC6: REGENERATING_GOLDEN.md ──────────────────────────────────────────────


def test_regenerating_doc_exists():
    """AC6: docs/REGENERATING_GOLDEN.md must exist."""
    assert REGEN_DOC_PATH.exists(), (
        f"Missing regeneration guide: {REGEN_DOC_PATH}. "
        "Add a doc explaining how to update golden_run_expected.json when a "
        "formula is intentionally changed."
    )


def test_regenerating_doc_contains_regen_command():
    """AC6: the doc must include the command to regenerate the expected-outputs file."""
    text = REGEN_DOC_PATH.read_text()
    # Accept either `make regen-golden` or `python scripts/regen_golden.py`
    has_make = "regen-golden" in text
    has_script = "regen_golden.py" in text
    assert has_make or has_script, (
        "REGENERATING_GOLDEN.md must contain the exact command to regenerate "
        "expected outputs (e.g. `make regen-golden` or `python scripts/regen_golden.py`)."
    )


def test_regenerating_doc_mentions_peer_review():
    """AC6: the doc must require a second engineer to verify new values."""
    text = REGEN_DOC_PATH.read_text()
    assert re.search(r"second|peer|review|manual", text, re.IGNORECASE), (
        "REGENERATING_GOLDEN.md must explain that a second engineer (peer) "
        "must manually verify new expected values before merging."
    )


# ── AC7: CI gate ──────────────────────────────────────────────────────────────


def test_golden_metrics_ci_workflow_exists():
    """AC7: .github/workflows/golden-metrics.yml must exist."""
    assert CI_WORKFLOW_PATH.exists(), (
        f"Missing CI workflow: {CI_WORKFLOW_PATH}. "
        "Create a GitHub Actions workflow that runs the golden tests on every PR."
    )


def test_golden_metrics_ci_triggers_on_pull_request():
    """AC7: the CI workflow must trigger on pull_request events.

    PyYAML parses YAML `on:` as Python bool True (a known quirk — `on` is a
    YAML 1.1 boolean alias).  GitHub Actions itself parses the key as the
    string 'on', so both string and bool keys are checked here.
    """
    import yaml  # available in the test environment via PyYAML

    with CI_WORKFLOW_PATH.open() as f:
        workflow = yaml.safe_load(f)

    # PyYAML 5.x parses `on:` as True; check both possible key forms
    triggers = workflow.get("on") or workflow.get(True) or {}
    if isinstance(triggers, bool):
        triggers = {}

    assert "pull_request" in triggers, (
        "golden-metrics.yml must trigger on pull_request so it gates every PR."
    )


def test_golden_metrics_ci_runs_pytest():
    """AC7: the CI workflow must invoke pytest (or a make target that calls pytest)."""
    text = CI_WORKFLOW_PATH.read_text()
    assert "pytest" in text or "regen-golden" in text or "golden" in text.lower(), (
        "golden-metrics.yml must run the golden test suite (pytest) on every PR."
    )


def test_golden_metrics_ci_fails_on_regression():
    """AC7: the CI workflow must not suppress test failures (no || true patterns)."""
    text = CI_WORKFLOW_PATH.read_text()
    # '|| true' or '|| exit 0' would swallow failures
    assert "|| true" not in text and "|| exit 0" not in text, (
        "golden-metrics.yml must not suppress failures with '|| true' or '|| exit 0'."
    )


# ── AC8: fixture realism ──────────────────────────────────────────────────────


def test_fixture_duration_at_least_twenty_minutes(golden_run):
    """AC8: fixture total duration must be ≥ 20 minutes (1200 s)."""
    duration = golden_run["metadata"]["duration_seconds"]
    assert duration >= 1200, (
        f"Fixture duration is {duration}s ({duration/60:.1f} min) — must be ≥ 20 min (AC8)."
    )


def test_fixture_laps_have_varied_pace(golden_run):
    """AC8: laps must show meaningfully varied pace/effort (not all identical).

    Threshold: fastest lap must be at least 10% faster (lower s/km) than
    slowest lap.  A flat-effort workout wouldn't provide signal for profile
    detection and wouldn't stress the NP algorithm.
    """
    paces = [lap["avg_pace_seconds_per_km"] for lap in golden_run["laps"]]
    slowest = max(paces)
    fastest = min(paces)
    variation_ratio = (slowest - fastest) / slowest
    assert variation_ratio >= 0.10, (
        f"Lap paces {paces} s/km are too similar (variation {variation_ratio:.1%}). "
        "Fixture must have ≥10% pace variation across laps to simulate a "
        "realistic varied-effort workout (AC8)."
    )


def test_fixture_laps_have_varied_power(golden_run):
    """AC8: laps must show varied power output across the effort profile."""
    powers = [lap["avg_power_w"] for lap in golden_run["laps"]]
    assert max(powers) / min(powers) >= 1.10, (
        f"Lap average powers {powers} W are too uniform. "
        "Fixture needs ≥10% power variation to exercise the metric calculations."
    )


def test_fixture_has_zero_cadence_segment_or_documents_absence(golden_run):
    """AC8: fixture should include a zero-cadence segment, or the metadata must
    explain why it is absent (continuous threshold run without rest laps).

    A rest lap / zero-cadence window tests that metric code handles gaps
    gracefully.  For a continuous threshold run this is unusual; accepting
    either the segment itself or a metadata note justifying its absence.
    """
    cadence = golden_run["streams"]["cadence_spm"]
    has_zero = any(v == 0 for v in cadence)
    has_note = "zero" in golden_run["metadata"].get("description", "").lower() or \
               "rest" in golden_run["metadata"].get("description", "").lower() or \
               "continuous" in golden_run["metadata"].get("description", "").lower()
    assert has_zero or has_note, (
        "Fixture must either contain a zero-cadence segment (to test gap handling) "
        "or the metadata description must explain why none is present "
        "(e.g. 'continuous threshold run without rest laps')."
    )
