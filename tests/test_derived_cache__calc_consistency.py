"""Calculation consistency: data version, derived cache, score reader as_of."""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.data_version import bump_data_version, get_data_version
from backend.services.derived_cache import derived_signature, get_or_compute
from backend.services.score_reader import get_scores


def test_bump_data_version_increments():
    user_id = uuid.uuid4()
    row = MagicMock()
    row.data_version = 3
    session = MagicMock()
    session.get.return_value = row
    assert bump_data_version(session, user_id) == 4
    assert row.data_version == 4


def test_derived_signature_includes_version():
    session = MagicMock()
    uid = uuid.uuid4()
    with patch("backend.services.derived_cache.get_data_version", return_value=7):
        sig = derived_signature(session, uid, date(2026, 11, 8))
    assert sig == "dv:7|2026-11-08"


def test_get_scores_historical_unavailable_without_snapshot():
    uid = uuid.uuid4()
    mock_session = MagicMock()
    with patch("backend.utils.time.today_bangkok", return_value=date(2026, 11, 8)), \
            patch("sqlalchemy.orm.session.Session") as sess_cls, \
            patch("backend.services.axis_snapshot.snapshot_row_on_or_before", return_value=None):
        sess_cls.return_value.__enter__.return_value = mock_session
        sess_cls.return_value.__exit__.return_value = False
        out = get_scores(uid, as_of=date(2026, 10, 1))
    assert out["state"] == "unavailable"
    assert out.get("reason")


def test_get_or_compute_calls_compute_once():
    uid = uuid.uuid4()
    session = MagicMock()
    calls = [0]
    store: dict = {}

    def compute():
        calls[0] += 1
        return {"x": 1}

    def fake_get(user_id, key, sig):
        return store.get((str(user_id), key, sig))

    def fake_put(user_id, key, sig, payload):
        store[(str(user_id), key, sig)] = payload

    with patch("backend.services.derived_cache.get_data_version", return_value=1), \
            patch("backend.services.derived_cache.summary_cache_get", side_effect=fake_get), \
            patch("backend.services.derived_cache.summary_cache_put", side_effect=fake_put):
        a = get_or_compute(session, uid, "derived:radar", date(2026, 11, 8), compute)
        b = get_or_compute(session, uid, "derived:radar", date(2026, 11, 8), compute)
    assert calls[0] == 1
    assert a == b == {"x": 1}