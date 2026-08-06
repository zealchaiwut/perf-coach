#!/usr/bin/env python3
"""Revision-id format lint for Alembic migrations — no database required.

Ensures every *new* migration file uses an Alembic-generated random hex
revision id (matching ``^[0-9a-f]{12,}$``) rather than a hand-authored
sequential id (e.g. ``gg7b8c9d0e1f``, ``z9n0o1p2q3r4``).

Background (CLAUDE.md, see also GitHub issue #1706):
  Hand-picked sequential ids have repeatedly caused duplicate-revision /
  multiple-head collisions when parallel feature branches each grab the
  "next letter". ``alembic revision -m "..."`` generates a random hex id
  that makes collisions nearly impossible.

The ``GRANDFATHERED_IDS`` set below lists every pre-existing non-compliant
id already in the chain as of sprint 130 (2026-08-06).  These are exempted
so CI stays green while we prevent the pattern from recurring.

Usage
-----
    python3 scripts/check_migration_ids.py               # check alembic/versions/
    python3 scripts/check_migration_ids.py --paths DIR   # check a specific dir (for tests)

Exit codes
----------
    0  All revision ids are valid or grandfathered.
    1  At least one non-grandfathered violation found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Grandfathered ids
# ---------------------------------------------------------------------------
# Every id listed here was already present in the alembic chain when issue
# #1706 was filed (2026-08-06).  They are exempted from the format check
# so that existing CI green stays green.  Do NOT add new ids here — if
# Alembic's ``alembic revision -m "..."`` is used as intended, new ids will
# always be valid random hex and won't need exempting.
GRANDFATHERED_IDS: frozenset[str] = frozenset(
    {
        # --- pre-sprint alphabetic chain (single-letter prefix, g-z suffix) ---
        "a0o1p2q3r4s5",  # add_sets_json_to_workout_exercises
        "g0a1b2c3d4e5",  # add_google_oauth_credentials
        "h1b2c3d4e5f6",  # add_sleep_imports_table
        "i2c3d4e5f6a7",  # add_workout_feel_table
        "j3d4e5f6a7b8",  # add_check_constraint_rpe_1_to_10
        "k4e5f6a7b8c9",  # add_training_load_snapshots
        "l5f6a7b8c9d0",  # add_is_admin_to_users
        "m6a7b8c9d0e1",  # merge_google_oauth_and_training_load_heads
        "n7b8c9d0e1f2",  # add_password_hash_avatar_to_users
        "o8c9d0e1f2a3",  # add_is_active_to_users
        "p9d0e1f2a3b4",  # add_app_config_table
        "q0e1f2a3b4c5",  # add_workout_templates_table
        "r1f2g3h4i5j6",  # revamp_weight_entries_table
        "s2g3h4i5j6k7",  # add_weight_targets_table
        "t3h4i5j6k7l8",  # add_user_preferences_table
        "u4i5j6k7l8m9",  # add_email_to_users
        "v5j6k7l8m9n0",  # add_sync_jobs_table
        "w6k7l8m9n0o1",  # add_avg_power_w_to_strava_activities
        "x7l8m9n0o1p2",  # add_zone2_minutes_to_workouts
        "y8m9n0o1p2q3",  # unified_habits_table
        "z9n0o1p2q3r4",  # add_habit_logs_full_schema
        # --- double-letter prefix chain (sprint-era, gg-nn) ---
        "gg7b8c9d0e1f",  # add_lap_type_to_workout_splits
        "hh8c9d0e1f2a",  # add_activity_streams_table
        "hh8c9d0e1f2g",  # add_streams_payload_to_stryd_activities
        "ii9d0e1f2a3b",  # add_detail_and_streams_payload_to_strava_activities
        "ii9d0e1f2g3h",  # add_channel_attribution_to_activity_streams
        "jj0e1f2a3b4c",  # merge_ii9_activity_streams_heads
        "kk1f2a3b4c5d",  # add_tss_method_to_workouts
        "kk1f2a3b4c5e",  # add_athlete_duration_curves_table
        "ll2a3b4c5d6e",  # add_races_table
        "ll2g3h4i5j6k",  # merge_height_cm_and_duration_curve_heads
        "mm3a4b5c6d7e",  # merge_races_and_height_duration_curve
        "mm3c4d5e6f7g",  # add_race_type_to_races
        "nn4d5e6f7g8h",  # merge_race_type_and_curve_heads
        # --- f→g typo: filename says aa1b2c3d4e5f, actual id is aa1b2c3d4e5g ---
        "aa1b2c3d4e5g",  # add_height_cm_to_users (typo in revision id, 'f'→'g')
    }
)

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

# Matches `revision = "abc"` and `revision: str = "abc"` at line start,
# but NOT `down_revision = ...`.
_REVISION_RE = re.compile(
    r"^revision(?:\s*:\s*\w+)?\s*=\s*[\"']([^\"']+)[\"']", re.M
)

# A valid Alembic-generated id: lowercase hex only, at least 12 chars.
_VALID_HEX = re.compile(r"^[0-9a-f]{12,}$")

# Migration filename convention: <revision_id>_<description>.py
_FILENAME_RE = re.compile(r"^([0-9a-f_A-Za-z]+?)_(.+)\.py$")


def check_directory(versions_dir: Path) -> list[str]:
    """Return a list of human-readable error strings for any violations found."""
    errors: list[str] = []

    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text()
        rev_ids = _REVISION_RE.findall(text)
        if not rev_ids:
            continue

        for rev_id in rev_ids:
            # Format check
            if not _VALID_HEX.match(rev_id):
                if rev_id not in GRANDFATHERED_IDS:
                    errors.append(
                        f"{path.name}: revision id {rev_id!r} is not valid "
                        f"random hex (must match ^[0-9a-f]{{12,}}$). "
                        f"Generate ids with: alembic revision -m \"<msg>\""
                    )

            # Filename-prefix check: the part of the filename before the first
            # underscore-followed-by-lowercase-letter should match the revision.
            m = _FILENAME_RE.match(path.name)
            if m:
                prefix = m.group(1)
                if prefix != rev_id:
                    is_both_grandfathered = (
                        rev_id in GRANDFATHERED_IDS and prefix in GRANDFATHERED_IDS
                    )
                    # Also allow if the revision is grandfathered (the file may
                    # have a typo in the filename that predates this check).
                    is_rev_grandfathered = rev_id in GRANDFATHERED_IDS
                    if not is_rev_grandfathered:
                        errors.append(
                            f"{path.name}: filename prefix {prefix!r} does not "
                            f"match revision id {rev_id!r}. Rename the file so "
                            f"its name starts with the actual revision id."
                        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths",
        metavar="DIR",
        help="Directory to scan (default: alembic/versions/)",
    )
    args = parser.parse_args(argv)

    versions_dir = (
        Path(args.paths) if args.paths else REPO_ROOT / "alembic" / "versions"
    )

    if not versions_dir.exists():
        print(f"check_migration_ids: directory not found: {versions_dir}", file=sys.stderr)
        return 1

    errors = check_directory(versions_dir)

    if errors:
        print("Migration id lint FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    count = sum(1 for _ in versions_dir.glob("*.py"))
    print(f"Migration id lint OK — {count} migration file(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
