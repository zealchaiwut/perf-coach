"""Tests for the Home today-focal-point UX improvement.

UX review finding: Home's main content area had no forward-looking "what
should I do today?" focal point — the prominent top-row slot beside
Readiness held a retrospective "Recent workouts" list instead. This adds a
"Today's plan" card in that slot (day/type/TSS for today's planned session,
or an honest "no plan" / "rest day" state), reusing the SAME
/api/planned-sessions data the Plan tab and the existing Week plan teaser
(home-brief-week-plan-card.js) already read — no new endpoint, no LLM.
Recent workouts is kept, not removed, and moves to its own card below
Training.

Deliberately PURE STATIC-SOURCE assertions (frontend/js/*.js and
frontend/pages/home.html read as text) — no live server and no live-DB
handle of any kind anywhere in this file. tests/conftest.py auto-marks any
test module that so much as mentions one of those live-service signatures
(see _LIVE_SERVICE_MARKERS there) as needing a live service, and CI's fast
gate excludes anything so marked; several sibling home-widget test files
(e.g. test_performance_prs_recent_workouts__441.py) mix a handful of
static-source checks into a file that also opens a live HTTP client, which
gets the WHOLE file skipped under the fast gate. Keeping this file free of
those signatures — including in comments/docstrings, which the marker scans
too — means it actually runs there. (Ask a fresh reader before adding an
import or a URL literal here: does it actually need a live service, or would
mentioning one just opt this file back out of the fast gate?)
"""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()
_HOME_GRID_JS = (_ROOT / "frontend" / "js" / "home-grid.js").read_text()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()
_TODAY_PLAN_CARD_PATH = _ROOT / "frontend" / "js" / "home-today-plan-card.js"


# ══════════════════════════════════════════════════════════════════════════
# The new widget file exists and is wired up
# ══════════════════════════════════════════════════════════════════════════

def test_today_plan_card_js_file_exists():
    assert _TODAY_PLAN_CARD_PATH.is_file(), (
        "frontend/js/home-today-plan-card.js must exist — the new Today's "
        "plan focal card"
    )


def _today_plan_card_js() -> str:
    return _TODAY_PLAN_CARD_PATH.read_text()


def test_today_plan_card_exposes_global():
    js = _today_plan_card_js()
    assert "window.HomeTodayPlanCard" in js, (
        "home-today-plan-card.js must expose window.HomeTodayPlanCard for "
        "home.js to call"
    )
    assert "render:" in js or "render :" in js, (
        "window.HomeTodayPlanCard must expose a render function"
    )


def test_home_html_has_today_plan_card_container():
    assert 'id="home-today-plan-card"' in _HOME_HTML, (
        "home.html must have a #home-today-plan-card container for the new "
        "focal card"
    )


def test_home_html_loads_today_plan_card_script():
    assert "js/home-today-plan-card.js" in _HOME_HTML, (
        "home.html must load js/home-today-plan-card.js"
    )


def test_today_plan_card_script_loads_before_home_js():
    """home.js's _initBriefCards calls window.HomeTodayPlanCard synchronously
    on page init, so the script tag order matters."""
    card_idx = _HOME_HTML.find("js/home-today-plan-card.js")
    home_js_idx = _HOME_HTML.find('src="js/home.js')
    assert card_idx != -1 and home_js_idx != -1
    assert card_idx < home_js_idx, (
        "js/home-today-plan-card.js must be loaded before js/home.js so "
        "window.HomeTodayPlanCard exists when home.js's init() runs"
    )


def test_home_js_initializes_today_plan_card():
    assert "HomeTodayPlanCard" in _HOME_JS, (
        "home.js must reference window.HomeTodayPlanCard to initialize the "
        "new card (see _initBriefCards)"
    )
    assert "home-today-plan-card" in _HOME_JS, (
        "home.js must look up the #home-today-plan-card container"
    )


# ══════════════════════════════════════════════════════════════════════════
# The card reuses existing plan data — no new endpoint, no invented source
# ══════════════════════════════════════════════════════════════════════════

def test_today_plan_card_reuses_planned_sessions_endpoint():
    js = _today_plan_card_js()
    assert "/api/planned-sessions" in js, (
        "home-today-plan-card.js must reuse GET /api/planned-sessions — the "
        "same endpoint the Plan tab and home-brief-week-plan-card.js already "
        "call — not a new data source"
    )


def test_today_plan_card_does_not_call_a_new_endpoint():
    js = _today_plan_card_js()
    # Every fetch() call target in this file must be the existing
    # planned-sessions endpoint (no /api/plan/today, /api/today-plan, etc.).
    import re
    fetch_targets = re.findall(r"fetch\(\s*['\"]([^'\"]*)['\"]", js)
    api_targets = [t for t in fetch_targets if t.startswith("/api")]
    assert api_targets, "expected at least one fetch() call to an /api endpoint"
    for t in api_targets:
        assert t.startswith("/api/planned-sessions"), (
            f"unexpected new API endpoint in home-today-plan-card.js: {t!r}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Rendering logic: real vs. estimated TSS, rest-day filtering, honest empty
# states (day/type/TSS per the issue spec)
# ══════════════════════════════════════════════════════════════════════════

def test_today_plan_card_shows_session_type_and_name():
    js = _today_plan_card_js()
    assert "session_type" in js, "must read session_type (the 'type' in day/type/TSS)"
    assert "p.name" in js or ".name" in js, "must render the planned session's name"


def test_today_plan_card_tss_distinguishes_actual_vs_estimated():
    js = _today_plan_card_js()
    assert "estimated_tss" in js, (
        "must use the same formula-only estimated_tss the Plan tab shows for "
        "still-open sessions (backend _planned_session_dict) — never fabricate"
        " a number of its own"
    )
    assert "actual" in js and ".tss" in js, (
        "must prefer the real logged actual.tss over the estimate once a "
        "session is done/matched"
    )
    assert "estimated" in js, (
        "must mark estimated TSS distinctly (e.g. a '~' prefix / is-estimated "
        "class) so it's never confused with a logged actual"
    )


def test_today_plan_card_filters_explicit_rest_sessions():
    """A PlannedSession row can itself have session_type == 'rest' (drafted
    rest slots) — that must be treated as the honest rest-day state, not
    rendered as a mislabeled session (see backend/main.py's own `non_rest`
    filter, applied the same way here)."""
    js = _today_plan_card_js()
    assert "'rest'" in js or '"rest"' in js, (
        "must special-case session_type 'rest' rather than rendering it as a "
        "generic (mislabeled) session"
    )


def test_today_plan_card_no_plan_empty_state():
    js = _today_plan_card_js()
    assert "No plan for today" in js, (
        "zero planned sessions for the WHOLE week must show an honest "
        "'No plan for today' state (a blank week means no plan was ever "
        "drafted, not that today was reviewed and cleared)"
    )


def test_today_plan_card_rest_day_empty_state():
    js = _today_plan_card_js()
    assert "Rest day" in js, (
        "a deliberate rest day within an otherwise-active plan must say so "
        "explicitly, distinct from the 'no plan at all' state"
    )


def test_today_plan_card_error_state():
    js = _today_plan_card_js()
    assert "renderUnavailable" in js or "Could not load" in js, (
        "a fetch failure must show an error state, not a silently blank card"
    )


def test_today_plan_card_loading_skeleton():
    js = _today_plan_card_js()
    assert "renderSkeleton" in js, "must show a loading skeleton while the fetch is in flight"


def test_today_plan_card_links_to_full_plan():
    js = _today_plan_card_js()
    assert "/log#plan" in js, "header must link out to the full Plan tab, matching the Week plan teaser"


def test_today_plan_card_uses_esc_for_user_strings():
    """Session names/notes are user-authored — must go through the shared
    escaper (issue #1603), not raw string concatenation into innerHTML."""
    js = _today_plan_card_js()
    assert "AppCommon.escapeHtml" in js or "function esc(" in js, (
        "must delegate to the shared escaper for user-supplied strings"
    )
    assert "esc(name)" in js or "esc(p.name" in js, (
        "the planned session name must be passed through esc() before being "
        "written into innerHTML"
    )


# ══════════════════════════════════════════════════════════════════════════
# CSS exists for the new card's states
# ══════════════════════════════════════════════════════════════════════════

def test_home_html_has_today_plan_card_css():
    assert ".tfc-empty" in _HOME_HTML, "home.html must style the empty/rest-day state"
    assert ".tfc-name" in _HOME_HTML, "home.html must style the planned session name"
    assert ".tfc-tss" in _HOME_HTML, "home.html must style the TSS badge"


def test_home_html_reuses_existing_tag_chip_classes():
    """Visual language must match the Plan tab / Week plan teaser's existing
    per-type chip colors (.hpl-tag--run/lift/plyo/stretch) rather than
    inventing a new palette."""
    js = _today_plan_card_js()
    assert "hpl-tag" in js, (
        "home-today-plan-card.js should reuse the existing .hpl-tag chip "
        "vocabulary (already styled in home.html) instead of a new one-off"
    )


# ══════════════════════════════════════════════════════════════════════════
# Recent workouts: kept, not removed — relocated below Training
# ══════════════════════════════════════════════════════════════════════════

def test_home_html_has_recent_workouts_container():
    assert 'id="home-recent-workouts-card"' in _HOME_HTML, (
        "Recent workouts must still exist on the page, just relocated"
    )


def test_home_html_no_longer_has_legacy_next_workout_card_id():
    assert 'id="home-next-workout-card"' not in _HOME_HTML, (
        "the old #home-next-workout-card slot must be gone — Today's plan "
        "took over that container id (renamed to #home-today-plan-card)"
    )


def test_recent_workouts_header_text_preserved():
    assert "Recent workouts" in _HOME_RTS_JS, (
        "the 'Recent workouts' header text must still be rendered somewhere "
        "— the information was relocated, not deleted"
    )


def test_recent_workouts_renderer_targets_new_container():
    assert "home-recent-workouts-card" in _HOME_RTS_JS, (
        "home-readiness-training-sleep.js must render Recent workouts into "
        "#home-recent-workouts-card"
    )
    assert "home-next-workout-card" not in _HOME_RTS_JS, (
        "home-readiness-training-sleep.js must not still target the old "
        "#home-next-workout-card id"
    )


# ══════════════════════════════════════════════════════════════════════════
# Grid registry (home-grid.js) — both widgets registered, in the right slots
# ══════════════════════════════════════════════════════════════════════════

def test_grid_registry_has_today_plan_card():
    assert "'home-today-plan-card'" in _HOME_GRID_JS, (
        "home-grid.js REGISTRY must include home-today-plan-card"
    )


def test_grid_registry_has_recent_workouts_card():
    assert "'home-recent-workouts-card'" in _HOME_GRID_JS, (
        "home-grid.js REGISTRY must include home-recent-workouts-card"
    )


def test_grid_registry_no_legacy_id():
    assert "home-next-workout-card" not in _HOME_GRID_JS, (
        "home-grid.js must not reference the retired home-next-workout-card id"
    )


def test_grid_height_pairs_updated():
    pairs_idx = _HOME_GRID_JS.find("HEIGHT_PAIRS")
    assert pairs_idx != -1
    # HEIGHT_PAIRS pairs Today's plan with Performance for equal top-row
    # height, same as it used to pair Recent workouts with Performance.
    snippet = _HOME_GRID_JS[pairs_idx:pairs_idx + 400]
    assert "home-today-plan-card" in snippet and "home-performance-card" in snippet, (
        "HEIGHT_PAIRS must pair home-today-plan-card with home-performance-card"
    )


def test_registry_order_today_plan_before_recent_workouts():
    """Today's plan is the forward-looking focal card (top row); Recent
    workouts is retrospective and now sits further down the page."""
    today_idx = _HOME_GRID_JS.find("'home-today-plan-card'")
    recent_idx = _HOME_GRID_JS.find("'home-recent-workouts-card'")
    assert today_idx != -1 and recent_idx != -1
    assert today_idx < recent_idx, (
        "home-today-plan-card must be registered before home-recent-workouts-card"
    )


def test_dom_order_today_plan_before_training_before_recent_workouts():
    today_pos = _HOME_HTML.find('id="home-today-plan-card"')
    training_pos = _HOME_HTML.find('id="home-training-card"')
    recent_pos = _HOME_HTML.find('id="home-recent-workouts-card"')
    assert today_pos != -1 and training_pos != -1 and recent_pos != -1
    assert today_pos < training_pos < recent_pos, (
        "DOM order must be Today's plan (top row) ... Training ... Recent "
        "workouts (below Training) — matching the relocation described in "
        "the grid comment"
    )


def test_today_plan_card_sits_near_readiness():
    """The whole point of the fix: the focal card must be in the SAME
    prominent top-row slot Readiness is in, not buried lower on the page."""
    readiness_pos = _HOME_HTML.find('id="home-top-row-right"')
    today_pos = _HOME_HTML.find('id="home-today-plan-card"')
    perf_pos = _HOME_HTML.find('id="home-performance-card"')
    assert readiness_pos != -1 and today_pos != -1 and perf_pos != -1
    assert readiness_pos < today_pos < perf_pos, (
        "Today's plan must sit directly between Readiness and Performance in "
        "the DOM — the prominent top-row slot Recent workouts used to occupy"
    )
