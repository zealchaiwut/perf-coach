"""Tests for Banister batch refit pipeline (issue #1206).

AC coverage:
  AC1 — Pipeline saves new versioned params for users with >= 14 observations and a convergent fit.
  AC2 — Pipeline emits WARNING and skips storage for users below the data gate.
  AC3 — Pipeline emits WARNING and skips storage when fitting fails to converge.
  AC4 — A batch run for the same user produces a new version row without removing prior rows.
  AC5 — Integration test: success path (fit → validate → store), data-gate fallback,
        convergence-failure fallback.
  AC6 — All new/modified files pass py_compile with zero errors.
"""

from __future__ import annotations

import logging
import math
import py_compile
import uuid
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


# ── helpers ──────────────────────────────────────────────────────────────────


def _banister_performance(loads, tau1, tau2, k1, k2, p0=250.0):
    """Compute ground-truth Banister performance series from known parameters."""
    alpha1 = math.exp(-1.0 / tau1)
    alpha2 = math.exp(-1.0 / tau2)
    g, h = 0.0, 0.0
    perfs = []
    for w in loads:
        g = g * alpha1 + w
        h = h * alpha2 + w
        perfs.append(p0 + k1 * g - k2 * h)
    return perfs


def _synthetic_banister_data(n=30):
    """Return (load_series, perf_series) with known Banister signal shape."""
    loads = [50.0 + 10.0 * math.sin(i * 0.5) for i in range(n)]
    perfs = _banister_performance(loads, tau1=42.0, tau2=7.0, k1=1.0, k2=2.0)
    return loads, perfs


def _uid():
    return uuid.uuid4()


# ── Fixtures: in-memory SQLite with required tables ──────────────────────────


@pytest.fixture(scope="module")
def db_engine():
    """In-memory SQLite engine with UserBanisterParams and TrainingLoadSnapshot."""
    from backend.models import UserBanisterParams, TrainingLoadSnapshot

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserBanisterParams.__table__.create(eng, checkfirst=True)
    TrainingLoadSnapshot.__table__.create(eng, checkfirst=True)
    return eng


@pytest.fixture
def db(db_engine):
    with Session(db_engine) as sess:
        yield sess
        sess.rollback()


def _insert_snapshot_rows(session, user_id, loads, perfs, base_date=None):
    """Insert TrainingLoadSnapshot rows for (load, performance) pairs.

    Provides explicit Python-side UUIDs to avoid the gen_random_uuid()
    server_default that is PostgreSQL-only.
    """
    from backend.models import TrainingLoadSnapshot

    if base_date is None:
        base_date = date(2024, 1, 1)
    rows = []
    for i, (load, perf) in enumerate(zip(loads, perfs)):
        snap_date = base_date + timedelta(days=i)
        row = TrainingLoadSnapshot(
            id=uuid.uuid4(),   # explicit to avoid gen_random_uuid() in SQLite
            user_id=user_id,
            snapshot_date=snap_date,
            tss_for_day=int(round(load)),
            ctl=perf,          # perf stored in ctl column for fitting
            atl=float(load),
            tsb=perf - float(load),
            computed_at=datetime.now(timezone.utc),
        )
        rows.append(row)
    session.add_all(rows)
    session.flush()


def _make_session_factory(engine):
    """Return a callable that produces a SQLAlchemy Session context manager."""
    from contextlib import contextmanager

    @contextmanager
    def _factory():
        with Session(engine) as sess:
            yield sess

    return _factory


# ── AC6: py_compile ───────────────────────────────────────────────────────────


def test_ac6_banister_pipeline_compiles():
    """backend/services/banister_pipeline.py passes py_compile."""
    import backend.services.banister_pipeline as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_ac6_banister_fitting_compiles():
    """backend/services/banister_fitting.py passes py_compile after additions."""
    import backend.services.banister_fitting as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── validate_banister_fit unit tests ─────────────────────────────────────────


def test_validate_accepts_good_params():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(42.0, 7.0, 1.0, 2.0) is True


def test_validate_rejects_nan_tau1():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(float("nan"), 7.0, 1.0, 2.0) is False


def test_validate_rejects_inf_k2():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(42.0, 7.0, 1.0, float("inf")) is False


def test_validate_rejects_tau_below_min():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(0.5, 7.0, 1.0, 2.0) is False


def test_validate_rejects_tau_above_max():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(42.0, 91.0, 1.0, 2.0) is False


def test_validate_accepts_boundary_tau_values():
    from backend.services.banister_fitting import validate_banister_fit
    assert validate_banister_fit(1.0, 90.0, 0.5, 1.5) is True


# ── AC1: success path — saves versioned params ────────────────────────────────


def test_ac1_pipeline_saves_params_on_success(db_engine, db):
    """Pipeline inserts a UserBanisterParams row when fitting succeeds."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)] == "ok"
    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 1, "Expected exactly one stored param row"


def test_ac1_saved_params_have_valid_tau(db_engine, db):
    """Stored params must have τ₁ and τ₂ in [1, 90]."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    row = (
        db.query(UserBanisterParams)
        .filter(UserBanisterParams.user_id == user_id)
        .first()
    )
    assert row is not None
    assert 1.0 <= row.tau1 <= 90.0
    assert 1.0 <= row.tau2 <= 90.0


# ── AC2: data gate — fewer than 14 observations ───────────────────────────────


def test_ac2_data_gate_emits_warning_not_exception(db_engine, db, caplog):
    """Pipeline emits a WARNING (not exception) and skips storage for < 14 pairs."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=5)   # below data gate
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    with caplog.at_level(logging.WARNING, logger="backend.services.banister_pipeline"):
        result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)].startswith("skipped")
    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 0, "Storage must be skipped when data gate fires"
    assert any("warning" in rec.levelname.lower() or "WARNING" in rec.levelname
               for rec in caplog.records), "At least one WARNING must be emitted"


def test_ac2_data_gate_zero_rows(db_engine, db, caplog):
    """Pipeline handles zero rows gracefully with WARNING and no storage."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    # Insert nothing for this user

    factory = _make_session_factory(db_engine)
    with caplog.at_level(logging.WARNING, logger="backend.services.banister_pipeline"):
        result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)].startswith("skipped")
    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 0


def test_ac2_previous_params_retained_after_data_gate(db_engine, db):
    """When data gate fires, previously stored params remain unchanged."""
    from backend.services.banister_params import save_banister_params, get_banister_params
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    # Pre-save a param record
    save_banister_params(db, user_id, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()

    # Insert fewer than 14 snapshot rows to trigger data gate
    loads, perfs = _synthetic_banister_data(n=8)
    _insert_snapshot_rows(db, user_id, loads, perfs, base_date=date(2024, 6, 1))
    db.commit()

    factory = _make_session_factory(db_engine)
    run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    latest = get_banister_params(db, user_id)
    assert latest["tau1"] == pytest.approx(50.0), "Prior params must not be overwritten"


# ── AC3: convergence failure — all-zero loads ─────────────────────────────────


def test_ac3_convergence_failure_emits_warning(db_engine, db, caplog):
    """Pipeline emits WARNING and skips storage when fitting fails to converge."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    # All-zero load → degenerate fit → None from fit_banister_params
    loads = [0.0] * 25
    perfs = [250.0] * 25
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    with caplog.at_level(logging.WARNING, logger="backend.services.banister_pipeline"):
        result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)].startswith("skipped")
    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 0
    assert any("WARNING" in rec.levelname or "warning" in rec.levelname.lower()
               for rec in caplog.records)


# ── AC4: each batch run produces a new version row ────────────────────────────


def test_ac4_two_runs_produce_two_rows(db_engine, db):
    """Running the pipeline twice for the same user stores two distinct rows."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    run_banister_refit_pipeline([str(user_id)], session_factory=factory)
    run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 2, f"Two runs must produce 2 versioned rows, got {len(rows)}"
    assert rows[0].id != rows[1].id


def test_ac4_prior_rows_not_deleted(db_engine, db):
    """Rows from earlier runs are never deleted."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    for _ in range(3):
        run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 3, "All 3 run-rows must be retained (no deletions)"


# ── AC5: integration test covering all three paths ────────────────────────────


def test_ac5_integration_success_path(db_engine, db):
    """End-to-end: fit → validate → store."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)] == "ok"
    saved = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).first()
    assert saved is not None
    assert saved.fitted_at is not None


def test_ac5_integration_data_gate_fallback(db_engine, db, caplog):
    """Integration: data-gate path emits WARNING, skips storage, keeps prior params."""
    from backend.services.banister_params import save_banister_params, get_banister_params
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    # Set up a prior saved param
    save_banister_params(db, user_id, tau1=48.0, tau2=9.0, k1=0.9, k2=1.8)
    db.commit()

    # Only 10 snapshot rows — below gate
    loads, perfs = _synthetic_banister_data(n=10)
    _insert_snapshot_rows(db, user_id, loads, perfs, base_date=date(2024, 3, 1))
    db.commit()

    factory = _make_session_factory(db_engine)
    with caplog.at_level(logging.WARNING, logger="backend.services.banister_pipeline"):
        result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)].startswith("skipped")
    # Prior params untouched — get_banister_params should still return the saved one
    current = get_banister_params(db, user_id)
    assert current["tau1"] == pytest.approx(48.0)


def test_ac5_integration_convergence_failure_fallback(db_engine, db, caplog):
    """Integration: convergence-failure path emits WARNING and skips storage."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads = [0.0] * 20   # zero-variance → degenerate fit
    perfs = [100.0] * 20
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    with caplog.at_level(logging.WARNING, logger="backend.services.banister_pipeline"):
        result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert result[str(user_id)].startswith("skipped")
    rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == user_id).all()
    assert len(rows) == 0


def test_ac5_integration_multi_user_mixed(db_engine, db):
    """Integration: batch with one success and one data-gate user."""
    from backend.models import UserBanisterParams
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    uid_good = _uid()
    uid_bad = _uid()

    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, uid_good, loads, perfs)

    # uid_bad gets only 5 rows
    loads2, perfs2 = _synthetic_banister_data(n=5)
    _insert_snapshot_rows(db, uid_bad, loads2, perfs2, base_date=date(2024, 6, 1))
    db.commit()

    factory = _make_session_factory(db_engine)
    result = run_banister_refit_pipeline(
        [str(uid_good), str(uid_bad)], session_factory=factory
    )

    assert result[str(uid_good)] == "ok"
    assert result[str(uid_bad)].startswith("skipped")

    good_rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == uid_good).all()
    bad_rows = db.query(UserBanisterParams).filter(UserBanisterParams.user_id == uid_bad).all()
    assert len(good_rows) == 1
    assert len(bad_rows) == 0


# ── Return value shape ────────────────────────────────────────────────────────


def test_pipeline_returns_dict_with_user_id_keys(db_engine, db):
    """run_banister_refit_pipeline returns dict[str, str] with user_id string keys."""
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    user_id = _uid()
    loads, perfs = _synthetic_banister_data(n=30)
    _insert_snapshot_rows(db, user_id, loads, perfs)
    db.commit()

    factory = _make_session_factory(db_engine)
    result = run_banister_refit_pipeline([str(user_id)], session_factory=factory)

    assert isinstance(result, dict)
    assert str(user_id) in result
    assert isinstance(result[str(user_id)], str)


def test_pipeline_empty_user_list_returns_empty_dict(db_engine):
    """Empty user list returns {}."""
    from backend.services.banister_pipeline import run_banister_refit_pipeline

    factory = _make_session_factory(db_engine)
    result = run_banister_refit_pipeline([], session_factory=factory)
    assert result == {}
