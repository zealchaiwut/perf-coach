#!/usr/bin/env python3
"""CLI command to roll back the active model fit to the prior version (issue #1170).

Usage::

    python scripts/rollback_refit.py

Override the store directory with the FIT_STORE_DIR environment variable.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.services.model_refit import ModelRefitStore, NoPreviousVersionError

_DEFAULT_STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fit_versions")


def main() -> None:
    store_dir = os.environ.get("FIT_STORE_DIR", _DEFAULT_STORE_DIR)
    store = ModelRefitStore(storage_dir=os.path.normpath(store_dir))
    try:
        prior = store.rollback()
        print(f"Rolled back to version: {prior['version_id']}")
        print(f"  fitted_at:  {prior['fitted_at']}")
        print(f"  constants:  {prior['constants']}")
    except NoPreviousVersionError as exc:
        print(f"Rollback failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
