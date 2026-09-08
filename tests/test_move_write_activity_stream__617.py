"""Tests for issue #617: move write_activity_stream out of activity_streams.py.

The module docstring of activity_streams.py states:
  "All computation lives here as pure, documented functions.
   Database writes are performed only in the thin caller layer (reconcile.py)."

These tests verify that the structural boundary is enforced:
  AC1 – activity_streams.py imports no SQLAlchemy (neither at module level
         nor inside any function body).
  AC2 – activity_streams.py imports no backend.models symbols.
  AC3 – write_activity_stream is callable from reconcile.py (its new home).
  AC4 – write_activity_stream still performs an idempotent upsert when called
         from reconcile (behavioural regression guard).
"""
import ast
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SRC = Path(__file__).parents[1] / "backend" / "services" / "activity_streams.py"


def _all_imports(source: str) -> list[str]:
    """Return a flat list of every module name referenced in import statements."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


# ---------------------------------------------------------------------------
# AC1 – no sqlalchemy imports anywhere in activity_streams.py
# ---------------------------------------------------------------------------

def test_activity_streams_has_no_sqlalchemy_import():
    """AC1: activity_streams.py must not import SQLAlchemy."""
    source = _SRC.read_text()
    imports = _all_imports(source)
    sqlalchemy_imports = [m for m in imports if m.startswith("sqlalchemy")]
    assert sqlalchemy_imports == [], (
        f"activity_streams.py must not import SQLAlchemy; found: {sqlalchemy_imports}"
    )


# ---------------------------------------------------------------------------
# AC2 – no backend.models imports anywhere in activity_streams.py
# ---------------------------------------------------------------------------

def test_activity_streams_has_no_models_import():
    """AC2: activity_streams.py must not import from backend.models."""
    source = _SRC.read_text()
    imports = _all_imports(source)
    model_imports = [m for m in imports if m.startswith("backend.models")]
    assert model_imports == [], (
        f"activity_streams.py must not import backend.models; found: {model_imports}"
    )


# ---------------------------------------------------------------------------
# AC3 – write_activity_stream is importable from reconcile.py
# ---------------------------------------------------------------------------

def test_write_activity_stream_importable_from_reconcile():
    """AC3: write_activity_stream lives in reconcile.py and is importable there."""
    from backend.services.reconcile import write_activity_stream  # noqa: F401
    assert callable(write_activity_stream)


# ---------------------------------------------------------------------------
# AC4 – write_activity_stream (from reconcile) still upserts correctly
# ---------------------------------------------------------------------------

def _make_user_and_workout() -> tuple[str, str]:
    from backend.db import engine
    uid = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO users (id, name, password_hash) VALUES (:id, :n, 'x')"
            ),
            {"id": uid, "n": f"u617_{uid[:8]}"},
        )
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO workouts (id, user_id, workout_date, name, workout_type) "
                "VALUES (:id, :uid, '2024-01-01', 'test', 'run')"
            ),
            {"id": wid, "uid": uid},
        )
    return uid, wid


def test_write_activity_stream_upserts_from_reconcile():
    """AC4: write_activity_stream from reconcile performs idempotent upsert."""
    from backend.db import engine
    from backend.services.reconcile import write_activity_stream
    from sqlalchemy.orm import Session
    from sqlalchemy import text

    _, wid = _make_user_and_workout()
    row_data = {
        "source": "strava",
        "sample_interval_seconds": 1,
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [120.0, 121.0, 122.0],
    }

    with Session(engine) as session:
        result = write_activity_stream(wid, row_data, session)
        session.commit()

    assert result is True

    # Second write (idempotent upsert) with updated data
    row_data2 = {**row_data, "heart_rate_bpm": [130.0, 131.0, 132.0]}
    with Session(engine) as session:
        write_activity_stream(wid, row_data2, session)
        session.commit()

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT heart_rate_bpm FROM activity_streams WHERE workout_id = :wid"),
            {"wid": wid},
        ).fetchone()

    assert row is not None
    assert row[0] == [130.0, 131.0, 132.0], f"upsert should overwrite; got {row[0]}"


def test_write_activity_stream_empty_noop_from_reconcile():
    """AC4b: write_activity_stream with empty dict is a no-op (returns False)."""
    from backend.services.reconcile import write_activity_stream
    from unittest.mock import MagicMock

    session = MagicMock()
    result = write_activity_stream("some-id", {}, session)
    assert result is False
    session.execute.assert_not_called()
