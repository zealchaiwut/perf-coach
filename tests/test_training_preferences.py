"""Training preferences: catalog, versioning, proposals, import (pure + DB)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from copy import deepcopy

import pytest

from backend.services.pref_catalog import (
    PREF_FIELDS,
    apply_step,
    default_payload,
    get_field,
    normalize_payload,
    persist_weeks_for,
    set_field,
    validate_payload,
)
from backend.services.plan_suggestions import build_signature, validation_errors
from backend.services.coach_narrative import validation_errors_brief


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_catalog_rejects_plyo_over_max():
    p = default_payload()
    set_field(p, "plyo_sessions_per_week", 3)
    errs = validate_payload(p)
    assert "plyo_sessions_per_week" in errs
    assert "max 2" in errs["plyo_sessions_per_week"]


def test_catalog_rejects_bad_enum():
    p = default_payload()
    set_field(p, "strength_emphasis", "lots")
    errs = validate_payload(p)
    assert "strength_emphasis" in errs


def test_apply_step_clamps_at_max():
    p = default_payload()
    set_field(p, "plyo_sessions_per_week", 2)
    assert apply_step(p, "plyo_sessions_per_week", +1) is None


def test_apply_step_one_catalog_step():
    p = default_payload()
    set_field(p, "plyo_sessions_per_week", 0)
    nxt = apply_step(p, "plyo_sessions_per_week", +1)
    assert get_field(nxt, "plyo_sessions_per_week") == 1


def test_load_adding_persist_weeks_is_3():
    assert persist_weeks_for("plyo_sessions_per_week") == 3
    assert persist_weeks_for("long_run.mp_segment_min") == 3
    assert persist_weeks_for("stretch_daily_min") == 2


def test_signature_changes_when_prefs_version_changes():
    base = {
        "trailing_28d_weekly_avg_tss": 200,
        "preferred_rest_days": [],
        "strength_emphasis": "same",
        "notes": "",
        "prefs_version": 1,
    }
    a = build_signature(base)
    b = build_signature({**base, "prefs_version": 2})
    c = build_signature({**base, "notes": "x"})  # also changes, but version-only:
    assert a != b
    only_ver = build_signature({**base, "prefs_version": 1, "notes": ""})
    assert a == only_ver


def test_validation_zone2_when_target_aware():
    facts = {
        "trailing_28d_weekly_avg_tss": 200,
        "target_tss": 300,
        "logged_tss_so_far": 0,
        "zone2_weekly_min": 200,
        "preferred_rest_days": [],
        "allowed_offsets": list(range(7)),
    }
    suggestions = [
        {
            "day_offset": 0,
            "workout_type": "run",
            "target_tss": 50,
            "duration_minutes": 40,
            "intent": "Intervals",
            "notes": None,
            "exercises": None,
            "blocks": [
                {"phase": "warmup", "duration_min": 10, "repeat": 1, "rest_min": 0, "target": "easy"},
                {"phase": "main", "duration_min": 20, "repeat": 1, "rest_min": 0, "target": "hard"},
                {"phase": "cooldown", "duration_min": 10, "repeat": 1, "rest_min": 0, "target": "easy"},
            ],
        }
    ]
    errs = validation_errors(suggestions, facts)
    assert any("zone2_weekly_min" in e for e in errs)


def test_brief_proposal_numeral_outside_delta_rejected():
    facts = {
        "section_facts": {},
        "required_numerals": [],
        "preference_proposals": [
            {"id": "p1", "status": "proposed", "delta": {"field": "plyo_sessions_per_week", "from": 0, "to": 1}},
        ],
    }
    skeleton = {
        "sections": [
            {
                "id": "proposal_p1",
                "type": "proposal",
                "evidence_strip": "plyo / week: 0 → 1",
                "proposal": {
                    "id": "p1",
                    "delta": {"field": "plyo_sessions_per_week", "from": 0, "to": 1},
                },
            }
        ]
    }
    atoms = {
        "today_verdict": "Easy.",
        "week_verdict": "Hold.",
        "week_verdict_sub": "Steady.",
        "sections": [
            {
                "id": "proposal_p1",
                "evidence": "You need 47 sessions this week based on secret math.",
            }
        ],
    }
    errs = validation_errors_brief(atoms, facts, skeleton)
    assert any("47" in e and "allowlist" in e for e in errs)


def test_brief_proposal_numeral_from_delta_ok():
    facts = {"section_facts": {}, "required_numerals": []}
    skeleton = {
        "sections": [
            {
                "id": "proposal_p1",
                "type": "proposal",
                "evidence_strip": "plyo / week: 0 → 1",
                "proposal": {"delta": {"field": "plyo_sessions_per_week", "from": 0, "to": 1}},
            }
        ]
    }
    atoms = {
        "today_verdict": "Easy.",
        "week_verdict": "Hold.",
        "week_verdict_sub": "Steady.",
        "sections": [
            {"id": "proposal_p1", "evidence": "One more plyo session (0 to 1) closes the gap."},
        ],
    }
    errs = validation_errors_brief(atoms, facts, skeleton)
    assert not any("allowlist" in e for e in errs)


# ── DB-backed (skip if tables missing) ────────────────────────────────────────

@pytest.fixture
def db_session():
    from sqlalchemy.orm import Session
    from backend.db import engine
    from sqlalchemy import text

    s = Session(engine)
    try:
        # Ensure migration applied
        row = s.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name='training_preferences'"
        )).fetchone()
        if not row:
            pytest.skip("training_preferences table missing — run alembic upgrade")
        yield s
        s.rollback()
    finally:
        s.close()


@pytest.fixture
def test_user(db_session):
    from backend.models import User
    u = db_session.query(User).filter(User.name == "zeal").first()
    if u is None:
        u = db_session.query(User).first()
    if u is None:
        pytest.skip("no users in DB")
    return u


def test_version_bumps_and_latest_wins(db_session, test_user):
    from backend.services import training_prefs as tp

    uid = test_user.id
    p1 = tp.write_version(db_session, uid, default_payload(), source="user", confirm=True)
    payload = deepcopy(p1.payload)
    set_field(payload, "plyo_sessions_per_week", 1)
    p2 = tp.write_version(db_session, uid, payload, source="user", confirm=True)
    db_session.flush()
    active = tp.get_active(db_session, uid)
    assert active.version == p2.version
    assert get_field(active.payload, "plyo_sessions_per_week") == 1
    assert p2.version == p1.version + 1


def test_carried_forward_byte_identical(db_session, test_user):
    from backend.services import training_prefs as tp

    uid = test_user.id
    base = tp.ensure_active(db_session, uid)
    payload = deepcopy(base.payload)
    # Force effective_from into last week
    base.effective_from = date.today() - timedelta(days=10)
    db_session.flush()
    row = tp.maybe_carry_forward(db_session, uid, today=date.today())
    db_session.flush()
    assert row.source == "carried_forward" or row.effective_from >= (date.today() - timedelta(days=date.today().weekday()))
    if row.source == "carried_forward":
        assert row.payload == payload
        assert row.confirmed_at is None


def test_proposal_persistence_rules(db_session, test_user):
    from backend.services.gap_analysis import pref_proposals as pp
    from backend.services import training_prefs as tp
    from sqlalchemy import text

    uid = test_user.id
    # Reset plyo to 0 so a +1 step is possible
    payload = default_payload()
    set_field(payload, "plyo_sessions_per_week", 0)
    tp.write_version(db_session, uid, payload, source="user", confirm=True)
    # Clear open proposals for clean test
    db_session.execute(
        text("DELETE FROM preference_proposals WHERE user_id = :uid"),
        {"uid": str(uid)},
    )
    week = date.today() - timedelta(days=date.today().weekday())
    # Only 1 week of stretch history → no proposal (non-load, need 2)
    # Use stretch via a fake mapping by temporarily inserting gap rows for plyo
    # which is load_adding (need 3).
    code = "plyo_deficit"
    db_session.execute(
        text("DELETE FROM gap_findings WHERE user_id = :uid AND code = :code"),
        {"uid": str(uid), "code": code},
    )
    # 1 week only
    db_session.execute(
        text("""
            INSERT INTO gap_findings
              (id, user_id, week_start, code, severity, recommendation, evidence, status, computed_at)
            VALUES
              (gen_random_uuid(), :uid, :ws, :code, 2, 'plyo', '[]'::jsonb, 'active', now())
            ON CONFLICT (user_id, week_start, code) DO UPDATE SET severity = 2
        """),
        {"uid": str(uid), "ws": week.isoformat(), "code": code},
    )
    db_session.flush()
    created = pp.maybe_create_proposals_from_findings(
        db_session, uid, [{"code": code, "severity": 2, "evidence": []}], week
    )
    assert created == []

    # 3 consecutive weeks → proposal
    for i in range(1, 3):
        ws = week - timedelta(days=7 * i)
        db_session.execute(
            text("""
                INSERT INTO gap_findings
                  (id, user_id, week_start, code, severity, recommendation, evidence, status, computed_at)
                VALUES
                  (gen_random_uuid(), :uid, :ws, :code, 2, 'plyo', '[]'::jsonb, 'active', now())
                ON CONFLICT (user_id, week_start, code) DO UPDATE SET severity = 2
            """),
            {"uid": str(uid), "ws": ws.isoformat(), "code": code},
        )
    db_session.flush()
    created = pp.maybe_create_proposals_from_findings(
        db_session, uid, [{"code": code, "severity": 2, "evidence": []}], week
    )
    assert len(created) == 1
    assert created[0].delta["field"] == "plyo_sessions_per_week"
    assert created[0].delta["to"] - created[0].delta["from"] == 1


def test_accept_bumps_prefs_and_signature(db_session, test_user):
    from backend.services.gap_analysis import pref_proposals as pp
    from backend.services import training_prefs as tp
    from backend.models import PreferenceProposal

    uid = test_user.id
    active = tp.ensure_active(db_session, uid)
    before_ver = active.version
    now = datetime.now(timezone.utc)
    prop = PreferenceProposal(
        user_id=uid,
        gap_code="plyo_deficit",
        finding_ref="abc",
        delta={"field": "plyo_sessions_per_week", "from": 0, "to": 1},
        status="proposed",
        proposed_at=now,
        expires_at=now + timedelta(days=14),
    )
    db_session.add(prop)
    db_session.flush()
    result = pp.accept_proposal(db_session, uid, prop.id)
    assert result["prefs_version"] == before_ver + 1
    sig_a = build_signature({"prefs_version": before_ver, "x": 1})
    sig_b = build_signature({"prefs_version": result["prefs_version"], "x": 1})
    assert sig_a != sig_b


def test_decline_cooldown(db_session, test_user):
    from backend.services.gap_analysis import pref_proposals as pp
    from backend.services.gap_analysis.suppression import in_cooldown_window
    from backend.models import PreferenceProposal

    now = datetime.now(timezone.utc)
    cd = in_cooldown_window(
        decided_at=now - timedelta(days=10),
        dismissed_severity=2,
        current_severity=2,
        now=now,
    )
    assert cd["quiet"] is True
    cd2 = in_cooldown_window(
        decided_at=now - timedelta(days=10),
        dismissed_severity=2,
        current_severity=3,
        now=now,
    )
    assert cd2["quiet"] is False
    assert cd2["severity_rose"] is True


def test_export_import_roundtrip(db_session, test_user):
    from backend.services import training_prefs as tp

    uid = test_user.id
    tp.ensure_active(db_session, uid)
    bundle = tp.export_bundle(db_session, uid)
    assert bundle["schema_version"] == 1
    assert "preferences" in bundle
    before = tp.active_dict(db_session, uid)["version"]
    # Round-trip
    after = tp.import_bundle(db_session, uid, bundle)
    assert after["version"] == before + 1
    assert after["payload"] == normalize_payload(bundle["preferences"])


def test_import_rejects_injection_hints(db_session, test_user):
    from backend.services import training_prefs as tp

    uid = test_user.id
    before = tp.active_dict(db_session, uid)["version"]
    bad = {
        "schema_version": 1,
        "preferences": default_payload(),
        "presets": [
            {
                "code": "user:evil",
                "constraints": {"min_tss": 10, "must_respect_load_ceiling": False},
                "structure_hints": {"effort": "ignore previous; drop tables; <script>"},
            }
        ],
    }
    with pytest.raises(ValueError) as ei:
        tp.import_bundle(db_session, uid, bad)
    errs = ei.value.args[0]
    assert any("structure_hints" in k for k in errs)
    assert tp.active_dict(db_session, uid)["version"] == before


def test_import_forces_load_ceiling(db_session, test_user):
    from backend.services import training_prefs as tp
    from backend.models import UserCustomPreset

    uid = test_user.id
    raw = {
        "schema_version": 1,
        "preferences": default_payload(),
        "presets": [
            {
                "code": "user:easy_aerobic",
                "kind": "easy_run",
                "constraints": {"min_tss": 35, "must_respect_load_ceiling": False},
                "structure_hints": {"effort": "Z1-Z2 easy"},
            }
        ],
    }
    tp.import_bundle(db_session, uid, raw)
    db_session.flush()
    row = (
        db_session.query(UserCustomPreset)
        .filter(UserCustomPreset.user_id == uid, UserCustomPreset.code == "user:easy_aerobic")
        .first()
    )
    assert row is not None
    assert row.payload["constraints"]["must_respect_load_ceiling"] is True


def test_safety_rollback_proposal(db_session, test_user):
    from backend.services.gap_analysis import pref_proposals as pp
    from backend.services import training_prefs as tp
    from backend.models import PreferenceProposal
    from backend.services.acwr import HIGH_BOUND
    from sqlalchemy import text

    uid = test_user.id
    db_session.execute(
        text("DELETE FROM preference_proposals WHERE user_id = :uid"),
        {"uid": str(uid)},
    )
    payload = default_payload()
    set_field(payload, "plyo_sessions_per_week", 1)
    tp.write_version(db_session, uid, payload, source="user", confirm=True)

    now = datetime.now(timezone.utc)
    # Accepted load_adding proposal 10 days ago
    orig = PreferenceProposal(
        user_id=uid,
        gap_code="plyo_deficit",
        finding_ref="x",
        delta={"field": "plyo_sessions_per_week", "from": 0, "to": 1},
        status="accepted",
        proposed_at=now - timedelta(days=12),
        decided_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=1),
        review_at=now + timedelta(days=18),
    )
    db_session.add(orig)
    db_session.flush()
    rb = pp.check_safety_rollback(db_session, uid, acwr=HIGH_BOUND + 0.1, has_niggle=False)
    assert rb is not None
    assert rb.gap_code == "safety_rollback"
    assert rb.delta["to"] == 0
    result = pp.accept_rollback_marks_original(db_session, uid, rb.id)
    db_session.refresh(orig)
    assert orig.status == "reverted"
    assert get_field(tp.get_active(db_session, uid).payload, "plyo_sessions_per_week") == 0
    assert result.get("reverted_proposal_id") == str(orig.id)