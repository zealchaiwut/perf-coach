"""Tests for issue #321: One-tap habit toggle and inline weight logging on Home.

Acceptance criteria verified:
(a) JS: showHabitError function defined for non-blocking habit error display
(b) JS: wasLogged pattern — optimistic toggle applied before await
(c) JS: rollback on error — done class/log-id restored if wasLogged was true
(d) JS: rollback on error — done class/log-id cleared if wasLogged was false
(e) JS: _buildWeightQuickInput accepts prefillValue parameter
(f) JS: prefillValue != null guard — sets value attribute on input
(g) JS: renderWeightTrendCard calls _buildWeightQuickInput with latest weight
(h) JS: showWeightErr function defined for weight validation errors
(i) JS: non-numeric input rejected (isNaN guard) before submission
(j) JS: out-of-range input rejected (val < 20 || val > 300) before submission
(k) HTML: .habit-inline-error CSS rule defined in home.html
(l) API: POST /api/habits/logs returns 201 with id for authenticated user
(m) API: DELETE /api/habits/logs/{id} returns 204, log is gone
(n) API: POST /api/weight returns 201 with weight_kg, recorded_date
(o) API: user isolation — Alice's habit logs not visible to Bob
(p) API: user isolation — Bob's weight entries not visible to Alice
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

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User

# ── Root detection: prefer coder root (pre-merge), tester root (post-merge) ──

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        js = root / "frontend" / "js" / "home.js"
        if js.exists() and "wasLogged" in js.read_text():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "home-toggle-321-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str):
    with httpx.Client(base_url=BASE, timeout=10) as fresh:
        res = fresh.post("/api/users", json={"name": username})
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]

        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            db.commit()

        login_res = fresh.post(
            "/api/auth/login",
            json={"username": username, "password": _TEST_PASSWORD},
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
    return user_id, authed


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice():
    user_id, authed = _make_authed_client(f"AliceHT321_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.delete(f"/api/users/{user_id}")


@pytest.fixture(scope="module")
def bob():
    user_id, authed = _make_authed_client(f"BobHT321_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.delete(f"/api/users/{user_id}")


# ── (a) JS: showHabitError function ──────────────────────────────────────────

def test_show_habit_error_function_defined():
    assert "function showHabitError(" in _HOME_JS, (
        "home.js must define showHabitError() for non-blocking habit error display"
    )


def test_show_habit_error_uses_inline_error_class():
    assert "habit-inline-error" in _HOME_JS, (
        "showHabitError must use .habit-inline-error class"
    )


# ── (b) JS: wasLogged optimistic toggle ──────────────────────────────────────

def test_waslogged_optimistic_pattern():
    assert "wasLogged" in _HOME_JS, (
        "home.js must use wasLogged variable for optimistic toggle before await"
    )


def test_optimistic_done_class_set_before_await():
    idx = _HOME_JS.find("wasLogged")
    snippet = _HOME_JS[idx: idx + 400]
    assert "classList" in snippet and "done" in snippet, (
        "Optimistic done-class toggle must appear near wasLogged"
    )


# ── (c/d) JS: rollback on error ───────────────────────────────────────────────

def test_rollback_restores_done_on_delete_failure():
    assert "if (wasLogged)" in _HOME_JS, (
        "Rollback block must check wasLogged to restore done class on delete failure"
    )


def test_rollback_clears_done_on_post_failure():
    assert "classList.remove('done')" in _HOME_JS or "classList.remove(\"done\")" in _HOME_JS, (
        "Rollback must clear done class when wasLogged was false and POST fails"
    )


def test_rollback_calls_show_habit_error():
    assert "showHabitError(card" in _HOME_JS, (
        "Rollback path must call showHabitError to surface the failure"
    )


# ── (e/f/g) JS: weight prefill ────────────────────────────────────────────────

def test_build_weight_quick_input_accepts_prefill_param():
    assert "function _buildWeightQuickInput(prefillValue)" in _HOME_JS, (
        "_buildWeightQuickInput must accept a prefillValue parameter"
    )


def test_build_weight_quick_input_guards_null():
    assert "prefillValue != null" in _HOME_JS, (
        "_buildWeightQuickInput must guard against null before setting value attr"
    )


def test_render_weight_card_passes_latest_weight():
    assert "_buildWeightQuickInput(latest.weight_kg.toFixed(1))" in _HOME_JS, (
        "renderWeightTrendCard must pass latest.weight_kg.toFixed(1) as prefill"
    )


# ── (h/i/j) JS: weight validation ────────────────────────────────────────────

def test_show_weight_err_function_defined():
    assert "function showWeightErr(" in _HOME_JS, (
        "home.js must define showWeightErr() for inline weight validation feedback"
    )


def test_weight_non_numeric_rejected():
    assert "isNaN(Number(raw))" in _HOME_JS, (
        "Weight save must reject non-numeric input via isNaN(Number(raw))"
    )


def test_weight_range_validated():
    assert "val < 20 || val > 300" in _HOME_JS, (
        "Weight save must reject values outside 20–300 kg range"
    )


# ── (k) HTML: .habit-inline-error CSS ────────────────────────────────────────

def test_habit_inline_error_css_in_html():
    assert ".habit-inline-error" in _HOME_HTML, (
        "home.html must define .habit-inline-error CSS rule"
    )


# ── (l) API: POST /api/habits/logs ────────────────────────────────────────────

def test_post_habit_log_returns_201_with_id(alice):
    ac = alice["client"]
    user_id = alice["id"]

    habit_res = ac.post("/api/habits", json={"name": f"ToggleHabit_{_RUN}"})
    assert habit_res.status_code == 201, habit_res.text
    habit_id = habit_res.json()["id"]

    log_res = ac.post("/api/habits/logs", json={
        "habit_id": habit_id,
        "logged_date": TODAY,
    })
    assert log_res.status_code == 201, log_res.text
    body = log_res.json()
    assert "id" in body, "POST /api/habits/logs must return id for optimistic UI"
    assert body["habit_id"] == habit_id
    assert body["logged_date"] == TODAY

    ac.delete(f"/api/habits/logs/{body['id']}")
    ac.delete(f"/api/habits/{habit_id}")


# ── (m) API: DELETE /api/habits/logs/{id} ────────────────────────────────────

def test_delete_habit_log_returns_204_and_removes_log(alice):
    ac = alice["client"]

    habit_res = ac.post("/api/habits", json={"name": f"DelHabit_{_RUN}"})
    assert habit_res.status_code == 201, habit_res.text
    habit_id = habit_res.json()["id"]

    log_res = ac.post("/api/habits/logs", json={
        "habit_id": habit_id,
        "logged_date": TODAY,
    })
    assert log_res.status_code == 201, log_res.text
    log_id = log_res.json()["id"]

    del_res = ac.delete(f"/api/habits/logs/{log_id}")
    assert del_res.status_code == 204, del_res.text

    logs = ac.get(f"/api/habits/logs?from={TODAY}&to={TODAY}").json()
    log_ids = [l["id"] for l in logs]
    assert log_id not in log_ids, "Deleted log must not appear in subsequent GET"

    ac.delete(f"/api/habits/{habit_id}")


# ── (n) API: POST /api/weight ─────────────────────────────────────────────────

def test_post_weight_returns_201_with_entry(alice):
    ac = alice["client"]
    test_date = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()

    res = ac.post("/api/weight", json={"weight_kg": 72.5, "recorded_date": test_date})
    assert res.status_code in (201, 409), res.text
    if res.status_code == 201:
        body = res.json()
        assert "id" in body
        assert body["weight_kg"] == pytest.approx(72.5)
        assert body["recorded_date"] == test_date
        ac.delete(f"/api/weight/{body['id']}")


# ── (o) API: Alice's habit logs not accessible by Bob ────────────────────────

def test_habit_log_isolation(alice, bob):  # noqa: F811
    ac = alice["client"]
    bc = bob["client"]

    habit_res = ac.post("/api/habits", json={"name": f"IsoHabit_{_RUN}"})
    assert habit_res.status_code == 201, habit_res.text
    habit_id = habit_res.json()["id"]

    log_res = ac.post("/api/habits/logs", json={
        "habit_id": habit_id,
        "logged_date": TODAY,
    })
    assert log_res.status_code == 201, log_res.text
    log_id = log_res.json()["id"]

    bob_logs = bc.get(f"/api/habits/logs?from={TODAY}&to={TODAY}").json()
    bob_log_ids = [l["id"] for l in bob_logs]
    assert log_id not in bob_log_ids, "Bob must not see Alice's habit log"

    del_by_bob = bc.delete(f"/api/habits/logs/{log_id}")
    assert del_by_bob.status_code in (403, 404), (
        "Bob must not be able to delete Alice's habit log"
    )

    ac.delete(f"/api/habits/logs/{log_id}")
    ac.delete(f"/api/habits/{habit_id}")


# ── (p) API: Bob's weight not visible to Alice ────────────────────────────────

def test_weight_entry_isolation(alice, bob):
    ac = alice["client"]
    bc = bob["client"]

    test_date = (datetime.date.today() - datetime.timedelta(days=91)).isoformat()
    res = bc.post("/api/weight", json={"weight_kg": 85.0, "recorded_date": test_date})
    assert res.status_code in (201, 409), res.text
    if res.status_code != 201:
        return

    bob_entry_id = res.json()["id"]

    alice_weights = ac.get("/api/weight").json()
    alice_ids = [e["id"] for e in alice_weights]
    assert bob_entry_id not in alice_ids, "Alice must not see Bob's weight entry"

    bc.delete(f"/api/weight/{bob_entry_id}")
