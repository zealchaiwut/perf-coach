"""Issue #1653 — Document/bound ACWR-ceiling overshoot from TSS floor re-clamp.

AC1: redistribute_meta["ceiling_overshoot"] is present and > 0 when floor bumps
     cause the final weekly TSS to exceed the ACWR ceiling.
AC2: ceiling_overshoot is 0 when no ACWR ceiling is passed (no ceiling, no overshoot).
AC3: ceiling_overshoot is 0 when every slot's proportional add keeps it above the
     floor — i.e. floor bumps are not needed.
AC4: ceiling_overshoot correctly sums the per-slot floor-bump excess (TSS added
     above what the ceiling would allow, slot by slot).
AC5: The source comment at the re-clamp site mentions that the floor intentionally
     overrides the ceiling and that aggregate overshoot is bounded.
"""
import ast
import inspect
import uuid

from backend.services import plan_skeleton_ops as ops


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_sessions(days_tss: dict[int, float]) -> list[dict]:
    return [
        {
            "slot_id": str(uuid.uuid4()),
            "day_offset": d,
            "workout_type": "run",
            "subtype": "easy_run",
            "target_tss": tss,
            "duration_minutes": 30,
            "locked": False,
        }
        for d, tss in days_tss.items()
    ]


def _weekly_tss(result: dict) -> float:
    return sum(
        float(s.get("target_tss") or 0)
        for s in result["slots"]
        if s.get("workout_type") != "rest"
    )


# ── AC1: ceiling_overshoot present and positive when floor bumps cause breach ──

class TestCeilingOvershootPresent:
    def test_overshoot_positive_when_floor_bumps_exceed_ceiling(self):
        """Single-slot: old=5 TSS, ceiling=5, drop=40. Floor bumps to 15 → overshoot=10."""
        slots = _make_sessions({1: 5.0, 3: 40.0})
        keep_id = slots[0]["slot_id"]
        drop_id = slots[1]["slot_id"]
        result = ops.remove(slots, slot_id=drop_id, mode="redistribute", acwr_ceiling=5.0)
        meta = result.get("redistribute")
        assert meta is not None, "redistribute key absent"
        assert "ceiling_overshoot" in meta, "ceiling_overshoot missing from redistribute_meta"
        assert meta["ceiling_overshoot"] > 0, (
            "expected positive ceiling_overshoot when floor bump exceeds ceiling"
        )

    def test_overshoot_matches_actual_breach(self):
        """ceiling_overshoot must equal final_total - ceiling (rounded to 1dp)."""
        slots = _make_sessions({1: 5.0, 3: 40.0})
        drop_id = slots[1]["slot_id"]
        ceiling = 5.0
        result = ops.remove(slots, slot_id=drop_id, mode="redistribute", acwr_ceiling=ceiling)
        meta = result["redistribute"]
        final_total = _weekly_tss(result)
        expected_overshoot = round(max(0.0, final_total - ceiling), 1)
        assert abs(meta["ceiling_overshoot"] - expected_overshoot) < 0.5, (
            f"ceiling_overshoot={meta['ceiling_overshoot']} but actual breach={expected_overshoot}"
        )


# ── AC2: ceiling_overshoot is 0 when no ceiling is passed ─────────────────────

class TestCeilingOvershootNoCeiling:
    def test_overshoot_zero_when_no_ceiling(self):
        """Without ACWR ceiling, ceiling_overshoot must be 0."""
        slots = _make_sessions({1: 5.0, 3: 40.0})
        drop_id = slots[1]["slot_id"]
        result = ops.remove(slots, slot_id=drop_id, mode="redistribute", acwr_ceiling=None)
        meta = result.get("redistribute")
        assert meta is not None
        assert meta.get("ceiling_overshoot", 0) == 0, (
            "ceiling_overshoot should be 0 when no ceiling is set"
        )

    def test_overshoot_absent_or_zero_in_drop_mode(self):
        """mode=drop does not produce redistribute_meta at all; no overshoot key."""
        slots = _make_sessions({1: 40.0, 3: 30.0})
        drop_id = slots[1]["slot_id"]
        result = ops.remove(slots, slot_id=drop_id, mode="drop")
        assert result.get("redistribute") is None, (
            "mode=drop should not produce redistribute_meta"
        )


# ── AC3: ceiling_overshoot is 0 when floor bumps are not needed ───────────────

class TestCeilingOvershootZeroWhenNoFloorBumps:
    def test_overshoot_zero_when_room_is_ample(self):
        """Plenty of ceiling room → all adds well above floor → overshoot=0."""
        # old=40, ceiling=200, dropped=30: add≈30, new≈70, well above floor
        slots = _make_sessions({1: 40.0, 3: 30.0})
        drop_id = slots[1]["slot_id"]
        result = ops.remove(slots, slot_id=drop_id, mode="redistribute", acwr_ceiling=200.0)
        meta = result["redistribute"]
        assert meta.get("ceiling_overshoot", 0) == 0, (
            "no floor bump needed — ceiling_overshoot should be 0"
        )

    def test_overshoot_zero_when_all_slots_already_above_floor(self):
        """All slots at 20 TSS, tight ceiling but add pushes to 20+small → still above floor."""
        # old=20, ceiling=25, current_sum=20, room=5, add=5, new=25 → above floor
        slots = _make_sessions({1: 20.0, 3: 30.0})
        drop_id = slots[1]["slot_id"]
        result = ops.remove(slots, slot_id=drop_id, mode="redistribute", acwr_ceiling=25.0)
        meta = result["redistribute"]
        assert meta.get("ceiling_overshoot", 0) == 0, (
            "slot at 20 + add still above floor — overshoot should be 0"
        )


# ── AC4: multi-slot aggregate overshoot is correct ────────────────────────────

class TestAggregateOvershootMultiSlot:
    def test_multi_slot_aggregate_overshoot_correct(self):
        """Multiple floor-bumped slots: overshoot = actual final_total - ceiling."""
        # 3 slots all at 5 TSS each (total=15), ceiling=15 (no room).
        # Each gets add=0 from ceiling, but floor bumps to 15 → total=45, overshoot=30.
        slots = [
            {"slot_id": f"keep-{i}", "day_offset": i, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 5.0, "duration_minutes": 20, "locked": False}
            for i in range(3)
        ] + [
            {"slot_id": "drop", "day_offset": 4, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 40.0, "duration_minutes": 40, "locked": False}
        ]
        result = ops.remove(slots, slot_id="drop", mode="redistribute", acwr_ceiling=15.0)
        meta = result["redistribute"]
        final_total = _weekly_tss(result)
        expected_overshoot = round(max(0.0, final_total - 15.0), 1)
        assert "ceiling_overshoot" in meta
        assert abs(meta["ceiling_overshoot"] - expected_overshoot) < 0.5, (
            f"multi-slot: ceiling_overshoot={meta['ceiling_overshoot']}, "
            f"actual breach={expected_overshoot}"
        )

    def test_per_slot_overshoot_bounded_by_floor(self):
        """Per-slot ceiling overshoot cannot exceed _PER_SLOT_TSS_FLOOR (15).
        Total overshoot <= n_bumped_slots × 15 is the mathematical bound.
        """
        n_slots = 4
        slots = [
            {"slot_id": f"keep-{i}", "day_offset": i, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 5.0, "duration_minutes": 20, "locked": False}
            for i in range(n_slots)
        ] + [
            {"slot_id": "drop", "day_offset": n_slots, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 60.0, "duration_minutes": 50, "locked": False}
        ]
        result = ops.remove(slots, slot_id="drop", mode="redistribute", acwr_ceiling=20.0)
        meta = result["redistribute"]
        assert meta["ceiling_overshoot"] <= n_slots * ops._PER_SLOT_TSS_FLOOR, (
            "aggregate overshoot must not exceed n_slots × _PER_SLOT_TSS_FLOOR"
        )

    def test_zero_room_many_slots(self):
        """ceiling_overshoot is correctly computed even when room is exactly 0."""
        slots = [
            {"slot_id": f"k{i}", "day_offset": i, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 10.0, "duration_minutes": 20, "locked": False}
            for i in range(5)
        ] + [
            {"slot_id": "drop", "day_offset": 5, "workout_type": "run",
             "subtype": "easy_run", "target_tss": 50.0, "duration_minutes": 40, "locked": False}
        ]
        ceiling = 50.0  # exactly equal to current sum (5×10)
        result = ops.remove(slots, slot_id="drop", mode="redistribute", acwr_ceiling=ceiling)
        meta = result["redistribute"]
        final_total = _weekly_tss(result)
        expected_overshoot = round(max(0.0, final_total - ceiling), 1)
        assert abs(meta["ceiling_overshoot"] - expected_overshoot) < 0.5


# ── AC5: comment at the re-clamp site ─────────────────────────────────────────

class TestFloorCeilingComment:
    def test_comment_mentions_floor_overrides_ceiling(self):
        """The source of plan_skeleton_ops.remove() must contain a comment
        explaining that the floor intentionally overrides the ACWR ceiling."""
        import backend.services.plan_skeleton_ops as m
        source = inspect.getsource(m.remove)
        # We look for a comment near the floor re-clamp mentioning 'floor'
        # and 'ceiling' (or 'ACWR') together — implementation may vary in wording.
        lower = source.lower()
        assert "floor" in lower and ("ceiling" in lower or "acwr" in lower), (
            "remove() source must contain both 'floor' and 'ceiling'/'acwr' "
            "in a comment explaining the intentional override"
        )
        # The comment must actually be in a comment line, not just code
        has_comment = any(
            ("#" in line and "floor" in line.lower() and
             ("ceiling" in line.lower() or "acwr" in line.lower() or "overshoot" in line.lower()))
            for line in source.splitlines()
        )
        assert has_comment, (
            "Expected a comment line in remove() mentioning 'floor' and "
            "'ceiling'/'acwr'/'overshoot' to document the intentional behavior"
        )
