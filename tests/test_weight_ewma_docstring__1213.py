"""Tests for docstring accuracy in weight_ewma.py (issue #1213).

Acceptance criteria covered:

  AC1 - Module docstring states default span is 14, not 7.
  AC2 - Function/class docstring does NOT claim alpha<=0 is treated as
        1/(span+1); instead it describes actual clamping to [0.0, 1.0]
        where alpha=0 remains 0.
  AC3 - No logic, constants, or runtime behaviour changed — only docstrings.
  AC4 - DEFAULT_SPAN = 14 is unchanged and consistent with the docstring.
  AC5 - All existing weight_ewma tests continue to pass (verified by running
        the full suite; this file only covers docstring correctness).
"""

from __future__ import annotations

import inspect
import backend.services.weight_ewma as ewma_module
from backend.services.weight_ewma import compute_ewma, DEFAULT_SPAN


# ---------------------------------------------------------------------------
# AC4 — DEFAULT_SPAN unchanged
# ---------------------------------------------------------------------------

class TestConstant:
    """AC4: DEFAULT_SPAN must remain 14."""

    def test_default_span_is_14(self):
        assert DEFAULT_SPAN == 14


# ---------------------------------------------------------------------------
# AC1 — Module docstring mentions span=14, not span=7
# ---------------------------------------------------------------------------

class TestModuleDocstring:
    """AC1: Module-level docstring states default span is 14."""

    def test_module_docstring_says_span_14(self):
        doc = ewma_module.__doc__ or ""
        assert "14" in doc, (
            "Module docstring must state the default span is 14."
        )

    def test_module_docstring_does_not_say_default_7(self):
        doc = ewma_module.__doc__ or ""
        # Should not describe the default as 7 anywhere in the docstring
        # (a bare "7" for other purposes is allowed, but "span=7" or "default 7" is not)
        assert "default 7" not in doc.lower(), (
            "Module docstring must not describe the default span as 7."
        )
        assert "span=7" not in doc, (
            "Module docstring must not contain 'span=7'."
        )


# ---------------------------------------------------------------------------
# AC2 — Function docstring describes clamping, not 1/(span+1) conversion
# ---------------------------------------------------------------------------

class TestFunctionDocstring:
    """AC2: compute_ewma docstring describes alpha clamping to [0.0, 1.0]."""

    def test_function_docstring_no_1_over_span_plus_1_claim(self):
        doc = inspect.getdoc(compute_ewma) or ""
        # The old incorrect claim used "1 / (span + 1)" or equivalent phrasing
        assert "1 / (span + 1)" not in doc, (
            "Function docstring must not claim alpha<=0 is converted to "
            "1/(span+1); that behaviour does not exist in the code."
        )
        assert "1/(span+1)" not in doc, (
            "Function docstring must not contain '1/(span+1)'."
        )

    def test_function_docstring_describes_clamping(self):
        doc = inspect.getdoc(compute_ewma) or ""
        # The docstring should reference the clamping behaviour
        assert "clamp" in doc.lower() or "[0" in doc or "0.0" in doc, (
            "Function docstring should describe that alpha is clamped to "
            "[0.0, 1.0]; got: {!r}".format(doc)
        )

    def test_alpha_0_freezes_ewma_in_reality(self):
        """AC3 runtime guard: alpha=0 actually freezes the EWMA (code unchanged)."""
        import datetime
        entries = [
            {"date": datetime.date(2026, 1, 1), "weight_kg": 75.0},
            {"date": datetime.date(2026, 1, 2), "weight_kg": 80.0},
            {"date": datetime.date(2026, 1, 3), "weight_kg": 70.0},
        ]
        result = compute_ewma(entries, alpha=0.0)
        # With alpha=0: prev = 0*raw + 1*prev => every value equals first weight
        assert result[0] == 75.0
        assert result[1] == 75.0
        assert result[2] == 75.0


# ---------------------------------------------------------------------------
# AC3 — No code changes, runtime behavior preserved
# ---------------------------------------------------------------------------

class TestNoCodeChanges:
    """AC3: No logic, constants, or runtime behaviour changed."""

    def test_compute_ewma_signature_unchanged(self):
        sig = inspect.signature(compute_ewma)
        params = list(sig.parameters.keys())
        assert params == ["entries", "span", "alpha"], (
            f"Function signature should be unchanged; got {params}"
        )

    def test_alpha_clamping_works_as_documented(self):
        """Verify alpha is truly clamped (not converted) to [0.0, 1.0]."""
        import datetime
        entries = [
            {"date": datetime.date(2026, 1, 1), "weight_kg": 75.0},
            {"date": datetime.date(2026, 1, 2), "weight_kg": 80.0},
        ]

        # alpha < 0 should be clamped to 0
        result_neg = compute_ewma(entries, alpha=-0.5)
        assert result_neg[1] == 75.0, (
            "alpha < 0 should be clamped to 0, freezing at first value"
        )

        # alpha > 1 should be clamped to 1
        result_over = compute_ewma(entries, alpha=2.0)
        assert result_over[1] == 80.0, (
            "alpha > 1 should be clamped to 1, yielding raw value"
        )


# ---------------------------------------------------------------------------
# AC5 — Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingBehavior:
    """AC5: All existing weight_ewma behavior is preserved."""

    def test_empty_list_returns_empty(self):
        result = compute_ewma([])
        assert result == []

    def test_single_entry_returns_single_value(self):
        import datetime
        entries = [{"date": datetime.date(2026, 1, 1), "weight_kg": 75.0}]
        result = compute_ewma(entries)
        assert len(result) == 1
        assert result[0] == 75.0

    def test_constant_weight_stays_flat(self):
        import datetime
        entries = [
            {"date": datetime.date(2026, 1, i + 1), "weight_kg": 75.0}
            for i in range(5)
        ]
        result = compute_ewma(entries)
        for v in result:
            assert abs(v - 75.0) < 1e-9

    def test_spike_resistance_with_default_span_14(self):
        """AC3 from the original #1154: +5kg spike shifts EWMA <1kg."""
        import datetime
        n = 14
        base = 75.0
        spike = base + 5.0
        entries = []
        for i in range(n):
            w = spike if i == n // 2 else base
            entries.append({"date": datetime.date(2026, 1, i + 1), "weight_kg": w})
        result = compute_ewma(entries)
        spike_idx = n // 2
        spike_shift = result[spike_idx] - base
        assert spike_shift < 1.0, (
            f"Spike of +5 kg caused EWMA shift of {spike_shift:.3f} kg "
            f"(must be < 1 kg) with default span=14"
        )
