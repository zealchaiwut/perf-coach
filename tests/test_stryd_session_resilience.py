"""Stryd session refresh must not delete credentials on transient errors."""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import urllib.error

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import stryd_sync
from backend.services.stryd import (
    StrydAuthError,
    StrydUnavailable,
    refresh_stryd_session_if_needed,
)
from fastapi.testclient import TestClient

UID = uuid.uuid4()
client = TestClient(app)


def _fernet(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("STRYD_FERNET_KEY", Fernet.generate_key().decode())


def test_call_stryd_signin_401_is_stryd_auth_error():
    from backend.services.stryd import _call_stryd_signin

    http_err = urllib.error.HTTPError(
        url="https://www.stryd.com/b/email/signin",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(StrydAuthError):
            _call_stryd_signin("a@b.com", "wrong")


def test_call_stryd_signin_5xx_is_stryd_unavailable():
    from backend.services.stryd import _call_stryd_signin

    http_err = urllib.error.HTTPError(
        url="https://www.stryd.com/b/email/signin",
        code=502,
        msg="Bad gateway",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(StrydUnavailable):
            _call_stryd_signin("a@b.com", "pw")


def test_status_unavailable_keeps_credentials(monkeypatch, as_user):
    _fernet(monkeypatch)
    as_user(str(UID))
    cred = MagicMock()
    cred.athlete_id = 9
    cred.stryd_email = "r@example.com"
    cred.session_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    cred.auth_failed_at = None
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = cred

    with patch("backend.main.Session", return_value=mock_s), \
            patch("backend.main.refresh_stryd_session_if_needed", side_effect=StrydUnavailable("down")):
        res = client.get("/api/stryd/status")
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["status"] == "unreachable"
    mock_s.delete.assert_not_called()


def test_status_auth_error_marks_reauth_not_delete(monkeypatch, as_user):
    _fernet(monkeypatch)
    as_user(str(UID))
    cred = MagicMock()
    cred.athlete_id = 9
    cred.stryd_email = "r@example.com"
    cred.session_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    cred.auth_failed_at = None
    after = MagicMock()
    after.auth_failed_at = datetime.now(timezone.utc)
    calls = [0]

    def _session_factory(*args, **kwargs):
        s = MagicMock()
        s.__enter__ = MagicMock(return_value=s)
        s.__exit__ = MagicMock(return_value=False)
        calls[0] += 1
        s.query.return_value.filter.return_value.first.return_value = cred if calls[0] <= 2 else after
        return s

    with patch("backend.main.Session", side_effect=_session_factory), \
            patch("backend.main.refresh_stryd_session_if_needed", side_effect=StrydAuthError("bad")), \
            patch("backend.main.mark_stryd_auth_failed") as mark:
        res = client.get("/api/stryd/status")
    mark.assert_called_once()
    assert res.json()["status"] == "reauth_required"
    assert res.json()["connected"] is True


def test_calendar_401_retries_signin_once():
    user_id = str(UID)
    token = "old"
    athlete = "ath-1"
    signin_calls = [0]

    def _refresh(uid, *, force=False):
        signin_calls[0] += 1
        return "new-tok" if force or signin_calls[0] > 1 else token

    responses = [
        urllib.error.HTTPError(url="u", code=401, msg="", hdrs=None, fp=None),
        b'{"activities":[]}',
    ]
    reads = [0]

    class _Resp:
        def __init__(self, data: bytes):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._data

    def _urlopen(req, timeout=30):
        if isinstance(responses[reads[0]], bytes):
            out = _Resp(responses[reads[0]])
            reads[0] += 1
            return out
        err = responses[reads[0]]
        reads[0] += 1
        raise err

    with patch("backend.services.stryd_sync.refresh_stryd_session_if_needed", side_effect=_refresh), \
            patch("urllib.request.urlopen", side_effect=_urlopen):
        out = stryd_sync.fetch_stryd_activities(token, athlete, user_id=user_id)
    assert out == []
    assert signin_calls[0] == 2


def test_concurrent_refresh_single_signin(monkeypatch):
    _fernet(monkeypatch)
    from types import SimpleNamespace
    from backend.services import stryd as stryd_mod

    now = datetime.now(timezone.utc)
    cred = SimpleNamespace(
        stryd_email="a@b.com",
        stryd_password_encrypted="enc",
        session_token=None,
        session_token_expires_at=None,
        athlete_id=None,
        auth_failed_at=None,
        updated_at=None,
    )
    signins = [0]

    class _Q:
        def filter(self, *a, **k):
            return self

        def with_for_update(self):
            return self

        def one(self):
            return cred

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, model):
            return _Q()

        def begin(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield self

            return _cm()

        def commit(self):
            pass

    def _signin(email, password):
        signins[0] += 1
        return {"token": f"t{signins[0]}"}

    with patch.object(stryd_mod, "Session", return_value=_Sess()), \
            patch.object(stryd_mod, "decrypt_value", return_value="pw"), \
            patch.object(stryd_mod, "_call_stryd_signin", side_effect=_signin):

        def _run():
            refresh_stryd_session_if_needed(str(UID))

        t1 = threading.Thread(target=_run)
        t2 = threading.Thread(target=_run)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    assert signins[0] == 1