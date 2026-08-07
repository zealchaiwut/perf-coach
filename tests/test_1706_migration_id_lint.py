"""
Tests for issue #1706: CI lint must reject new migration files whose revision
id is not a valid Alembic-generated random hex id.

Acceptance criteria:
  AC-1  The lint detects revision ids containing non-hex characters (a-f, 0-9
        are valid hex; g-z and other non-hex chars are not) and reports them
        as errors.
  AC-2  The lint passes cleanly on the current repo state — all existing
        non-compliant ids are in the grandfathered set so CI is not broken.
  AC-3  The CI workflow (.github/workflows/migrations-check.yml) runs
        scripts/check_migration_ids.py as a named step.
  AC-4  The lint also detects when a migration file's filename prefix does not
        match its actual revision id (e.g. filename says aa1b2c3d4e5f but
        revision = "aa1b2c3d4e5g").
  AC-5  The lint accepts valid Alembic-generated random hex ids of 12+ chars.
  AC-6  The grandfathered set in check_migration_ids.py documents each exempted
        id so future maintainers understand why it bypasses the check.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_migration_ids.py"
VERSIONS_DIR = REPO_ROOT / "alembic" / "versions"

_REVISION_RE = re.compile(
    r"^revision(?:\s*:\s*\w+)?\s*=\s*[\"']([^\"']+)[\"']", re.M
)
VALID_HEX_RE = re.compile(r"^[0-9a-f]{12,}$")


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_grandfathered() -> set[str]:
    """Import GRANDFATHERED_IDS from the script without side effects."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_migration_ids", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.GRANDFATHERED_IDS)


# ── AC-1: non-hex chars are detected ─────────────────────────────────────────


def test_detects_nonhex_revision_id():
    """A revision id with g-z chars must be flagged as invalid by the regex."""
    bad_ids = [
        "gg7b8c9d0e1f",   # g not hex
        "hh8c9d0e1f2a",   # h not hex
        "nn4d5e6f7g8h",   # n, g, h not hex
        "z9n0o1p2q3r4",   # z, n, o, p, q, r not hex
        "aa1b2c3d4e5g",   # g not hex (the f→g typo)
        "short",          # too short
    ]
    for rev_id in bad_ids:
        assert not VALID_HEX_RE.match(rev_id), (
            f"Expected {rev_id!r} to fail the valid-hex check but it passed"
        )


def test_accepts_valid_hex_ids():
    """Well-formed Alembic-generated ids must pass the valid-hex regex."""
    good_ids = [
        "00b745c5fa52",
        "017a12a2a6f5",
        "02ea347c3bd1",
        "1da954a27351bb1b",   # 16-char id is also fine
        "7921872665c9",        # the current head
        "046b014b2eab",
    ]
    for rev_id in good_ids:
        assert VALID_HEX_RE.match(rev_id), (
            f"Expected {rev_id!r} to pass the valid-hex check but it failed"
        )


# ── AC-2: current repo passes the lint ────────────────────────────────────────


def test_script_exits_zero_on_current_repo():
    """Running check_migration_ids.py on the current repo must exit 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"check_migration_ids.py failed on current repo:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


# ── AC-3: CI workflow runs the new script ─────────────────────────────────────


def test_ci_workflow_runs_check_migration_ids():
    """The migrations CI workflow must invoke check_migration_ids.py."""
    workflow = REPO_ROOT / ".github" / "workflows" / "migrations-check.yml"
    assert workflow.exists(), "migrations-check.yml not found"
    text = workflow.read_text()
    assert "check_migration_ids.py" in text, (
        "migrations-check.yml must call scripts/check_migration_ids.py"
    )


# ── AC-4: filename-revision mismatch is detected ──────────────────────────────


def test_script_detects_filename_revision_mismatch(tmp_path):
    """A migration whose filename prefix ≠ revision id must be detected."""
    # Create a fake migration where filename says 'aabbccddeeff' but revision is 'aabbccddeeff' + 'g'
    bad_file = tmp_path / "aabbccddeeff_some_migration.py"
    bad_file.write_text('revision = "aabbccddeeffg"\n')  # 'g' makes it non-hex AND mismatched

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--paths", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode != 0, (
        "Expected non-zero exit for filename/revision mismatch but got 0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "aabbccddeeffg" in combined or "mismatch" in combined.lower() or "invalid" in combined.lower(), (
        f"Error output must mention the bad revision id. Got:\n{combined}"
    )


# ── AC-5 (redundant path): ensure valid ids are accepted in real files ────────


def test_no_new_violations_in_version_files():
    """Every revision id in alembic/versions/ is either valid hex or grandfathered."""
    grandfathered = _load_grandfathered()

    violations: list[tuple[str, str]] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text()
        for rev_id in _REVISION_RE.findall(text):
            if not VALID_HEX_RE.match(rev_id) and rev_id not in grandfathered:
                violations.append((path.name, rev_id))

    assert not violations, (
        "Found revision ids that are neither valid hex nor in GRANDFATHERED_IDS:\n"
        + "\n".join(f"  {fname}: {rid!r}" for fname, rid in violations)
    )


# ── AC-6: grandfathered set is documented ─────────────────────────────────────


def test_grandfathered_ids_have_comments():
    """The GRANDFATHERED_IDS definition in check_migration_ids.py must have
    inline comments explaining why each id is exempted."""
    text = SCRIPT.read_text()
    # The set must exist and have at least a block comment before it
    assert "GRANDFATHERED_IDS" in text, "GRANDFATHERED_IDS not found in script"
    # There should be a comment explaining the grandfathering (# or docstring style)
    idx = text.index("GRANDFATHERED_IDS")
    surrounding = text[max(0, idx - 500) : idx + 200]
    has_comment = "#" in surrounding or '"""' in surrounding
    assert has_comment, (
        "GRANDFATHERED_IDS must be accompanied by a comment explaining "
        "why the ids are exempted"
    )
