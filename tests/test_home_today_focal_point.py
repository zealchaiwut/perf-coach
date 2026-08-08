"""Tests for the Home today-focal-point UX improvement.

UX review finding: Home's main content area had no forward-looking "what
should I do today?" focal point. This was originally fixed with a dedicated
home-today-plan-card.js widget; home revamp v2 (docs/mocks/home-revamp-v2.html)
superseded that with a shared, reusable component — frontend/js/lib/next-up-card.js
(window.NextUpCard) — extracted from the Plan tab's own "Next up" hero
(training-plan.js's #plan-next-up) so Home's "Today's workout"
(#home-next-up) and the Plan tab render byte-for-byte identical markup off
the SAME /api/planned-sessions data, instead of home.html shipping a second,
divergent implementation. gridstack.js (frontend/js/home-grid.js) was also
removed in the same revamp — Home's layout is now a plain CSS Grid
(#home-cols) — so this file no longer reads that module either.

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
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_RTS_JS = (_ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()
_NEXT_UP_CARD_PATH = _ROOT / "frontend" / "js" / "lib" / "next-up-card.js"


# ══════════════════════════════════════════════════════════════════════════
# The shared component exists and is wired up
# ══════════════════════════════════════════════════════════════════════════

def test_next_up_card_js_file_exists():
    assert _NEXT_UP_CARD_PATH.is_file(), (
        "frontend/js/lib/next-up-card.js must exist — the shared 'Next up' / "
        "'Today's workout' hero, reused by both the Plan tab and Home"
    )


def _next_up_card_js() -> str:
    return _NEXT_UP_CARD_PATH.read_text()


def test_next_up_card_exposes_global():
    js = _next_up_card_js()
    assert "window.NextUpCard" in js, (
        "next-up-card.js must expose window.NextUpCard for home.js and "
        "training-plan.js to call"
    )
    assert "render:" in js or "render :" in js, (
        "window.NextUpCard must expose a render function"
    )


def test_home_html_has_next_up_container():
    assert 'id="home-next-up"' in _HOME_HTML, (
        "home.html must have a #home-next-up container for the shared "
        "Today's workout card"
    )


def test_home_html_loads_next_up_card_script():
    assert "js/lib/next-up-card.js" in _HOME_HTML, (
        "home.html must load js/lib/next-up-card.js"
    )


def test_next_up_card_script_loads_before_home_js():
    """home.js calls window.NextUpCard.render synchronously on page init, so
    the script tag order matters."""
    card_idx = _HOME_HTML.find("js/lib/next-up-card.js")
    home_js_idx = _HOME_HTML.find('src="js/home.js')
    assert card_idx != -1 and home_js_idx != -1
    assert card_idx < home_js_idx, (
        "js/lib/next-up-card.js must be loaded before js/home.js so "
        "window.NextUpCard exists when home.js's init() runs"
    )


def test_home_js_initializes_next_up_card():
    assert "NextUpCard" in _HOME_JS, (
        "home.js must reference window.NextUpCard to initialize the "
        "Today's workout card"
    )
    assert "home-next-up" in _HOME_JS, (
        "home.js must look up the #home-next-up container"
    )


def test_gridstack_layout_engine_removed():
    """home-grid.js (gridstack.js) was retired in the revamp — Home's layout
    is now a plain CSS Grid (#home-cols, see home.html's own rules).

    Checks for actual gridstack markers (CDN link, class="grid-stack", the
    old #home-dashboard-grid host) rather than a bare "gridstack" substring
    match, since home.html's own comments legitimately mention the retired
    library by name when documenting what replaced it."""
    assert not (_ROOT / "frontend" / "js" / "home-grid.js").exists(), (
        "frontend/js/home-grid.js must be deleted — gridstack.js is retired"
    )
    assert "gridstack.min" not in _HOME_HTML and "cdn.jsdelivr.net/npm/gridstack" not in _HOME_HTML, (
        "home.html must not link the gridstack.js CDN bundle"
    )
    assert "grid-stack" not in _HOME_HTML, (
        'home.html must not use gridstack\'s class="grid-stack" markup'
    )
    assert 'id="home-dashboard-grid"' not in _HOME_HTML, (
        "home.html must not have the old gridstack #home-dashboard-grid host"
    )
    assert 'home-col' in _HOME_HTML and 'display: contents' in _HOME_HTML, (
        "home.html must use .home-col stacks with display:contents on mobile"
    )
    assert 'id="home-cols"' in _HOME_HTML, (
        "home.html must have the #home-cols CSS Grid container that replaced "
        "gridstack's #home-dashboard-grid"
    )


# ══════════════════════════════════════════════════════════════════════════
# The card reuses existing plan data — no new endpoint, no invented source
# ══════════════════════════════════════════════════════════════════════════

def test_next_up_card_takes_days_as_input_not_a_fetch():
    """next-up-card.js is a pure render(host, opts) component — it takes
    opts.days rather than fetching its own copy, so the SAME
    /api/planned-sessions response can be shared across Home's morning
    session row, Today's workout, and Week plan teaser (one fetch, three
    consumers — see home.js's _fetchWeekPlannedSessions)."""
    js = _next_up_card_js()
    assert "opts.days" in js or "opts && opts.days" in js or "days = opts.days" in js, (
        "next-up-card.js must read its session list from opts.days"
    )
    assert "fetch(" not in js, (
        "next-up-card.js must not fetch its own data — it must be handed "
        "opts.days by its caller (home.js / training-plan.js)"
    )


def test_home_js_fetches_planned_sessions_once_for_next_up():
    assert "/api/planned-sessions" in _HOME_JS, (
        "home.js must fetch /api/planned-sessions and pass the result to "
        "NextUpCard.render (and the morning session row, and the week plan "
        "teaser) — not a new endpoint"
    )


# ══════════════════════════════════════════════════════════════════════════
# Rendering logic: real vs. estimated TSS, rest-day filtering, honest empty
# state (day/type/TSS per the issue spec)
# ══════════════════════════════════════════════════════════════════════════

def test_next_up_card_shows_session_type_and_name():
    js = _next_up_card_js()
    assert "session_type" in js, "must read session_type (the 'type' in day/type/TSS)"
    assert "p.name" in js or ".name" in js, "must render the planned session's name"


def test_next_up_card_tss_distinguishes_actual_vs_estimated():
    js = _next_up_card_js()
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
        "flag) so it's never confused with a logged actual"
    )


def test_next_up_card_filters_explicit_rest_sessions():
    """A PlannedSession row can itself have session_type == 'rest' (drafted
    rest slots) — that must be excluded from "next up" candidates, not
    rendered as a mislabeled session (see backend/main.py's own `non_rest`
    filter, applied the same way here)."""
    js = _next_up_card_js()
    assert "'rest'" in js or '"rest"' in js, (
        "must special-case session_type 'rest' rather than treating it as an "
        "open, pickable session"
    )


def test_next_up_card_empty_state():
    js = _next_up_card_js()
    assert "Nothing scheduled" in js, (
        "zero open planned sessions from today forward must show an honest "
        "empty state, not a blank card"
    )


def test_next_up_card_uses_esc_for_user_strings():
    """Session names/notes are user-authored — must go through the shared
    escaper (issue #1603), not raw string concatenation into innerHTML."""
    js = _next_up_card_js()
    assert "AppCommon.escapeHtml" in js or "function esc(" in js, (
        "must delegate to the shared escaper for user-supplied strings"
    )
    assert "esc(" in js, "planned session strings must be passed through esc() before innerHTML"


# ══════════════════════════════════════════════════════════════════════════
# Recent workouts: kept, not removed — bottom of the right column
# ══════════════════════════════════════════════════════════════════════════

def test_home_html_has_recent_workouts_container():
    assert 'id="home-recent-workouts-card"' in _HOME_HTML, (
        "Recent workouts must still exist on the page, just relocated"
    )


def test_home_html_no_longer_has_legacy_ids():
    for legacy_id in ("home-next-workout-card", "home-today-plan-card", "home-perf-container"):
        assert f'id="{legacy_id}"' not in _HOME_HTML, (
            f"legacy container #{legacy_id} must be gone from home.html"
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
# Layout — Today's workout leads the right column, beside Readiness's row
# ══════════════════════════════════════════════════════════════════════════

def test_dom_order_next_up_before_training_before_recent_workouts():
    next_up_pos = _HOME_HTML.find('id="home-next-up"')
    training_pos = _HOME_HTML.find('id="home-training-card"')
    recent_pos = _HOME_HTML.find('id="home-recent-workouts-card"')
    assert next_up_pos != -1 and training_pos != -1 and recent_pos != -1
    assert next_up_pos < training_pos < recent_pos, (
        "DOM order must be Today's workout (top of right column) ... "
        "Training ... Recent workouts (bottom of right column)"
    )


def test_next_up_sits_near_readiness():
    """The whole point of the fix: the focal card must be in the SAME
    prominent top slot Readiness occupies in the other column, not buried
    lower on the page."""
    readiness_pos = _HOME_HTML.find('id="home-top-row-right"')
    next_up_pos = _HOME_HTML.find('id="home-next-up"')
    cols_pos = _HOME_HTML.find('id="home-cols"')
    assert readiness_pos != -1 and next_up_pos != -1 and cols_pos != -1
    assert cols_pos < readiness_pos and cols_pos < next_up_pos, (
        "Both Readiness and Today's workout must be inside #home-cols"
    )
