"""Hermes and the dashboard agree about fitness — issue #1601.

perf-coach runs two FastAPI apps over one database. Both answered "what is my
CTL today", and they answered differently:

- webapp ``GET /api/training-load/current`` → ``training_load.current_load``,
  which requires an EXACT snapshot_date match, a matching ``formula_version``,
  and matching ``ctl_days``/``atl_days`` calibration — recomputing when any of
  those miss.
- worker ``GET /api/training/load`` → its own ``snapshot_date <= target_date``
  query, ordered desc, first row. No version check, no calibration check, no
  bound on staleness.

So after a formula change or a CTL-days settings edit, the dashboard showed the
correct number while Hermes reported one computed under the old formula,
possibly days old. Same athlete, same date, two answers — and the Discord
message is the one the athlete reads first thing in the morning.

The fix is delegation, not duplication: the worker calls the same function. That
is only possible because ``current_load`` lives in ``backend.services`` and
never imports ``backend.main`` — the constraint ``worker_app``'s module
docstring states, and the reason a shared core was extracted in the first place.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def worker_route_src() -> str:
    import backend.worker_app as w

    return inspect.getsource(w.training_load)


def _code_without_docstring(src: str) -> str:
    """Strip the leading triple-quoted docstring so prose describing the old
    behaviour isn't mistaken for the old behaviour."""
    opener = src.find('"""')
    if opener == -1:
        return src
    closer = src.find('"""', opener + 3)
    return src[:opener] + src[closer + 3:] if closer != -1 else src


# ── Delegation ────────────────────────────────────────────────────────────────

def test_worker_delegates_to_the_shared_load_function(worker_route_src):
    assert "current_load" in worker_route_src, (
        "the worker computes training load itself again; it must call the same "
        "training_load.current_load the dashboard uses"
    )


def test_worker_no_longer_hand_queries_snapshots(worker_route_src):
    """The exact shape of the bug: take the newest row at-or-before the date and
    trust it, whatever formula or calibration produced it.

    Checks the code body only. The docstring quotes the old query to explain the
    regression, and ``snapshot_date`` survives as a RESPONSE KEY that Hermes
    consumes — neither is the thing being guarded against.
    """
    body = _code_without_docstring(worker_route_src)
    assert "snapshot_date <=" not in body
    assert "TrainingLoadSnapshot" not in body


def test_shared_function_still_guards_version_and_calibration():
    """What the worker was skipping. If these guards ever leave current_load,
    delegation stops being a fix."""
    from backend.services import training_load

    src = inspect.getsource(training_load.current_load)
    assert "formula_version" in src
    assert "ctl_days" in src


# ── Rounding parity ───────────────────────────────────────────────────────────

def test_rounding_matches_the_webapp(worker_route_src):
    """The webapp rounds ctl/atl/tsb to 1 dp; the worker returned raw stored
    precision (2 dp), so the two could print different numbers from identical
    data even when the underlying row agreed."""
    assert "round(float(value), digits)" in worker_route_src

    main_src = (REPO / "backend" / "main.py").read_text()
    assert 'ctl = round(load["ctl"], 1)' in main_src, (
        "the webapp's rounding changed; the worker's _r default must follow"
    )


# ── The isolation rule still holds ────────────────────────────────────────────

def test_worker_does_not_import_backend_main():
    """worker_app's docstring: it must NEVER import backend.main, which starts
    daemon threads at import time. Delegation is only safe because current_load
    lives in backend.services."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys, backend.worker_app; "
         "print('backend.main' in sys.modules)"],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "False", "worker_app pulled in backend.main"


def test_current_load_is_importable_without_backend_main():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; from backend.services.training_load import current_load; "
         "print('backend.main' in sys.modules)"],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "False"


# ── Response shape preserved ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "key", ["date", "snapshot_date", "ctl", "atl", "tsb", "acwr", "verdict", "verdict_date"]
)
def test_response_keys_unchanged(worker_route_src, key):
    """Hermes consumes this shape. Fixing the number must not change the
    contract underneath it."""
    assert f'"{key}"' in worker_route_src
