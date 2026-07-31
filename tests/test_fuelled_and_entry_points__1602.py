"""The fuelled toggle and the two orphaned logging pages — §9 and issue #1602.

Two gaps from the same family: something fully built with no way to reach it.

``workouts.fuelled`` got its write path in #1595 but no UI, so marking a long run
as fuelled required a curl — and the long-run-fuel habit, one of the lean
program's three, could not tick without it.

``/run-builder`` (a whole manual run-logging flow) and ``/sessions`` (the
strength/plyo logger) are registered in ``main.py``'s ``_PAGES`` and were linked
from nowhere. ``nav.js`` never referenced them and no page did either.

Entry points go on the Log workout header rather than the global nav: they are
alternate ways to log a session, so they belong beside the thing they are
alternates to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TRAINING_HTML = REPO / "frontend" / "pages" / "training.html"
TRAINING_JS = REPO / "frontend" / "js" / "training.js"
MAIN_PY = REPO / "backend" / "main.py"


@pytest.fixture(scope="module")
def html() -> str:
    return TRAINING_HTML.read_text()


@pytest.fixture(scope="module")
def js() -> str:
    return TRAINING_JS.read_text()


# ── The fuelled control ───────────────────────────────────────────────────────

def test_fuelled_control_exists(html):
    assert 'id="workout-fuelled"' in html


def test_fuelled_is_tri_state_not_a_checkbox(html):
    """null = not recorded, and it must never read as "no". A checkbox has two
    states and would silently answer a question the athlete never answered —
    the long-run-fuel habit ticks only on an explicit yes."""
    block = html[html.index('id="workout-fuelled"') :]
    block = block[: block.index("</select>")]
    assert 'value=""' in block
    assert 'value="true"' in block
    assert 'value="false"' in block
    assert "checkbox" not in block


def test_form_sends_fuelled(js):
    assert "fuelled: triStateVal('workout-fuelled')" in js


def test_tristate_helper_distinguishes_empty_from_false(js):
    """The helper is the whole reason this isn't a checkbox — an empty value has
    to survive as null all the way to the API."""
    start = js.index("function triStateVal(")
    body = js[start : js.index("function intFieldVal(")]
    assert "return null" in body
    assert "=== 'true'" in body


@pytest.mark.parametrize("occurrences", [4])
def test_fuelled_repopulates_on_edit_and_duplicate(js, occurrences):
    """Rendered but never populated drops the value on every edit — the field
    would look optional and behave destructively."""
    assert js.count("workout-fuelled") >= occurrences, (
        "expected clear + populate-on-edit + populate-on-duplicate + save"
    )


def test_repopulate_preserves_false(js):
    """`false` is a real answer. A truthiness check would render it as
    "Not recorded" and then save null back, quietly erasing a "no"."""
    assert js.count("== null ? '' : String(") >= 2, (
        "fuelled repopulation must test for null, not falsiness"
    )


# ── The orphaned pages ────────────────────────────────────────────────────────

@pytest.mark.parametrize("href", ["/run-builder", "/sessions"])
def test_orphaned_pages_have_an_entry_point(html, href):
    assert f'href="{href}"' in html, (
        f"{href} is still reachable only by typing the URL"
    )


@pytest.mark.parametrize("page", ["run-builder", "sessions"])
def test_those_routes_actually_exist(page):
    """A link to a route that isn't registered is worse than no link."""
    assert f'"{page}"' in MAIN_PY.read_text()


def test_entry_points_are_styled(html):
    """Unstyled anchors next to pill buttons read as a rendering bug."""
    assert ".rl-altlog" in html


def test_entry_points_have_visible_labels(html):
    """Icon-only would need aria-labels; these carry text, so the emoji is
    decorative and must be hidden from screen readers."""
    for label in ("Build a run", "Strength / plyo session"):
        assert label in html
    block = html[html.index('href="/run-builder"') :]
    block = block[: block.index("</a>")]
    assert 'aria-hidden="true"' in block
