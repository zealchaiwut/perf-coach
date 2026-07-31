"""Optimal racing weight as a hypothesis — not a number off a chart.

The premise
-----------
"As lean as I can" has no stopping rule, which is what makes it dangerous. A
target weight taken from a chart or a peer percentile is a guess dressed as a
goal, and in runners specifically that framing drives disordered patterns — the
source book's own counterpoints say so.

So this module refuses to produce a target. It produces a **hypothesis**: given
this athlete's own history, the weight band where their performance scores were
highest. That dissolves "as lean as I can" by making leanness pay only until it
stops paying — and if the answer comes back 85 kg rather than 79, that is the
finding, not a failure.

How it works
------------
Weight trend and performance score are both already computed daily. Pair them by
date, bucket by weight, and report the mean score per bucket. The peak bucket is
the hypothesis; the spread around it is the honest uncertainty.

What it will not do
-------------------
- **No target, ever.** The output has no ``target_kg`` key; it has a
  ``peak_estimate_kg`` and a band, both labelled as estimates.
- **No claim without coverage.** Fewer than ``MIN_BUCKETS`` populated buckets or
  ``MIN_PAIRS`` observations and the answer is "not enough range yet". An
  athlete who has only ever been 84-85 kg has no evidence about 80.
- **No causation.** Weight and score move together for many reasons — a build
  block raises both. The copy says where the scores were highest, not that the
  weight caused it.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from typing import Optional
from backend.utils.time import today_bangkok

# Weight buckets, in kg. Fine enough to locate a peak, coarse enough that a
# bucket holds more than one week of data.
BUCKET_KG = 0.5
# Minimum paired observations before any estimate is offered.
MIN_PAIRS = 30
# Distinct populated buckets needed — an athlete who has only ever been 84-85 kg
# has no evidence about 80, however many days they logged.
MIN_BUCKETS = 4
# Observations a bucket needs before it can be called the peak.
MIN_PER_BUCKET = 3
# Half-width of the reported band around the peak, in kg. Bioimpedance-grade
# precision this is not; the band says so.
BAND_HALF_WIDTH_KG = 1.0


def _bucket(weight_kg: float) -> float:
    return round(round(weight_kg / BUCKET_KG) * BUCKET_KG, 1)


def compute_hypothesis(pairs: list[dict]) -> dict:
    """Locate the weight band where performance scores were highest.

    Parameters
    ----------
    pairs:
        Dicts with ``weight_kg`` and ``score``. One per day is expected; the
        caller decides which score (endurance, speed, or a blend).

    Returns
    -------
    dict with ``readable``, ``reason``, ``peak_estimate_kg``, ``band_kg``,
    ``confidence``, ``buckets``, ``n_pairs``, ``current_weight_kg``,
    ``direction``, ``sentence``.

    There is no ``target_kg``, and there never will be.
    """
    out = {
        "readable": False,
        "reason": None,
        "peak_estimate_kg": None,
        "band_kg": None,
        "confidence": "none",
        "buckets": [],
        "n_pairs": 0,
        "current_weight_kg": None,
        "direction": None,
        "sentence": None,
    }

    rows = [
        p for p in (pairs or [])
        if p.get("weight_kg") is not None and p.get("score") is not None
    ]
    out["n_pairs"] = len(rows)
    if rows:
        out["current_weight_kg"] = round(float(rows[-1]["weight_kg"]), 1)

    if len(rows) < MIN_PAIRS:
        out["reason"] = (
            f"{len(rows)} paired days — {MIN_PAIRS} are needed before a weight "
            "band means anything"
        )
        return out

    grouped: dict[float, list[float]] = {}
    for p in rows:
        grouped.setdefault(_bucket(float(p["weight_kg"])), []).append(float(p["score"]))

    buckets = [
        {
            "weight_kg": w,
            "mean_score": round(sum(scores) / len(scores), 1),
            "n": len(scores),
        }
        for w, scores in sorted(grouped.items())
    ]
    out["buckets"] = buckets

    eligible = [b for b in buckets if b["n"] >= MIN_PER_BUCKET]
    if len(eligible) < MIN_BUCKETS:
        out["reason"] = (
            f"only {len(eligible)} weight bands with enough days — the range "
            "you've actually trained at is too narrow to locate a peak"
        )
        return out

    peak = max(eligible, key=lambda b: b["mean_score"])
    out["readable"] = True
    out["peak_estimate_kg"] = peak["weight_kg"]
    out["band_kg"] = [
        round(peak["weight_kg"] - BAND_HALF_WIDTH_KG, 1),
        round(peak["weight_kg"] + BAND_HALF_WIDTH_KG, 1),
    ]

    # Confidence is about coverage, not about the size of the difference: more
    # bands and more days mean the peak is less likely to be an artefact.
    if len(eligible) >= MIN_BUCKETS + 3 and len(rows) >= MIN_PAIRS * 3:
        out["confidence"] = "moderate"
    elif len(eligible) >= MIN_BUCKETS + 1:
        out["confidence"] = "low"
    else:
        out["confidence"] = "very low"

    current = out["current_weight_kg"]
    if current is not None:
        if current > out["band_kg"][1]:
            out["direction"] = "below_current"
        elif current < out["band_kg"][0]:
            out["direction"] = "above_current"
        else:
            out["direction"] = "within_band"

    lo, hi = out["band_kg"]
    out["sentence"] = (
        f"Your scores have been highest around {peak['weight_kg']:.1f} kg "
        f"({lo:.1f}-{hi:.1f} kg), on {peak['n']} days at that weight. "
        f"Confidence is {out['confidence']} — this is where the numbers were "
        "best, not proof that the weight caused it."
    )
    return out


def pairs_for_user(db, user_id, today: Optional[_date] = None, days: int = 540) -> list[dict]:
    """Daily (weight trend, endurance score) pairs from stored history.

    Weight trend rather than raw weigh-ins: a single heavy morning is noise, and
    the question is about where the athlete *lived*, not what the scale said once.
    """
    from backend.models import PerformanceScoreHistory, WeightEntry
    from backend.services.weight_ewma import compute_ewma

    today = today or today_bangkok()
    start = today - _timedelta(days=days)

    weight_rows = (
        db.query(WeightEntry.entry_date, WeightEntry.weight_kg)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= start,
            WeightEntry.entry_date <= today,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    if not weight_rows:
        return []

    entries = [{"date": r[0], "weight_kg": float(r[1])} for r in weight_rows]
    smoothed = compute_ewma(entries)
    trend_by_date = {e["date"]: float(v) for e, v in zip(entries, smoothed)}

    score_rows = (
        db.query(PerformanceScoreHistory.score_date, PerformanceScoreHistory.endurance)
        .filter(
            PerformanceScoreHistory.user_id == user_id,
            PerformanceScoreHistory.score_date >= start,
            PerformanceScoreHistory.score_date <= today,
            PerformanceScoreHistory.endurance.isnot(None),
        )
        .order_by(PerformanceScoreHistory.score_date.asc())
        .all()
    )

    pairs: list[dict] = []
    for day, score in score_rows:
        weight = trend_by_date.get(day)
        if weight is None:
            continue
        pairs.append({"date": day.isoformat(), "weight_kg": weight, "score": float(score)})
    return pairs


def hypothesis_for_user(db, user_id, today: Optional[_date] = None) -> dict:
    """``compute_hypothesis`` over a user's stored weight and score history."""
    return compute_hypothesis(pairs_for_user(db, user_id, today))
