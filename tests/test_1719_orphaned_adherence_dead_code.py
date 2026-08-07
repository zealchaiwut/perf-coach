"""Tests for issue #1719: Orphaned adherence dead code in fuel.js

The _fuelRenderWeeklyReview() function referenced #cut-review-adherence which
no longer exists in weight.html after the weight-tab revamp. Dead code on both
sides: the getElementById lookup always returns null, and the .textContent = ''
assignment is never reached.

Fix: remove the two dead lines from fuel.js. The logging_adherence_pct
computation in cut_review.py must remain — it drives the check_logging
recommendation branch.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
FUEL_JS = REPO_ROOT / "frontend" / "js" / "fuel.js"
WEIGHT_HTML = REPO_ROOT / "frontend" / "pages" / "weight.html"
CUT_REVIEW_PY = REPO_ROOT / "backend" / "services" / "cut_review.py"


def test_fuel_js_no_dead_adherence_lookup():
    """Dead getElementById('cut-review-adherence') call must not exist in fuel.js."""
    src = FUEL_JS.read_text()
    assert "cut-review-adherence" not in src, (
        "fuel.js still references #cut-review-adherence which does not exist in "
        "weight.html — remove the orphaned getElementById call"
    )


def test_weight_html_has_no_cut_review_adherence_element():
    """weight.html must not contain a #cut-review-adherence element (confirms element is gone)."""
    html = WEIGHT_HTML.read_text()
    assert "cut-review-adherence" not in html, (
        "weight.html defines #cut-review-adherence but fuel.js no longer populates it"
    )


def test_cut_review_still_computes_logging_adherence():
    """logging_adherence_pct computation must remain in cut_review.py (drives check_logging branch)."""
    src = CUT_REVIEW_PY.read_text()
    assert "logging_adherence_pct" in src, (
        "logging_adherence_pct was removed from cut_review.py but it is still needed "
        "to determine the check_logging recommendation"
    )
    # Confirm the actual decision branch is still present
    assert "check_logging" in src, (
        "check_logging recommendation branch was removed from cut_review.py"
    )
