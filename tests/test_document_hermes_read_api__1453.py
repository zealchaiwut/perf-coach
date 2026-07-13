"""Tests for issue #1453: Document Hermes read API in docs/worker.md"""
import os
import json
import re
import pytest


# Test against the repo root, not UAT server
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_WORKER = os.path.join(REPO_ROOT, "docs", "worker.md")


def test_document_hermes_read_api__section_exists():
    """AC: New section in docs/worker.md titled 'Read API (Hermes)' listing all four endpoints."""
    with open(DOCS_WORKER) as f:
        content = f.read()

    # Check section exists
    assert "## Read API (Hermes)" in content, "Missing 'Read API (Hermes)' section header"

    # Check all four endpoints are listed
    endpoints = [
        "GET /api/training/load",
        "GET /api/scores",
        "GET /api/plan/today",
        "GET /api/weight/recent",
    ]
    for endpoint in endpoints:
        assert f"### `{endpoint}`" in content, f"Missing endpoint documentation: {endpoint}"


def test_document_hermes_read_api__conventions_documented():
    """AC: Documents shared conventions: ?user= / WORKER_READ_API_USER resolution, date defaults (Asia/Bangkok), no auth."""
    with open(DOCS_WORKER) as f:
        content = f.read()

    # Check conventions section exists
    assert "### Shared conventions" in content, "Missing 'Shared conventions' subsection"

    # Check key convention phrases
    assert "?user=" in content or "user=" in content, "Missing ?user= convention"
    assert "WORKER_READ_API_USER" in content, "Missing WORKER_READ_API_USER env var reference"
    assert "Asia/Bangkok" in content, "Missing Bangkok timezone mention"
    assert "No auth" in content or "no auth" in content, "Missing 'no auth' statement"


def test_document_hermes_read_api__read_only_note():
    """AC: One-line design note verbatim: 'read-only by design' and contrast with write paths."""
    with open(DOCS_WORKER) as f:
        content = f.read()

    # Check read-only note
    assert "Read-only by design" in content, "Missing 'Read-only by design' phrase"
    assert "all writes happen" in content, "Missing write-routing statement"
    assert "no POST/PATCH/DELETE" in content or "GET-only" in content, "Missing GET-only emphasis"


def test_document_hermes_read_api__binding_confirmed():
    """AC: Confirms binding: worker on Mac Mini (zeal-server), port 9100, localhost/tailnet only."""
    with open(DOCS_WORKER) as f:
        content = f.read()

    # Check binding info
    assert "port 9100" in content, "Missing port 9100 mention"
    assert "localhost" in content or "tailnet" in content, "Missing localhost/tailnet binding"
    assert "not deployed to Render" in content, "Missing 'not deployed to Render' statement"


def test_document_hermes_read_api__example_responses_field_names():
    """AC: Example responses have correct field names (verified against doc structure)."""
    with open(DOCS_WORKER) as f:
        content = f.read()

    # Extract JSON blocks from the Read API section only
    hermes_section_start = content.find("## Read API (Hermes)")
    hermes_section_end = content.find("## Audit trail")
    hermes_section = content[hermes_section_start:hermes_section_end]

    json_blocks = re.findall(r'```json\n(.*?)\n```', hermes_section, re.DOTALL)
    assert len(json_blocks) >= 4, f"Expected at least 4 JSON examples in Hermes section, found {len(json_blocks)}"

    # Parse each and check structure
    for i, block in enumerate(json_blocks):
        try:
            obj = json.loads(block)
            # Just verify it's valid JSON with dict structure
            assert isinstance(obj, dict), f"Example {i} is not a JSON object"
        except json.JSONDecodeError as e:
            pytest.fail(f"Example {i} is not valid JSON: {e}\n{block}")

    # Spot-check key fields by endpoint
    full_doc = content

    # training/load: check ctl, atl, tsb, acwr, verdict
    load_section = full_doc[full_doc.find("### `GET /api/training/load`"):full_doc.find("### `GET /api/scores`")]
    assert "ctl" in load_section, "training/load response missing 'ctl' field"
    assert "atl" in load_section, "training/load response missing 'atl' field"
    assert "tsb" in load_section, "training/load response missing 'tsb' field"
    assert "acwr" in load_section, "training/load response missing 'acwr' field"
    assert "verdict" in load_section, "training/load response missing 'verdict' field"

    # scores: check endurance, speed, trend
    scores_section = full_doc[full_doc.find("### `GET /api/scores`"):full_doc.find("### `GET /api/plan/today`")]
    assert "endurance" in scores_section, "scores response missing 'endurance' field"
    assert "speed" in scores_section, "scores response missing 'speed' field"
    assert "trend" in scores_section, "scores response missing 'trend' field"

    # plan/today: check planned, sessions
    plan_section = full_doc[full_doc.find("### `GET /api/plan/today`"):full_doc.find("### `GET /api/weight/recent`")]
    assert "planned" in plan_section, "plan/today response missing 'planned' field"
    assert "sessions" in plan_section, "plan/today response missing 'sessions' field"

    # weight/recent: check entries, ewma, trend
    weight_section = full_doc[full_doc.find("### `GET /api/weight/recent`"):full_doc.find("## Audit trail")]
    assert "entries" in weight_section, "weight/recent response missing 'entries' field"
    assert "ewma" in weight_section, "weight/recent response missing 'ewma' field"
    assert "trend" in weight_section, "weight/recent response missing 'trend' field"
