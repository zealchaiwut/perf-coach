"""Coach brief v4 — assemble, hash, persist, retrieve structured JSON briefs."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.utils.log import get_logger

_log = get_logger(__name__)

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
SCHEMA_VERSION = 4

CLOSING_QUESTION = (
    "How's sleep? Resting HR? And what do your legs feel like "
    "when you first stand up in the morning?"
)


def _stable_json(obj: Any) -> str:
    """Stable serialization for hashing (sorted keys, rounded floats)."""

    def _norm(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, dict):
            return {str(k): _norm(v[k]) for k in sorted(v.keys(), key=str)}
        if isinstance(v, (list, tuple)):
            return [_norm(x) for x in v]
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return v

    return json.dumps(_norm(obj), separators=(",", ":"), ensure_ascii=False)


def fact_hash_for_section(section_facts: dict) -> str:
    raw = _stable_json(section_facts or {})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def derive_today_chips(facts: dict) -> list[dict]:
    """Deterministic chips for the Today strip (status only; no weigh-in/deload pills)."""
    chips: list[dict] = []
    load = facts.get("load") or {}

    # Weigh-in + deload status live in the brief / today_verdict — not as strip pills.
    unlock = load.get("unlock_date")
    if unlock and load.get("state") == "locked":
        try:
            d = date.fromisoformat(str(unlock)[:10])
            chips.append({
                "kind": "load_unlock",
                "tone": "ok",
                "text": f"LOAD UNLOCKED {d.strftime('%b').upper()} {d.day}",
            })
        except Exception:
            chips.append({
                "kind": "load_unlock",
                "tone": "ok",
                "text": f"LOAD UNLOCKED {unlock}",
            })
    elif load.get("state") == "available" and not load.get("deload_week"):
        chips.append({
            "kind": "load_ok",
            "tone": "ok",
            "text": "LOAD OPEN",
        })

    return chips[:4]


def _top_focus_section_id(facts: dict | None, brief: dict | None = None) -> str | None:
    from backend.services.coach_brief_map import FOCUS_ID_TO_SECTION

    if brief:
        rows = (brief.get("digest") or {}).get("focus") or []
        if rows and isinstance(rows[0], dict):
            sid = rows[0].get("section_id")
            if sid:
                return sid
            fid = rows[0].get("id")
            if fid:
                return FOCUS_ID_TO_SECTION.get(fid)
    if facts:
        fr = (facts.get("focus_ranked") or [None])[0]
        if isinstance(fr, dict) and fr.get("id"):
            return FOCUS_ID_TO_SECTION.get(fr["id"])
    return None


def apply_today_verdict_from_focus(brief: dict, facts: dict | None = None) -> dict:
    """Set today.today_verdict from focus #1 section DO (else headline)."""
    today = brief.setdefault("today", {})
    by_sid = {
        s["id"]: s
        for s in (brief.get("sections") or [])
        if isinstance(s, dict) and s.get("id")
    }
    sid = _top_focus_section_id(facts, brief)
    session = today.get("session") or {}
    if sid and sid in by_sid:
        sec = by_sid[sid]
        line = (sec.get("do") or "").strip() or (sec.get("headline") or "").strip()
        if line:
            today["today_verdict"] = line[:140]
            return brief
    if session.get("name"):
        today["today_verdict"] = (
            f"Today: {session['name']}. Stay on the plan — no extras."
        )[:140]
    elif not (today.get("today_verdict") or "").strip():
        today["today_verdict"] = "Rest or easy only — protect the week."[:140]
    return brief


def apply_open_by_default(brief: dict, facts: dict | None = None) -> dict:
    """Reorder sections by focus priority; mark up to 3 open_by_default."""
    from backend.services.coach_brief_map import FOCUS_ID_TO_SECTION

    sections = [s for s in (brief.get("sections") or []) if isinstance(s, dict)]
    for s in sections:
        s["open_by_default"] = False

    focus_sids: list[str] = []
    seen: set[str] = set()
    for fr in (facts or {}).get("focus_ranked") or []:
        if not isinstance(fr, dict):
            continue
        sid = FOCUS_ID_TO_SECTION.get(fr.get("id") or "")
        if sid and sid not in seen:
            focus_sids.append(sid)
            seen.add(sid)
    for row in (brief.get("digest") or {}).get("focus") or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("section_id") or FOCUS_ID_TO_SECTION.get(row.get("id") or "")
        if sid and sid not in seen:
            focus_sids.append(sid)
            seen.add(sid)

    by_sid = {s["id"]: s for s in sections if s.get("id")}
    ordered: list[dict] = []
    used: set[str] = set()
    for sid in focus_sids:
        s = by_sid.get(sid)
        if s and sid not in used:
            ordered.append(s)
            used.add(sid)
    for s in sections:
        sid = s.get("id")
        if sid and sid not in used:
            ordered.append(s)
            used.add(sid)

    opened = 0
    for s in ordered:
        if opened >= 3:
            break
        if s.get("changed_since_yesterday"):
            s["open_by_default"] = True
            opened += 1

    brief["sections"] = ordered
    return brief


def finalize_brief(brief: dict, facts: dict | None = None) -> dict:
    """Sync digest titles, today verdict, chip order already in skeleton, open flags."""
    sync_digest_with_sections(brief)
    apply_today_verdict_from_focus(brief, facts)
    apply_open_by_default(brief, facts)
    # Refresh chips with focus-aware order if facts available
    if facts is not None and isinstance(brief.get("today"), dict):
        brief["today"]["chips"] = derive_today_chips(facts)
    return brief


def _session_from_facts(facts: dict) -> dict | None:
    """Build today.session from planned next session + chosen preset."""
    ref = facts.get("reflection") or {}
    nxt = ref.get("next_session") or {}
    preset = facts.get("chosen_preset") or {}
    if not nxt and not preset:
        return None
    name = (
        (preset.get("name") if preset else None)
        or nxt.get("name")
        or "Session"
    )
    stype = (preset.get("kind") if preset else None) or nxt.get("type") or "run"
    summary = (preset.get("summary") if preset else None) or ""
    return {
        "name": name,
        "type": stype,
        "summary": summary,
        "date": nxt.get("date") or facts.get("as_of"),
        "planned_session_id": nxt.get("id"),
        "preset_code": (preset or {}).get("code"),
    }


def _fmt_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return None
    if s < 0:
        return None
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m} min"


def _fmt_pace(distance_km: float | None, duration_seconds: int | None) -> str | None:
    if not distance_km or not duration_seconds:
        return None
    try:
        d = float(distance_km)
        sec = int(duration_seconds)
    except (TypeError, ValueError):
        return None
    if d <= 0 or sec <= 0:
        return None
    spk = sec / d  # seconds per km
    mm = int(spk // 60)
    ss = int(round(spk % 60))
    if ss == 60:
        mm += 1
        ss = 0
    return f"{mm}:{ss:02d}/km"


def _praise_for_workout(
    name: str,
    workout_type: str | None,
    run_subtype: str | None = None,
    *,
    distance_km: float | None = None,
    duration_seconds: int | None = None,
) -> str:
    kind = (workout_type or "").lower()
    subtype = (run_subtype or "").lower()
    n = (name or "").lower()
    longish = False
    try:
        longish = (distance_km is not None and float(distance_km) >= 15.0) or (
            duration_seconds is not None and int(duration_seconds) >= 5400
        )
    except (TypeError, ValueError):
        longish = False
    if subtype == "longrun" or "long" in n or "long" in subtype or (kind == "run" and longish):
        return "Good work — long run in the bank."
    if kind in ("run",):
        return "Nice run — that one counts."
    if kind in ("ride", "bike", "cycle"):
        return "Nice ride — that one counts."
    if kind in ("strength", "weights", "gym"):
        return "Solid strength work — well done."
    return "Good work — today's session is logged."


def completed_workout_for_day(user_id, day: date, db: Session | None = None) -> dict | None:
    """Best synced workout on ``day`` (prefer longest duration), or None."""
    from backend.models import Workout

    _own = db is None
    if _own:
        from backend.db import engine
        db = Session(engine)
    try:
        rows = (
            db.query(Workout)
            .filter(Workout.user_id == user_id, Workout.workout_date == day)
            .all()
        )
        if not rows:
            return None

        def _dur_key(w: Any) -> int:
            try:
                return int(w.duration_seconds or 0)
            except (TypeError, ValueError):
                return 0

        w = max(rows, key=lambda r: (_dur_key(r), str(getattr(r, "created_at", None) or "")))
        dist = float(w.distance_km) if w.distance_km is not None else None
        dur = int(w.duration_seconds) if w.duration_seconds is not None else None
        tss = float(w.tss) if w.tss is not None else None
        name = w.name or w.workout_type or "Workout"
        wtype = w.workout_type or "run"
        subtype = getattr(w, "run_subtype", None)
        stats: list[str] = []
        dlabel = _fmt_duration(dur)
        if dlabel:
            stats.append(dlabel)
        if dist is not None and dist > 0:
            stats.append(f"{dist:.1f} km")
        pace = _fmt_pace(dist, dur)
        if pace:
            stats.append(pace)
        if tss is not None:
            stats.append(f"{int(round(tss))} TSS")
        return {
            "id": str(w.id),
            "name": name,
            "type": wtype,
            "run_subtype": subtype,
            "distance_km": dist,
            "duration_seconds": dur,
            "duration_label": dlabel,
            "pace_label": pace,
            "tss": tss,
            "stats_line": " · ".join(stats),
            "praise": _praise_for_workout(
                name, wtype, subtype, distance_km=dist, duration_seconds=dur
            ),
            "source": getattr(w, "source", None),
        }
    finally:
        if _own:
            db.close()


def attach_completed_workout(brief: dict, user_id, db: Session | None = None) -> dict:
    """Live-attach today's synced workout + plan nudge onto brief['today']."""
    today_block = brief.setdefault("today", {})
    try:
        day = date.fromisoformat(str(brief.get("brief_date") or date.today())[:10])
    except ValueError:
        day = date.today()
    today_block["completed_workout"] = completed_workout_for_day(user_id, day, db=db)
    today_block["planned_today"] = planned_today_for_day(user_id, day, db=db)
    return brief


def planned_today_for_day(user_id, day: date, db: Session | None = None) -> dict | None:
    """Active planned session for ``day`` (workout nudge or rest), or None."""
    from backend.models import PlannedSession

    _own = db is None
    if _own:
        from backend.db import engine
        db = Session(engine)
    try:
        rows = (
            db.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user_id,
                PlannedSession.planned_date == day,
            )
            .all()
        )
        if not rows:
            return None
        done = {"done_auto", "done_manual", "skipped"}
        active = [
            r
            for r in rows
            if (r.status or "planned") not in done
        ]
        if not active:
            return None

        def _is_rest(r: Any) -> bool:
            return (r.session_type or "").lower() == "rest"

        workouts = [r for r in active if not _is_rest(r)]
        if workouts:
            # Prefer run > strength > other when multiple
            priority = {"run": 0, "plyo": 1, "strength": 2, "stretch": 3}
            workouts.sort(
                key=lambda r: (
                    priority.get((r.session_type or "").lower(), 9),
                    r.name or "",
                )
            )
            w = workouts[0]
            name = w.name or (w.session_type or "Session").title()
            stype = (w.session_type or "run").lower()
            return {
                "kind": "workout",
                "id": str(w.id),
                "name": name,
                "type": stype,
                "date": day.isoformat(),
                "status": w.status or "planned",
                "nudge": "Still on the plan for today — get this one done.",
                "summary": (w.notes or "").strip() or None,
            }

        r = next((x for x in active if _is_rest(x)), active[0])
        return {
            "kind": "rest",
            "id": str(r.id),
            "name": r.name or "Rest day",
            "type": "rest",
            "date": day.isoformat(),
            "status": r.status or "planned",
            "nudge": "Rest day — recover well. No training needed.",
            "summary": (r.notes or "").strip() or None,
        }
    finally:
        if _own:
            db.close()


def _digest_focus(facts: dict) -> list[dict]:
    """Top 3 focus_ranked → digest.focus rows (titles synced to section headlines later)."""
    from backend.services.coach_brief_map import FOCUS_ID_TO_SECTION

    out: list[dict] = []
    for fr in (facts.get("focus_ranked") or [])[:3]:
        tr = fr.get("tracking") or {}
        progress = None
        state = "pending"
        if tr.get("current") is not None and tr.get("target") is not None:
            try:
                cur = float(tr["current"])
                tgt = float(tr["target"])
                progress = {
                    "current": cur,
                    "target": tgt,
                    "label": f"{int(cur) if cur == int(cur) else cur} / "
                    f"{int(tgt) if tgt == int(tgt) else tgt}",
                }
                if cur >= tgt:
                    state = "done"
            except (TypeError, ValueError):
                progress = None
        fid = fr.get("id")
        out.append({
            "rank": int(fr.get("rank") or len(out) + 1),
            "title": fr.get("label") or fid or "Focus",
            "why": (fr.get("rationale") or "")[:120],
            "progress": progress,
            "state": state,
            "id": fid,
            "section_id": FOCUS_ID_TO_SECTION.get(fid) if fid else None,
        })
    return out


def sync_digest_with_sections(brief: dict) -> dict:
    """Copy section headlines (and short evidence) onto matching digest focus rows.

    Keeps digest and full brief from disagreeing on what #1 / #2 / #3 say.
    """
    from backend.services.coach_brief_map import FOCUS_ID_TO_SECTION

    by_sid = {
        s["id"]: s
        for s in (brief.get("sections") or [])
        if isinstance(s, dict) and s.get("id")
    }
    digest = brief.setdefault("digest", {})
    for row in digest.get("focus") or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("section_id") or FOCUS_ID_TO_SECTION.get(row.get("id") or "")
        if not sid:
            continue
        sec = by_sid.get(sid)
        if not sec:
            continue
        row["section_id"] = sid
        headline = (sec.get("headline") or "").strip()
        if headline:
            row["title"] = headline[:90]
        evidence = (sec.get("evidence") or "").strip()
        if evidence:
            # One short beat under the shared headline — not a third essay
            row["why"] = evidence[:120]
    return brief


def apply_changed_flags(
    sections: list[dict],
    yesterday_payload: dict | None,
) -> list[dict]:
    """Set changed_since_yesterday from yesterday's section fact_hashes."""
    ymap: dict[str, str] = {}
    if yesterday_payload and isinstance(yesterday_payload.get("sections"), list):
        for s in yesterday_payload["sections"]:
            if isinstance(s, dict) and s.get("id") and s.get("fact_hash"):
                ymap[s["id"]] = s["fact_hash"]
    for s in sections:
        prev = ymap.get(s["id"])
        if prev is None:
            s["changed_since_yesterday"] = True
        else:
            s["changed_since_yesterday"] = s.get("fact_hash") != prev
    return sections


def build_brief_skeleton(facts: dict, yesterday_payload: dict | None = None) -> dict:
    """Deterministic v4 skeleton (empty LLM atoms)."""
    from backend.services.coach_brief_map import (
        build_sections,
        collect_section_facts,
    )

    section_facts = collect_section_facts(facts)
    facts["section_facts"] = section_facts

    sections = build_sections(facts)
    for s in sections:
        sid = s["id"]
        s["fact_hash"] = fact_hash_for_section(section_facts.get(sid) or {})
    apply_changed_flags(sections, yesterday_payload)

    nxt = (facts.get("reflection") or {}).get("next_session") or {}
    serves = nxt.get("serves_focus_rank")

    brief_date = facts.get("as_of") or date.today().isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "brief_date": brief_date,
        "today": {
            "session": _session_from_facts(facts),
            "today_verdict": "",
            "serves_focus_rank": serves,
            "chips": derive_today_chips(facts),
        },
        "digest": {
            "week_verdict": "",
            "week_verdict_sub": "",
            "focus": _digest_focus(facts),
        },
        "sections": sections,
        "closing_question": CLOSING_QUESTION,
        "source": "pending",
    }


def merge_llm_atoms(skeleton: dict, atoms: dict, facts: dict | None = None) -> dict:
    """Fill LLM prose atoms into the deterministic skeleton."""
    brief = json.loads(json.dumps(skeleton))  # deep copy via JSON
    today = brief.setdefault("today", {})
    digest = brief.setdefault("digest", {})
    if atoms.get("today_verdict"):
        today["today_verdict"] = str(atoms["today_verdict"]).strip()[:140]
    if atoms.get("week_verdict"):
        digest["week_verdict"] = str(atoms["week_verdict"]).strip()[:90]
    if atoms.get("week_verdict_sub"):
        digest["week_verdict_sub"] = str(atoms["week_verdict_sub"]).strip()[:110]

    by_id = {
        s["id"]: s
        for s in (atoms.get("sections") or [])
        if isinstance(s, dict) and s.get("id")
    }
    # Also accept flat map sections.<id>.{headline,evidence,do}
    flat = atoms.get("section_atoms") or {}
    for s in brief.get("sections") or []:
        a = by_id.get(s["id"]) or flat.get(s["id"]) or {}
        if a.get("headline"):
            s["headline"] = str(a["headline"]).strip()[:60]
        if a.get("evidence"):
            s["evidence"] = str(a["evidence"]).strip()[:280]
        if a.get("do"):
            s["do"] = str(a["do"]).strip()[:140]
    # Prefer deterministic today_verdict from focus #1 DO over LLM drift
    return finalize_brief(brief, facts)


def _longrun_fade_evidence(facts: dict) -> str:
    """Coach prose only — durations / dates live on evidence_strip."""
    vm = facts.get("volume_mix") or {}
    longs = vm.get("recent_longs") or []
    if vm.get("missing_long") or not longs:
        return (
            "You're short on long-run volume right now. Get one easy long on the "
            "calendar first — fueling tips can wait until that session exists."
        )
    return (
        "You're already doing the long runs — that box is checked. What still "
        "costs you late in the race is fading when fueling slips. Treat mid-run "
        "gels or drink as part of the workout, not optional."
    )


def _longrun_fade_do(facts: dict) -> str:
    vm = facts.get("volume_mix") or {}
    if vm.get("missing_long") or not (vm.get("recent_longs") or []):
        return "Schedule one easy long (≥90 min or ≥14 km) this week."
    return "Gels or drink from minute 40 on every long run."


def _weight_gate_evidence(facts: dict) -> str:
    """Coach prose only — logged counts / kg live on evidence_strip."""
    w = facts.get("weight") or {}
    direction = (w.get("gap_direction") or "").lower()
    if direction == "behind":
        beat = (
            "You're a little heavy vs the plan line — noted, but don't turn that "
            "into a crash diet today."
        )
    elif direction == "ahead":
        beat = (
            "You're ahead of the plan line — nice — still don't invent a bigger cut."
        )
    elif direction == "on_plan":
        beat = "You're roughly on the plan line — keep the boring consistency."
    else:
        beat = "Use the numbers below for where you sit vs plan."
    return (
        f"{beat} Food talk waits until morning weigh-ins are consistent. "
        "Any race-time upside from cutting later is a prize after the gate — "
        "not this morning's weigh target."
    )


def _weight_gate_do(facts: dict) -> str:
    w = facts.get("weight") or {}
    window = w.get("window_days") or 14
    gate = max(12, int(window) - 2) if window else 12
    return (
        f"Weigh in this morning before coffee. No calorie change until {gate}/{gate}."
    )


def compose_coach_brief(facts: dict, yesterday_payload: dict | None = None) -> dict:
    """Deterministic fallback — same v4 JSON shape as LLM path."""
    skel = build_brief_skeleton(facts, yesterday_payload)
    load = facts.get("load") or {}

    if load.get("deload_week"):
        skel["digest"]["week_verdict"] = "Deload is doing its job. Don't refill it."[:90]
        skel["digest"]["week_verdict_sub"] = (
            "Load is down on purpose. Resume the ramp Monday at 5%/week — no catching up."
        )[:110]
    else:
        skel["digest"]["week_verdict"] = "Hold the main levers. Don't invent work."[:90]
        skel["digest"]["week_verdict_sub"] = (
            "Top focus first; everything else is noise this week."
        )[:110]

    templates = {
        "load_deload": {
            "headline": "Hold the deload — don't refill the week"[:60],
            "evidence": (
                "You're on a deload week. Resting matters more than it feels — "
                "this quiet is the plan working, not a gap to fill. Hold the load; "
                "you get the 5%/week ramp back next week."
            )[:280],
            "do": "Today's session easy, nothing extra. Ramp resumes at 5%/week."[:140],
        },
        "weight_gate": {
            "headline": "Weigh-ins are the gate to the food conversation"[:60],
            "evidence": _weight_gate_evidence(facts)[:280],
            "do": _weight_gate_do(facts)[:140],
        },
        "longrun_fade": {
            "headline": (
                "Long-run volume is short — put one on the calendar"
                if (facts.get("volume_mix") or {}).get("missing_long")
                else "Long runs: the late fade is the fixable part"
            )[:60],
            "evidence": _longrun_fade_evidence(facts)[:280],
            "do": _longrun_fade_do(facts)[:140],
        },
        "season": {
            "headline": "Season — stay on the A-race line"[:60],
            "evidence": (
                "Checkpoints are progress checks toward the A-race, not separate seasons. "
                "Same engine as the Performance tab."
            )[:280],
            "do": "Nothing today. This section reopens when an estimate or date moves."[:140],
        },
        "week_review": {
            "headline": "Last week in review"[:60],
            "evidence": (
                "Credit the quality sessions worth keeping. One quiet week doesn't undo fitness."
            )[:280],
            "do": "Keep the strength + quality combination. Everything else was fine."[:140],
        },
    }
    if not load.get("deload_week"):
        templates["load_deload"] = {
            "headline": "Protect the load ramp"[:60],
            "evidence": (
                "Stay under the ceiling and avoid catch-up weeks. Consistency beats spikes."
            )[:280],
            "do": "Hit today's planned work; skip add-ons."[:140],
        }

    for s in skel.get("sections") or []:
        if s.get("type") == "proposal" or str(s.get("id") or "").startswith("proposal_"):
            # Deterministic why fallback — LLM may replace with ≤140 char sentence
            delta = (s.get("proposal") or {}).get("delta") or {}
            field = delta.get("field") or "preference"
            s["evidence"] = (
                f"This gap has persisted long enough that a small step in "
                f"{field.replace('_', ' ').replace('.', ' ')} is worth trying."
            )[:140]
            s["do"] = ""
            continue
        t = templates.get(s["id"]) or {}
        s["headline"] = t.get("headline", s["id"].replace("_", " ").title())[:60]
        s["evidence"] = t.get("evidence", "")[:280]
        s["do"] = t.get("do", "")[:140]

    skel["source"] = "fallback"
    skel["closing_question"] = CLOSING_QUESTION
    return finalize_brief(skel, facts)


def brief_to_text(brief: dict) -> str:
    """Render v4 JSON → legacy four-header Markdown for Hermes / export."""
    today = brief.get("today") or {}
    digest = brief.get("digest") or {}
    sections = {s["id"]: s for s in (brief.get("sections") or []) if s.get("id")}

    now_parts: list[str] = []
    if today.get("today_verdict"):
        now_parts.append(today["today_verdict"])
    for sid in ("load_deload",):
        s = sections.get(sid)
        if s and (s.get("headline") or s.get("evidence")):
            now_parts.append(
                f"{s.get('headline', '').strip()}\n{s.get('evidence', '').strip()}".strip()
            )
            if s.get("do"):
                now_parts.append(f"Do: {s['do']}")

    focus_parts: list[str] = []
    if digest.get("week_verdict"):
        focus_parts.append(digest["week_verdict"])
    if digest.get("week_verdict_sub"):
        focus_parts.append(digest["week_verdict_sub"])
    for f in digest.get("focus") or []:
        line = f"{f.get('rank')}. {f.get('title')}"
        if f.get("why"):
            line += f" — {f['why']}"
        focus_parts.append(line)
    for sid in ("weight_gate", "longrun_fade"):
        s = sections.get(sid)
        if s and s.get("evidence"):
            focus_parts.append(f"{s.get('headline', '')}: {s['evidence']}".strip())

    dream_parts: list[str] = []
    s = sections.get("season")
    if s:
        if s.get("headline"):
            dream_parts.append(s["headline"])
        if s.get("evidence"):
            dream_parts.append(s["evidence"])

    ref_parts: list[str] = []
    s = sections.get("week_review")
    if s:
        if s.get("headline"):
            ref_parts.append(s["headline"])
        if s.get("evidence"):
            ref_parts.append(s["evidence"])
        if s.get("do"):
            ref_parts.append(f"Do: {s['do']}")
    cq = brief.get("closing_question") or CLOSING_QUESTION
    ref_parts.append(cq)

    from backend.services.coach_sections import sections_to_text

    return sections_to_text({
        "now": "\n\n".join(p for p in now_parts if p) or "—",
        "focus": "\n\n".join(p for p in focus_parts if p) or "—",
        "dream": "\n\n".join(p for p in dream_parts if p) or "—",
        "reflection": "\n\n".join(p for p in ref_parts if p) or "—",
    })


def get_yesterday_brief_payload(db: Session, user_id, brief_date: date) -> dict | None:
    from backend.models import DailyBrief

    y = brief_date - timedelta(days=1)
    row = (
        db.query(DailyBrief)
        .filter(DailyBrief.user_id == user_id, DailyBrief.brief_date == y)
        .first()
    )
    if row and isinstance(row.payload, dict):
        return row.payload
    return None


def persist_daily_brief(
    db: Session,
    user_id,
    brief_date: date,
    payload: dict,
    source: str,
) -> Any:
    from backend.models import DailyBrief

    row = (
        db.query(DailyBrief)
        .filter(DailyBrief.user_id == user_id, DailyBrief.brief_date == brief_date)
        .first()
    )
    if row is None:
        row = DailyBrief(
            user_id=user_id,
            brief_date=brief_date,
            payload=payload,
            source=source or "fallback",
        )
        db.add(row)
    else:
        row.payload = payload
        row.source = source or "fallback"
    db.flush()
    return row


def build_brief_deterministic(
    facts: dict,
    *,
    db: Session | None = None,
    user_id=None,
    brief_date: date | None = None,
) -> dict:
    """Build a v4 brief with no LLM, and persist it when given a db.

    Replaces ``coach_narrative.generate_brief`` on every live path (Priority 2,
    D4). Same return shape, so callers did not have to change: ``brief``,
    ``text``, ``sections``, ``source``, ``attempts``, ``orch``,
    ``chosen_preset``. ``source`` is always "fallback" and ``attempts`` always
    0 — there is nothing to attempt.

    This is exactly the branch ``generate_brief`` already took whenever the LLM
    was off, unreachable, or produced atoms that failed validation. Parking the
    LLM makes that branch the only branch; it does not introduce a new one.
    """
    from datetime import date as _date

    from backend.services.coach_sections import apply_chosen_preset

    brief_date = brief_date or _date.fromisoformat(
        str(facts.get("as_of") or _date.today().isoformat())[:10]
    )
    yesterday = None
    if db is not None and user_id is not None:
        yesterday = get_yesterday_brief_payload(db, user_id, brief_date)

    brief = compose_coach_brief(facts, yesterday)
    # None = take the first active preset. The LLM's pick was validated against
    # the same list and fell back here whenever it was absent or rejected.
    apply_chosen_preset(facts, None)

    finalize_brief(brief, facts)
    brief["source"] = "fallback"

    text = brief_to_text(brief)
    if db is not None and user_id is not None:
        try:
            persist_daily_brief(db, user_id, brief_date, brief, "fallback")
        except Exception as exc:
            _log.warning("persist daily_brief failed: %s", exc)
            # A failed persist (e.g. unique-constraint race on
            # (user_id, brief_date)) aborts the transaction; roll back so the
            # caller's later db.commit() doesn't raise on a poisoned session.
            try:
                db.rollback()
            except Exception:
                pass

    from backend.services.coach_sections import parse_sections_from_text

    return {
        "brief": brief,
        "text": text,
        "sections": parse_sections_from_text(text),
        "source": "fallback",
        "attempts": 0,
        "orch": "deterministic",
        "chosen_preset": facts.get("chosen_preset"),
    }


def get_or_build_brief(
    db: Session,
    user_id,
    brief_date: date | None = None,
    *,
    force: bool = False,
) -> dict | None:
    """Return stored v4 brief; build on demand if missing."""
    from backend.models import DailyBrief
    from backend.services.coach_facts import build_coach_facts

    brief_date = brief_date or datetime.now(BANGKOK_TZ).date()
    if not force:
        row = (
            db.query(DailyBrief)
            .filter(
                DailyBrief.user_id == user_id,
                DailyBrief.brief_date == brief_date,
            )
            .first()
        )
        if row and isinstance(row.payload, dict) and row.payload.get("schema_version") == 4:
            return attach_completed_workout(dict(row.payload), user_id, db=db)

    facts = build_coach_facts(user_id, today=brief_date, db=db)
    if facts is None:
        return None
    result = build_brief_deterministic(
        facts, db=db, user_id=user_id, brief_date=brief_date
    )
    brief = result.get("brief")
    if brief is None:
        return None
    return attach_completed_workout(brief, user_id, db=db)
