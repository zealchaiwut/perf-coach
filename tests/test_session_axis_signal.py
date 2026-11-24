"""Session drawer fitness signal: 7 axes, one source per row."""
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from backend.services.radar_payload import AXIS_LABELS, build_axes
from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.score_format import display_score
from backend.services.session_axis_signal import (
    DELTA_STATUSES,
    NO_DELTA_STATUSES,
    axis_signal_summary,
    session_axis_signal,
)
from backend.services.zone_constants import make_zone_constants

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 24)
SCORES = {
    "endurance": 47,
    "speed": 52,
    "economy": 42,
    "strength": 25,
    "mobility": None,
    "power_to_weight": 91,
    "durability": None,
}
ZC = make_zone_constants()
PREFS = {
    "ftp_w": 200,
    "threshold_hr": 165,
    "threshold_pace_seconds_per_km": 300,
}


def _workout(**kw):
    base = dict(
        id="sess-1",
        user_id="user-1",
        workout_type="run",
        workout_date=TODAY,
        duration_seconds=3763,
        zone2_minutes=10,
        name="Tempo 6 mins x 3",
        exercises=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _easy_run(run_id, day="2026-11-10"):
    return {
        "run_id": run_id,
        "workout_date": day,
        "duration_seconds": 4200,
        "laps": [{
            "band": "easy",
            "avg_power": 180,
            "avg_hr": 140.0,
            "distance_km": 2.0,
            "duration_seconds": 540.0,
        }],
        "decoupling_pct": 5.0,
        "avg_power": 180,
        "avg_hr": 140.0,
        "distance_km": 10.0,
    }


def _interval_laps():
    # 4:58 /km × 6 min (358 s / 1.203 km ≈ 297.6 s/km)
    return [{
        "band": "interval",
        "avg_power": 280,
        "avg_hr": 176.0,
        "distance_km": 1.203,
        "duration_seconds": 358.0,
    } for _ in range(3)]


def _hard_run(run_id, day="2026-11-08"):
    return {
        "run_id": run_id,
        "workout_date": day,
        "duration_seconds": 2400,
        "laps": [{
            "band": "interval",
            "avg_power": 250,
            "avg_hr": 170.0,
            "distance_km": 1.0,
            "duration_seconds": 330.0,
        }],
        "avg_power": 250,
        "avg_hr": 170.0,
        "distance_km": 5.0,
        "speed_signal": 1.12,
        "speed_signal_basis": "pace",
        "speed_signal_window_seconds": 360,
    }


def _assert_row_invariants(rows):
    assert [r["axis"] for r in rows] == list(AXIS_LABELS)
    for r in rows:
        assert r["reason"], r
        if r["status"] in DELTA_STATUSES:
            assert r["delta"] is not None, r
        if r["status"] in NO_DELTA_STATUSES:
            assert r["delta"] is None, r


def test_tempo_run_speed_raised_endurance_has_hard_efforts():
    tempo = {
        "run_id": "sess-1",
        "workout_date": "2026-11-22",
        "duration_seconds": 3763,
        "laps": _interval_laps(),
        "avg_power": 280,
        "avg_hr": 176.0,
        "distance_km": 9.0,
    }
    easy = [_easy_run(f"e{i}", f"2026-11-0{i+1}") for i in range(3)]
    hards = [_hard_run(f"h{i}", f"2026-11-1{i}") for i in range(3)]
    e_res = compute_endurance_score(easy + [tempo], PREFS, ZC)
    s_res = compute_speed_score(hards + [tempo], PREFS, ZC)
    assert e_res["run_skip_reasons"]["sess-1"] == "has_hard_efforts"
    w = _workout(id="sess-1", duration_seconds=3763, zone2_minutes=8)
    rows = session_axis_signal(
        None, w, TODAY, endurance_result=e_res, speed_result=s_res, scores=SCORES
    )
    _assert_row_invariants(rows)
    by = {r["axis"]: r for r in rows}
    assert by["speed"]["status"] == "raised"
    assert by["speed"]["delta"] is not None and by["speed"]["delta"] > 0
    assert "4:58" in by["speed"]["reason"] or "raised" in by["speed"]["reason"]
    assert by["endurance"]["status"] == "not_counted"
    assert "has_hard_efforts" in e_res["run_skip_reasons"]["sess-1"]
    assert "tempo" in by["endurance"]["reason"] or "interval" in by["endurance"]["reason"] or "hard" in by["endurance"]["reason"]
    assert by["strength"]["status"] == "not_this_kind"
    assert "lifts" in by["strength"]["reason"].lower() or "anchor" in by["strength"]["reason"].lower()
    assert axis_signal_summary(rows)["total"] == 7
    assert axis_signal_summary(rows)["moved"] == sum(
        1 for r in rows if r["status"] in ("raised", "lowered", "first")
    )


def test_easy_61_min_durability_mentions_minutes():
    easy_w = _workout(
        id="easy-1",
        name="Lunch Run",
        duration_seconds=61 * 60,
        zone2_minutes=50,
    )
    easy_runs = [_easy_run(f"e{i}", f"2026-11-0{i+1}") for i in range(3)]
    this = {
        "run_id": "easy-1",
        "workout_date": "2026-11-21",
        "duration_seconds": 61 * 60,
        "laps": [{
            "band": "easy",
            "avg_power": 175,
            "avg_hr": 138.0,
            "distance_km": 2.0,
            "duration_seconds": 560.0,
        }],
        "decoupling_pct": 4.0,
        "avg_power": 175,
        "avg_hr": 138.0,
        "distance_km": 7.15,
    }
    e_res = compute_endurance_score(easy_runs + [this], PREFS, ZC)
    s_res = compute_speed_score(easy_runs + [this], PREFS, ZC)
    assert s_res["run_skip_reasons"].get("easy-1") == "no_hard_effort"
    rows = session_axis_signal(
        None, easy_w, TODAY, endurance_result=e_res, speed_result=s_res, scores=SCORES
    )
    _assert_row_invariants(rows)
    by = {r["axis"]: r for r in rows}
    assert by["endurance"]["status"] in ("counted", "raised", "lowered", "first")
    assert by["durability"]["status"] == "not_counted"
    assert "61" in by["durability"]["reason"]
    assert by["speed"]["status"] == "not_counted"


def test_strength_session_raises_and_runs_are_not_this_kind(monkeypatch):
    from backend.services.axis_strength import session_contribution as strength_contrib

    w = _workout(
        id="str-1",
        workout_type="strength",
        name="Strength · lower body",
        duration_seconds=45 * 60,
        exercises=[
            SimpleNamespace(
                name="Back squat",
                weight_kg=80,
                reps=5,
                sets=3,
                sets_json=json.dumps([
                    {"weight": 80, "reps": 5, "type": "working"},
                    {"weight": 80, "reps": 5, "type": "working"},
                    {"weight": 80, "reps": 5, "type": "working"},
                ]),
            )
        ],
    )
    anchors = [{
        "key": "back_squat",
        "label": "Back squat",
        "target_factor": 1.0,
        "match": ["back squat", "squat"],
    }]
    prior = [{
        "workout_date": date(2026, 10, 1),
        "name": "Back squat",
        "sets_json": json.dumps([{"weight": 75, "reps": 5, "type": "working"}]),
        "weight_kg": 75,
        "reps": 5,
        "workout_id": "old",
    }]
    def _contrib(workout, as_of, **kw):
        kw.setdefault("exercises", w.exercises)
        kw.setdefault("prior_rows", prior)
        kw.setdefault("anchors", anchors)
        kw.setdefault("trend_mass_kg", 100.0)
        return strength_contrib(workout, as_of, **kw)

    monkeypatch.setattr("backend.services.axis_strength.session_contribution", _contrib)
    st, delta, reason = _contrib(w, TODAY)
    assert st == "raised"
    assert delta is not None and delta > 0
    assert "80" in reason and "75" in reason

    scores = dict(SCORES)
    scores["strength"] = 27
    rows = session_axis_signal(
        None, w, TODAY,
        exercises=w.exercises,
        scores=scores,
    )
    by = {r["axis"]: r for r in rows}
    assert by["endurance"]["status"] == "not_this_kind"
    assert by["speed"]["status"] == "not_this_kind"
    assert by["economy"]["status"] == "not_this_kind"
    assert by["durability"]["status"] == "not_this_kind"
    assert by["power_to_weight"]["status"] == "not_this_kind"
    assert by["strength"]["status"] == "raised"
    assert by["strength"]["delta"] is not None
    _assert_row_invariants(rows)


def test_delta_present_iff_counted_status():
    w = _workout()
    rows = session_axis_signal(
        None, w, TODAY,
        endurance_result={
            "run_contributions": {"sess-1": 0.0},
            "run_skip_reasons": {},
        },
        speed_result={
            "run_skip_reasons": {"sess-1": "no_hard_effort"},
            "run_contributions": {},
        },
        scores=SCORES,
    )
    _assert_row_invariants(rows)


def test_scores_match_performance_radar_display():
    overall = {
        "endurance": {"score": 46.6, "stale": False},
        "speed": {"score": 52.4, "stale": False},
    }
    axis_blocks = {
        "economy": {"score": 42.0, "stale": False},
        "strength": {"score": 25.2, "stale": False},
        "mobility": {"score": None, "never_measured": True, "stale": True},
        "power_to_weight": {"score": 91.0, "stale": False},
        "durability": {"score": None, "never_measured": True, "stale": True},
    }
    axes = build_axes(overall, axis_blocks, {k: None for k in AXIS_LABELS})
    radar = {a["axis"]: a["score_display"] for a in axes}
    w = _workout()
    rows = session_axis_signal(
        None, w, TODAY,
        endurance_result={"run_skip_reasons": {"sess-1": "has_hard_efforts"}, "run_skip_detail": {"sess-1": {"hard_desc": "3 × 6 min at tempo"}}},
        speed_result={"run_contributions": {"sess-1": 3.5}, "run_effort": {"sess-1": {"pace_s_per_km": 298, "duration_seconds": 360}}},
        scores={
            k: (overall.get(k) or axis_blocks.get(k) or {}).get("score")
            for k in AXIS_LABELS
        },
    )
    for row in rows:
        assert row["score"] == radar[row["axis"]]
        assert row["score"] == display_score(
            overall.get(row["axis"], axis_blocks.get(row["axis"], {})).get("score")
        )


def test_js_seven_rows_tooltip_click_and_outside(tmp_path):
    payload = {
        "workout_type": "run",
        "axis_signal_summary": {"moved": 1, "total": 7},
        "axis_signal": [
            {"axis": "endurance", "label": "Endurance", "score": 47, "status": "not_counted", "delta": None,
             "reason": "Endurance uses steady runs; this one had 3 × 6 min at tempo."},
            {"axis": "speed", "label": "Speed", "score": 52, "status": "raised", "delta": 3.5,
             "reason": "6 min at 4:58 /km is a new Speed anchor and raised the score by 3.5."},
            {"axis": "economy", "label": "Economy", "score": 42, "status": "not_counted", "delta": None,
             "reason": "Economy uses easy runs with Stryd form data."},
            {"axis": "strength", "label": "Strength", "score": 25, "status": "not_this_kind", "delta": None,
             "reason": "Strength moves with logged lifts and anchor tests."},
            {"axis": "mobility", "label": "Mobility", "score": None, "status": "not_measured", "delta": None,
             "reason": "Mobility comes from tests, not sessions."},
            {"axis": "power_to_weight", "label": "Power/wt", "score": 91, "status": "not_counted", "delta": None,
             "reason": "Uses CP and the weight trend."},
            {"axis": "durability", "label": "Durability", "score": None, "status": "not_counted", "delta": None,
             "reason": "Needs an easy run of 90 min or more."},
        ],
    }
    script = r"""
const fs = require('fs');
const vm = require('vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = {
  window: null,
  console,
  document: {
    addEventListener(type, fn) { sandbox._docListeners[type] = sandbox._docListeners[type] || []; sandbox._docListeners[type].push(fn); },
    querySelector() { return null; },
  },
  AppCommon: {
    escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
  },
};
sandbox._docListeners = {};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const html = sandbox.RunDetailView.renderFitnessSignal(payload);
if ((html.match(/role="listitem"/g) || []).length !== 7) throw new Error('need 7 rows');
if (html.indexOf('rd4-signal-note') !== -1) throw new Error('caption note leaked');
if (html.indexOf('No signal recorded') !== -1) throw new Error('empty-state leaked');
if (html.indexOf('rd4-new-badge') !== -1) throw new Error('NEW badge');
if (html.indexOf('role="button"') !== -1) throw new Error('section must not be a button');
if (html.indexOf('3 × 6 min at tempo') === -1) throw new Error('reason missing from tooltip html');
// Reason must live in the bubble, not in the axis/score cells.
const ax = html.match(/rd4-signal-ax">[^<]+/g).join(' ');
if (ax.indexOf('tempo') !== -1) throw new Error('reason visible in axis name');

function el(cls, extra) {
  extra = extra || {};
  const node = {
    className: cls,
    parent: extra.parent || null,
    children: extra.children || [],
    _attrs: Object.assign({'aria-expanded': 'false'}, extra.attrs || {}),
    listeners: {},
    textContent: extra.text || '',
    classList: {
      add(c) { if ((' '+node.className+' ').indexOf(' '+c+' ') < 0) node.className += ' '+c; },
      remove(c) { node.className = node.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
      contains(c) { return (' '+node.className+' ').indexOf(' '+c+' ') >= 0; },
    },
    setAttribute(k, v) { node._attrs[k] = v; },
    getAttribute(k) { return node._attrs[k]; },
    addEventListener(type, fn) { (node.listeners[type] = node.listeners[type] || []).push(fn); },
    querySelector(sel) {
      const want = sel.replace('.', '');
      if ((' '+this.className+' ').indexOf(' '+want+' ') >= 0) return this;
      for (const c of this.children) {
        const hit = c.querySelector(sel);
        if (hit) return hit;
      }
      return null;
    },
    querySelectorAll(sel) {
      const tokens = sel.replace(/^\./, '').split('.').filter(Boolean);
      const out = [];
      const walk = (n) => {
        const parts = n.className.split(/\s+/);
        if (tokens.every(t => parts.indexOf(t) >= 0)) out.push(n);
        n.children.forEach(walk);
      };
      walk(this);
      return out;
    },
    closest(sel) {
      const want = sel.replace('.', '');
      let n = this;
      while (n) {
        if ((' '+n.className+' ').indexOf(' '+want+' ') >= 0) return n;
        n = n.parent;
      }
      return null;
    },
    contains(other) {
      if (other === this) return true;
      return this.children.some(c => c.contains(other));
    },
  };
  node.children.forEach(c => { c.parent = node; });
  return node;
}

const bub = el('rd4-signal-bub', { text: '6 min at 4:58 /km is a new Speed anchor and raised the score by 3.5.' });
const btn = el('rd4-signal-i');
const row = el('rd4-signal-row', { children: [btn, bub] });
btn.parent = row; bub.parent = row;
const card = el('rd4-signal', { children: [row] });
row.parent = card;
const root = { querySelector(sel) { return sel.indexOf('rd4-signal') >= 0 ? card : null; } };
sandbox.document.addEventListener = function (type, fn) {
  sandbox._docListeners[type] = sandbox._docListeners[type] || [];
  sandbox._docListeners[type].push(fn);
};
sandbox.RunDetailView.wireFitnessSignal(root);
const clickEvt = { target: btn, preventDefault() {}, stopPropagation() {} };
(card.listeners.click || []).forEach(fn => fn(clickEvt));
if (!bub.classList.contains('is-open')) throw new Error('click i should open bubble');
(sandbox._docListeners.click || []).forEach(fn => fn({ target: { closest() { return null; } } }));
if (bub.classList.contains('is-open')) throw new Error('outside click should close');
console.log('ok');
"""
    proc = subprocess.run(
        ["node", "-e", script, str(REPO / "frontend" / "js" / "lib" / "run-detail-view.js")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "ok" in proc.stdout
