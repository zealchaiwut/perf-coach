"""Tests for the follow-up fix to issue #1369: strength workout_type casing.

Regression covered: `workouts.workout_type` had case-inconsistent values in
production ('strength' lowercase from Strava sync, 'Strength' capitalized
from manual entry, which bypassed normalization). structural_dose.py's
original case-sensitive `workout_type = 'strength'` query silently excluded
the capitalized rows, so the gap-analysis `strength_lapsed` rule falsely
claimed "no strength sessions in 3 weeks" even when a real, recent strength
session existed.

Fix covered here:
  - write-time normalization (`_normalize_workout_type` in backend/main.py)
    now canonicalizes 'Strength'/'STRENGTH'/'strength' -> 'strength',
    mirroring the pre-existing run-type handling.
  - migration d74840f7d00e backfills historical mis-cased rows.
  - backend/services/workout_types.py centralizes the canonical constants.
  - structural_dose.py's query is defense-in-depth case-insensitive
    (`LOWER(workout_type) = LOWER(:strength_type)`).
  - strength_lapsed's recommendation text is now data-driven (states the
    actual days_ago instead of a fixed "3 weeks" claim).
"""
from __future__ import annotations

import ast
import datetime
import inspect
import os
import pathlib
import re
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as _OrmSess

from backend.main import _normalize_workout_type
from backend.services.gap_analysis.rules.strength_lapsed import (
    STRENGTH_LAPSED_DAYS,
    strength_lapsed,
)
from backend.services.structural_dose import compute_structural_dose
from backend.services.workout_types import WORKOUT_TYPE_RUN, WORKOUT_TYPE_STRENGTH

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STRUCTURAL_DOSE_SRC = (_ROOT / "backend" / "services" / "structural_dose.py").read_text()
_WORKOUT_TYPES_SRC = (_ROOT / "backend" / "services" / "workout_types.py").read_text()
_MIGRATION_SRC = (
    _ROOT / "alembic" / "versions" / "d74840f7d00e_normalize_workout_type_strength_casing.py"
).read_text()


# ═════════════════════════════════════════════════════════════════════════════
# _normalize_workout_type — pure function
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalizeWorkoutTypeStrength:
    """Write-time normalization: strength casing variants collapse to 'strength'."""

    @pytest.mark.parametrize("raw", ["Strength", "STRENGTH", "strength", "  Strength  "])
    def test_strength_variants_normalize_to_lowercase(self, raw):
        assert _normalize_workout_type(raw) == WORKOUT_TYPE_STRENGTH

    @pytest.mark.parametrize("raw", ["Crossfit", "Rowing", "Walk"])
    def test_other_types_pass_through_case_preserved(self, raw):
        """Types without a case-sensitive query dependency must NOT be
        lowercased — only 'run' and 'strength' are canonicalized."""
        assert _normalize_workout_type(raw) == raw

    @pytest.mark.parametrize(
        "raw,expected",
        [("Run", "run"), ("running", "run"), ("RUNNING", "run"), ("run", "run"), ("Running", "run")],
    )
    def test_run_variants_still_normalize_no_regression(self, raw, expected):
        assert _normalize_workout_type(raw) == expected

    def test_none_passthrough(self):
        assert _normalize_workout_type(None) is None

    def test_returns_shared_constants_not_raw_literals(self):
        """AST-level check on the function body itself: the strength/run
        branches must return the imported WORKOUT_TYPE_* names, not a fresh
        string literal — otherwise a future edit could silently reintroduce
        a second hardcoded 'strength'/'run' spelling that drifts from the
        shared enum."""
        src = inspect.getsource(_normalize_workout_type)
        tree = ast.parse(src)
        literal_returns = [
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.value.lower() in ("run", "running", "strength")
        ]
        assert not literal_returns, (
            "_normalize_workout_type must return WORKOUT_TYPE_RUN / "
            f"WORKOUT_TYPE_STRENGTH, not raw literals: {literal_returns}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Static analysis — the literal must be drawn from the shared enum
# ═════════════════════════════════════════════════════════════════════════════
#
# NOTE ON SCOPE: the broader ask was "assert the only place the literal
# 'strength' appears as a value is inside workout_types.py and the
# migration". That literal blanket assertion does not hold for this
# codebase: backend/main.py has many PRE-EXISTING, out-of-scope
# `== "strength"` comparisons unrelated to this bug (planned-session types,
# exercise-catalog categories, muscle-load source tagging, etc. — see e.g.
# lines ~7190, ~7369, ~7453, ~13921, ~17163). Those predate this fix and
# rewriting them is out of scope for a casing-bug fix. Asserting zero
# "strength" literals across all of main.py would fail for reasons
# unrelated to the regression and would encode scope creep into the test
# suite. Instead, these tests scope the check to exactly what the bug (and
# fix) touched: the query construction in structural_dose.py and the
# write-time normalizer's return values (tested above).

def _sql_text_call_args(src: str) -> list[str]:
    """Return the string literal passed to every text(...)/_text(...) call —
    i.e. the actual SQL that executes at runtime — excluding docstrings and
    comments, which are prose and legitimately describe the query using the
    word 'strength'."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname in ("text", "_text") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.append(arg.value)
    return out


class TestStrengthLiteralStaticAnalysis:
    def test_workout_types_module_defines_the_canonical_constant(self):
        assert re.search(
            r"""WORKOUT_TYPE_STRENGTH\s*:\s*str\s*=\s*["']strength["']""",
            _WORKOUT_TYPES_SRC,
        ), "workout_types.py must define WORKOUT_TYPE_STRENGTH = 'strength'"

    def test_structural_dose_sql_has_no_hardcoded_strength_equality(self):
        """The exact bug: a case-sensitive `workout_type = 'strength'` bare
        literal comparison baked into the SQL text. Must fail if such a
        literal reappears in query code without being drawn from the shared
        enum via the :strength_type bind parameter."""
        sql_blocks = _sql_text_call_args(_STRUCTURAL_DOSE_SRC)
        assert sql_blocks, "expected to find text(...)/_text(...) SQL blocks in structural_dose.py"

        offending = [
            sql for sql in sql_blocks
            if re.search(r"workout_type\s*=\s*'strength'", sql, re.IGNORECASE)
        ]
        assert not offending, (
            f"structural_dose.py has a hardcoded case-sensitive strength "
            f"equality instead of LOWER(...) + :strength_type:\n{offending}"
        )

    def test_structural_dose_imports_and_binds_the_shared_constant(self):
        assert (
            "from backend.services.workout_types import WORKOUT_TYPE_STRENGTH"
            in _STRUCTURAL_DOSE_SRC
        ), "structural_dose.py must import WORKOUT_TYPE_STRENGTH rather than hardcode it"
        assert '"strength_type": WORKOUT_TYPE_STRENGTH' in _STRUCTURAL_DOSE_SRC, (
            "the :strength_type bind parameter must be sourced from the shared constant"
        )

    def test_structural_dose_query_uses_case_insensitive_comparison(self):
        sql_blocks = _sql_text_call_args(_STRUCTURAL_DOSE_SRC)
        strength_queries = [sql for sql in sql_blocks if "strength_type" in sql]
        assert strength_queries, "expected at least one query bound to :strength_type"
        for sql in strength_queries:
            assert "LOWER(workout_type)" in sql and "LOWER(:strength_type)" in sql, (
                f"strength-scoped query must compare case-insensitively:\n{sql}"
            )

    def test_migration_hardcodes_strength_literal_by_design(self):
        """The migration's UPDATE is a one-time historical backfill — it
        necessarily hardcodes the literal (this matches the precedent set by
        the sibling run-casing migration, d16a76bf72ca, which also hardcodes
        'run'). This is the documented, accepted exception — not a failure
        mode."""
        assert "workout_type = 'strength'" in _MIGRATION_SRC
        assert "lower(workout_type) = 'strength'" in _MIGRATION_SRC


# ═════════════════════════════════════════════════════════════════════════════
# strength_lapsed rule — pure function
# ═════════════════════════════════════════════════════════════════════════════

def _inputs(days_ago, other_codes=None, week_start=datetime.date(2026, 7, 13)):
    return {
        "structural_dose": {"last_strength_days_ago": days_ago},
        "other_findings_codes": other_codes or [],
        "week_start": week_start,
    }


class TestStrengthLapsedRule:
    def test_recent_strength_suppresses_finding(self):
        assert strength_lapsed(_inputs(8)) is None

    def test_one_day_under_threshold_suppresses(self):
        assert strength_lapsed(_inputs(STRENGTH_LAPSED_DAYS - 1)) is None

    def test_boundary_at_threshold_still_fires(self):
        """Spec: 'days_ago < STRENGTH_LAPSED_DAYS: return None' — so exactly
        21 (not strictly less than) must still fire. Confirms this diff did
        not change the pre-existing boundary condition."""
        result = strength_lapsed(_inputs(STRENGTH_LAPSED_DAYS))
        assert result is not None, (
            f"days_ago == STRENGTH_LAPSED_DAYS ({STRENGTH_LAPSED_DAYS}) must still fire "
            "(only strictly-less-than suppresses)"
        )
        assert str(STRENGTH_LAPSED_DAYS) in result.recommendation

    def test_lapsed_fires_with_quantified_recommendation(self):
        result = strength_lapsed(_inputs(25))
        assert result is not None
        assert "25" in result.recommendation
        assert "days" in result.recommendation

    def test_never_recorded_fires_with_no_record_phrasing(self):
        result = strength_lapsed(_inputs(None))
        assert result is not None
        assert "No strength sessions on record" in result.recommendation
        assert "3 weeks" not in result.recommendation

    @pytest.mark.parametrize(
        "suppressing_code", ["recurrent_niggle_area", "undertrained_area_under_ramp"]
    )
    def test_suppressed_by_specific_structural_rule(self, suppressing_code):
        assert strength_lapsed(_inputs(30, other_codes=[suppressing_code])) is None

    def test_missing_structural_dose_returns_none(self):
        inputs = {"other_findings_codes": [], "week_start": datetime.date(2026, 7, 13)}
        assert strength_lapsed(inputs) is None


# ═════════════════════════════════════════════════════════════════════════════
# Live-DB integration — structural_dose.py + strength_lapsed regression
# ═════════════════════════════════════════════════════════════════════════════

_root = _ROOT
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _insert_workout(engine, user_id, workout_date, workout_type, name="strength session"):
    """Insert a workout row via raw SQL, bypassing _normalize_workout_type —
    simulates both pre-fix historical rows and a hypothetical future bypass."""
    with _OrmSess(engine) as db:
        db.execute(
            text(
                """
                INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
                VALUES (gen_random_uuid(), :uid, :d, :name, :wtype)
                """
            ),
            {"uid": user_id, "d": workout_date, "name": name, "wtype": workout_type},
        )
        db.commit()


@pytest.fixture
def db_user():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")
    user_id = uuid.uuid4()
    with _OrmSess(_engine) as db:
        db.execute(
            text("INSERT INTO users (id, name) VALUES (:id, :name)"),
            {"id": user_id, "name": f"strcasing_{user_id.hex[:8]}"},
        )
        db.commit()
    yield user_id
    with _OrmSess(_engine) as db:
        db.execute(text("DELETE FROM workouts WHERE user_id = :id"), {"id": user_id})
        db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db.commit()


class TestStrengthCasingRegression:
    """The exact regression scenario: a capitalized 'Strength' session must
    be found by compute_structural_dose and must suppress strength_lapsed."""

    def test_capitalized_strength_counted_and_suppresses_rule(self, db_user):
        today = datetime.date(2026, 7, 15)
        session_date = datetime.date(2026, 7, 7)
        _insert_workout(_engine, db_user, session_date, "Strength")

        with _OrmSess(_engine) as db:
            dose = compute_structural_dose(db, db_user, today, weeks=8)

        assert dose["last_strength_days_ago"] == 8, (
            "a capitalized 'Strength' workout_type must be counted by the "
            "case-insensitive query, not silently excluded — this is the "
            "exact production bug"
        )

        week_start = today - datetime.timedelta(days=today.weekday())
        finding = strength_lapsed(
            {
                "structural_dose": dose,
                "other_findings_codes": [],
                "week_start": week_start,
            }
        )
        assert finding is None, (
            "a real strength session 8 days ago must suppress the "
            "strength_lapsed advisory, not falsely claim no recent strength"
        )


class TestStructuralDoseCaseInsensitiveQuery:
    """Defense-in-depth: even if a future write path bypasses the
    normalizer, the read-time query must still count mixed-case rows."""

    def test_mixed_casing_all_counted_no_bypass(self, db_user):
        today = datetime.date(2026, 7, 15)
        monday = today - datetime.timedelta(days=today.weekday())
        d_lower = monday
        d_title = monday + datetime.timedelta(days=1)
        d_upper = monday + datetime.timedelta(days=2)

        _insert_workout(_engine, db_user, d_lower, "strength")
        _insert_workout(_engine, db_user, d_title, "Strength")
        _insert_workout(_engine, db_user, d_upper, "STRENGTH")

        with _OrmSess(_engine) as db:
            dose = compute_structural_dose(db, db_user, today, weeks=2)

        current_week = next(
            (b for b in dose["weekly"] if b["week_start"] == monday.isoformat()), None
        )
        assert current_week is not None
        assert current_week["strength_days"] == 3, (
            "all three casing variants ('strength'/'Strength'/'STRENGTH') "
            "must be counted as distinct strength days"
        )
        assert dose["last_strength_days_ago"] == (today - d_upper).days, (
            "recency must be derived from the most recent row regardless of its casing"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Migration — real upgrade() run through alembic against a scratch DB
# ═════════════════════════════════════════════════════════════════════════════

class TestMigrationNormalizesStrengthCasing:
    """Runs the actual migration's upgrade() through alembic against a
    throwaway scratch DB. Gated on TEST_DATABASE_URL (same convention as
    scripts/test_migrations.sh) — never point this at UAT/PRD, the fixture
    wipes the target schema."""

    @pytest.fixture
    def migration_cfg(self, monkeypatch):
        db_url = os.environ.get("TEST_DATABASE_URL")
        if not db_url:
            pytest.skip("TEST_DATABASE_URL not set (see scripts/test_migrations.sh)")

        reset_engine = create_engine(db_url)
        with reset_engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()
        reset_engine.dispose()

        monkeypatch.setenv("ENVIRONMENT", "uat")
        monkeypatch.setenv("DATABASE_URL_UAT", db_url)

        from alembic.config import Config as _AlembicConfig
        from alembic import command as _alembic_command

        cfg = _AlembicConfig(str(_root / "alembic.ini"))
        # Build schema up to (not including) the migration under test.
        _alembic_command.upgrade(cfg, "8d14fe27be6b")

        engine = create_engine(db_url)
        yield engine, cfg
        engine.dispose()

    def test_upgrade_normalizes_only_mismatched_casing(self, migration_cfg):
        engine, cfg = migration_cfg
        from alembic import command as _alembic_command

        user_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (id, name) VALUES (:id, 'migtest_strength_casing')"),
                {"id": user_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO workouts (id, user_id, workout_date, name, workout_type)
                    VALUES
                        (gen_random_uuid(), :uid, '2026-07-01', 'a', 'Strength'),
                        (gen_random_uuid(), :uid, '2026-07-02', 'b', 'strength'),
                        (gen_random_uuid(), :uid, '2026-07-03', 'c', 'Crossfit')
                    """
                ),
                {"uid": user_id},
            )

        _alembic_command.upgrade(cfg, "d74840f7d00e")

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT workout_date, workout_type FROM workouts "
                    "WHERE user_id = :uid ORDER BY workout_date"
                ),
                {"uid": user_id},
            ).fetchall()

        by_date = {r[0]: r[1] for r in rows}
        assert by_date[datetime.date(2026, 7, 1)] == "strength", (
            "capitalized 'Strength' must be normalized to lowercase"
        )
        assert by_date[datetime.date(2026, 7, 2)] == "strength", (
            "an already-lowercase row must be untouched (idempotent no-op)"
        )
        assert by_date[datetime.date(2026, 7, 3)] == "Crossfit", (
            "an unrelated workout_type must be untouched"
        )

    def test_upgrade_sql_is_idempotent_on_rerun(self, migration_cfg):
        engine, cfg = migration_cfg
        from alembic import command as _alembic_command

        user_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (id, name) VALUES (:id, 'migtest_idempotent')"),
                {"id": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO workouts (id, user_id, workout_date, name, workout_type) "
                    "VALUES (gen_random_uuid(), :uid, '2026-07-01', 'a', 'Strength')"
                ),
                {"uid": user_id},
            )

        _alembic_command.upgrade(cfg, "d74840f7d00e")

        # Re-run the migration's own UPDATE statement a second time directly
        # (alembic itself won't replay an already-applied revision, so this
        # exercises the SQL's own idempotency guard: `workout_type <> 'strength'`).
        rerun_sql = (
            "UPDATE workouts SET workout_type = 'strength' "
            "WHERE lower(workout_type) = 'strength' "
            "AND workout_type <> 'strength'"
        )
        with engine.begin() as conn:
            result = conn.execute(text(rerun_sql))
        assert result.rowcount == 0, (
            "re-running the backfill after rows are normalized must be a no-op"
        )
