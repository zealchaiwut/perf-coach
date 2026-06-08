"""
Tests for issue #334: WeightTarget model and weight_targets table.
5 AC anchors: (a) import, (b) non-active duplicates OK, (c) two active → IntegrityError,
(d) all four status values accepted, (e) gain goal (target > start) accepted.
"""
import uuid
import datetime
import pytest
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.models import WeightTarget

_BASE = datetime.date(2099, 4, 1)  # far-future sentinel — avoids seed collisions


def _make_user(prefix: str = "wt") -> str:
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


def _insert_target(conn, uid: str, status: str = "active", *, start: float = 80.0, target: float = 70.0) -> None:
    conn.execute(
        text(
            "INSERT INTO weight_targets "
            "(user_id, start_weight_kg, start_date, target_weight_kg, target_date, status) "
            "VALUES (:uid, :sw, :sd, :tw, :td, :st)"
        ),
        {
            "uid": uid,
            "sw": start,
            "sd": str(_BASE),
            "tw": target,
            "td": str(_BASE + datetime.timedelta(days=90)),
            "st": status,
        },
    )


# ── (a) Model is importable and instantiates without error ────────────────────

def test_a_model_imports_and_instantiates():
    """AC (a): WeightTarget importable from backend.models and instantiates without error."""
    obj = WeightTarget()
    assert obj is not None


# ── (b) Multiple non-active targets for same user do not raise ────────────────

def test_b_multiple_non_active_targets_do_not_raise():
    """AC (b): Multiple 'abandoned' targets for same user all commit without error."""
    uid = _make_user("wt_b")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "replaced")
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM weight_targets WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 3
    finally:
        _drop_user(uid)


# ── (c) Two active targets for same user → IntegrityError ────────────────────

def test_c_two_active_targets_raise_integrity_error():
    """AC (c): Inserting a second 'active' target for the same user raises IntegrityError."""
    uid = _make_user("wt_c")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "active")
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_target(conn, uid, "active")
    finally:
        _drop_user(uid)


# ── (d) All four status values are accepted ───────────────────────────────────

def test_d_all_four_status_values_accepted():
    """AC (d): active, achieved, abandoned, replaced all insert without constraint violations."""
    uid = _make_user("wt_d")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "achieved")
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "replaced")
        # Insert 'active' separately (partial unique index allows only one)
        with engine.begin() as conn:
            _insert_target(conn, uid, "active")
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM weight_targets WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 4
    finally:
        _drop_user(uid)


# ── (e) Gain goal (target_weight_kg > start_weight_kg) accepted ───────────────

def test_e_gain_goal_accepted():
    """AC (e): target_weight_kg > start_weight_kg (gain goal) inserts without error."""
    uid = _make_user("wt_e")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "active", start=60.0, target=75.0)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT start_weight_kg, target_weight_kg "
                    "FROM weight_targets WHERE user_id = :uid"
                ),
                {"uid": uid},
            ).fetchone()
        assert row is not None
        assert Decimal(str(row.target_weight_kg)) > Decimal(str(row.start_weight_kg))
    finally:
        _drop_user(uid)
