"""Incremental Sync new must run in-process so it works with the worker off.

Render previously pinned WEB_INCREMENTAL_SYNC_ENABLED=0. In queue mode that
enqueues a job and returns 202 even when the worker is asleep, so nothing
pulls until zeal-server is up.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = (ROOT / "render.yaml").read_text()
MAIN = (ROOT / "backend" / "main.py").read_text()


def _web_flag_values_in_render():
    blocks = re.findall(
        r"- key: WEB_INCREMENTAL_SYNC_ENABLED\s+value: \"([^\"]+)\"",
        RENDER,
    )
    return blocks


def test_render_keeps_incremental_on_the_webapp():
    values = _web_flag_values_in_render()
    assert values, "WEB_INCREMENTAL_SYNC_ENABLED missing from render.yaml"
    assert all(v == "1" for v in values), (
        "Render must set WEB_INCREMENTAL_SYNC_ENABLED=1 so Settings → Sync new "
        "runs in-process when the worker is off; got %s" % values
    )


def test_default_web_incremental_flag_is_on():
    snippet = MAIN[MAIN.find("def _web_incremental_sync_enabled") :]
    assert 'os.getenv("WEB_INCREMENTAL_SYNC_ENABLED", "1")' in snippet


def test_incremental_path_starts_inprocess_job():
    assert "_sync_jobs.start" in MAIN
    assert "_maybe_delegate_incremental" in MAIN
