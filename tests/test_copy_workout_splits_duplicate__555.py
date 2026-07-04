"""Tests for issue #555: Copy workout_splits in duplicate_workout endpoint.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria:
  AC1 — duplicate_workout queries all WorkoutSplit rows where workout_id == wid
         after copying exercises.
  AC2 — Each retrieved WorkoutSplit row is inserted as a new row with the new
         workout's id, preserving split_index order and all other field values.
  AC3 — A workout with zero splits duplicates without error and the duplicate
         has zero splits.
  AC4 — A workout with one or more user-authored splits produces a duplicate
         whose splits match the original in count, order, and content.
  AC5 — The original workout's splits are unchanged after duplication (no
         mutation of source rows).
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import CSRF_COOKIE_NAME, generate_csrf_token, hash_password
from backend.models import User, Workout, WorkoutSplit
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "dup-split-555-pw"
TODAY = datetime.date.today()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"DupSplit555_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with DBSession(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    login_res = client.post(
        "/api/auth/login",
        json={"username": name, "password": _TEST_PASSWORD},
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    session_cookie = login_res.cookies.get("session")
    assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    yield {"id": user_id, "name": name, "client": authed}
    authed.close()
    client.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


def _make_workout(authed, day):
    body = {
        "name": "Run session 555",
        "workout_date": day.isoformat(),
        "workout_type": "run",
        "remarks": "intervals",
        "tss": 60.0,
    }
    res = authed.post("/api/workouts", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _add_splits(workout_id: str, splits: list[dict]) -> None:
    """Insert WorkoutSplit rows directly via DB (mirrors the authoring endpoint)."""
    with DBSession(engine) as session:
        for s in splits:
            split = WorkoutSplit(
                workout_id=uuid.UUID(workout_id),
                split_index=s["split_index"],
                distance_km=s["distance_km"],
                duration_seconds=s["duration_seconds"],
                avg_hr=s.get("avg_hr"),
                lap_type="manual",
            )
            session.add(split)
        session.commit()


def _get_splits(workout_id: str) -> list[dict]:
    """Return splits for a workout ordered by split_index."""
    with DBSession(engine) as session:
        rows = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == uuid.UUID(workout_id))
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        return [
            {
                "split_index": r.split_index,
                "distance_km": float(r.distance_km),
                "duration_seconds": r.duration_seconds,
                "avg_hr": r.avg_hr,
                "lap_type": r.lap_type,
                "workout_id": str(r.workout_id),
            }
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — Zero-split workout duplicates without error, duplicate has zero splits
# ─────────────────────────────────────────────────────────────────────────────

def test_ac3_duplicate_workout_with_no_splits(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=5))
    # No splits added.

    target = (TODAY - datetime.timedelta(days=4)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"

    dup_id = res.json()["id"]
    dup_splits = _get_splits(dup_id)
    assert dup_splits == [], f"Duplicate of splitless workout must have 0 splits, got: {dup_splits}"

    authed.delete(f"/api/workouts/{dup_id}")
    authed.delete(f"/api/workouts/{src['id']}")


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Splits are copied: count, order, and content match the original
# ─────────────────────────────────────────────────────────────────────────────

def test_ac4_duplicate_copies_splits_count(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=6))
    _add_splits(src["id"], [
        {"split_index": 0, "distance_km": 1.0, "duration_seconds": 240, "avg_hr": 145},
        {"split_index": 1, "distance_km": 1.0, "duration_seconds": 230, "avg_hr": 150},
        {"split_index": 2, "distance_km": 1.0, "duration_seconds": 225, "avg_hr": 155},
    ])

    target = (TODAY - datetime.timedelta(days=5)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, res.text

    dup_id = res.json()["id"]
    dup_splits = _get_splits(dup_id)
    assert len(dup_splits) == 3, f"Expected 3 splits in duplicate, got {len(dup_splits)}"

    authed.delete(f"/api/workouts/{dup_id}")
    authed.delete(f"/api/workouts/{src['id']}")


def test_ac4_duplicate_copies_splits_order_and_content(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=7))
    src_split_data = [
        {"split_index": 0, "distance_km": 1.5, "duration_seconds": 360, "avg_hr": 140},
        {"split_index": 1, "distance_km": 1.0, "duration_seconds": 210, "avg_hr": 160},
    ]
    _add_splits(src["id"], src_split_data)

    target = (TODAY - datetime.timedelta(days=6)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, res.text

    dup_id = res.json()["id"]
    dup_splits = _get_splits(dup_id)

    assert len(dup_splits) == 2
    for i, (s, d) in enumerate(zip(src_split_data, dup_splits)):
        assert d["split_index"] == s["split_index"], f"split {i}: split_index mismatch"
        assert d["distance_km"] == float(s["distance_km"]), f"split {i}: distance_km mismatch"
        assert d["duration_seconds"] == s["duration_seconds"], f"split {i}: duration_seconds mismatch"
        assert d["avg_hr"] == s.get("avg_hr"), f"split {i}: avg_hr mismatch"

    authed.delete(f"/api/workouts/{dup_id}")
    authed.delete(f"/api/workouts/{src['id']}")


# ─────────────────────────────────────────────────────────────────────────────
# AC1 + AC2 — New split rows have the duplicate's workout_id (not the source's)
# ─────────────────────────────────────────────────────────────────────────────

def test_ac1_ac2_duplicate_splits_have_new_workout_id(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=8))
    _add_splits(src["id"], [
        {"split_index": 0, "distance_km": 2.0, "duration_seconds": 480, "avg_hr": 150},
    ])

    target = (TODAY - datetime.timedelta(days=7)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, res.text

    dup_id = res.json()["id"]
    dup_splits = _get_splits(dup_id)
    assert len(dup_splits) == 1, "Duplicate must have exactly 1 split"
    assert dup_splits[0]["workout_id"] == dup_id, (
        "Duplicate split must reference the new workout id, not the source's"
    )

    # Source's split still points to source.
    src_splits = _get_splits(src["id"])
    assert len(src_splits) == 1
    assert src_splits[0]["workout_id"] == src["id"]

    authed.delete(f"/api/workouts/{dup_id}")
    authed.delete(f"/api/workouts/{src['id']}")


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — Source workout's splits are unchanged after duplication
# ─────────────────────────────────────────────────────────────────────────────

def test_ac5_source_splits_unchanged_after_duplicate(auth_user):
    authed = auth_user["client"]
    src = _make_workout(authed, TODAY - datetime.timedelta(days=9))
    _add_splits(src["id"], [
        {"split_index": 0, "distance_km": 1.2, "duration_seconds": 300, "avg_hr": 142},
        {"split_index": 1, "distance_km": 0.8, "duration_seconds": 180, "avg_hr": 158},
    ])
    src_splits_before = _get_splits(src["id"])

    target = (TODAY - datetime.timedelta(days=8)).isoformat()
    res = authed.post(f"/api/workouts/{src['id']}/duplicate", json={"workout_date": target})
    assert res.status_code == 201, res.text

    dup_id = res.json()["id"]
    src_splits_after = _get_splits(src["id"])

    assert len(src_splits_after) == len(src_splits_before), (
        "Source split count must be unchanged after duplication"
    )
    for before, after in zip(src_splits_before, src_splits_after):
        assert before["split_index"] == after["split_index"]
        assert before["distance_km"] == after["distance_km"]
        assert before["duration_seconds"] == after["duration_seconds"]
        assert before["avg_hr"] == after["avg_hr"]
        assert before["workout_id"] == after["workout_id"]

    authed.delete(f"/api/workouts/{dup_id}")
    authed.delete(f"/api/workouts/{src['id']}")
