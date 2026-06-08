"""
Tests for issue #333: WeightEntry model and weight_entries table.
5 AC anchors: (a) import/instantiate, (b) duplicate constraint,
(c) same-date different-time, (d) cascade delete, (e) numeric precision.
"""
import uuid
import datetime
import pytest
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.models import WeightEntry

_BASE = datetime.date(2099, 3, 1)  # far-future sentinel — avoids seed collisions


def _make_user(prefix: str = "we") -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


# ── (a) Model imports and instantiates without error ──────────────────────────

def test_a_model_imports_and_instantiates():
    """AC (a): WeightEntry importable from backend.models and instantiates without error."""
    obj = WeightEntry()
    assert obj is not None


# ── (b) Exact duplicate (user_id, entry_date, entry_time=None) → IntegrityError

def test_b_duplicate_entry_raises_integrity_error():
    """AC (b): Inserting exact duplicate (user_id, entry_date, entry_time=None) raises IntegrityError."""
    uid = _make_user("we_b")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                    "VALUES (:uid, :d, 70.00)"
                ),
                {"uid": uid, "d": str(_BASE)},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                        "VALUES (:uid, :d, 71.00)"
                    ),
                    {"uid": uid, "d": str(_BASE)},
                )
    finally:
        _drop_user(uid)


# ── (c) Same date, different entry_time — both commit successfully ─────────────

def test_c_same_date_different_times_both_commit():
    """AC (c): Two entries on same date with different entry_time both commit successfully."""
    uid = _make_user("we_c")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO weight_entries (user_id, entry_date, entry_time, weight_kg) "
                    "VALUES (:uid, :d, '07:00:00', 69.50)"
                ),
                {"uid": uid, "d": str(_BASE)},
            )
            conn.execute(
                text(
                    "INSERT INTO weight_entries (user_id, entry_date, entry_time, weight_kg) "
                    "VALUES (:uid, :d, '19:00:00', 70.10)"
                ),
                {"uid": uid, "d": str(_BASE)},
            )
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM weight_entries WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 2, f"Expected 2 entries for different times, found {count}"
    finally:
        _drop_user(uid)


# ── (d) Deleting a user cascades and removes all their WeightEntry rows ────────

def test_d_cascade_delete_on_user_delete():
    """AC (d): Deleting a user cascades and removes all their WeightEntry rows."""
    uid = _make_user("we_d")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                "VALUES (:uid, :d, 72.00)"
            ),
            {"uid": uid, "d": str(_BASE)},
        )
    with engine.connect() as conn:
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM weight_entries WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar()
    assert count_before == 1

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    with engine.connect() as conn:
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM weight_entries WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar()
    assert count_after == 0, (
        f"Expected 0 weight_entries after cascade delete, found {count_after}"
    )


# ── (e) weight_kg = 88.4 stores and retrieves with correct precision ───────────

def test_e_numeric_precision_preserved():
    """AC (e): weight_kg=88.4 stores and retrieves as 88.40 — Numeric(5,2) precision intact."""
    uid = _make_user("we_e")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO weight_entries (user_id, entry_date, weight_kg) "
                    "VALUES (:uid, :d, 88.4)"
                ),
                {"uid": uid, "d": str(_BASE)},
            )
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT weight_kg FROM weight_entries WHERE user_id = :uid"),
                {"uid": uid},
            ).fetchone()
        assert row is not None
        assert Decimal(str(row.weight_kg)) == Decimal("88.40"), (
            f"Expected Decimal('88.40'), got {row.weight_kg!r}"
        )
    finally:
        _drop_user(uid)
