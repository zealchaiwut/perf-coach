"""Tests for issue #1519 — atl parameter removed from _load_interpretation.

Acceptance criteria (from issue #1519):
- AC1: _load_interpretation ignores atl — the parameter is fully removed so
       the function signature is (ctl, tsb).
- AC2: The function body does not reference atl in any form (no _atl param,
       no atl reference).
- AC3: _assemble_form is updated to call _load_interpretation(ctl, tsb).
"""
from __future__ import annotations

import importlib
import inspect


def _svc():
    import backend.services.daily_brief as m
    importlib.reload(m)
    return m


# ── AC1: atl parameter is fully removed ──────────────────────────────────────

def test_load_interpretation_ignores_atl_value():
    """AC1: function works with (ctl, tsb) only — no atl accepted."""
    svc = _svc()
    result_a = svc._load_interpretation(50.0, 5.0)
    result_b = svc._load_interpretation(50.0, 5.0)
    assert result_a == result_b
    assert isinstance(result_a, str)


# ── AC2: no atl reference in params ──────────────────────────────────────────

def test_load_interpretation_atl_param_is_prefixed_unused():
    """AC2: neither 'atl' nor '_atl' appear in _load_interpretation's params."""
    svc = _svc()
    sig = inspect.signature(svc._load_interpretation)
    params = list(sig.parameters.keys())
    assert "atl" not in params, (
        f"'atl' param still present; got {params}"
    )
    assert "_atl" not in params, (
        f"'_atl' param still present; got {params}"
    )
    assert params == ["ctl", "tsb"], (
        f"Expected params ['ctl', 'tsb'], got {params}"
    )


# ── AC3: caller no longer passes atl ─────────────────────────────────────────

def test_assemble_form_passes_atl_to_load_interpretation():
    """AC3: _assemble_form calls _load_interpretation(ctl, tsb) without atl."""
    svc = _svc()
    src = inspect.getsource(svc._assemble_form)
    assert "_load_interpretation(ctl, atl, tsb)" not in src, (
        "_assemble_form still passes atl to _load_interpretation"
    )
    assert "_load_interpretation(ctl, tsb)" in src, (
        "_assemble_form must call _load_interpretation(ctl, tsb)"
    )
