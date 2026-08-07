"""Tests for issue #1734: OAUTH_FERNET_KEY missing from render.yaml.

Verifies that render.yaml declares OAUTH_FERNET_KEY for both services with
sync: false, and that the secrets comment block documents it alongside the
generation command.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def _render_yaml():
    return yaml.safe_load((ROOT / "render.yaml").read_text())


def _render_yaml_text():
    return (ROOT / "render.yaml").read_text()


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


def test_render_uat_oauth_fernet_key_declared():
    svc = _service("perf-coach-uat")
    assert svc, "perf-coach-uat service not found in render.yaml"
    ev = _env_var(svc, "OAUTH_FERNET_KEY")
    assert ev is not None, "OAUTH_FERNET_KEY not declared in perf-coach-uat envVars"


def test_render_uat_oauth_fernet_key_sync_false():
    svc = _service("perf-coach-uat")
    ev = _env_var(svc, "OAUTH_FERNET_KEY")
    assert ev is not None, "OAUTH_FERNET_KEY not declared in perf-coach-uat envVars"
    assert ev.get("sync") is False, (
        "OAUTH_FERNET_KEY must have sync: false on perf-coach-uat "
        "(value must be set manually in the Render dashboard)"
    )


def test_render_prd_oauth_fernet_key_declared():
    svc = _service("perf-coach-prd")
    assert svc, "perf-coach-prd service not found in render.yaml"
    ev = _env_var(svc, "OAUTH_FERNET_KEY")
    assert ev is not None, "OAUTH_FERNET_KEY not declared in perf-coach-prd envVars"


def test_render_prd_oauth_fernet_key_sync_false():
    svc = _service("perf-coach-prd")
    ev = _env_var(svc, "OAUTH_FERNET_KEY")
    assert ev is not None, "OAUTH_FERNET_KEY not declared in perf-coach-prd envVars"
    assert ev.get("sync") is False, (
        "OAUTH_FERNET_KEY must have sync: false on perf-coach-prd "
        "(value must be set manually in the Render dashboard)"
    )


def test_render_yaml_comment_block_documents_oauth_fernet_key():
    text = _render_yaml_text()
    assert "OAUTH_FERNET_KEY" in text, (
        "OAUTH_FERNET_KEY not mentioned in render.yaml comment block"
    )


def test_render_yaml_comment_block_has_generation_command():
    text = _render_yaml_text()
    # The generation command for Fernet keys must appear in the comment block
    assert "Fernet.generate_key" in text, (
        "render.yaml comment block must include the Fernet key generation command "
        "so operators know how to generate OAUTH_FERNET_KEY before deploying"
    )
