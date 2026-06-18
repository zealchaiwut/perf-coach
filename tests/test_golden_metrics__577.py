"""Golden fixture regression tests for workout metrics (issue #577).

Acceptance criteria covered:
  AC-fixture      — tests/fixtures/golden_run.json exists and is well-formed
  AC-expected     — tests/fixtures/golden_run_expected.json exists w/ required keys
  AC-np-value     — normalized_power result matches expected within ±0.01
  AC-np-exact     — final_value matches expected within ±0.1% relative tolerance
  AC-tss          — tss matches expected value and method (implemented in issue #582)
  AC-profile-skip — detected_profile placeholder skipped with future-ticket note
  AC-regression   — a deliberate mutation to the formula produces a detectable diff
"""

import json
import pathlib
import types

import pytest

from backend.services.normalized_power import compute_normalized_power

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURE_PATH = FIXTURES_DIR / "golden_run.json"
EXPECTED_PATH = FIXTURES_DIR / "golden_run_expected.json"


# ── Fixture loading helpers ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def golden_run():
    """Load and return the static golden run fixture."""
    with FIXTURE_PATH.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_expected():
    """Load and return the hand-verified expected-outputs file."""
    with EXPECTED_PATH.open() as f:
        return json.load(f)


# ── AC-fixture: fixture file is well-formed ──────────────────────────────────


def test_fixture_file_exists():
    """AC-fixture: tests/fixtures/golden_run.json must exist."""
    assert FIXTURE_PATH.exists(), f"Missing fixture: {FIXTURE_PATH}"


def test_fixture_has_metadata(golden_run):
    """AC-fixture: fixture contains a metadata block with required keys."""
    meta = golden_run["metadata"]
    assert meta["duration_seconds"] >= 1800, "duration should be ≥ 30 minutes"
    assert meta["duration_seconds"] <= 5400, "duration should be ≤ 90 minutes"
    assert meta["sample_interval_seconds"] > 0


def test_fixture_has_at_least_three_laps(golden_run):
    """AC-fixture: fixture must have at least 3 laps."""
    assert len(golden_run["laps"]) >= 3


def test_fixture_power_stream_non_empty(golden_run):
    """AC-fixture: power_w stream must be present and non-empty."""
    pw = golden_run["streams"]["power_w"]
    assert len(pw) > 0


def test_fixture_streams_present(golden_run):
    """AC-fixture: streams block must include time, power, HR, cadence, pace."""
    streams = golden_run["streams"]
    for key in ("time_offset_seconds", "power_w", "heart_rate_bpm",
                "cadence_spm", "pace_seconds_per_km"):
        assert key in streams, f"missing stream channel: {key}"


def test_fixture_no_zeroed_streams(golden_run):
    """AC-fixture: no stream channel should be all zeros (synthetic data check)."""
    for channel, values in golden_run["streams"].items():
        if channel == "time_offset_seconds":
            continue
        assert any(v != 0 for v in values), f"stream '{channel}' appears zeroed-out"


def test_fixture_power_stream_length_matches_duration(golden_run):
    """AC-fixture: power stream length must equal duration_seconds (1 Hz recording)."""
    duration = golden_run["metadata"]["duration_seconds"]
    interval = golden_run["metadata"]["sample_interval_seconds"]
    expected_length = duration // interval
    actual_length = len(golden_run["streams"]["power_w"])
    assert actual_length == expected_length, (
        f"Expected {expected_length} power samples for {duration}s at "
        f"{interval}s/sample, got {actual_length}"
    )


# ── AC-expected: expected-outputs file is well-formed ────────────────────────


def test_expected_file_exists():
    """AC-expected: tests/fixtures/golden_run_expected.json must exist."""
    assert EXPECTED_PATH.exists(), f"Missing expected-outputs file: {EXPECTED_PATH}"


def test_expected_has_normalized_power_key(golden_expected):
    """AC-expected: expected-outputs must have a non-null 'normalized_power' entry."""
    assert "normalized_power" in golden_expected
    assert golden_expected["normalized_power"]["value"] is not None


def test_expected_has_tss_entry(golden_expected):
    """AC-expected: 'tss' key with a non-null value must exist (implemented in issue #582)."""
    assert "tss" in golden_expected
    entry = golden_expected["tss"]
    assert entry.get("value") is not None, (
        "tss.value must not be null — TSS is now implemented (issue #582). "
        "Run scripts/regen_golden.py to regenerate the expected value."
    )
    assert isinstance(entry["value"], int), "tss.value must be a whole integer"
    assert "method" in entry, "tss entry must include 'method' field"


def test_expected_has_detected_profile_placeholder(golden_expected):
    """AC-expected: 'detected_profile' key with null and placeholder note exists."""
    assert "detected_profile" in golden_expected
    entry = golden_expected["detected_profile"]
    assert entry["value"] is None
    assert "PLACEHOLDER" in entry.get("placeholder_note", ""), (
        "detected_profile entry must have 'placeholder_note' with word PLACEHOLDER"
    )


# ── AC-np-value: normalized_power matches expected ───────────────────────────


def test_normalized_power_matches_expected_value(golden_run, golden_expected):
    """AC-np-value: compute_normalized_power on fixture matches expected ±0.01.

    Tolerance: normalized_power is returned as rounded integer (watts).
    Absolute tolerance ±0.01 on integer is effectively exact equality —
    any formula change shifting rounded result by ≥1 W will fail this test.
    """
    power_stream = golden_run["streams"]["power_w"]
    sample_interval = golden_run["metadata"]["sample_interval_seconds"]
    expected_np = golden_expected["normalized_power"]["value"]
    tolerance = golden_expected["normalized_power"]["tolerance"]

    np_val, _ = compute_normalized_power(power_stream, sample_interval)

    assert np_val is not None, (
        "compute_normalized_power returned None — fixture data may be too short"
    )
    assert abs(np_val - expected_np) <= tolerance, (
        f"normalized_power mismatch: got {np_val}, expected {expected_np} "
        f"(tolerance ±{tolerance}). "
        "If intentional, regenerate via `make regen-golden` and get peer review."
    )


def test_normalized_power_final_value_within_relative_tolerance(
    golden_run, golden_expected
):
    """AC-np-exact: unrounded final_value matches expected within ±0.1% relative.

    Tolerance: ±0.1% relative covers floating-point implementation drift
    across Python versions without masking a real formula change.
    """
    power_stream = golden_run["streams"]["power_w"]
    sample_interval = golden_run["metadata"]["sample_interval_seconds"]
    expected_final = golden_expected["normalized_power"]["final_value_exact"]
    rel_tol = golden_expected["normalized_power"]["final_value_tolerance_relative"]

    _, info = compute_normalized_power(power_stream, sample_interval)

    actual_final = info["final_value"]
    relative_diff = abs(actual_final - expected_final) / expected_final
    assert relative_diff <= rel_tol, (
        f"final_value relative diff {relative_diff:.6f} exceeds ±{rel_tol} "
        f"(got {actual_final:.6f}, expected {expected_final:.6f})"
    )


def test_normalized_power_is_integer(golden_run):
    """AC-np-value: compute_normalized_power must return an int, not a float."""
    power_stream = golden_run["streams"]["power_w"]
    sample_interval = golden_run["metadata"]["sample_interval_seconds"]
    np_val, _ = compute_normalized_power(power_stream, sample_interval)
    assert isinstance(np_val, int), f"Expected int, got {type(np_val)}"


# ── AC-tss: TSS matches expected value (implemented in issue #582) ────────────


def test_tss_matches_expected(golden_run, golden_expected):
    """AC-tss: compute_running_tss on the golden fixture matches the hand-verified expected value.

    Uses the fixture_prefs recorded in golden_run_expected.json so the test is
    deterministic: ftp_w=280, threshold_pace=300, threshold_hr=170.  The power
    method wins because NP is available; expected TSS=69.
    """
    from backend.services.tss import compute_running_tss

    tss_section = golden_expected.get("tss", {})
    expected_value = tss_section.get("value")
    expected_method = tss_section.get("method")
    fixture_prefs = tss_section.get("fixture_prefs", {})

    if expected_value is None:
        pytest.skip("tss.value is still a placeholder in golden_run_expected.json")

    from backend.services.normalized_power import compute_normalized_power
    power_stream = golden_run["streams"]["power_w"]
    sample_interval = golden_run["metadata"]["sample_interval_seconds"]
    np_val, _ = compute_normalized_power(power_stream, sample_interval)

    laps = golden_run.get("laps", [])
    splits = [
        types.SimpleNamespace(
            duration_seconds=lap["duration_seconds"],
            distance_km=lap["distance_km"],
            avg_hr=round(lap["avg_hr_bpm"]) if "avg_hr_bpm" in lap else None,
        )
        for lap in laps
    ]
    workout = types.SimpleNamespace(
        np=np_val,
        avg_hr=None,
        distance_km=golden_run["metadata"]["total_distance_km"],
        duration_seconds=golden_run["metadata"]["duration_seconds"],
    )
    prefs = types.SimpleNamespace(
        ftp_w=fixture_prefs.get("ftp_w"),
        threshold_pace_seconds_per_km=fixture_prefs.get("threshold_pace_seconds_per_km"),
        threshold_hr=fixture_prefs.get("threshold_hr"),
    )

    result = compute_running_tss(workout, splits, prefs)

    assert result["tss"] == expected_value, (
        f"golden fixture TSS mismatch: got {result['tss']}, expected {expected_value}. "
        "Regenerate expected-outputs via `make regen-golden` after an intentional formula change."
    )
    assert result["method"] == expected_method, (
        f"golden fixture method mismatch: got {result['method']!r}, expected {expected_method!r}"
    )
    assert isinstance(result["tss"], int), "TSS must be a whole integer"


# ── AC-profile-skip: detected_profile is not yet implemented ─────────────────


@pytest.mark.skip(
    reason=(
        "Workout profile detection not yet implemented — "
        "see placeholder in golden_run_expected.json "
        "(PLACEHOLDER: implement in [ticket reference — workout profile detection])"
    )
)
def test_detected_profile_matches_expected(golden_run, golden_expected):
    """AC-profile-skip: placeholder — asserts detected_profile == expected when done."""
    raise NotImplementedError(
        "Workout profile detection not implemented in this sprint"
    )


# ── AC-regression: a formula mutation is detectable ──────────────────────────


def test_formula_mutation_is_detectable(golden_run, golden_expected):
    """AC-regression: deliberately mutating the formula produces a different result.

    This test verifies that the golden test CAN catch a regression — it computes
    NP with a modified power stream (every value scaled up by 10%) and confirms
    the result differs from the expected value. If the test suite could not detect
    formula changes, the golden fixture would be useless.
    """
    power_stream = golden_run["streams"]["power_w"]
    sample_interval = golden_run["metadata"]["sample_interval_seconds"]
    expected_np = golden_expected["normalized_power"]["value"]

    # Simulate a formula mutation: scale all power values up by 10%
    mutated_stream = [p * 1.10 for p in power_stream]
    mutated_np, _ = compute_normalized_power(mutated_stream, sample_interval)

    assert mutated_np != expected_np, (
        "Scaling power by 10% should produce a different NP — "
        "if this assertion fails, the golden test cannot detect formula mutations."
    )
