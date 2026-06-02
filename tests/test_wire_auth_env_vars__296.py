"""Tests for issue #296: wire SESSION_SECRET, ADMIN_SECRET_*, GOOGLE_LOGIN_ENABLED.

Verifies .env.example and render.yaml declare all required env vars correctly
without committing any real secret values.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent


# ── .env.example checks ──────────────────────────────────────────────────────

def _env_example_lines():
    return (ROOT / ".env.example").read_text().splitlines()


def _env_example_text():
    return (ROOT / ".env.example").read_text()


def test_env_example_has_session_secret():
    lines = _env_example_lines()
    active = [l for l in lines if l.startswith("SESSION_SECRET=")]
    assert active, "SESSION_SECRET= not found in .env.example"
    assert "change-me" in active[0], f"Expected placeholder value, got: {active[0]}"


def test_env_example_has_admin_secret_uat():
    lines = _env_example_lines()
    active = [l for l in lines if l.startswith("ADMIN_SECRET_UAT=")]
    assert active, "ADMIN_SECRET_UAT= not found as active line in .env.example"
    assert "change-me" in active[0], f"Expected placeholder value, got: {active[0]}"


def test_env_example_has_admin_secret_prd():
    text = _env_example_text()
    assert "ADMIN_SECRET_PRD" in text, "ADMIN_SECRET_PRD not mentioned in .env.example"


def test_env_example_has_google_login_enabled():
    lines = _env_example_lines()
    active = [l for l in lines if l.startswith("GOOGLE_LOGIN_ENABLED=")]
    assert active, "GOOGLE_LOGIN_ENABLED= not found in .env.example"


def test_env_example_has_render_dashboard_comments():
    text = _env_example_text()
    assert "Render dashboard" in text, ".env.example missing Render dashboard guidance comment"


def test_env_example_no_real_secrets():
    text = _env_example_text()
    # Must not contain anything that looks like a real secret (long hex/base64 token)
    suspicious = re.findall(r'(?:SESSION_SECRET|ADMIN_SECRET_(?:UAT|PRD))=([A-Za-z0-9+/=_\-]{32,})', text)
    placeholders = {"change-me"}
    real = [v for v in suspicious if v not in placeholders and not v.startswith("change")]
    assert not real, f"Possible real secret value in .env.example: {real}"


# ── render.yaml checks ───────────────────────────────────────────────────────

def _render_yaml():
    return yaml.safe_load((ROOT / "render.yaml").read_text())


def _service(name):
    data = _render_yaml()
    for svc in data.get("services", []):
        if svc.get("name") == name:
            return svc
    return None


def _env_var(svc, key):
    for ev in svc.get("envVars", []):
        if ev.get("key") == key:
            return ev
    return None


def test_render_uat_session_secret_sync_false():
    svc = _service("perf-coach-uat")
    assert svc, "perf-coach-uat service not found in render.yaml"
    ev = _env_var(svc, "SESSION_SECRET")
    assert ev, "SESSION_SECRET not in perf-coach-uat envVars"
    assert ev.get("sync") is False, "SESSION_SECRET must have sync: false on UAT service"


def test_render_prd_session_secret_sync_false():
    svc = _service("perf-coach-prd")
    assert svc, "perf-coach-prd service not found in render.yaml"
    ev = _env_var(svc, "SESSION_SECRET")
    assert ev, "SESSION_SECRET not in perf-coach-prd envVars"
    assert ev.get("sync") is False, "SESSION_SECRET must have sync: false on PRD service"


def test_render_uat_admin_secret_uat_sync_false():
    svc = _service("perf-coach-uat")
    ev = _env_var(svc, "ADMIN_SECRET_UAT")
    assert ev, "ADMIN_SECRET_UAT not in perf-coach-uat envVars"
    assert ev.get("sync") is False, "ADMIN_SECRET_UAT must have sync: false on UAT service"


def test_render_prd_admin_secret_prd_sync_false():
    svc = _service("perf-coach-prd")
    ev = _env_var(svc, "ADMIN_SECRET_PRD")
    assert ev, "ADMIN_SECRET_PRD not in perf-coach-prd envVars"
    assert ev.get("sync") is False, "ADMIN_SECRET_PRD must have sync: false on PRD service"


def test_render_uat_no_wrong_admin_secret():
    svc = _service("perf-coach-uat")
    ev = _env_var(svc, "ADMIN_SECRET_PRD")
    assert ev is None, "UAT service must not declare ADMIN_SECRET_PRD"


def test_render_prd_no_wrong_admin_secret():
    svc = _service("perf-coach-prd")
    ev = _env_var(svc, "ADMIN_SECRET_UAT")
    assert ev is None, "PRD service must not declare ADMIN_SECRET_UAT"


def test_render_uat_google_login_plain_value():
    svc = _service("perf-coach-uat")
    ev = _env_var(svc, "GOOGLE_LOGIN_ENABLED")
    assert ev, "GOOGLE_LOGIN_ENABLED not in perf-coach-uat envVars"
    assert "value" in ev, "GOOGLE_LOGIN_ENABLED must be a plain env var (not sync: false)"
    assert ev.get("sync") is None, "GOOGLE_LOGIN_ENABLED must NOT have sync: false"


def test_render_prd_google_login_plain_value():
    svc = _service("perf-coach-prd")
    ev = _env_var(svc, "GOOGLE_LOGIN_ENABLED")
    assert ev, "GOOGLE_LOGIN_ENABLED not in perf-coach-prd envVars"
    assert "value" in ev, "GOOGLE_LOGIN_ENABLED must be a plain env var (not sync: false)"
    assert ev.get("sync") is None, "GOOGLE_LOGIN_ENABLED must NOT have sync: false"


def test_render_yaml_no_real_secrets():
    text = (ROOT / "render.yaml").read_text()
    suspicious = re.findall(
        r'(?:SESSION_SECRET|ADMIN_SECRET_(?:UAT|PRD)):\s*([A-Za-z0-9+/=_\-]{16,})',
        text,
    )
    assert not suspicious, f"Possible real secret value in render.yaml: {suspicious}"
