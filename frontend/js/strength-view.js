(function () {
  "use strict";

  // ── Helpers ────────────────────────────────────────────────────────────────

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

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

  function fmtWeight(kg) {
    return kg != null ? kg + " kg" : "—";
  }

  // ── RPE tier ───────────────────────────────────────────────────────────────

  var RPE_TIERS = [
    { max: 3, label: "Easy", color: "#86efac" },
    { max: 6, label: "Moderate", color: "#fcd34d" },
    { max: 8, label: "Hard", color: "#fb923c" },
    { max: 10, label: "Max", color: "#f87171" },
  ];
  var RPE_NEUTRAL = { label: "No RPE logged", color: "#cbd5e1" };

  function rpeTier(rpe) {
    if (rpe == null) return RPE_NEUTRAL;
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

    // Tally tier counts for an accessible text summary (the bar itself is
    // a decorative visualization; screen reader users get the same info
    // as a sentence instead of parsing colored divs).
    var tierCounts = {};
    var bars = allSets.map(function (s) {
      var rpe = s.rpe != null ? s.rpe : s.exRpe;
      var tier = rpeTier(rpe);
      tierCounts[tier.label] = (tierCounts[tier.label] || 0) + 1;
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

    var summaryParts = [];
    [RPE_NEUTRAL].concat(RPE_TIERS).forEach(function (tier) {
      if (tierCounts[tier.label]) {
        summaryParts.push(tierCounts[tier.label] + " " + tier.label.toLowerCase());
      }
    });
    var barLabel = allSets.length + " sets: " + summaryParts.join(", ");

    var legendItems = RPE_TIERS.map(function (tier) {
      return (
        '<li class="sv-profile-legend-item">' +
        '<span class="sv-profile-legend-dot" style="background:' + tier.color + '"></span>' +
        esc(tier.label) +
        "</li>"
      );
    }).join("");

    return (
      '<div class="sv-profile-bar" role="img" aria-label="' + esc(barLabel) + '">' +
      bars.join("") +
      "</div>" +
      '<ul class="sv-profile-legend">' + legendItems + "</ul>"
    );
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

  // Normalizes an exercise's sets into one row per set: { n, reps, weightKg, rpe }.
  // Falls back to synthesizing rows from the exercise-level sets/reps/weight/rpe
  // fields when there's no per-set breakdown, so every set gets its own row
  // instead of being collapsed into one ambiguous summary string.
  function getSetRows(ex) {
    var raw = parseSets(ex);
    if (raw.length) {
      return raw.map(function (s, i) {
        return {
          n: i + 1,
          reps: s.reps,
          weightKg: s.weight_kg,
          rpe: s.rpe != null ? s.rpe : null,
        };
      });
    }
    var count = ex.sets || 1;
    var rows = [];
    for (var i = 0; i < count; i++) {
      rows.push({ n: i + 1, reps: ex.reps, weightKg: ex.weight_kg, rpe: ex.rpe });
    }
    return rows;
  }

  // Quick-glance summary next to the exercise name. When every set shares the
  // same reps/weight this collapses to the familiar "N × M @ W kg" shorthand;
  // otherwise it falls back to a plain set count (the full breakdown is in
  // the table below either way).
  function setsSummaryText(rows) {
    if (!rows.length) return "";
    if (rows.length === 1)
      return "1 × " + dash(rows[0].reps) + " @ " + fmtWeight(rows[0].weightKg);
    var repsVary = rows.some(function (r) { return r.reps !== rows[0].reps; });
    var weightVaries = rows.some(function (r) { return r.weightKg !== rows[0].weightKg; });
    if (!repsVary && !weightVaries)
      return rows.length + " × " + dash(rows[0].reps) + " @ " + fmtWeight(rows[0].weightKg);
    return rows.length + " sets";
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
      '<p class="sv-stat-val">' + dash(value) + "</p>" +
      '<p class="sv-stat-label">' + label + "</p>" +
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

  // ── Exercises / sets table ───────────────────────────────────────────────

  function renderSetTable(ex) {
    var rows = getSetRows(ex);
    var hasRpeCol = rows.some(function (r) { return r.rpe != null; });

    var headerCells =
      '<th scope="col" role="columnheader">Set</th>' +
      '<th scope="col" role="columnheader">Reps</th>' +
      '<th scope="col" role="columnheader">Weight</th>' +
      (hasRpeCol ? '<th scope="col" role="columnheader">RPE</th>' : "");

    var bodyRows = rows.map(function (r) {
      return (
        '<tr role="row">' +
        '<td role="cell" data-label="Set"><span class="sv-set-num">' + r.n + "</span></td>" +
        '<td role="cell" data-label="Reps">' + dash(r.reps) + "</td>" +
        '<td role="cell" data-label="Weight">' + fmtWeight(r.weightKg) + "</td>" +
        (hasRpeCol ? '<td role="cell" data-label="RPE">' + dash(r.rpe) + "</td>" : "") +
        "</tr>"
      );
    }).join("");

    return (
      '<table class="sv-set-table" role="table">' +
      '<caption class="u-sr-only">Sets for ' + esc(ex.name || "exercise") + "</caption>" +
      '<thead role="rowgroup"><tr role="row">' + headerCells + "</tr></thead>" +
      '<tbody role="rowgroup">' + bodyRows + "</tbody>" +
      "</table>"
    );
  }

  function renderExercisesList(exercises) {
    if (!exercises || !exercises.length)
      return '<p class="sv-empty">No exercises recorded for this session.</p>';

    return (
      '<div class="sv-exercises-list">' +
      exercises.map(function (ex) {
        var tier = rpeTier(ex.rpe);
        var rpePillVal = ex.rpe != null ? "RPE " + ex.rpe : "—";
        var setRows = getSetRows(ex);
        return (
          '<div class="sv-exercise-block">' +
          '<div class="sv-ex-head">' +
          '<span class="sv-ex-bullet" style="background:' + tier.color + '" aria-hidden="true"></span>' +
          '<span class="sv-ex-name">' + esc(ex.name || "Exercise") + "</span>" +
          '<span class="sv-ex-count">' + esc(setsSummaryText(setRows)) + "</span>" +
          '<span class="sv-rpe-pill" style="background:' + tier.color + '">' + rpePillVal + "</span>" +
          "</div>" +
          renderSetTable(ex) +
          "</div>"
        );
      }).join("") +
      "</div>"
    );
  }

  // ── Badge helpers ─────────────────────────────────────────────────────────

  // Tinted background + dark ink text (instrument-system convention) rather
  // than a saturated fill with white text, which failed AA contrast at the
  // badge's 11px/bold size.
  var TYPE_COLORS = {
    strength: { bg: "#ede9fe", text: "#5b21b6" },
    lift: { bg: "#ede9fe", text: "#5b21b6" },
    "weight training": { bg: "#ede9fe", text: "#5b21b6" },
  };
  var TYPE_COLOR_DEFAULT = { bg: "#f1f5f9", text: "#334155" };

  function badgeColors(workoutType) {
    var t = (workoutType || "").toLowerCase();
    for (var key in TYPE_COLORS) {
      if (t.indexOf(key) !== -1) return TYPE_COLORS[key];
    }
    return TYPE_COLOR_DEFAULT;
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function renderView(data) {
    var w = data.workout;
    var exercises = w.exercises || [];
    var typeLabel = (w.workout_type || "Strength").toUpperCase();
    var colors = badgeColors(w.workout_type);

    var header =
      '<div class="sv-card sv-header">' +
      '<span class="sv-badge" style="background:' + colors.bg + ";color:" + colors.text + '">' + esc(typeLabel) + "</span>" +
      '<h1 class="sv-workout-name">' + esc(w.name || "Untitled") + "</h1>" +
      '<div class="sv-date">' + fmtDate(w.workout_date) + "</div>" +
      "</div>";

    var stats = computeStats(w, exercises);
    var statsCard =
      '<div class="sv-card sv-stats">' +
      '<h2 class="sv-section-title">Stats</h2>' +
      renderStatsGrid(stats) +
      "</div>";

    var profileBar = renderProfileBar(exercises);
    var profileCard = profileBar
      ? '<div class="sv-card sv-profile">' +
        '<h2 class="sv-section-title">Session Profile · Effort</h2>' +
        profileBar +
        "</div>"
      : "";

    var exercisesCard =
      '<div class="sv-card sv-exercises">' +
      '<h2 class="sv-section-title">Exercises</h2>' +
      renderExercisesList(exercises) +
      "</div>";

    var root = document.getElementById("sv-root");
    root.innerHTML = header + statsCard + profileCard + exercisesCard;
    root.setAttribute("aria-busy", "false");
  }

  // ── Error / loading states ───────────────────────────────────────────────

  function renderLoading() {
    var root = document.getElementById("sv-root");
    root.setAttribute("aria-busy", "true");
    root.innerHTML =
      '<div class="sv-card">' +
      '<div class="sv-skel-badge"></div>' +
      '<div class="sv-skel-title"></div>' +
      '<div class="sv-skel-date"></div>' +
      "</div>" +
      '<div class="sv-card">' +
      '<div class="sv-skel-tiles">' +
      '<div class="sv-skel-tile"></div><div class="sv-skel-tile"></div>' +
      '<div class="sv-skel-tile"></div><div class="sv-skel-tile"></div>' +
      '<div class="sv-skel-tile"></div><div class="sv-skel-tile"></div>' +
      "</div></div>" +
      '<div class="sv-card"><div class="sv-skel-bar"></div></div>' +
      '<div class="sv-card">' +
      '<div class="sv-skel-row"></div><div class="sv-skel-row"></div><div class="sv-skel-row"></div>' +
      "</div>";
  }

  function renderError(message) {
    var root = document.getElementById("sv-root");
    root.setAttribute("aria-busy", "false");
    root.innerHTML =
      '<div class="sv-error" role="alert">' +
      '<p class="sv-error__title">Couldn’t load this session</p>' +
      '<p class="sv-error__msg">' + esc(message) + "</p>" +
      '<button type="button" class="sv-retry-btn" id="sv-retry-btn">Try again</button>' +
      "</div>";
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  function getWorkoutId() {
    var params = new URLSearchParams(window.location.search);
    return params.get("id");
  }

  function init() {
    var workoutId = getWorkoutId();
    if (!workoutId) {
      renderError("No workout ID supplied. Add ?id=<workout-id> to the URL.");
      return;
    }
    renderLoading();
    fetch("/api/workouts/" + workoutId + "/full", { credentials: "include" })
      .then(function (r) {
        if (r.status === 404) throw new Error("This workout no longer exists.");
        if (!r.ok) throw new Error("Failed to load workout (" + r.status + ")");
        return r.json();
      })
      .then(function (data) {
        renderView(data);
      })
      .catch(function (err) {
        renderError(err.message);
      });
  }

  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "sv-retry-btn") init();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
