"""Tests for issue #1724: CONCURRENTLY index build can leave an INVALID index
that the existence-guard then skips.

Acceptance criteria verified:
- AC1: alembic/helpers.py exposes a valid_index_exists(table, name) function.
- AC2: valid_index_exists queries indisvalid so it returns False for INVALID indexes
       and True only for valid ones.
- AC3: 4ad3bf3fff49 upgrade guard uses valid_index_exists (not bare index_exists)
       for the CONCURRENTLY build.
- AC4: r1f2g3h4i5j6 existing-table branch upgrade guard uses valid_index_exists
       (not bare index_exists) for the CONCURRENTLY build.
- AC5: z9n0o1p2q3r4 existing-table branch upgrade guard uses valid_index_exists
       (not bare index_exists) for the CONCURRENTLY build.
- AC6: valid_index_exists returns False when index does not exist, False when index
       is INVALID, and True when index is valid.
"""
import importlib
import pathlib
import re
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


_VERSIONS = pathlib.Path(__file__).parents[1] / "alembic" / "versions"
_HELPERS = pathlib.Path(__file__).parents[1] / "alembic" / "helpers.py"

_WEIGHT_REVAMP = _VERSIONS / "r1f2g3h4i5j6_revamp_weight_entries_table.py"
_WEIGHT_PARTIAL = _VERSIONS / "4ad3bf3fff49_add_partial_unique_index_weight_null_.py"
_HABIT_LOGS = _VERSIONS / "z9n0o1p2q3r4_add_habit_logs_full_schema.py"


def _src(path: pathlib.Path) -> str:
    return path.read_text()


def _existing_table_branch(src: str, marker: str) -> str:
    idx = src.find(marker)
    assert idx != -1, f"Could not find marker {marker!r} in source"
    return src[idx:]


# ---------------------------------------------------------------------------
# AC1: helpers.py exposes valid_index_exists
# ---------------------------------------------------------------------------


class TestValidIndexExistsExists:
    def test_function_defined_in_helpers_source(self):
        """AC1: valid_index_exists is defined in alembic/helpers.py."""
        src = _HELPERS.read_text()
        assert "def valid_index_exists" in src, (
            "alembic/helpers.py must define valid_index_exists(table, name) "
            "(issue #1724)."
        )

    def test_function_accepts_table_and_name_params(self):
        """AC1: valid_index_exists signature takes table and name parameters."""
        src = _HELPERS.read_text()
        assert re.search(r"def valid_index_exists\s*\(\s*table\s*[,:]", src), (
            "valid_index_exists must accept 'table' as first parameter (issue #1724)."
        )


# ---------------------------------------------------------------------------
# AC2: valid_index_exists checks indisvalid
# ---------------------------------------------------------------------------


class TestValidIndexExistsChecksIndisvalid:
    def test_helpers_source_references_indisvalid(self):
        """AC2: helpers.py queries indisvalid to detect INVALID indexes."""
        src = _HELPERS.read_text()
        assert "indisvalid" in src, (
            "alembic/helpers.py valid_index_exists must query pg_index.indisvalid "
            "to detect partially-built INVALID indexes (issue #1724)."
        )


# ---------------------------------------------------------------------------
# AC3: 4ad3bf3fff49 uses valid_index_exists for CONCURRENTLY guard
# ---------------------------------------------------------------------------


class TestWeightPartialIndexGuard:
    def test_upgrade_imports_valid_index_exists(self):
        """AC3: 4ad3bf3fff49 imports valid_index_exists from helpers."""
        src = _src(_WEIGHT_PARTIAL)
        assert "valid_index_exists" in src, (
            "4ad3bf3fff49 must import and use valid_index_exists for the CONCURRENTLY "
            "build guard (issue #1724)."
        )

    def test_upgrade_guard_uses_valid_index_exists_not_bare_index_exists(self):
        """AC3: The CONCURRENTLY guard calls valid_index_exists, not index_exists."""
        src = _src(_WEIGHT_PARTIAL)
        # Locate the guard before the autocommit_block
        autocommit_idx = src.find("autocommit_block")
        assert autocommit_idx != -1, "autocommit_block not found in 4ad3bf3fff49"
        before_autocommit = src[:autocommit_idx]
        # The guard nearest to autocommit_block should use valid_index_exists
        # Find the last if-not-index guard before autocommit
        matches = list(re.finditer(r"if not (valid_index_exists|index_exists)\(", before_autocommit))
        assert matches, "No if-not-...-exists guard found before autocommit_block in 4ad3bf3fff49"
        last_guard = matches[-1].group(1)
        assert last_guard == "valid_index_exists", (
            f"4ad3bf3fff49: guard before CONCURRENTLY build must use valid_index_exists, "
            f"got {last_guard!r} (issue #1724)."
        )


# ---------------------------------------------------------------------------
# AC4: r1f2g3h4i5j6 uses valid_index_exists for CONCURRENTLY guard
# ---------------------------------------------------------------------------


class TestWeightRevampIndexGuard:
    def test_upgrade_imports_valid_index_exists(self):
        """AC4: r1f2g3h4i5j6 imports valid_index_exists from helpers."""
        src = _src(_WEIGHT_REVAMP)
        assert "valid_index_exists" in src, (
            "r1f2g3h4i5j6 must import and use valid_index_exists for the CONCURRENTLY "
            "build guard (issue #1724)."
        )

    def test_existing_table_branch_guard_uses_valid_index_exists(self):
        """AC4: The CONCURRENTLY guard in existing-table branch calls valid_index_exists."""
        src = _src(_WEIGHT_REVAMP)
        tail = _existing_table_branch(src, "# ── Add index")
        autocommit_idx = tail.find("autocommit_block")
        assert autocommit_idx != -1, "autocommit_block not found in existing-table branch of r1f2g3h4i5j6"
        before_autocommit = tail[:autocommit_idx]
        matches = list(re.finditer(r"if not (valid_index_exists|index_exists)\(", before_autocommit))
        assert matches, "No if-not-...-exists guard found before autocommit_block in r1f2g3h4i5j6"
        last_guard = matches[-1].group(1)
        assert last_guard == "valid_index_exists", (
            f"r1f2g3h4i5j6: guard before CONCURRENTLY build must use valid_index_exists, "
            f"got {last_guard!r} (issue #1724)."
        )


# ---------------------------------------------------------------------------
# AC5: z9n0o1p2q3r4 uses valid_index_exists for CONCURRENTLY guard
# ---------------------------------------------------------------------------


class TestHabitLogsIndexGuard:
    def test_upgrade_imports_valid_index_exists(self):
        """AC5: z9n0o1p2q3r4 imports valid_index_exists from helpers."""
        src = _src(_HABIT_LOGS)
        assert "valid_index_exists" in src, (
            "z9n0o1p2q3r4 must import and use valid_index_exists for the CONCURRENTLY "
            "build guard (issue #1724)."
        )

    def test_existing_table_branch_guard_uses_valid_index_exists(self):
        """AC5: The CONCURRENTLY guard in existing-table branch calls valid_index_exists."""
        src = _src(_HABIT_LOGS)
        tail = _existing_table_branch(src, "# 5. Composite index")
        autocommit_idx = tail.find("autocommit_block")
        assert autocommit_idx != -1, "autocommit_block not found in existing-table branch of z9n0o1p2q3r4"
        before_autocommit = tail[:autocommit_idx]
        matches = list(re.finditer(r"if not (valid_index_exists|index_exists)\(", before_autocommit))
        assert matches, "No if-not-...-exists guard found before autocommit_block in z9n0o1p2q3r4"
        last_guard = matches[-1].group(1)
        assert last_guard == "valid_index_exists", (
            f"z9n0o1p2q3r4: guard before CONCURRENTLY build must use valid_index_exists, "
            f"got {last_guard!r} (issue #1724)."
        )


# ---------------------------------------------------------------------------
# AC6: valid_index_exists returns correct values for valid, invalid, missing
# ---------------------------------------------------------------------------


def _load_helpers_module():
    """Load alembic/helpers.py fresh with op mocked out.

    Each call produces a new module object and a fresh op_stub so tests are
    isolated from one another regardless of sys.modules caching.
    """
    helpers_path = pathlib.Path(__file__).parents[1] / "alembic" / "helpers.py"
    # Always remove any previously loaded helpers copy so exec_module re-runs.
    sys.modules.pop("alembic_helpers", None)

    # Build / reuse the alembic stub; always replace .op so the exec sees the
    # fresh mock when `from alembic import op` runs inside the module body.
    op_stub = MagicMock()
    if "alembic" not in sys.modules:
        alembic_stub = types.ModuleType("alembic")
        sys.modules["alembic"] = alembic_stub
    else:
        alembic_stub = sys.modules["alembic"]
    alembic_stub.op = op_stub

    spec = importlib.util.spec_from_file_location("alembic_helpers", helpers_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, op_stub


class TestValidIndexExistsBehaviour:
    """AC6: Unit tests for valid_index_exists logic using a mocked DB connection."""

    def _make_mock_bind(self, rows):
        """Return a mock bind whose execute().fetchone() returns the given row."""
        bind = MagicMock()
        result = MagicMock()
        result.fetchone.return_value = rows
        bind.execute.return_value = result
        return bind

    def test_returns_false_when_index_does_not_exist(self):
        """AC6: valid_index_exists → False when pg_class has no matching row."""
        mod, op_stub = _load_helpers_module()
        bind = self._make_mock_bind(None)  # no row → index absent
        op_stub.get_bind.return_value = bind
        result = mod.valid_index_exists("weight_entries", "ix_weight_entries_user_date_null_time")
        assert result is False, "valid_index_exists must return False when index does not exist"

    def test_returns_false_when_index_is_invalid(self):
        """AC6: valid_index_exists → False when index exists but indisvalid=False."""
        mod, op_stub = _load_helpers_module()
        # Row returned but indisvalid column is falsy
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=False)  # row[0] or row['indisvalid']
        # Use a simple tuple-like object
        bind = self._make_mock_bind((False,))
        op_stub.get_bind.return_value = bind
        result = mod.valid_index_exists("weight_entries", "ix_weight_entries_user_date_null_time")
        assert result is False, "valid_index_exists must return False for an INVALID index"

    def test_returns_true_when_index_is_valid(self):
        """AC6: valid_index_exists → True when index exists and indisvalid=True."""
        mod, op_stub = _load_helpers_module()
        bind = self._make_mock_bind((True,))
        op_stub.get_bind.return_value = bind
        result = mod.valid_index_exists("weight_entries", "ix_weight_entries_user_date_null_time")
        assert result is True, "valid_index_exists must return True for a valid existing index"
