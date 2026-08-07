"""Issue #1694 — PRD Banister refit guard: render.yaml, worker.md, release-process.md.

Three regression tests:

1. render.yaml must not silently disable Banister refit for PRD (BANISTER_REFIT_ENABLED
   must NOT be "0" for perf-coach-prd) until a PRD worker is confirmed running.
   The flag defaults to "1" when absent, so removing it is equally safe.

2. docs/worker.md must contain a PRD worker runbook section so ops can stand up
   the PRD worker and then flip the flag at deploy time.

3. docs/release-process.md must include a pre-deploy worker check step so the
   release procedure explicitly covers whether the PRD worker is live before
   disabling the fallback in-process refit.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
RENDER_YAML = REPO / "render.yaml"
WORKER_MD = REPO / "docs" / "worker.md"
RELEASE_MD = REPO / "docs" / "release-process.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prd_service(render_doc: dict) -> dict:
    """Return the perf-coach-prd service block from the parsed render.yaml."""
    for svc in render_doc.get("services", []):
        if svc.get("name") == "perf-coach-prd":
            return svc
    raise KeyError("perf-coach-prd service not found in render.yaml")


def _banister_flag_for_prd(render_doc: dict) -> str | None:
    """Return the BANISTER_REFIT_ENABLED value for PRD, or None if absent."""
    prd = _prd_service(render_doc)
    for entry in prd.get("envVars", []):
        if entry.get("key") == "BANISTER_REFIT_ENABLED":
            return str(entry.get("value", ""))
    return None  # absent → defaults to "1" at runtime


# ---------------------------------------------------------------------------
# Test 1 — render.yaml must not disable PRD Banister refit without a PRD worker
# ---------------------------------------------------------------------------

def test_render_yaml_prd_banister_not_silently_disabled():
    """BANISTER_REFIT_ENABLED must not be "0" for perf-coach-prd.

    Setting it to "0" assumes a PRD worker is running; if none is deployed the
    refit silently stops for production athletes (regression from current
    behavior). The value should be "1" (or absent, which also defaults to "1")
    until a PRD worker is confirmed live — at which point it can be switched to
    "0" via the Render dashboard.
    """
    doc = yaml.safe_load(RENDER_YAML.read_text())
    flag = _banister_flag_for_prd(doc)
    assert flag != "0", (
        "render.yaml sets BANISTER_REFIT_ENABLED=\"0\" for perf-coach-prd. "
        "This disables the fallback in-process Banister refit on the PRD web "
        "dyno without a confirmed PRD worker running — a silent regression for "
        "production athletes. Set it to \"1\" (or remove the entry) until a PRD "
        "worker is stood up and verified. See docs/worker.md § Live PRD runbook."
    )


# ---------------------------------------------------------------------------
# Test 2 — docs/worker.md must contain a PRD runbook section
# ---------------------------------------------------------------------------

def test_worker_md_has_prd_runbook_section():
    """docs/worker.md must have a clearly labelled PRD runbook.

    The UAT runbook already exists (§ Live UAT runbook). The PRD equivalent
    must be present so operators know how to stand up the PRD worker on
    zeal-server and what env vars to set before flipping BANISTER_REFIT_ENABLED
    to "0" in the Render dashboard.
    """
    text = WORKER_MD.read_text()
    assert "Live PRD runbook" in text, (
        "docs/worker.md is missing a 'Live PRD runbook' section. "
        "Add a PRD equivalent of the existing '### Live UAT runbook' block, "
        "covering the clone path, port, DATABASE_URL_PRD, launchd service "
        "name, and the step to flip BANISTER_REFIT_ENABLED to \"0\" in Render "
        "once the worker is verified running."
    )


# ---------------------------------------------------------------------------
# Test 3 — docs/release-process.md must include a worker verification step
# ---------------------------------------------------------------------------

def test_release_process_md_mentions_worker_check():
    """docs/release-process.md must include a pre-deploy worker verification step.

    The current release flow (7 steps) never mentions the compute worker.
    After this fix it must tell the release operator to verify the PRD worker
    is running (or confirm BANISTER_REFIT_ENABLED=1) before clicking
    'Manual Deploy' in the Render dashboard.
    """
    text = RELEASE_MD.read_text()
    assert "worker" in text.lower(), (
        "docs/release-process.md never mentions the compute worker. "
        "Add a pre-deploy step that tells the operator to verify the PRD "
        "worker is running (curl the /internal/health endpoint) or confirm "
        "BANISTER_REFIT_ENABLED=1 in the Render dashboard before deploying."
    )
    # Must be more than a passing mention — look for a concrete action
    worker_lines = [ln for ln in text.splitlines() if "worker" in ln.lower()]
    assert any(
        any(kw in ln.lower() for kw in ("verify", "check", "confirm", "health", "running"))
        for ln in worker_lines
    ), (
        "docs/release-process.md mentions 'worker' but does not include an "
        "actionable verification step (verify/check/confirm/health/running). "
        "Add a concrete step the operator can execute before deploying."
    )
