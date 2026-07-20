"""Unit tests for unified session-modal helpers (plan-session-helpers.js).

Mirrors duration math with plan_matching._planned_duration_seconds and covers
AI-bar dormancy / structure / source stamping predicates used by the modal.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.services.plan_matching import _planned_duration_seconds

HELPERS = Path(__file__).resolve().parents[1] / "frontend" / "js" / "lib" / "plan-session-helpers.js"


def _run_helpers(expr: str):
    """Evaluate an expression against PlanSessionHelpers in node."""
    script = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(HELPERS))}, 'utf8');
const ctx = {{ globalThis: {{}}, console }};
ctx.window = ctx.globalThis;
vm.createContext(ctx);
vm.runInContext(code, ctx);
const H = ctx.globalThis.PlanSessionHelpers;
const result = ({expr});
process.stdout.write(JSON.stringify(result));
"""
    out = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(out)


def test_duration_minutes_matches_plan_matching():
    blocks = [
        {"phase": "warmup", "duration_min": 10},
        {"phase": "main", "duration_min": 10, "repeat": 3, "rest_min": 2},
        {"phase": "cooldown", "duration_min": 8},
    ]
    # Backend: seconds; helper: minutes
    assert _planned_duration_seconds({"blocks": blocks}) == 52 * 60
    assert _run_helpers(
        "H.durationMinutesFromBlocks(" + json.dumps(blocks) + ")"
    ) == 52


def test_derive_tiles_from_blocks_when_planned_absent():
    structure = {
        "blocks": [
            {"phase": "warmup", "duration_min": 10},
            {"phase": "main", "duration_min": 10, "repeat": 3, "rest_min": 2},
            {"phase": "cooldown", "duration_min": 8},
        ]
    }
    tiles = _run_helpers("H.deriveTiles(" + json.dumps(structure) + ", {})")
    assert tiles["duration_min"] == 52
    assert tiles["target_tss"] is None
    assert tiles["distance_km"] is None


def test_derive_tiles_prefers_planned_values():
    structure = {"blocks": [{"duration_min": 30}], "duration_minutes": 30}
    tiles = _run_helpers(
        "H.deriveTiles("
        + json.dumps(structure)
        + ", {duration_minutes: 90, target_tss: 80, distance_km: 12})"
    )
    assert tiles == {"duration_min": 90, "target_tss": 80, "distance_km": 12}


def test_has_structure_and_ai_dormant():
    assert _run_helpers("H.hasStructure(null)") is False
    assert _run_helpers('H.hasStructure({focus: "legs"})') is True
    assert _run_helpers('H.hasStructure({blocks: [{duration_min: 10}]})') is True
    assert _run_helpers(
        'H.aiBarDormant({status: "done_auto", matched_workout_id: "w1"})'
    ) is True
    assert _run_helpers(
        'H.aiBarDormant({status: "planned", matched_workout_id: "w1"})'
    ) is False
    assert _run_helpers(
        'H.aiBarDormant({status: "done_manual", actual: {id: "w1"}})'
    ) is True


def test_stamp_source_user_and_snapshots():
    stamped = _run_helpers('H.stampSourceUser({blocks: [{duration_min: 10}]})')
    assert stamped["source"] == "user"
    assert stamped["blocks"][0]["duration_min"] == 10
    a = _run_helpers('H.snapshotFields({name: "A", notes: "", planned_date: "2026-07-20", session_type: "run", structure: {blocks: []}})')
    b = _run_helpers('H.snapshotFields({name: "A", notes: "", planned_date: "2026-07-20", session_type: "run", structure: {blocks: []}})')
    assert _run_helpers("H.snapshotsEqual(" + json.dumps(a) + ", " + json.dumps(b) + ")") is True
    b["name"] = "B"
    assert _run_helpers("H.snapshotsEqual(" + json.dumps(a) + ", " + json.dumps(b) + ")") is False


def test_helpers_file_exists():
    assert HELPERS.is_file()
