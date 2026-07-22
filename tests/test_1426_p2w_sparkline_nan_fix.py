"""Tests for issue #1426: P2W sparkline NaN path coords on null w_per_kg days.

AC anchors:
  AC1: _p2wDrawSparkline path-builder must not produce NaN for null pts.
       The old blind .map() over all pts (i ? 'L' : 'M') + x + ' ' + y
       emits NaN coords for null v.  The fix must NOT use that index-only
       M/L decision — it must be null-aware.
  AC2: Nulls create a gap: next non-null point after a null must emit a new
       M (move-to) rather than L (line-to), producing a broken-line instead
       of an invalid degenerate path.
  AC3: All-non-null series still renders a valid contiguous path; the min/max
       scaling logic is intact.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEIGHT_JS = (ROOT / "frontend" / "js" / "weight.js").read_text()

# Extract just the _p2wDrawSparkline function body for targeted checks.
_FN_MATCH = re.search(
    r'function _p2wDrawSparkline\s*\([^)]*\)\s*\{(.+?)(?=\nfunction |\Z)',
    WEIGHT_JS,
    re.DOTALL,
)
_P2W_BODY = _FN_MATCH.group(1) if _FN_MATCH else ""


class TestAC1_NoIndexOnlyPathDecision:
    """AC1: the old (i ? 'L' : 'M') pattern is index-only — it emits NaN for nulls.

    After the fix the M-vs-L decision must consider null, not just position.
    """

    def test_old_index_only_m_l_pattern_removed(self):
        """The buggy (i ? 'L' : 'M') or (i === 0 ? 'M' : 'L') pattern must be gone.

        This exact pattern maps over ALL pts and uses the array index to choose
        M vs L, ignoring null values.  Any null v causes (v - mn) = NaN in y.
        """
        assert _P2W_BODY, "_p2wDrawSparkline function body could not be extracted"

        # Match: (i ? 'L' : 'M') or (i ? "L" : "M") in various spacing forms
        index_only_ml = re.search(
            r'''\(\s*i\s*\?\s*['"]L['"]\s*:\s*['"]M['"]\s*\)''',
            _P2W_BODY,
        )
        assert index_only_ml is None, (
            "Buggy index-only (i ? 'L' : 'M') pattern found in _p2wDrawSparkline. "
            "This emits NaN path coords for null pts.  Replace with a null-aware "
            "reduce/loop that emits 'M' for the first non-null after a gap."
        )

    def test_path_builder_is_null_aware(self):
        """The path-building section must skip null values explicitly.

        Acceptable patterns (any one suffices):
          (a) .reduce() accumulator that skips null v
          (b) for/forEach loop that skips null v with a continue/return
          (c) .map() whose callback has an explicit null guard before computing y
        """
        assert _P2W_BODY, "_p2wDrawSparkline function body could not be extracted"

        # Check (a): reduce present — reduce is the natural fit for building a
        # running string while tracking gap state
        has_reduce = ".reduce(" in _P2W_BODY

        # Check (b): an explicit loop that can skip nulls
        has_loop = bool(re.search(r'\bfor\s*\(|\bforEach\s*\(', _P2W_BODY))

        # Check (c): map callback that guards null BEFORE computing (v - mn)
        # Heuristic: map + null check appearing before the arithmetic
        has_null_guarded_map = (
            ".map(" in _P2W_BODY
            and bool(re.search(r'if\s*\(\s*v\s*==\s*null', _P2W_BODY))
        )

        assert has_reduce or has_loop or has_null_guarded_map, (
            "_p2wDrawSparkline path builder must be null-aware. "
            "Use reduce(), a for/forEach loop, or a .map() with explicit null guard."
        )


class TestAC2_GapSubpath:
    """AC2: null days produce a gap (new M subpath) not NaN coords."""

    def test_m_command_emitted_for_post_null_point(self):
        """After a null gap, the next non-null point must start a new M subpath.

        The fixed code must have logic that emits 'M' when the preceding point
        was null — not just when i === 0.  This ensures gaps in the series
        produce separate line segments rather than an invalid path.
        """
        assert _P2W_BODY, "_p2wDrawSparkline function body could not be extracted"

        # The function must contain 'M' (the SVG move-to command)
        has_m_cmd = "'M'" in _P2W_BODY or '"M"' in _P2W_BODY
        assert has_m_cmd, "Path must include 'M' (move-to) SVG command"

        # The 'M' command must be chosen based on null-awareness, not just index 0.
        # Pattern: emit M when previous point is null OR when starting accumulation.
        # We look for null checks near 'M' in the path-building section.
        null_near_m = bool(re.search(
            r'''(?:null|== null|!= null).{0,200}['"]M['"]|['"]M['"].{0,200}(?:null|== null|!= null)''',
            _P2W_BODY,
            re.DOTALL,
        ))
        # Alternative: accumulator-empty check ('' === acc) triggers M for first point
        empty_acc_check = bool(re.search(r'''===\s*['"]['"]\s*|['""]\s*===\s*acc|acc\s*===\s*['"]''', _P2W_BODY))

        assert null_near_m or empty_acc_check, (
            "The 'M' command must be emitted based on null-awareness (gap detection), "
            "not just the position index.  After a null gap, the next non-null point "
            "must start a new subpath with M."
        )


class TestAC3_CoreScalingIntact:
    """AC3: all-non-null series still renders correctly."""

    def test_min_max_computed_from_valid_points(self):
        """min/max scaling must still use only non-null (valid) points."""
        assert _P2W_BODY, "_p2wDrawSparkline function body could not be extracted"
        assert "valid" in _P2W_BODY, (
            "_p2wDrawSparkline must filter to valid (non-null) points for min/max"
        )
        assert "Math.min" in _P2W_BODY, "Math.min must still be used for scaling"
        assert "Math.max" in _P2W_BODY, "Math.max must still be used for scaling"

    def test_svg_path_element_created(self):
        """The function must still create and append an SVG path element."""
        assert _P2W_BODY, "_p2wDrawSparkline function body could not be extracted"
        assert "createElementNS" in _P2W_BODY, (
            "_p2wDrawSparkline must create the path via createElementNS"
        )
        assert "setAttribute" in _P2W_BODY, (
            "_p2wDrawSparkline must set SVG path attributes"
        )
        assert "appendChild" in _P2W_BODY, (
            "_p2wDrawSparkline must append the path to the SVG element"
        )
