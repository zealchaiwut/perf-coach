"""
TDD tests for issue #516 — Fix dead chart zones and stale width comment.

AC anchors:
  (ac1) FUTURE_W is >= 110 viewBox units (CW=834), enabling the MILESTONES AHEAD
        path to render, OR the milestone-ahead code path is removed entirely.
  (ac2) PAST_W reflects intentional UX — not an accidental 5% leftover.
  (ac3) The width-split comment at weight-chart.js:11 matches PAST_W, FUTURE_W,
        and the center-zone constants actually in the code.
  (ac4) Three-zone background tints and separator lines are still rendered when
        a target exists (no visual regression).
"""
from pathlib import Path
import re

CHART_JS = Path(__file__).parent.parent / "frontend" / "js" / "weight-chart.js"

# Viewbox constants — must stay in sync with weight-chart.js preamble
VW = 900
PAD_LEFT = 50
PAD_RIGHT = 16
CW = VW - PAD_LEFT - PAD_RIGHT  # 834


def _src():
    return CHART_JS.read_text()


# ── AC1: FUTURE_W is reachable, or milestone-ahead path is removed ────────────

def test_ac1_future_w_threshold_is_reachable():
    """AC1: FUTURE_W >= 110 is achievable at CW=834, OR the `if (FUTURE_W >= 110)` guard is absent."""
    src = _src()
    has_guard = "FUTURE_W >= 110" in src

    if has_guard:
        m = re.search(r"const\s+FUTURE_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
        assert m, "Cannot parse FUTURE_W definition from weight-chart.js"
        mult = float(m.group(1))
        future_w = round(CW * mult)
        assert future_w >= 110, (
            f"FUTURE_W = {future_w} (CW * {mult}) < 110 — "
            f"'MILESTONES AHEAD' path is dead code. "
            f"Raise multiplier to >= {110 / CW:.3f} or remove the guard."
        )
    # Guard absent → milestone-ahead path removed → AC1 satisfied by removal


def test_ac1_future_zone_is_internally_consistent():
    """AC1: If the FUTURE_W >= 110 guard exists, the milestone rendering block must follow."""
    src = _src()
    has_guard = "FUTURE_W >= 110" in src
    has_milestone_block = "hasFutureZone" in src or "future_milestones" in src
    if has_guard:
        assert has_milestone_block, (
            "FUTURE_W >= 110 guard exists but milestone rendering block (hasFutureZone / "
            "future_milestones) is missing — inconsistent state."
        )


# ── AC2: PAST_W reflects intentional UX ──────────────────────────────────────

def test_ac2_past_w_is_not_5_percent():
    """AC2: PAST_W multiplier is not 0.05 — a 5% sliver was an accidental leftover."""
    src = _src()
    m = re.search(r"const\s+PAST_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    assert m, "Cannot parse PAST_W definition from weight-chart.js"
    mult = float(m.group(1))
    assert mult != 0.05, (
        f"PAST_W is still 5% (CW * 0.05) — identified as an accidental leftover. "
        f"Update to an intentional value (e.g. 0.20) that matches the zone-layout comment."
    )


def test_ac2_past_w_is_visible_zone():
    """AC2: PAST_W resolves to a meaningful zone width (>= 50 viewBox units at CW=834)."""
    src = _src()
    m = re.search(r"const\s+PAST_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    assert m, "Cannot parse PAST_W definition from weight-chart.js"
    past_w = round(CW * float(m.group(1)))
    assert past_w >= 50, (
        f"PAST_W = {past_w} is too narrow to be an intentional historical-context zone. "
        f"Raise the multiplier to produce a visible past zone."
    )


# ── AC3: Comment matches actual values ────────────────────────────────────────

def test_ac3_comment_past_pct_matches_code():
    """AC3: '[past XX%]' in the zone-layout comment equals the actual PAST_W multiplier."""
    src = _src()
    comment_m = re.search(r"\[past\s+(\d+)%\]", src, re.IGNORECASE)
    assert comment_m, (
        "Zone-layout comment is missing or malformed — expected '[past XX%]' near line 11."
    )
    comment_pct = int(comment_m.group(1))

    code_m = re.search(r"const\s+PAST_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    assert code_m, "Cannot parse PAST_W definition from weight-chart.js"
    actual_pct = round(float(code_m.group(1)) * 100)

    assert comment_pct == actual_pct, (
        f"Comment says 'past {comment_pct}%' but PAST_W uses {actual_pct}% — "
        f"update the code or the comment so they agree."
    )


def test_ac3_comment_future_pct_matches_code():
    """AC3: '[future XX%]' in the zone-layout comment equals the actual FUTURE_W multiplier."""
    src = _src()
    comment_m = re.search(r"\[future\s+(\d+)%\]", src, re.IGNORECASE)
    assert comment_m, (
        "Zone-layout comment is missing or malformed — expected '[future XX%]' near line 11."
    )
    comment_pct = int(comment_m.group(1))

    code_m = re.search(r"const\s+FUTURE_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    assert code_m, "Cannot parse FUTURE_W definition from weight-chart.js"
    actual_pct = round(float(code_m.group(1)) * 100)

    assert comment_pct == actual_pct, (
        f"Comment says 'future {comment_pct}%' but FUTURE_W uses {actual_pct}% — "
        f"update the code or the comment so they agree."
    )


def test_ac3_comment_current_pct_matches_derived_center():
    """AC3: '[current XX%]' in the comment equals 100 - PAST_W% - FUTURE_W%."""
    src = _src()
    comment_m = re.search(r"\[current\s+(\d+)%\]", src, re.IGNORECASE)
    assert comment_m, (
        "Zone-layout comment is missing or malformed — expected '[current XX%]' near line 11."
    )
    comment_pct = int(comment_m.group(1))

    past_m   = re.search(r"const\s+PAST_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    future_m = re.search(r"const\s+FUTURE_W\s*=\s*Math\.round\(CW\s*\*\s*([\d.]+)\)", src)
    assert past_m and future_m, "Cannot parse PAST_W / FUTURE_W from weight-chart.js"

    past_pct   = round(float(past_m.group(1)) * 100)
    future_pct = round(float(future_m.group(1)) * 100)
    center_pct = 100 - past_pct - future_pct

    assert comment_pct == center_pct, (
        f"Comment says 'current {comment_pct}%' but actual center zone is "
        f"{center_pct}% (100 - {past_pct}% - {future_pct}%) — "
        f"update the code multipliers or the comment."
    )


# ── AC4: Zone rendering still intact (no visual regression) ──────────────────

def test_ac4_past_zone_tint_code_present():
    """AC4: Past-zone grey tint rect is still referenced in the three-zone render block."""
    src = _src()
    assert "PAST_L" in src and "PAST_W" in src, (
        "PAST_L / PAST_W references removed — past-zone tint rect was deleted."
    )
    assert "f3f4f6" in src, (
        "Past-zone fill color '#f3f4f6' missing — past-zone tint was removed."
    )


def test_ac4_future_zone_tint_code_present():
    """AC4: Future-zone blue tint rect is still referenced in the three-zone render block."""
    src = _src()
    assert "FUTURE_L" in src and "FUTURE_W" in src, (
        "FUTURE_L / FUTURE_W references removed — future-zone tint rect was deleted."
    )
    assert "future_bg" in src, (
        "future_bg color reference missing — future-zone tint fill was removed."
    )


def test_ac4_zone_separators_code_present():
    """AC4: Thin separator lines between zones are still rendered (PAST_R and CUR_R3 used)."""
    src = _src()
    assert "PAST_R" in src, (
        "PAST_R reference missing — zone separator between past/current was removed."
    )
    assert "CUR_R3" in src, (
        "CUR_R3 reference missing — zone separator between current/future was removed."
    )
    assert "C_SEP" in src, (
        "C_SEP (separator stroke color) missing — separator line styling was removed."
    )


def test_ac4_three_zone_layout_constants_still_derived():
    """AC4: CUR_W3, CUR_L3, CUR_R3 are still derived from PAST_W and FUTURE_W."""
    src = _src()
    assert "CUR_W3" in src, "CUR_W3 (current zone width) removed from weight-chart.js"
    assert "CUR_L3" in src, "CUR_L3 (current zone left edge) removed from weight-chart.js"
    assert "CUR_R3" in src, "CUR_R3 (current zone right edge) removed from weight-chart.js"
