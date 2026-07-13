# Gap Analysis — Engine Contract

_Issue #1370 — sprint 107_

The gap analyzer turns a user's training data into prioritized "what to improve" findings. This document is the contract: finding schema, severity semantics, rule registry, and how to add a new rule.

---

## Finding Schema

Every finding is one row in `gap_findings` and is also returned in the API payload.

| Field | Type | Description |
|-------|------|-------------|
| `code` | `string(80)` | Stable string id for the rule that fired. Never changes — used for dedup and accept/dismiss in sprint 108. Examples: `no_recent_plyo`, `muscle_imbalance`. |
| `severity` | `int 1\|2\|3` | 1 = note, 2 = recommend, 3 = priority |
| `recommendation` | `text` | Short imperative sentence for the athlete. No metadata, no units prose. |
| `evidence` | `jsonb list` | Machine-readable list of `{metric, value, threshold, window}` objects. No natural-language prose here — callers render text from the fields. |
| `target` | `string(100) \| null` | Muscle group or session type the finding addresses (e.g. `"plyo"`, `"glutes"`). Null when finding is general. |
| `week_start` | `date` | ISO Monday of the week the finding was computed for. |
| `status` | `string` | `active` (default) \| `accepted` \| `dismissed`. Set by the athlete in sprint 108; recomputing never overwrites status. |
| `computed_at` | `timestamptz` | When the engine ran. |

### Evidence shape

```json
[
  {
    "metric":    "days_since_plyo",
    "value":     35,
    "threshold": 28,
    "window":    "28d"
  }
]
```

- `metric` — stable key consumers can translate
- `value` — the observed value (may be `null` if the metric was never recorded)
- `threshold` — the boundary that triggered the finding
- `window` — human-readable lookback window for context

---

## Severity Semantics

| Level | Label | Meaning |
|-------|-------|---------|
| 1 | note | Low urgency; athlete should be aware but no immediate action required. |
| 2 | recommend | Moderate gap; act in the next 1–2 weeks. |
| 3 | priority | High-impact gap; act this week. |

---

## Persistence (gap_findings table)

Unique key: `(user_id, week_start, code)`.

Recomputing the same week **upserts**: `severity`, `recommendation`, `evidence`, `target`, and `computed_at` are refreshed. **`status` is preserved** — an athlete-accepted finding survives recomputes.

---

## Rule Registry

Rules live in `backend/services/gap_analysis/rules/`. Each rule is a pure function:

```python
def my_rule(inputs: dict) -> GapAnalysisFinding | None:
    ...
```

- **Pure**: no DB calls, no side effects. Inputs are pre-gathered by the engine.
- **Returns `None`** when the finding does not apply (athlete is within tolerance).
- **Returns a `GapAnalysisFinding`** when a gap is detected.

Rules are registered in `backend/services/gap_analysis/engine.py` via `_REGISTRY.register(requires=[...])`:

```python
_REGISTRY.register(requires=["structural_dose"])(my_rule)
```

`requires` is the list of input keys the rule needs from the inputs dict. If any required key is absent, the engine **skips** the rule and lists it in `skipped_rules` — it never crashes the run.

### Available inputs (sprint 107)

| Key | Source | Contents |
|-----|--------|----------|
| `structural_dose` | `backend/services/structural_dose.py` | `last_plyo_days_ago`, `last_strength_days_ago`, weekly plyo/strength buckets |
| `week_start` | engine | `datetime.date` — always present |

Future sprints will add: `muscle_volume` (#1367 acwr), `form_metrics` (#1368), `intensity_distribution`, `training_load`, `injury_log` (#1350), `scores`.

---

## Adding a New Rule

1. Create `backend/services/gap_analysis/rules/my_rule.py`:

```python
from typing import Optional
from backend.services.gap_analysis.schemas import GapAnalysisFinding

def my_rule(inputs: dict) -> Optional[GapAnalysisFinding]:
    dose = inputs["structural_dose"]
    # ... compute ...
    return GapAnalysisFinding(
        code="my_rule",
        severity=2,
        recommendation="Do something specific.",
        evidence=[{"metric": "...", "value": ..., "threshold": ..., "window": "..."}],
        target="glutes",
        week_start=inputs["week_start"],
    )
```

2. Register it in `backend/services/gap_analysis/engine.py` inside `_register_builtin_rules()`:

```python
from backend.services.gap_analysis.rules.my_rule import my_rule
_REGISTRY.register(requires=["structural_dose"])(my_rule)
```

3. Write tests in `tests/test_<issue>_<slug>.py` covering:
   - Rule fires when threshold is exceeded
   - Rule is silent when athlete is within tolerance
   - Evidence shape (metric name, threshold value)
   - Rule registered in `_REGISTRY`

---

## API

`GET /api/training/gap-analysis`

Auth: session cookie required (401 if anonymous).

Response:

```json
{
  "week_start":   "2026-07-07",
  "computed_at":  "2026-07-13T08:42:00Z",
  "findings": [
    {
      "code":           "no_recent_plyo",
      "severity":       1,
      "recommendation": "Schedule a plyometric session this week to maintain reactive strength.",
      "evidence":       [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
      "target":         "plyo"
    }
  ],
  "skipped_rules": []
}
```

`skipped_rules` lists rule function names whose inputs were unavailable or that raised an exception — for observability, not user display.

---

## Reference Rule: no_recent_plyo

File: `backend/services/gap_analysis/rules/no_recent_plyo.py`

Fires when `structural_dose.last_plyo_days_ago` is `None` (never recorded) or `> 28`.

- `code`: `no_recent_plyo`
- `severity`: 1 (note)
- `evidence metric`: `days_since_plyo`
- `threshold`: 28 days
- `target`: `plyo`
