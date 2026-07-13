"""Tests for docs/worker.md — Read API (Hermes) documentation (issue #1453).

Each test anchors to a specific AC item and checks the doc file directly.
"""
import re
from pathlib import Path

WORKER_DOC = Path(__file__).parent.parent / "docs" / "worker.md"


def _doc() -> str:
    return WORKER_DOC.read_text()


# ── AC1: Section header and all four endpoints listed ─────────────────────────

def test_read_api_section_exists():
    """AC1: New section 'Read API (Hermes)' exists in docs/worker.md."""
    assert "Read API (Hermes)" in _doc(), (
        "docs/worker.md must contain a 'Read API (Hermes)' section"
    )


def test_training_load_endpoint_documented():
    """AC1: GET /api/training/load is documented with a description."""
    doc = _doc()
    assert "/api/training/load" in doc
    assert "CTL" in doc and "ATL" in doc and "TSB" in doc


def test_scores_endpoint_documented():
    """AC1: GET /api/scores is documented with a description."""
    doc = _doc()
    assert "/api/scores" in doc
    assert "Endurance" in doc and "Speed" in doc


def test_plan_today_endpoint_documented():
    """AC1: GET /api/plan/today is documented with a description."""
    doc = _doc()
    assert "/api/plan/today" in doc
    assert "planned" in doc.lower()


def test_weight_recent_endpoint_documented():
    """AC1: GET /api/weight/recent is documented with a description."""
    doc = _doc()
    assert "/api/weight/recent" in doc
    assert "EWMA" in doc or "ewma" in doc


def test_all_four_endpoints_have_example_responses():
    """AC1: Each endpoint has at least one JSON example response block."""
    doc = _doc()
    # Count JSON code blocks after the Read API section
    read_api_idx = doc.find("Read API (Hermes)")
    assert read_api_idx != -1
    read_api_section = doc[read_api_idx:]
    json_blocks = re.findall(r"```json", read_api_section)
    assert len(json_blocks) >= 4, (
        f"Expected at least 4 JSON example blocks in Read API section, found {len(json_blocks)}"
    )


# ── AC2: Shared conventions ───────────────────────────────────────────────────

def test_user_param_convention_documented():
    """AC2: ?user= query param convention documented."""
    assert "?user=" in _doc() or "user=" in _doc()


def test_worker_read_api_user_env_documented():
    """AC2: WORKER_READ_API_USER env var documented."""
    assert "WORKER_READ_API_USER" in _doc()


def test_date_default_bangkok_documented():
    """AC2: date defaulting to Asia/Bangkok documented."""
    assert "Asia/Bangkok" in _doc() or "Bangkok" in _doc()


def test_no_auth_vs_internal_contrast_documented():
    """AC2: no-auth on read routes vs secret-gated /internal/* is documented."""
    doc = _doc()
    assert "no auth" in doc.lower() or "unauthenticated" in doc.lower() or "no authentication" in doc.lower()
    assert "/internal/" in doc  # contrast with secret-gated routes must be mentioned


# ── AC3: Binding confirmed ────────────────────────────────────────────────────

def test_port_9100_documented():
    """AC3: Worker binding on port 9100 documented."""
    assert "9100" in _doc()


def test_localhost_tailnet_only_documented():
    """AC3: localhost/tailnet-only binding documented."""
    doc = _doc()
    assert "localhost" in doc or "tailnet" in doc


def test_not_render_documented():
    """AC3: Explicitly states NOT deployed to Render."""
    doc = _doc()
    read_api_idx = doc.find("Read API (Hermes)")
    assert read_api_idx != -1
    read_api_section = doc[read_api_idx:]
    assert "Render" in read_api_section or "render" in read_api_section


# ── AC4: Read-only design note ────────────────────────────────────────────────

def test_read_only_design_note_present():
    """AC4: Read-only by design note present — no POST/PATCH/DELETE routes."""
    doc = _doc()
    assert "read-only" in doc.lower() or "read only" in doc.lower()


def test_no_write_routes_note_present():
    """AC4: Explicitly states no POST/PATCH/DELETE routes."""
    doc = _doc()
    # Must mention that writes are not here, or that no write methods exist
    has_note = (
        "POST" in doc and ("PATCH" in doc or "DELETE" in doc) and "no" in doc.lower()
    ) or "no POST" in doc or "never" in doc.lower()
    assert has_note, "Read-only design note must state no POST/PATCH/DELETE routes"


# ── AC5: Docs reflect the four-ticket sprint's shipped fields ─────────────────

def test_training_load_response_fields():
    """AC5: training/load example has the expected fields from issue #1449."""
    doc = _doc()
    # These are the AC-specified response fields from issue #1449
    for field in ("ctl", "atl", "tsb", "acwr", "verdict"):
        assert field in doc, f"Expected field '{field}' in docs"


def test_scores_response_fields():
    """AC5: scores example has the expected fields from issue #1450."""
    doc = _doc()
    for field in ("as_of", "endurance", "speed", "trend"):
        assert field in doc, f"Expected field '{field}' in docs"


def test_plan_today_response_fields():
    """AC5: plan/today example has the expected fields from issue #1451."""
    doc = _doc()
    for field in ("plan_date", "planned", "session_type"):
        assert field in doc, f"Expected field '{field}' in docs"


def test_weight_recent_response_fields():
    """AC5: weight/recent example has the expected fields from issue #1452."""
    doc = _doc()
    for field in ("entries", "last_logged", "ewma", "trend"):
        assert field in doc, f"Expected field '{field}' in docs"
