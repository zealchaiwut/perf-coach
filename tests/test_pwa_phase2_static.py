"""PWA phase 2 static contracts (Today + Hermes)."""
from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import mobile as mobile_router

REPO = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


def test_ping_is_204_with_no_db():
    src = inspect.getsource(mobile_router.mobile_ping)
    assert "Session" not in src
    assert "engine" not in src
    r = CLIENT.get("/api/mobile/ping")
    assert r.status_code == 204
    assert r.content in (b"", b"null")


def test_today_link_shape_in_source():
    src = inspect.getsource(mobile_router.mobile_today_link)
    assert "/m/gym/" in src
    assert "/m/today" in src
    assert "/m/body/weigh-in" in src
    assert "session_id" in src
    assert "session_name" in src


def test_hermes_doc_lists_urls_and_auth():
    doc = (REPO / "docs" / "pwa" / "hermes.md").read_text(encoding="utf-8")
    assert "GET /api/mobile/ping" in doc
    assert "GET /api/mobile/today-link" in doc
    assert "Authorization: Bearer" in doc
    assert "/m/today" in doc
    assert "/m/gym/{session_id}" in doc or "/m/gym/{id}" in doc
    assert "/m/body/weigh-in" in doc
    assert "10 minutes" in doc


def test_deep_links_served_by_shell():
    for path in ("/m/today", "/m/gym/abc", "/m/body/weigh-in"):
        r = CLIENT.get(path, cookies={"device_session": "x"}, follow_redirects=False)
        assert r.status_code == 200, path
        assert "m-main" in r.text


def test_today_first_paint_from_store():
    js = (REPO / "frontend" / "js" / "m" / "today.js").read_text(encoding="utf-8")
    assert "MStore.getBundle()" in js
    assert js.index("MStore.getBundle()") < js.index("/api/mobile/today-link")
    assert "refreshBundle" in js
    shell = (REPO / "frontend" / "js" / "m" / "shell.js").read_text(encoding="utf-8")
    assert "MToday.mount()" in shell
    gym = (REPO / "frontend" / "js" / "m" / "gym.js").read_text(encoding="utf-8")
    assert "sessionIdFromPath" in gym
    body = (REPO / "frontend" / "js" / "m" / "body.js").read_text(encoding="utf-8")
    assert "weigh-in" in body


def test_today_variants_harness():
    harness = REPO / "tests" / "js" / "test_m_today.mjs"
    proc = subprocess.run(
        ["node", "--test", str(harness)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
