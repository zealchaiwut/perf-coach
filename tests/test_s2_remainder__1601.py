"""S2 remainder — issue #1601's mechanical items.

Four fixes that needed no design decision. The two that DID need one are
deliberately left open and noted at the bottom of this file.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


# ── 1. The avatar endpoint requires a session ─────────────────────────────────

def test_avatar_requires_a_session():
    """It was the one avatar route with no auth — its siblings are
    /api/users/me/avatar and both require the session — so anyone who could
    guess or enumerate a UUID could read any user's photo."""
    from backend.main import app

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/users/00000000-0000-0000-0000-000000000001/avatar")
    assert r.status_code == 401


def test_avatar_is_still_readable_across_users_once_authenticated():
    """The fix is that you must be SOMEONE, not that you must be the subject —
    the nav renders other members' avatars in a multi-user instance."""
    from backend.main import get_avatar

    src = inspect.getsource(get_avatar)
    assert "resolve_user" in src
    assert "user_id != " not in src, "avatar became self-only; that was not the intent"


# ── 2. Both feel routes enforce the same future-date rule ─────────────────────

def test_worker_feel_entry_rejects_future_dates():
    """The two routes write the SAME table and had different integrity rules:
    the webapp rejected `feel_date > tomorrow`, the worker accepted anything
    parseable, so a malformed Hermes request could insert a row the webapp
    would have refused."""
    import backend.worker_app as worker

    src = inspect.getsource(worker.post_feel_entry)
    assert "feel_date > tomorrow" in src


def test_both_feel_routes_allow_tomorrow():
    """Tomorrow is permitted on both — a session logged just past a local
    midnight is legitimate. Parity means the same rule, not a stricter one."""
    import backend.worker_app as worker
    from backend import main

    worker_src = inspect.getsource(worker.post_feel_entry)
    assert "timedelta(days=1)" in worker_src
    main_src = Path(main.__file__).read_text()
    assert "tomorrow = today + _timedelta(days=1)" in main_src


# ── 3. One pace calculation, not two ──────────────────────────────────────────

def test_main_delegates_pace_to_the_shared_function():
    """weight_plan.compute_current_pace_kg_per_week was written specifically to
    mirror main.py's copy so the worker could report the same number — its
    docstring says so. main.py never called it and kept its own, so the claimed
    parity was enforced by a comment and nothing else."""
    from backend import main

    src = inspect.getsource(main._compute_weight_target_active)
    assert "compute_current_pace_kg_per_week" in src


def test_the_inline_pace_maths_is_gone():
    """Both bodies were verified equivalent before one replaced the other. If
    the inline version returns, the two can drift again silently."""
    from backend import main

    src = inspect.getsource(main._compute_weight_target_active)
    assert "kg_change / days_span * 7" not in src


def test_the_shared_function_still_documents_the_parity_it_now_actually_has():
    from backend.services import weight_plan

    doc = inspect.getdoc(weight_plan.compute_current_pace_kg_per_week) or ""
    assert "Mirrors the pace calc" in doc


# ── 4. The docs describe routes that exist ────────────────────────────────────

def test_worker_docs_do_not_document_a_phantom_endpoint():
    """docs/worker.md carried a full GET /api/scores section — description,
    example request, example response — for a route that has never existed in
    worker_app.py. Anyone scoping the Hermes surface from that file, including
    the audit that found it, got a larger API than the code has."""
    import backend.worker_app as worker

    doc = (REPO / "docs" / "worker.md").read_text()
    src = inspect.getsource(worker)
    documented = "### `GET /api/scores`" in doc
    implemented = '"/api/scores"' in src
    assert documented == implemented, (
        "docs and code disagree about whether GET /api/scores exists"
    )


def test_the_removal_is_explained_rather_than_silent():
    """When docs and code disagreed, the strike-through left a paper trail.
    With the route restored, the live section must still mention that history
    so nobody re-strikes it as 'phantom' by mistake."""
    doc = (REPO / "docs" / "worker.md").read_text()
    assert "### `GET /api/scores`" in doc
    assert "never implemented" in doc


# ── Still open, deliberately ──────────────────────────────────────────────────

def test_the_worker_token_is_still_a_service_credential():
    """Also NOT fixed here. The token proves the caller is Hermes, never WHICH
    athlete, so a holder can still read any user via `?user=`. Closing that
    needs per-user tokens — and would break Hermes a second time, on top of the
    bearer-on-GETs change already pending. Sequencing that belongs to the
    operator."""
    import backend.worker_app as worker

    src = inspect.getsource(worker._resolve_read_user)
    assert "user_param" in src
