"""
Tests for issue #473: Document range token day-count semantics in weight-chart.

The range token resolution uses timedelta(days=N-1) for an N-day inclusive
range (e.g. 7D → days=6 so that both from_d and to_d are included).

These tests verify that backend/main.py uses a named RANGE_OFFSETS constant
(rather than scattered magic numbers) so the inclusive semantics are explicit
and the mapping is easy to update if future tickets change semantics.
"""

import pathlib
import ast
import re

MAIN_PY = pathlib.Path(__file__).parent.parent / "backend" / "main.py"


def _source() -> str:
    return MAIN_PY.read_text()


# ── AC-1: RANGE_OFFSETS constant is defined in backend/main.py ────────────────

def test_range_offsets_constant_exists():
    """backend/main.py defines a RANGE_OFFSETS dict-like constant."""
    src = _source()
    assert "RANGE_OFFSETS" in src, (
        "backend/main.py must define RANGE_OFFSETS to document inclusive semantics"
    )


def test_range_offsets_is_dict_literal():
    """RANGE_OFFSETS is a dict mapping token strings to integer day offsets."""
    src = _source()
    # Find the assignment line
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match is not None, "RANGE_OFFSETS must be a dict literal { ... }"
    body = match.group(1)
    # Must contain the 7D key
    assert '"7D"' in body or "'7D'" in body, "RANGE_OFFSETS must include the '7D' token"


# ── AC-2: Each standard token maps to the correct inclusive day offset ─────────

def test_range_offsets_7d_value():
    """RANGE_OFFSETS['7D'] == 6 (today - 6 days → 7 inclusive days)."""
    src = _source()
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match, "RANGE_OFFSETS not found"
    body = match.group(1)
    pair = re.search(r'["\']7D["\']\s*:\s*(\d+)', body)
    assert pair is not None, "RANGE_OFFSETS must contain '7D' key"
    assert int(pair.group(1)) == 6, f"7D offset must be 6 (inclusive), got {pair.group(1)}"


def test_range_offsets_30d_value():
    """RANGE_OFFSETS['30D'] == 29 (today - 29 days → 30 inclusive days)."""
    src = _source()
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match, "RANGE_OFFSETS not found"
    body = match.group(1)
    pair = re.search(r'["\']30D["\']\s*:\s*(\d+)', body)
    assert pair is not None, "RANGE_OFFSETS must contain '30D' key"
    assert int(pair.group(1)) == 29, f"30D offset must be 29 (inclusive), got {pair.group(1)}"


def test_range_offsets_90d_value():
    """RANGE_OFFSETS['90D'] == 89 (today - 89 days → 90 inclusive days)."""
    src = _source()
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match, "RANGE_OFFSETS not found"
    body = match.group(1)
    pair = re.search(r'["\']90D["\']\s*:\s*(\d+)', body)
    assert pair is not None, "RANGE_OFFSETS must contain '90D' key"
    assert int(pair.group(1)) == 89, f"90D offset must be 89 (inclusive), got {pair.group(1)}"


def test_range_offsets_6m_value():
    """RANGE_OFFSETS['6M'] == 183 (today - 183 days → 6 calendar months approx)."""
    src = _source()
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match, "RANGE_OFFSETS not found"
    body = match.group(1)
    pair = re.search(r'["\']6M["\']\s*:\s*(\d+)', body)
    assert pair is not None, "RANGE_OFFSETS must contain '6M' key"
    assert int(pair.group(1)) == 183, f"6M offset must be 183 (inclusive), got {pair.group(1)}"


def test_range_offsets_1y_value():
    """RANGE_OFFSETS['1Y'] == 364 (today - 364 days → 365 inclusive days)."""
    src = _source()
    match = re.search(r'RANGE_OFFSETS\s*=\s*\{([^}]+)\}', src)
    assert match, "RANGE_OFFSETS not found"
    body = match.group(1)
    pair = re.search(r'["\']1Y["\']\s*:\s*(\d+)', body)
    assert pair is not None, "RANGE_OFFSETS must contain '1Y' key"
    assert int(pair.group(1)) == 364, f"1Y offset must be 364 (inclusive), got {pair.group(1)}"


# ── AC-3: RANGE_OFFSETS is consumed in the range-token resolution block ────────

def test_range_offsets_used_in_resolution():
    """backend/main.py uses RANGE_OFFSETS (not bare magic-number timedeltas) to resolve tokens."""
    src = _source()
    assert "RANGE_OFFSETS" in src, "RANGE_OFFSETS must be defined"
    # After the definition it should be referenced (subscripted) inside get_weight_chart
    # i.e. RANGE_OFFSETS[range_token] or .get(range_token)
    usage_patterns = [
        r'RANGE_OFFSETS\[',
        r'RANGE_OFFSETS\.get\(',
        r'for .+ in RANGE_OFFSETS',
    ]
    found = any(re.search(p, src) for p in usage_patterns)
    assert found, (
        "RANGE_OFFSETS must be subscripted or iterated in the resolution logic "
        "(e.g. RANGE_OFFSETS[range_token])"
    )


# ── AC-4: A comment explaining inclusive semantics is present ─────────────────

def test_inclusive_semantics_comment_present():
    """backend/main.py contains a comment explaining the inclusive day-count convention."""
    src = _source()
    # Look for a comment near RANGE_OFFSETS that mentions 'inclusive'
    # Accept any comment on the same block that uses the word
    block_match = re.search(r'RANGE_OFFSETS[\s\S]{0,300}inclusive', src)
    comment_match = re.search(r'#[^\n]*inclusive[^\n]*', src)
    assert block_match is not None or comment_match is not None, (
        "A comment explaining inclusive semantics (the word 'inclusive') must appear "
        "near RANGE_OFFSETS or in the range-token resolution block"
    )
