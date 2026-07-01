"""Periodic model refit with versioning and rollback (issue #1170).

Provides a thread-safe versioned store for model constants produced by
fitting (load, performance) pairs.  Retains at least two most recent
versioned fits, enabling one-step rollback without manual file editing.

Each completed refit is persisted as a timestamped JSON artifact under
``storage_dir`` (when provided); an ``active.json`` pointer tracks which
version is currently in use.  Pass ``storage_dir=None`` for in-memory-only
operation (useful in tests).

Typical usage::

    store = ModelRefitStore(storage_dir="/var/data/fit_versions")
    version = store.run_refit(data_pairs)   # fit and save
    active  = store.get_active_version()    # observe current constants
    store.rollback()                        # restore prior version
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_RETAINED_VERSIONS: int = 2


class NoPreviousVersionError(Exception):
    """Raised by :meth:`ModelRefitStore.rollback` when no earlier version exists."""


def _linear_fit_constants(pairs: list) -> dict:
    """Fit a linear model to *(load, performance)* pairs via ordinary least squares.

    Returns a dict with ``slope`` and ``intercept`` (both rounded to 6 d.p.).
    Falls back to zero coefficients when *pairs* is empty or all x-values are
    identical (zero variance).
    """
    n = len(pairs)
    if n == 0:
        return {"slope": 0.0, "intercept": 0.0}
    xs = [float(p[0]) for p in pairs]
    ys = [float(p[1]) for p in pairs]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    slope = num / den if den != 0.0 else 0.0
    intercept = y_mean - slope * x_mean
    return {"slope": round(slope, 6), "intercept": round(intercept, 6)}


class ModelRefitStore:
    """Versioned store for model constants produced by periodic refits.

    Parameters
    ----------
    storage_dir:
        Directory where versioned JSON artifacts are persisted.  Created
        automatically if it does not exist.  Pass ``None`` for in-memory
        operation (versions are lost on process exit).
    max_versions:
        Number of most-recent fit versions to retain.  Minimum is 2.
    """

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        max_versions: int = _MAX_RETAINED_VERSIONS,
    ) -> None:
        self._lock = threading.Lock()
        self._storage_dir = storage_dir
        self._max_versions = max(2, max_versions)
        self._versions: list[dict] = []
        self._active_version_id: Optional[str] = None

        if self._storage_dir:
            os.makedirs(self._storage_dir, exist_ok=True)
            self._load_from_disk()

        if self._active_version_id:
            logger.info("model_refit: active version on load: %s", self._active_version_id)
        else:
            logger.info("model_refit: no active version on load")

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_refit(self, data_pairs: list) -> dict:
        """Fit constants from *data_pairs*, save a versioned artifact, and activate it.

        Parameters
        ----------
        data_pairs:
            List of ``(load, performance)`` tuples.

        Returns
        -------
        dict
            The new version: ``version_id``, ``constants``, ``fitted_at``.
        """
        constants = _linear_fit_constants(data_pairs)
        fitted_at = datetime.now(timezone.utc)
        version_id = fitted_at.strftime("%Y%m%dT%H%M%S%fZ")
        version = {
            "version_id": version_id,
            "constants": constants,
            "fitted_at": fitted_at.isoformat(),
        }

        with self._lock:
            self._versions.append(version)
            self._active_version_id = version_id
            self._prune_versions()
            if self._storage_dir:
                self._save_version_to_disk(version)
                self._save_active_pointer()

        logger.info("model_refit: new version fitted and activated: %s", version_id)
        return version

    def rollback(self) -> dict:
        """Restore the prior versioned fit as the active fit.

        Returns
        -------
        dict
            The version that is now active.

        Raises
        ------
        NoPreviousVersionError
            When there is no earlier version to restore.
        """
        with self._lock:
            idx = self._active_index()
            if idx is None or idx == 0:
                raise NoPreviousVersionError("No previous version to roll back to.")
            prior = self._versions[idx - 1]
            self._active_version_id = prior["version_id"]
            if self._storage_dir:
                self._save_active_pointer()

        logger.info("model_refit: rolled back to version: %s", prior["version_id"])
        return prior

    def get_active_version(self) -> Optional[dict]:
        """Return the currently active versioned fit, or ``None`` if no fit exists."""
        with self._lock:
            if self._active_version_id is None:
                return None
            for v in self._versions:
                if v["version_id"] == self._active_version_id:
                    return dict(v)
            return None

    def list_versions(self) -> list:
        """Return all retained versions in chronological order (oldest first)."""
        with self._lock:
            return [dict(v) for v in self._versions]

    # ── Internals ──────────────────────────────────────────────────────────────

    def _active_index(self) -> Optional[int]:
        if self._active_version_id is None:
            return None
        for i, v in enumerate(self._versions):
            if v["version_id"] == self._active_version_id:
                return i
        return None

    def _prune_versions(self) -> None:
        """Keep at most *max_versions* most recent; always preserve the active version."""
        if len(self._versions) <= self._max_versions:
            return
        keep_ids = {v["version_id"] for v in self._versions[-self._max_versions:]}
        if self._active_version_id:
            keep_ids.add(self._active_version_id)
        self._versions = [v for v in self._versions if v["version_id"] in keep_ids]

    def _save_version_to_disk(self, version: dict) -> None:
        path = os.path.join(self._storage_dir, f"{version['version_id']}.json")
        with open(path, "w") as fh:
            json.dump(version, fh, indent=2)

    def _save_active_pointer(self) -> None:
        path = os.path.join(self._storage_dir, "active.json")
        with open(path, "w") as fh:
            json.dump({"active_version_id": self._active_version_id}, fh)

    def _load_from_disk(self) -> None:
        active_path = os.path.join(self._storage_dir, "active.json")
        if os.path.exists(active_path):
            with open(active_path) as fh:
                data = json.load(fh)
            self._active_version_id = data.get("active_version_id")

        versions = []
        for fname in os.listdir(self._storage_dir):
            if fname.endswith(".json") and fname != "active.json":
                path = os.path.join(self._storage_dir, fname)
                with open(path) as fh:
                    v = json.load(fh)
                versions.append(v)
        versions.sort(key=lambda v: v["version_id"])
        self._versions = versions
