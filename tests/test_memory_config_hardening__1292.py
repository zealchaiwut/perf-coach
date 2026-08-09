"""Tests for memory config hardening (issue #1292).

AC coverage:
  AC1 — render.yaml sets BANISTER_REFIT_ENABLED=0 on both uat and prd web services
  AC2 — backend/db.py engine uses pool_size=3, max_overflow=2 (pool_pre_ping and
         pool_recycle=3600 unchanged)
  AC3 — _sync_pool in backend/main.py uses max_workers=1
  AC4 — With BANISTER_REFIT_ENABLED=0, scipy is not in sys.modules after import
  AC5 — Worker (backend/worker_app.py) behavior unchanged — no BANISTER guard there
  AC6 — Refit scheduler thread does not start when BANISTER_REFIT_ENABLED=0
"""

from __future__ import annotations

import os
import subprocess
import sys

import yaml


# ── helpers ──────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _render_yaml() -> dict:
    with open(os.path.join(REPO_ROOT, "render.yaml")) as f:
        return yaml.safe_load(f)


def _env_value(service_envvars: list[dict], key: str) -> str | None:
    for item in service_envvars:
        if item.get("key") == key:
            return item.get("value")
    return None


# ── AC1: render.yaml sets BANISTER_REFIT_ENABLED=0 on both services ──────────


def test_render_yaml_banister_disabled_uat():
    """AC1a: perf-coach-uat web service has BANISTER_REFIT_ENABLED=0."""
    doc = _render_yaml()
    services = doc.get("services", [])
    uat = next((s for s in services if s.get("name") == "perf-coach-uat"), None)
    assert uat is not None, "perf-coach-uat service not found in render.yaml"
    env_val = _env_value(uat.get("envVars", []), "BANISTER_REFIT_ENABLED")
    assert env_val == "0", (
        f"perf-coach-uat: expected BANISTER_REFIT_ENABLED=0, got {env_val!r}"
    )


def test_render_yaml_banister_disabled_prd():
    """AC1b: perf-coach-prd web service has BANISTER_REFIT_ENABLED=0."""
    doc = _render_yaml()
    services = doc.get("services", [])
    prd = next((s for s in services if s.get("name") == "perf-coach-prd"), None)
    assert prd is not None, "perf-coach-prd service not found in render.yaml"
    env_val = _env_value(prd.get("envVars", []), "BANISTER_REFIT_ENABLED")
    assert env_val == "0", (
        f"perf-coach-prd: expected BANISTER_REFIT_ENABLED=0, got {env_val!r}"
    )


def test_render_yaml_healthz_probe():
    doc = _render_yaml()
    for name in ("perf-coach-uat", "perf-coach-prd"):
        svc = next((s for s in doc.get("services", []) if s.get("name") == name), None)
        assert svc is not None
        assert svc.get("healthCheckPath") == "/api/healthz", name


# ── AC2: db.py engine pool settings ──────────────────────────────────────────


def test_db_pool_size():
    """AC2a: SQLAlchemy engine uses pool_size=3."""
    from backend.db import engine

    pool = engine.pool
    assert pool.size() == 3, f"Expected pool_size=3, got {pool.size()}"


def test_db_max_overflow():
    """AC2b: SQLAlchemy engine uses max_overflow=2."""
    from backend.db import engine

    pool = engine.pool
    # _max_overflow is a private SQLAlchemy attr (verified against 2.0.x).
    # If this breaks after a dep bump, check QueuePool's public API for max_overflow.
    assert pool._max_overflow == 2, (
        f"Expected max_overflow=2, got {pool._max_overflow}"
    )


def test_db_pool_pre_ping_and_recycle_unchanged():
    """AC2c: pool_pre_ping=True and pool_recycle=3600 are preserved."""
    from backend.db import engine

    # _pre_ping and _recycle are private SQLAlchemy attrs (verified against 2.0.x).
    # If these break after a dep bump, look for pool_pre_ping / pool_recycle
    # equivalents in the public QueuePool or Engine API for that version.
    assert engine.pool._pre_ping is True, "pool_pre_ping must remain True"
    assert engine.pool._recycle == 3600, (
        f"pool_recycle must remain 3600, got {engine.pool._recycle}"
    )


# ── AC3: _sync_pool uses max_workers=1 ────────────────────────────────────────


def test_sync_pool_max_workers():
    """AC3: _sync_pool in backend/main.py has max_workers=1."""
    import backend.main as main_mod

    pool = main_mod._sync_pool
    assert pool._max_workers == 1, (
        f"Expected _sync_pool max_workers=1, got {pool._max_workers}"
    )


# ── AC4: no scipy import when BANISTER_REFIT_ENABLED=0 ───────────────────────


def test_no_scipy_when_banister_disabled():
    """AC4: scipy not in sys.modules after app import with BANISTER_REFIT_ENABLED=0."""
    env = {**os.environ, "BANISTER_REFIT_ENABLED": "0"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import backend.main; "
            "print('scipy' not in sys.modules)",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"subprocess failed:\n{result.stderr}"
    assert result.stdout.strip() == "True", (
        f"scipy was imported in web process with BANISTER_REFIT_ENABLED=0.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr[:500]!r}"
    )


# ── AC5: worker_app.py has no BANISTER_REFIT_ENABLED guard ───────────────────


def test_worker_app_not_gated():
    """AC5: worker_app.py does not gate its Banister refit on BANISTER_REFIT_ENABLED."""
    worker_path = os.path.join(REPO_ROOT, "backend", "worker_app.py")
    with open(worker_path) as f:
        src = f.read()

    # The guard BANISTER_REFIT_ENABLED must not suppress the worker's scheduler
    # (the worker always runs the refit). So either the var is absent from the
    # worker entirely, or it is present but the worker always enables it.
    # Simplest invariant: the worker's refit scheduler setup is not gated
    # by checking os.environ.get("BANISTER_REFIT_ENABLED") == "0".
    assert 'os.environ.get("BANISTER_REFIT_ENABLED", "1") != "0"' not in src, (
        "worker_app.py must not gate its Banister refit on BANISTER_REFIT_ENABLED"
    )


# ── AC6: refit scheduler thread does not start when env var is 0 ─────────────


def test_banister_refit_thread_not_started_when_disabled():
    """AC6: with BANISTER_REFIT_ENABLED=0, no banister-refit-scheduler thread starts."""
    env = {**os.environ, "BANISTER_REFIT_ENABLED": "0"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import threading; import backend.main; "
            "names = [t.name for t in threading.enumerate()]; "
            "print('banister-refit-scheduler' not in names)",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"subprocess failed:\n{result.stderr}"
    assert result.stdout.strip() == "True", (
        f"banister-refit-scheduler thread was started with BANISTER_REFIT_ENABLED=0.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr[:500]!r}"
    )
