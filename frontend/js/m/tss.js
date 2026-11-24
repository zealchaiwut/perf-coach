/* Phone-side strength TSS — same formula as backend.services.strength_tss. */
(function (global) {
  "use strict";
  var STRENGTH_SET_TSS = 3.3;

  function fromExercises(exercises, multipliers) {
    multipliers = multipliers || {};
    if (!exercises || !exercises.length) {
      return { tss: null, method: "exercises", per_exercise: [], reason: "no exercises" };
    }
    var per = [];
    var total = 0;
    exercises.forEach(function (ex) {
      var name = (ex.name || "").trim();
      var sets = Array.isArray(ex.sets) ? ex.sets : [];
      var n = sets.length;
      var mult = multipliers[name.toLowerCase()] != null ? multipliers[name.toLowerCase()] : 1;
      var tss = Math.round(n * STRENGTH_SET_TSS * mult * 10) / 10;
      per.push({ name: name, tss: tss, set_count: n, multiplier: mult });
      total += tss;
    });
    return { tss: Math.round(total * 10) / 10, method: "exercises", per_exercise: per };
  }

  function fromEffortTime(durationMin, effort) {
    effort = Number(effort);
    durationMin = Number(durationMin);
    if (effort < 1 || effort > 10) {
      return { tss: null, method: "effort_time", reason: "effort must be 1–10" };
    }
    if (!(durationMin > 0)) {
      return { tss: null, method: "effort_time", reason: "duration required" };
    }
    var raw = (durationMin / 60) * Math.pow(effort / 10, 2) * 100;
    return { tss: Math.round(raw), method: "effort_time" };
  }

  global.MTss = {
    STRENGTH_SET_TSS: STRENGTH_SET_TSS,
    fromExercises: fromExercises,
    fromEffortTime: fromEffortTime
  };
})(window);
