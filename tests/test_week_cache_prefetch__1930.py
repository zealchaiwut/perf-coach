"""Issue #1930 — in-memory week cache and idle prefetch of adjacent weeks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
BOARD_JS = (ROOT / "frontend" / "js" / "v2-plan-week-board.js").read_text(encoding="utf-8")


def test_nav_returns_cached_week_without_blocking():
    assert "var weekCache = {}" in PLAN_JS
    assert "function cacheGet(ws)" in PLAN_JS
    assert "function cachePut(ws, data)" in PLAN_JS
    assert "Promise.resolve(cached)" in PLAN_JS
    nav = PLAN_JS.split("function navFetch")[1].split("function prefetchAdj")[0]
    assert "cacheGet(ws)" in nav
    assert "Promise.resolve(cached)" in nav
    assert "fetchWeek(ws" in nav


def test_idle_prefetch_adjacent_once():
    assert "function prefetchAdj(ws)" in PLAN_JS
    assert "requestIdleCallback" in PLAN_JS
    assert "setTimeout(cb, 1)" in PLAN_JS
    assert "var prefetchOnce = false" in PLAN_JS
    assert "prefetchAdj(state.ws)" in PLAN_JS
    assert "board,week_load" in PLAN_JS.split("function prefetchAdj")[1].split("function loadAll")[0]


def test_mutation_invalidates_and_return_sections_refills():
    assert "weekCacheInvalidate" in PLAN_JS
    assert "weekCachePut" in PLAN_JS
    mut = PLAN_JS.split("function applyMutation")[1].split("function renderRoadChart")[0]
    assert "weekCacheInvalidate" in mut
    assert "weekCachePut" in mut
    assert "weekCacheInvalidate" in BOARD_JS
    assert "afterSave" in BOARD_JS
