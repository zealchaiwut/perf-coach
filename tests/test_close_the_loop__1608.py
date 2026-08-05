"""Closing the consult loop — issue #1608.

The paste loop is: app exports data → you paste it into Claude → Claude proposes
a change list → you record the decision → the next export carries it back.

The Plan-tab "From a consult" JSON prefs importer (added so the consult prompt
had somewhere to send patches) was later removed — prefs changes from a consult
are applied in the Plan preferences form fields directly. Section 1 below pins
that the prompt no longer promises a dead importer.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLAN_JS = REPO / "frontend" / "js" / "training-plan.js"
WEIGHT_JS = REPO / "frontend" / "js" / "weight.js"
WEIGHT_HTML = REPO / "frontend" / "pages" / "weight.html"


@pytest.fixture(scope="module")
def plan_js() -> str:
    return PLAN_JS.read_text()


# ── 1. Consult no longer promises a prefs JSON importer ───────────────────────

def test_consult_template_does_not_promise_prefs_importer():
    from backend.services.coach_export import CONSULT_TEMPLATE

    assert "prefs importer" not in CONSULT_TEMPLATE
    assert "JSON patch" not in CONSULT_TEMPLATE


def test_plan_prefs_has_no_consult_importer(plan_js):
    assert "pl-import-json" not in plan_js
    assert "_importerHtml" not in plan_js
    assert "From a consult" not in plan_js


def test_write_version_really_does_replace():
    """Prefs PUT replaces the whole payload — partial patches would wipe omitted
    fields. The removed consult importer existed to merge for that reason; the
    Plan form still collects a full payload before save."""
    from backend.services import training_prefs

    src = inspect.getsource(training_prefs.write_version)
    assert "payload=normalized" in src
    assert "prev.payload" not in src, "write_version now merges; revisit prefs save paths"


def test_style_version_bumped(plan_js):
    """PLAN_CSS only re-applies when its version changes; new rules without a
    bump are invisible on a warm page."""
    assert "20260804plyo1" in plan_js


# ── 2. Paused tracking is visible in the app ──────────────────────────────────

def test_weight_endpoint_reports_tracking_state():
    """tracking_state's docstring claimed four consumers "including the weight
    card"; only the worker nudge and coach_export actually read it."""
    src = (REPO / "backend" / "main.py").read_text()
    assert '"tracking": tracking' in src
    assert "state_for_user" in src


def test_tracking_state_lookup_is_best_effort():
    """A state we could not compute must never cost the athlete their weight
    history — the entries are the point of the endpoint."""
    src = (REPO / "backend" / "main.py").read_text()
    block = src[src.index("tracking = None") : src.index('"tracking": tracking')]
    assert "except Exception" in block


def test_weight_page_renders_the_paused_copy():
    js = WEIGHT_JS.read_text()
    assert "tracking-state" in js
    assert "state === 'paused'" in js
    assert 'id="tracking-state"' in WEIGHT_HTML.read_text()


def test_paused_banner_is_reassurance_not_alarm():
    """"The app gets quieter, not louder." Nothing turns red; the copy says
    training continues."""
    from backend.services.tracking_state import PAUSED_COPY

    assert "training continues" in PAUSED_COPY
    html = WEIGHT_HTML.read_text()
    block = html[html.index(".tracking-state {") : html.index("}", html.index(".tracking-state {"))]
    for alarm in ("#b91c1c", "#c92a2a", "red"):
        assert alarm not in block, "the paused banner should not read as an error"


def test_banner_hidden_when_active():
    js = WEIGHT_JS.read_text()
    block = js[js.index("const banner = document.getElementById('tracking-state')") :]
    block = block[: block.index("const count")]
    assert "banner.hidden = !paused" in block


# ── 3. One voice for guardrail copy ───────────────────────────────────────────

def test_slow_down_obeys_the_eat_more_contract():
    """cut_review's guardrail advice is the same advice a deficit pause gives;
    it read in a different voice only because it lived in a different module."""
    from backend.services.cut_review import SLOW_DOWN_COPY
    from backend.services.deficit_guard import assert_eat_more_copy

    assert_eat_more_copy(SLOW_DOWN_COPY)  # raises if it drifts


def test_the_contract_is_checked_at_import():
    """A drifted string should fail on import, not in front of the athlete."""
    src = inspect.getsource(__import__("backend.services.cut_review", fromlist=["x"]))
    assert "_assert_eat_more(SLOW_DOWN_COPY)" in src


def test_ease_off_is_deliberately_outside_the_contract():
    """Documented, not accidental: ease_off is a pace adjustment, not a
    guardrail trip, so it is not bound by the pause-copy tone rules."""
    src = inspect.getsource(__import__("backend.services.cut_review", fromlist=["x"]))
    assert "deliberately outside the contract" in src


# ── 4. The export contract is documented ──────────────────────────────────────

@pytest.mark.parametrize(
    "block", ["decisions", "volume_plays", "sprint", "hypothesis", "goal_habits", "evidence"]
)
def test_schema_v2_v4_blocks_are_documented(block):
    """The doc stopped at `findings` — roughly a third of the payload was
    undocumented, and this file is what people build against. It has already
    misled twice."""
    assert block in (REPO / "docs" / "features" / "coach-export.md").read_text()


def test_documented_blocks_actually_exist_in_the_payload():
    """Documenting a block that isn't emitted would be the same failure in the
    other direction."""
    import backend.services.coach_export as ce

    src = inspect.getsource(ce.build_export)
    for block in ("decisions", "volume_plays", "sprint", "hypothesis"):
        assert f'"{block}"' in src, f"{block} is documented but not emitted"


# ── 5. Habit evidence has a UI ────────────────────────────────────────────────

def test_habits_summary_returns_evidence():
    """habit_evidence.py's docstring calls itself "what the habit surface shows
    instead" of streaks, and lean-program.md describes it rendering there. It
    was only ever built inside coach_export."""
    src = (REPO / "backend" / "main.py").read_text()
    assert '"evidence": evidence' in src
    assert "build_user_evidence" in src


def test_evidence_lookup_is_best_effort():
    """Decoration. A habit grid that fails because a sentence could not be
    built is worse than a grid with no sentence."""
    src = (REPO / "backend" / "main.py").read_text()
    block = src[src.index("evidence: list = []") : src.index('"evidence": evidence')]
    assert "except Exception" in block


def test_habits_page_renders_evidence():
    js = (REPO / "frontend" / "js" / "habits.js").read_text()
    assert "_renderHabitEvidence" in js
    assert 'id="habit-evidence"' in (REPO / "frontend" / "pages" / "habits.html").read_text()


def test_evidence_block_hides_itself_when_empty():
    """build_user_evidence returns ONLY readable comparisons, so an empty list
    means there is genuinely nothing to say. Rendering "not enough data yet"
    three times is the failure this design avoids."""
    js = (REPO / "frontend" / "js" / "habits.js").read_text()
    block = js[js.index("function _renderHabitEvidence") :]
    block = block[: block.index("async function loadAndRender")]
    assert "host.hidden = true" in block


def test_evidence_fetch_cannot_break_the_grid():
    js = (REPO / "frontend" / "js" / "habits.js").read_text()
    assert ".catch(() => null)" in js, "the evidence fetch must not reject the Promise.all"


def test_evidence_is_styled_quietly():
    """A streak shouts; this states. No badge, no fire, no alarm colour."""
    css = (REPO / "frontend" / "css" / "habits.css").read_text()
    block = css[css.index(".habit-evidence-row {") :]
    block = block[: block.index("}")]
    for shout in ("#b91c1c", "#c92a2a", "bold", "700"):
        assert shout not in block
