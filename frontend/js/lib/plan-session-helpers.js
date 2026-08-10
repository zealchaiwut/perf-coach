/* Pure helpers for the unified Plan session modal (view = edit = AI).
 * Exposed on window.PlanSessionHelpers for training-plan.js + light tests.
 */
(function (global) {
  'use strict';

  function hasStructure(structure) {
    if (!structure || typeof structure !== 'object') return false;
    if (Array.isArray(structure.blocks) && structure.blocks.length) return true;
    if (Array.isArray(structure.exercises) && structure.exercises.length) return true;
    if (structure.focus && String(structure.focus).trim()) return true;
    return false;
  }

  /** Completed + matched ⇒ AI bar dormant by default (expandable). */
  function aiBarDormant(session) {
    if (!session) return false;
    var done = session.status === 'done_auto' || session.status === 'done_manual';
    var matched = !!(session.matched_workout_id || (session.actual && session.actual.id));
    return done && matched;
  }

  /**
   * Duration minutes from run blocks — same sum as
   * plan_matching._planned_duration_seconds / 60:
   * duration_min * repeat + rest_min * (repeat - 1) per block.
   * Fixture: warmup 10 + main 3×10 rest 2 + cooldown 8 ⇒ 52 min.
   */
  function durationMinutesFromBlocks(blocks) {
    if (!Array.isArray(blocks) || !blocks.length) return null;
    var tot = 0;
    var any = false;
    blocks.forEach(function (b) {
      var d = Number(b.duration_min);
      if (!isFinite(d) || d < 0) return;
      any = true;
      var r = Math.max(1, Number(b.repeat) || 1);
      var rest = Number(b.rest_min) || 0;
      tot += d * r + rest * Math.max(0, r - 1);
    });
    return any ? Math.round(tot) : null;
  }

  function deriveTiles(structure, planned) {
    planned = planned || {};
    var s = structure || {};
    var dur = planned.duration_minutes != null ? Number(planned.duration_minutes)
      : (s.duration_minutes != null ? Number(s.duration_minutes) : null);
    if (dur == null || !isFinite(dur)) {
      dur = durationMinutesFromBlocks(s.blocks);
    }
    var tss = planned.target_tss != null ? Number(planned.target_tss)
      : (s.target_tss != null ? Number(s.target_tss) : null);
    var dist = planned.distance_km != null ? Number(planned.distance_km)
      : (s.distance_km != null ? Number(s.distance_km) : null);
    return {
      duration_min: (dur != null && isFinite(dur)) ? dur : null,
      target_tss: (tss != null && isFinite(tss)) ? tss : null,
      distance_km: (dist != null && isFinite(dist)) ? dist : null,
    };
  }

  function snapshotFields(session) {
    var s = session || {};
    return {
      name: s.name || '',
      notes: s.notes || '',
      planned_date: s.planned_date || '',
      session_type: s.session_type || 'run',
      structure: JSON.parse(JSON.stringify(s.structure || null)),
    };
  }

  function snapshotsEqual(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  function stampSourceUser(structure) {
    var s = structure ? JSON.parse(JSON.stringify(structure)) : {};
    if (!s || typeof s !== 'object') s = {};
    s.source = 'user';
    return s;
  }

  /**
   * Display TSS for a planned session.
   * actual.tss when logged; else server estimated_tss (already encodes
   * pin / spend / history). Never re-prefer structure.target_tss.
   */
  function sessionTss(p) {
    if (p && p.actual && p.actual.tss != null) return { value: p.actual.tss, estimated: false };
    if (p && p.estimated_tss != null && isFinite(Number(p.estimated_tss))) {
      return { value: Number(p.estimated_tss), estimated: true };
    }
    return null;
  }

  global.PlanSessionHelpers = {
    hasStructure: hasStructure,
    aiBarDormant: aiBarDormant,
    durationMinutesFromBlocks: durationMinutesFromBlocks,
    deriveTiles: deriveTiles,
    snapshotFields: snapshotFields,
    snapshotsEqual: snapshotsEqual,
    stampSourceUser: stampSourceUser,
    sessionTss: sessionTss,
  };
})(typeof window !== 'undefined' ? window : globalThis);
