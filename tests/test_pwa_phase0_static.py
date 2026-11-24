"""PWA phase 0 static contracts (no live DB)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.plan_pattern_fill import fill_strength
from backend.services.plan_pattern_seeds import default_exercises, default_strength_patterns
from backend.services.session_exercises import (
    enrich_generated_exercises,
    format_exercises,
    map_generator_format,
    normalize_exercises,
    validate_sections,
)

REPO = Path(__file__).resolve().parents[1]


def test_old_sessions_load_unchanged():
    raw = [{"name": "Press", "sets": [{"kg": 40, "reps": 8}]}]
    exercises, errors = normalize_exercises(raw)
    assert not errors
    assert exercises == [{"name": "Press", "sets": [{"kg": 40, "reps": 8}]}]
    text = format_exercises(exercises)
    again, err2 = normalize_exercises(json.loads(text))
    assert not err2
    assert format_exercises(again) == text


@pytest.mark.parametrize(
    "fmt,payload",
    [
        (
            "straight",
            {"name": "Calf raise", "section_format": "straight", "sets": [{"kg": 24, "reps": 15}]},
        ),
        (
            "superset",
            {
                "name": "A1 split squat",
                "section_id": 3,
                "section_format": "superset",
                "pair_label": "A1",
                "sets": [{"kg": 22, "reps": "8/side"}],
            },
        ),
        (
            "emom",
            {
                "name": "Pogo hops",
                "section_id": 4,
                "section_format": "emom",
                "emom": {"minutes": 8, "minute_rule": "odd"},
                "sets": [{"reps": 12}],
            },
        ),
        (
            "interval",
            {
                "name": "KB swing",
                "section_format": "interval",
                "interval": {"work_seconds": 40, "rest_seconds": 20, "intervals": 6},
                "sets": [{"reps": 1}],
            },
        ),
        (
            "hold",
            {
                "name": "Hollow hold",
                "section_format": "hold",
                "hold": {"target_seconds": 45, "count_mode": "up"},
                "sets": [{"hold": "45s"}],
            },
        ),
    ],
)
def test_section_round_trip(fmt, payload):
    exercises, errors = normalize_exercises([payload])
    assert not errors, errors
    assert exercises[0]["section_format"] == payload["section_format"]
    text = format_exercises(exercises)
    again, err2 = normalize_exercises(json.loads(text))
    assert not err2
    assert again[0]["section_format"] == fmt


def test_mixed_session_round_trip():
    raw = [
        {"name": "Warm-up march", "section_id": 1, "section_format": "straight", "sets": [{"reps": 20}]},
        {
            "name": "A1 split squat",
            "section_id": 3,
            "section_format": "superset",
            "pair_label": "A1",
            "sets": [{"kg": 22, "reps": 8}],
        },
        {
            "name": "A2 calf raise",
            "section_id": 3,
            "section_format": "superset",
            "pair_label": "A2",
            "sets": [{"kg": 24, "reps": 15}],
        },
    ]
    exercises, errors = normalize_exercises(raw)
    assert not errors
    assert validate_sections(exercises) == []


def test_invalid_interval_and_emom_and_superset():
    assert validate_sections(
        [{"name": "X", "section_id": 1, "section_format": "interval", "sets": [{"reps": 1}]}]
    )
    assert validate_sections(
        [{"name": "Only one", "section_id": 2, "section_format": "superset", "pair_label": "A1", "sets": [{"reps": 1}]}]
    )
    bad_emom = [
        {"name": "Odd", "section_id": 4, "section_format": "emom", "emom": {"minutes": 8, "minute_rule": "odd"}, "sets": [{"reps": 10}]},
    ]
    errs = validate_sections(bad_emom)
    assert errs and "exactly once" in errs[0]


def test_generator_emits_valid_section_fields():
    pat = next(p for p in default_strength_patterns() if p.get("subtype") == "strength_lower")
    content = fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": "strength_lower"},
        default_exercises(),
    )
    exercises = content["exercises"]
    assert exercises
    assert all(e.get("section_format") for e in exercises)
    assert validate_sections(exercises) == []


def test_map_generator_format():
    assert map_generator_format("warmup", None) == "straight"
    assert map_generator_format("superset", None) == "superset"
    assert map_generator_format("finisher", "emom") == "emom"
    assert map_generator_format("finisher", "40_20") == "interval"
    assert map_generator_format("isometric", None) == "hold"


def test_enrich_assigns_pair_labels_and_emom_rules():
    rows = [
        {"name": "A1", "block": "Superset A", "_fmt": "superset", "_group_key": "superset", "sets": 3},
        {"name": "A2", "block": "Superset A", "_fmt": "superset", "_group_key": "superset", "sets": 3},
        {"name": "Odd", "block": "EMOM", "_fmt": "emom", "_group_key": "finisher", "sets": 8},
        {"name": "Even", "block": "EMOM", "_fmt": "emom", "_group_key": "finisher", "sets": 8},
    ]
    out = enrich_generated_exercises(rows)
    assert out[0]["pair_label"] == "A1"
    assert out[1]["pair_label"] == "A2"
    assert out[2]["emom"]["minute_rule"] == "odd"
    assert out[3]["emom"]["minute_rule"] == "even"
    assert validate_sections(out) == []


def test_bundle_shape_keys_in_source():
    src = (REPO / "backend" / "services" / "mobile_bundle.py").read_text(encoding="utf-8")
    for key in (
        '"today"',
        '"sessions"',
        '"last_numbers"',
        '"anchors"',
        '"library"',
        '"swap_history"',
        '"recent_runs"',
        '"body"',
        '"server_time"',
        '"bundle_version"',
        '"zone2_week"',
    ):
        assert key in src


def test_mobile_routes_registered():
    from backend.main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/mobile/bundle" in paths
    assert "/api/mobile/sync" in paths
    assert "/api/mobile/ping" in paths
    assert "/api/auth/remember-device" in paths
    assert "/api/mobile/devices" in paths


def test_ping_is_204():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/mobile/ping")
    assert r.status_code == 204


def test_profile_devices_markup():
    html = (REPO / "frontend" / "pages" / "v2-settings.html").read_text(encoding="utf-8")
    js = (REPO / "frontend" / "js" / "settings-profile.js").read_text(encoding="utf-8")
    assert "profile-devices" in html
    assert "Sign out device" in js
    assert "/api/mobile/devices" in js


def test_worker_schedules_mutation_cleanup():
    src = (REPO / "backend" / "worker_app.py").read_text(encoding="utf-8")
    assert "cleanup_old_mutations" in src


def test_migration_guards():
    src = (REPO / "alembic" / "versions" / "bffa23e7b071_pwa_processed_mutations_and_device_.py").read_text(
        encoding="utf-8"
    )
    assert "table_exists" in src
    assert "processed_mutations" in src
    assert "device_sessions" in src
