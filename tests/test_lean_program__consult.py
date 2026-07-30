"""Phase 0 — the consult template and volume_plays (lean-program spec §5, Appendix A).

The consult is the second template over the SAME export payload. Where the daily
message is one-way and short, this one is a dialogue that ends in a change list.
It stays paste-based permanently and by design: the judgment layer lives outside
the app (D12 — the only LLM is the consult, and it isn't in perf-coach).

What's pinned here is the behaviour the template promises, because a rule that
quietly disappears is how the coach starts recomputing CTL or inventing meal
plans:

- canonical numbers are not recomputed (rule 1, inherited from the daily template)
- constraints are never crossed (rule 2)
- a paused tracking state or an auto-paused deficit is respected, not undone
  (rules 3 and 4)
- decisions are read first (rule 7)
- food comes from ``volume_plays`` (rule 8)
"""
from __future__ import annotations

import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.services import coach_export as ce
from backend.services import pref_catalog


# ── Template shape ───────────────────────────────────────────────────────────

def test_consult_template_is_versioned_alongside_the_schema():
    assert ce.CONSULT_PROMPT_VERSION in ce.CONSULT_TEMPLATE
    assert f"schema v{ce.SCHEMA_VERSION}" in ce.CONSULT_TEMPLATE


def test_schema_and_prompt_versions_moved_together():
    """Spec §10: new payload blocks bump both. A v2 payload served with a v3
    template (or the reverse) is a bug, not a version skew to tolerate."""
    assert ce.PROMPT_VERSION.endswith(f"v{ce.SCHEMA_VERSION}")


def test_consult_template_carries_no_athlete_facts():
    """Same rule as the daily template: identity lives in the JSON. Single digits
    are the rule/step enumeration; anything larger is a quantity."""
    facts = re.findall(r"\b\d{2,}(?:\.\d+)?\b|\b\d+\.\d+\b", ce.CONSULT_TEMPLATE)
    assert facts == [], f"numeric facts leaked into the consult template: {facts}"


@pytest.mark.parametrize(
    "phrase",
    [
        "CANONICAL",
        "constraints",
        "meta.tracking_state",
        "auto_pause_active",
        "confidence interval",
        "decisions[]",
        "volume_plays[]",
        "CHANGES TO APPLY",
    ],
)
def test_consult_template_states_each_rule(phrase):
    assert phrase in ce.CONSULT_TEMPLATE


def test_consult_asks_questions_before_the_change_list():
    """Step 4 is "wait for my answers" — a consult that dumps changes without
    asking is the thing this template exists to prevent."""
    body = ce.CONSULT_TEMPLATE
    assert body.index("Ask me two or three questions") < body.index("CHANGES TO APPLY")
    assert "wait for my answers" in body


def test_consult_template_bans_moralising_about_food():
    assert "Never moralise about food" in ce.CONSULT_TEMPLATE


def test_consult_template_caps_the_change_list():
    """One or two changes, not five — a list of five is a list of none."""
    assert "One or two changes, not five" in ce.CONSULT_TEMPLATE


# ── Blob assembly ────────────────────────────────────────────────────────────

_PAYLOAD = {
    "meta": {"schema_version": ce.SCHEMA_VERSION, "tracking_state": "active"},
    "decisions": [
        {"decided_on": "2026-07-16", "raw_text": "swap the oil", "due_for_review": True}
    ],
    "volume_plays": ["oyakodon with extra cabbage", "kimchi jjigae"],
}


def test_consult_blob_is_template_then_data():
    blob = ce.build_consult_blob(_PAYLOAD)
    assert blob.startswith("# Coach consult")
    assert blob.index("## Rules") < blob.index("## My data") < blob.index("```json")


def test_consult_blob_round_trips_the_payload():
    blob = ce.build_consult_blob(_PAYLOAD)
    body = blob.split("```json", 1)[1].rsplit("```", 1)[0]
    assert json.loads(body) == _PAYLOAD


def test_consult_and_daily_blobs_share_one_payload():
    """Two templates, one export — that's the whole reason both live here."""
    daily = ce.build_paste_blob(_PAYLOAD)
    consult = ce.build_consult_blob(_PAYLOAD)
    daily_json = daily.split("```json", 1)[1].rsplit("```", 1)[0]
    consult_json = consult.split("```json", 1)[1].rsplit("```", 1)[0]
    assert json.loads(daily_json) == json.loads(consult_json)
    assert daily.split("```json")[0] != consult.split("```json")[0]


# ── volume_plays preference ──────────────────────────────────────────────────

def test_volume_plays_is_in_the_catalog_with_a_list_default():
    meta = pref_catalog.field_meta("volume_plays")
    assert meta is not None
    assert meta["type"] == "list[str]"
    assert meta["default"] == []


def test_volume_plays_accepts_a_list_of_dish_names():
    payload = pref_catalog.default_payload()
    payload["volume_plays"] = ["oyakodon", "kimchi jjigae", "tom yum with tofu"]
    assert pref_catalog.validate_payload(payload) == {}


def test_volume_plays_rejects_non_strings():
    payload = pref_catalog.default_payload()
    payload["volume_plays"] = ["oyakodon", 42]
    assert "volume_plays" in pref_catalog.validate_payload(payload)


def test_volume_plays_rejects_too_many_items():
    payload = pref_catalog.default_payload()
    payload["volume_plays"] = [f"dish {i}" for i in range(11)]
    errors = pref_catalog.validate_payload(payload)
    assert "at most 10" in errors["volume_plays"]


def test_volume_plays_rejects_an_overlong_item():
    """It's a dish name, not a recipe — a recipe database is out of scope."""
    payload = pref_catalog.default_payload()
    payload["volume_plays"] = ["x" * 81]
    assert "volume_plays" in pref_catalog.validate_payload(payload)


def test_volume_plays_rejects_a_non_list():
    payload = pref_catalog.default_payload()
    payload["volume_plays"] = "oyakodon"
    assert "volume_plays" in pref_catalog.validate_payload(payload)


def test_normalize_trims_blanks_and_clips_items():
    out = pref_catalog.normalize_payload({
        "volume_plays": ["  oyakodon  ", "", "   ", "y" * 100],
    })
    assert out["volume_plays"][0] == "oyakodon"
    assert len(out["volume_plays"]) == 2
    assert len(out["volume_plays"][1]) == 80


def test_normalize_caps_the_item_count():
    out = pref_catalog.normalize_payload({"volume_plays": [f"d{i}" for i in range(30)]})
    assert len(out["volume_plays"]) == 10


def test_default_payload_includes_volume_plays():
    assert pref_catalog.default_payload()["volume_plays"] == []


def test_existing_prefs_still_validate_with_the_new_field():
    """Adding a catalog field must not invalidate a payload written before it."""
    legacy = {"rest_days": [2, 6], "strength_emphasis": "same", "notes": ""}
    assert pref_catalog.validate_payload(legacy) == {}


# ── Endpoint ─────────────────────────────────────────────────────────────────

class _StubUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "consult-test"


@pytest.fixture
def client_user(monkeypatch):
    user = _StubUser()
    app.dependency_overrides[resolve_user] = lambda: user
    monkeypatch.setattr(
        ce, "build_export", lambda user_id, window_days=90, today=None: dict(_PAYLOAD)
    )
    yield TestClient(app), user
    app.dependency_overrides.pop(resolve_user, None)


def test_consult_endpoint_serves_the_blob_as_plain_text(client_user):
    client, _ = client_user
    res = client.get("/api/coach/consult")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert res.text.startswith("# Coach consult")


def test_consult_endpoint_honours_the_window(client_user, monkeypatch):
    client, _ = client_user
    seen = {}
    monkeypatch.setattr(
        ce,
        "build_export",
        lambda user_id, window_days=90, today=None: seen.update(w=window_days) or dict(_PAYLOAD),
    )
    client.get("/api/coach/consult?window=45")
    assert seen["w"] == 45


def test_consult_endpoint_rejects_a_bad_window(client_user, monkeypatch):
    client, _ = client_user

    def _raise(user_id, window_days=90, today=None):
        raise ValueError("window_days must be between 7 and 365, got 1")

    monkeypatch.setattr(ce, "build_export", _raise)
    assert client.get("/api/coach/consult?window=1").status_code == 422


def test_consult_endpoint_does_not_stamp_the_export_timestamp(client_user, monkeypatch):
    """A check-in is a conversation, not the daily message. Consuming the
    "nothing moved since" signal here would silence the next season check."""
    import backend.routers.coach as coach_router

    stamped = []
    monkeypatch.setattr(
        coach_router,
        "Session",
        lambda *_a, **_k: stamped.append(True) or (_ for _ in ()).throw(AssertionError()),
    )
    client, _ = client_user
    assert client.get("/api/coach/consult").status_code == 200
    assert stamped == []


def test_consult_endpoint_requires_a_session():
    app.dependency_overrides.pop(resolve_user, None)
    assert TestClient(app).get("/api/coach/consult").status_code in (401, 403)
