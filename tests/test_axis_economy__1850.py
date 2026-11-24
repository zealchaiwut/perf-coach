"""P4-3 (#1850) — economy score from Stryd form metrics."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.services import axis_economy as e
from backend.services.form_metrics_extractor import extract_form_metrics_row

AS_OF = date(2026, 11, 20)


def row(days_ago=1, *, lss=9.4, gct=248.0, fpr=0.23, power=210.0, minutes=60, z2_frac=0.8):
    return {
        "workout_date": AS_OF - timedelta(days=days_ago),
        "duration_seconds": minutes * 60,
        "zone2_minutes": int(minutes * z2_frac),
        "lss_kn_m": lss, "gct_ms": gct, "form_power_ratio": fpr, "power_w": power,
    }


def test_worked_example_exact():
    assert e.stiffness_sub_score(9.4) == pytest.approx(56.6667, abs=1e-3)
    assert e.ground_contact_sub_score(248) == pytest.approx(57.7778, abs=1e-3)
    assert e.form_power_ratio_sub_score(0.23) == pytest.approx(70.0)
    out = e.compute_economy([row(d) for d in range(1, 6)], AS_OF)
    # mean(56.667, 57.778, 70.0) = 61.48 -> 61
    assert out["score"] == 61
    assert out["never_measured"] is False
    assert out["stale"] is False


def test_sub_scores_clamped():
    assert e.stiffness_sub_score(4) == 0.0 and e.stiffness_sub_score(14) == 100.0
    assert e.ground_contact_sub_score(320) == 0.0 and e.ground_contact_sub_score(200) == 100.0
    assert e.form_power_ratio_sub_score(0.35) == 0.0 and e.form_power_ratio_sub_score(0.2) == pytest.approx(100.0)


def test_medians_over_pool():
    rows = [row(1, lss=8.0), row(2, lss=9.0), row(3, lss=20.0)]
    out = e.compute_economy(rows, AS_OF)
    assert out["raw"]["lss_kn_m"] == 9.0


def test_pool_excludes_hard_and_old_runs():
    hard = row(1, z2_frac=0.49)
    boundary = row(2, z2_frac=0.5)
    old = row(28)  # 28 days ago is outside the 28-day window (window = 27 days back)
    edge = row(27)
    future = row(-1)
    pool = e.easy_pool([hard, boundary, old, edge, future], AS_OF)
    assert boundary in pool and edge in pool
    assert hard not in pool and old not in pool and future not in pool


def test_pool_requires_form_data():
    r = row(1, lss=None, gct=None, fpr=None, power=None)
    assert e.easy_pool([r], AS_OF) == []


def test_two_sub_minimum():
    one = e.compute_economy([row(d, gct=None, fpr=None) for d in range(1, 6)], AS_OF)
    assert one["score"] is None and one["never_measured"] is True
    two = e.compute_economy([row(d, fpr=None) for d in range(1, 6)], AS_OF)
    assert two["score"] == int(round((56.6667 + 57.7778) / 2))
    assert two["sub_scores"]["form_power_ratio"] is None


def test_staleness_below_five_runs():
    out = e.compute_economy([row(d) for d in range(1, 5)], AS_OF)
    assert out["score"] == 61 and out["stale"] is True


def test_median_power_for_power_to_weight():
    assert e.median_power_w(e.easy_pool([row(1, power=200), row(2, power=220), row(3, power=300)], AS_OF)) == 220.0


def test_form_power_from_live_stryd_streams_fixture():
    import json
    from backend.services.form_metrics_extractor import form_power_w_from_streams
    from backend.services.stryd_sync import map_stryd_activity

    fixture = json.loads(Path("tests/fixtures/stryd_activity_form_power.json").read_text())
    assert "average_form_power" not in fixture and "form_power" not in fixture
    mapped = map_stryd_activity(fixture, "u")
    assert mapped["form_metrics"].get("form_power_w") is None  # calendar has no key
    assert form_power_w_from_streams(fixture) == 46.0
    r = extract_form_metrics_row(
        user_id="u", stryd_activity_pk="a", run_date=AS_OF, avg_power_w=200,
        form_metrics={"form_power_w": form_power_w_from_streams(fixture)},
    )
    assert r["form_power_ratio"] == 0.23


def test_extractor_derives_form_power_ratio():
    base = dict(user_id="u", stryd_activity_pk="a", run_date=AS_OF, avg_power_w=200)
    r = extract_form_metrics_row(form_metrics={"form_power_w": 46}, **base)
    assert r["form_power_ratio"] == 0.23
    r = extract_form_metrics_row(form_metrics={"form_power_ratio": 0.25}, **base)
    assert r["form_power_ratio"] == 0.25
    r = extract_form_metrics_row(form_metrics={"ground_contact_time_ms": 250}, **base)
    assert r["form_power_ratio"] is None
    r = extract_form_metrics_row(
        form_metrics={"form_power_w": 46, "cadence_spm": 180}, **{**base, "avg_power_w": None})
    assert r["form_power_ratio"] is None


def test_migration_and_model():
    from backend.models import RunFormMetrics
    assert "form_power_ratio" in RunFormMetrics.__table__.columns.keys()
    src = Path("alembic/versions/bf3569410f9f_run_form_metrics_form_power_ratio.py").read_text()
    assert "drop_column" in src and "column_exists" in src
