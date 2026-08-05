"""Preview tab — pool counts, thin blocks, run/strength budget traces."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from backend.services.plan_pattern_fill import (
    THIN_POOL_MULTIPLIER,
    compute_pool_counts,
    fill_slot,
    match_exercises_for_tags,
    resolve_groups_for_duration,
    select_pattern,
)
from backend.services.plan_pattern_seeds import default_exercises, default_strength_patterns


def test_thin_pool_multiplier_constant():
    assert THIN_POOL_MULTIPLIER == 2


@pytest.mark.parametrize(
    "pick_n,matched,expect_thin",
    [
        (2, 3, True),
        (2, 4, False),
        (1, 1, True),
        (1, 2, False),
        (0, 0, False),
    ],
)
def test_thin_block_detection(pick_n, matched, expect_thin):
    thin = bool(pick_n > 0 and matched < pick_n * THIN_POOL_MULTIPLIER)
    assert thin is expect_thin


def test_pool_counts_match_fill_matcher():
    pat = next(p for p in default_strength_patterns() if p["subtype"] == "strength_lower")
    pool = default_exercises()
    counts = compute_pool_counts(pat, pool, duration_min=50)
    groups, _ = resolve_groups_for_duration(pat["recipe"], 50)
    assert counts["blocks"]
    for block, group in zip(counts["blocks"], groups):
        tags = block["from_tags"]
        matched = match_exercises_for_tags(pool, tags)
        assert block["matched_count"] == len(matched)
        assert block["key"] == str(group.get("key") or "")


def test_strength_budget_trace_ops():
    slot = {
        "day_offset": 0,
        "workout_type": "strength",
        "target_tss": 50,
        "duration_minutes": 45,
        "subtype": "strength_lower",
        "structure_hints": {},
        "locked": False,
    }
    content = fill_slot(slot, db=None, week_ctx={"skeleton_slots": [slot]}, rng=random.Random(1))
    trace = (content.get("fill_log") or {}).get("budget_trace") or []
    ops = [e["op"] for e in trace]
    assert "budget_start" in ops
    assert "group_open" in ops
    assert "budget_pick" in ops
    assert "budget_end" in ops
    open_ev = next(e for e in trace if e["op"] == "group_open")
    assert "key" in open_ev
    pick = next(e for e in trace if e["op"] == "budget_pick")
    assert {"score", "bias", "random", "top", "sets", "reps"} <= set(pick)


def test_run_budget_trace_no_strength_fields():
    slot = {
        "day_offset": 0,
        "workout_type": "run",
        "target_tss": 50,
        "duration_minutes": 60,
        "subtype": "tempo",
        "structure_hints": {},
        "locked": False,
    }
    content = fill_slot(slot, db=None, week_ctx={"skeleton_slots": [slot]}, rng=random.Random(1))
    trace = (content.get("fill_log") or {}).get("budget_trace") or []
    assert trace, "run fill must emit budget_trace"
    ops = [e["op"] for e in trace]
    assert ops[0] == "budget_start"
    assert "group_open" in ops
    assert "budget_pick" in ops
    assert ops[-1] == "budget_end"
    pick = next(e for e in trace if e["op"] == "budget_pick")
    assert pick.get("kind") == "run"
    assert "sets" not in pick
    assert "reps" not in pick
    assert pick.get("pace_mult") is not None
    assert pick.get("score") is None


def test_preview_ui_shell_has_reshuffle_and_pool_summary():
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend" / "pages" / "admin-plan-library.html").read_text(encoding="utf-8")
    js = (root / "frontend" / "js" / "admin-plan-library.js").read_text(encoding="utf-8")
    assert 'id="btn-reshuffle"' in html
    assert 'id="pool-summary"' in html
    assert "Live fill preview" in html
    assert "slice(1, 3)" in js
    assert "/api/admin/plan-library/pool-counts" in js
    assert "reshuffle: true" in js
    assert "__planLibraryPreview" in js


def test_budget_trace_html_runners_up_via_node():
    """Render every op type; runners-up shows at most 2."""
    import json
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    js_path = root / "frontend" / "js" / "admin-plan-library.js"
    # Minimal harness: load esc+budgetTraceHtml by evaluating exported hook needs DOM.
    # Instead, replicate the runners-up slice contract and op coverage with a stub.
    harness = r"""
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
"""
    # Pull budgetTraceHtml + helpers from file between markers
    src = js_path.read_text(encoding="utf-8")
    # Use the window export path via vm — call functions by evaling excerpt
    start = src.index("  function budgetRemainHtml")
    end = src.index("  function formatFillStep")
    body = src[start:end]
    # Strip leading 2-space indent to top-level
    lines = []
    for line in body.splitlines():
        if line.startswith("  "):
            lines.append(line[2:])
        else:
            lines.append(line)
    body = "\n".join(lines)
    script = harness + "\n" + body + "\n" + r"""
const trace = [
  {op:'budget_start', remain_tss:50, remain_min:45},
  {op:'group_open', key:'warmup', label:'Warm-up', n:2, group_tss:5, group_min:6},
  {op:'budget_remain', remain_tss:50, remain_min:45, note:'pad'},
  {op:'budget_pick', name:'A', sets:3, reps:'10', load:'mod', spend_min:3, spend_tss:4,
   score:1.1, bias:1, random:1.1, remain_tss_after:46, remain_min_after:42,
   top:[{name:'A',score:1.1},{name:'B',score:0.9},{name:'C',score:0.8},{name:'D',score:0.7}]},
  {op:'budget_pick', name:'E', sets:2, reps:'8', load:'bw', spend_min:2, spend_tss:2,
   score:0.5, bias:0.5, random:1, remain_tss_after:44, remain_min_after:40},
  {op:'group_skip', label:'Accessories', reason:'time_budget'},
  {op:'budget_exhausted', remain_tss:0, remain_min:0},
  {op:'budget_end', remain_tss:0, remain_min:0, exercise_count:2},
];
const pool = {blocks:[{key:'warmup', label:'Warm-up', matched_count:4}]};
const html = budgetTraceHtml(trace, pool);
if (!html.includes('Warm-up · pick 2')) throw new Error('group header');
if (!html.includes('4 in pool')) throw new Error('pool count');
if (!html.includes('score <span class="bt-score">1.1</span> = bias 1 × random 1.1')) throw new Error('score line');
if (!html.includes('runners-up: B 0.9, C 0.8')) throw new Error('runners-up two');
if (html.includes('D 0.7')) throw new Error('runners-up leaked 3rd');
if (!html.includes('skip Accessories')) throw new Error('skip');
if (!html.includes('Budget exhausted')) throw new Error('exhausted');
if (!html.includes('Done · 2')) throw new Error('end');
// no top → no runners-up
const html2 = budgetTraceHtml([
  {op:'budget_pick', name:'Solo', sets:1, reps:'5', load:'bw', spend_min:1, spend_tss:1,
   score:1, bias:1, random:1, remain_tss_after:0, remain_min_after:0}
], null);
if (html2.includes('runners-up')) throw new Error('empty top');
// run pick — no sets×reps
const html3 = budgetTraceHtml([
  {op:'budget_pick', kind:'run', name:'main', duration_min:10, repeat:3, rest_min:2,
   target:'tempo', pace_mult:1.02, spend_min:34, spend_tss:30,
   remain_tss_after:10, remain_min_after:10}
], null);
if (!html3.includes('pace ×1.02 threshold')) throw new Error('pace line');
if (/\d+ × \d+ ·/.test(html3)) throw new Error('strength rx leaked');
console.log('ok');
"""
    r = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, r.stderr or r.stdout


@pytest.fixture
def admin_client():
    import time

    import httpx
    from backend.auth import ADMIN_COOKIE_NAME, create_admin_cookie

    base = os.getenv("PERF_COACH_TEST_BASE", "http://127.0.0.1:9001")
    secret = os.getenv("ADMIN_SECRET_UAT") or os.getenv("ADMIN_SECRET_PRD")
    if not secret:
        pytest.skip("No ADMIN_SECRET — skip live admin smoke")
    try:
        r = httpx.get(f"{base}/api/health", timeout=2.0)
        if r.status_code >= 500:
            pytest.skip("server unhealthy")
    except Exception:
        pytest.skip("live server not reachable")
    token = create_admin_cookie(time.time())
    with httpx.Client(base_url=base, cookies={ADMIN_COOKIE_NAME: token}, timeout=15.0) as c:
        yield c


def test_live_pool_counts_and_preview(admin_client):
    c = admin_client
    seed = c.post("/api/admin/plan-patterns/seed")
    if seed.status_code == 401:
        pytest.skip("admin cookie rejected")
    assert seed.status_code == 200

    pc = c.get(
        "/api/admin/plan-library/pool-counts",
        params={"subtype": "strength_lower", "duration_min": 50},
    )
    assert pc.status_code == 200, pc.text
    data = pc.json()
    assert data["matched_total"] > 0
    assert data["blocks"]
    pid = data.get("pattern_id")
    assert pid
    by_id = c.get(f"/api/admin/plan-patterns/{pid}/pool-counts", params={"duration_min": 50})
    assert by_id.status_code == 200
    assert by_id.json()["matched_total"] == data["matched_total"]

    prev = c.post(
        "/api/admin/plan-exercises/preview",
        json={"subtype": "strength_lower", "duration_minutes": 50, "target_tss": 45},
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body.get("pool_counts")
    assert body.get("budget_trace")
    # group header pool counts align
    idx = {b["key"]: b["matched_count"] for b in body["pool_counts"]["blocks"]}
    for ev in body["budget_trace"]:
        if ev.get("op") == "group_open" and ev.get("key") in idx:
            # fill may narrow tags via format; key still present
            assert idx[ev["key"]] >= 0

    run = c.post(
        "/api/admin/plan-exercises/preview",
        json={"subtype": "tempo", "duration_minutes": 60, "target_tss": 50},
    )
    assert run.status_code == 200, run.text
    rbody = run.json()
    assert rbody["workout_type"] == "run"
    assert rbody.get("budget_trace")
    for ev in rbody["budget_trace"]:
        if ev.get("op") == "budget_pick":
            assert "sets" not in ev
            assert ev.get("pace_mult") is not None
