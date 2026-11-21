"""P4-5 (#1852) — mobility self-test: form validation, score math, stale chip."""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.services import axis_mobility as m

TODAY = date(2026, 11, 20)


def test_score_math():
    # ktw min(10, 12)=10 -> 83.33 ; sar (5+10)/30 = 50 ; mean 66.67 -> 67
    assert m.knee_to_wall_sub_score(10, 12) == pytest.approx(83.3333, abs=1e-3)
    assert m.sit_and_reach_sub_score(5) == 50.0
    assert m.mobility_score(10, 12, 5) == 67


def test_clamps():
    assert m.knee_to_wall_sub_score(20, 20) == 100.0
    assert m.sit_and_reach_sub_score(-20) == 0.0
    assert m.sit_and_reach_sub_score(40) == 100.0
    assert m.mobility_score(0, 0, -10) == 0
    assert m.mobility_score(30, 30, 40) == 100


def test_asymmetry_rule_uses_min_of_sides():
    assert m.mobility_score(6, 14, 5) == m.mobility_score(6, 6, 5)
    assert m.mobility_score(14, 6, 5) == m.mobility_score(6, 14, 5)
    assert m.mobility_score(6, 14, 5) < m.mobility_score(14, 14, 5)


def test_validation_ranges():
    ok = (10, 11, 5, TODAY, TODAY)
    m.validate_test_input(*ok)
    m.validate_test_input(0, 30, -20, TODAY, TODAY)
    m.validate_test_input(30, 0, 40, TODAY, TODAY)
    for args, field in [
        ((-0.1, 11, 5, TODAY, TODAY), "knee_to_wall_left_cm"),
        ((10, 30.1, 5, TODAY, TODAY), "knee_to_wall_right_cm"),
        ((10, 11, -20.1, TODAY, TODAY), "sit_and_reach_cm"),
        ((10, 11, 40.1, TODAY, TODAY), "sit_and_reach_cm"),
        ((None, 11, 5, TODAY, TODAY), "knee_to_wall_left_cm"),
        ((10, 11, 5, None, TODAY), "test_date"),
        ((10, 11, 5, TODAY + timedelta(days=1), TODAY), "test_date"),
    ]:
        with pytest.raises(m.MobilityValidationError) as e:
            m.validate_test_input(*args)
        assert e.value.field == field


def row(days_ago, l=10, r=11, s=5):
    return SimpleNamespace(
        test_date=TODAY - timedelta(days=days_ago),
        knee_to_wall_left_cm=l, knee_to_wall_right_cm=r, sit_and_reach_cm=s,
    )


def test_stale_chip_boundary_at_46_days():
    assert m.compute_mobility(row(45), TODAY)["test_due"] is False
    assert m.compute_mobility(row(45), TODAY)["stale"] is False
    out = m.compute_mobility(row(46), TODAY)
    assert out["test_due"] is True and out["stale"] is True
    assert out["score"] == m.mobility_score(10, 11, 5)  # stale keeps the score
    assert out["never_measured"] is False


def test_never_measured_without_a_test():
    out = m.compute_mobility(None, TODAY)
    assert out["score"] is None and out["never_measured"] is True and out["test_due"] is True


def test_block_has_reader_keys():
    out = m.compute_mobility(row(3), TODAY)
    for k in ("score", "delta_28d", "anchor_date", "anchor_title", "stale", "never_measured"):
        assert k in out
    assert out["anchor_date"] == (TODAY - timedelta(days=3)).isoformat()
    assert out["raw"]["knee_to_wall_min_cm"] == 10


def test_endpoints_registered_and_require_session():
    from backend.main import app
    c = TestClient(app)
    assert c.get("/api/performance/mobility-tests").status_code == 401
    assert c.post("/api/performance/mobility-tests", json={}).status_code == 401
    assert c.delete("/api/performance/mobility-tests/00000000-0000-0000-0000-000000000001").status_code == 401


def test_post_validation_returns_422_with_field_detail(monkeypatch):
    from backend.main import app
    from backend.auth import resolve_user
    from backend.models import User

    app.dependency_overrides[resolve_user] = lambda: User(id=__import__("uuid").uuid4(), name="t")
    try:
        c = TestClient(app)
        r = c.post("/api/performance/mobility-tests", json={
            "knee_to_wall_left_cm": 31, "knee_to_wall_right_cm": 10, "sit_and_reach_cm": 5})
        assert r.status_code == 422 and "knee_to_wall_left_cm" in r.json()["detail"]
        r = c.post("/api/performance/mobility-tests", json={
            "knee_to_wall_left_cm": 10, "knee_to_wall_right_cm": 10, "sit_and_reach_cm": 41})
        assert r.status_code == 422 and "sit_and_reach_cm" in r.json()["detail"]
        r = c.post("/api/performance/mobility-tests", json={
            "test_date": "nope", "knee_to_wall_left_cm": 10, "knee_to_wall_right_cm": 10, "sit_and_reach_cm": 5})
        assert r.status_code == 422
        assert c.delete("/api/performance/mobility-tests/not-a-uuid").status_code == 400
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_model_and_migration():
    from backend.models import MobilityTest
    cols = MobilityTest.__table__.columns.keys()
    for c in ("user_id", "test_date", "knee_to_wall_left_cm", "knee_to_wall_right_cm", "sit_and_reach_cm"):
        assert c in cols
    src = Path("alembic/versions/25e2032a3208_create_mobility_tests.py").read_text()
    assert "def downgrade" in src and "drop_table" in src and "table_exists" in src


def test_performance_page_wires_mobility_drawer():
    html = Path("frontend/pages/v2-performance.html").read_text(encoding="utf-8")
    js = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
    assert "v2-perf-mobility" in html and "v2-perf-drawer" in html
    assert "/api/performance/mobility-tests" in js
    assert "Log a test" in js and "mobility-test-due" in js
