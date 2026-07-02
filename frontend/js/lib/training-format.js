// Shared training format helpers (issue #531).
//
// `training-log.js` (the log viewer) and `training.js` (the workout editor)
// used to keep their own copies of type normalization, pace/duration
// formatting, and segment↔exercise mapping. The copies had drifted, which was
// the root cause of structured-run detection and source-attribution bugs.
// This module is the single home for that logic so both pages agree.
//
// No build step in this project (plain <script> tags, served as FileResponse),
// so the module attaches its API to `window.TrainingFormat` and is loaded as a
// classic script BEFORE the page scripts. Consumers read helpers from
// `window.TrainingFormat` instead of defining their own.
(function (global) {
  'use strict';

  function pad(n) { return String(n).padStart(2, '0'); }

  // ── Type normalization ──────────────────────────────────────────────────
  // Map free-text workout_type values onto canonical keys. The full editor
  // saves "Running"/"Strength"/"Race"; synced workouts use "run". Both pages
  // run the SAME normalization so run/structured detection is identical.
  function normalizeType(t) {
    t = (t || '').toLowerCase().trim();
    if (/^run(ning)?$|^race$/.test(t)) return 'run';
    // 'interval'/'intervals' is a DISTINCT canonical key (must survive so the
    // Performance Speed feed matches it) — keep it before the generic fallback.
    if (/^intervals?$/.test(t)) return 'interval';
    if (/^(lift|strength)/.test(t)) return 'lift';
    if (/^(bike|ride|cycl)/.test(t)) return 'bike';
    if (/^(wod|crossfit)/.test(t)) return 'wod';
    return t;
  }

  // ── Pace formatting ─────────────────────────────────────────────────────
  // Canonical "m:ss" pace string from a duration (seconds) and a distance
  // (km). Returns null when either input is missing/non-positive so callers
  // can decide their own fallback ("—", "", etc.). To format an already
  // computed seconds-per-km value, pass it as durSeconds with distKm = 1.
  function formatPace(durSeconds, distKm) {
    if (!durSeconds || !distKm || durSeconds <= 0 || distKm <= 0) return null;
    var secPerKm = durSeconds / distKm;
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + pad(s);
  }

  // ── Duration formatting ─────────────────────────────────────────────────
  // Canonical "h:mm:ss" (or "m:ss" under an hour) for a non-negative number
  // of seconds. Returns null for null/non-finite input so callers map their
  // own empty/dash placeholder.
  function formatDuration(secs) {
    if (secs == null || !isFinite(secs)) return null;
    var total = Math.max(0, secs);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = Math.round(total % 60);
    if (s === 60) { s = 0; m += 1; }
    if (m === 60) { m = 0; h += 1; }
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  // ── Run segments ────────────────────────────────────────────────────────
  // Canonical run-segment definitions. `label` is what gets stored as the
  // exercise name; `intensity` drives the log timeline colors. Both pages
  // derive their segment tables from this single source.
  var SEG_TYPES = {
    warmup:    { label: 'Warm-up',   mode: 'span',  intensity: 'warmup' },
    easy:      { label: 'Easy run',  mode: 'span',  intensity: 'easy' },
    tempo:     { label: 'Tempo',     mode: 'span',  intensity: 'tempo' },
    intervals: { label: 'Intervals', mode: 'block', intensity: 'intervals' },
    rest:      { label: 'Rest',      mode: 'span',  intensity: 'rest' },
    cooldown:  { label: 'Cool-down', mode: 'span',  intensity: 'cooldown' },
  };

  // Lower-cased segment label → intensity key. Truthy membership of this map
  // is also how the log decides whether a stored exercise is a run segment.
  var segmentIntensityByLabel = (function () {
    var m = {};
    Object.keys(SEG_TYPES).forEach(function (k) {
      m[SEG_TYPES[k].label.toLowerCase()] = SEG_TYPES[k].intensity;
    });
    return m;
  })();

  function isRunSegmentName(name) {
    return !!segmentIntensityByLabel[(name || '').toLowerCase()];
  }

  // Resolve one UI segment to km + seconds (pace fills the missing side).
  // `repKm`/`repSec` are per-rep; `km`/`sec` apply the block multiplier.
  function segmentDims(s) {
    var km = null, sec = null;
    var pace = (s.paceSec != null && !isNaN(s.paceSec)) ? s.paceSec : null;
    if (s.unit === 'km') {
      km = s.value;
      if (km != null && pace) sec = km * pace;
    } else {
      sec = s.value != null ? s.value * 60 : null;
      if (sec != null && pace) km = sec / pace;
    }
    var mult = s.sets != null && s.sets > 0 ? s.sets : 1;
    return {
      km: km != null ? km * mult : null,
      sec: sec != null ? sec * mult : null,
      repKm: km, repSec: sec,
    };
  }

  // Serialize UI segment descriptors into workout_exercises payload rows.
  // Per-rep distance/duration for blocks; pace materializes the missing side.
  // Empty rows (no value, sets, or HR) are skipped.
  function mapSegmentsToExercises(segments) {
    var out = [];
    (segments || []).forEach(function (s, i) {
      var cfg = SEG_TYPES[s.type];
      if (!cfg) return;
      if (s.value == null && s.sets == null && s.hr == null) return;
      var d = segmentDims(s);
      out.push({
        display_order: i,
        name: cfg.label,
        sets: cfg.mode === 'block' ? s.sets : null,
        reps: null,
        weight_kg: null,
        duration: null,
        rpe: null,
        distance_km: d.repKm != null ? parseFloat(d.repKm.toFixed(3)) : null,
        duration_seconds: d.repSec != null ? Math.round(d.repSec) : null,
        avg_hr: s.hr,
      });
    });
    return out;
  }

  global.TrainingFormat = {
    normalizeType: normalizeType,
    formatPace: formatPace,
    formatDuration: formatDuration,
    mapSegmentsToExercises: mapSegmentsToExercises,
    // supporting data/utilities shared by the two pages
    segmentDims: segmentDims,
    SEG_TYPES: SEG_TYPES,
    segmentIntensityByLabel: segmentIntensityByLabel,
    isRunSegmentName: isRunSegmentName,
  };
})(typeof window !== 'undefined' ? window : this);
