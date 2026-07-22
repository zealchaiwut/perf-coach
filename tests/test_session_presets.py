"""Unit tests for gap session presets + clamp helpers."""
from __future__ import annotations

from backend.services.gap_analysis.session_presets import (
    clamp_duration_tss,
    get_preset_for_code,
    is_incomplete_gap_session,
    materialize_planned_fields,
    presets_from_findings,
)


def test_long_run_preset_min_110():
    p = get_preset_for_code("aerobic_durability_gap", priority=2)
    assert p is not None
    assert p["constraints"]["min_duration_min"] == 110
    assert p["constraints"]["must_respect_load_ceiling"] is True


def test_hollow_gap_session_is_incomplete():
    preset = get_preset_for_code("aerobic_durability_gap")
    assert is_incomplete_gap_session({"_gap_code": "aerobic_durability_gap"}, preset)
    assert is_incomplete_gap_session({}, preset)


def test_materialized_gap_session_is_complete():
    preset = get_preset_for_code("aerobic_durability_gap")
    fields = materialize_planned_fields(preset)
    assert not is_incomplete_gap_session(fields["structure"], preset)


def test_below_floor_run_is_incomplete():
    preset = get_preset_for_code("aerobic_durability_gap")
    stub = {
        "_gap_code": "aerobic_durability_gap",
        "blocks": [{"phase": "main", "duration_min": 70, "target": "Z1-Z2"}],
        "duration_min": 70,
        "target_tss": 50,
    }
    assert is_incomplete_gap_session(stub, preset)


def test_intervals_preset_min_50():
    p = get_preset_for_code("speed_neglected")
    assert p is not None
    assert p["constraints"]["min_duration_min"] == 50


def test_plyo_preset_min_30():
    p = get_preset_for_code("plyo_deficit")
    assert p is not None
    assert p["constraints"]["min_duration_min"] == 30


def test_clamp_respects_floor_and_ceiling():
    preset = get_preset_for_code("aerobic_durability_gap")
    d, t = clamp_duration_tss(
        duration_min=40,
        tss=50,
        preset=preset,
        load_ceiling_tss=100,
    )
    assert d >= 110
    assert t >= 80
    assert t <= 100


def test_materialize_embeds_preset_meta():
    preset = get_preset_for_code("aerobic_durability_gap")
    fields = materialize_planned_fields(preset, load_ceiling_tss=200)
    assert fields["structure"]["_preset_code"] == "aerobic_durability_gap"
    assert fields["structure"]["_preset_constraints"]["min_duration_min"] == 110
    assert fields["duration_min"] >= 110


def test_presets_from_findings_skips_inactive():
    findings = [
        {"code": "aerobic_durability_gap", "severity": 2, "status": "active"},
        {"code": "plyo_deficit", "severity": 2, "status": "accepted"},
    ]
    presets = presets_from_findings(findings)
    assert len(presets) == 1
    assert presets[0]["code"] == "aerobic_durability_gap"


def test_no_preset_for_overuse():
    assert get_preset_for_code("intensity_too_hard") is None
