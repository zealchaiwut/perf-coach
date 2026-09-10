"""Tests for issue #1666: Remove orphaned plan-modal-type select from training-log.html.

Context: After sprint-126 (#1282), #plan-modal-type <select> has no JS wiring —
the modal type is supplied via the raceType argument to openModal(). The element
was made off-screen but still visible to screen readers (aria-label="Entry type"),
creating an orphaned combobox that does nothing.

Acceptance criteria:
  AC1 — The `#plan-modal-type` <select> element is removed from training-log.html.
  AC2 — No JS in training-performance.js references `plan-modal-type` (the orphaned id).
  AC3 — The `#plan-modal-typeseg` tablist (the real segmented control) is still present.
"""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOG_HTML = (_ROOT / "frontend" / "pages" / "training-log.html").read_text()
_PERF_JS = (_ROOT / "frontend" / "js" / "training-performance.js").read_text()


# ── AC1 ──────────────────────────────────────────────────────────────────────

def test_ac1_orphaned_select_removed_from_html():
    """AC1: The orphaned #plan-modal-type <select> must not appear in the HTML."""
    assert 'id="plan-modal-type"' not in _LOG_HTML, (
        "The orphaned #plan-modal-type <select> must be removed from training-log.html; "
        "it has no JS wiring and creates a screen-reader-visible combobox that does nothing"
    )


# ── AC2 ──────────────────────────────────────────────────────────────────────

def test_ac2_no_js_references_orphaned_id():
    """AC2: training-performance.js must not reference plan-modal-type (no wiring existed)."""
    assert "plan-modal-type" not in _PERF_JS or "plan-modal-typeseg" in _PERF_JS, (
        "The only acceptable occurrence of 'plan-modal-type' in the JS is as a "
        "prefix of 'plan-modal-typeseg' — a bare reference to the orphaned select "
        "must not exist"
    )
    # Stricter: the literal id string (without the 'seg' suffix) must not appear alone.
    import re
    bare_refs = re.findall(r'plan-modal-type(?!seg)', _PERF_JS)
    assert not bare_refs, (
        f"JS must not reference the orphaned #plan-modal-type id directly; "
        f"found: {bare_refs}"
    )


# ── AC3 ──────────────────────────────────────────────────────────────────────

def test_ac3_real_segmented_control_still_present():
    """AC3: The #plan-modal-typeseg tablist (the real type control) must remain."""
    assert 'id="plan-modal-typeseg"' in _LOG_HTML, (
        "#plan-modal-typeseg (the real segmented type control) must still be in "
        "training-log.html after removing the orphaned select"
    )
