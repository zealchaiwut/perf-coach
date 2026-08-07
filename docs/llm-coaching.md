# LLM Coaching

Foundation module (`backend/services/llm.py`) for the Groq-backed coaching layer.
Everything is OFF by default — zero behavior change until explicitly enabled.

## Env Vars

| Variable | Default | Description |
|---|---|---|
| `LLM_COACH_ENABLED` | `false` | Master kill switch. Set to `true` to enable. |
| `GROQ_API_KEY` | _(unset)_ | Groq API key. **Required when enabled.** Get one at https://console.groq.com/keys |
| `GROQ_MODEL_FAST` | `llama-3.1-8b-instant` | Model used for the `fast` tier (low latency). |
| `GROQ_MODEL_DEEP` | `openai/gpt-oss-120b` | Model used for the `deep` tier (higher quality). |

Both `LLM_COACH_ENABLED=false` and `GROQ_API_KEY` absent are set in `render.yaml`
for both services (UAT + PRD). Override in the Render dashboard to enable.

## Surfaces

| Surface | Module | Notes |
|---|---|---|
| Habit insights / nudges | `habit_insights.py`, `habit_nudges.py` | Fast tier |
| Readiness explanation | `readiness_explanation.py` | Fast tier |
| Plan session suggest | `plan_suggestions.py` | Deep tier. Single-shot — the `PLAN_ORCH` switch and its LangGraph / Pydantic-AI alternatives were deleted once the comparison ended. |
| **Daily coach message** | `coach_facts` + `weekly_coach_message._call_llm_narrative` + worker `daily_coach` job | **Worker only.** Fast tier. Rewrites the prose around a deterministic message; `_numbers_preserved()` discards any rephrase whose numerals drift. Falls back to the deterministic text on any failure. `weekly_coach` is a dispatch alias. |

### Daily Home Coach (worker schedule)

`weekly_coach_message.generate_for_user` runs on the compute worker (`daily_coach`
job). The warmth rephrase (`_call_llm_narrative`) is gated by `LLM_COACH_ENABLED`
and routes to whichever provider API key is set (GLM → Cerebras → Groq). Render
webapps only read `GET /api/coach/daily-message`; they never invoke the rephrase.

| Variable | Default | Description |
|---|---|---|
| `PERFCOACH_ROLE` | _(unset on web)_ / `worker` via `start_worker.sh` | Worker identity flag — determines which scheduled jobs run. |
| `WORKER_DAILY_COACH_ENABLED` | `1` | Scheduler enqueues once per calendar day (Bangkok). Falls back to `WORKER_WEEKLY_COACH_ENABLED` if unset. |

Manual: `POST /internal/daily-coach/run` on the worker (`/internal/weekly-coach/run` alias). Details: `docs/worker.md`.

## Fail-Safe Contract

`complete_structured()` and `get_or_generate()` **never raise**. Every failure
path — missing key, disabled flag, HTTP error, network timeout, schema-invalid
JSON, DB error — returns `None`. Callers check for `None` and fall back to their
existing behavior (no LLM text displayed).

One `INFO` log line is emitted at startup to indicate whether LLM coaching is
enabled or why it is unavailable. No repeated warnings.

## Cache Model

Generated text is stored in the `llm_generations` table keyed by
`(user_id, surface, input_signature)`:

- `surface` — a short string naming the coaching feature (e.g. `habit_insights`).
- `input_signature` — sha256 of the canonical inputs. When inputs change the
  signature changes and a fresh generation is triggered; the old row is superseded
  on the next unique (user, surface, sig) write.
- `payload` — JSONB; the parsed dict returned by Groq.

The helper `get_or_generate(user_id, surface, signature, generate_fn, *, db=None)`:
1. Looks up `(user_id, surface, signature)` in `llm_generations`.
2. On hit: returns `cached.payload` immediately (no HTTP call).
3. On miss: calls `generate_fn()` (which internally calls `complete_structured`).
4. On success: inserts a new row and returns the payload.
5. On failure (`generate_fn` returns `None` or raises): returns `None`, nothing stored.

## How Later Surfaces Plug In

```python
from backend.services.llm import get_or_generate, complete_structured
import hashlib, json

def get_habit_insights_text(user_id, habits_data, db):
    sig = hashlib.sha256(json.dumps(habits_data, sort_keys=True).encode()).hexdigest()

    def generate():
        return complete_structured(
            system="You are a concise fitness coach...",
            user=json.dumps(habits_data),
            schema_name="habit_insights",
            json_schema={"type": "object", "properties": {"summary": {"type": "string"}}, ...},
            model_tier="fast",
        )

    return get_or_generate(user_id, "habit_insights", sig, generate, db=db)
    # Returns dict | None — caller renders text or skips the LLM block
```

No SDK is used. Transport is raw `httpx` (already a dependency) with
`response_format={"type":"json_schema",...}` (Groq's OpenAI-compatible endpoint).
Timeout: 60 s total, 10 s connect. No retries inside the provider.
