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
import re
import time

import httpx

from backend.utils.log import get_logger

_log = get_logger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# z.ai (Zhipu) OpenAI-compatible endpoint — selected when GLM_API_KEY is set
# (or LLM_PROVIDER=glm). GLM flash models are effectively free and don't
# share Groq's tight 8k-TPM / 200k-TPD free-tier budget that kept starving
# the per-slot session fills.
_GLM_URL = "https://api.z.ai/api/paas/v4/chat/completions"
# Cerebras (OpenAI-compatible, json_schema-capable) — opt-in only, via
# LLM_PROVIDER=cerebras; never auto-selected.
_CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
_DEFAULT_MODEL_FAST = "llama-3.1-8b-instant"
_DEFAULT_MODEL_DEEP = "openai/gpt-oss-120b"
_DEFAULT_GLM_MODEL = "glm-4.7-flash"
_DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"

_startup_logged = False


def _provider() -> str:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in ("glm", "zai", "z.ai"):
        return "glm"
    if p == "cerebras":
        return "cerebras"
    if p == "groq":
        return "groq"
    # No explicit choice: prefer GLM when its key exists.
    return "glm" if os.getenv("GLM_API_KEY") else "groq"


def _emit_startup_info() -> None:
    global _startup_logged
    if _startup_logged:
        return
    _startup_logged = True
    if not os.getenv("LLM_COACH_ENABLED", "").lower() in ("1", "true", "yes"):
        _log.info("LLM coaching disabled (LLM_COACH_ENABLED not set)")
    elif not _api_key():
        _log.info("LLM coaching enabled but no API key for provider %s — all calls return None", _provider())


def _api_key() -> str:
    p = _provider()
    if p == "glm":
        return os.getenv("GLM_API_KEY", "")
    if p == "cerebras":
        return os.getenv("CEREBRAS_API_KEY", "")
    return os.getenv("GROQ_API_KEY", "")


def llm_enabled() -> bool:
    flag = os.getenv("LLM_COACH_ENABLED", "").lower() in ("1", "true", "yes")
    return flag and bool(_api_key())


def _model(tier: str) -> str:
    p = _provider()
    if p == "glm":
        if tier == "fast":
            return os.getenv("GLM_MODEL_FAST", _DEFAULT_GLM_MODEL)
        return os.getenv("GLM_MODEL_DEEP", _DEFAULT_GLM_MODEL)
    if p == "cerebras":
        if tier == "fast":
            return os.getenv("CEREBRAS_MODEL_FAST", _DEFAULT_CEREBRAS_MODEL)
        return os.getenv("CEREBRAS_MODEL_DEEP", _DEFAULT_CEREBRAS_MODEL)
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

    provider = _provider()
    api_key = _api_key()
    model = _model(model_tier)
    url = {"glm": _GLM_URL, "cerebras": _CEREBRAS_URL}.get(provider, _GROQ_URL)

    if provider == "glm":
        # z.ai has no strict json_schema mode — use json_object and carry the
        # schema in the system prompt; validation_errors() upstream rejects
        # and retries anything off-shape, same as Groq's strict mode would.
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system
                    + "\nReturn ONLY a JSON object (no prose, no markdown fences) matching this JSON Schema:\n"
                    + json.dumps(json_schema),
                },
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
    else:
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

    # One extra try, only for 429: Groq's free tier enforces a small
    # tokens-per-minute budget and PRE-BOOKS prompt + max_completion_tokens
    # against it, so back-to-back structured calls (e.g. "Fill sessions with
    # AI" walking a week of slots) reliably 429 with a "try again in Ns"
    # hint. Sleeping out that hint and retrying once turns a dead slot into
    # a slow one. Non-429 failures never retry here — callers own that.
    attempts = 2
    for attempt in range(attempts):
        try:
            resp = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            _log.info(
                "LLM call ok",
                extra={
                    "provider": provider,
                    "model": model,
                    "schema": schema_name,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
            )
            content = data["choices"][0]["message"]["content"] or ""
            # json_object mode (GLM) is not strict — some generations wrap the
            # object in markdown fences; strip them before parsing.
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            return json.loads(content)
        except Exception as exc:
            # Groq puts the actual failure reason (json_validate_failed,
            # rate_limit details, context length) in the response BODY —
            # without it a 400/429 in the log is undiagnosable.
            body = ""
            status = None
            response = getattr(exc, "response", None)
            if response is not None:
                status = getattr(response, "status_code", None)
                try:
                    body = response.text[:500]
                except Exception:
                    body = ""
            if status == 429 and attempt + 1 < attempts:
                m = re.search(r"try again in ([0-9.]+)s", body)
                wait = min(float(m.group(1)) if m else 20.0, 75.0) + 1.0
                _log.warning(
                    "LLM rate-limited — waiting to retry",
                    extra={"model": model, "wait_seconds": wait},
                )
                time.sleep(wait)
                continue
            _log.warning(
                "LLM request failed",
                extra={"error": str(exc), "model": model, "response_body": body},
            )
            return None
    return None


_emit_startup_info()


def get_or_generate(
    user_id: str,
    surface: str,
    signature: str,
    generate_fn,
    *,
    db=None,
    model_tier: str = "fast",
) -> dict | None:
    """Return cached LLM payload or call generate_fn and cache the result.

    generate_fn() must return dict | None; None means generation failed and
    nothing is stored. Callers always fall back when this returns None.
    db is a SQLAlchemy Session; when None a new session is created internally.
    model_tier labels the cached row for debugging (defaults to "fast" for
    backward compat) — pass the tier generate_fn() actually calls with, or
    the cache table misreports which model produced a given payload.
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
            model=_model(model_tier),
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
