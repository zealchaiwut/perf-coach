"""Phase 1 — the worker weight-write endpoint and weigh-in autofill (spec §6).

Everything else in the lean program rests on this endpoint: a number replied in
Discord becomes a weight entry, the weigh-in habit ticks itself off that entry
with no tap, and the tracking state decides what tomorrow's nudge looks like.

Spec §6 acceptance: reply ``87.6`` in Discord → entry stored, habit ticked,
nudge silent next morning.

The worker is patched to an in-memory SQLite DB the same way the existing worker
route tests do it (no live Postgres in this environment).
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess
from sqlalchemy.pool import StaticPool

try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.models import Base, Habit, HabitLog, User, WeightEntry, Workout  # noqa: E402

_UTC = datetime.timezone.utc
TOKEN = "test-worker-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_TABLES = (User, WeightEntry, Habit, HabitLog, Workout)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_pg_functions(dbapi_conn, _record):  # pragma: no cover - plumbing
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(engine, tables=[m.__table__ for m in _TABLES])
    return engine


@pytest.fixture
def worker(db_engine, monkeypatch):
    """Worker app wired to the test DB with a known API token."""
    import backend.worker_app as worker_app
    from backend.services import habit_autofill, tracking_state

    monkeypatch.setenv("WORKER_API_TOKEN", TOKEN)
    monkeypatch.setattr(worker_app, "engine", db_engine)
    monkeypatch.setattr(habit_autofill, "engine", db_engine)

    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(), name="lean", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        uid = user.id

    class _Resolved:
        id = uid

    monkeypatch.setattr(worker_app, "_resolve_read_user", lambda user=None: _Resolved())
    return TestClient(worker_app.app), uid, db_engine, tracking_state


# ── Writing a weigh-in ───────────────────────────────────────────────────────

def test_replying_with_a_number_stores_an_entry(worker):
    client, uid, engine, _ = worker
    res = client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    assert res.status_code == 201
    body = res.json()
    assert body["weight_kg"] == pytest.approx(87.6)
    assert body["created"] is True

    with _OrmSess(engine) as s:
        rows = s.query(WeightEntry).filter(WeightEntry.user_id == uid).all()
        assert len(rows) == 1
        assert float(rows[0].weight_kg) == pytest.approx(87.6)


def test_entry_defaults_to_today_in_bangkok(worker):
    client, _, _, _ = worker
    body = client.post("/weight-entry", json={"weight_kg": 80.0}, headers=AUTH).json()
    import backend.worker_app as worker_app

    expected = datetime.datetime.now(worker_app.BANGKOK_TZ).date().isoformat()
    assert body["entry_date"] == expected


def test_second_reply_the_same_morning_corrects_rather_than_duplicates(worker):
    """"Reply 87.6" then "actually 87.4" should be one row, not two."""
    client, uid, engine, _ = worker
    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    second = client.post("/weight-entry", json={"weight_kg": 87.4}, headers=AUTH)
    assert second.status_code == 201
    assert second.json()["created"] is False

    with _OrmSess(engine) as s:
        rows = s.query(WeightEntry).filter(WeightEntry.user_id == uid).all()
        assert len(rows) == 1
        assert float(rows[0].weight_kg) == pytest.approx(87.4)


def test_entry_is_marked_as_imported_not_manual(worker):
    client, uid, engine, _ = worker
    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    with _OrmSess(engine) as s:
        assert s.query(WeightEntry).filter(WeightEntry.user_id == uid).first().source == "imported"


def test_backdating_a_weigh_in_is_allowed(worker):
    client, _, _, _ = worker
    body = client.post(
        "/weight-entry", json={"weight_kg": 87.0, "entry_date": "2026-07-01"}, headers=AUTH
    ).json()
    assert body["entry_date"] == "2026-07-01"


# ── Validation ───────────────────────────────────────────────────────────────

def test_missing_weight_is_rejected(worker):
    client, _, _, _ = worker
    assert client.post("/weight-entry", json={}, headers=AUTH).status_code == 400


@pytest.mark.parametrize("value", [19.9, 300.1, -5])
def test_implausible_weights_are_rejected(worker, value):
    client, _, _, _ = worker
    assert client.post("/weight-entry", json={"weight_kg": value}, headers=AUTH).status_code == 400


def test_non_numeric_weight_is_rejected(worker):
    client, _, _, _ = worker
    res = client.post("/weight-entry", json={"weight_kg": "heavy"}, headers=AUTH)
    assert res.status_code == 400


def test_future_dated_entry_is_rejected(worker):
    client, _, _, _ = worker
    import backend.worker_app as worker_app

    future = (datetime.datetime.now(worker_app.BANGKOK_TZ).date() + datetime.timedelta(days=2))
    res = client.post(
        "/weight-entry",
        json={"weight_kg": 80.0, "entry_date": future.isoformat()},
        headers=AUTH,
    )
    assert res.status_code == 400


def test_bad_date_format_is_rejected(worker):
    client, _, _, _ = worker
    res = client.post(
        "/weight-entry", json={"weight_kg": 80.0, "entry_date": "30-07-2026"}, headers=AUTH
    )
    assert res.status_code == 400


def test_write_requires_the_worker_token(worker):
    client, _, _, _ = worker
    assert client.post("/weight-entry", json={"weight_kg": 87.6}).status_code == 401
    assert client.post(
        "/weight-entry", json={"weight_kg": 87.6}, headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


# ── Weigh-in habit autofill ──────────────────────────────────────────────────

def _add_weigh_in_habit(engine, uid) -> uuid.UUID:
    with _OrmSess(engine) as s:
        habit = Habit(
            id=uuid.uuid4(), user_id=uid, name="Morning weigh-in",
            habit_type="binary", schedule_type="daily", active=True,
            is_archived=False, sort_order=0, display_order=0,
            tracking_type="daily_checkmark", section="training",
            auto_fill_source="weight.logged",
            created_at=datetime.datetime.now(_UTC),
        )
        s.add(habit)
        s.commit()
        return habit.id


def test_weigh_in_habit_ticks_itself_off_the_entry(worker):
    """Spec §6: real autofill, no tap. A number in Discord IS the habit."""
    client, uid, engine, _ = worker
    habit_id = _add_weigh_in_habit(engine, uid)

    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)

    with _OrmSess(engine) as s:
        logs = s.query(HabitLog).filter(HabitLog.habit_id == habit_id).all()
        assert len(logs) == 1
        assert float(logs[0].value) == 1.0
        assert logs[0].source == "workout_autofill"


def test_autofill_is_idempotent_across_repeat_writes(worker):
    client, uid, engine, _ = worker
    habit_id = _add_weigh_in_habit(engine, uid)
    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    client.post("/weight-entry", json={"weight_kg": 87.4}, headers=AUTH)

    with _OrmSess(engine) as s:
        assert s.query(HabitLog).filter(HabitLog.habit_id == habit_id).count() == 1


def test_weight_autofill_does_not_touch_workout_sourced_habits(worker):
    client, uid, engine, _ = worker
    with _OrmSess(engine) as s:
        other = Habit(
            id=uuid.uuid4(), user_id=uid, name="Zone 2", habit_type="count",
            schedule_type="daily", active=True, is_archived=False, sort_order=1,
            display_order=1, tracking_type="daily_checkmark", section="training",
            auto_fill_source="workout.zone2_minutes",
            created_at=datetime.datetime.now(_UTC),
        )
        s.add(other)
        s.commit()
        other_id = other.id

    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    with _OrmSess(engine) as s:
        assert s.query(HabitLog).filter(HabitLog.habit_id == other_id).count() == 0


def test_a_failing_autofill_never_costs_the_weigh_in(worker, monkeypatch):
    """The entry is the point; the habit tick is a convenience."""
    client, _, engine, _ = worker
    from backend.services import habit_autofill

    monkeypatch.setattr(
        habit_autofill,
        "recompute_autofill_for_week",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    res = client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    assert res.status_code == 201


# ── The nudge endpoint ───────────────────────────────────────────────────────

def test_nudge_is_silent_once_today_is_logged(worker):
    """Spec §6 acceptance: nudge silent next morning after a reply."""
    client, _, _, _ = worker
    client.post("/weight-entry", json={"weight_kg": 87.6}, headers=AUTH)
    body = client.get("/api/weight/nudge").json()
    assert body["logged_today"] is True
    assert body["deliver_now"] is False


def test_nudge_reports_active_state_for_a_regular_logger(worker):
    client, uid, engine, _ = worker
    import backend.worker_app as worker_app

    today = datetime.datetime.now(worker_app.BANGKOK_TZ).date()
    with _OrmSess(engine) as s:
        for offset in (1, 2, 3):
            s.add(
                WeightEntry(
                    id=uuid.uuid4(), user_id=uid,
                    entry_date=today - datetime.timedelta(days=offset),
                    weight_kg=87.0, source="imported",
                    created_at=datetime.datetime.now(_UTC),
                )
            )
        s.commit()

    body = client.get("/api/weight/nudge").json()
    assert body["tracking_state"] == "active"
    assert body["nudge_cadence"] == "daily"


def test_nudge_goes_weekly_after_a_week_of_silence(worker):
    client, uid, engine, _ = worker
    import backend.worker_app as worker_app

    today = datetime.datetime.now(worker_app.BANGKOK_TZ).date()
    with _OrmSess(engine) as s:
        s.add(
            WeightEntry(
                id=uuid.uuid4(), user_id=uid,
                entry_date=today - datetime.timedelta(days=20),
                weight_kg=87.0, source="imported",
                created_at=datetime.datetime.now(_UTC),
            )
        )
        s.commit()

    body = client.get("/api/weight/nudge").json()
    assert body["tracking_state"] == "paused"
    assert body["nudge_cadence"] == "weekly"
    assert body["paused_since"] is not None


def test_paused_nudge_copy_says_training_continues(worker):
    client, uid, engine, _ = worker
    import backend.worker_app as worker_app

    today = datetime.datetime.now(worker_app.BANGKOK_TZ).date()
    with _OrmSess(engine) as s:
        s.add(
            WeightEntry(
                id=uuid.uuid4(), user_id=uid,
                entry_date=today - datetime.timedelta(days=20),
                weight_kg=87.0, source="imported",
                created_at=datetime.datetime.now(_UTC),
            )
        )
        s.commit()

    body = client.get("/api/weight/nudge").json()
    assert "training continues" in body["message"]
    assert "fail" not in body["message"].lower()


def test_nudge_deliver_now_requires_the_morning_window(worker):
    """Hermes polls; the endpoint decides. Outside the window the answer is no,
    whatever else is true."""
    client, _, _, _ = worker
    body = client.get("/api/weight/nudge").json()
    if not body["in_window"]:
        assert body["deliver_now"] is False


def test_nudge_needs_no_auth_token(worker):
    """Same as the other /api/weight/* read routes — tailnet-scoped, not
    token-scoped. Only the write is token-guarded."""
    client, _, _, _ = worker
    assert client.get("/api/weight/nudge").status_code == 200
