"""Positive assertion for worker_app.py Banister refit scheduler (issue #1300).

The original test_worker_app_not_gated (AC5 of #1292) only checks that the
BANISTER_REFIT_ENABLED guard is absent. This file adds the complementary
positive assertions so the invariant holds against false negatives too:
if the refit scheduler setup is removed from worker_app.py, these tests fail.
"""

from __future__ import annotations

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_worker_has_run_banister_refit_batch():
    """_run_banister_refit_batch must be defined in worker_app.py."""
    worker_path = os.path.join(REPO_ROOT, "backend", "worker_app.py")
    with open(worker_path) as f:
        src = f.read()
    assert "_run_banister_refit_batch" in src, (
        "worker_app.py must define _run_banister_refit_batch "
        "(refit scheduler setup absent)"
    )


def test_worker_dispatches_banister_refit_job():
    """worker_app.py must dispatch 'banister_refit' jobs."""
    worker_path = os.path.join(REPO_ROOT, "backend", "worker_app.py")
    with open(worker_path) as f:
        src = f.read()
    assert '"banister_refit"' in src, (
        "worker_app.py must dispatch 'banister_refit' jobs "
        "(refit scheduler setup absent)"
    )


def test_worker_defines_banister_refit_interval():
    """_BANISTER_REFIT_INTERVAL_SECONDS must be defined in worker_app.py."""
    worker_path = os.path.join(REPO_ROOT, "backend", "worker_app.py")
    with open(worker_path) as f:
        src = f.read()
    assert "_BANISTER_REFIT_INTERVAL_SECONDS" in src, (
        "worker_app.py must define _BANISTER_REFIT_INTERVAL_SECONDS "
        "(refit scheduler setup absent)"
    )
