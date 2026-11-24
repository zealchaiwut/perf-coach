"""Issue #1913 — single-flight sync/status, shared auth/me, lazy html2canvas."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATUS = (REPO / "frontend" / "js" / "v2-sync-status.js").read_text(encoding="utf-8")
TOOLBAR = (REPO / "frontend" / "js" / "lib" / "v2-sync-toolbar.js").read_text(encoding="utf-8")
NAV = (REPO / "frontend" / "js" / "v2-nav.js").read_text(encoding="utf-8")
REVAMP = (REPO / "frontend" / "js" / "revamp-ui.js").read_text(encoding="utf-8")
DRAWER = (REPO / "frontend" / "js" / "v2-run-drawer.js").read_text(encoding="utf-8")
LOG_HTML = (REPO / "frontend" / "pages" / "v2-training-log.html").read_text(encoding="utf-8")


def _else_of_v2_sync_status(src: str) -> str:
    """Return the `else { ... }` body that follows a V2SyncStatus presence check."""
    needle = "V2SyncStatus"
    i = src.find(needle)
    assert i != -1, "expected a V2SyncStatus branch"
    else_at = src.find("else {", i)
    assert else_at != -1, "expected else fallback after V2SyncStatus"
    start = src.find("{", else_at) + 1
    depth = 1
    j = start
    while j < len(src) and depth:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    return src[start : j - 1]


def test_poll_is_single_flight_with_5s_reuse():
    assert "var REUSE_MS = 5000" in STATUS
    assert "if (inflight) return inflight" in STATUS
    assert "lastPayload && lastFetchAt" in STATUS
    assert 'fetch("/api/sync/status"' in STATUS


def test_focus_poll_throttled_30s():
    assert "var FOCUS_MIN_MS = 30000" in STATUS
    assert "maybeFocusPoll" in STATUS
    assert "visibilitychange" in STATUS


def test_toolbar_does_not_fetch_status_when_v2_sync_status_exists():
    if_branch_end = TOOLBAR.find("} else {", TOOLBAR.find("if (global.V2SyncStatus)"))
    if_branch = TOOLBAR[TOOLBAR.find("if (global.V2SyncStatus)") : if_branch_end]
    assert "fetch(" not in if_branch
    assert "lastDetail" in if_branch
    assert "V2SyncStatus.poll" in if_branch
    else_body = _else_of_v2_sync_status(TOOLBAR)
    assert "/api/sync/status" in else_body


def test_nav_does_not_fetch_status_when_v2_sync_status_exists():
    if_at = NAV.find("if (window.V2SyncStatus")
    else_at = NAV.find("} else {", if_at)
    if_branch = NAV[if_at:else_at]
    assert "fetch(" not in if_branch
    assert "V2SyncStatus.poll" in if_branch
    else_body = NAV[else_at : NAV.find("}", NAV.find("fetch(", else_at)) + 1]
    assert "/api/sync/status" in else_body


def test_admin_tab_uses_shared_fetch_current_user():
    assert "fetchCurrentUser" in REVAMP
    assert "function initAdminTab" in REVAMP


def test_log_html_has_no_eager_html2canvas_script():
    assert "html2canvas.min.js" not in LOG_HTML
    assert '<script src="/js/lib/html2canvas' not in LOG_HTML


def test_run_drawer_loads_html2canvas_on_share():
    assert "loadHtml2Canvas" in DRAWER
    assert "/js/lib/html2canvas.min.js" in DRAWER
    assert "document.createElement('script')" in DRAWER
