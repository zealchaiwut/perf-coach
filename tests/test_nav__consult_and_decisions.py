"""The consult blob and the decisions log are reachable from the nav.

Both existed as working backend surfaces with no way in:

- ``GET /api/coach/consult`` shipped with the coach export (#1593) but only the
  *daily* blob got a button, so the check-in — the half that asks questions and
  produces a change list — was curl-only.
- ``/decisions`` is registered in ``main.py``'s ``_PAGES`` but ``nav.js`` never
  linked it, and no page linked it either. The export cites decision rows by
  date, so the loop's own memory was URL-only.

Both were listed in ``docs/lean-program-operator-guide.md`` §9 as known gaps.
That listing is the reason they were found; these tests are the reason they
stay fixed.

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


def test_icon_only_button_has_an_accessible_name(nav):
    """It has no visible <span>, so aria-label is the only name a screen reader
    gets."""
    btn = nav[nav.index('id="gn-copy-consult"') - 200:]
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


# ── The decisions link ────────────────────────────────────────────────────────

def test_decisions_is_in_the_nav_links(nav):
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    links = nav[links_start:links_end]
    assert "'/decisions'" in links


def test_decisions_link_is_not_disabled(nav):
    """Other LINKS entries have carried `disabled: true` in the past (e.g. the
    now-removed `/calendar` link). Decisions must not inherit that by
    copy-paste."""
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    for line in nav[links_start:links_end].splitlines():
        if "/decisions" in line:
            assert "disabled" not in line
            break
    else:
        pytest.fail("no /decisions entry found in LINKS")


def test_the_decisions_page_route_exists():
    assert '"decisions": "decisions.html"' in MAIN_PY.read_text()


def test_decisions_matches_its_legacy_html_path(nav):
    """Every page is served at both /x and /x.html; the active-state match list
    has to cover both or the nav item never highlights."""
    links_start = nav.index("var LINKS = [")
    links_end = nav.index("];", links_start)
    for line in nav[links_start:links_end].splitlines():
        if "/decisions" in line:
            assert "/decisions.html" in line
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


def test_copy_buttons_have_a_pre_copy_explanation(nav):
    """A short, always-in-the-DOM explanation of what each button copies —
    reusing the shared .info-tip-bubble component (styles.css) that the
    CTL/ATL/TSB/ACWR tiles already use for this exact job, hover/focus
    triggered off the button itself rather than a native `title` (slow,
    inconsistent, easy to miss)."""
    for btn_id in ("gn-copy-claude", "gn-copy-consult"):
        start = nav.index('id="' + btn_id + '"')
        end = nav.index("</button>", start)
        btn = nav[start:end]
        assert "info-tip-bubble" in btn
        assert 'role="tooltip"' in btn
        assert "aria-describedby=" in btn


def test_pre_copy_explanation_is_reachable_on_mobile():
    """The mobile media query hides the copy buttons' plain <span> labels
    (icon-only at narrow widths) — it must not blanket-hide the info-tip
    bubble along with them, or the pre-copy explanation would be unreachable
    on the majority-mobile surface it matters most for."""
    nav_src = NAV_JS.read_text()
    mobile_start = nav_src.index("@media (max-width:880px)")
    mobile = nav_src[mobile_start : nav_src.index("]", mobile_start)]
    assert "gn-copy span:not(.info-tip-bubble){display:none;}" in mobile
