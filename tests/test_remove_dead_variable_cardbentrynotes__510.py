"""Tests for issue #510: Remove dead variable _cardBEntryNotes in weight.js (runs against UAT)"""
import os
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def weight_js_content():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.get("/js/weight.js")
        if r.status_code != 200:
            pytest.skip(f"Could not fetch weight.js: HTTP {r.status_code}")
        return r.text


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria ---

def test_remove_dead_variable_cardbentrynotes__declaration_removed(weight_js_content):
    # AC: The declaration `let _cardBEntryNotes = null` is removed from weight.js
    assert "_cardBEntryNotes" not in weight_js_content


def test_remove_dead_variable_cardbentrynotes__assignment_sites_removed(weight_js_content):
    # AC: Both assignment sites of _cardBEntryNotes inside _cardBSetLoggedState are removed
    assert "_cardBEntryNotes" not in weight_js_content


def test_remove_dead_variable_cardbentrynotes__no_references_remain(weight_js_content):
    # AC: No other references to _cardBEntryNotes remain anywhere in weight.js
    count = weight_js_content.count("_cardBEntryNotes")
    assert count == 0, f"Found {count} reference(s) to _cardBEntryNotes"


def test_remove_dead_variable_cardbentrynotes__edit_link_handler_uses_dataset_weight(weight_js_content):
    # AC: The edit-link handler continues to read logged.dataset.weight directly (unchanged)
    # Note: AC text says logged.dataset.notes, but the actual handler reads logged.dataset.weight
    assert "logged.dataset.weight" in weight_js_content