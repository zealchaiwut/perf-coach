"""Every process runs on Bangkok time — issue #1600, step 1.

perf-coach is a single-timezone app. Every "today" it computes — the morning
weigh-in, the fuel budget, the guardrail's week boundary, the weight hypothesis
— means a Bangkok calendar day.

Neither Render service nor the worker set ``TZ``, so all three ran **UTC**. A
bare ``date.today()`` therefore returned *yesterday* for the first seven hours
of every Bangkok day — 00:00 to 07:00 local, the window that contains the
morning weigh-in the whole lean program is built around. Wrong numbers, not
crashes, so nothing surfaced it.

There were 109 bare ``date.today()`` calls in ``backend/``. Setting ``TZ``
corrects all of them at once, which is why it goes first. It is not the whole
fix: ``today_bangkok()`` should still become the single resolution point so the
behaviour does not depend on deployment config (the rest of #1600), and the
frontend has its own split where two files use browser-local time (#1603).

Why this deserves a test: it is a config change with no code to review. Nothing
imports it, nothing calls it, and it can be dropped in a `render.yaml` edit
without anyone noticing until numbers quietly shift by a day.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RENDER_YAML = REPO / "render.yaml"
WORKER_SH = REPO / "start_worker.sh"
ENV_EXAMPLE = REPO / ".env.example"

BANGKOK = "Asia/Bangkok"


@pytest.fixture(scope="module")
def render_yaml() -> str:
    return RENDER_YAML.read_text()


def test_both_render_services_set_the_timezone(render_yaml):
    """One per service — UAT and PRD. Setting only one leaves the other
    computing a different 'today' from the same code."""
    assert render_yaml.count("- key: TZ") == 2, (
        "expected TZ on both the UAT and PRD services in render.yaml"
    )
    assert render_yaml.count(f"value: {BANGKOK}") == 2


def test_the_worker_sets_the_timezone_too():
    """The worker is launched from start_worker.sh on zeal-server, not by
    Render, so render.yaml does not cover it — and the worker is exactly where
    the morning weigh-in nudge and the daily coach job run."""
    src = WORKER_SH.read_text()
    assert "export TZ=" in src
    assert BANGKOK in src


def test_the_worker_timezone_is_overridable():
    """Default, not a hardcode — a deliberate override for testing another
    locale should still work."""
    assert 'export TZ="${TZ:-Asia/Bangkok}"' in WORKER_SH.read_text()


def test_env_example_documents_it():
    """An operator setting up locally gets the same clock as production."""
    src = ENV_EXAMPLE.read_text()
    assert "TZ=" in src
    assert BANGKOK in src


def test_no_naive_datetime_now_in_backend():
    """TZ changes what a naive datetime.now() means, not just date.today().

    This passed cleanly when TZ was introduced — every datetime in backend/ is
    explicitly UTC or explicitly Bangkok, so flipping the container clock could
    only affect date resolution, never a stored timestamp. If this starts
    failing, someone added a naive datetime.now() whose meaning now depends on
    deployment config.
    """
    offenders = []
    for path in (REPO / "backend").rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "datetime.now()" not in line:
                continue
            if any(marker in line for marker in ("timezone.utc", "BANGKOK", "_BKK", "tz=")):
                continue
            offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert not offenders, (
        "naive datetime.now() found — its meaning now depends on TZ. Use "
        "datetime.now(timezone.utc) for stored timestamps or the Bangkok "
        "helpers for user-facing days:\n  " + "\n  ".join(offenders)
    )


def test_bangkok_helper_still_exists():
    """TZ makes bare date.today() correct in deployment; today_bangkok() is what
    makes it correct regardless of deployment. The rest of #1600 routes call
    sites through it — this asserts it is still there to route to."""
    from backend.utils.time import today_bangkok

    assert callable(today_bangkok)
