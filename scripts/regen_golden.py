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
import types

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.services.normalized_power import compute_normalized_power  # noqa: E402
from backend.services.tss import compute_running_tss  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run.json"
EXPECTED_PATH = REPO_ROOT / "tests" / "fixtures" / "golden_run_expected.json"

# Reference prefs used for the golden TSS computation.  These are not production
# thresholds — they are fixed values chosen so the fixture result is reproducible
# across environments.  Update fixture_prefs in the expected file and re-verify
# manually if you change them.
_GOLDEN_FTP_W = 280
_GOLDEN_THRESHOLD_PACE = 300
_GOLDEN_THRESHOLD_HR = 170


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

    laps = fixture.get("laps", [])
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
        distance_km=fixture["metadata"]["total_distance_km"],
        duration_seconds=fixture["metadata"]["duration_seconds"],
    )
    prefs = types.SimpleNamespace(
        ftp_w=_GOLDEN_FTP_W,
        threshold_pace_seconds_per_km=_GOLDEN_THRESHOLD_PACE,
        threshold_hr=_GOLDEN_THRESHOLD_HR,
    )
    tss_result = compute_running_tss(workout, splits, prefs)
    tss_val = tss_result["tss"]
    tss_method = tss_result["method"]

    if tss_val is None:
        msg = "ERROR: compute_running_tss returned None — check fixture data"
        print(msg, file=sys.stderr)
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
            "value": tss_val,
            "method": tss_method,
            "fixture_prefs": {
                "ftp_w": _GOLDEN_FTP_W,
                "threshold_pace_seconds_per_km": _GOLDEN_THRESHOLD_PACE,
                "threshold_hr": _GOLDEN_THRESHOLD_HR,
            },
            "tolerance_note": (
                "Exact integer equality — TSS rounds to a whole number."
            ),
            "verification_note": (
                f"Hand-verified against compute_running_tss with "
                f"ftp_w={_GOLDEN_FTP_W}, NP={np_val} (from streams), "
                f"duration={fixture['metadata']['duration_seconds']}s. "
                f"IF={np_val}/{_GOLDEN_FTP_W}={np_val/_GOLDEN_FTP_W:.4f}, "
                f"TSS=round({fixture['metadata']['duration_seconds']/3600:.4f}"
                f"*{(np_val/_GOLDEN_FTP_W)**2:.4f}*100)={tss_val}."
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
    print(f"tss.value                     = {tss_val}")
    print(f"tss.method                    = {tss_method}")
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
