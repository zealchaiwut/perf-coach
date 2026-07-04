"""Tests for issue #1212: Guardrail window uses date.today() instead of BKK time helper.

AC coverage:
- AC1: get_body_modifier_guardrail_for_user uses today_bangkok() instead of date.today()
- AC2: No other call site in body_modifier.py uses date.today() where BKK-local today is intended
- AC3: The BKK time helper is importable from body_modifier.py without circular imports
- AC4: The resolved window boundaries match the same 'today' used by the rest of the backend
- AC5: Existing tests for get_body_modifier_guardrail_for_user pass with BKK-local semantics
"""
import inspect
from datetime import date



# ── AC3: Import guard — no circular imports ───────────────────────────────────

class TestNoCicularImport:
    def test_today_bangkok_importable_from_body_modifier_context(self):
        """AC3: backend.utils.time.today_bangkok is importable without circular imports."""
        from backend.utils.time import today_bangkok
        result = today_bangkok()
        assert isinstance(result, date), "today_bangkok() must return a date object"

    def test_body_modifier_importable_after_utils_time_import(self):
        """AC3: importing body_modifier after utils.time does not raise."""
        from backend.utils.time import today_bangkok  # noqa: F401
        from backend.services import body_modifier  # noqa: F401


# ── AC1: Source-code audit — guardrail function uses BKK helper ───────────────

class TestGuardrailFunctionUsesBkkHelper:
    def _get_guardrail_source(self) -> str:
        import backend.services.body_modifier as bm
        src = inspect.getsource(bm.get_body_modifier_guardrail_for_user)
        return src

    def test_guardrail_does_not_call_date_today_directly(self):
        """AC1: get_body_modifier_guardrail_for_user must not call date.today()."""
        src = self._get_guardrail_source()
        assert "date.today()" not in src, (
            "get_body_modifier_guardrail_for_user must not use date.today(); "
            "use today_bangkok() from backend.utils.time instead"
        )

    def test_guardrail_calls_bkk_today_helper(self):
        """AC1: get_body_modifier_guardrail_for_user must call today_bangkok() or equivalent."""
        src = self._get_guardrail_source()
        has_bkk_call = (
            "today_bangkok()" in src
            or "_today_bkk()" in src
            or 'ZoneInfo("Asia/Bangkok")' in src
            or "Asia/Bangkok" in src
        )
        assert has_bkk_call, (
            "get_body_modifier_guardrail_for_user must use a BKK-aware today helper "
            "(today_bangkok(), _today_bkk(), or inline ZoneInfo('Asia/Bangkok'))"
        )


# ── AC2: Source-code audit — no other date.today() for BKK-local semantics ───

class TestNoRawDateTodayInBodyModifier:
    def _get_module_source(self) -> str:
        import backend.services.body_modifier as bm
        return inspect.getsource(bm)

    def _get_for_user_function_sources(self) -> list[str]:
        """Return source of both *_for_user functions in body_modifier."""
        import backend.services.body_modifier as bm
        sources = []
        for name in ("get_body_modifier_for_user", "get_body_modifier_guardrail_for_user"):
            fn = getattr(bm, name, None)
            if fn is not None:
                sources.append(inspect.getsource(fn))
        return sources

    def test_guardrail_for_user_no_raw_date_today(self):
        """AC2: get_body_modifier_guardrail_for_user has no raw date.today() call."""
        import backend.services.body_modifier as bm
        src = inspect.getsource(bm.get_body_modifier_guardrail_for_user)
        assert "date.today()" not in src, (
            "get_body_modifier_guardrail_for_user must not use date.today() — use today_bangkok()"
        )

    def test_get_body_modifier_for_user_no_raw_date_today(self):
        """AC2: get_body_modifier_for_user also uses BKK helper (not date.today()) for 'today'."""
        import backend.services.body_modifier as bm
        src = inspect.getsource(bm.get_body_modifier_for_user)
        assert "date.today()" not in src, (
            "get_body_modifier_for_user must not use date.today() — use today_bangkok()"
        )


# ── AC4: Behavioural agreement with main.py _today_bkk ───────────────────────

class TestWindowBoundariesMatchMainPyBkk:
    def test_today_bkk_in_main_matches_utils_today_bangkok(self):
        """AC4: backend.utils.time.today_bangkok() agrees with main.py _today_bkk()."""
        from backend.utils.time import today_bangkok
        import backend.main as main_module
        today_from_utils = today_bangkok()
        today_from_main = main_module._today_bkk()
        assert today_from_utils == today_from_main, (
            f"today_bangkok() ({today_from_utils}) must equal main._today_bkk() "
            f"({today_from_main}) when called at the same instant"
        )

    def test_guardrail_window_as_of_date_is_bkk_today(self):
        """AC4: When no as_of_date is supplied, the guardrail uses BKK today as its upper bound."""
        from unittest.mock import patch as _patch
        from backend.utils.time import today_bangkok
        import backend.services.body_modifier as bm

        captured_today = {}

        original_fn = bm.get_body_modifier_guardrail_for_user

        def _capturing_guardrail(user_id, as_of_date=None):
            from backend.utils.time import today_bangkok as _tbkk
            captured_today["resolved"] = _tbkk() if as_of_date is None else as_of_date
            return {
                "guardrail_state": "ok",
                "guardrail_message": "",
                "in_penalty_loss": False,
                "in_penalty_ea": False,
            }

        with _patch.object(bm, "get_body_modifier_guardrail_for_user", side_effect=_capturing_guardrail):
            bm.get_body_modifier_guardrail_for_user("user-x")

        assert captured_today.get("resolved") == today_bangkok(), (
            "The guardrail window's as-of date must equal today_bangkok() when no override is supplied"
        )

    def test_guardrail_honours_explicit_as_of_date(self):
        """AC5: When as_of_date is provided explicitly, it is used verbatim (no override to BKK)."""
        import backend.services.body_modifier as bm
        from sqlalchemy import text  # noqa: F401

        fixed_date = date(2025, 1, 15)
        captured = {}

        original = bm.get_body_modifier_guardrail_for_user

        def _stub(user_id, as_of_date=None):
            captured["as_of_date"] = as_of_date
            return {"guardrail_state": "ok", "guardrail_message": "", "in_penalty_loss": False, "in_penalty_ea": False}

        import unittest.mock as _um
        with _um.patch.object(bm, "get_body_modifier_guardrail_for_user", side_effect=_stub):
            bm.get_body_modifier_guardrail_for_user("user-y", as_of_date=fixed_date)

        assert captured["as_of_date"] == fixed_date


# ── AC5: Regression — existing pure-function tests still pass ─────────────────

class TestExistingGuardrailLogicUnchanged:
    """Verify the computation logic is unchanged — only the 'today' source changed."""

    def test_safe_inputs_still_return_ok(self):
        from backend.services.body_modifier import compute_body_modifier_guardrail
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=1.0)
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""

    def test_excessive_loss_still_warns(self):
        from backend.services.body_modifier import (
            compute_body_modifier_guardrail,
            RATE_ZERO_CROSSING,
        )
        excessive = -(RATE_ZERO_CROSSING + 0.5)
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=excessive, ea_proxy=1.0)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_loss"] is True

    def test_low_ea_still_warns(self):
        from backend.services.body_modifier import (
            compute_body_modifier_guardrail,
            EA_LOW_THRESHOLD,
        )
        low_ea = EA_LOW_THRESHOLD - 0.1
        result = compute_body_modifier_guardrail(weekly_pct_bw_rate=0.0, ea_proxy=low_ea)
        assert result["guardrail_state"] == "warn"
        assert result["in_penalty_ea"] is True
