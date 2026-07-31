"""No naive `date.today()` in backend code — issue #1600, the S1 ratchet.

This is the lint rule S1 asked for. The repo has no ruff/flake8 config, and
enforcing it as a test means it runs in the same CI gate as everything else
rather than needing a second tool.

## Why a naive call is a bug here and not a style nit

perf-coach is a single-timezone app: one athlete, in Bangkok (UTC+7). Both
services run in UTC containers. So for the seven hours between 17:00 and
midnight Bangkok time, `date.today()` returns YESTERDAY — silently. No error,
no warning; readiness, fuel targets and the daily coach message just answer for
the wrong day, every single evening.

PR #1612 set `TZ=Asia/Bangkok` on both services, which fixes the behaviour. But
that made correctness a property of the DEPLOYMENT rather than the code: unset
the variable, run a script by hand, add a third service, or run a test on a
laptop in another zone, and all of it comes back. An environment variable is
not a place to keep a business rule.

`today_bangkok()` is right regardless of how the process was launched, so it is
the only way the backend should ask what day it is.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"

# One file is exempt, with a reason.
#
# alembic/ is not scanned at all: migrations are historical records that ran
# once against a real database. Rewriting one changes what a past migration
# claims to have done.
_EXEMPT: dict[str, str] = {}


def _backend_files() -> list[Path]:
    return sorted(
        p for p in BACKEND.rglob("*.py")
        if "__pycache__" not in p.parts and p.name not in _EXEMPT
    )


def _naive_today_calls(path: Path) -> list[int]:
    """Line numbers of `<something>.today()` calls, excluding the safe helper.

    Parsed rather than grepped: a grep for `.today()` matches inside strings,
    docstrings and comments — this file's own docstring would trip it.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "today":
            # date.today() / datetime.today() / _date.today() — all naive.
            hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("path", _backend_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_naive_today_call(path: Path):
    hits = _naive_today_calls(path)
    assert not hits, (
        f"{path.relative_to(REPO)} calls .today() at line(s) {hits}. "
        "Use today_bangkok() (backend/utils/time.py) — a naive today() returns "
        "yesterday for the last 7 hours of every Bangkok day unless TZ happens "
        "to be set."
    )


def test_no_naive_utcnow_or_now():
    """`datetime.now()` with no tzinfo has the same defect for anything that
    later takes `.date()`, and `utcnow()` returns a naive datetime that compares
    wrongly against aware ones."""
    offenders = []
    for path in _backend_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            # `func.now()` is SQLAlchemy emitting SQL NOW() — evaluated by
            # Postgres, never by this process, so the container's zone is
            # irrelevant to it.
            if isinstance(fn.value, ast.Name) and fn.value.id == "func":
                continue
            if fn.attr == "utcnow":
                offenders.append(f"{path.relative_to(REPO)}:{node.lineno} utcnow()")
            elif fn.attr == "now" and not node.args and not node.keywords:
                offenders.append(f"{path.relative_to(REPO)}:{node.lineno} now()")
    assert not offenders, (
        "naive now()/utcnow(): " + ", ".join(offenders) +
        " — pass a tzinfo, or use now_bangkok()/today_bangkok()."
    )


# ── The helper itself ─────────────────────────────────────────────────────────

def test_the_helper_is_the_one_that_may_call_today():
    """today_bangkok is allowed to reach the clock — that is its whole job — but
    it must do so through an explicit zone, never a bare today()."""
    src = (BACKEND / "utils" / "time.py").read_text()
    assert "Asia/Bangkok" in src
    assert "date.today()" not in src


def test_main_alias_delegates_rather_than_reimplementing():
    """main.py keeps a short `_today_bkk` alias because it appears ~50 times,
    but it used to be a third private copy of the zone lookup — alongside
    utils.time and the worker's. Three copies of a timezone rule is how two of
    them end up wrong."""
    import inspect

    from backend import main

    src = inspect.getsource(main._today_bkk)
    assert "_today_bangkok()" in src
    assert "ZoneInfo" not in src, "the alias reimplemented the zone lookup again"


def test_seed_uses_the_helper_through_its_own_import_path():
    """seed.py is run as `python backend/seed.py`, which puts backend/ on
    sys.path — so it imports `utils.time`, not `backend.utils.time`. Using the
    wrong prefix here breaks the script without breaking any test that imports
    it, because nothing imports it."""
    src = (BACKEND / "seed.py").read_text()
    assert "from utils.time import today_bangkok" in src
    assert "from backend.utils.time" not in src


# ── Scope note ────────────────────────────────────────────────────────────────

def test_frontend_is_not_covered_by_this_rule():
    """Documented boundary, not an oversight.

    The frontend calls `new Date()`, which is browser-local — correct for an
    athlete in Bangkok and wrong on a laptop elsewhere. Fixing it means deciding
    whether the app should follow the device or pin to Bangkok, which is a
    product question. Tracked as #1603.
    """
    js = (REPO / "frontend" / "js")
    assert js.is_dir()
