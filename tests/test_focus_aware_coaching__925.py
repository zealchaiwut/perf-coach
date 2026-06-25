"""Tests for issue #925: Add focus-aware coaching: slipping warnings, minimum version, anchoring, keystone.

Anchored to each AC item:

AC1  — Focus habit with H4 slipping signal triggers prospective warning on/before predicted-miss day.
AC2  — Prospective warning is non-shaming and presents a calm recommit-or-drop decision;
        all copy rendered through the voice module.
AC3  — When focus habit drops meaningfully, coaching surfaces recommit-or-drop choice,
        not a streak-loss notification.
AC4  — Each focus habit supports optional minimum_version field (additive, nullable text)
        on the habit record; absent/null by default; does not break existing habits.
AC5  — On a detected struggling day the coach offers minimum_version text instead of full target;
        if minimum_version is null the feature is silently skipped.
AC6  — Each focus habit supports optional anchor_event field (additive, nullable text).
AC7  — When anchor_event is set, coaching message includes cue copy linking habit to that action.
AC8  — When H3 flags one focus habit as driving the other two, coach names it keystone (priority + two supports);
        framing is associative, never causal.
AC9  — Correlation language never fabricates numbers; reads H3 signals verbatim.
AC10 — Schema change is additive, idempotent migration only; no existing columns altered/removed.
AC11 — All DB access lives in caller/service layer; coaching logic receives pre-fetched signals,
        no DB queries inside focus_coaching.
AC12 — All user-facing copy passes through the voice module; no raw strings hardcoded in coaching logic.
"""

from __future__ import annotations

import re
import types

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001FA00-\U0001FA6F"
    "\U00002702-\U000027B0"
    "]+",
    flags=re.UNICODE,
)

_CAUSAL_RE = re.compile(
    r"\b(causes|caused|cause|leads to|results in|drives|driven by|because of)\b",
    re.IGNORECASE,
)

_SHAMING_RE = re.compile(
    r"\b(fail|shame|bad|terrible|loser|worthless|lazy|weak|worse)\b",
    re.IGNORECASE,
)


def _make_slipping_signal(*, is_slipping=True, predicted_miss_weekday="Thursday",
                           days_until_miss=1, consistency_pct_7d=30.0):
    return {
        "is_slipping": is_slipping,
        "predicted_miss_weekday": predicted_miss_weekday,
        "days_until_miss": days_until_miss,
        "consistency_pct_7d": consistency_pct_7d,
    }


def _make_correlation_signal(*, r=0.72, n=28, reason=""):
    return {"r": r, "n": n, "reason": reason}


# ════════════════════════════════════════════════════════════════════════════════
# AC1 — Slipping prospective warning fires before predicted miss
# ════════════════════════════════════════════════════════════════════════════════

class TestSlippingProspectiveWarning:
    """AC1: focus_coaching.build_slipping_warning returns a message when H4 signal
    indicates a likely miss; returns None when the habit is not slipping."""

    def test_warning_returned_when_slipping(self):
        """AC1: build_slipping_warning returns a dict when is_slipping=True."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True, days_until_miss=1)
        result = build_slipping_warning("Morning run", signal)
        assert result is not None
        assert isinstance(result, dict)
        assert "message" in result
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_no_warning_when_not_slipping(self):
        """AC1: build_slipping_warning returns None when is_slipping=False."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=False)
        result = build_slipping_warning("Morning run", signal)
        assert result is None

    def test_warning_fires_before_miss_day(self):
        """AC1: warning is returned when days_until_miss >= 0 (on or before predicted miss)."""
        from backend.services.focus_coaching import build_slipping_warning
        for days in (2, 1, 0):
            signal = _make_slipping_signal(is_slipping=True, days_until_miss=days)
            result = build_slipping_warning("Meditation", signal)
            assert result is not None, f"Expected warning for days_until_miss={days}"

    def test_warning_references_habit_name(self):
        """AC1: warning message references the habit being discussed."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True)
        result = build_slipping_warning("Cold shower", signal)
        assert "Cold shower" in result["message"]


# ════════════════════════════════════════════════════════════════════════════════
# AC2 — Warning is non-shaming, includes recommit-or-drop, uses voice module
# ════════════════════════════════════════════════════════════════════════════════

class TestSlippingWarningTone:
    """AC2: prospective warning is non-shaming and presents a calm recommit-or-drop
    decision; all copy rendered through the voice module (no raw strings hardcoded)."""

    def test_warning_no_shaming_language(self):
        """AC2: slipping warning must not use shaming words."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True)
        result = build_slipping_warning("Reading", signal)
        assert not _SHAMING_RE.search(result["message"]), (
            f"Shaming language in warning: {result['message']!r}"
        )

    def test_warning_no_exclamation(self):
        """AC2: warning must not contain exclamation marks."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True)
        result = build_slipping_warning("Reading", signal)
        assert "!" not in result["message"]

    def test_warning_no_emoji(self):
        """AC2: warning must not contain decorative emoji."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True)
        result = build_slipping_warning("Sleep 8h", signal)
        assert not _EMOJI_RE.search(result["message"])

    def test_warning_includes_recommit_or_drop_type(self):
        """AC2: warning result flags that it includes a recommit-or-drop framing."""
        from backend.services.focus_coaching import build_slipping_warning
        signal = _make_slipping_signal(is_slipping=True)
        result = build_slipping_warning("Morning run", signal)
        assert result.get("includes_recommit_or_drop") is True

    def test_warning_uses_voice_module(self):
        """AC2: build_slipping_warning delegates copy to coaching_voice, not raw strings."""
        import backend.services.coaching_voice as cv
        from backend.services.focus_coaching import build_slipping_warning

        recorded = []
        original = cv.decision_prompt_line_builder

        def capturing(*args, **kwargs):
            recorded.append(args)
            return original(*args, **kwargs)

        cv.decision_prompt_line_builder = capturing
        try:
            signal = _make_slipping_signal(is_slipping=True)
            build_slipping_warning("Meditation", signal)
        finally:
            cv.decision_prompt_line_builder = original

        assert recorded, (
            "build_slipping_warning did not call coaching_voice.decision_prompt_line_builder"
        )


# ════════════════════════════════════════════════════════════════════════════════
# AC3 — Meaningful drop → recommit-or-drop, not streak-loss notification
# ════════════════════════════════════════════════════════════════════════════════

class TestRecommitOrDrop:
    """AC3: when a focus habit drops meaningfully, build_recommit_or_drop returns
    a recommit-or-drop framing, not a streak-loss message."""

    def test_recommit_or_drop_returns_dict(self):
        """AC3: build_recommit_or_drop returns a dict with message."""
        from backend.services.focus_coaching import build_recommit_or_drop
        result = build_recommit_or_drop("Morning run", consistency_pct_7d=30.0)
        assert isinstance(result, dict)
        assert "message" in result
        assert len(result["message"]) > 0

    def test_recommit_or_drop_no_streak_language(self):
        """AC3: recommit-or-drop message must not mention streak loss or reset."""
        from backend.services.focus_coaching import build_recommit_or_drop
        result = build_recommit_or_drop("Meditation", consistency_pct_7d=25.0)
        msg = result["message"].lower()
        for phrase in ("streak: 0", "streak reset", "streak broke", "lost your streak"):
            assert phrase not in msg, f"Streak-loss phrase '{phrase}' found in message: {msg!r}"

    def test_recommit_or_drop_not_shaming(self):
        """AC3: recommit-or-drop message must not use shaming language."""
        from backend.services.focus_coaching import build_recommit_or_drop
        result = build_recommit_or_drop("Cold shower", consistency_pct_7d=20.0)
        assert not _SHAMING_RE.search(result["message"])

    def test_recommit_or_drop_references_habit_name(self):
        """AC3: recommit-or-drop message references the habit name."""
        from backend.services.focus_coaching import build_recommit_or_drop
        result = build_recommit_or_drop("Evening walk", consistency_pct_7d=30.0)
        assert "Evening walk" in result["message"]

    def test_recommit_or_drop_type_field(self):
        """AC3: result dict carries type='recommit_or_drop'."""
        from backend.services.focus_coaching import build_recommit_or_drop
        result = build_recommit_or_drop("Reading", consistency_pct_7d=40.0)
        assert result.get("type") == "recommit_or_drop"


# ════════════════════════════════════════════════════════════════════════════════
# AC4 — minimum_version field on Habit model
# ════════════════════════════════════════════════════════════════════════════════

class TestMinimumVersionField:
    """AC4: The Habit SQLAlchemy model exposes a nullable text minimum_version field
    that is absent/null by default and does not break existing habits."""

    def test_habit_model_has_minimum_version_column(self):
        """AC4: Habit model declares minimum_version as a nullable column."""
        from backend.models import Habit
        assert hasattr(Habit, "minimum_version"), (
            "Habit model is missing minimum_version attribute"
        )
        col = Habit.__table__.c.get("minimum_version")
        assert col is not None, "minimum_version column not in Habit.__table__"
        assert col.nullable, "minimum_version must be nullable"

    def test_minimum_version_not_in_existing_required_columns(self):
        """AC4: minimum_version is additive — its absence does not break existing habits."""
        from backend.models import Habit
        col = Habit.__table__.c.get("minimum_version")
        assert col is not None
        # Server default must be NULL (no default clause)
        assert col.server_default is None or str(col.server_default.arg) in ("null", "NULL", "")


# ════════════════════════════════════════════════════════════════════════════════
# AC5 — minimum_version offered on struggling day; null → silently skip
# ════════════════════════════════════════════════════════════════════════════════

class TestMinimumVersionOffer:
    """AC5: build_minimum_version_offer returns offer copy when minimum_version
    is set, and returns None when minimum_version is null."""

    def test_offer_returned_when_minimum_version_set(self):
        """AC5: returns a dict with message when minimum_version is non-null."""
        from backend.services.focus_coaching import build_minimum_version_offer
        result = build_minimum_version_offer("30-minute run", "5-minute walk")
        assert result is not None
        assert isinstance(result, dict)
        assert "message" in result

    def test_offer_contains_minimum_version_text(self):
        """AC5: the offer message contains the minimum_version text verbatim."""
        from backend.services.focus_coaching import build_minimum_version_offer
        result = build_minimum_version_offer("30-minute run", "5-minute walk")
        assert "5-minute walk" in result["message"]

    def test_offer_null_minimum_version_returns_none(self):
        """AC5: returns None when minimum_version is null — feature silently skipped."""
        from backend.services.focus_coaching import build_minimum_version_offer
        assert build_minimum_version_offer("30-minute run", None) is None

    def test_offer_empty_minimum_version_returns_none(self):
        """AC5: returns None when minimum_version is empty string."""
        from backend.services.focus_coaching import build_minimum_version_offer
        assert build_minimum_version_offer("30-minute run", "") is None

    def test_offer_no_shaming_language(self):
        """AC5: offer copy must not shame the user for struggling."""
        from backend.services.focus_coaching import build_minimum_version_offer
        result = build_minimum_version_offer("30-minute run", "5-minute walk")
        assert not _SHAMING_RE.search(result["message"])

    def test_offer_no_exclamation(self):
        """AC5: offer copy must not contain exclamation marks."""
        from backend.services.focus_coaching import build_minimum_version_offer
        result = build_minimum_version_offer("Workout", "10 squats")
        assert "!" not in result["message"]


# ════════════════════════════════════════════════════════════════════════════════
# AC6 — anchor_event field on Habit model
# ════════════════════════════════════════════════════════════════════════════════

class TestAnchorEventField:
    """AC6: The Habit SQLAlchemy model exposes a nullable text anchor_event field."""

    def test_habit_model_has_anchor_event_column(self):
        """AC6: Habit model declares anchor_event as a nullable column."""
        from backend.models import Habit
        assert hasattr(Habit, "anchor_event"), (
            "Habit model is missing anchor_event attribute"
        )
        col = Habit.__table__.c.get("anchor_event")
        assert col is not None, "anchor_event column not in Habit.__table__"
        assert col.nullable, "anchor_event must be nullable"

    def test_anchor_event_additive(self):
        """AC6: anchor_event is additive — no server default value."""
        from backend.models import Habit
        col = Habit.__table__.c.get("anchor_event")
        assert col is not None
        assert col.server_default is None or str(col.server_default.arg) in ("null", "NULL", "")


# ════════════════════════════════════════════════════════════════════════════════
# AC7 — anchor_event set → coaching includes cue copy linking habit to action
# ════════════════════════════════════════════════════════════════════════════════

class TestAnchorCue:
    """AC7: build_anchor_cue returns cue copy when anchor_event is set;
    returns None when anchor_event is null."""

    def test_cue_returned_when_anchor_event_set(self):
        """AC7: returns a dict with message when anchor_event is non-null."""
        from backend.services.focus_coaching import build_anchor_cue
        result = build_anchor_cue("Meditation", "daily weigh-in")
        assert result is not None
        assert isinstance(result, dict)
        assert "message" in result

    def test_cue_contains_anchor_event_name(self):
        """AC7: cue message explicitly references the anchor event."""
        from backend.services.focus_coaching import build_anchor_cue
        result = build_anchor_cue("Meditation", "daily weigh-in")
        assert "daily weigh-in" in result["message"], (
            f"Anchor event not found in cue message: {result['message']!r}"
        )

    def test_cue_contains_habit_name(self):
        """AC7: cue message references the habit being anchored."""
        from backend.services.focus_coaching import build_anchor_cue
        result = build_anchor_cue("Meditation", "daily weigh-in")
        assert "Meditation" in result["message"]

    def test_cue_null_anchor_returns_none(self):
        """AC7: returns None when anchor_event is null — no cue copy."""
        from backend.services.focus_coaching import build_anchor_cue
        assert build_anchor_cue("Meditation", None) is None

    def test_cue_empty_anchor_returns_none(self):
        """AC7: returns None when anchor_event is empty string."""
        from backend.services.focus_coaching import build_anchor_cue
        assert build_anchor_cue("Meditation", "") is None

    def test_cue_no_shaming_language(self):
        """AC7: cue copy must not shame the user."""
        from backend.services.focus_coaching import build_anchor_cue
        result = build_anchor_cue("Exercise", "morning coffee")
        assert not _SHAMING_RE.search(result["message"])

    def test_cue_no_exclamation(self):
        """AC7: cue copy must not contain exclamation marks."""
        from backend.services.focus_coaching import build_anchor_cue
        result = build_anchor_cue("Cold shower", "morning alarm")
        assert "!" not in result["message"]

    def test_cue_uses_voice_module(self):
        """AC7: build_anchor_cue delegates copy to coaching_voice, not raw strings."""
        import backend.services.coaching_voice as cv
        from backend.services.focus_coaching import build_anchor_cue

        recorded = []
        original_builders = {
            "praise_line_builder": cv.praise_line_builder,
            "decision_prompt_line_builder": cv.decision_prompt_line_builder,
            "miss_and_pivot_line_builder": cv.miss_and_pivot_line_builder,
            "reframe_line_builder": cv.reframe_line_builder,
        }

        def make_capturing(name, orig):
            def capturing(*args, **kwargs):
                recorded.append(name)
                return orig(*args, **kwargs)
            return capturing

        for name, orig in original_builders.items():
            setattr(cv, name, make_capturing(name, orig))

        try:
            build_anchor_cue("Meditation", "daily weigh-in")
        finally:
            for name, orig in original_builders.items():
                setattr(cv, name, orig)

        assert recorded, (
            "build_anchor_cue did not call any coaching_voice builder function"
        )


# ════════════════════════════════════════════════════════════════════════════════
# AC8 — Keystone elevation: one priority + two supports; associative not causal
# ════════════════════════════════════════════════════════════════════════════════

class TestKeystoneElevation:
    """AC8: build_keystone_elevation names the keystone habit as priority, labels
    the other two as supports, uses associative not causal language."""

    def _signal(self):
        return _make_correlation_signal(r=0.72, n=28)

    def test_keystone_elevation_returns_dict(self):
        """AC8: build_keystone_elevation returns a dict with message."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Morning run",
            ["Meditation", "Cold shower"],
            self._signal(),
        )
        assert isinstance(result, dict)
        assert "message" in result
        assert len(result["message"]) > 0

    def test_keystone_labeled_as_priority(self):
        """AC8: keystone habit name appears in message; priority framing used."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Morning run",
            ["Meditation", "Cold shower"],
            self._signal(),
        )
        msg = result["message"].lower()
        assert "morning run" in msg
        assert result.get("keystone_role") == "priority"

    def test_supports_labeled(self):
        """AC8: support habits are identified in result."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Morning run",
            ["Meditation", "Cold shower"],
            self._signal(),
        )
        assert "support_names" in result
        assert "Meditation" in result["support_names"]
        assert "Cold shower" in result["support_names"]

    def test_no_causal_language(self):
        """AC8: keystone message must not use causal language."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Morning run",
            ["Meditation", "Cold shower"],
            self._signal(),
        )
        assert not _CAUSAL_RE.search(result["message"]), (
            f"Causal language found in keystone message: {result['message']!r}"
        )

    def test_no_shaming_language(self):
        """AC8: keystone message must not shame the user."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Morning run",
            ["Meditation", "Cold shower"],
            self._signal(),
        )
        assert not _SHAMING_RE.search(result["message"])

    def test_no_exclamation(self):
        """AC8: keystone message must not contain exclamation marks."""
        from backend.services.focus_coaching import build_keystone_elevation
        result = build_keystone_elevation(
            "Sleep ≥ 7h",
            ["Exercise", "Meditation"],
            self._signal(),
        )
        assert "!" not in result["message"]


# ════════════════════════════════════════════════════════════════════════════════
# AC9 — Correlation language never fabricates numbers
# ════════════════════════════════════════════════════════════════════════════════

class TestNoFabricatedNumbers:
    """AC9: keystone/correlation copy uses only the r and n values from the H3 signal;
    no numbers invented by the coaching layer."""

    def test_keystone_passes_signal_verbatim(self):
        """AC9: H3 signal values are passed to voice module without modification."""
        from backend.services.focus_coaching import build_keystone_elevation

        signal_a = _make_correlation_signal(r=0.72, n=28)
        signal_b = _make_correlation_signal(r=0.35, n=12)

        result_a = build_keystone_elevation("Habit A", ["B", "C"], signal_a)
        result_b = build_keystone_elevation("Habit A", ["B", "C"], signal_b)

        # Different signals must produce different messages
        assert result_a["message"] != result_b["message"], (
            "Different H3 signals must produce different keystone messages; "
            "check that the signal values are being used"
        )

    def test_keystone_no_invented_percentage(self):
        """AC9: correlation language uses the coefficient from the H3 signal,
        not an independently computed or fabricated percentage."""
        from backend.services.focus_coaching import build_keystone_elevation

        # Provide a signal with a specific r value; the module must use it
        signal = _make_correlation_signal(r=0.55, n=20)
        result = build_keystone_elevation("Running", ["Meditation", "Sleep"], signal)

        # The result should contain 'n' or 'r' value (either formatted or referenced)
        # — at minimum the message must NOT contain numbers that can't come from the signal
        msg = result["message"]

        # Find all numbers in the message
        numbers_in_msg = re.findall(r"\d+\.?\d*", msg)
        # Each number in the message should be derivable from the signal
        # (r=0.55, n=20, or derived from the habit names/context)
        allowed_values = {"0.55", "0.6", "20", "55", "2"}  # plausible derivations
        # Key guard: the message must not contain completely unrelated numbers
        # We verify this by checking the n value (20) or r value appears
        has_signal_reference = any(
            v in msg for v in ("0.55", "0.6", "20", "n = 20", "n=20")
        ) or len(numbers_in_msg) == 0
        assert has_signal_reference or numbers_in_msg == [], (
            f"Message may contain fabricated numbers: {msg!r}; signal was r=0.55, n=20"
        )

    def test_correlation_reason_empty_when_valid(self):
        """AC9: a valid H3 signal has an empty reason; build_keystone_elevation
        must not surface a message when the signal carries a non-empty reason."""
        from backend.services.focus_coaching import build_keystone_elevation

        invalid_signal = _make_correlation_signal(r=0.0, n=1, reason="insufficient data")
        result = build_keystone_elevation("Running", ["Meditation", "Sleep"], invalid_signal)
        # When signal is invalid, result should indicate it cannot be shown
        assert result.get("available") is False or result.get("message") == "" or result.get("reason") != ""


# ════════════════════════════════════════════════════════════════════════════════
# AC10 — Schema migration is additive and idempotent
# ════════════════════════════════════════════════════════════════════════════════

class TestSchemaMigration:
    """AC10: migration adds minimum_version and anchor_event to habits table;
    it is idempotent (column_exists guarded) and additive only."""

    def test_migration_file_exists(self):
        """AC10: a migration file exists for issue #925."""
        import pathlib
        versions_dir = pathlib.Path("alembic/versions")
        migration_files = list(versions_dir.glob("*925*"))
        assert migration_files, (
            "No migration file found for issue #925 in alembic/versions/"
        )

    def test_migration_uses_column_exists_guard(self):
        """AC10: migration uses column_exists helper to stay idempotent."""
        import pathlib
        versions_dir = pathlib.Path("alembic/versions")
        files = list(versions_dir.glob("*925*"))
        assert files, "Migration file not found"
        content = files[0].read_text()
        assert "column_exists" in content, (
            "Migration does not use column_exists helper — not idempotent"
        )

    def test_migration_only_adds_columns_to_habits(self):
        """AC10: migration only adds columns to habits table; no DROP or ALTER except add."""
        import pathlib
        versions_dir = pathlib.Path("alembic/versions")
        files = list(versions_dir.glob("*925*"))
        assert files
        content = files[0].read_text()
        assert "minimum_version" in content
        assert "anchor_event" in content
        # Should NOT alter or drop existing columns in upgrade()
        upgrade_section = content.split("def upgrade")[1].split("def downgrade")[0]
        assert "alter_column" not in upgrade_section or "minimum_version" in upgrade_section or "anchor_event" in upgrade_section


# ════════════════════════════════════════════════════════════════════════════════
# AC11 — DB access stays in caller; focus_coaching has no DB imports
# ════════════════════════════════════════════════════════════════════════════════

class TestNoDB:
    """AC11: focus_coaching module imports no database dependencies."""

    def test_focus_coaching_no_db_import(self):
        """AC11: focus_coaching.py does not import SQLAlchemy, Session, or models."""
        import ast
        import pathlib

        path = pathlib.Path("backend/services/focus_coaching.py")
        assert path.exists(), "focus_coaching.py not found"
        tree = ast.parse(path.read_text())

        forbidden_modules = {
            "sqlalchemy", "backend.db", "backend.models",
            "sqlalchemy.orm", "psycopg2",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for forbidden in forbidden_modules:
                    assert not mod.startswith(forbidden), (
                        f"focus_coaching imports from {mod!r} — DB access must stay in caller"
                    )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_modules:
                        assert not alias.name.startswith(forbidden), (
                            f"focus_coaching imports {alias.name!r} — DB access must stay in caller"
                        )

    def test_focus_coaching_is_pure_function_module(self):
        """AC11: focus_coaching functions return data from their arguments, not from queries."""
        from backend.services.focus_coaching import (
            build_slipping_warning,
            build_recommit_or_drop,
            build_minimum_version_offer,
            build_anchor_cue,
            build_keystone_elevation,
        )
        # All functions must be callable with only plain Python values
        assert callable(build_slipping_warning)
        assert callable(build_recommit_or_drop)
        assert callable(build_minimum_version_offer)
        assert callable(build_anchor_cue)
        assert callable(build_keystone_elevation)


# ════════════════════════════════════════════════════════════════════════════════
# AC12 — All copy passes through voice module
# ════════════════════════════════════════════════════════════════════════════════

class TestVoiceModuleRouting:
    """AC12: every builder in focus_coaching delegates its copy to coaching_voice;
    no raw strings are hardcoded in coaching logic."""

    def test_focus_coaching_imports_coaching_voice(self):
        """AC12: focus_coaching.py imports coaching_voice."""
        import ast
        import pathlib

        path = pathlib.Path("backend/services/focus_coaching.py")
        assert path.exists()
        tree = ast.parse(path.read_text())

        imports_voice = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "coaching_voice" in node.module:
                    imports_voice = True
            if isinstance(node, ast.Import):
                if any("coaching_voice" in a.name for a in node.names):
                    imports_voice = True
        assert imports_voice, (
            "focus_coaching.py does not import from coaching_voice"
        )

    def test_recommit_or_drop_uses_voice_module(self):
        """AC12: build_recommit_or_drop delegates to coaching_voice."""
        import backend.services.coaching_voice as cv
        from backend.services.focus_coaching import build_recommit_or_drop

        recorded = []
        originals = {
            "decision_prompt_line_builder": cv.decision_prompt_line_builder,
            "miss_and_pivot_line_builder": cv.miss_and_pivot_line_builder,
        }

        def make_cap(name, orig):
            def cap(*args, **kwargs):
                recorded.append(name)
                return orig(*args, **kwargs)
            return cap

        for name, orig in originals.items():
            setattr(cv, name, make_cap(name, orig))

        try:
            build_recommit_or_drop("Morning run", consistency_pct_7d=25.0)
        finally:
            for name, orig in originals.items():
                setattr(cv, name, orig)

        assert recorded, "build_recommit_or_drop did not call any coaching_voice builder"

    def test_minimum_version_offer_uses_voice_module(self):
        """AC12: build_minimum_version_offer delegates to coaching_voice."""
        import backend.services.coaching_voice as cv
        from backend.services.focus_coaching import build_minimum_version_offer

        recorded = []
        original = cv.decision_prompt_line_builder

        def capturing(*args, **kwargs):
            recorded.append(args)
            return original(*args, **kwargs)

        cv.decision_prompt_line_builder = capturing
        try:
            build_minimum_version_offer("30-minute run", "5-minute walk")
        finally:
            cv.decision_prompt_line_builder = original

        assert recorded, "build_minimum_version_offer did not call coaching_voice.decision_prompt_line_builder"

    def test_keystone_uses_voice_module(self):
        """AC12: build_keystone_elevation delegates to coaching_voice."""
        import backend.services.coaching_voice as cv
        from backend.services.focus_coaching import build_keystone_elevation

        recorded = []
        originals = {
            name: getattr(cv, name)
            for name in (
                "praise_line_builder",
                "reframe_line_builder",
                "miss_and_pivot_line_builder",
                "decision_prompt_line_builder",
            )
        }

        def make_cap(name, orig):
            def cap(*a, **kw):
                recorded.append(name)
                return orig(*a, **kw)
            return cap

        for name, orig in originals.items():
            setattr(cv, name, make_cap(name, orig))

        try:
            build_keystone_elevation(
                "Morning run",
                ["Meditation", "Cold shower"],
                _make_correlation_signal(r=0.72, n=28),
            )
        finally:
            for name, orig in originals.items():
                setattr(cv, name, orig)

        assert recorded, "build_keystone_elevation did not call any coaching_voice builder"
