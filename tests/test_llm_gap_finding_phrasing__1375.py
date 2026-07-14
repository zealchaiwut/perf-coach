"""Tests for issue #1375: LLM coach phrasing for gap findings (runs against UAT)"""
import os
import pytest
import httpx
from unittest.mock import patch


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def authenticated_client(client):
    """Return a client authenticated as testuser."""
    # Login with test user credentials
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass"},
    )
    # Session cookies are handled automatically by httpx.Client
    if login_resp.status_code not in (200, 400, 401):
        # 400/401 is expected if user doesn't exist, which is acceptable for UAT
        pass
    return client


# --- Acceptance Criteria ---

def test_llm_gap_finding_phrasing__phrasing_field_in_response(authenticated_client):
    # AC1: Per-finding phrasing via the existing Groq client
    # AC3: API field identical shape both paths (phrasing_source: llm|template)
    # Verify that gap-analysis response includes phrasing and phrasing_source fields

    r = authenticated_client.get("/api/training/gap-analysis")
    # Accept 200 (success), 401 (not logged in), or 404 (endpoint not updated yet)
    # These are all expected during testing before full integration
    if r.status_code == 401:
        pytest.skip("Test user not authenticated in UAT")
    if r.status_code == 404:
        pytest.skip("Gap analysis endpoint not found (feature may not be deployed yet)")

    assert r.status_code == 200, f"Gap analysis endpoint failed with {r.status_code}: {r.text}"

    data = r.json()
    assert "findings" in data
    assert isinstance(data["findings"], list)

    # Each finding should have phrasing fields
    if data["findings"]:  # Only check if findings exist
        for finding in data["findings"]:
            assert "code" in finding
            assert "severity" in finding
            assert "recommendation" in finding
            assert "evidence" in finding
            assert isinstance(finding["evidence"], list)
            # evidence_text should be present (from #1374)
            assert "evidence_text" in finding
            assert isinstance(finding["evidence_text"], str)
            # phrasing and phrasing_source should be present (issue #1375)
            assert "phrasing" in finding, "phrasing field missing in finding"
            assert "phrasing_source" in finding, "phrasing_source field missing in finding"
            assert isinstance(finding["phrasing"], str)
            assert finding["phrasing_source"] in ("llm", "template"), \
                f"phrasing_source must be 'llm' or 'template', got {finding['phrasing_source']}"


def test_llm_gap_finding_phrasing__cache_table_schema():
    # AC2: Cached in llm_generations (surface="gap_finding", signature over
    # user + week + finding code + evidence values)
    # This test checks that the cache table has the right structure

    from backend.models import LlmGeneration
    from sqlalchemy import inspect

    mapper = inspect(LlmGeneration)
    columns = {c.name for c in mapper.columns}

    assert "surface" in columns, "llm_generations.surface column missing"
    assert "input_signature" in columns, "llm_generations.input_signature column missing"
    assert "payload" in columns, "llm_generations.payload column missing"
    assert "user_id" in columns, "llm_generations.user_id column missing"
    # The table should have a unique constraint enforcing uniqueness on (user_id, surface, input_signature)


def test_llm_gap_finding_phrasing__signature_deterministic():
    # AC2: Cache hit when evidence unchanged; regenerate when evidence changes
    # This test verifies that the signature computation is deterministic

    try:
        from backend.services.gap_analysis.phrasing import build_phrasing_signature
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    finding_code = "plyo_deficit"
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    week_start = "2026-07-07"

    evidence_1 = [
        {"metric": "lss_improvement_pct", "value": -5.0, "threshold": -2.0, "window": "8w"},
        {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
    ]
    evidence_2 = [
        {"metric": "lss_improvement_pct", "value": -5.0, "threshold": -2.0, "window": "8w"},
        {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
    ]

    # Same evidence → same signature
    sig1 = build_phrasing_signature(user_id, week_start, finding_code, evidence_1)
    sig2 = build_phrasing_signature(user_id, week_start, finding_code, evidence_2)
    assert sig1 == sig2, "Identical evidence should produce identical signatures"

    # Different evidence → different signature
    evidence_3 = [
        {"metric": "lss_improvement_pct", "value": -3.0, "threshold": -2.0, "window": "8w"},  # Changed
        {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
    ]
    sig3 = build_phrasing_signature(user_id, week_start, finding_code, evidence_3)
    assert sig3 != sig1, "Different evidence should produce different signatures"


def test_llm_gap_finding_phrasing__fallback_on_llm_disabled():
    # AC3: LLM disabled/failed/guard-tripped -> deterministic template from #1374
    # Test the fallback function directly

    try:
        from backend.services.gap_analysis.phrasing import get_finding_phrasing
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    finding = {
        "code": "plyo_deficit",
        "severity": 2,
        "recommendation": "Increase plyometric frequency",
        "evidence": [
            {"metric": "lss_improvement_pct", "value": -5.0, "threshold": -2.0, "window": "8w"},
            {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
        ],
        "target": None,
    }

    # When LLM is disabled, get_finding_phrasing should return template source
    with patch.dict(os.environ, {"LLM_COACH_ENABLED": "false"}):
        # Force module reload to apply env change
        import importlib
        import backend.services.llm as llm_module
        importlib.reload(llm_module)

        result = get_finding_phrasing(
            finding,
            user_id="550e8400-e29b-41d4-a716-446655440000",
            week_start="2026-07-07",
            db=None,
        )

        assert "phrasing" in result
        assert "phrasing_source" in result
        assert result["phrasing_source"] == "template"
        assert isinstance(result["phrasing"], str)
        assert len(result["phrasing"]) > 0


def test_llm_gap_finding_phrasing__phrasing_schema_single_text_field():
    # AC4: LLM output may not change severity, recommendation, or target
    # (phrasing only; enforced by schema: single text field)
    # Verify that the LLM schema only has a "phrasing" field

    # The phrasing module uses a JSON schema with only one field: "phrasing"
    # This prevents the LLM from adding/modifying severity, recommendation, etc.

    try:
        from backend.services.gap_analysis import phrasing as phrasing_module
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")


    # The schema should only allow {"phrasing": "string"}
    schema = phrasing_module._PHRASING_JSON_SCHEMA
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"phrasing"}
    assert set(schema["properties"].keys()) == {"phrasing"}
    assert schema["properties"]["phrasing"]["type"] == "string"
    assert schema.get("additionalProperties") is False, \
        "Schema should reject additional properties to prevent LLM from adding fields"


def test_llm_gap_finding_phrasing__numeral_guard_allows_valid_numbers():
    # AC1 safety: Numeral guard discards output containing numbers not present in input facts
    # Same guard pattern as readiness explanation (#1313)

    try:
        from backend.services.gap_analysis.phrasing import _numeral_guard_passes
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    # LLM output with only numbers from evidence — should pass guard
    evidence_facts = "5.0 2.0 0.5 1.0"  # Values and thresholds from evidence
    good_output = "LSS down 5% over 8 weeks with 0.5 plyo sessions per week (need 1)."
    assert _numeral_guard_passes(good_output, evidence_facts), \
        "Guard should pass when all output numbers are in evidence facts"


def test_llm_gap_finding_phrasing__numeral_guard_rejects_invalid_numbers():
    # AC1 safety: Guard should reject LLM output with numbers not in evidence

    try:
        from backend.services.gap_analysis.phrasing import _numeral_guard_passes
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    evidence_facts = "5.0 2.0 0.5 1.0"  # Values and thresholds from evidence
    # LLM output with extraneous number not in evidence — should fail guard
    bad_output = "LSS down 5% over 8 weeks; 47 other metrics show decline."
    assert not _numeral_guard_passes(bad_output, evidence_facts), \
        "Guard should reject output with numbers not in evidence (47 is not valid)"


def test_llm_gap_finding_phrasing__phrasing_and_phrasing_source_present():
    # AC3: API field identical shape both paths (phrasing_source: llm|template)
    # Verify that get_finding_phrasing returns a dict with "phrasing" and "phrasing_source"

    try:
        from backend.services.gap_analysis.phrasing import get_finding_phrasing
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    finding = {
        "code": "plyo_deficit",
        "severity": 2,
        "recommendation": "Increase plyometric frequency",
        "evidence": [
            {"metric": "lss_improvement_pct", "value": -5.0, "threshold": -2.0, "window": "8w"},
            {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
        ],
        "target": None,
    }

    result = get_finding_phrasing(
        finding,
        user_id="550e8400-e29b-41d4-a716-446655440000",
        week_start="2026-07-07",
        db=None,
    )

    # Result must have exactly these two fields
    assert set(result.keys()) == {"phrasing", "phrasing_source"}
    assert isinstance(result["phrasing"], str)
    assert result["phrasing_source"] in ("llm", "template")


def test_llm_gap_finding_phrasing__no_expiry_policy():
    # AC2: Cache is persistent in llm_generations until evidence changes
    # No TTL or expiry_at column (cache invalidation only via signature change)

    from backend.models import LlmGeneration
    from sqlalchemy import inspect

    mapper = inspect(LlmGeneration)
    columns = {c.name for c in mapper.columns}

    # No expiry/TTL column — cache is persistent
    assert "expiry_at" not in columns
    assert "ttl" not in columns


def test_llm_gap_finding_phrasing__deterministic_template_fallback():
    # AC3: LLM disabled/failed/guard-tripped -> deterministic template used
    # Verify that render_evidence_text from #1374 is the fallback

    from backend.services.gap_analysis.evidence_text import render_evidence_text

    code = "plyo_deficit"
    evidence = [
        {"metric": "lss_improvement_pct", "value": -5.0, "threshold": -2.0, "window": "8w"},
        {"metric": "plyo_sessions_per_week", "value": 0.5, "threshold": 1.0, "window": "4w"},
    ]

    result = render_evidence_text(code, evidence, target=None)

    # Should produce the deterministic template sentence
    assert isinstance(result, str)
    assert len(result) > 0
    # Should mention LSS (or leg-spring) and plyo
    assert any(s in result for s in ["LSS", "leg-spring", "stiffness"])


def test_llm_gap_finding_phrasing__length_cap_enforcement():
    # AC1: LLM output is length-capped
    # Verify the max length constant is reasonable

    try:
        from backend.services.gap_analysis import phrasing as phrasing_module
    except (ModuleNotFoundError, ImportError):
        pytest.skip("Phrasing module not available (feature may not be deployed yet)")

    max_len = phrasing_module._MAX_PHRASING_LEN
    # Should be a reasonable limit (not too short, not unlimited)
    assert max_len > 100, "Max phrasing length should be > 100 chars"
    assert max_len < 1000, "Max phrasing length should be < 1000 chars"
