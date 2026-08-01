"""Coach export — the paste blob's structural contract.

The blob is what actually reaches a fresh Claude session, so these are the
properties that break the whole feature if they regress:

- the template is read BEFORE the data (instructions first, payload last);
- the payload survives a round trip through the fence, so a model that splits on
  `````json`` gets valid JSON back;
- ``PROMPT_VERSION`` and ``schema_version`` are both present and paired;
- every field the template names by path exists in a freshly built payload —
  a template that references a field the payload no longer carries is a live
  bug, not a typo (spec §4).
- session rows render as ONE line each, which is the whole reason the renderer
  isn't plain ``json.dumps(indent=2)``.
"""
from __future__ import annotations

import json
import re

import pytest

from backend.services import coach_export as ce


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _minimal_payload() -> dict:
    """A payload with the null shape of every block — the empty-state export."""
    return {
        "meta": {
            "schema_version": ce.SCHEMA_VERSION,
            "prompt_version": ce.PROMPT_VERSION,
            "generated_at": "2026-07-30T07:15:00+07:00",
            "timezone": "Asia/Bangkok",
            "window_days": 90,
            "previous_export_date": None,
            "data_freshness": {"last_workout_date": None, "last_weigh_in": None},
            "note": ce._META_NOTE,
            "acwr_null_note": ce._ACWR_NULL_NOTE,
            "degraded": [],
        },
        "athlete": dict(ce._NULL_ATHLETE),
        "goal": dict(ce._NULL_GOAL),
        "constraints": dict(ce._NULL_CONSTRAINTS),
        "fitness": dict(ce._NULL_FITNESS),
        "performance": {
            "state": "scored",
            "endurance": dict(ce._NULL_SCORE),
            "speed": dict(ce._NULL_SCORE),
        },
        "body": dict(ce._NULL_BODY),
        "training": {
            "weekly_rollups": [],
            "skipped_planned": [],
            "sessions": [
                {
                    "date": "2026-07-25",
                    "dow": "Sat",
                    "type": "run",
                    "name": "Moderate long run",
                    "duration_min": 118,
                    "tss": 97,
                    "distance_km": 15.1,
                    "avg_pace_per_km": "7:49",
                    "avg_hr": 146,
                    "zone2_min": 118,
                },
                {
                    "date": "2026-07-27",
                    "dow": "Mon",
                    "type": "strength",
                    "name": "Lower body",
                    "duration_min": 46,
                    "tss": 30,
                    "exercises": 6,
                },
            ],
        },
        "races": dict(ce._NULL_RACES),
        "habits": dict(ce._NULL_HABITS),
        "plan": dict(ce._NULL_PLAN),
        "findings": [],
    }


def _populated_payload() -> dict:
    """Same shape with a race and a body target set, so the nested paths the
    template names (``goal.race.current_estimate`` …) are addressable."""
    payload = _minimal_payload()
    payload["goal"]["race"] = {
        "name": "Chiang Mai Half",
        "distance": "half",
        "distance_km": 21.0975,
        "date": "2026-11-15",
        "weeks_out": 15.3,
        "goal_time": "1:45:00",
        "current_estimate": "1:49:12",
        "estimate_band_min": 3.4,
        "estimate_source": "race_readiness_projection",
    }
    payload["goal"]["body"] = {
        "target_kg": 72.0,
        "target_date": "2026-11-01",
        "needed_rate_kg_per_week": -0.35,
        "intent": "lose",
    }
    return payload


@pytest.fixture
def blob() -> str:
    return ce.build_paste_blob(_minimal_payload())


def _fenced_json(blob_text: str) -> dict:
    body = blob_text.split("```json", 1)[1].rsplit("```", 1)[0]
    return json.loads(body)


# ── Template before data ─────────────────────────────────────────────────────

def test_template_appears_before_the_data(blob):
    """Rules must be read before the payload, or rule 1 can't bind."""
    assert blob.index("## Rules") < blob.index("## My data") < blob.index("```json")


def test_blob_starts_with_the_template_not_the_payload(blob):
    assert blob.startswith("# Daily coach message")


# ── Round trip ───────────────────────────────────────────────────────────────

def test_payload_parses_back_after_splitting_on_the_fence(blob):
    assert _fenced_json(blob) == _minimal_payload()


def test_exactly_one_json_fence(blob):
    """A second fence would make "split on the fence" ambiguous."""
    assert blob.count("```json") == 1
    assert blob.count("```") == 2


# ── Versions ─────────────────────────────────────────────────────────────────

def test_prompt_version_and_schema_version_both_present(blob):
    assert ce.PROMPT_VERSION in blob
    assert f"schema v{ce.SCHEMA_VERSION}" in blob
    payload = _fenced_json(blob)
    assert payload["meta"]["schema_version"] == ce.SCHEMA_VERSION
    assert payload["meta"]["prompt_version"] == ce.PROMPT_VERSION


# ── Template carries behaviour, not facts ────────────────────────────────────

def test_template_contains_no_athlete_facts():
    """Identity lives in the JSON. A number in the template goes stale silently —
    nothing recomputes it when the athlete changes.

    Single digits are the rule and section enumeration ("1.", "2." …). Anything
    with two digits or a decimal point is a quantity — a threshold, a pace, a
    mass, a distance — and belongs in the payload.
    """
    facts = re.findall(r"\b\d{2,}(?:\.\d+)?\b|\b\d+\.\d+\b", ce.PROMPT_TEMPLATE)
    assert facts == [], f"numeric facts leaked into the prompt template: {facts}"


def test_template_states_the_canonical_rule_first():
    rules = ce.PROMPT_TEMPLATE.split("## Rules", 1)[1]
    first_rule = rules.split("2. **", 1)[0]
    assert "canonical" in first_rule
    assert "training.sessions" in first_rule


def test_template_names_all_four_sections():
    for section in ("**Today**", "**This week**", "**Body**", "**Season check**"):
        assert section in ce.PROMPT_TEMPLATE


# ── Template ↔ payload field parity ──────────────────────────────────────────

# Dotted paths the template instructs the reader to consult. Each must resolve
# in a freshly built payload; a rename on either side fails here.
_REFERENCED_PATHS = (
    "athlete",
    "goal",
    "goal.body",
    "goal.race",
    "goal.race.current_estimate",
    "goal.race.goal_time",
    "constraints.acwr_ceiling_weekly_tss",
    "constraints.current_verdict",
    "constraints.ea_floor_kcal_rest_day",
    "constraints.max_deficit_kcal_per_day",
    "fitness.tsb",
    "performance",
    "body.state",
    "body.readable",
    "plan.today",
    "plan.week",
    "plan.week_planned_tss",
    "plan.week_logged_tss_so_far",
    "meta.previous_export_date",
)


def _resolve(payload: dict, path: str):
    node = payload
    for part in path.split("."):
        assert isinstance(node, dict), f"{path}: {part} is not addressable"
        assert part in node, f"payload is missing {path}"
        node = node[part]
    return node


@pytest.mark.parametrize("path", _REFERENCED_PATHS)
def test_every_path_the_template_names_exists_in_the_payload(path):
    _resolve(_populated_payload(), path)
    assert path in ce.PROMPT_TEMPLATE, (
        f"{path} is asserted as referenced but no longer appears in the template"
    )


def test_nested_goal_paths_are_absent_not_missing_when_no_race_is_set():
    """With no race the block is None, not a dict of nulls — the template's rule
    2 ("null means unknown") is what covers this case, not a fake race object."""
    assert _minimal_payload()["goal"]["race"] is None


def test_template_references_no_unknown_payload_paths():
    """Catch the reverse drift: a backticked `block.field` in the template that
    the payload does not carry."""
    payload = _populated_payload()
    top_level = set(payload)
    for match in re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", ce.PROMPT_TEMPLATE):
        head = match.split(".", 1)[0]
        if head not in top_level:
            continue  # e.g. `training.sessions` prose about a nested list
        node = payload
        for part in match.split("."):
            if isinstance(node, list):
                break  # list-element field, not addressable on an empty list
            assert isinstance(node, dict) and part in node, (
                f"template references `{match}` which the payload does not carry"
            )
            node = node[part]


# ── One-line session rows ────────────────────────────────────────────────────

def test_session_rows_render_one_per_line(blob):
    sessions = _minimal_payload()["training"]["sessions"]
    lines = [ln.strip().rstrip(",") for ln in blob.splitlines()]
    for row in sessions:
        expected = json.dumps(row, ensure_ascii=False, separators=(", ", ": "))
        assert expected in lines, f"session row was not rendered on one line: {row}"


def test_nested_blocks_still_render_indented(blob):
    """Compaction applies to leaf objects only — the block structure has to stay
    skimmable or the reader can't find `constraints` at a glance."""
    assert '\n  "training": {' in blob
    assert '\n    "sessions": [' in blob


def test_empty_containers_render_compactly(blob):
    assert '"findings": []' in blob
    assert '"skipped_planned": []' in blob


# ── Renderer unit behaviour ──────────────────────────────────────────────────

def test_render_json_compacts_leaf_dicts_but_not_parents():
    out = ce._render_json({"leaf": {"a": 1, "b": "x"}, "parent": {"child": {"a": 1}}})
    assert '"leaf": {"a": 1, "b": "x"}' in out
    assert '"parent": {\n' in out


def test_render_json_is_valid_json_for_nested_structures():
    value = {
        "a": [{"x": 1}, {"x": 2}],
        "b": {"c": [1, 2, 3], "d": {"e": None, "f": [{"g": True}]}},
    }
    assert json.loads(ce._render_json(value)) == value


def test_render_json_escapes_non_ascii_safely():
    value = {"note": 'quote " and ünicode', "list": ["a\nb"]}
    assert json.loads(ce._render_json(value)) == value
