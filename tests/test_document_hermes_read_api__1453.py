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

    # GET /api/scores was in this list and is NOT — it was documented in
    # docs/worker.md but never implemented in worker_app.py, and git shows no
    # commit that ever added it (#1601). This assertion was enforcing the
    # documentation of a phantom: anyone scoping the Hermes surface from that
    # file got a larger API than the code has, and this test kept it there.
    #
    # If the endpoint is built, add it back here and to the docs together.
    endpoints = [
        "GET /api/training/load",
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
    # Was >= 4. One example went with the GET /api/scores section, which
    # documented an endpoint that was never implemented (#1601).
    assert len(json_blocks) >= 3, f"Expected at least 3 JSON examples in Hermes section, found {len(json_blocks)}"

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
    load_section = full_doc[full_doc.find("### `GET /api/training/load`"):# was the /api/scores heading, removed with that phantom section (#1601)
        full_doc.find("### `GET /api/plan/today`")]
    assert "ctl" in load_section, "training/load response missing 'ctl' field"
    assert "atl" in load_section, "training/load response missing 'atl' field"
    assert "tsb" in load_section, "training/load response missing 'tsb' field"
    assert "acwr" in load_section, "training/load response missing 'acwr' field"
    assert "verdict" in load_section, "training/load response missing 'verdict' field"

    # The scores spot-check was removed with the phantom GET /api/scores
    # section (#1601): it verified example fields for an endpoint that was
    # documented but never implemented.

    # plan/today: check planned, sessions
    plan_section = full_doc[full_doc.find("### `GET /api/plan/today`"):full_doc.find("### `GET /api/weight/recent`")]
    assert "planned" in plan_section, "plan/today response missing 'planned' field"
    assert "sessions" in plan_section, "plan/today response missing 'sessions' field"

    # weight/recent: check entries, ewma, trend
    weight_section = full_doc[full_doc.find("### `GET /api/weight/recent`"):full_doc.find("## Audit trail")]
    assert "entries" in weight_section, "weight/recent response missing 'entries' field"
    assert "ewma" in weight_section, "weight/recent response missing 'ewma' field"
    assert "trend" in weight_section, "weight/recent response missing 'trend' field"
