"""Regenerate tests/fixtures/golden_run_expected.json from the static fixture.

Run this ONLY after an intentional formula change. See docs/REGENERATING_GOLDEN.md
for the full workflow, including the required peer-review step.

Usage:
    python scripts/regen_golden.py [--dry-run]

Options:
    --dry-run   Print the computed values without writing the file.
"""
import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.services.normalized_power import compute_normalized_power  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run.json"
EXPECTED_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run_expected.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print computed values without writing the file.")
    args = parser.parse_args()

    with FIXTURE_PATH.open() as f:
        fixture = json.load(f)

    power_stream = fixture["streams"]["power_w"]
    sample_interval = fixture["metadata"]["sample_interval_seconds"]

    np_val, info = compute_normalized_power(power_stream, sample_interval)
    if np_val is None:
        print(
            f"ERROR: compute_normalized_power returned None: {info['reason']}",
            file=sys.stderr,
        )
        sys.exit(1)

    expected = {
        "_comment": (
            "Hand-verified expected outputs for the golden_run.json fixture "
            "(issue #577). Regenerate ONLY after an intentional formula change "
            "using scripts/regen_golden.py. A second engineer must manually verify "
            "new values before merging. See docs/REGENERATING_GOLDEN.md for the "
            "full regeneration workflow."
        ),
        "normalized_power": {
            "value": np_val,
            "tolerance": 0.01,
            "tolerance_note": (
                "Absolute tolerance of ±0.01 W on the rounded integer result. "
                "Since the result is always an integer, tolerance is exact equality."
            ),
            "final_value_exact": round(info["final_value"], 10),
            "final_value_tolerance_relative": 0.001,
            "final_value_tolerance_note": (
                "±0.1% relative tolerance on the unrounded final_value."
            ),
        },
        "tss": {
            "value": None,
            "placeholder_note": (
                "PLACEHOLDER: implement in [ticket reference — Running TSS "
                "calculation]"
            ),
        },
        "detected_profile": {
            "value": None,
            "placeholder_note": (
                "PLACEHOLDER: implement in [ticket reference — workout profile "
                "detection]"
            ),
        },
    }

    print(f"normalized_power.value        = {np_val}")
    print(f"normalized_power.final_value  = {info['final_value']:.10f}")
    print("tss                           = null (placeholder)")
    print("detected_profile              = null (placeholder)")

    if args.dry_run:
        print("\n[dry-run] No file written.")
        return

    with EXPECTED_PATH.open("w") as f:
        json.dump(expected, f, indent=2)
        f.write("\n")

    print(f"\nWrote {EXPECTED_PATH}")
    print(
        "\n*** IMPORTANT: Before committing, have a second engineer manually "
        "verify ***\n"
        "***            the new expected values. "
        "See docs/REGENERATING_GOLDEN.md.  ***"
    )


if __name__ == "__main__":
    main()
