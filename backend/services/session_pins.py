"""Session budget pins + exercise-level pin helpers for refill.

Rule: anything the athlete or coach chose on purpose is pinned; anything the
generator chose is fair game. Refill keeps pinned rows and refills the rest.

Does NOT touch fill scoring — callers subtract pinned spend / pick counts, then
invoke the existing pattern engine unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


GENERATED = "generated"
NON_GENERATED_SOURCES = frozenset({
    "manual",
    "swap",
    "homework_week",
    "homework_standing",
    "coach",
    "substituted",
})


def normalize_exercise_source(ex: dict | None) -> str:
    if not isinstance(ex, dict):
        return GENERATED
    src = str(ex.get("source") or GENERATED).strip().lower() or GENERATED
    if src == "pattern":
        return GENERATED
    return src


def exercise_is_pinned(ex: dict | None) -> bool:
    """Pinned if flagged, or non-generated source (defaults to pinned)."""
    if not isinstance(ex, dict):
        return False
    if ex.get("pinned") is True:
        return True
    if ex.get("pinned") is False:
        return False
    return normalize_exercise_source(ex) != GENERATED


def ensure_exercise_pin_fields(ex: dict) -> dict:
    """Normalize pin/source defaults on a single exercise row (mutates copy)."""
    row = deepcopy(ex) if isinstance(ex, dict) else {}
    src = normalize_exercise_source(row)
    row["source"] = src
    if "pinned" not in row:
        row["pinned"] = src != GENERATED
    else:
        row["pinned"] = bool(row["pinned"])
    if "state" not in row:
        row["state"] = "done"
    return row


def split_pinned_exercises(exercises: list | None) -> tuple[list[dict], list[dict]]:
    pinned: list[dict] = []
    unpinned: list[dict] = []
    for raw in exercises or []:
        if not isinstance(raw, dict):
            continue
        row = ensure_exercise_pin_fields(raw)
        if exercise_is_pinned(row):
            pinned.append(row)
        else:
            unpinned.append(row)
    return pinned, unpinned


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def exercise_spend(ex: dict | None) -> tuple[float, float]:
    """Return (spend_tss, spend_min) for one row."""
    if not isinstance(ex, dict):
        return 0.0, 0.0
    tss = _num(ex.get("spend_tss"), default=-1.0)
    mins = _num(ex.get("spend_min"), default=-1.0)
    if tss < 0:
        tss = _num(ex.get("_tss_weight"), default=1.0)
    if mins < 0:
        sets = _num(ex.get("sets"), default=3.0)
        mins = max(2.0, sets * 2.5)
    return tss, mins


def sum_spend(exercises: list | None, *, only_done: bool = False) -> tuple[float, float]:
    tss = 0.0
    mins = 0.0
    _done = frozenset({"done", "completed", "complete"})
    for ex in exercises or []:
        if only_done and str((ex or {}).get("state") or "done").lower() not in _done:
            continue
        st, sm = exercise_spend(ex)
        tss += st
        mins += sm
    return tss, mins


def structure_actual_spend(structure: Any) -> dict[str, Any] | None:
    """Actual session spend from exercise rows (non-skipped).

    Returns None when the structure has no exercise-level spend to read —
    callers then fall back to duration×baseline estimates / planned pin.
    """
    if not isinstance(structure, dict):
        return None
    exercises = structure.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        return None
    # Only treat as "has spend" when at least one row carries spend_tss /
    # spend_min / _tss_weight — empty skeletons shouldn't zero out estimates.
    has_spend = False
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        if ex.get("spend_tss") is not None or ex.get("spend_min") is not None or ex.get("_tss_weight") is not None:
            has_spend = True
            break
    if not has_spend:
        return None
    # Only report actual spend when at least one row is explicitly done —
    # all-pending generated sessions should fall back to baseline estimates.
    # Plan UI / fill use both "done" and "completed".
    _done = frozenset({"done", "completed", "complete"})
    has_done = any(
        isinstance(ex, dict) and str(ex.get("state") or "done").lower() in _done
        for ex in exercises
    )
    if not has_done:
        return None
    tss, mins = sum_spend(exercises, only_done=True)
    planned = _num(structure.get("target_tss"), default=-1.0)
    return {
        "actual_tss": round(tss, 1),
        "actual_duration_min": round(mins, 1),
        "planned_tss": round(planned, 1) if planned >= 0 else None,
        "skipped_count": sum(
            1 for ex in exercises
            if isinstance(ex, dict) and str(ex.get("state") or "done") == "skipped"
        ),
    }


def block_key(label: str | None) -> str:
    return str(label or "").strip().lower().replace(" ", "_").replace("-", "_")


def count_pinned_in_block(pinned: list[dict], group_key: str, group_label: str) -> int:
    gk = block_key(group_key)
    gl = block_key(group_label)
    n = 0
    for ex in pinned:
        bk = block_key(ex.get("block"))
        if bk and (bk == gk or bk == gl or gk in bk or gl in bk or bk in gk or bk in gl):
            n += 1
    return n


def spend_pinned_in_block(pinned: list[dict], group_key: str, group_label: str) -> tuple[float, float]:
    gk = block_key(group_key)
    gl = block_key(group_label)
    tss = 0.0
    mins = 0.0
    for ex in pinned:
        bk = block_key(ex.get("block"))
        if bk and (bk == gk or bk == gl or gk in bk or gl in bk or bk in gk or bk in gl):
            st, sm = exercise_spend(ex)
            tss += st
            mins += sm
    return tss, mins


def refill_contract(
    *,
    target_tss: float | None,
    duration_minutes: int | None,
    exercises: list | None,
) -> dict[str, Any]:
    """Decide whether Refill may run. Never mutates.

    When pinned spend alone exceeds the TSS budget, refill is blocked — it must
    never appear to work and change nothing.
    """
    pinned, unpinned = split_pinned_exercises(exercises)
    pinned_tss, pinned_min = sum_spend(pinned)
    budget_tss = _num(target_tss, default=0.0)
    budget_min = _num(duration_minutes, default=0.0)

    if budget_tss <= 0 and budget_min <= 0:
        return {
            "ok": False,
            "reason": "needs TSS or duration pinned to fill from patterns",
            "pinned_count": len(pinned),
            "unpinned_count": len(unpinned),
            "pinned_tss": round(pinned_tss, 1),
            "pinned_min": round(pinned_min, 1),
            "remain_tss": 0.0,
            "remain_min": 0.0,
            "blocked": "no_budget",
        }

    if budget_tss > 0 and pinned_tss > budget_tss + 1e-6:
        return {
            "ok": False,
            "reason": "pinned rows already exceed the budget — unpin one or raise the pin",
            "pinned_count": len(pinned),
            "unpinned_count": len(unpinned),
            "pinned_tss": round(pinned_tss, 1),
            "pinned_min": round(pinned_min, 1),
            "remain_tss": round(budget_tss - pinned_tss, 1),
            "remain_min": round(max(0.0, budget_min - pinned_min), 1),
            "blocked": "pinned_exceeds_budget",
        }

    remain_tss = max(0.0, budget_tss - pinned_tss) if budget_tss > 0 else 0.0
    remain_min = max(0.0, budget_min - pinned_min) if budget_min > 0 else 0.0
    note = (
        f"keeps {len(pinned)} pinned row"
        f"{'' if len(pinned) == 1 else 's'} · refills the rest"
        + (f" to {int(round(remain_tss))} TSS" if budget_tss > 0 else "")
    )
    return {
        "ok": True,
        "reason": note,
        "pinned_count": len(pinned),
        "unpinned_count": len(unpinned),
        "pinned_tss": round(pinned_tss, 1),
        "pinned_min": round(pinned_min, 1),
        "remain_tss": round(remain_tss, 1),
        "remain_min": round(remain_min, 1),
        "blocked": None,
    }


def stamp_generated(exercises: list | None) -> list[dict]:
    out = []
    for ex in exercises or []:
        if not isinstance(ex, dict):
            continue
        row = deepcopy(ex)
        row["source"] = GENERATED
        row["pinned"] = False
        if "state" not in row:
            row["state"] = "done"
        out.append(row)
    return out
