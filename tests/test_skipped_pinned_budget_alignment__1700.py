"""Issue #1700: align client-side and server-side budget math for skipped+pinned rows.

The bug: session-budget.js `analyze()` skips ALL rows with state='skipped' before
computing pinnedTss/pinnedCount, so a pinned+skipped row contributes nothing to the
client budget bar. Server-side `refill_contract()` calls `sum_spend(pinned)` without
`only_done=True`, so it DOES include skipped+pinned rows in pinned_tss.

Fix: client `analyze()` must include skipped+pinned rows in pinnedTss/pinnedCount,
matching the server. Non-pinned skipped rows remain excluded from filledTss.

AC1 (server): refill_contract includes skipped+pinned rows in pinned_tss.
AC2 (server): sum_spend without only_done includes skipped rows.
AC3 (client): analyze() counts skipped+pinned rows toward pinnedTss.
AC4 (client): analyze() counts skipped+pinned rows toward pinnedCount.
AC5 (client): analyze() still excludes non-pinned skipped rows from filledTss.
AC6 (client): analyze() note text is coherent — pinnedCount matches what is kept.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from backend.services.session_pins import refill_contract, sum_spend

REPO = Path(__file__).resolve().parents[1]
SESSION_BUDGET_JS = REPO / "frontend" / "js" / "lib" / "session-budget.js"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_analyze(exercises: list, budget_tss: float | None = None, budget_min: float | None = None):
    """Run SessionBudget.analyze() in node and return the parsed result."""
    script = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(SESSION_BUDGET_JS))}, 'utf8');
const ctx = {{ globalThis: {{}}, console }};
ctx.window = ctx.globalThis;
vm.createContext(ctx);
vm.runInContext(code, ctx);
const SB = ctx.globalThis.SessionBudget;
const opts = {{
  budgetTss: {json.dumps(budget_tss)},
  budgetMin: {json.dumps(budget_min)},
  exercises: {json.dumps(exercises)},
}};
process.stdout.write(JSON.stringify(SB.analyze(opts)));
"""
    out = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(out)


# ---------------------------------------------------------------------------
# AC1: server refill_contract includes skipped+pinned rows in pinned_tss
# ---------------------------------------------------------------------------

def test_ac1_server_refill_contract_includes_skipped_pinned_in_pinned_tss():
    """refill_contract must count a pinned+skipped row in pinned_tss (AC1)."""
    exercises = [
        {
            "name": "Deadlift",
            "source": "swap",
            "pinned": True,
            "state": "skipped",
            "spend_tss": 20,
            "spend_min": 10,
        },
        {
            "name": "Curl",
            "source": "generated",
            "pinned": False,
            "state": "done",
            "spend_tss": 5,
            "spend_min": 4,
        },
    ]
    c = refill_contract(target_tss=50, duration_minutes=45, exercises=exercises)
    assert c["pinned_tss"] == 20.0, (
        f"Expected pinned_tss=20.0 (skipped+pinned row must count), got {c['pinned_tss']}"
    )
    assert c["pinned_count"] == 1


def test_ac1b_server_refill_contract_blocked_when_skipped_pinned_exceeds_budget():
    """A skipped+pinned row can push pinned_tss over budget — must block (AC1)."""
    exercises = [
        {
            "name": "Heavy Squat",
            "source": "manual",
            "pinned": True,
            "state": "skipped",
            "spend_tss": 30,
            "spend_min": 15,
        },
    ]
    c = refill_contract(target_tss=25, duration_minutes=45, exercises=exercises)
    assert c["ok"] is False
    assert c["blocked"] == "pinned_exceeds_budget"
    assert c["pinned_tss"] == 30.0


# ---------------------------------------------------------------------------
# AC2: sum_spend without only_done includes skipped rows
# ---------------------------------------------------------------------------

def test_ac2_sum_spend_includes_skipped_by_default():
    """sum_spend(only_done=False) must include skipped rows (AC2)."""
    rows = [
        {"state": "done", "spend_tss": 10, "spend_min": 5},
        {"state": "skipped", "spend_tss": 8, "spend_min": 4},
    ]
    tss, mins = sum_spend(rows)
    assert tss == 18.0
    assert mins == 9.0


def test_ac2_sum_spend_only_done_excludes_skipped():
    """sum_spend(only_done=True) must exclude skipped rows."""
    rows = [
        {"state": "done", "spend_tss": 10, "spend_min": 5},
        {"state": "skipped", "spend_tss": 8, "spend_min": 4},
    ]
    tss, mins = sum_spend(rows, only_done=True)
    assert tss == 10.0
    assert mins == 5.0


# ---------------------------------------------------------------------------
# AC3: client analyze() counts skipped+pinned rows toward pinnedTss
# ---------------------------------------------------------------------------

def test_ac3_client_analyze_pinned_skipped_counts_in_pinned_tss():
    """After fix: analyze() must include skipped+pinned row in pinnedTss (AC3)."""
    exercises = [
        {"name": "Deadlift", "pinned": True, "state": "skipped", "spend_tss": 20, "spend_min": 10},
        {"name": "Curl", "pinned": False, "state": "done", "spend_tss": 5, "spend_min": 4},
    ]
    result = _run_analyze(exercises, budget_tss=50)
    assert result["pinnedTss"] == 20.0, (
        f"Expected pinnedTss=20.0 for skipped+pinned row, got {result['pinnedTss']}"
    )


def test_ac3b_client_analyze_pinned_skipped_not_in_filled_tss():
    """Skipped+pinned row must not appear in filledTss (goes to pinned only)."""
    exercises = [
        {"name": "Deadlift", "pinned": True, "state": "skipped", "spend_tss": 20, "spend_min": 10},
    ]
    result = _run_analyze(exercises, budget_tss=50)
    assert result["filledTss"] == 0.0, (
        f"Expected filledTss=0, got {result['filledTss']}"
    )


# ---------------------------------------------------------------------------
# AC4: client analyze() counts skipped+pinned rows toward pinnedCount
# ---------------------------------------------------------------------------

def test_ac4_client_analyze_pinned_skipped_counts_in_pinned_count():
    """After fix: analyze() must include skipped+pinned row in pinnedCount (AC4)."""
    exercises = [
        {"name": "Squat", "pinned": True, "state": "skipped", "spend_tss": 15, "spend_min": 8},
        {"name": "Press", "pinned": True, "state": "done", "spend_tss": 10, "spend_min": 6},
    ]
    result = _run_analyze(exercises, budget_tss=50)
    assert result["pinnedCount"] == 2, (
        f"Expected pinnedCount=2 (both pinned rows, one skipped), got {result['pinnedCount']}"
    )


# ---------------------------------------------------------------------------
# AC5: client analyze() still excludes non-pinned skipped rows from filledTss
# ---------------------------------------------------------------------------

def test_ac5_client_analyze_non_pinned_skipped_excluded_from_filled():
    """Non-pinned skipped rows must still be excluded from filledTss (AC5)."""
    exercises = [
        {"name": "Curl", "pinned": False, "state": "skipped", "spend_tss": 5, "spend_min": 3},
        {"name": "Row", "pinned": False, "state": "done", "spend_tss": 8, "spend_min": 5},
    ]
    result = _run_analyze(exercises, budget_tss=50)
    assert result["filledTss"] == 8.0, (
        f"Expected filledTss=8.0 (only done non-pinned row), got {result['filledTss']}"
    )
    assert result["pinnedTss"] == 0.0


# ---------------------------------------------------------------------------
# AC6: client analyze() note/pinnedCount coherent with what Refill will keep
# ---------------------------------------------------------------------------

def test_ac6_client_analyze_blocked_when_skipped_pinned_exceeds_budget():
    """After fix: client must block when a skipped+pinned row makes pinnedTss > budget (AC6)."""
    exercises = [
        {"name": "Heavy DL", "pinned": True, "state": "skipped", "spend_tss": 60, "spend_min": 20},
    ]
    result = _run_analyze(exercises, budget_tss=50)
    assert result["pinnedExceeds"] is True, (
        f"Expected pinnedExceeds=True when skipped+pinned TSS exceeds budget, got {result['pinnedExceeds']}"
    )
    assert result["blocked"] is True


def test_ac6b_client_and_server_agree_on_pinned_tss_for_skipped_pinned():
    """Client pinnedTss must equal server pinned_tss for the same exercise set (AC6)."""
    exercises_client = [
        {"name": "Squat", "pinned": True, "state": "skipped", "spend_tss": 18, "spend_min": 9, "source": "swap"},
        {"name": "Lunge", "pinned": False, "state": "done", "spend_tss": 6, "spend_min": 4, "source": "generated"},
    ]
    exercises_server = [
        {"name": "Squat", "pinned": True, "state": "skipped", "spend_tss": 18, "spend_min": 9, "source": "swap"},
        {"name": "Lunge", "pinned": False, "state": "done", "spend_tss": 6, "spend_min": 4, "source": "generated"},
    ]
    client = _run_analyze(exercises_client, budget_tss=40)
    server = refill_contract(target_tss=40, duration_minutes=30, exercises=exercises_server)
    assert client["pinnedTss"] == server["pinned_tss"], (
        f"Client pinnedTss={client['pinnedTss']} != server pinned_tss={server['pinned_tss']}"
    )
    assert client["remainTss"] == server["remain_tss"], (
        f"Client remainTss={client['remainTss']} != server remain_tss={server['remain_tss']}"
    )
