"""Evidence-text serializer for gap-analysis findings (issue #1374).

render_evidence_text(code, evidence, target) → str
  Turns the machine-readable evidence list for a given rule code into a single
  deterministic English sentence for the UI panel.

sort_findings_for_panel(findings) → list[dict]
  Returns findings sorted severity desc, then code asc, ready for the frontend
  to take [:3] for the top-three panel.
"""
from __future__ import annotations


# ── Helpers ───────────────────────────────────────────────────────────────────

def _v(ev: dict, metric: str):
    """Return the value for a metric from the evidence dict (keyed by metric name)."""
    entry = ev.get(metric)
    if entry is None:
        return None
    return entry.get("value")


def _th(ev: dict, metric: str):
    """Return the threshold for a metric from the evidence dict."""
    entry = ev.get(metric)
    if entry is None:
        return None
    return entry.get("threshold")


def _ev_map(evidence: list[dict]) -> dict:
    """Index evidence list by metric name."""
    return {e["metric"]: e for e in evidence}


# ── Evidence templates per rule code ─────────────────────────────────────────

def render_evidence_text(
    code: str,
    evidence: list[dict],
    target: str | None,
) -> str:
    """Return a deterministic evidence sentence for a rule code.

    Falls back to a generic summary when the code is unrecognised or evidence
    is missing expected keys.  Always returns a non-empty str.
    """
    ev = _ev_map(evidence)

    if code == "no_recent_plyo":
        days = _v(ev, "days_since_plyo")
        if days is None:
            return "No plyometric sessions recorded."
        return f"No plyometric session in the last {int(days)} days (threshold: 28 days)."

    if code == "plyo_deficit":
        pct = _v(ev, "lss_improvement_pct")
        sessions = _v(ev, "plyo_sessions_per_week")
        if pct is not None and sessions is not None:
            direction = "down" if float(pct) < 0 else "up"
            return (
                f"LSS {direction} {abs(float(pct)):.1f}% over 8 weeks; "
                f"avg {float(sessions):.1f} plyo sessions/week (need ≥1)."
            )
        return "Leg-spring stiffness is flat or falling with insufficient plyo frequency."

    if code == "gct_lengthening":
        delta = _v(ev, "gct_rise_ms")
        recent = _v(ev, "gct_recent_mean_ms")
        prior = _v(ev, "gct_prior_mean_ms")
        if delta is not None and recent is not None and prior is not None:
            return (
                f"Ground contact time rose {float(delta):.0f} ms at matched effort "
                f"({float(recent):.0f} ms now vs {float(prior):.0f} ms prior 28 days)."
            )
        return "Ground contact time is lengthening at matched running effort."

    if code == "cadence_drift":
        pct = _v(ev, "cadence_drop_pct")
        recent = _v(ev, "cadence_recent_mean_spm")
        baseline = _v(ev, "cadence_baseline_mean_spm")
        if pct is not None and recent is not None and baseline is not None:
            return (
                f"Running cadence dropped {float(pct):.1f}% below your long baseline "
                f"({float(recent):.0f} vs {float(baseline):.0f} spm)."
            )
        return "Running cadence has drifted below your long-run baseline."

    if code == "intensity_too_hard":
        high = _v(ev, "high_pct_4w")
        low = _v(ev, "low_pct_4w")
        threshold = _th(ev, "high_pct_4w")
        if high is not None and low is not None:
            thresh_str = f" (target ≤{float(threshold):.0f}%)" if threshold is not None else ""
            return (
                f"Hard-zone time is {float(high):.0f}% of total{thresh_str}; "
                f"easy-zone is {float(low):.0f}% over the last 4 weeks."
            )
        return "Too much time in hard intensity zones over the last 4 weeks."

    if code == "aerobic_durability_gap":
        avg = _v(ev, "avg_decoupling_pct_4w")
        count = _v(ev, "long_run_count_4w")
        threshold = _th(ev, "avg_decoupling_pct_4w")
        if avg is not None and count is not None:
            thresh_str = f" (threshold: {float(threshold):.0f}%)" if threshold is not None else ""
            return (
                f"Avg aerobic decoupling on {int(count)} long runs "
                f"is {float(avg):.1f}%{thresh_str} over 4 weeks."
            )
        return "Aerobic efficiency fades during long efforts."

    if code == "speed_neglected":
        decay = _v(ev, "speed_score_decay_8w")
        sessions = _v(ev, "quality_sessions_3w")
        if decay is not None and sessions is not None:
            return (
                f"Speed score fell {float(decay):.0f} pts over 8 weeks; "
                f"only {int(sessions)} quality session(s) in the last 3 weeks."
            )
        return "Speed score is declining with few quality sessions."

    if code == "recurrent_niggle_area":
        count = _v(ev, "niggle_count")
        date = _v(ev, "most_recent_entry_date")
        group = target or "area"
        if count is not None:
            date_str = f"; most recent: {date}" if date else ""
            return f"{int(count)} {group} niggles logged in the last 90 days{date_str}."
        return f"Recurrent {group} niggles detected in the last 90 days."

    if code == "undertrained_area_under_ramp":
        weeks = _v(ev, "zero_volume_weeks")
        ramp = _v(ev, "tss_ramp_pct")
        group = target or "muscle group"
        if weeks is not None and ramp is not None:
            return (
                f"{group.capitalize()} strength has been zero for {int(weeks)} weeks "
                f"while running TSS rose {float(ramp):.0f}%."
            )
        return f"{group.capitalize() if group else 'Muscle group'} strength is low while running load is rising."

    if code == "strength_lapsed":
        days = _v(ev, "days_since_strength")
        if days is None:
            return "No strength sessions recorded."
        return f"No strength sessions in the last {int(days)} days (threshold: 21 days)."

    if code.startswith("muscle_overused."):
        group = target or code.split(".", 1)[1]
        acwr = _v(ev, "acwr")
        threshold = _th(ev, "acwr")
        source = _v(ev, "main_source")
        parts: list[str] = []
        if acwr is not None:
            thresh_str = f" (threshold: {float(threshold):.2f})" if threshold is not None else ""
            parts.append(f"{group} ACWR is {float(acwr):.2f}{thresh_str}")
        if source:
            parts.append(f"main source: {source}")
        if parts:
            return "; ".join(parts) + "."
        return f"{group} is overloaded."

    if code.startswith("muscle_untrained."):
        group = target or code.split(".", 1)[1]
        weeks = _v(ev, "weeks_untrained")
        if weeks is not None:
            return f"{group.capitalize()} untrained for {int(weeks)} consecutive weeks."
        return f"{group.capitalize()} is chronically undertrained."

    if code.startswith("muscle_detraining."):
        group = target or code.split(".", 1)[1]
        chronic = _v(ev, "chronic_28d")
        if chronic is not None:
            return f"{group.capitalize()} training load is declining (chronic load: {float(chronic):.1f})."
        return f"{group.capitalize()} training load is declining."

    # Generic fallback for unknown / future rule codes
    if evidence:
        parts = []
        for e in evidence[:2]:
            m = e.get("metric", "")
            v = e.get("value")
            t = e.get("threshold")
            w = e.get("window", "")
            if v is not None and t is not None:
                parts.append(f"{m}: {v} (threshold: {t}, {w})")
            elif v is not None:
                parts.append(f"{m}: {v} ({w})")
        if parts:
            return "; ".join(parts) + "."
    return "Gap detected — see full analysis."


# ── Ordering helper ───────────────────────────────────────────────────────────

def sort_findings_for_panel(findings: list[dict]) -> list[dict]:
    """Return findings sorted severity desc, then code asc.

    The frontend takes findings[:3] for the top-three panel.
    """
    return sorted(findings, key=lambda f: (-f.get("severity", 0), f.get("code", "")))
