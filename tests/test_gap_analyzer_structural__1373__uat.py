"""UAT tests for issue #1373: Gap analyzer structural rules C.

These are lightweight integration tests that verify the rules integrate
correctly with the engine and gap_findings table.
"""
import datetime
import pytest

from backend.services.gap_analysis.engine import run_gap_analysis
from backend.services.gap_analysis.rules.recurrent_niggle_area import recurrent_niggle_area
from backend.services.gap_analysis.rules.undertrained_area_under_ramp import undertrained_area_under_ramp
from backend.services.gap_analysis.rules.strength_lapsed import strength_lapsed


def test_all_three_rules_registered():
    """AC: All three structural rules are registered in the engine."""
    from backend.services.gap_analysis.engine import _REGISTRY

    # Verify rules exist in the registry
    rule_names = [entry.fn.__name__ for entry in _REGISTRY._rules]
    assert "recurrent_niggle_area" in rule_names
    assert "undertrained_area_under_ramp" in rule_names
    assert "strength_lapsed" in rule_names


def test_recurrent_niggle_area_rule_fires():
    """AC1: recurrent_niggle_area fires when >= 2 entries within 90 days."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    inputs = {
        "week_start": week_start,
        "injury_log": [
            {
                "body_area": "left_calf",
                "severity": 1,
                "started_on": (today - datetime.timedelta(days=40)).isoformat(),
                "ended_on": None,
            },
            {
                "body_area": "right_calf",
                "severity": 1,
                "started_on": (today - datetime.timedelta(days=5)).isoformat(),
                "ended_on": None,
            },
        ],
    }

    result = recurrent_niggle_area(inputs)
    assert result is not None
    assert result.code == "recurrent_niggle_area"
    assert result.severity == 3
    assert result.target == "calf"
    assert "niggle" in result.recommendation.lower() or "recurrent" in result.recommendation.lower()


def test_undertrained_area_under_ramp_fires():
    """AC2: undertrained_area_under_ramp fires with zero volume and TSS ramp."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    # Create a muscle volume series with 4+ weeks of zero calf load
    muscle_volume = []
    for weeks_ago in [7, 6, 5, 4, 3, 2, 1, 0]:
        ws = week_start - datetime.timedelta(weeks=weeks_ago)
        muscle_volume.append({
            "week_start": ws.isoformat(),
            "muscle_group": "calf",
            "weekly_load": 0.0,
        })

    # Create TSS data that shows a ramp (> 10%)
    training_load = {
        "weekly": [
            {"week_start": (week_start - datetime.timedelta(weeks=4)).isoformat(), "running_tss": 100.0},
            {"week_start": (week_start - datetime.timedelta(weeks=3)).isoformat(), "running_tss": 110.0},
            {"week_start": (week_start - datetime.timedelta(weeks=2)).isoformat(), "running_tss": 150.0},
            {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "running_tss": 160.0},
        ],
    }

    inputs = {
        "week_start": week_start,
        "muscle_volume": muscle_volume,
        "training_load": training_load,
        "injury_log": [],  # No active injury
    }

    result = undertrained_area_under_ramp(inputs)
    assert result is not None
    assert result.code == "undertrained_area_under_ramp"
    assert result.severity == 2
    assert result.target == "calf"
    assert "reintroduce" in result.recommendation.lower()


def test_undertrained_area_suppressed_by_active_severe_injury():
    """AC4: Active severe injury suppresses loading advice for that area."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    muscle_volume = []
    for weeks_ago in [7, 6, 5, 4, 3, 2, 1, 0]:
        ws = week_start - datetime.timedelta(weeks=weeks_ago)
        muscle_volume.append({
            "week_start": ws.isoformat(),
            "muscle_group": "calf",
            "weekly_load": 0.0,
        })

    training_load = {
        "weekly": [
            {"week_start": (week_start - datetime.timedelta(weeks=4)).isoformat(), "running_tss": 100.0},
            {"week_start": (week_start - datetime.timedelta(weeks=3)).isoformat(), "running_tss": 110.0},
            {"week_start": (week_start - datetime.timedelta(weeks=2)).isoformat(), "running_tss": 150.0},
            {"week_start": (week_start - datetime.timedelta(weeks=1)).isoformat(), "running_tss": 160.0},
        ],
    }

    # Active severe calf injury (severity >= 2, ended_on=None)
    injury_log = [
        {
            "body_area": "left_calf",
            "severity": 2,
            "started_on": (today - datetime.timedelta(days=5)).isoformat(),
            "ended_on": None,  # Active
        }
    ]

    inputs = {
        "week_start": week_start,
        "muscle_volume": muscle_volume,
        "training_load": training_load,
        "injury_log": injury_log,
    }

    result = undertrained_area_under_ramp(inputs)
    assert result is not None
    assert result.code == "undertrained_area_under_ramp"
    assert result.severity == 2
    # Should surface recovery-deferring advice
    assert "defer" in result.recommendation.lower() or "recovery" in result.recommendation.lower()
    assert "reintroduce" not in result.recommendation.lower()


def test_strength_lapsed_fires():
    """AC3: strength_lapsed fires when no strength for 21+ days."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    inputs = {
        "week_start": week_start,
        "structural_dose": {
            "last_strength_days_ago": 25,  # > 21 days
            "weekly": [],
        },
        "other_findings_codes": [],  # No suppressing rules fired
    }

    result = strength_lapsed(inputs)
    assert result is not None
    assert result.code == "strength_lapsed"
    assert result.severity == 1
    assert "strength" in result.recommendation.lower()


def test_strength_lapsed_suppressed_by_niggle():
    """AC3: strength_lapsed suppressed when recurrent_niggle_area fired."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    inputs = {
        "week_start": week_start,
        "structural_dose": {
            "last_strength_days_ago": 25,
            "weekly": [],
        },
        "other_findings_codes": ["recurrent_niggle_area"],  # Suppressing rule fired
    }

    result = strength_lapsed(inputs)
    assert result is None  # Should be suppressed


def test_strength_lapsed_suppressed_by_undertrained():
    """AC3: strength_lapsed suppressed when undertrained_area_under_ramp fired."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    inputs = {
        "week_start": week_start,
        "structural_dose": {
            "last_strength_days_ago": 25,
            "weekly": [],
        },
        "other_findings_codes": ["undertrained_area_under_ramp"],  # Suppressing rule fired
    }

    result = strength_lapsed(inputs)
    assert result is None  # Should be suppressed


def test_strength_lapsed_not_suppressed_by_unrelated_rules():
    """AC3: strength_lapsed NOT suppressed by rules other than the two structural ones."""
    today = datetime.date(2026, 7, 14)
    week_start = today - datetime.timedelta(days=today.weekday())

    inputs = {
        "week_start": week_start,
        "structural_dose": {
            "last_strength_days_ago": 25,
            "weekly": [],
        },
        "other_findings_codes": ["plyo_deficit", "speed_neglected"],  # Unrelated rules
    }

    result = strength_lapsed(inputs)
    assert result is not None  # Should fire
    assert result.code == "strength_lapsed"
