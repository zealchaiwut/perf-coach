"""Tests for issue #201 — refresh_token_if_needed returns None (not NoResultFound) when no token row."""

from unittest.mock import MagicMock, patch

from backend.services.strava import refresh_token_if_needed


# ── 1. Returns None when no StravaToken row exists ────────────────────────────

def test_refresh_token_if_needed_returns_none_when_no_token_row():
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

    with patch("backend.services.strava.Session", return_value=mock_session), \
         patch("backend.services.strava._call_strava_refresh") as mock_refresh:
        result = refresh_token_if_needed("user-with-no-strava-token")

    assert result is None
    mock_refresh.assert_not_called()
    mock_session.commit.assert_not_called()


# ── 2. Uses one_or_none (not one) — no NoResultFound on missing row ───────────

def test_refresh_token_if_needed_uses_one_or_none():
    """Verify .one_or_none() is called so SQLAlchemy never raises NoResultFound."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

    with patch("backend.services.strava.Session", return_value=mock_session):
        refresh_token_if_needed("ghost-user")

    mock_session.query.return_value.filter.return_value.one_or_none.assert_called_once()
    mock_session.query.return_value.filter.return_value.one.assert_not_called()


# ── 3. Return type annotation is str | None ───────────────────────────────────

def test_refresh_token_if_needed_return_annotation():
    import inspect
    hints = inspect.get_annotations(refresh_token_if_needed)
    assert hints.get("return") in (str | None, "str | None"), (
        "return annotation must be str | None"
    )
