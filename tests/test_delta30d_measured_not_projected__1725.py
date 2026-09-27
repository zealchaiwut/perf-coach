"""Tests for issue #1725: confirm delta_30d_kg semantic.

Context: a code-review of #1713 flagged that stats["delta_30d_kg"] returns
weekly_rate_ewma_kg × 4 (not the raw 30-day measured delta) when the rate is
readable. The reviewer asked: is this intentional? Answer: YES — #1698
intentionally changed 'This mo' pill to use OLS rate × 4 so both sibling pills
('This wk' and 'This mo') derive from the same canonical OLS-on-EWMA rate.
#1713 did not touch delta_30d_kg; the reviewer was looking at #1698's work.

Acceptance Criteria:
  AC1: When rate is readable, stats["delta_30d_kg"] == round(weekly_rate_kg * 4, 2)
       — confirming the rate-pill-consistency intent from #1698 is in effect.
  AC2: When rate is unreadable, stats["delta_30d_kg"] falls back to the raw
       two-point 30-day measured delta (unchanged fallback).
  AC3: The delta_30d_kg expression in the get_weight_chart stats dict literal
       uses weekly_rate_ewma_kg * 4 (AST check — documents the intentional form).
  AC4: A code comment near delta_30d_kg documents the #1698 rate-pill-consistency
       rationale so future reviewers do not repeat the confusion.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_MAIN_PY = pathlib.Path(__file__).parent.parent / "backend" / "main.py"


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_weight_chart_body() -> list[ast.stmt]:
    tree = ast.parse(_MAIN_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_weight_chart":
            return node.body
    raise AssertionError("get_weight_chart not found in backend/main.py")


def _find_delta_30d_value_in_stats_dict(stmts: list[ast.stmt]) -> ast.expr | None:
    """Return the AST value expression for 'delta_30d_kg' in the stats dict."""
    for stmt in stmts:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "delta_30d_kg":
                    return value
    return None


def _contains_weekly_rate_times_4(expr: ast.expr) -> bool:
    """Return True if expression contains `weekly_rate_ewma_kg * 4`."""
    for node in ast.walk(expr):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            lname = isinstance(node.left, ast.Name) and node.left.id == "weekly_rate_ewma_kg"
            r4 = isinstance(node.right, ast.Constant) and node.right.value == 4
            rname = isinstance(node.right, ast.Name) and node.right.id == "weekly_rate_ewma_kg"
            l4 = isinstance(node.left, ast.Constant) and node.left.value == 4
            if (lname and r4) or (rname and l4):
                return True
    return False


# ── AC3: AST check ────────────────────────────────────────────────────────────

def test_ac3_delta_30d_stats_dict_uses_rate_times_4():
    """AC3: delta_30d_kg in the stats dict literal must use weekly_rate_ewma_kg * 4
    (confirming the intentional rate-pill-consistency form from #1698)."""
    stmts = _get_weight_chart_body()
    value_expr = _find_delta_30d_value_in_stats_dict(stmts)
    assert value_expr is not None, "Could not find 'delta_30d_kg' key in stats dict"
    assert _contains_weekly_rate_times_4(value_expr), (
        "delta_30d_kg in get_weight_chart does NOT use `weekly_rate_ewma_kg * 4`. "
        "The rate-pill-consistency behavior from #1698 appears to have been reverted. "
        "Both 'This wk' (delta_7d_kg) and 'This mo' (delta_30d_kg) must use the same "
        "OLS-on-EWMA rate when readable."
    )


# ── AC4: documentation comment check ─────────────────────────────────────────

def _get_delta_30d_context_lines() -> list[str]:
    """Return lines immediately around the delta_30d_kg assignment."""
    text = _MAIN_PY.read_text()
    lines = text.splitlines()
    ctx = []
    for i, line in enumerate(lines):
        if "delta_30d_kg" in line:
            start = max(0, i - 3)
            end = min(len(lines), i + 4)
            ctx.extend(lines[start:end])
    return ctx


def test_ac4_delta_30d_code_documents_rate_pill_rationale():
    """AC4: There must be a comment near delta_30d_kg explaining the #1698
    rate-pill-consistency reason so future reviewers understand the intent."""
    ctx_lines = _get_delta_30d_context_lines()
    comment_lines = [l for l in ctx_lines if "#" in l]
    comment_text = " ".join(comment_lines).lower()

    has_rationale = any(
        term in comment_text
        for term in ("1698", "rate-pill", "rate pill", "ols", "this mo", "this wk",
                     "consistency", "same rate", "sibling")
    )
    assert has_rationale, (
        "No documentation comment found near delta_30d_kg explaining the "
        "rate-pill-consistency rationale from #1698. Add a comment so future "
        "reviewers know this is intentional."
    )


# ── AC1 + AC2: runtime behavioral checks ─────────────────────────────────────

import datetime
import unittest.mock as mock
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import Session as OrmSession

from backend.main import app, resolve_user
from backend.models import Base, User, WeightEntry, WeightTarget

_TODAY = datetime.date.today()
_TABLES = [User.__table__, WeightEntry.__table__, WeightTarget.__table__]


def _mem_engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e, tables=_TABLES)
    return e


class _Stub:
    def __init__(self, uid):
        self.id = uid
        self.name = "user1725"
        self.is_admin = False
        self.is_active = True


def _add_user(session):
    uid = uuid.uuid4()
    session.add(User(
        id=uid,
        name="user1725_" + uuid.uuid4().hex[:6],
        is_admin=False,
        is_active=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    session.commit()
    return _Stub(uid)


def _seed_entries(session, user_id, *, n=35, start_kg=80.0, rate=-0.04):
    now = datetime.datetime.now(datetime.timezone.utc)
    for i in range(n):
        d = _TODAY - datetime.timedelta(days=n - 1 - i)
        session.add(WeightEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            entry_date=d,
            weight_kg=round(start_kg + rate * i, 2),
            source="manual",
            created_at=now,
            updated_at=now,
        ))
    session.commit()


def _mock_rate_dict(*, readable, rate_kg_wk=None):
    return {
        "readable": readable,
        "rate_kg_wk": rate_kg_wk,
        "trend_kg": 79.5,
        "ci_kg_wk": 0.05 if readable else None,
        "state": "losing" if readable else "unknown",
        "gated": False,
        "gate_reason": None,
        "days_needed": 0,
        "coverage_pct": 95.0 if readable else 25.0,
        "needed_rate_kg_wk": None,
    }


def _chart_stats(engine, user, *, readable, rate_kg_wk):
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        rate_dict = _mock_rate_dict(readable=readable, rate_kg_wk=rate_kg_wk)
        with (
            mock.patch("backend.main.engine", engine),
            mock.patch("backend.db.engine", engine),
            mock.patch("backend.main._weight_stats", return_value=rate_dict),
            mock.patch("backend.main._today_bkk", return_value=_TODAY),
        ):
            tc = TestClient(app, raise_server_exceptions=True)
            resp = tc.get("/api/weight-chart", params={"range": "30D", "include_target": "false"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        return resp.json()["stats"]
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_ac1_delta_30d_kg_is_rate_times_4_when_readable():
    """AC1: delta_30d_kg == round(rate_kg_wk * 4, 2) when rate is readable.
    Confirms the intentional #1698 rate-pill-consistency behavior."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        _seed_entries(s, user.id)

    ols_weekly = -0.5
    stats = _chart_stats(e, user, readable=True, rate_kg_wk=ols_weekly)

    expected = round(ols_weekly * 4, 2)
    actual = stats["delta_30d_kg"]
    assert actual == expected, (
        f"AC1 FAIL: delta_30d_kg should be {expected} (weekly_rate × 4) when "
        f"rate is readable, got {actual!r}. Both 'This wk' and 'This mo' pills "
        f"must use the same OLS-on-EWMA rate (#1698 rate-pill-consistency)."
    )


def test_ac2_delta_30d_kg_falls_back_to_measured_when_unreadable():
    """AC2: delta_30d_kg falls back to the raw two-point measured delta when
    the rate is unreadable."""
    e = _mem_engine()
    with OrmSession(e) as s:
        user = _add_user(s)
        _seed_entries(s, user.id, n=35, start_kg=80.0, rate=-0.04)

    stats = _chart_stats(e, user, readable=False, rate_kg_wk=None)

    assert stats["delta_30d_kg"] is not None, (
        "AC2 FAIL: delta_30d_kg must be the raw measured delta (not None) "
        "when rate is unreadable."
    )
    assert abs(stats["delta_30d_kg"]) < 3.0, (
        f"AC2 FAIL: fallback delta_30d_kg={stats['delta_30d_kg']!r} looks "
        f"too large — expected a ~1 kg raw two-point delta."
    )
