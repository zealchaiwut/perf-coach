"""The consult blob and the decisions log are reachable from the nav.

Both existed as working backend surfaces with no way in:

- ``GET /api/coach/consult`` shipped with the coach export (#1593) but only the
  *daily* blob got a button, so the check-in — the half that asks questions and
  produces a change list — was curl-only.
- ``/decisions`` was registered in ``main.py``'s ``_PAGES`` but ``nav.js`` never
  linked it, and no page linked it either. The export cites decision rows by
  date, so the loop's own memory was URL-only.

Both were listed in ``docs/lean-program-operator-guide.md`` §9 as known gaps.
That listing is the reason they were found; these tests are the reason they
stay fixed.

**Update (feature/coach-tab):** the standalone ``/decisions`` page and the
nav dropdown's "Copy for consult" item are now one linear flow, ``/coach`` —
start a check-in, paste the changes back, see the history — reachable from a
single new top-level nav entry (``Coach``, superseding the old ``Decisions``
link). ``/decisions`` itself becomes a redirect shim to ``/coach`` (same
pattern as ``/preferences``), so old bookmarks still land somewhere real. The
nav dropdown's copy buttons are untouched by this — "Copy for consult" stays
available there too, per product decision; this is additive, not a reduction.

Static assertions over ``nav.js`` — the nav is vanilla JS with no bundler and
no DOM harness in this repo, so reading the source is the alternative to not
testing the wiring at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NAV_JS = REPO / "frontend" / "js" / "nav.js"
MAIN_PY = REPO / "backend" / "main.py"
COACH_PY = REPO / "backend" / "routers" / "coach.py"


@pytest.fixture(scope="module")
def nav() -> str:
    return NAV_JS.read_text()


# ── The consult button ────────────────────────────────────────────────────────

def test_consult_button_is_rendered(nav):
    assert 'id="gn-copy-consult"' in nav


def test_consult_button_targets_the_consult_endpoint(nav):
    assert '"/api/coach/consult"' in nav, "nav.js does not reference the consult endpoint"


def test_the_consult_endpoint_actually_exists():
    """A button pointing at a route that doesn't exist is worse than no button."""
    assert '@router.get("/api/coach/consult"' in COACH_PY.read_text()


def test_consult_and_daily_are_separate_endpoints(nav):
    """The daily paste stamps last_coach_export_at; the consult deliberately does
    not. Pointing both buttons at one endpoint would silence the next day's
    season check."""
    assert '"/api/coach/export/paste"' in nav
    assert '"/api/coach/consult"' in nav


def test_both_buttons_are_wired(nav):
    """Rendered but unwired is the failure this whole review kept finding."""
    wire_start = nav.index("function _wireCopyForClaude(")
    # Boundary on the next TOP-LEVEL declaration (two-space indent). Searching
    # for a bare "function " lands inside the addEventListener callbacks and
    # truncates the body before the second button.
    wire_end = nav.index("\n  function ", wire_start + 10)
    body = nav[wire_start:wire_end]
    assert "gn-copy-claude" in body
    assert "gn-copy-consult" in body


def test_copy_trigger_has_an_accessible_name(nav):
    """The trigger's visible <span> label is hidden at mobile widths (icon +
    caret only), so aria-label is the only name a screen reader gets there."""
    btn = nav[nav.index('id="gn-copy-trigger"') - 200:]
    btn = btn[: btn.index("</button>")]
    assert "aria-label=" in btn


def test_copy_helper_is_shared_not_duplicated(nav):
    """One fetch/clipboard/toast/retry path for both blobs. A second copy would
    drift — see the 17 divergent esc() copies this codebase already carries."""
    assert nav.count("function _copyForClaude(") == 1


def test_retry_preserves_the_endpoint(nav):
    """The error toast offers a retry; retrying the consult must not silently
    re-fetch the daily blob."""
    assert "_copyForClaude(btn, endpoint, label)" in nav


# ── The Coach link (supersedes the old standalone Decisions link) ─────────────

def test_coach_is_in_the_nav_links(nav):
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    links = nav[links_start:links_end]
    assert "'/coach'" in links


def test_coach_link_is_not_disabled(nav):
    """Other LINKS entries have carried `disabled: true` in the past (e.g. the
    now-removed `/calendar` link). Coach must not inherit that by copy-paste."""
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    for line in nav[links_start:links_end].splitlines():
        if "/coach" in line:
            assert "disabled" not in line
            break
    else:
        pytest.fail("no /coach entry found in LINKS")


def test_decisions_is_no_longer_a_top_level_nav_link(nav):
    """Coach supersedes the standalone Decisions link — LINKS should carry
    exactly one of the two, not both left behind by copy-paste."""
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    links = nav[links_start:links_end]
    assert "'/decisions'" not in links


def test_the_coach_page_route_exists():
    assert '"coach": "coach.html"' in MAIN_PY.read_text()


def test_the_decisions_page_route_still_exists_as_a_shim():
    """Not hard-deleted — old /decisions bookmarks must land somewhere real,
    not 404. See frontend/pages/decisions.html, which now redirects to
    /coach (same pattern as preferences.html -> /training-log)."""
    assert '"decisions": "decisions.html"' in MAIN_PY.read_text()


def test_decisions_page_redirects_to_coach():
    decisions_html = (REPO / "frontend" / "pages" / "decisions.html").read_text()
    assert "/coach" in decisions_html
    assert "location.replace" in decisions_html


def test_coach_matches_its_legacy_html_path(nav):
    """Every page is served at both /x and /x.html; the active-state match list
    has to cover both or the nav item never highlights."""
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    for line in nav[links_start:links_end].splitlines():
        if "/coach" in line:
            assert "/coach.html" in line
            break


# ── The Bangkok stamp ─────────────────────────────────────────────────────────

def test_copy_toast_stamps_bangkok_not_browser_local():
    """This app is single-timezone Asia/Bangkok. `new Date().toISOString()`
    stamps UTC, which is the previous day for the first 7 hours of every
    Bangkok day — the same class of bug as #1600."""
    nav_src = NAV_JS.read_text()
    copy_fn = nav_src[nav_src.index("function _copyForClaude(") :]
    copy_fn = copy_fn[: copy_fn.index("function _wireCopyForClaude(")]
    assert "Asia/Bangkok" in copy_fn
    assert "toISOString" not in copy_fn


# ── Loading state during the ~12s build ────────────────────────────────────────
# The export is consistently slow (dev→remote Neon; see
# docs/pre-production-review-status.md §"UX judgment calls" item 3) and, before
# this fix, gave no feedback beyond a button label swap — nothing told the
# athlete it was working rather than stuck, and nothing explained what the
# button was about to copy before they clicked it.

def test_copy_fn_shows_a_persisted_building_toast(nav):
    """The button's own "Building…" label is easy to miss; the toast is the
    loud half of the same signal and must survive the whole ~12s wait, not
    the normal 4s auto-dismiss (see _copyToast's `persist` branch)."""
    copy_fn = nav[nav.index("function _copyForClaude(") : nav.index("function _wireCopyForClaude(")]
    assert "persist: true" in copy_fn
    assert "Building your training summary" in copy_fn
    assert "Building your check-in" in copy_fn


def test_persisted_toast_is_exempted_from_auto_dismiss(nav):
    toast_fn = nav[nav.index("function _copyToast(") : nav.index("function _copyCharCount(")]
    assert "opts.persist" in toast_fn


def test_building_toast_differs_by_endpoint_without_new_helper_params(nav):
    """The retry path calls `_copyForClaude(btn, endpoint, label)` verbatim
    (see test_retry_preserves_the_endpoint) — the building-toast copy must be
    derived from `endpoint` inside the function, not bolted on as a new
    parameter that would silently break that call."""
    copy_fn = nav[nav.index("function _copyForClaude(") : nav.index("function _wireCopyForClaude(")]
    assert "endpoint === CONSULT_ENDPOINT" in copy_fn


def test_copy_items_have_a_pre_copy_explanation(nav):
    """A short, always-in-the-DOM explanation of what each menu item copies.
    The two buttons used to carry this as a hover .info-tip-bubble; merged
    into one dropdown, it's plain body text under each item's title instead
    (see the CSS comment above .gn-copy-item) — a menu is read top-to-bottom
    so hover-to-reveal buys nothing, and it removes a second nested
    absolutely-positioned bubble that could reintroduce the off-screen
    clipping e4fb2e2c fixed for the old standalone buttons."""
    for btn_id in ("gn-copy-claude", "gn-copy-consult"):
        start = nav.index('id="' + btn_id + '"')
        end = nav.index("</button>", start)
        item = nav[start:end]
        assert "gn-copy-item-title" in item
        assert "gn-copy-item-desc" in item
        # No hover-triggered bubble should have crept back in here.
        assert "info-tip-bubble" not in item


def test_pre_copy_explanation_is_reachable_at_every_width():
    """Unlike the old per-button info-tip bubble (hover/focus only, and the
    mobile query had to explicitly exempt it from the label-hiding rule), the
    dropdown item's .gn-copy-item-desc is plain text belonging to a class the
    mobile media query never touches — reachable at every width as soon as
    the menu is open, with no exemption to maintain."""
    nav_src = NAV_JS.read_text()
    mobile_start = nav_src.index("@media (max-width:880px)")
    mobile = nav_src[mobile_start : nav_src.index("]", mobile_start)]
    # No rule in the mobile block hides the description class.
    assert "gn-copy-item-desc{display:none" not in mobile
    assert "gn-copy-item-desc {display:none" not in mobile
    # The trigger's own label is what mobile hides — icon + caret carry it,
    # backed by the aria-label test above.
    assert "gn-copy-trigger span{display:none;}" in mobile


# ── The merged dropdown ─────────────────────────────────────────────────────
# Product decision: the two actions stay distinct (same data, different
# purposes — one open-ended, one ending in a /decisions change list) but move
# from two peer buttons in the bar to one entry point with a dropdown.

def test_single_trigger_replaces_the_two_peer_buttons(nav):
    """Exactly one clickable entry point sits in the nav bar itself; the two
    choices live inside the panel it opens, not beside it."""
    assert 'id="gn-copy-trigger"' in nav
    assert 'aria-haspopup="true"' in nav[nav.index('id="gn-copy-trigger"') - 50 :][:400]


def test_dropdown_panel_is_right_aligned_not_centered(nav):
    """The trigger sits at the nav's right edge next to the env badge/avatar —
    a centered panel would clip off-screen there exactly the way the old
    info-tip bubbles did before e4fb2e2c. Right-aligning (right:0;left:auto)
    is the same fix already proven for .gn-profile-menu, reused here."""
    css_start = nav.index(".global-nav .gn-copy-dropdown{")
    css_end = nav.index("}", css_start)
    rule = nav[css_start:css_end]
    assert "right:0" in rule
    assert "left:auto" in rule


def test_dropdown_items_are_inside_the_panel(nav):
    menu_start = nav.index('id="gn-copy-dropdown"')
    menu_end = nav.index('"gn-env"', menu_start)  # next sibling markup after the menu closes
    body = nav[menu_start:menu_end]
    assert 'id="gn-copy-claude"' in body
    assert 'id="gn-copy-consult"' in body


def test_selecting_an_item_closes_the_dropdown(nav):
    """The panel must not linger open after a choice is made — both item click
    handlers close it before kicking off the copy."""
    wire_start = nav.index("function _wireCopyForClaude(")
    wire_end = nav.index("\n  function ", wire_start + 10)
    body = nav[wire_start:wire_end]
    assert body.count("_closeCopyDropdown()") == 2


def test_copy_menu_is_wired_in_build_nav(nav):
    build_start = nav.index("function buildNav(")
    build_end = nav.index("\n  // ── Copy for Claude")
    body = nav[build_start:build_end]
    assert "_wireCopyMenu(nav)" in body


# ── The /coach page reuses nav.js's copy logic, not a second copy ──────────────
# The ticket's explicit instruction: don't reimplement the fetch/clipboard/toast
# path a second time in coach.js. nav.js is a single IIFE with nothing
# copy-related previously exposed on window, so the fix is exposing the one
# function coach.js needs.

COACH_JS = REPO / "frontend" / "js" / "coach.js"
COACH_HTML = REPO / "frontend" / "pages" / "coach.html"


@pytest.fixture(scope="module")
def coach_js() -> str:
    return COACH_JS.read_text()


def test_navcopy_is_exposed_on_window(nav):
    assert "window.NavCopy" in nav
    assert "copyForClaude: _copyForClaude" in nav


def test_coach_js_calls_the_shared_helper_not_a_new_one(coach_js):
    assert "window.NavCopy" in coach_js
    assert "NavCopy.copyForClaude" in coach_js
    # No second _copyForClaude/fetch-and-clipboard implementation in coach.js.
    assert "function _copyForClaude(" not in coach_js
    assert "navigator.clipboard" not in coach_js


def test_coach_js_uses_the_consult_endpoint_via_navcopy(coach_js):
    assert "NavCopy.CONSULT_ENDPOINT" in coach_js
    # Not a hardcoded second copy of the literal endpoint string.
    assert '"/api/coach/consult"' not in coach_js


def test_coach_html_has_a_checkin_button_wired_by_coach_js():
    html = COACH_HTML.read_text()
    js = COACH_JS.read_text()
    assert 'id="coach-checkin-btn"' in html
    assert 'getElementById("coach-checkin-btn")' in js


def test_coach_html_loads_nav_js_before_coach_js():
    """coach.js reads window.NavCopy at click time (after nav.js has already
    run its top-level `window.NavCopy = {...}` assignment), but script order
    still has to put nav.js first for that to ever be true, not just for the
    happy timing case."""
    html = COACH_HTML.read_text()
    assert html.index('src="js/nav.js"') < html.index('src="js/coach.js"')


def test_coach_html_carries_the_paste_back_and_history_ids():
    """Relocated from decisions.js/decisions.html verbatim — same ids, same
    behavior, just living on /coach now."""
    html = COACH_HTML.read_text()
    for el_id in ("dc-raw", "dc-decided-on", "dc-review-on", "dc-tags", "dc-save", "dc-list"):
        assert 'id="' + el_id + '"' in html


def test_coach_html_has_a_flow_hint_between_checkin_and_paste_back():
    """The whole point of this page over the old split nav-dropdown +
    /decisions arrangement: the round trip has to be obvious on first use."""
    html = COACH_HTML.read_text()
    checkin_idx = html.index('id="coach-checkin-btn"')
    paste_idx = html.index('id="dc-raw"')
    hint = html[checkin_idx:paste_idx]
    assert "paste" in hint.lower()
