"""PWA phase 1 static contracts (no live DB)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

REPO = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


def test_manifest_install_fields():
    man = json.loads((REPO / "frontend" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert man["name"] == "perf-coach"
    assert man["short_name"] == "Coach"
    assert man["start_url"] == "/m/today"
    assert man["scope"] == "/"
    assert man["display"] == "standalone"
    assert man["theme_color"] == "#1f3b8a"
    assert man["background_color"] == "#1f3b8a"
    sizes = {i["sizes"] for i in man["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes
    assert any(i.get("purpose") == "maskable" for i in man["icons"])
    for icon in man["icons"]:
        rel = icon["src"].lstrip("/")
        assert (REPO / "frontend" / rel.replace("icons/", "icons/", 1)).exists() or (
            REPO / "frontend" / "icons" / Path(icon["src"]).name
        ).exists()


def test_icon_files_exist():
    icons = REPO / "frontend" / "icons"
    assert (icons / "icon-192.png").is_file()
    assert (icons / "icon-512.png").is_file()
    assert (icons / "icon-512-maskable.png").is_file()
    assert (icons / "icon-192.png").stat().st_size > 32


def test_m_shell_has_pwa_head():
    html = (REPO / "frontend" / "pages" / "m-shell.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in html
    assert 'href="/manifest.webmanifest"' in html
    assert 'name="theme-color"' in html
    assert "#1f3b8a" in html
    assert 'rel="apple-touch-icon"' in html
    assert "/js/m/shell.js" in html
    assert "/css/m.css" in html


def test_v2_pages_link_manifest():
    pages = list((REPO / "frontend" / "pages").glob("v2-*.html"))
    missing = [p.name for p in pages if 'rel="manifest"' not in p.read_text(encoding="utf-8")]
    assert missing == []


def test_v2_nav_injects_pwa_meta():
    src = (REPO / "frontend" / "js" / "v2-nav.js").read_text(encoding="utf-8")
    assert "ensurePwaMeta" in src
    assert "/manifest.webmanifest" in src
    assert "theme-color" in src
    assert "apple-touch-icon" in src


def test_sw_precache_and_strategies():
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    sw = (REPO / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert version in sw
    assert "pc-shell-" in sw
    for path in ("/m/today", "/m/gym", "/m/body", "/css/m.css", "/js/m/store.js", "/manifest.webmanifest"):
        assert path in sw
    assert "/api/mobile/bundle" in sw
    assert "4000" in sw
    assert "skipWaiting" in sw
    install = sw.split("addEventListener(\"install\"")[1].split("addEventListener")[0]
    assert "skipWaiting" not in install
    assert 'event.data.type === "SKIP_WAITING"' in sw or 'event.data && event.data.type === "SKIP_WAITING"' in sw


def test_sw_route_headers():
    r = CLIENT.get("/sw.js")
    assert r.status_code == 200
    assert r.headers.get("service-worker-allowed") == "/"
    assert "javascript" in (r.headers.get("content-type") or "")


def test_manifest_route():
    r = CLIENT.get("/manifest.webmanifest")
    assert r.status_code == 200
    body = r.json() if "json" in (r.headers.get("content-type") or "") else json.loads(r.text)
    assert body["start_url"] == "/m/today"


def test_m_routes_without_revamp_gate():
    src = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
    block = src.split("def _serve_m_shell")[1].split("@app.get")[0]
    assert "_revamp_ui_enabled" not in block
    r = CLIENT.get("/m/today", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/login" in (r.headers.get("location") or "")


def test_device_cookie_passes_html_guard():
    r = CLIENT.get("/m/today", cookies={"device_session": "placeholder"}, follow_redirects=False)
    assert r.status_code == 200
    assert "m-pill" in r.text
    assert "Waiting to sync" in r.text


def test_auth_guard_accepts_device_cookie():
    src = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'path == "/m"' in src
    assert "DEVICE_COOKIE_NAME" in src.split("def _auth_guard")[1].split("async def _csrf_protect")[0]


def test_store_and_sync_contracts():
    store = (REPO / "frontend" / "js" / "m" / "store.js").read_text(encoding="utf-8")
    sync = (REPO / "frontend" / "js" / "m" / "sync.js").read_text(encoding="utf-8")
    for name in ("bundle", "outbox", "session_state", "meta"):
        assert f'"{name}"' in store or f"'{name}'" in store
    assert "client_mutation_id" in store
    assert "enqueue" in sync
    assert "flush" in sync
    assert "[2000, 4000, 8000, 16000, 32000, 60000]" in sync
    assert "duplicate" in sync
    assert "conflict" in sync
    assert "visibilitychange" in sync
    assert "If-None-Match" in sync
    assert "waking" in sync


def test_status_pill_states_and_touch():
    status = (REPO / "frontend" / "js" / "m" / "status.js").read_text(encoding="utf-8")
    css = (REPO / "frontend" / "css" / "m.css").read_text(encoding="utf-8")
    html = (REPO / "frontend" / "pages" / "m-shell.html").read_text(encoding="utf-8")
    assert "Synced" in status
    assert "Offline ·" in status
    assert "Waking the server" in status
    assert "Sync problem" in status
    assert "Keep phone version" in status
    assert "Use server version" in status
    assert "Keep using the app" in html
    assert "Free tier sleeps" in html
    assert "--touch: 44px" in css
    assert "min-height: var(--touch)" in css or "min-height: 44px" in css


def test_shell_suppresses_toast_during_session():
    shell = (REPO / "frontend" / "js" / "m" / "shell.js").read_text(encoding="utf-8")
    assert "session-active" in shell
    assert "New version ready" in shell
    assert "SKIP_WAITING" in shell
    gym = (REPO / "frontend" / "js" / "m" / "gym.js").read_text(encoding="utf-8")
    assert "session-active" in gym


def test_js_harness_enqueue_flush():
    harness = REPO / "tests" / "js" / "test_m_sync.mjs"
    assert harness.is_file()
    proc = subprocess.run(
        ["node", "--test", str(harness)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
