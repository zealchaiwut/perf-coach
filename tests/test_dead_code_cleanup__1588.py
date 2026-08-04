"""Tests for issue #1588: dead code cleanup — llm_transport(), _trigger_curve_rebuild_background, tss expire guard.

AC: dead functions removed, no behavior change, grep-clean.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# AC1 — llm_transport() removed from backend/services/llm.py
# ---------------------------------------------------------------------------

def test_llm_transport_not_exported_from_llm_module():
    """llm_transport() must not exist on backend.services.llm after cleanup."""
    import backend.services.llm as llm_mod

    assert not hasattr(llm_mod, "llm_transport"), (
        "llm_transport() still exists in backend.services.llm — it was declared "
        "dead (zero callers) and must be removed."
    )


def test_llm_transport_not_mentioned_in_module_docstring():
    """The module docstring must no longer advertise llm_transport()."""
    import backend.services.llm as llm_mod

    doc = llm_mod.__doc__ or ""
    assert "llm_transport" not in doc, (
        "llm_transport is still listed in the module docstring of "
        "backend/services/llm.py — remove that line too."
    )


def test_llm_module_still_exports_live_functions():
    """Removing llm_transport must not break any live export."""
    from backend.services.llm import llm_enabled, complete_structured, get_or_generate

    assert callable(llm_enabled)
    assert callable(complete_structured)
    assert callable(get_or_generate)


# ---------------------------------------------------------------------------
# AC2 — _trigger_curve_rebuild_background removed from backend/main.py
# ---------------------------------------------------------------------------

def test_trigger_curve_rebuild_not_defined_in_main():
    """_trigger_curve_rebuild_background() must not exist in backend.main after cleanup."""
    import backend.main as main_mod

    assert not hasattr(main_mod, "_trigger_curve_rebuild_background"), (
        "_trigger_curve_rebuild_background() still exists in backend.main — it had "
        "zero callers and the in-process rebuild path was eliminated; delete it."
    )


def test_trigger_curve_rebuild_not_in_main_source():
    """Static check: the symbol must not appear in main.py source at all."""
    main_src = (REPO / "backend" / "main.py").read_text()
    assert "_trigger_curve_rebuild_background" not in main_src, (
        "backend/main.py still contains _trigger_curve_rebuild_background — "
        "remove the function definition."
    )


# ---------------------------------------------------------------------------
# AC3 — tss.py recompute loop retains flush+expire guard
# ---------------------------------------------------------------------------

def test_tss_recompute_loop_has_flush_and_expire():
    """recompute_user_running_tss must call session.flush() and session.expire(w)
    inside its loop so the ORM doesn't accumulate the full history in memory.

    This guard was restored in PR #1576; ensure it wasn't accidentally dropped.
    """
    from backend.services.tss import recompute_user_running_tss

    src = inspect.getsource(recompute_user_running_tss)
    assert "session.flush()" in src, (
        "recompute_user_running_tss() is missing session.flush() — the per-loop "
        "flush+expire guard was required by PR #1576 to prevent ORM memory growth."
    )
    assert "session.expire(w)" in src, (
        "recompute_user_running_tss() is missing session.expire(w) — the per-loop "
        "flush+expire guard was required by PR #1576 to prevent ORM memory growth."
    )
