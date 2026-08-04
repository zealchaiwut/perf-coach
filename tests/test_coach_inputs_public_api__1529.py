"""Tests for issue #1529: promote private weekly_coach_message helpers to public API.

AC coverage:
- AC1: weekly_coach_message exposes load_inputs_for_user (public, no underscore)
- AC2: weekly_coach_message exposes build_projection_info (public, no underscore)
- AC3: weekly_coach_message exposes format_hms (public, no underscore)
- AC4: coach_facts does NOT import underscore-private names from weekly_coach_message
- AC5: backward-compat underscore aliases still work (do not break test_race_goal_resolution__1541)
- AC6: format_hms public function is callable and returns correct H:MM strings
"""
from __future__ import annotations

import ast
import inspect
import pathlib


# ── AC1: load_inputs_for_user is public ───────────────────────────────────────

def test_load_inputs_for_user_is_public():
    """AC1: weekly_coach_message.load_inputs_for_user is importable as a public name."""
    from backend.services import weekly_coach_message
    assert hasattr(weekly_coach_message, "load_inputs_for_user"), (
        "weekly_coach_message must expose public `load_inputs_for_user` "
        "(no underscore) so cross-module callers don't rely on private API"
    )
    fn = weekly_coach_message.load_inputs_for_user
    assert callable(fn)


# ── AC2: build_projection_info is public ──────────────────────────────────────

def test_build_projection_info_is_public():
    """AC2: weekly_coach_message.build_projection_info is importable as a public name."""
    from backend.services import weekly_coach_message
    assert hasattr(weekly_coach_message, "build_projection_info"), (
        "weekly_coach_message must expose public `build_projection_info` "
        "(no underscore) so callers use the stable API"
    )
    fn = weekly_coach_message.build_projection_info
    assert callable(fn)


# ── AC3: format_hms is public ─────────────────────────────────────────────────

def test_format_hms_is_public():
    """AC3: weekly_coach_message.format_hms is importable as a public name."""
    from backend.services import weekly_coach_message
    assert hasattr(weekly_coach_message, "format_hms"), (
        "weekly_coach_message must expose public `format_hms` "
        "(no underscore) so coach_facts can import from stable API"
    )
    fn = weekly_coach_message.format_hms
    assert callable(fn)


# ── AC4: coach_facts imports only public names from weekly_coach_message ──────

def test_coach_facts_imports_no_private_names_from_weekly_coach_message():
    """AC4: coach_facts.py must not import underscore-private names from weekly_coach_message."""
    src_path = pathlib.Path(__file__).parent.parent / "backend" / "services" / "coach_facts.py"
    source = src_path.read_text()
    tree = ast.parse(source)

    private_imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "weekly_coach_message" in module:
                    for alias in node.names:
                        name = alias.name
                        if name.startswith("_"):
                            private_imports.append(name)

    # Also check inline imports inside function bodies (dynamic import pattern)
    # by scanning raw source for the pattern
    import re
    inline_pattern = re.compile(
        r'from\s+backend\.services\.weekly_coach_message\s+import\s+([^)]+)',
        re.MULTILINE | re.DOTALL,
    )
    for match in inline_pattern.finditer(source):
        names_str = match.group(1)
        for raw_name in re.split(r'[,\s\n]+', names_str):
            raw_name = raw_name.strip().strip("()")
            if raw_name.startswith("_") and raw_name:
                private_imports.append(raw_name)

    assert not private_imports, (
        f"coach_facts.py imports private names from weekly_coach_message: "
        f"{private_imports!r}. Use public API instead (no underscore prefix)."
    )


# ── AC5: backward-compat underscore aliases still exist ───────────────────────

def test_underscore_aliases_still_exist():
    """AC5: old underscore names remain as aliases so existing tests are not broken."""
    from backend.services import weekly_coach_message

    assert hasattr(weekly_coach_message, "_load_inputs_for_user"), (
        "_load_inputs_for_user alias must exist for backward compatibility"
    )
    assert hasattr(weekly_coach_message, "_format_hms"), (
        "_format_hms alias must exist for backward compatibility"
    )
    # _build_projection_info was never externally imported; alias is nice-to-have
    # but required only for the two that were actually cross-imported.


# ── AC6: format_hms correctness ──────────────────────────────────────────────

def test_format_hms_returns_correct_format():
    """AC6: public format_hms produces the same output as the old private helper."""
    from backend.services.weekly_coach_message import format_hms

    assert format_hms(0) == "0:00"
    assert format_hms(3600) == "1:00"
    assert format_hms(3661) == "1:01:01"
    assert format_hms(5400) == "1:30"
    # negative values clamp to 0
    assert format_hms(-1) == "0:00"
