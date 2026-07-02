"""Tests for issues #233, #248, #250: GET, PATCH, DELETE /api/feel; auto-link"""
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_RUN = str(uuid.uuid4())[:8]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    name = f"FeelUser_{_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next((u for u in users if u["name"] == name), None)
    assert u is not None
    return u["id"]


@pytest.fixture(scope="module")
def workout_id(client, user_id):
    res = client.post(
        "/api/workouts",
        json={
            "user_id": user_id,
            "workout_date": "2026-01-10",
            "name": f"Workout_{_RUN}",
            "workout_type": "run",
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


@pytest.fixture(scope="module")
def feel_entry_1(client, user_id):
    """Entry on 2026-01-05, with rpe and notes."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-05", "rpe_1_to_10": 7, "notes": "good day"},
    )
    assert res.status_code == 201
    return res.json()


@pytest.fixture(scope="module")
def feel_entry_2(client, user_id):
    """Entry on 2026-01-15, notes only."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-15", "notes": "tired"},
    )
    assert res.status_code == 201
    return res.json()


@pytest.fixture(scope="module")
def feel_entry_workout(client, user_id, workout_id):
    """Entry linked to a workout."""
    res = client.post(
        "/api/feel",
        json={"user_id": user_id, "feel_date": "2026-01-10", "workout_id": workout_id, "notes": "post-workout"},
    )
    assert res.status_code == 201
    return res.json()


# (a) GET returns entries for user_id
def test_get_feel_returns_entries(client, user_id, feel_entry_1, feel_entry_2):
    res = client.get("/api/feel", params={"user_id": user_id})
    assert res.status_code == 200
    data = res.json()
    assert "entries" in data
    assert "count" in data
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_1["id"] in ids
    assert feel_entry_2["id"] in ids
    assert data["count"] >= 2
    # sorted feel_date DESC
    dates = [e["feel_date"] for e in data["entries"]]
    assert dates == sorted(dates, reverse=True)


# (b) GET filters by date range
def test_get_feel_date_range(client, user_id, feel_entry_1, feel_entry_2, feel_entry_workout):
    res = client.get("/api/feel", params={"user_id": user_id, "from": "2026-01-10", "to": "2026-01-15"})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_2["id"] in ids        # 2026-01-15 — inside range
    assert feel_entry_workout["id"] in ids  # 2026-01-10 — inside range
    assert feel_entry_1["id"] not in ids    # 2026-01-05 — outside range


# (c) GET filters by workout_id
def test_get_feel_workout_filter(client, user_id, workout_id, feel_entry_workout, feel_entry_1):
    res = client.get("/api/feel", params={"user_id": user_id, "workout_id": workout_id})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_workout["id"] in ids
    assert feel_entry_1["id"] not in ids


# (d) GET has_rpe filter
def test_get_feel_has_rpe(client, user_id, feel_entry_1, feel_entry_2):
    res = client.get("/api/feel", params={"user_id": user_id, "has_rpe": "true"})
    assert res.status_code == 200
    data = res.json()
    ids = {e["id"] for e in data["entries"]}
    assert feel_entry_1["id"] in ids   # rpe_1_to_10=7
    assert feel_entry_2["id"] not in ids  # no rpe


# (e) PATCH updates a field
def test_patch_feel_updates_field(client, feel_entry_1):
    res = client.patch(f"/api/feel/{feel_entry_1['id']}", json={"notes": "updated notes"})
    assert res.status_code == 200
    data = res.json()
    assert data["notes"] == "updated notes"
    assert data["id"] == feel_entry_1["id"]


# (f) PATCH with feel_date in body returns 422
def test_patch_feel_date_immutable(client, feel_entry_1):
    res = client.patch(f"/api/feel/{feel_entry_1['id']}", json={"feel_date": "2026-06-01"})
    assert res.status_code == 422


# (g) PATCH unknown id returns 404
def test_patch_feel_not_found(client):
    fake_id = str(uuid.uuid4())
    res = client.patch(f"/api/feel/{fake_id}", json={"notes": "ghost"})
    assert res.status_code == 404


# (h) DELETE removes entry
def test_delete_feel(client, user_id, feel_entry_2):
    res = client.delete(f"/api/feel/{feel_entry_2['id']}")
    assert res.status_code == 204
    # confirm gone
    res2 = client.get("/api/feel", params={"user_id": user_id})
    ids = {e["id"] for e in res2.json()["entries"]}
    assert feel_entry_2["id"] not in ids


# (i) DELETE unknown id returns 404
def test_delete_feel_not_found(client):
    fake_id = str(uuid.uuid4())
    res = client.delete(f"/api/feel/{fake_id}")
    assert res.status_code == 404


# ── Issue #250: auto-link tests ───────────────────────────────────────────────

_AL_RUN = str(uuid.uuid4())[:8]
_AL_DATE_SINGLE = "2025-11-10"
_AL_DATE_MULTI = "2025-11-11"
_AL_DATE_NONE = "2025-11-12"
_AL_DATE_BACKFILL = "2025-11-13"


@pytest.fixture(scope="module")
def al_user_id(client):
    name = f"ALUser_{_AL_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next(u for u in users if u["name"] == name)
    return u["id"]


@pytest.fixture(scope="module")
def al_single_workout_id(client, al_user_id):
    res = client.post(
        "/api/workouts",
        json={"user_id": al_user_id, "workout_date": _AL_DATE_SINGLE,
              "name": f"ALSingle_{_AL_RUN}", "workout_type": "run"},
    )
    assert res.status_code == 201
    return res.json()["id"]


@pytest.fixture(scope="module")
def al_multi_workout_ids(client, al_user_id):
    ids = []
    for i in range(2):
        res = client.post(
            "/api/workouts",
            json={"user_id": al_user_id, "workout_date": _AL_DATE_MULTI,
                  "name": f"ALMulti{i}_{_AL_RUN}", "workout_type": "run"},
        )
        assert res.status_code == 201
        ids.append(res.json()["id"])
    return ids


@pytest.fixture(scope="module")
def al_backfill_workout_id(client, al_user_id):
    res = client.post(
        "/api/workouts",
        json={"user_id": al_user_id, "workout_date": _AL_DATE_BACKFILL,
              "name": f"ALBackfill_{_AL_RUN}", "workout_type": "run"},
    )
    assert res.status_code == 201
    return res.json()["id"]


# (a) POST feel with single workout auto-links workout_id
def test_post_feel_auto_link_single_workout(client, al_user_id, al_single_workout_id):
    res = client.post(
        "/api/feel",
        json={"user_id": al_user_id, "feel_date": _AL_DATE_SINGLE, "rpe_1_to_10": 7},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["workout_id"] == al_single_workout_id


# (b) POST feel with multiple workouts leaves workout_id null
def test_post_feel_auto_link_multi_workout(client, al_user_id, al_multi_workout_ids):
    res = client.post(
        "/api/feel",
        json={"user_id": al_user_id, "feel_date": _AL_DATE_MULTI, "rpe_1_to_10": 5},
    )
    assert res.status_code == 201
    assert res.json()["workout_id"] is None


# (c) POST feel with no workouts leaves workout_id null
def test_post_feel_auto_link_no_workout(client, al_user_id):
    res = client.post(
        "/api/feel",
        json={"user_id": al_user_id, "feel_date": _AL_DATE_NONE, "rpe_1_to_10": 3},
    )
    assert res.status_code == 201
    assert res.json()["workout_id"] is None


# (d) Manual trigger links all eligible entries for user/date
def test_post_feel_auto_link_manual_trigger(client, al_user_id, al_backfill_workout_id):
    # Insert two unlinked entries (no workout_id provided)
    for i in range(2):
        res = client.post(
            "/api/feel",
            json={"user_id": al_user_id, "feel_date": _AL_DATE_BACKFILL, "notes": f"backfill {i}"},
        )
        assert res.status_code == 201

    # Manually trigger auto-link
    res = client.post(
        "/api/feel/auto-link",
        params={"user_id": al_user_id, "feel_date": _AL_DATE_BACKFILL},
    )
    assert res.status_code == 200
    data = res.json()
    assert "linked" in data
    assert data["linked"] >= 0

    # Verify entries are now linked
    entries_res = client.get("/api/feel", params={"user_id": al_user_id, "workout_id": al_backfill_workout_id})
    assert entries_res.status_code == 200
    assert entries_res.json()["count"] >= 1


# (e) Re-running auto-link is idempotent
def test_post_feel_auto_link_idempotent(client, al_user_id, al_backfill_workout_id):
    res = client.post(
        "/api/feel/auto-link",
        params={"user_id": al_user_id, "feel_date": _AL_DATE_BACKFILL},
    )
    assert res.status_code == 200
    assert res.json()["linked"] == 0


# (f) Auto-link failure inside POST does not fail the POST
def test_post_feel_auto_link_failure_does_not_fail_post(client, al_user_id, monkeypatch):
    import backend.main as _main

    def _fail(*_a, **_kw):
        raise RuntimeError("simulated auto-link failure")

    monkeypatch.setattr(_main, "auto_link_feel_entries", _fail)

    res = client.post(
        "/api/feel",
        json={"user_id": al_user_id, "feel_date": _AL_DATE_NONE, "notes": "fallback test"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["workout_id"] is None


# ── Issue #251: summary and search endpoints ──────────────────────────────────

_SS_RUN = str(uuid.uuid4())[:8]


@pytest.fixture(scope="module")
def ss_user_id(client):
    name = f"SSUser_{_SS_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next(u for u in users if u["name"] == name)
    return u["id"]


@pytest.fixture(scope="module")
def ss_entries(client, ss_user_id):
    """Seed three feel entries: one RPE-only, one notes-only, one both."""
    entries = [
        {"user_id": ss_user_id, "feel_date": "2026-01-10", "rpe_1_to_10": 6},
        {"user_id": ss_user_id, "feel_date": "2026-01-12", "notes": "hamstring felt tight during warm-up"},
        {"user_id": ss_user_id, "feel_date": "2026-01-14", "rpe_1_to_10": 8, "notes": "strong session; HAMSTRING fine today"},
    ]
    created = []
    for e in entries:
        res = client.post("/api/feel", json=e)
        assert res.status_code == 201
        created.append(res.json())
    return created


# (a) summary with no entries returns null stats
def test_summary_no_entries_returns_null_stats(client):
    name = f"EmptyUser_{_SS_RUN}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code in (201, 409)
    users = client.get("/api/users", cookies=_admin_cookies()).json()
    u = next(u for u in users if u["name"] == name)
    empty_uid = u["id"]

    res = client.get("/api/feel/summary", params={"user_id": empty_uid})
    assert res.status_code == 200
    data = res.json()
    assert data["total_entries"] == 0
    assert data["avg_rpe"] is None
    assert data["min_rpe"] is None
    assert data["max_rpe"] is None
    assert data["avg_notes_length_chars"] is None


# (b) summary computes avg_rpe correctly
def test_summary_computes_avg_rpe(client, ss_user_id, ss_entries):
    res = client.get("/api/feel/summary", params={"user_id": ss_user_id, "from": "2026-01-01", "to": "2026-01-31"})
    assert res.status_code == 200
    data = res.json()
    assert data["total_entries"] >= 3
    # entries with RPE: 6 and 8; avg = 7.0
    rpe_entries = [e for e in ss_entries if e["rpe_1_to_10"] is not None]
    expected_avg = sum(e["rpe_1_to_10"] for e in rpe_entries) / len(rpe_entries)
    assert abs(data["avg_rpe"] - expected_avg) < 0.01


# (c) search finds case-insensitive matches
def test_search_case_insensitive(client, ss_user_id, ss_entries):
    for term in ("hamstring", "HAMSTRING", "Hamstring"):
        res = client.get("/api/feel/search", params={"user_id": ss_user_id, "q": term})
        assert res.status_code == 200
        data = res.json()
        assert data["count"] >= 2, f"expected >=2 results for q={term!r}, got {data['count']}"
        ids = {r["id"] for r in data["results"]}
        assert ss_entries[1]["id"] in ids
        assert ss_entries[2]["id"] in ids


# (d) search with <2-char query returns 422
def test_search_short_query_returns_422(client, ss_user_id):
    res = client.get("/api/feel/search", params={"user_id": ss_user_id, "q": "x"})
    assert res.status_code == 422


# (e) search highlights matched text in preview
def test_search_highlights_match_in_preview(client, ss_user_id, ss_entries):
    res = client.get("/api/feel/search", params={"user_id": ss_user_id, "q": "hamstring"})
    assert res.status_code == 200
    data = res.json()
    for result in data["results"]:
        assert "preview" in result
        assert "**hamstring**" in result["preview"].lower()
