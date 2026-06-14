"""Tests for issue #521: Add logging streak and adherence indicator to weight page.

AC anchors verified:
  (ac1) Current consecutive logging streak displayed on weight page.
  (ac2) Adherence ratio (logged / last 14 days) surfaced near/below page subtitle.
  (ac3) Both computed client-side from existing entry data — no new API endpoint.
  (ac4) Streak resets to 0 if today or yesterday has no entry.
  (ac5) Display updates immediately when entry added or deleted within session.
  (ac6) Values render correctly when zero entries exist (streak: 0, adherence: 0/14).
"""
import pathlib
import subprocess
import json
import datetime
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "frontend" / "js"
PAGES_DIR = ROOT / "frontend" / "pages"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()

TODAY = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _run_js(snippet: str) -> object:
    """Run JS snippet via node and return parsed JSON output."""
    # Extract utility functions and the streak/adherence functions from weight.js
    # We pull everything up to (but not past) the DOM-dependent init.
    lines = WEIGHT_JS.splitlines()
    # Grab everything before DOMContentLoaded
    safe_lines = []
    for line in lines:
        if "DOMContentLoaded" in line:
            break
        safe_lines.append(line)
    safe_js = "\n".join(safe_lines)

    script = textwrap.dedent(f"""
        'use strict';
        // Stub browser globals
        const document = {{ getElementById: () => null, querySelectorAll: () => [] }};
        {safe_js}
        {snippet}
    """)
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"JS error: {result.stderr}"
    return json.loads(result.stdout.strip())


# ── AC1: Streak element present in HTML ──────────────────────────────────────

def test_ac1_streak_element_in_html():
    assert "streak" in WEIGHT_HTML.lower(), \
        "weight.html must contain a streak display element"


def test_ac1_streak_element_has_id():
    assert 'id="streak' in WEIGHT_HTML or "id='streak" in WEIGHT_HTML, \
        "HTML must have an element with id starting with 'streak'"


def test_ac1_streak_js_function_defined():
    assert "_computeStreak" in WEIGHT_JS, \
        "weight.js must define _computeStreak function"


def test_ac1_streak_render_function_defined():
    assert "renderStreakAndAdherence" in WEIGHT_JS or "renderStreak" in WEIGHT_JS, \
        "weight.js must define a function to render streak and adherence values"


# ── AC2: Adherence element present near subtitle ──────────────────────────────

def test_ac2_adherence_element_in_html():
    assert "adherence" in WEIGHT_HTML.lower(), \
        "weight.html must contain an adherence display element"


def test_ac2_adherence_element_has_id():
    assert 'id="adherence' in WEIGHT_HTML or "id='adherence" in WEIGHT_HTML, \
        "HTML must have an element with id starting with 'adherence'"


def test_ac2_adherence_placed_near_subtitle():
    html = WEIGHT_HTML
    # Use specific id attributes to find HTML elements (not CSS class names)
    sub_idx = html.find('id="page-subtitle"')
    adh_idx = html.find('id="adherence-value"')
    assert sub_idx != -1, "HTML must have element with id='page-subtitle'"
    assert adh_idx != -1, "HTML must have element with id='adherence-value'"
    # Adherence element must appear within 400 chars of the subtitle element in the HTML body
    assert abs(sub_idx - adh_idx) < 400, \
        "Adherence element must be placed near the page subtitle (within 400 chars in HTML body)"


def test_ac2_adherence_js_function_defined():
    assert "_computeAdherence" in WEIGHT_JS, \
        "weight.js must define _computeAdherence function"


# ── AC3: Client-side only, no new API endpoint ────────────────────────────────

def test_ac3_no_new_api_endpoint_for_streak():
    # The streak and adherence come from the existing /api/weight-entries data
    assert "/api/streak" not in WEIGHT_JS, \
        "Must not add new /api/streak endpoint — use existing entry data"


def test_ac3_no_new_api_endpoint_for_adherence():
    assert "/api/adherence" not in WEIGHT_JS, \
        "Must not add new /api/adherence endpoint — use existing entry data"


def test_ac3_streak_uses_existing_entries():
    # _computeStreak should take entries as argument (client-side computation)
    assert "_computeStreak(" in WEIGHT_JS, \
        "_computeStreak must be called with entries array from existing API data"


# ── AC4: Streak computation logic ─────────────────────────────────────────────

def test_ac4_streak_five_consecutive_ending_today():
    # 5 entries ending today → streak = 5
    entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(5)
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 5, f"5 consecutive entries ending today → streak 5, got {result}"


def test_ac4_streak_gap_missing_today_and_yesterday():
    # Entries exist but gap at today AND yesterday → streak = 0
    entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(2, 7)  # days 2-6 ago only
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 0, f"Gap at today+yesterday → streak 0, got {result}"


def test_ac4_streak_missing_today_but_has_yesterday():
    # Has yesterday but not today → streak resets to 0 (AC: resets if today OR yesterday missing)
    entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(1, 6)  # yesterday through 5 days ago
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 0, f"Missing today → streak 0, got {result}"


def test_ac4_streak_consecutive_starting_yesterday():
    # Has today → should count from today backwards
    entries = [
        {"entry_date": str(datetime.date.today())},
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=1))},
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=2))},
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 3, f"3 consecutive entries ending today → streak 3, got {result}"


def test_ac4_streak_gap_in_middle():
    # today + 4 days ago (gap on days 1-3) → streak = 1
    entries = [
        {"entry_date": TODAY},
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=4))},
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 1, f"Today only (gap before) → streak 1, got {result}"


# ── AC5: render called in all mutation paths ───────────────────────────────────

def test_ac5_render_called_in_reload():
    assert "renderStreakAndAdherence" in WEIGHT_JS, \
        "renderStreakAndAdherence must be defined"
    # It must be called inside _reload (after entries are updated)
    reload_start = WEIGHT_JS.find("async function _reload(")
    reload_end = WEIGHT_JS.find("\nasync function ", reload_start + 1)
    if reload_end == -1:
        reload_end = len(WEIGHT_JS)
    reload_body = WEIGHT_JS[reload_start:reload_end]
    assert "renderStreakAndAdherence" in reload_body, \
        "renderStreakAndAdherence must be called inside _reload()"


def test_ac5_render_called_after_entry_reload():
    # _reloadEntries must call renderStreakAndAdherence
    reload_start = WEIGHT_JS.find("async function _reloadEntries(")
    reload_end = WEIGHT_JS.find("\nasync function ", reload_start + 1)
    if reload_end == -1:
        reload_end = len(WEIGHT_JS)
    reload_body = WEIGHT_JS[reload_start:reload_end]
    assert "renderStreakAndAdherence" in reload_body, \
        "renderStreakAndAdherence must be called inside _reloadEntries() for live updates"


# ── AC6: Zero entries state ────────────────────────────────────────────────────

def test_ac6_streak_zero_when_no_entries():
    result = _run_js("""
        const entries = [];
        console.log(JSON.stringify(_computeStreak(entries)));
    """)
    assert result == 0, f"No entries → streak 0, got {result}"


def test_ac6_adherence_zero_when_no_entries():
    result = _run_js("""
        const entries = [];
        console.log(JSON.stringify(_computeAdherence(entries)));
    """)
    assert result == 0, f"No entries → adherence 0, got {result}"


def test_ac6_adherence_14_days_window():
    # 14 entries in 14 days → adherence 14
    entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(14)
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeAdherence(entries)));
    """)
    assert result == 14, f"14 entries in 14 days → adherence 14, got {result}"


def test_ac6_adherence_partial_window():
    # 7 entries in 14 days → adherence 7
    entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(0, 14, 2)  # every other day
    ]
    result = _run_js(f"""
        const entries = {json.dumps(entries)};
        console.log(JSON.stringify(_computeAdherence(entries)));
    """)
    assert result == 7, f"7 entries in 14 days → adherence 7, got {result}"


def test_ac6_adherence_ignores_older_than_14_days():
    # entries older than 14 days must not count
    old_entries = [
        {"entry_date": str(datetime.date.today() - datetime.timedelta(days=i))}
        for i in range(15, 30)  # 15-29 days ago
    ]
    result = _run_js(f"""
        const entries = {json.dumps(old_entries)};
        console.log(JSON.stringify(_computeAdherence(entries)));
    """)
    assert result == 0, f"Entries older than 14 days must not count, got {result}"


def test_ac6_html_shows_denominator_14():
    # The adherence display should reference "14" (days) in static HTML or JS
    assert "14" in WEIGHT_JS and ("adherence" in WEIGHT_JS.lower() or "14 day" in WEIGHT_JS.lower()), \
        "JS must use 14-day window for adherence calculation"
