"""PWA phase 0 DB tests: apply_once, cleanup, bundle, sync, device session."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from backend.db import engine
from backend.models import ProcessedMutation, User
from backend.services.processed_mutations import apply_once, cleanup_old_mutations
from sqlalchemy.orm import Session


def test_apply_once_runs_fn_once():
    uid = uuid.uuid4()
    mid = uuid.uuid4()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return {"ok": True, "n": calls["n"]}

    with Session(engine) as session:
        session.add(User(id=uid, name=f"pwa-{uid.hex[:8]}"))
        session.commit()
        try:
            a = apply_once(session, uid, mid, "weigh_in", fn)
            b = apply_once(session, uid, mid, "weigh_in", fn)
            session.commit()
            assert a == b == {"ok": True, "n": 1}
            assert calls["n"] == 1
        finally:
            session.query(ProcessedMutation).filter(ProcessedMutation.user_id == uid).delete()
            session.query(User).filter(User.id == uid).delete()
            session.commit()


def test_apply_once_concurrent_unique_constraint():
    uid = uuid.uuid4()
    mid = uuid.uuid4()
    calls = {"n": 0}
    lock = threading.Lock()

    def fn():
        with lock:
            calls["n"] += 1
        return {"n": calls["n"]}

    with Session(engine) as setup:
        setup.add(User(id=uid, name=f"pwa-c-{uid.hex[:8]}"))
        setup.commit()

    results = [None, None]
    errors = []

    def worker(i):
        try:
            with Session(engine) as session:
                results[i] = apply_once(session, uid, mid, "weigh_in", fn)
                session.commit()
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    try:
        assert not errors, errors
        assert calls["n"] == 1
        live = [r for r in results if r is not None]
        assert live
        assert all(r == live[0] for r in live)
    finally:
        with Session(engine) as session:
            session.query(ProcessedMutation).filter(ProcessedMutation.user_id == uid).delete()
            session.query(User).filter(User.id == uid).delete()
            session.commit()


def test_cleanup_removes_only_old_rows():
    uid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(User(id=uid, name=f"pwa-old-{uid.hex[:8]}"))
        session.flush()
        old = ProcessedMutation(
            user_id=uid,
            client_mutation_id=uuid.uuid4(),
            op_type="weigh_in",
            received_at=now - timedelta(days=31),
            result={"old": True},
        )
        young = ProcessedMutation(
            user_id=uid,
            client_mutation_id=uuid.uuid4(),
            op_type="weigh_in",
            received_at=now - timedelta(days=2),
            result={"young": True},
        )
        session.add_all([old, young])
        session.commit()
        try:
            n = cleanup_old_mutations(session, now=now)
            session.commit()
            assert n >= 1
            left = session.query(ProcessedMutation).filter(ProcessedMutation.user_id == uid).all()
            assert len(left) == 1
            assert left[0].result == {"young": True}
        finally:
            session.query(ProcessedMutation).filter(ProcessedMutation.user_id == uid).delete()
            session.query(User).filter(User.id == uid).delete()
            session.commit()


def test_sync_duplicate_and_invalid_op(as_user):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.models import WeightEntry

    uid = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=uid, name=f"pwa-sync-{uid.hex[:8]}"))
        session.commit()
    as_user(uid)
    client = TestClient(app)
    mid = str(uuid.uuid4())
    ops = [
        {
            "client_mutation_id": mid,
            "op_type": "weigh_in",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"date": "2026-11-24", "kg": 67.8},
        },
        {
            "client_mutation_id": str(uuid.uuid4()),
            "op_type": "not_a_thing",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        },
    ]
    try:
        r1 = client.post("/api/mobile/sync", json={"ops": ops})
        assert r1.status_code == 200, r1.text
        body = r1.json()["ops"]
        assert body[0]["status"] == "applied"
        assert body[1]["status"] == "invalid"
        r2 = client.post("/api/mobile/sync", json={"ops": [ops[0]]})
        assert r2.json()["ops"][0]["status"] == "duplicate"
    finally:
        with Session(engine) as session:
            session.query(ProcessedMutation).filter(ProcessedMutation.user_id == uid).delete()
            session.query(WeightEntry).filter(WeightEntry.user_id == uid).delete()
            session.query(User).filter(User.id == uid).delete()
            session.commit()


def test_bundle_304_and_device_revoke(as_user):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.models import DeviceSession
    from backend.services.device_sessions import issue_device_session

    uid = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=uid, name=f"pwa-dev-{uid.hex[:8]}"))
        session.commit()
        row, raw, _csrf = issue_device_session(session, uid, label="Test phone")
        session.commit()
        did = row.id
        live = session.get(DeviceSession, did)
        live.last_seen_at = datetime.now(timezone.utc) - timedelta(days=60)
        session.commit()
    as_user(uid)
    client = TestClient(app)
    try:
        r = client.get("/api/mobile/bundle?days=7")
        assert r.status_code == 200, r.text
        etag = r.headers.get("etag")
        assert etag
        r2 = client.get("/api/mobile/bundle?days=7", headers={"If-None-Match": etag})
        assert r2.status_code == 304
        gone = client.delete(f"/api/mobile/devices/{did}")
        assert gone.status_code == 200
        listed = client.get("/api/mobile/devices").json()["devices"]
        assert listed == []
    finally:
        with Session(engine) as session:
            session.query(DeviceSession).filter(DeviceSession.user_id == uid).delete()
            session.query(User).filter(User.id == uid).delete()
            session.commit()
