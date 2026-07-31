"""Pace formatting goes through one implementation — issue #1603.

`frontend/js/lib/training-format.js` guards the rounding boundary:

    if (s === 60) { m += 1; s = 0; }

Three pages carried their own copy without it, so any pace landing within half a
second of a minute rendered as `5:60 /km` instead of `6:00 /km`:

    run-view.js, training-performance.js, run-builder.js

Reproduced before the fix at 359.6 s/km — the local copies returned "5:60", the
shared formatter "6:00".

Two of those pages did not even load the shared library, which is why the fix is
a `<script>` tag as much as a code change. A page that calls
`window.TrainingFormat` without loading it silently renders "—" for every pace,
so the tag and the call have to be asserted together.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "frontend" / "js" / "lib" / "training-format.js"

# page file -> the JS module it hosts
PAGES = {
    "run-view.html": "run-view.js",
    "run-builder.html": "run-builder.js",
    "training-log.html": "training-performance.js",
}


def test_the_shared_formatter_still_guards_the_boundary():
    """If this guard is ever removed, every page regresses at once — which is
    the trade for having one implementation."""
    assert "if (s === 60) { m += 1; s = 0; }" in LIB.read_text()


@pytest.mark.parametrize("page", sorted(PAGES))
def test_pages_load_the_shared_formatter(page):
    assert "js/lib/training-format.js" in (REPO / "frontend" / "pages" / page).read_text(), (
        f"{page} does not load training-format.js — every pace on it would "
        "render as an em dash"
    )


@pytest.mark.parametrize("page,script", sorted(PAGES.items()))
def test_formatter_loads_before_the_page_script(page, script):
    """Load order matters: window.TrainingFormat must exist before the page
    script's own helpers close over it."""
    html = (REPO / "frontend" / "pages" / page).read_text()
    lib_at = html.index("js/lib/training-format.js")
    page_at = html.index(script)
    assert lib_at < page_at, f"{page} loads {script} before training-format.js"


@pytest.mark.parametrize("script", sorted(PAGES.values()))
def test_pace_helpers_delegate_to_the_shared_formatter(script):
    src = (REPO / "frontend" / "js" / script).read_text()
    assert "TrainingFormat.formatPace" in src, (
        f"{script} still formats pace locally"
    )


@pytest.mark.parametrize("script", sorted(PAGES.values()))
def test_no_unguarded_local_pace_maths_remains(script):
    """The signature of the bug: rounding seconds-per-km with no minute carry.

    Asserted per-file rather than globally so a new page copy-pasting the old
    maths is caught here rather than shipping.
    """
    src = (REPO / "frontend" / "js" / script).read_text()
    has_modulo_round = "Math.round(secPerKm % 60)" in src or "Math.round(sPerKm % 60)" in src
    assert not has_modulo_round, (
        f"{script} computes pace seconds locally again — it will render :60"
    )
