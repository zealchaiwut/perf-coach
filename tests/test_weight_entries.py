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


# ═══════════════════════════════════════════════════════════════════════════════
# Issue #335 — /api/weight-entries CRUD endpoint tests (a) through (j)
# ═══════════════════════════════════════════════════════════════════════════════
import datetime as _dt
import httpx

_API_BASE = "http://127.0.0.1:9001"
_WE_ENDPOINT = "/api/weight-entries"


@pytest.fixture(scope="module")
def http_client():
    with httpx.Client(base_url=_API_BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def api_user_id(http_client):
    """Create a test user for API tests; delete (cascade) on teardown."""
    import uuid as _uuid_mod
    name = f"we_api_{_uuid_mod.uuid4().hex[:8]}"
    res = http_client.post("/api/users", json={"name": name})
    assert res.status_code == 201, res.text
    uid = res.json()["id"]
    yield uid
    http_client.delete(f"/api/users/{uid}")


def _we_post(client, user_id, entry_date, weight_kg, **kw):
    payload = {"user_id": user_id, "entry_date": entry_date, "weight_kg": weight_kg}
    if "entry_time" in kw:
        payload["entry_time"] = kw["entry_time"]
    if "notes" in kw:
        payload["notes"] = kw["notes"]
    return client.post(_WE_ENDPOINT, json=payload)


# ── (a) POST creates entry ────────────────────────────────────────────────────

def test_api_a_post_creates_entry(http_client, api_user_id):
    """AC (a): POST returns 201 with full row including source='manual'."""
    res = _we_post(http_client, api_user_id, "2020-11-01", 75.0, notes="morning")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user_id"] == api_user_id
    assert body["entry_date"] == "2020-11-01"
    assert body["weight_kg"] == 75.0
    assert body["source"] == "manual"
    assert "id" in body and "created_at" in body
    http_client.delete(f"{_WE_ENDPOINT}/{body['id']}")


# ── (b) Duplicate POST returns 409 with existing_id ──────────────────────────

def test_api_b_duplicate_post_returns_409(http_client, api_user_id):
    """AC (b): Duplicate (user_id+entry_date+entry_time) returns 409 with error_code and existing_id."""
    r1 = _we_post(http_client, api_user_id, "2020-11-02", 75.0)
    assert r1.status_code == 201, r1.text
    existing_id = r1.json()["id"]

    r2 = _we_post(http_client, api_user_id, "2020-11-02", 76.0)
    assert r2.status_code == 409, r2.text
    body = r2.json()
    assert body["error_code"] == "duplicate"
    assert body["existing_id"] == existing_id

    http_client.delete(f"{_WE_ENDPOINT}/{existing_id}")


# ── (c) Future entry_date > 1 day returns 422 ────────────────────────────────

def test_api_c_future_entry_date_returns_422(http_client, api_user_id):
    """AC (c): entry_date more than 1 day in the future returns 422."""
    future = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
    res = _we_post(http_client, api_user_id, future, 75.0)
    assert res.status_code == 422, res.text


# ── (d) weight_kg outside 20–300 returns 422 ────────────────────────────────

def test_api_d_weight_kg_out_of_range_returns_422(http_client, api_user_id):
    """AC (d): weight_kg outside 20–300 returns 422."""
    for bad_kg in [5.0, 19.9, 300.1, 500.0]:
        res = _we_post(http_client, api_user_id, "2099-11-03", bad_kg)
        assert res.status_code == 422, f"Expected 422 for weight_kg={bad_kg}, got {res.status_code}: {res.text}"


# ── (e) GET filters correctly by date range ───────────────────────────────────

def test_api_e_get_filters_by_date_range(http_client, api_user_id):
    """AC (e): GET returns only entries within the specified from/to date range."""
    r_in = _we_post(http_client, api_user_id, "2020-11-10", 72.0)
    r_out = _we_post(http_client, api_user_id, "2020-12-01", 73.0)
    assert r_in.status_code == 201 and r_out.status_code == 201
    id_in, id_out = r_in.json()["id"], r_out.json()["id"]

    res = http_client.get(_WE_ENDPOINT, params={
        "user_id": api_user_id,
        "from": "2020-11-01",
        "to": "2020-11-30",
    })
    assert res.status_code == 200, res.text
    entry_ids = [e["id"] for e in res.json()["entries"]]
    assert id_in in entry_ids, "in-range entry should appear"
    assert id_out not in entry_ids, "out-of-range entry should be absent"

    http_client.delete(f"{_WE_ENDPOINT}/{id_in}")
    http_client.delete(f"{_WE_ENDPOINT}/{id_out}")


# ── (f) GET summary statistics are accurate ───────────────────────────────────

def test_api_f_get_summary_statistics(http_client, api_user_id):
    """AC (f): GET summary contains accurate aggregates."""
    data = [("2020-11-15", 70.0), ("2020-11-16", 72.0), ("2020-11-17", 68.0)]
    ids = []
    for d, w in data:
        r = _we_post(http_client, api_user_id, d, w)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    res = http_client.get(_WE_ENDPOINT, params={
        "user_id": api_user_id,
        "from": "2020-11-15",
        "to": "2020-11-17",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    s = body["summary"]
    assert s["first_date"] == "2020-11-15"
    assert s["last_date"] == "2020-11-17"
    assert s["min_kg"] == 68.0
    assert s["max_kg"] == 72.0
    assert round(s["avg_kg"], 4) == round((70.0 + 72.0 + 68.0) / 3, 4)
    assert s["entries_logged"] == 3
    assert s["days_in_range"] == 3
    assert s["days_logged_pct"] == 100.0

    for eid in ids:
        http_client.delete(f"{_WE_ENDPOINT}/{eid}")


# ── (g) PATCH updates weight_kg ───────────────────────────────────────────────

def test_api_g_patch_updates_weight_kg(http_client, api_user_id):
    """AC (g): PATCH weight_kg returns 200 with updated entry."""
    r = _we_post(http_client, api_user_id, "2020-11-20", 80.0)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    res = http_client.patch(f"{_WE_ENDPOINT}/{eid}", json={"weight_kg": 82.5})
    assert res.status_code == 200, res.text
    assert res.json()["weight_kg"] == 82.5

    http_client.delete(f"{_WE_ENDPOINT}/{eid}")


# ── (h) PATCH with entry_date in body returns 422 ────────────────────────────

def test_api_h_patch_with_entry_date_returns_422(http_client, api_user_id):
    """AC (h): PATCH returns 422 when entry_date is present in the request body."""
    r = _we_post(http_client, api_user_id, "2020-11-21", 80.0)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    res = http_client.patch(f"{_WE_ENDPOINT}/{eid}", json={"entry_date": "2020-11-22"})
    assert res.status_code == 422, res.text

    http_client.delete(f"{_WE_ENDPOINT}/{eid}")


# ── (i) DELETE removes entry ──────────────────────────────────────────────────

def test_api_i_delete_removes_entry(http_client, api_user_id):
    """AC (i): DELETE returns 200 with {"deleted": true} and entry is gone after."""
    r = _we_post(http_client, api_user_id, "2020-11-25", 75.0)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    res = http_client.delete(f"{_WE_ENDPOINT}/{eid}")
    assert res.status_code == 200, res.text
    assert res.json() == {"deleted": True}

    res2 = http_client.delete(f"{_WE_ENDPOINT}/{eid}")
    assert res2.status_code == 404


# ── (j) DELETE unknown ID returns 404 ────────────────────────────────────────

def test_api_j_delete_unknown_id_returns_404(http_client, api_user_id):
    """AC (j): DELETE on a non-existent ID returns 404."""
    fake_id = str(uuid.uuid4())
    res = http_client.delete(f"{_WE_ENDPOINT}/{fake_id}")
    assert res.status_code == 404, res.text


# ── Additional AC coverage ────────────────────────────────────────────────────

def test_api_post_unknown_user_returns_404(http_client):
    """AC: POST returns 404 when user_id does not exist."""
    fake_uid = str(uuid.uuid4())
    res = http_client.post(_WE_ENDPOINT, json={
        "user_id": fake_uid,
        "entry_date": "2020-11-05",
        "weight_kg": 75.0,
    })
    assert res.status_code == 404, res.text


def test_api_get_from_after_to_returns_422(http_client, api_user_id):
    """AC: GET returns 422 when from > to."""
    res = http_client.get(_WE_ENDPOINT, params={
        "user_id": api_user_id,
        "from": "2020-12-01",
        "to": "2020-11-01",
    })
    assert res.status_code == 422, res.text


def test_api_get_range_exceeds_365_returns_422(http_client, api_user_id):
    """AC: GET returns 422 when date range exceeds 365 days."""
    res = http_client.get(_WE_ENDPOINT, params={
        "user_id": api_user_id,
        "from": "2020-01-01",
        "to": "2021-06-01",
    })
    assert res.status_code == 422, res.text


def test_api_patch_unknown_id_returns_404(http_client):
    """AC: PATCH returns 404 when entry_id does not exist."""
    fake_id = str(uuid.uuid4())
    res = http_client.patch(f"{_WE_ENDPOINT}/{fake_id}", json={"weight_kg": 70.0})
    assert res.status_code == 404, res.text


def test_api_patch_with_user_id_returns_422(http_client, api_user_id):
    """AC: PATCH returns 422 when user_id is present in body."""
    r = http_client.post(_WE_ENDPOINT, json={
        "user_id": api_user_id,
        "entry_date": "2020-11-28",
        "weight_kg": 77.0,
    })
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    res = http_client.patch(f"{_WE_ENDPOINT}/{eid}", json={"user_id": str(uuid.uuid4())})
    assert res.status_code == 422, res.text

    http_client.delete(f"{_WE_ENDPOINT}/{eid}")


def test_api_post_notes_too_long_returns_422(http_client, api_user_id):
    """AC: POST returns 422 when notes exceeds 500 characters."""
    res = http_client.post(_WE_ENDPOINT, json={
        "user_id": api_user_id,
        "entry_date": "2020-11-29",
        "weight_kg": 75.0,
        "notes": "x" * 501,
    })
    assert res.status_code == 422, res.text
