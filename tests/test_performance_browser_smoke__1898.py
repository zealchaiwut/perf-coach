"""Issue #1898 — browser smoke for /v2/performance behind REVAMP_UI=1."""
import time

from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_cookie
from backend.main import app

SECTIONS = (
    "v2-perf-hero",
    "v2-perf-radar",
    "v2-perf-focus",
    "v2-perf-score-cards",
    "v2-perf-projection-wrap",
    "v2-perf-races",
    "v2-perf-coach",
    "v2-perf-drawer",
)


def test_performance_page_smoke_html(monkeypatch):
    monkeypatch.setenv("REVAMP_UI", "1")
    client = TestClient(app)
    uid = "00000000-0000-0000-0000-000000001898"
    client.cookies.set(COOKIE_NAME, create_session_cookie(uid, time.time()))
    resp = client.get("/v2/performance", follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    for eid in SECTIONS:
        assert f'id="{eid}"' in html, eid
    assert "/js/v2-performance.js" in html
    assert "/js/lib/csrf-fetch.js" in html
    assert "/js/lib/perf-radar.js" in html
