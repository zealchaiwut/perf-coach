"""Issue #1821 — session_tss reader and dual-method storage."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.session_tss import (
    DEFAULT_TSS_METHOD,
    session_tss,
)


def _workout(**kwargs):
    base = {
        "tss": None,
        "tss_source": "calculated",
        "tss_method": None,
        "tss_power": 173.0,
        "tss_stryd": 129.0,
        "tss_method_override": None,
        "workout_type": "run",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _prefs(method=DEFAULT_TSS_METHOD):
    return SimpleNamespace(tss_method_default=method)


def test_dual_method_defaults_to_power():
    r = session_tss(_workout(), prefs=_prefs("power"))
    assert r["tss"] == 173.0
    assert r["method"] == "power"


def test_dual_method_user_default_stryd():
    r = session_tss(_workout(), prefs=_prefs("stryd"))
    assert r["tss"] == 129.0
    assert r["method"] == "stryd"


def test_session_override_beats_user_default():
    r = session_tss(_workout(tss_method_override="stryd"), prefs=_prefs("power"))
    assert r["tss"] == 129.0
    assert r["method"] == "stryd"


def test_single_value_power_only():
    r = session_tss(_workout(tss_stryd=None), prefs=_prefs("stryd"))
    assert r["tss"] == 173.0
    assert r["method"] == "power"


def test_single_value_stryd_only():
    r = session_tss(_workout(tss_power=None), prefs=_prefs("power"))
    assert r["tss"] == 129.0
    assert r["method"] == "stryd"


def test_manual_tss_wins():
    r = session_tss(_workout(tss=88, tss_source="manual"), prefs=_prefs("stryd"))
    assert r["tss"] == 88.0
    assert r["method"] == "manual"


def test_migration_backfill_preserves_week_total():
    """After backfill (tss_power=tss), default power keeps the same counted total."""
    old_tss = 95.0
    w = _workout(tss=old_tss, tss_power=old_tss, tss_stryd=70.0)
    total_before = float(w.tss)
    total_after = session_tss(w, prefs=_prefs("power"))["tss"]
    assert total_after == total_before


BACKEND = Path(__file__).resolve().parents[1] / "backend"
ALLOWED_DUAL_TSS_READS = {
    "services/session_tss.py",
    "services/tss.py",
    "models.py",
}


@pytest.mark.parametrize("rel", list(BACKEND.rglob("*.py")))
def test_dual_method_columns_only_read_in_reader_or_sync(rel: Path):
    """tss_power / tss_stryd attribute reads stay in the reader or sync writers."""
    try:
        rel.relative_to(BACKEND)
    except ValueError:
        pytest.skip()
    text = rel.read_text(encoding="utf-8")
    if "tss_power" not in text and "tss_stryd" not in text:
        return
    rel_key = str(rel.relative_to(BACKEND))
    if rel_key in ALLOWED_DUAL_TSS_READS:
        return
    for pat in (r"\.tss_power\b", r"\.tss_stryd\b", r"getattr\([^)]*tss_power", r"getattr\([^)]*tss_stryd"):
        if re.search(pat, text):
            pytest.fail(f"{rel_key} reads dual-method TSS columns outside reader/sync writers")