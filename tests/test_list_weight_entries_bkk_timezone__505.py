"""Tests for issue #505: list_weight_entries must use _today_bkk() for default date range.

AC anchors:
  (a) _today_bkk() is called instead of _date.today() in list_weight_entries default path
  (b) default from date is 89 days before Bangkok today
  (c) default to date is Bangkok today
  (d) explicit from/to params behave identically to before the change
  (e) all three weight endpoints use _today_bkk(), no _date.today() in weight date logic
"""
import datetime
import unittest.mock as mock
import pytest
import os
import uuid
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_PW = "test-505-pw"


def _create_user_and_login(client: httpx.Client) -> tuple[str, str]:
    name = f"t505_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert r.status_code == 201
    uid = r.json()["id"]
    pw_hash = _hash_pw(_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    login_res = client.post("/api/auth/login", json={"username": name, "password": _PW})
    assert login_res.status_code == 200
    return uid, login_res.cookies.get("session")


def _delete_user(client: httpx.Client, uid: str) -> None:
    client.delete(f"/api/users/{uid}", cookies=_admin_cookies())


# AC (a)/(b)/(c): default range uses Bangkok today, not UTC today
def test_default_range_uses_bangkok_today():
    """When from/to are omitted, the range should end on Bangkok today (from _today_bkk())."""
    import backend.main as _main

    fake_bkk = datetime.date(2026, 1, 15)

    with mock.patch.object(_main, "_today_bkk", return_value=fake_bkk):
        with httpx.Client(base_url=BASE_URL) as client:
            uid, cookie = _create_user_and_login(client)
            try:
                r = client.get("/api/weight-entries", cookies={"session": cookie})
                assert r.status_code == 200
                data = r.json()
                # The response should reflect Bangkok-anchored range:
                # to_date == 2026-01-15, from_date == 2026-01-15 - 89 days == 2025-10-18
                expected_to = fake_bkk.isoformat()
                expected_from = (fake_bkk - datetime.timedelta(days=89)).isoformat()
                assert data.get("to") == expected_to, (
                    f"Expected to={expected_to}, got {data.get('to')}"
                )
                assert data.get("from") == expected_from, (
                    f"Expected from={expected_from}, got {data.get('from')}"
                )
            finally:
                _delete_user(client, uid)


# AC (d): explicit params are unaffected
def test_explicit_dates_unaffected():
    """Explicit from/to params must pass through unchanged."""
    with httpx.Client(base_url=BASE_URL) as client:
        uid, cookie = _create_user_and_login(client)
        try:
            r = client.get(
                "/api/weight-entries",
                params={"from": "2026-01-01", "to": "2026-03-31"},
                cookies={"session": cookie},
            )
            assert r.status_code == 200
            data = r.json()
            assert data.get("from") == "2026-01-01"
            assert data.get("to") == "2026-03-31"
        finally:
            _delete_user(client, uid)


# AC (e): static code check — no _date.today() in the three weight endpoint functions
def test_no_date_today_in_weight_endpoints():
    """Grep backend/main.py weight endpoints for _date.today() — must find zero occurrences."""
    import ast
    import pathlib

    source = pathlib.Path("backend/main.py").read_text()
    tree = ast.parse(source)

    weight_fn_names = {"list_weight_entries", "create_weight_entry", "get_weight_chart"}
    offending = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in weight_fn_names:
                fn_source = ast.get_source_segment(source, node) or ""
                if "_date.today()" in fn_source:
                    offending.append(node.name)

    assert offending == [], (
        f"_date.today() still present in weight endpoint(s): {offending}. "
        "Must use _today_bkk() instead."
    )