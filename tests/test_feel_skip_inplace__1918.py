"""Issue #1918 — feel/skip patch in place, stale-response guards, cached lookups."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
FEEL_JS = (REPO / "frontend" / "js" / "lib" / "v2-feel-buttons.js").read_text(encoding="utf-8")
DRAWER = (REPO / "frontend" / "js" / "v2-run-drawer.js").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    needle = "function " + name + "("
    start = src.find(needle)
    assert start != -1, name
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError("unclosed " + name)


def test_feel_tap_issues_exactly_one_request():
    patch = _fn(FEEL_JS, "patchFeeling")
    assert patch.count("fetch(") == 1
    assert "/api/workouts/" in patch
    assert "r.json()" in patch
    assert "body.feeling" in patch
    mount_at = LOG_JS.find("V2FeelButtons.mount")
    assert mount_at != -1
    feel_mount = LOG_JS[mount_at : mount_at + 400]
    assert "applyFeelInPlace" in feel_mount
    assert "refreshAll" not in feel_mount
    skip_at = LOG_JS.find("el.querySelectorAll('[data-plan-skip]')")
    feel_block = LOG_JS[LOG_JS.find("el.querySelectorAll('[data-feel-host]')") : skip_at]
    assert "refreshAll" not in feel_block
    assert "loadList" not in feel_block
    assert "loadMonth" not in feel_block


def test_skip_refetches_only_that_week_rollup():
    skip = LOG_JS[LOG_JS.find("data-plan-skip") :]
    skip = skip[: skip.find("el.querySelectorAll('[data-log-late]')")]
    assert "/api/planned-sessions/" in skip
    assert "applySkipInPlace" in skip
    assert "refreshWeekRollup" in skip
    assert "refreshAll" not in skip
    assert "loadList" not in skip
    assert "loadMonth" not in skip
    roll = _fn(LOG_JS, "refreshWeekRollup")
    assert "/api/weekly-rollup?week_start=" in roll
    assert "drawChart" in roll


def test_refresh_all_only_for_sync_and_explicit():
    init = _fn(LOG_JS, "init")
    assert "onRefresh: refreshAll" in init
    assert "v2:log-refresh" in init
    refresh = _fn(LOG_JS, "refreshAll")
    assert "loadMonth" in refresh
    assert "loadChart" in refresh
    assert "loadList(true)" in refresh


def test_month_rapid_next_keeps_last_response():
    month = _fn(LOG_JS, "loadMonth")
    assert "AbortController" in month
    assert "++state.monthSeq" in month
    assert "if (seq !== state.monthSeq) return" in month
    chart = _fn(LOG_JS, "loadChart")
    assert "AbortController" in chart
    assert "++state.chartSeq" in chart
    assert "if (seq !== state.chartSeq) return" in chart
    initial = _fn(LOG_JS, "fetchInitialWeeks")
    assert "++state.listSeq" in initial
    assert "if (seq !== state.listSeq) return" in initial


def test_drawer_prefs_and_shoes_cached_once():
    assert "function fetchPrefs" in DRAWER
    assert "function fetchShoes" in DRAWER
    assert "if (prefsCache) return Promise.resolve(prefsCache)" in DRAWER
    assert "if (shoesCache) return Promise.resolve(shoesCache)" in DRAWER
    assert "function clearLookups" in DRAWER
    assert "clearLookups: clearLookups" in DRAWER
    load = _fn(DRAWER, "loadCurrent")
    assert "fetchPrefs()" in load
    assert "fetchShoes()" in load
    assert load.count("fetch('/api/user-preferences'") == 0
    assert load.count("fetch('/api/athlete-shoes'") == 0
