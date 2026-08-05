"""Tests for issue #1519 — atl parameter is unused in _load_interpretation.

Acceptance criteria:
- AC1: _load_interpretation ignores the atl argument (output is identical
       regardless of the atl value passed).
- AC2: The function body does not reference atl in its logic (confirmed via
       source inspection — the param is prefixed '_atl' to signal unused).
- AC3: _assemble_form still passes atl positionally (interface unchanged).
"""
from __future__ import annotations

import importlib
import inspect


def _svc():
    import backend.services.daily_brief as m
    importlib.reload(m)
    return m


# ── AC1: atl has no effect on the output ─────────────────────────────────────

def test_load_interpretation_ignores_atl_value():
    """AC1: output is identical for any atl value when ctl and tsb are fixed."""
    svc = _svc()
    result_low = svc._load_interpretation(50.0, 0.0, 5.0)
    result_high = svc._load_interpretation(50.0, 999.0, 5.0)
    assert result_low == result_high


# ── AC2: parameter is prefixed to signal it is intentionally unused ───────────

def test_load_interpretation_atl_param_is_prefixed_unused():
    """AC2: the atl parameter is named '_atl' (underscore prefix = intentionally unused)."""
    svc = _svc()
    sig = inspect.signature(svc._load_interpretation)
    params = list(sig.parameters.keys())
    assert "_atl" in params, (
        f"Expected '_atl' in params to signal unused; got {params}"
    )
    assert "atl" not in params, (
        f"Plain 'atl' param still present (must be renamed '_atl'); got {params}"
    )


# ── AC3: caller passes atl to preserve the existing interface ─────────────────

def test_assemble_form_passes_atl_to_load_interpretation():
    """AC3: _assemble_form calls _load_interpretation(ctl, atl, tsb)."""
    svc = _svc()
    src = inspect.getsource(svc._assemble_form)
    assert "_load_interpretation(ctl, atl, tsb)" in src, (
        "_assemble_form must call _load_interpretation(ctl, atl, tsb)"
    )
