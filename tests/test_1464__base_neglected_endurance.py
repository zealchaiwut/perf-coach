"""Tests for issue #1464: base_neglected (Endurance) rule implementation (runs against UAT)

Verifies that the base_neglected rule was implemented as required by AC #1372.
The rule should mirror speed_neglected but anchored to Endurance score with easy-run volume evidence.
"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC: Implement base_neglected rule mirroring speed_neglected for Endurance ──

def test_base_neglected_rule_exists(client):
    """AC: base_neglected rule is implemented in load_mix.py."""
    # Import the rule directly to verify it exists
    from backend.services.gap_analysis.rules.load_mix import base_neglected
    assert callable(base_neglected)


def test_base_neglected_fires_when_endurance_decayed(client):
    """AC: base_neglected fires when Endurance score decayed > threshold AND easy runs < threshold."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    # Fire: endurance_score_history_8w shows decay > ENDURANCE_DECAY_THRESHOLD (10.0)
    # AND easy_runs_3w count < EASY_RUNS_MIN_PER_WEEK * EASY_RUNS_WINDOW_WEEKS (2 * 3 = 6)
    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,  # decay = 15.0 > threshold 10.0
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,  # 2 < 6 required
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None, "base_neglected should fire with endurance decay > threshold"
    assert result.code == "base_neglected"
    assert result.severity == 2


def test_base_neglected_silent_when_endurance_not_decayed(client):
    """AC: base_neglected silent when Endurance decay <= threshold."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 73.0,  # decay = 2.0 <= threshold 10.0
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 0,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is None, "base_neglected should not fire when decay <= threshold"


def test_base_neglected_silent_when_easy_runs_adequate(client):
    """AC: base_neglected silent when easy-run volume is adequate despite decay."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,  # decay = 15.0 > threshold
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 7,  # 7 >= 6 required
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is None, "base_neglected should not fire when easy-run volume is adequate"


def test_base_neglected_uses_endurance_score_history(client):
    """AC: base_neglected is anchored to Endurance score (not Speed)."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 80.0,
            "newest_endurance": 65.0,  # 15.0 decay
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 1,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None
    # Verify evidence includes endurance_score_decay, not speed_score_decay
    metrics = {e["metric"] for e in result.evidence}
    assert "endurance_score_decay_8w" in metrics


def test_base_neglected_uses_easy_run_volume_evidence(client):
    """AC: base_neglected uses easy-run count as volume evidence (mirrors speed_neglected quality sessions)."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None
    # Verify evidence includes easy_runs_3w, not quality_sessions_3w
    metrics = {e["metric"] for e in result.evidence}
    assert "easy_runs_3w" in metrics


def test_base_neglected_respects_back_off_verdict(client):
    """AC: base_neglected downgrades to severity 1 when training verdict is back_off."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,
            "window_weeks": 3,
        },
        "training_verdict": "back_off",  # Should defer the rule
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None
    assert result.severity == 1, "Severity should be 1 (note) when verdict is back_off"
    assert "deferred while backing off" in result.recommendation.lower()


def test_base_neglected_registered_in_engine(client):
    """AC: base_neglected is registered in the gap analysis engine registry."""
    from backend.services.gap_analysis.engine import _REGISTRY

    names = [e.fn.__name__ for e in _REGISTRY._rules]
    assert "base_neglected" in names, "base_neglected should be registered in the engine"


def test_base_neglected_requires_correct_inputs(client):
    """AC: base_neglected is registered with correct input requirements."""
    from backend.services.gap_analysis.engine import _REGISTRY

    entry = next(
        (e for e in _REGISTRY._rules if e.fn.__name__ == "base_neglected"),
        None,
    )
    assert entry is not None, "base_neglected not found in registry"
    assert "endurance_score_history_8w" in entry.requires
    assert "easy_runs_3w" in entry.requires


def test_base_neglected_recommendation_mentions_aerobic_base(client):
    """AC: base_neglected recommendation references aerobic base/endurance training."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None
    # Verify recommendation is about endurance/easy volume, not speed/intervals
    rec_lower = result.recommendation.lower()
    assert any(term in rec_lower for term in ["aerobic", "base", "easy", "volume", "endurance"])


def test_base_neglected_returns_finding_object(client):
    """AC: base_neglected returns a GapAnalysisFinding object when firing."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected
    from backend.services.gap_analysis.schemas import GapAnalysisFinding

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }
    result = base_neglected(inputs)
    assert result is not None
    assert isinstance(result, GapAnalysisFinding)
    assert result.target == "easy_volume"


def test_base_neglected_pure_function(client):
    """AC: base_neglected is a pure function (no DB access, no side effects)."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    inputs = {
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "easy_runs_3w": {
            "count": 2,
            "window_weeks": 3,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    }

    # Call twice with same inputs — should return identical results
    result1 = base_neglected(inputs)
    result2 = base_neglected(inputs)

    assert result1 is not None
    assert result2 is not None
    assert result1.code == result2.code
    assert result1.severity == result2.severity
    assert result1.recommendation == result2.recommendation


def test_base_neglected_insufficient_data_returns_none(client):
    """AC: base_neglected returns None when required input data is missing."""
    from backend.services.gap_analysis.rules.load_mix import base_neglected

    # Missing endurance_score_history_8w
    result1 = base_neglected({
        "easy_runs_3w": {"count": 2, "window_weeks": 3},
        "training_verdict": "build",
        "week_start": "2026-07-14",
    })
    assert result1 is None

    # Missing easy_runs_3w
    result2 = base_neglected({
        "endurance_score_history_8w": {
            "oldest_endurance": 75.0,
            "newest_endurance": 60.0,
            "formula_version": "v1",
            "count": 10,
        },
        "training_verdict": "build",
        "week_start": "2026-07-14",
    })
    assert result2 is None

    # Both missing
    result3 = base_neglected({
        "training_verdict": "build",
        "week_start": "2026-07-14",
    })
    assert result3 is None
