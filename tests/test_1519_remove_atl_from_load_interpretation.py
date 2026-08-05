"""Tests for issue #1519 — remove unused atl parameter from _load_interpretation.

Acceptance criteria (derived from issue):
- AC1: _load_interpretation accepts exactly (ctl, tsb) — no atl parameter.
- AC2: The function body still returns the correct label for every TSB band.
- AC3: _assemble_form no longer passes atl to _load_interpretation.
"""
from __future__ import annotations

import inspect
import importlib

import pytest


def _svc():
    import backend.services.daily_brief as m
    importlib.reload(m)
    return m


# ── AC1: signature check ──────────────────────────────────────────────────────

def test_load_interpretation_does_not_accept_atl():
    """AC1: _load_interpretation signature must be (ctl, tsb) with no atl param."""
    svc = _svc()
    sig = inspect.signature(svc._load_interpretation)
    params = list(sig.parameters.keys())
    assert "atl" not in params, (
        f"_load_interpretation still has 'atl' param; got params: {params}"
    )
    assert params == ["ctl", "tsb"], (
        f"Expected params ['ctl', 'tsb'], got {params}"
    )


def test_load_interpretation_called_with_two_args():
    """AC1: _load_interpretation can be called with two positional args."""
    svc = _svc()
    result = svc._load_interpretation(50.0, 10.0)
    assert isinstance(result, str)


def test_load_interpretation_rejects_three_positional_args():
    """AC1: Calling with three positional args raises TypeError."""
    svc = _svc()
    with pytest.raises(TypeError):
        svc._load_interpretation(50.0, 40.0, 10.0)


# ── AC2: label correctness ────────────────────────────────────────────────────

@pytest.mark.parametrize("ctl,tsb,expected", [
    (50.0, 10.0, "Fresh"),
    (50.0, 2.0, "Neutral"),
    (50.0, -8.0, "Productive"),
    (50.0, -22.0, "Overreached"),
    (65.0, 5.0, "well-trained"),
    (20.0, 5.0, "undertrained"),
])
def test_load_interpretation_label(ctl, tsb, expected):
    """AC2: Each TSB / CTL combination maps to the expected label fragment."""
    svc = _svc()
    result = svc._load_interpretation(ctl, tsb)
    assert expected in result, f"Expected {expected!r} in {result!r} (ctl={ctl}, tsb={tsb})"


# ── AC3: caller updated ───────────────────────────────────────────────────────

def test_assemble_form_source_does_not_pass_atl_to_load_interpretation():
    """AC3: _assemble_form source no longer passes atl to _load_interpretation."""
    svc = _svc()
    src = inspect.getsource(svc._assemble_form)
    # After the fix, the call should be _load_interpretation(ctl, tsb) not (ctl, atl, tsb)
    assert "_load_interpretation(ctl, atl, tsb)" not in src, (
        "_assemble_form still passes atl to _load_interpretation"
    )
    assert "_load_interpretation(ctl, tsb)" in src, (
        "_assemble_form must call _load_interpretation(ctl, tsb)"
    )
