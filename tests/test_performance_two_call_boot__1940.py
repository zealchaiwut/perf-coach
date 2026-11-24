"""Issue #1940 — two-call Performance boot, lazy sections, safe retries."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend" / "js" / "v2-performance.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "pages" / "v2-performance.html").read_text(encoding="utf-8")
RADAR = (ROOT / "frontend" / "js" / "lib" / "perf-radar.js").read_text(encoding="utf-8")
CSRF = (ROOT / "frontend" / "js" / "lib" / "csrf-fetch.js").read_text(encoding="utf-8")

OLD_GETS = (
    "/api/performance/hero",
    "/api/performance/score-cards",
    "/api/performance/a-race-readiness",
    "/api/performance/projection",
    "/api/performance/races",
    "/api/performance/coach-block",
    "/api/performance/radar",
)


def test_initial_request_is_above_the_fold_page_call():
    assert 'FIRST_SECTIONS = "hero,radar,score_cards"' in JS
    assert "fetchPage(FIRST_SECTIONS)" in JS
    assert "PERFORMANCE_PAGE" in JS and "/api/performance/page" in JS
    for path in OLD_GETS:
        if path == "/api/performance/races":
            assert "/api/performance/races?all=1" in JS
            assert JS.count(path) == 1
            continue
        assert path not in JS


def test_lazy_call_fires_once_on_scroll():
    assert 'LAZY_SECTIONS = "readiness,projection,races,coach,mobility,anchors"' in JS
    assert "IntersectionObserver" in JS
    assert 'rootMargin: "300px 0px"' in JS
    assert "if (lazyStarted) return" in JS
    assert "fetchPage(LAZY_SECTIONS)" in JS


def test_retry_only_network_or_502_504():
    assert "status === 502 || status === 503 || status === 504" in JS
    assert "if (!status) return true" in JS
    assert "fetchJSONWithRetry" not in JS
    assert "1000 + Math.floor(Math.random() * 1000)" in JS


def test_section_error_state_has_retry():
    assert "data-section-retry" in JS
    assert "Could not load this section" in JS
    assert "renderSectionError" in JS
    assert "sectionFailed" in JS


def test_hero_error_is_not_no_upcoming_a_race():
    assert 'renderSectionError(host, "A race", loadHero)' in JS
    assert "Could not load this section" in JS
    assert "No upcoming A race" in JS  # success empty-state, not the error path


def test_csrf_uses_shared_v2_csrf():
    assert "/js/lib/csrf-fetch.js" in HTML
    assert "function csrfToken" not in JS
    assert "/api/csrf-token" not in JS
    assert "X-CSRF-Token" in CSRF
    assert "window.sendJSON" in CSRF
    assert "function sendJSON" in JS


def test_mutations_refetch_only_affected_sections():
    assert 'refetchSections("radar"' in JS  # anchors + focus queue
    assert 'refetchSections("mobility,radar"' in JS
    assert 'refetchSections("hero,readiness,projection,races,score_cards,radar"' in JS
    assert 'refetchSections("readiness,hero"' in JS
    assert 'refetchSections("coach"' in JS


def test_no_perf_radar_self_mount_on_performance():
    assert 'data-perf-radar-boot="page"' in HTML
    assert 'data-perf-radar-boot") === "page"' in RADAR
    assert "function paint(" in RADAR
    assert "PerfRadar.paint" in JS
