"""Tests for issue #1204: per-user Banister parameter storage with versioned history.

AC coverage:
  AC1 — save_banister_params inserts a new versioned record; prior records retained.
  AC2 — get_banister_params returns the latest fitted record when one exists.
  AC3 — get_banister_params returns population defaults for a user with no stored params.
  AC4 — list_banister_param_versions returns full history in descending chronological order.
  AC5 — Existing consumers of get_banister_params are unaffected (no API change / defaults).
  AC6 — Unit tests: save + retrieve latest, multiple versions in order, missing user defaults.
  AC7 — All new/modified files pass py_compile with zero errors.
"""

import py_compile
import time
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


# ── Fixture: in-memory SQLite with user_banister_params table ─────────────────


@pytest.fixture(scope="module")
def db_engine():
    """In-memory SQLite engine with user_banister_params created from the real model."""
    from backend.models import UserBanisterParams

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite ignores FK constraints by default, so we can create this table
    # without also creating the users table.
    UserBanisterParams.__table__.create(eng, checkfirst=True)
    return eng


@pytest.fixture
def db(db_engine):
    with Session(db_engine) as sess:
        yield sess
        sess.rollback()


def _uid() -> uuid.UUID:
    """Return a new unique UUID for use as a test user_id."""
    return uuid.uuid4()


# ── AC7: py_compile ───────────────────────────────────────────────────────────


def test_ac7_banister_params_service_compiles():
    """backend/services/banister_params.py passes py_compile with zero errors."""
    import backend.services.banister_params as mod

    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_ac7_models_compiles():
    """backend/models.py passes py_compile with zero errors after adding UserBanisterParams."""
    import backend.models as mod

    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_ac7_migration_compiles():
    """The new Alembic migration file passes py_compile with zero errors."""
    import os
    import glob

    versions_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    matches = glob.glob(os.path.join(versions_dir, "*user_banister_params*"))
    assert matches, "No migration file matching *user_banister_params* found"
    for path in matches:
        py_compile.compile(path, doraise=True)


# ── AC5: POPULATION_DEFAULTS ──────────────────────────────────────────────────


def test_ac5_population_defaults_exist():
    """POPULATION_DEFAULTS dict is importable and contains all four Banister keys."""
    from backend.services.banister_params import POPULATION_DEFAULTS

    for key in ("tau1", "tau2", "k1", "k2"):
        assert key in POPULATION_DEFAULTS, f"POPULATION_DEFAULTS missing: {key}"
        assert isinstance(POPULATION_DEFAULTS[key], float)


# ── AC1: save inserts new versioned row; prior rows retained ──────────────────


def test_ac1_save_returns_dict_with_id(db):
    """save_banister_params returns a serialised dict including a non-null id."""
    from backend.services.banister_params import save_banister_params

    uid = _uid()
    result = save_banister_params(db, uid, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()

    assert isinstance(result, dict)
    assert result["id"] is not None
    assert result["tau1"] == pytest.approx(50.0)
    assert result["tau2"] == pytest.approx(11.0)
    assert result["k1"] == pytest.approx(1.0)
    assert result["k2"] == pytest.approx(2.0)
    assert result["fitted_at"] is not None


def test_ac1_save_twice_produces_distinct_ids(db):
    """Two saves for the same user produce distinct row ids (no overwrite)."""
    from backend.services.banister_params import save_banister_params

    uid = _uid()
    r1 = save_banister_params(db, uid, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()
    time.sleep(0.002)
    r2 = save_banister_params(db, uid, tau1=55.0, tau2=12.0, k1=1.1, k2=2.1)
    db.commit()

    assert r1["id"] != r2["id"], "Two saves must produce distinct row ids"


def test_ac1_prior_records_retained(db):
    """Both rows are still retrievable after two saves (no overwrite)."""
    from backend.services.banister_params import save_banister_params, list_banister_param_versions

    uid = _uid()
    save_banister_params(db, uid, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()
    time.sleep(0.002)
    save_banister_params(db, uid, tau1=55.0, tau2=12.0, k1=1.1, k2=2.1)
    db.commit()

    versions = list_banister_param_versions(db, uid)
    assert len(versions) == 2, f"Expected 2 retained versions, got {len(versions)}"


# ── AC2: get returns the most recent record ───────────────────────────────────


def test_ac2_get_returns_latest_record(db):
    """get_banister_params returns the most-recently saved record for the user."""
    from backend.services.banister_params import save_banister_params, get_banister_params

    uid = _uid()
    save_banister_params(db, uid, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()
    time.sleep(0.002)
    save_banister_params(db, uid, tau1=60.0, tau2=13.0, k1=1.5, k2=2.5)
    db.commit()

    result = get_banister_params(db, uid)
    assert result["tau1"] == pytest.approx(60.0), "Must return the second (latest) row"
    assert result["tau2"] == pytest.approx(13.0)
    assert result["k1"] == pytest.approx(1.5)
    assert result["k2"] == pytest.approx(2.5)


def test_ac2_get_returns_dict_with_fitted_at(db):
    """get_banister_params result includes a fitted_at timestamp string."""
    from backend.services.banister_params import save_banister_params, get_banister_params

    uid = _uid()
    save_banister_params(db, uid, tau1=50.0, tau2=11.0, k1=1.0, k2=2.0)
    db.commit()

    result = get_banister_params(db, uid)
    assert "fitted_at" in result
    assert result["fitted_at"] is not None


# ── AC3: get returns defaults for unknown user ────────────────────────────────


def test_ac3_get_returns_defaults_for_new_user(db):
    """get_banister_params returns POPULATION_DEFAULTS when no row exists."""
    from backend.services.banister_params import get_banister_params, POPULATION_DEFAULTS

    result = get_banister_params(db, _uid())

    assert result == POPULATION_DEFAULTS


def test_ac3_get_never_raises(db):
    """get_banister_params returns a dict (no exception) for any user_id."""
    from backend.services.banister_params import get_banister_params

    result = get_banister_params(db, _uid())
    assert isinstance(result, dict)
    for key in ("tau1", "tau2", "k1", "k2"):
        assert key in result


# ── AC4: list returns all in descending chronological order ──────────────────


def test_ac4_list_returns_all_versions_descending(db):
    """list_banister_param_versions returns all rows newest-first."""
    from backend.services.banister_params import save_banister_params, list_banister_param_versions

    uid = _uid()
    values = [(50.0, 11.0, 1.0, 2.0), (52.0, 11.5, 1.1, 2.1), (54.0, 12.0, 1.2, 2.2)]
    for tau1, tau2, k1, k2 in values:
        save_banister_params(db, uid, tau1=tau1, tau2=tau2, k1=k1, k2=k2)
        db.commit()
        time.sleep(0.002)

    versions = list_banister_param_versions(db, uid)
    assert len(versions) == 3, f"Expected 3 versions, got {len(versions)}"

    for i in range(len(versions) - 1):
        assert versions[i]["fitted_at"] >= versions[i + 1]["fitted_at"], (
            "list_banister_param_versions must be newest-first"
        )

    assert versions[0]["tau1"] == pytest.approx(54.0), "Latest row must be first"


def test_ac4_list_empty_for_new_user(db):
    """list_banister_param_versions returns [] for a user with no rows."""
    from backend.services.banister_params import list_banister_param_versions

    assert list_banister_param_versions(db, _uid()) == []


# ── AC6: combined scenario ────────────────────────────────────────────────────


def test_ac6_save_then_retrieve_latest(db):
    """Save one record then get it back as the latest."""
    from backend.services.banister_params import save_banister_params, get_banister_params

    uid = _uid()
    saved = save_banister_params(db, uid, tau1=47.0, tau2=10.5, k1=0.95, k2=1.9)
    db.commit()

    latest = get_banister_params(db, uid)
    assert latest["tau1"] == pytest.approx(47.0)
    assert latest["id"] == saved["id"]


def test_ac6_multiple_versions_returned_in_order(db):
    """Three saves → list returns all three in descending order."""
    from backend.services.banister_params import save_banister_params, list_banister_param_versions

    uid = _uid()
    for i in range(3):
        save_banister_params(db, uid, tau1=40.0 + i * 5, tau2=10.0 + i, k1=0.9 + i * 0.1, k2=1.8 + i * 0.1)
        db.commit()
        time.sleep(0.002)

    versions = list_banister_param_versions(db, uid)
    assert len(versions) == 3

    tau1_values = [v["tau1"] for v in versions]
    assert tau1_values == sorted(tau1_values, reverse=True), (
        "Versions must be ordered newest (highest tau1) first"
    )


def test_ac6_missing_user_returns_defaults(db):
    """get returns POPULATION_DEFAULTS (no exception) for a brand-new user."""
    from backend.services.banister_params import get_banister_params, POPULATION_DEFAULTS

    assert get_banister_params(db, _uid()) == POPULATION_DEFAULTS
