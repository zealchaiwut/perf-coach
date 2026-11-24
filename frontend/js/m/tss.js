/* Phone-side strength TSS estimate — same formula as backend.services.strength_tss. */
(function (global) {
  "use strict";
  function fromExercises(exercises) {
    var tss = 0;
    (exercises || []).forEach(function (ex) {
      var sets = Array.isArray(ex.sets) ? ex.sets : [];
      var w = Number(ex.tss_weight || 1);
      tss += sets.length * w;
    });
    return Math.round(tss * 10) / 10;
  }
  function fromEffortTime(durationSeconds, sessionEffort) {
    if (!durationSeconds) return 0;
    var effort = Number(sessionEffort || 5);
    return Math.round((durationSeconds / 3600) * effort * 10 * 10) / 10;
  }
  global.MTss = { fromExercises: fromExercises, fromEffortTime: fromEffortTime };
})(window);
