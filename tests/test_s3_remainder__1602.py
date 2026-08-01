"""S3 remainder — issue #1602's reachability sweep.

Four items, none of them needing a design decision once the endpoints existed:

1. The what-if button was a decoy. `#whatif-open-btn` unhid `#edit-panel` — the
   ordinary edit-goal form — instead of calling
   `POST /api/weight-targets/{goal_id}/what-if`, which was fully implemented
   and tested with zero frontend callers. Worse than missing: a button
   labelled for a simulation silently gave the user an edit form.
2. `GET /api/weight-targets/arrival-projection` had zero frontend callers.
3. `GET /api/adherence-nudges` had zero frontend callers.
4. `/projection` and `/strength-view` were registered page routes with no
   entry point anywhere in the frontend — reachable only by typing the URL.

   `/weight/targets` was on the same list, but adding a link to it turned out
   to be a regression, not a fix: `test_weight_page_frontend__412.py::
   test_b_manage_target_links_to_weight_targets` (AC #461) pins that the link
   was deliberately REMOVED from weight.html when the standalone
   `/weight/targets` page was consolidated into weight.html's own slide-in
   panel. Re-adding it anywhere on that page fights a real prior decision, not
   an oversight — so it is treated the same way as `/preferences`: the
   redirect shim stays reachable by typing the URL, not linked from normal
   flow.

Static analysis only — no live server needed, mirrors
tests/test_frontend_shared_lib__1603.py's grep/regex-ratchet style rather than
tests/test_no_naive_today__1600.py's AST walk, because the things being
checked here are "does this string appear", not "is this call shape banned".
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "frontend" / "js"
PAGES = REPO / "frontend" / "pages"
MAIN = (REPO / "backend" / "main.py").read_text()

WEIGHT_JS = (JS / "weight.js").read_text()
WEIGHT_HTML = (PAGES / "weight.html").read_text()
HABITS_HTML = (PAGES / "habits.html").read_text()
TRAINING_JS = (JS / "training.js").read_text()
TRAINING_HTML = (PAGES / "training.html").read_text()


def _all_frontend_text() -> str:
    parts = []
    for p in JS.rglob("*.js"):
        parts.append(p.read_text())
    for p in PAGES.glob("*.html"):
        parts.append(p.read_text())
    return "\n".join(parts)


# ── 1. The what-if button calls the what-if endpoint, not the edit form ───────

def test_the_what_if_endpoint_still_exists_and_is_a_post():
    """Ground truth check — if this ever moves, the frontend wiring below is
    testing against a route that no longer exists."""
    assert '@app.post("/api/weight-targets/{goal_id}/what-if")' in MAIN


def test_weight_js_calls_the_what_if_endpoint():
    assert "/what-if" in WEIGHT_JS, (
        "weight.js has no reference to the what-if endpoint — the button is "
        "still a decoy"
    )
    # It must be a POST (the ticket text's original GET assumption was wrong;
    # the implemented endpoint takes a body).
    call_site = re.search(r"[^\n]*['\"`][^'\"`\n]*/what-if[^'\"`\n]*['\"`][^\n]*", WEIGHT_JS)
    assert call_site, "could not locate the what-if fetch call site"
    window = WEIGHT_JS[call_site.start(): call_site.start() + 400]
    assert "'POST'" in window or '"POST"' in window, (
        "the what-if call must be a POST — GET was the ticket's (wrong) "
        "assumption, not the endpoint's actual shape"
    )


def test_what_if_button_no_longer_opens_the_edit_panel():
    """The ratchet. Before the fix, #whatif-open-btn's click handler unhid
    #edit-panel/#edit-scrim — the ordinary edit-goal form — and nothing else.
    If that pattern reappears immediately around the button's wiring, the
    decoy behaviour is back."""
    open_btn_idx = WEIGHT_JS.index("_initWhatifPanel")
    # Look at the whole what-if section of the file, not just one function —
    # the point is that opening the prompt must not fall back to edit-panel.
    section_start = WEIGHT_JS.index("_openWhatifPanel")
    section = WEIGHT_JS[section_start:open_btn_idx + 2000]
    assert "edit-panel" not in section and "edit-scrim" not in section, (
        "the what-if open/run flow still references the edit-goal panel — "
        "the decoy behaviour may have come back"
    )


def test_whatif_panel_markup_exists():
    """The JS referenced #whatif-prompt/#whatif-headline/#whatif-open-btn
    before this fix, but no HTML defined them — the whole block was dead
    code, `if (whatifPrompt)` was always false. The result panel must exist
    too, or the button has nothing to open."""
    for el_id in (
        "whatif-prompt", "whatif-headline", "whatif-open-btn",
        "whatif-panel", "whatif-scrim", "whatif-run-btn", "whatif-result",
    ):
        assert f'id="{el_id}"' in WEIGHT_HTML, f"weight.html is missing #{el_id}"


def test_whatif_result_rendering_handles_loading_and_error():
    """Never a blank panel or an unhandled rejection (explicit requirement)."""
    assert "UIStates.setLoading" in WEIGHT_JS
    assert "UIStates.setError" in WEIGHT_JS
    assert "catch" in WEIGHT_JS[WEIGHT_JS.index("_runWhatifSimulation"):]


# ── 2. Arrival projection has a frontend caller ────────────────────────────────

def test_arrival_projection_endpoint_still_exists():
    assert '@app.get("/api/weight-targets/arrival-projection")' in MAIN


def test_weight_js_calls_arrival_projection():
    assert "/api/weight-targets/arrival-projection" in WEIGHT_JS


def test_weight_html_has_an_arrival_projection_element():
    assert 'id="arrival-projection"' in WEIGHT_HTML


# ── 3. Adherence & nudges has a frontend caller ────────────────────────────────

def test_adherence_nudges_endpoint_still_exists():
    assert '@app.get("/api/adherence-nudges")' in MAIN


def test_a_frontend_module_calls_adherence_nudges():
    assert "/api/adherence-nudges" in _all_frontend_text()


def test_habits_page_loads_a_nudges_module_and_has_a_mount_point():
    """Picked Habits over Home: the endpoint's own data (per-habit adherence,
    slipping-habit detection) is habit-scoped, and the page already has an
    established pattern for this exact shape of panel (habit-insights.js /
    #insights-panel) to be consistent with."""
    assert "habit-nudges.js" in HABITS_HTML
    assert 'id="nudges-panel"' in HABITS_HTML
    assert 'id="nudges-body"' in HABITS_HTML
    nudges_js = JS / "habit-nudges.js"
    assert nudges_js.is_file()
    assert "/api/adherence-nudges" in nudges_js.read_text()


# ── 4. /projection and /strength-view are reachable ────────────────────────────

@pytest.mark.parametrize("route", ["/projection", "/strength-view", "/weight/targets"])
def test_route_is_still_registered(route: str):
    """Ground truth — these must still be real routes, or the frontend links
    added below would point at 404s. Includes /weight/targets even though it
    stays deliberately unlinked (below) — it must still resolve for anyone
    who has the old URL bookmarked."""
    assert f'"{route.lstrip("/")}"' in MAIN or f'"{route}"' in MAIN, (
        f"{route} no longer appears to be registered in main.py"
    )


@pytest.mark.parametrize("route", ["/projection", "/strength-view"])
def test_route_has_a_frontend_entry_point(route: str):
    """Cross-references registered routes against every href/navigation in the
    frontend — the same method the doc used to find these in the first place.
    A literal string match is enough: /strength-view's link is built at
    runtime (`'/strength-view?id=' + id`), so this checks for the route
    prefix, not a full static href attribute.
    """
    assert route in _all_frontend_text(), (
        f"{route} is registered but still has no frontend reference — it is "
        "reachable only by typing the URL"
    )


def test_strength_view_link_is_wired_from_the_workout_detail_modal():
    """More specific than the generic 'somewhere in the frontend' check above:
    pins the actual entry point (training.js's detail modal, shown only for
    Strength-type workouts, matching what /strength-view expects — a
    workout id)."""
    assert "detail-strength-view-link" in TRAINING_HTML
    assert "/strength-view?id=" in TRAINING_JS


def test_projection_link_is_wired_from_training_history():
    assert 'href="/projection"' in TRAINING_HTML


def test_weight_targets_was_deliberately_left_unlinked():
    """The opposite of the other two routes in this section — pinned so a
    future sweep doesn't 're-fix' this without re-reading why. Linking
    /weight/targets from weight.html would revert AC #461's consolidation
    (see test_weight_page_frontend__412.py::
    test_b_manage_target_links_to_weight_targets, which fails the moment such
    a link reappears)."""
    assert "/weight/targets" not in WEIGHT_HTML


def test_preferences_was_deliberately_left_alone():
    """Documented exception, not an oversight — its client-side redirect shim
    (-> /training-log?tab=plan#prefs) was judged fine as-is. This test pins
    the shim's destination so a future sweep doesn't silently change it
    without re-reading why it wasn't touched here."""
    assert '"preferences": "preferences.html"' in MAIN
    prefs_html = (PAGES / "preferences.html").read_text()
    assert "/training-log?tab=plan#prefs" in prefs_html
