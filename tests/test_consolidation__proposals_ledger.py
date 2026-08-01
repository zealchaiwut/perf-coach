"""Priority 2, D6: the preference-proposals ledger moved to Preferences.

The gap analyzer proposes a preference change (one catalog step) when a finding
persists. Accept / Adjust / Not now used to live in the coach brief. They live in
the Preferences panel now, because deciding "should plyo sessions go 0 -> 1" is a
different act from reading the morning brief, and it is easier with the plyo
control visible directly below the proposal.

What did NOT move: the proposals computation. pref_proposals.py and the
/api/preferences/proposals/* endpoints are untouched — this is a rendering move,
which is the whole of D6.

These are static assertions over the two JS files. The panel is vanilla JS with
no bundler and no DOM test harness in this repo, so the alternative to reading
the source is not testing the move at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BRIEF_JS = REPO / "frontend" / "js" / "coach-brief.js"
PLAN_JS = REPO / "frontend" / "js" / "training-plan.js"
HOME_HTML = REPO / "frontend" / "pages" / "home.html"


@pytest.fixture(scope="module")
def brief_src() -> str:
    return BRIEF_JS.read_text()


@pytest.fixture(scope="module")
def plan_src() -> str:
    return PLAN_JS.read_text()


# ── The brief no longer decides ───────────────────────────────────────────────

def test_brief_has_no_proposal_action_buttons(brief_src):
    for marker in ("hc-prop-accept", "hc-prop-decline", "hc-prop-adjust", "hc-prop-btn"):
        assert marker not in brief_src, (
            f"coach-brief.js still renders {marker} — the decision controls moved "
            "to the Preferences panel"
        )


def test_brief_does_not_post_to_the_proposals_api(brief_src):
    assert "/api/preferences/proposals/" not in brief_src, (
        "coach-brief.js still posts proposal decisions; that belongs to the "
        "Preferences panel now"
    )


def test_brief_filters_proposal_sections_out_of_the_accordion(brief_src):
    """The server still sends proposal sections (coach_brief_map appends them).
    The brief must drop them rather than render them as rows."""
    assert "filter(function (s) { return !_isProposal(s); })" in brief_src


def test_brief_still_points_at_pending_proposals(brief_src):
    """Silently dropping them would mean never noticing one without opening
    Preferences on spec. The pointer is what keeps the prompt-to-act."""
    assert "_proposalsLink" in brief_src
    assert "hc-prop-pointer" in brief_src
    assert "waiting" in brief_src


def test_brief_pointer_links_to_preferences(brief_src):
    assert "CARD_HREF.preferences" in brief_src


def test_pointer_has_a_style(brief_src):
    assert ".hc-prop-pointer" in HOME_HTML.read_text(), (
        "hc-prop-pointer is rendered but unstyled"
    )


def test_no_dangling_references_to_the_removed_handlers(brief_src):
    """_sectionHtml used to call _proposalActions on a branch. The branch is
    unreachable now, but a call to a deleted function is a landmine, not a
    dead line — it throws the moment anything makes it reachable again."""
    for gone in ("_proposalActions", "_postProposal", "_bindProposalActions"):
        assert gone not in brief_src, f"{gone} still referenced in coach-brief.js"


# ── Preferences now decides ───────────────────────────────────────────────────

def test_prefs_panel_renders_a_proposals_ledger(plan_src):
    assert "_proposalsHtml" in plan_src
    assert "pl-prop-block" in plan_src
    for action in ("pl-prop-accept", "pl-prop-adjust", "pl-prop-decline"):
        assert action in plan_src, f"prefs panel is missing the {action} control"


def test_prefs_panel_posts_the_decision(plan_src):
    assert "/api/preferences/proposals/" in plan_src


def test_ledger_shows_pending_only(plan_src):
    """GET /api/preferences returns settled proposals too (include_settled=True).
    A decision surface that lists decided items is a report."""
    assert "p2.status === 'proposed'" in plan_src


def test_ledger_refetches_instead_of_reloading_the_page(plan_src):
    """The brief reloaded because it was a modal over Home. Here the athlete may
    be mid-edit in the prefs form, and a reload discards unsaved changes."""
    ledger_start = plan_src.index("function _bindProposalActions(")
    ledger_end = plan_src.index("function _paintPrefsForm(")
    ledger = plan_src[ledger_start:ledger_end]
    assert "window.location.reload" not in ledger, (
        "the ledger reloads the page on decision, discarding unsaved prefs edits"
    )
    assert "_renderPrefsForm()" in ledger


def test_ledger_reports_errors_in_the_form_not_an_alert(plan_src):
    ledger_start = plan_src.index("function _bindProposalActions(")
    ledger_end = plan_src.index("function _paintPrefsForm(")
    ledger = plan_src[ledger_start:ledger_end]
    assert "window.alert" not in ledger
    assert "pl-sug-prefs-err" in ledger


def test_ledger_is_styled(plan_src):
    for cls in (".pl-prop{", ".pl-props{", ".pl-prop-actions{", ".pl-prop-count{"):
        assert cls in plan_src, f"missing style for {cls}"


def test_style_version_bumped(plan_src):
    """PLAN_CSS is injected under a versioned <style> id and only replaced when
    the version changes — new rules without a bump are invisible on a warm
    page."""
    assert "20260722draft7" not in plan_src, "style VER not bumped after adding rules"


# ── The computation is untouched ──────────────────────────────────────────────

def test_proposal_computation_still_exists():
    """D6 moves rendering only. pref_proposals stays exactly where it was."""
    from backend.services.gap_analysis import pref_proposals

    assert callable(pref_proposals.list_proposals)
    assert callable(pref_proposals.accept_proposal)


def test_server_still_emits_proposal_sections():
    """coach_brief_map still appends them — the brief counts them for the
    pointer, so removing them server-side would silently kill the pointer."""
    from backend.services import coach_brief_map

    src = Path(coach_brief_map.__file__).read_text()
    assert 'PROPOSAL_SECTION_PREFIX' in src
    assert '"type": "proposal"' in src


def test_preferences_endpoint_still_returns_proposals():
    """The ledger reads them from GET /api/preferences, not a new endpoint."""
    from backend.routers import preferences

    src = Path(preferences.__file__).read_text()
    assert '"proposals": proposals' in src
