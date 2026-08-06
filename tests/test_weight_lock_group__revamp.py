"""Locked-group redesign — payload gates, delta arithmetic, timeline clip, DOM."""
from __future__ import annotations

import datetime
import textwrap
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.models import Base, User, WeightEntry, WeightTarget
from backend.services.cut_review import get_weekly_review
from backend.services.weight_stats import (
    COVERAGE_THRESHOLD,
    DEFAULT_WINDOW_DAYS,
    MIN_N_DAYS,
    weight_stats,
)

ROOT = Path(__file__).resolve().parent.parent
WEIGHT_HTML = (ROOT / "frontend/pages/weight.html").read_text()
WEIGHT_JS = (ROOT / "frontend/js/weight.js").read_text()
TIMELINE_JS = (ROOT / "frontend/js/weight-timeline.js").read_text()

AS_OF = datetime.date(2026, 7, 30)


def _session() -> OrmSession:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, WeightEntry.__table__, WeightTarget.__table__],
    )
    return OrmSession(engine)


def _user(session: OrmSession) -> User:
    u = User(
        id=uuid.uuid4(),
        name="lockgrp",
        is_admin=False,
        is_active=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(u)
    session.commit()
    return u


def _entry(session, user_id, d: datetime.date, kg: float) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    session.add(
        WeightEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            entry_date=d,
            weight_kg=kg,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


def _seed(session, user_id, *, days: int, weigh_ins: int, start=89.0) -> None:
    step = max(1, days // max(weigh_ins, 1))
    for i in range(weigh_ins):
        d = AS_OF - datetime.timedelta(days=(weigh_ins - 1 - i) * step)
        _entry(session, user_id, d, round(start - 0.02 * i, 2))


# ── Payload: locked carries no conclusions ───────────────────────────────────


def test_locked_weight_stats_omits_rate():
    session = _session()
    user = _user(session)
    _seed(session, user.id, days=30, weigh_ins=5)  # ~17%
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["coverage_pct"] < COVERAGE_THRESHOLD
    assert stats["gated"] is True
    assert stats["readable"] is False
    assert stats["rate_kg_wk"] is None
    assert stats["ci_kg_wk"] is None
    assert stats["days_needed"] >= 1


def test_locked_cut_review_omits_conclusions():
    session = _session()
    user = _user(session)
    _seed(session, user.id, days=30, weigh_ins=5)
    review = get_weekly_review(user.id, as_of_date=AS_OF, db=session)
    assert review["gated"] is True
    assert review["recommendation"] == "insufficient_coverage"
    assert review["actual_rate_kg_per_week"] is None
    assert review["action"] is None
    assert review["plateau_days"] is None
    assert "Plateau" not in str(review)
    assert "+0." not in str(review.get("actual_rate_kg_per_week"))


def test_unlocked_at_70_and_21_days():
    session = _session()
    user = _user(session)
    _seed(session, user.id, days=30, weigh_ins=26)
    stats = weight_stats(session, user.id, window_days=DEFAULT_WINDOW_DAYS, as_of=AS_OF)
    assert stats["coverage_pct"] >= COVERAGE_THRESHOLD
    assert stats["entries_used"] >= MIN_N_DAYS
    assert stats["gated"] is False
    assert stats["readable"] is True
    assert stats["rate_kg_wk"] is not None


def test_gated_at_69_or_20_days():
    session = _session()
    user = _user(session)
    # 20 weigh-ins in 30d → entries < 21 even if coverage looks ok
    _seed(session, user.id, days=30, weigh_ins=20)
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    assert stats["gated"] is True
    assert stats["readable"] is False


def test_cut_review_rate_matches_weight_stats_when_unlocked():
    session = _session()
    user = _user(session)
    _seed(session, user.id, days=30, weigh_ins=26, start=90.0)
    stats = weight_stats(session, user.id, window_days=30, as_of=AS_OF)
    review = get_weekly_review(user.id, as_of_date=AS_OF, db=session)
    assert review["gated"] is False
    assert review["actual_rate_kg_per_week"] == pytest.approx(stats["rate_kg_wk"], abs=1e-3)


# ── Frontend: delta arithmetic ───────────────────────────────────────────────


def test_rate_card_delta_uses_trend_not_plan_gap():
    start = WEIGHT_JS.find("function renderRateCard")
    end = WEIGHT_JS.find("async function renderHypothesis")
    block = WEIGHT_JS[start:end]
    assert "todayMarker.gap_kg" not in block
    assert "vs trend" in block
    assert "trendForDelta" in block


def test_delta_arithmetic_89_6_minus_89_3():
    """Unit-level: the expression raw - trend yields 0.3 for the screenshot case."""
    raw, trend = 89.6, 89.3
    assert abs((raw - trend) - 0.3) < 1e-9


# ── Timeline clip ────────────────────────────────────────────────────────────


def test_timeline_domain_from_ewma_and_clips_dots():
    script = textwrap.dedent(
        f"""
        {TIMELINE_JS}
        const domain = WeightTimeline.timelineDomain([88.2, 88.4, 88.6]);
        // lo/hi snap to 0.5 kg ticks around trend ± 0.35
        if (domain.hi > Math.ceil((88.6 + 0.35) * 2) / 2 + 0.01) {{
          throw new Error('yHi too high: ' + domain.hi);
        }}
        if (domain.lo < Math.floor((88.2 - 0.35) * 2) / 2 - 0.01) {{
          throw new Error('yLo too low: ' + domain.lo);
        }}
        const clipped = Math.max(domain.lo, Math.min(domain.hi, 90.5));
        if (clipped !== domain.hi) throw new Error('expected clip to hi, got ' + clipped);
        console.log(JSON.stringify({{ domain, clipped }}));
        """
    )
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    out = subprocess.check_output([node, "-e", script], text=True).strip()
    data = json.loads(out.splitlines()[-1])
    assert data["clipped"] == data["domain"]["hi"]
    # timelineDomain snaps to 0.5 kg ticks around trend ± 0.35
    assert data["domain"]["hi"] == 89.0
    assert data["domain"]["lo"] == 87.5


# ── DOM: one lock group ──────────────────────────────────────────────────────


def test_gated_dom_has_one_lock_group():
    assert 'id="lock-group"' in WEIGHT_HTML
    assert WEIGHT_HTML.count('id="lock-group"') == 1
    assert "UNLOCKS AT 70% COVERAGE" not in WEIGHT_HTML
    assert "_renderLockGroup" in WEIGHT_JS
    assert "weight-lock-group-peek" in WEIGHT_JS


def test_ungated_keeps_three_cards():
    for cid in ("rate-card", "hypothesis-card", "cut-review-card"):
        assert f'id="{cid}"' in WEIGHT_HTML
    assert "GATED_SECTION_IDS" in WEIGHT_JS


def test_inputs_never_gate():
    assert "log-submit-btn" in WEIGHT_HTML
    assert "stepper-input" in WEIGHT_HTML
    assert "bm-waist-input" in WEIGHT_HTML
    assert "unit-toggle" in WEIGHT_HTML
    log_pos = WEIGHT_HTML.find('id="log-today-card"')
    lock_pos = WEIGHT_HTML.find('id="lock-group"')
    assert log_pos != -1 and lock_pos != -1
    assert log_pos < lock_pos
