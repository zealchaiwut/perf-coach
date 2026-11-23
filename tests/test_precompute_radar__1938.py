"""Issue #1938 — worker precompute stores derived:radar / score_cards for cache hits."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.services import precompute
from backend.services import radar_cache as rc
from backend.services.derived_cache import DERIVED_SCORE_CARDS
from backend.services.sync_runner import _post_sync_warm

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)


def _mem_cache():
    store: dict = {}

    def fake_get(user_id, key, sig):
        return store.get((str(user_id), key, sig))

    def fake_put(user_id, key, sig, payload):
        store[(str(user_id), key, sig)] = payload

    return store, fake_get, fake_put


def test_warm_v2_derived_then_get_radar_payload_skips_build():
    store, fake_get, fake_put = _mem_cache()
    fake_s = MagicMock()
    fake_s.__enter__.return_value = fake_s
    fake_s.__exit__.return_value = False
    payload = {"axes": [{"axis": "economy", "focus": False}]}
    build = MagicMock(return_value=payload)
    with (
        patch("sqlalchemy.orm.Session", return_value=fake_s),
        patch("backend.services.derived_cache.get_data_version", return_value=1),
        patch("backend.services.derived_cache.summary_cache_get", side_effect=fake_get),
        patch("backend.services.derived_cache.summary_cache_put", side_effect=fake_put),
        patch("backend.services.radar_payload.build_radar", build),
        patch("backend.services.axis_snapshot.snapshot_user"),
        patch("backend.services.score_cards.build_cards", return_value={"cards": []}),
        patch("backend.services.race_hero.build_hero", return_value={}),
        patch("backend.services.projection_view.build_projection", return_value={}),
        patch("backend.services.race_list.build_race_list", return_value={}),
        patch("backend.services.revamp_home.home_payload", return_value={}),
    ):
        out = precompute._warm_v2_derived(str(UID), TODAY)
        assert "radar" in out["warmed"]
        assert "score_cards" in out["warmed"]
        assert build.call_count == 1
        rc.get_radar_payload(fake_s, UID, TODAY)
        assert build.call_count == 1
    assert store[(str(UID), rc.DERIVED_RADAR_KEY, "dv:1|2026-11-23")] == payload
    assert (str(UID), DERIVED_SCORE_CARDS, "dv:1|2026-11-23") in store


def test_post_sync_precompute_failure_does_not_fail_sync():
    with (
        patch("backend.services.data_version.bump_data_version"),
        patch("backend.services.precompute.precompute_user", side_effect=RuntimeError("boom")),
        patch("backend.db.engine", MagicMock()),
        patch("sqlalchemy.orm.Session") as sess,
    ):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.__exit__.return_value = False
        sess.return_value = fake
        _post_sync_warm(str(UID))


def test_worker_registers_precompute_nightly_job():
    src = Path("backend/worker_app.py").read_text()
    assert '"precompute_nightly": _h_precompute_nightly' in src
    assert "precompute_nightly:" in src


def test_h_precompute_passes_v2():
    import backend.worker_app as w

    with patch.object(precompute, "precompute_user") as mock_pc:
        w._h_precompute({"user_id": "u1", "dates": ["2026-01-01"]})
    mock_pc.assert_called_once_with("u1", dates=["2026-01-01"], v2=True)
