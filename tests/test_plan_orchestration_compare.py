"""Plan-suggestion orchestration: validation_errors + the three orchestrators.

Covers the retry-with-feedback loop shared by plain / langgraph, the single-shot
default, per-orchestrator dispatch, and the fallback-safe contract (LLM disabled
or retries exhausted → deterministic template). The LLM call is mocked at
backend.services.llm.complete_structured, so no network / API key is needed. The
pydantic_ai path (which uses its own client) is only exercised in its
LLM-disabled → fallback form, which needs no key.
"""

import backend.services.llm as llm
import backend.services.plan_suggestions as ps

# ceiling = max(200, 80) * 1.3 = 260
FACTS = {"trailing_28d_weekly_avg_tss": 200.0}

_BLOCKS = [{"phase": "main", "duration_min": 30, "repeat": None, "rest_min": None, "target": "easy"}]

GOOD = [{"day_offset": 0, "workout_type": "run", "target_tss": 100,
         "duration_minutes": 45, "intent": "easy", "blocks": _BLOCKS}]
BAD_TYPE = [{"day_offset": 0, "workout_type": "swim", "target_tss": 100,
             "duration_minutes": 45, "intent": "x"}]
OVER = [{"day_offset": i, "workout_type": "run", "target_tss": 100,
         "duration_minutes": 45, "intent": "x", "blocks": _BLOCKS} for i in range(4)]  # 400 > 260


def _mock_llm(monkeypatch, sequence):
    """Make complete_structured return each item of `sequence` in turn, then None."""
    calls = {"n": 0}

    def fake(system, user, schema_name, json_schema, model_tier="fast", max_tokens=None):
        i = calls["n"]
        calls["n"] += 1
        return sequence[i] if i < len(sequence) else None

    monkeypatch.setattr(llm, "complete_structured", fake)
    return calls


# ── validation_errors ─────────────────────────────────────────────────────────

def test_validation_errors_empty_when_valid():
    assert ps.validation_errors(GOOD, FACTS) == []


def test_validation_errors_names_bad_type():
    errs = ps.validation_errors(BAD_TYPE, FACTS)
    assert any("workout_type" in e for e in errs)


def test_validation_errors_names_ceiling():
    errs = ps.validation_errors(OVER, FACTS)
    assert any("ceiling" in e.lower() for e in errs)


def test_validate_suggestions_still_bool():
    assert ps.validate_suggestions(GOOD, FACTS) is True
    assert ps.validate_suggestions(BAD_TYPE, FACTS) is False


# ── retry loop (plain + langgraph behave identically) ─────────────────────────

def test_plain_retries_until_valid(monkeypatch):
    calls = _mock_llm(monkeypatch, [{"suggestions": BAD_TYPE},
                                    {"suggestions": OVER},
                                    {"suggestions": GOOD}])
    monkeypatch.setenv("PLAN_ORCH", "plain")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "llm" and r["orch"] == "plain"
    assert r["attempts"] == 3 and calls["n"] == 3


def test_langgraph_retries_until_valid(monkeypatch):
    calls = _mock_llm(monkeypatch, [{"suggestions": BAD_TYPE},
                                    {"suggestions": OVER},
                                    {"suggestions": GOOD}])
    monkeypatch.setenv("PLAN_ORCH", "langgraph")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "llm" and r["orch"] == "langgraph"
    assert r["attempts"] == 3 and calls["n"] == 3


def test_plain_retries_exhausted_falls_back(monkeypatch):
    calls = _mock_llm(monkeypatch, [{"suggestions": BAD_TYPE}] * 5)
    monkeypatch.setenv("PLAN_ORCH", "plain")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "fallback"
    assert r["attempts"] == ps._MAX_PLAN_ATTEMPTS
    assert calls["n"] == ps._MAX_PLAN_ATTEMPTS  # no calls past the cap


# ── single-shot default (original behaviour preserved) ────────────────────────

def test_single_is_default_and_single_shot(monkeypatch):
    calls = _mock_llm(monkeypatch, [{"suggestions": BAD_TYPE}, {"suggestions": GOOD}])
    monkeypatch.delenv("PLAN_ORCH", raising=False)
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["orch"] == "single"
    assert r["source"] == "fallback"  # first answer invalid → no retry
    assert calls["n"] == 1


def test_single_accepts_valid_first_answer(monkeypatch):
    _mock_llm(monkeypatch, [{"suggestions": GOOD}])
    monkeypatch.setenv("PLAN_ORCH", "single")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "llm" and r["attempts"] == 1


# ── fallback-safe: LLM disabled ───────────────────────────────────────────────

def test_all_orchestrators_fallback_when_llm_returns_none(monkeypatch):
    """single never retries (attempts=0, by design — the original baseline
    behaviour). plain/langgraph retry a failed/unparseable call up to
    _MAX_PLAN_ATTEMPTS before giving up — a None isn't proof the LLM is down,
    it can be Groq's own strict-mode validator rejecting one bad generation
    (e.g. a required-but-nullable key silently dropped), which a plain retry
    can recover from. So they report the full attempt count actually spent."""
    monkeypatch.setattr(llm, "complete_structured", lambda *a, **k: None)
    expected_attempts = {"single": 0, "plain": ps._MAX_PLAN_ATTEMPTS, "langgraph": ps._MAX_PLAN_ATTEMPTS}
    for orch in ("single", "plain", "langgraph"):
        monkeypatch.setenv("PLAN_ORCH", orch)
        r = ps.get_suggestions_from_facts(FACTS)
        assert r["source"] == "fallback" and r["attempts"] == expected_attempts[orch], orch
        assert len(r["suggestions"]) > 0


def test_plain_retries_on_none_then_succeeds(monkeypatch):
    """A transient/unparseable call (raw=None) must not end the attempt — the
    next attempt still gets to run and can succeed."""
    calls = _mock_llm(monkeypatch, [None, {"suggestions": GOOD}])
    monkeypatch.setenv("PLAN_ORCH", "plain")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "llm" and r["attempts"] == 2 and calls["n"] == 2


def test_langgraph_retries_on_none_then_succeeds(monkeypatch):
    calls = _mock_llm(monkeypatch, [None, {"suggestions": GOOD}])
    monkeypatch.setenv("PLAN_ORCH", "langgraph")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "llm" and r["attempts"] == 2 and calls["n"] == 2


def test_pydantic_ai_falls_back_when_llm_disabled(monkeypatch):
    # llm_enabled() is False without GROQ_API_KEY + LLM_COACH_ENABLED
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_COACH_ENABLED", raising=False)
    monkeypatch.setenv("PLAN_ORCH", "pydantic_ai")
    r = ps.get_suggestions_from_facts(FACTS)
    assert r["source"] == "fallback" and r["orch"] == "pydantic_ai"
    assert len(r["suggestions"]) > 0


# ── dispatch / unknown value ──────────────────────────────────────────────────

def test_unknown_orch_value_defaults_to_single(monkeypatch):
    monkeypatch.setenv("PLAN_ORCH", "does-not-exist")
    assert ps._plan_orch() == "single"
