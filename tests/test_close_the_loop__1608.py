"""Closing the consult loop — issue #1608.

The paste loop is: app exports data → you paste it into Claude → Claude proposes
a change list → you record the decision → the next export carries it back. Five
things stopped that cycle closing.

The first is the one that mattered: the consult prompt told Claude to hand over
"the JSON patch to paste into the prefs importer", and there was no importer.
Every consult touching a preference produced instructions for a feature that did
not exist, and the athlete hand-translated it into Settings — silent manual work
the app never admitted to.
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


# ── 1. The prefs importer exists ──────────────────────────────────────────────

def test_the_importer_the_prompt_promises_exists(plan_js):
    from backend.services.coach_export import CONSULT_TEMPLATE

    assert "prefs importer" in CONSULT_TEMPLATE, (
        "the consult prompt no longer mentions an importer — if that promise was "
        "removed instead, delete this test with it"
    )
    assert "pl-import-json" in plan_js, "the prompt promises an importer that does not exist"


def test_importer_merges_rather_than_replaces(plan_js):
    """THE safety property.

    training_prefs.write_version stores `payload=normalized` wholesale with no
    merge against the previous version, so PUTting a bare patch would erase
    every field the patch omits. A consult produces a PATCH ("plyo 0 -> 1"),
    never a full document — so applying one naively would silently wipe rest
    days, notes and everything else.
    """
    assert "_deepMerge" in plan_js
    body = plan_js[plan_js.index("previewBtn.addEventListener") :]
    body = body[: body.index("applyBtn.addEventListener")]
    assert "_collectTrainingPrefsPayload()" in body, "patch is not merged onto current prefs"
    assert "_deepMerge(current, patch)" in body


def test_the_merged_payload_is_what_gets_sent(plan_js):
    """Merging and then sending the patch anyway would be worse than not
    merging, because the preview would look right."""
    body = plan_js[plan_js.index("applyBtn.addEventListener") :]
    body = body[: body.index("function _paintPrefsForm") if "function _paintPrefsForm" in body else len(body)]
    assert "_importPreview.merged" in body
    assert "payload: _importPreview.patch" not in body


def test_write_version_really_does_replace():
    """Pins the assumption the merge exists for. If this ever starts merging
    server-side, the client-side merge becomes redundant rather than wrong —
    but someone should know."""
    from backend.services import training_prefs

    src = inspect.getsource(training_prefs.write_version)
    assert "payload=normalized" in src
    assert "prev.payload" not in src, "write_version now merges; revisit the importer"


def test_importer_previews_before_applying(plan_js):
    """A change list from an LLM is not something to apply sight-unseen."""
    assert "_diffPayloads" in plan_js
    assert 'id="pl-import-preview"' in plan_js
    assert 'id="pl-import-apply"' in plan_js


def test_invalid_json_is_reported_not_swallowed(plan_js):
    body = plan_js[plan_js.index("previewBtn.addEventListener") :]
    body = body[: body.index("applyBtn.addEventListener")]
    assert "JSON.parse" in body
    assert "not valid JSON" in body


def test_a_non_object_patch_is_rejected(plan_js):
    """A pasted array or string would merge into nonsense."""
    body = plan_js[plan_js.index("previewBtn.addEventListener") :]
    body = body[: body.index("applyBtn.addEventListener")]
    assert "Array.isArray(patch)" in body


def test_importer_refetches_after_applying(plan_js):
    """Show what the server stored, not what we hoped it would store — the API
    normalises payloads on write."""
    body = plan_js[plan_js.index("applyBtn.addEventListener") :]
    assert "_renderPrefsForm()" in body


def test_style_version_bumped(plan_js):
    """PLAN_CSS only re-applies when its version changes; new rules without a
    bump are invisible on a warm page."""
    assert "20260731import1" in plan_js


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
