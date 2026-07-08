"""Groq LLM client service (issue #1311).

Exposes:
  llm_enabled()              — True iff GROQ_API_KEY set AND LLM_COACH_ENABLED=true
  complete_structured(...)   — call Groq, return parsed dict or None (never raises)
  get_or_generate(...)       — cache-aware wrapper over complete_structured

Everything is OFF by default: when LLM_COACH_ENABLED is unset/false this module
is a no-op and zero behavior changes anywhere. Later surfaces import and call
get_or_generate; they always check for None and fall back gracefully.
"""

from __future__ import annotations

import json
import os

import httpx

from backend.utils.log import get_logger

_log = get_logger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL_FAST = "llama-3.1-8b-instant"
_DEFAULT_MODEL_DEEP = "openai/gpt-oss-120b"

_startup_logged = False


def _emit_startup_info() -> None:
    global _startup_logged
    if _startup_logged:
        return
    _startup_logged = True
    if not os.getenv("LLM_COACH_ENABLED", "").lower() in ("1", "true", "yes"):
        _log.info("LLM coaching disabled (LLM_COACH_ENABLED not set)")
    elif not os.getenv("GROQ_API_KEY"):
        _log.info("LLM coaching enabled but GROQ_API_KEY absent — all calls return None")


def llm_enabled() -> bool:
    flag = os.getenv("LLM_COACH_ENABLED", "").lower() in ("1", "true", "yes")
    key = bool(os.getenv("GROQ_API_KEY"))
    return flag and key


def _model(tier: str) -> str:
    if tier == "fast":
        return os.getenv("GROQ_MODEL_FAST", _DEFAULT_MODEL_FAST)
    return os.getenv("GROQ_MODEL_DEEP", _DEFAULT_MODEL_DEEP)


def complete_structured(
    system: str,
    user: str,
    schema_name: str,
    json_schema: dict,
    model_tier: str = "fast",
    max_tokens: int | None = None,
) -> dict | None:
    """Call Groq with JSON-schema structured output. Returns parsed dict or None.

    `max_tokens` overrides Groq's implicit completion-length default — a schema
    asking for a lot of structured detail (e.g. a full week of exercises/blocks)
    can otherwise get truncated mid-JSON ("max completion tokens reached before
    generating a valid document"), which surfaces as an opaque 400 and a
    fallback with zero indication of why. Pass a generous value for any
    schema whose worst case is large.
    """
    if not llm_enabled():
        return None

    api_key = os.getenv("GROQ_API_KEY", "")
    model = _model(model_tier)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
                "strict": True,
            },
        },
    }
    if max_tokens is not None:
        payload["max_completion_tokens"] = max_tokens

    try:
        resp = httpx.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:
        _log.warning("LLM request failed", extra={"error": str(exc), "model": model})
        return None


def get_or_generate(
    user_id: str,
    surface: str,
    signature: str,
    generate_fn,
    *,
    db=None,
) -> dict | None:
    """Return cached LLM payload or call generate_fn and cache the result.

    generate_fn() must return dict | None; None means generation failed and
    nothing is stored. Callers always fall back when this returns None.
    db is a SQLAlchemy Session; when None a new session is created internally.
    """
    from backend.models import LlmGeneration

    _own_session = db is None
    if _own_session:
        from backend.db import engine
        from sqlalchemy.orm import Session
        db = Session(engine)

    try:
        cached = db.query(LlmGeneration).filter_by(
            user_id=user_id, surface=surface, input_signature=signature
        ).first()
        if cached is not None:
            return cached.payload

        try:
            payload = generate_fn()
        except Exception as exc:
            _log.warning(
                "LLM generate_fn raised",
                extra={"surface": surface, "error": str(exc)},
            )
            return None

        if payload is None:
            return None

        row = LlmGeneration(
            user_id=user_id,
            surface=surface,
            input_signature=signature,
            payload=payload,
            model=_model("fast"),
        )
        db.add(row)
        db.commit()
        return payload
    except Exception as exc:
        _log.warning(
            "LLM cache error",
            extra={"surface": surface, "error": str(exc)},
        )
        if _own_session:
            try:
                db.rollback()
            except Exception:
                pass
        return None
    finally:
        if _own_session:
            db.close()
