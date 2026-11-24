from datetime import datetime, timedelta, timezone

from backend.services.sync_provider_status import dot_state


def test_dot_green_under_48h():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    p = {
        "connected": True,
        "last_success_at": (now - timedelta(hours=6)).isoformat(),
        "last_error": None,
    }
    assert dot_state(p, now=now) == "green"


def test_dot_amber_when_stale():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    p = {
        "connected": True,
        "last_success_at": (now - timedelta(hours=72)).isoformat(),
        "last_error": None,
    }
    assert dot_state(p, now=now) == "amber"


def test_dot_red_on_error_or_disconnect():
    now = datetime.now(timezone.utc)
    assert dot_state({"connected": False}, now=now) == "red"
    assert dot_state({"connected": True, "last_error": "boom"}, now=now) == "red"