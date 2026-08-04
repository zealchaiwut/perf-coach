"""Tests for issue #1582: daily coach dedupe key mismatch — post-sync / scheduled batch
can both fire generate_for_user for the same user on the same day.

AC: _run_daily_coach_batch must skip users who already have a persisted
WeeklyCoachMessage row for today — one LLM generation per user per day.
"""
import datetime
import types
import uuid
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uid():
    return uuid.uuid4()


def _make_message(uid, for_date):
    """Return a minimal WeeklyCoachMessage-like dict."""
    msg = MagicMock()
    msg.user_id = uid
    msg.for_date = for_date
    return msg


# ---------------------------------------------------------------------------
# AC1: batch skips users with persisted message for today
# ---------------------------------------------------------------------------

def test_batch_skips_user_with_existing_message_today():
    """_run_daily_coach_batch must NOT call generate_for_user for users
    that already have a WeeklyCoachMessage row for today (the batch date)."""
    import backend.worker_app as wa

    today = datetime.date(2026, 8, 3)
    uid = _make_uid()

    existing_msg = _make_message(uid, today)

    generate_calls = []

    def fake_generate(user_id, today):
        generate_calls.append(user_id)
        return {"plan_state_snapshot": {"source": "deterministic"}}

    def fake_has_message(db, uid_arg, date_arg):
        return uid_arg == uid and date_arg == today

    with (
        patch("backend.worker_app.Session") as mock_session_cls,
        patch("backend.worker_app.engine"),
        patch("backend.services.weekly_coach_message.generate_for_user", side_effect=fake_generate),
        patch("backend.worker_app.DbRecorder"),
    ):
        # Make the session query return one active user
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [(uid,)]
        mock_session.query.return_value.filter.return_value.all.return_value = [(uid,)]

        # Patch _daily_coach_message_exists to return True for this user/date
        with patch("backend.worker_app._daily_coach_message_exists", side_effect=fake_has_message):
            wa._run_daily_coach_batch(user_id=str(uid), triggered_by="post_sync", today=today)

    assert uid not in generate_calls, (
        "generate_for_user must NOT be called for a user who already has a message today"
    )


# ---------------------------------------------------------------------------
# AC2: batch generates for users without an existing message
# ---------------------------------------------------------------------------

def test_batch_generates_for_user_without_existing_message():
    """_run_daily_coach_batch MUST call generate_for_user for users that
    do NOT yet have a WeeklyCoachMessage row for today."""
    import backend.worker_app as wa

    today = datetime.date(2026, 8, 3)
    uid = _make_uid()

    generate_calls = []

    def fake_generate(user_id, today):
        generate_calls.append(user_id)
        return {"plan_state_snapshot": {"source": "deterministic"}}

    with (
        patch("backend.worker_app.Session") as mock_session_cls,
        patch("backend.worker_app.engine"),
        patch("backend.services.weekly_coach_message.generate_for_user", side_effect=fake_generate),
        patch("backend.worker_app.DbRecorder"),
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [(uid,)]
        mock_session.query.return_value.filter.return_value.all.return_value = [(uid,)]

        # No existing message
        with patch("backend.worker_app._daily_coach_message_exists", return_value=False):
            wa._run_daily_coach_batch(user_id=str(uid), triggered_by="post_sync", today=today)

    assert uid in generate_calls, (
        "generate_for_user must be called for users without a message today"
    )


# ---------------------------------------------------------------------------
# AC3: result dict marks skipped-already-generated users correctly
# ---------------------------------------------------------------------------

def test_batch_result_marks_already_generated_as_skip():
    """When a user is skipped due to an existing message, the result dict entry
    must start with 'skip' (so skip counter increments, not ok or error)."""
    import backend.worker_app as wa

    today = datetime.date(2026, 8, 3)
    uid = _make_uid()
    uid_str = str(uid)

    results_captured = {}

    original_run = wa._run_daily_coach_batch

    with (
        patch("backend.worker_app.Session") as mock_session_cls,
        patch("backend.worker_app.engine"),
        patch("backend.worker_app.DbRecorder") as mock_recorder_cls,
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [(uid,)]
        mock_session.query.return_value.filter.return_value.all.return_value = [(uid,)]

        recorder = MagicMock()
        mock_recorder_cls.return_value = recorder

        def capture_stats(*args, **kwargs):
            stats = kwargs.get("stats") or (args[1] if len(args) > 1 else None)
            if stats:
                results_captured.update(stats.get("results", {}))

        recorder.mark_success.side_effect = capture_stats

        with patch("backend.worker_app._daily_coach_message_exists", return_value=True):
            wa._run_daily_coach_batch(user_id=uid_str, triggered_by="post_sync", today=today)

    assert uid_str in results_captured, "result dict must contain the user's key"
    assert results_captured[uid_str].startswith("skip"), (
        f"Expected result to start with 'skip', got: {results_captured[uid_str]!r}"
    )


# ---------------------------------------------------------------------------
# AC4: _daily_coach_message_exists helper is importable from worker_app
# ---------------------------------------------------------------------------

def test_daily_coach_message_exists_helper_exists():
    """The helper _daily_coach_message_exists must be defined in worker_app
    so the short-circuit check has a testable boundary."""
    import backend.worker_app as wa
    assert hasattr(wa, "_daily_coach_message_exists"), (
        "_daily_coach_message_exists must be defined in backend.worker_app"
    )
    assert callable(wa._daily_coach_message_exists)


# ---------------------------------------------------------------------------
# AC5: dedupe keys use consistent per-user-per-day format
# ---------------------------------------------------------------------------

def test_enqueue_after_sync_dedupe_key_format():
    """_enqueue_daily_coach_after_sync must use daily_coach:{day}:{user_id}
    as the dedupe key (consistent with per-user semantics)."""
    import backend.worker_app as wa

    uid = str(_make_uid())
    enqueued = []

    class FakeQueue:
        def enqueue(self, job_type, payload, enqueued_by=None, dedupe_key=None):
            enqueued.append({"job_type": job_type, "dedupe_key": dedupe_key, "payload": payload})

    original_jq = wa.job_queue
    wa.job_queue = FakeQueue()
    try:
        today_str = datetime.date.today().isoformat()
        wa._enqueue_daily_coach_after_sync(uid)
    finally:
        wa.job_queue = original_jq

    assert len(enqueued) == 1
    dk = enqueued[0]["dedupe_key"]
    assert dk.startswith("daily_coach:"), f"Expected dedupe_key to start with 'daily_coach:', got {dk!r}"
    assert uid in dk, f"Expected user_id in dedupe_key, got {dk!r}"
