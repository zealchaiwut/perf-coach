(function () {
  "use strict";

  // ── Helpers ────────────────────────────────────────────────────────────────

  function dash(v) {
    return v == null || v === "" ? "—" : v;
  }

  function fmtDuration(sec) {
    if (!sec) return "—";
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0)
      return (
        h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0")
      );
    return m + ":" + String(s).padStart(2, "0");
  }

  function fmtDate(str) {
    if (!str) return "—";
    try {
      var d = new Date(str + "T00:00:00");
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch (e) {
      return str;
    }
  }

  // ── RPE tier ───────────────────────────────────────────────────────────────

  var RPE_TIERS = [
    { max: 3, label: "easy",     color: "#86efac" },
    { max: 6, label: "moderate", color: "#fcd34d" },
    { max: 8, label: "hard",     color: "#fb923c" },
    { max: 10, label: "max",     color: "#f87171" },
  ];
  var RPE_NEUTRAL = "#cbd5e1";

  function rpeTier(rpe) {
    if (rpe == null) return { label: "neutral", color: RPE_NEUTRAL };
    for (var i = 0; i < RPE_TIERS.length; i++) {
      if (rpe <= RPE_TIERS[i].max) return RPE_TIERS[i];
    }
    return RPE_TIERS[RPE_TIERS.length - 1];
  }

  // ── Session-profile bar ───────────────────────────────────────────────────

  function renderProfileBar(exercises) {
    if (!exercises || !exercises.length) return "";

    // Flatten sets from all exercises
    var allSets = [];
    exercises.forEach(function (ex) {
      var sets = parseSets(ex);
      if (sets.length) {
        sets.forEach(function (s) {
          allSets.push({ rpe: s.rpe, duration: s.duration_seconds, exRpe: ex.rpe });
        });
      } else {
        // Exercise-level fallback: one virtual set
        allSets.push({ rpe: ex.rpe, duration: ex.duration_seconds, exRpe: ex.rpe });
      }
    });

    if (!allSets.length) return "";

    var totalDur = allSets.reduce(function (sum, s) {
      return sum + (s.duration || 0);
    }, 0);
    var defaultWidthPct = 100 / allSets.length;

    var bars = allSets.map(function (s) {
      var rpe = s.rpe != null ? s.rpe : s.exRpe;
      var tier = rpeTier(rpe);
      var heightPct = rpe != null ? Math.max(15, (rpe / 10) * 100) : 30;
      var widthPct = totalDur > 0 && s.duration
        ? (s.duration / totalDur) * 100
        : defaultWidthPct;
      return (
        '<div class="sv-profile-bar-seg" style="' +
        "width:" + widthPct.toFixed(2) + "%;" +
        "height:" + heightPct.toFixed(0) + "%;" +
        "background:" + tier.color +
        '"></div>'
      );
    });

    return '<div class="sv-profile-bar">' + bars.join("") + "</div>";
  }

  // ── Set parsing ────────────────────────────────────────────────────────────

  function parseSets(ex) {
    if (!ex.sets_json) return [];
    try {
      var parsed = JSON.parse(ex.sets_json);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  // ── Stats grid ────────────────────────────────────────────────────────────

  function computeStats(workout, exercises) {
    var duration = workout.duration_seconds;
    var exerciseCount = exercises.length;
    var totalReps = 0;
    var totalRpe = 0;
    var rpeCount = 0;

    exercises.forEach(function (ex) {
      var sets = parseSets(ex);
      if (sets.length) {
        sets.forEach(function (s) {
          if (s.reps != null) totalReps += s.reps;
          if (s.rpe != null) { totalRpe += s.rpe; rpeCount++; }
        });
      } else {
        var setCount = ex.sets || 1;
        if (ex.reps != null) totalReps += ex.reps * setCount;
        if (ex.rpe != null) { totalRpe += ex.rpe; rpeCount++; }
      }
    });

    var avgRpe = rpeCount > 0 ? (totalRpe / rpeCount).toFixed(1) : null;
    return {
      duration: duration,
      exerciseCount: exerciseCount || null,
      totalReps: totalReps || null,
      avgRpe: avgRpe,
      avgHr: workout.avg_hr,
      tss: workout.tss,
    };
  }

  function statTile(label, value) {
    return (
      '<div class="sv-stat-tile">' +
      '<div class="sv-stat-val">' + dash(value) + "</div>" +
      '<div class="sv-stat-label">' + label + "</div>" +
      "</div>"
    );
  }

  function renderStatsGrid(stats) {
    return (
      '<div class="sv-stats-grid">' +
      statTile("Duration", fmtDuration(stats.duration)) +
      statTile("Exercises", stats.exerciseCount) +
      statTile("Total Reps", stats.totalReps) +
      statTile("Avg RPE", stats.avgRpe) +
      statTile("Avg HR", stats.avgHr != null ? stats.avgHr + " bpm" : null) +
      statTile("TSS", stats.tss) +
      "</div>"
    );
  }

  // ── Exercises list ────────────────────────────────────────────────────────

  function setSummary(ex) {
    var sets = parseSets(ex);
    if (sets.length) {
      return sets.map(function (s) {
        var reps = dash(s.reps);
        var weight = s.weight_kg != null ? s.weight_kg + " kg" : "—";
        return reps + " × — @ " + weight;
      }).join(", ");
    }
    var setCount = dash(ex.sets);
    var reps = dash(ex.reps);
    var weight = ex.weight_kg != null ? ex.weight_kg + " kg" : "—";
    return setCount + " × " + reps + " @ " + weight;
  }

  function renderExercisesList(exercises) {
    if (!exercises || !exercises.length)
      return '<p class="sv-empty">No exercises recorded</p>';

    return (
      '<div class="sv-exercises-list">' +
      exercises.map(function (ex) {
        var tier = rpeTier(ex.rpe);
        var rpePillVal = ex.rpe != null ? "RPE " + ex.rpe : "—";
        return (
          '<div class="sv-ex-row">' +
          '<span class="sv-ex-bullet" style="background:' + tier.color + '"></span>' +
          '<span class="sv-ex-name">' + (ex.name || "Exercise") + "</span>" +
          '<span class="sv-ex-summary">' + setSummary(ex) + "</span>" +
          '<span class="sv-rpe-pill" style="background:' + tier.color + '">' + rpePillVal + "</span>" +
          "</div>"
        );
      }).join("") +
      "</div>"
    );
  }

  // ── Badge helpers ─────────────────────────────────────────────────────────

  var TYPE_COLORS = {
    strength:  "#8b5cf6",
    lift:      "#8b5cf6",
    "weight training": "#8b5cf6",
  };

  function badgeColor(workoutType) {
    var t = (workoutType || "").toLowerCase();
    for (var key in TYPE_COLORS) {
      if (t.indexOf(key) !== -1) return TYPE_COLORS[key];
    }
    return "#64748b";
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function renderView(data) {
    var w = data.workout;
    var exercises = w.exercises || [];
    var typeLabel = (w.workout_type || "Strength").toUpperCase();
    var color = badgeColor(w.workout_type);

    var header =
      '<div class="sv-card sv-header">' +
      '<span class="sv-badge" style="background:' + color + '">' + typeLabel + "</span>" +
      '<h1 class="sv-workout-name">' + (w.name || "Untitled") + "</h1>" +
      '<div class="sv-date">' + fmtDate(w.workout_date) + "</div>" +
      "</div>";

    var stats = computeStats(w, exercises);
    var statsCard =
      '<div class="sv-card sv-stats">' +
      '<h2 class="sv-section-title">Stats</h2>' +
      renderStatsGrid(stats) +
      "</div>";

    var profileCard =
      '<div class="sv-card sv-profile">' +
      '<h2 class="sv-section-title">Session Profile · Effort</h2>' +
      renderProfileBar(exercises) +
      "</div>";

    var exercisesCard =
      '<div class="sv-card sv-exercises">' +
      '<h2 class="sv-section-title">Exercises</h2>' +
      renderExercisesList(exercises) +
      "</div>";

    document.getElementById("sv-root").innerHTML =
      header + statsCard + profileCard + exercisesCard;
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  function getWorkoutId() {
    var params = new URLSearchParams(window.location.search);
    return params.get("id");
  }

  function init() {
    var workoutId = getWorkoutId();
    if (!workoutId) {
      document.getElementById("sv-root").innerHTML =
        '<div class="sv-error">No workout ID supplied. Add ?id=&lt;workout-id&gt; to the URL.</div>';
      return;
    }
    fetch("/api/workouts/" + workoutId + "/full", { credentials: "include" })
      .then(function (r) {
        if (r.status === 404) throw new Error("Workout not found");
        if (!r.ok) throw new Error("Failed to load workout (" + r.status + ")");
        return r.json();
      })
      .then(function (data) {
        renderView(data);
      })
      .catch(function (err) {
        document.getElementById("sv-root").innerHTML =
          '<div class="sv-error">' + err.message + "</div>";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
