"""TDD tests for issue #402 — rename sbadge2 to sbadgeStryd in training-log.js."""

import re
from pathlib import Path

JS_FILE = Path(__file__).parents[1] / "frontend" / "js" / "training-log.js"


def _source():
    return JS_FILE.read_text()


def test_sbadge2_not_present():
    """AC: variable name sbadge2 must not appear anywhere in training-log.js."""
    assert "sbadge2" not in _source(), (
        "sbadge2 still present in training-log.js — rename to sbadgeStryd"
    )


def test_sbadgeStryd_present():
    """AC: sbadgeStryd must be declared and used for the Stryd source badge."""
    src = _source()
    assert "sbadgeStryd" in src, (
        "sbadgeStryd not found in training-log.js — rename sbadge2 to sbadgeStryd"
    )


def test_sbadgeStryd_has_stryd_class():
    """AC: the renamed variable must still carry the source-badge--stryd class."""
    src = _source()
    # find the block that assigns sbadgeStryd.className
    assert re.search(r"sbadgeStryd\.className\s*=.*source-badge--stryd", src), (
        "sbadgeStryd.className no longer assigns 'source-badge--stryd'"
    )


def test_sbadgeStryd_appended_to_wrap():
    """AC: sbadgeStryd must still be appended to its parent container."""
    src = _source()
    assert re.search(r"\.appendChild\(sbadgeStryd\)", src), (
        "sbadgeStryd not appended to parent — rename may have broken the append call"
    )
