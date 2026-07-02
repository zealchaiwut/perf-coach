"""Tests for periodic model refit with versioning and rollback (issue #1170).

AC coverage:
  (a) Refit produces a new version with unique version_id — distinct from all prior fits.
  (b) Rollback restores the previous version as active, without manual file editing.
  (c) Schedule fires the refit callable on the configured interval.
  (d) Two most recent versioned fits are retained at minimum.
  (e) Active fit version is observable at runtime via get_active_version().
  (f) py_compile passes on all new .py files with zero errors.
"""

import json
import os
import py_compile
import tempfile
import threading
import time

import pytest

from backend.services.model_refit import (
    ModelRefitStore,
    NoPreviousVersionError,
)
from backend.services.refit_scheduler import RefitScheduler

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pairs(n=6):
    """Return n (load, performance) pairs for fitting."""
    return [(float(i + 1) * 10, float(i + 1) * 5 + 20) for i in range(n)]


def _store():
    """Return an in-memory ModelRefitStore (no disk I/O)."""
    return ModelRefitStore(storage_dir=None)


# ── AC (a): Refit produces a new versioned artifact ──────────────────────────


def test_refit_returns_version_dict():
    """run_refit returns a dict representing the new versioned fit."""
    store = _store()
    version = store.run_refit(_make_pairs())
    assert isinstance(version, dict)


def test_refit_version_has_required_keys():
    """Versioned artifact includes version_id, constants, and fitted_at."""
    store = _store()
    version = store.run_refit(_make_pairs())
    assert "version_id" in version
    assert "constants" in version
    assert "fitted_at" in version


def test_refit_constants_has_slope_and_intercept():
    """Fitted constants include at least slope and intercept."""
    store = _store()
    version = store.run_refit(_make_pairs())
    assert "slope" in version["constants"]
    assert "intercept" in version["constants"]


def test_two_refits_have_distinct_version_ids():
    """Two sequential refits produce artifacts with different version identifiers."""
    store = _store()
    v1 = store.run_refit(_make_pairs())
    time.sleep(0.001)
    v2 = store.run_refit(_make_pairs())
    assert v1["version_id"] != v2["version_id"]


def test_refit_version_id_is_non_empty_string():
    store = _store()
    version = store.run_refit(_make_pairs())
    assert isinstance(version["version_id"], str)
    assert len(version["version_id"]) > 0


# ── AC (e): Active fit version is observable at runtime ──────────────────────


def test_get_active_version_returns_none_before_any_refit():
    """Before any refit, get_active_version() returns None."""
    store = _store()
    assert store.get_active_version() is None


def test_active_version_set_after_refit():
    """After a refit, get_active_version() returns that version."""
    store = _store()
    version = store.run_refit(_make_pairs())
    active = store.get_active_version()
    assert active is not None
    assert active["version_id"] == version["version_id"]


def test_active_version_is_most_recent_after_two_refits():
    """Active version tracks the latest refit."""
    store = _store()
    store.run_refit(_make_pairs())
    time.sleep(0.001)
    v2 = store.run_refit(_make_pairs())
    assert store.get_active_version()["version_id"] == v2["version_id"]


def test_active_version_constants_are_numeric():
    """Constants in the active version are numeric (slope and intercept)."""
    store = _store()
    store.run_refit(_make_pairs())
    active = store.get_active_version()
    assert isinstance(active["constants"]["slope"], (int, float))
    assert isinstance(active["constants"]["intercept"], (int, float))


# ── AC (b): Rollback restores the previous version ──────────────────────────


def test_rollback_after_two_refits_restores_first():
    """After two refits, rollback makes the first fit active again."""
    store = _store()
    v1 = store.run_refit(_make_pairs())
    time.sleep(0.001)
    store.run_refit(_make_pairs())
    store.rollback()
    assert store.get_active_version()["version_id"] == v1["version_id"]


def test_rollback_raises_when_only_one_version():
    """Rollback raises NoPreviousVersionError when no prior version exists."""
    store = _store()
    store.run_refit(_make_pairs())
    with pytest.raises(NoPreviousVersionError):
        store.rollback()


def test_rollback_raises_when_no_versions():
    """Rollback raises NoPreviousVersionError on an empty store."""
    store = _store()
    with pytest.raises(NoPreviousVersionError):
        store.rollback()


def test_rollback_active_version_has_prior_constants():
    """After rollback, the active constants match those from the prior fit."""
    store = _store()
    pairs1 = [(10.0, 20.0), (20.0, 30.0), (30.0, 40.0), (40.0, 50.0), (50.0, 60.0), (60.0, 70.0)]
    pairs2 = [(10.0, 5.0), (20.0, 8.0), (30.0, 11.0), (40.0, 14.0), (50.0, 17.0), (60.0, 20.0)]
    v1 = store.run_refit(pairs1)
    time.sleep(0.001)
    store.run_refit(pairs2)
    store.rollback()
    active = store.get_active_version()
    assert active["constants"] == v1["constants"]


# ── AC (d): Two most recent versions are retained at minimum ─────────────────


def test_list_versions_has_at_least_two_after_two_refits():
    store = _store()
    store.run_refit(_make_pairs())
    time.sleep(0.001)
    store.run_refit(_make_pairs())
    assert len(store.list_versions()) >= 2


def test_at_least_two_versions_retained_after_three_refits():
    """With default max_versions=2, at least two versions survive three refits."""
    store = _store()
    for _ in range(3):
        store.run_refit(_make_pairs())
        time.sleep(0.001)
    assert len(store.list_versions()) >= 2


def test_two_most_recent_versions_always_present():
    """After N refits, the two most recent version IDs are always in list_versions()."""
    store = ModelRefitStore(storage_dir=None, max_versions=2)
    v_ids = []
    for _ in range(4):
        v = store.run_refit(_make_pairs())
        v_ids.append(v["version_id"])
        time.sleep(0.001)
    retained = {v["version_id"] for v in store.list_versions()}
    assert v_ids[-1] in retained, "Newest version must be retained"
    assert v_ids[-2] in retained, "Second-newest version must be retained"


# ── AC (c): Schedule fires the refit callable ────────────────────────────────


def test_schedule_fires_refit_callable():
    """RefitScheduler calls the refit callable within the scheduled interval."""
    fired = threading.Event()

    def fake_refit():
        fired.set()

    scheduler = RefitScheduler()
    scheduler.start(interval_seconds=0.1, refit_callable=fake_refit)
    try:
        assert fired.wait(timeout=2.0), "Scheduler did not fire within 2 seconds"
    finally:
        scheduler.stop()


def test_scheduler_fires_multiple_times():
    """Scheduler fires repeatedly, not just once."""
    counter = {"n": 0}
    lock = threading.Lock()

    def count_refit():
        with lock:
            counter["n"] += 1

    scheduler = RefitScheduler()
    scheduler.start(interval_seconds=0.05, refit_callable=count_refit)
    time.sleep(0.5)
    scheduler.stop()
    assert counter["n"] >= 2, "Scheduler should have fired at least twice in 500ms"


def test_scheduler_is_running_after_start():
    scheduler = RefitScheduler()
    scheduler.start(interval_seconds=60, refit_callable=lambda: None)
    try:
        assert scheduler.is_running()
    finally:
        scheduler.stop()


def test_scheduler_is_not_running_after_stop():
    scheduler = RefitScheduler()
    scheduler.start(interval_seconds=60, refit_callable=lambda: None)
    scheduler.stop()
    assert not scheduler.is_running()


# ── AC (d) — Disk persistence ────────────────────────────────────────────────


def test_disk_persistence_creates_versioned_json_file():
    """run_refit writes a timestamped JSON artifact to storage_dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = ModelRefitStore(storage_dir=tmp_dir)
        store.run_refit(_make_pairs())
        version_files = [f for f in os.listdir(tmp_dir) if f.endswith(".json") and f != "active.json"]
        assert len(version_files) == 1


def test_disk_persistence_active_pointer_written():
    """run_refit writes an active.json pointer to the new version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = ModelRefitStore(storage_dir=tmp_dir)
        v = store.run_refit(_make_pairs())
        with open(os.path.join(tmp_dir, "active.json")) as fh:
            data = json.load(fh)
        assert data["active_version_id"] == v["version_id"]


def test_disk_persistence_reloads_on_new_instance():
    """A new store instance reading the same storage_dir restores the active version."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store1 = ModelRefitStore(storage_dir=tmp_dir)
        v = store1.run_refit(_make_pairs())
        store2 = ModelRefitStore(storage_dir=tmp_dir)
        active = store2.get_active_version()
        assert active is not None
        assert active["version_id"] == v["version_id"]


def test_rollback_updates_active_pointer_on_disk():
    """rollback() persists the updated active pointer so restarts see it."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = ModelRefitStore(storage_dir=tmp_dir)
        v1 = store.run_refit(_make_pairs())
        time.sleep(0.001)
        store.run_refit(_make_pairs())
        store.rollback()
        store2 = ModelRefitStore(storage_dir=tmp_dir)
        assert store2.get_active_version()["version_id"] == v1["version_id"]


# ── AC (f): py_compile passes with zero errors ───────────────────────────────


def test_py_compile_model_refit():
    path = os.path.join(
        os.path.dirname(__file__), "..", "backend", "services", "model_refit.py"
    )
    py_compile.compile(os.path.normpath(path), doraise=True)


def test_py_compile_refit_scheduler():
    path = os.path.join(
        os.path.dirname(__file__), "..", "backend", "services", "refit_scheduler.py"
    )
    py_compile.compile(os.path.normpath(path), doraise=True)
