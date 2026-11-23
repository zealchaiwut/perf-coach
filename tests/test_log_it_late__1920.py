"""Issue #1920 — Log it late prefill + match-on-save."""
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
STR_JS = (REPO / "frontend" / "js" / "v2-strength-drawer.js").read_text(encoding="utf-8")


def test_prefill_mapping_in_log_js():
    assert "function prefillFromPlanned" in LOG_JS
    assert "planned_structure" in LOG_JS
    assert "exercises_json" in LOG_JS
    assert "data-log-late" in LOG_JS
    assert "Log it late" in LOG_JS
    assert "Review in Plan" not in LOG_JS


def test_strength_drawer_matches_planned_on_create():
    assert "planned_id" in STR_JS
    assert "/api/planned-sessions/" in STR_JS
    assert "/match" in STR_JS


def test_match_endpoint_links_workout():
    uid = uuid4()
    wid = uuid4()
    pid = uuid4()
    app.dependency_overrides[resolve_user] = lambda: User(id=uid, name="t")
    planned = MagicMock()
    planned.id = pid
    planned.user_id = uid
    planned.matched_workout_id = None
    planned.status = "planned"
    workout = MagicMock()
    workout.id = wid
    workout.user_id = uid
    sess = MagicMock()
    sess.__enter__.return_value = sess
    sess.__exit__.return_value = False

    def _get(model, ident):
        if ident == wid:
            return workout
        return planned

    sess.get.side_effect = _get
    try:
        with (
            patch("backend.main.Session", return_value=sess),
            patch("backend.main._get_planned_session_or_404", return_value=planned),
            patch("backend.services.plan_match_apply.apply_planned_session_to_workout", return_value={}),
            patch("backend.services.plan_match_apply.after_match_side_effects"),
            patch("backend.main._planned_session_dict", return_value={"matched_workout_id": str(wid)}),
        ):
            r = TestClient(app).post(
                f"/api/planned-sessions/{pid}/match",
                json={"workout_id": str(wid)},
            )
        assert r.status_code == 200, r.text
        assert planned.matched_workout_id == wid
        assert planned.status == "done_manual"
    finally:
        app.dependency_overrides.pop(resolve_user, None)
