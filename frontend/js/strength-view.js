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

  function isStrength(workoutType) {
    var t = (workoutType || "").toLowerCase();
    return t === "strength" || t === "lift" || t.indexOf("weight") !== -1;
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

    var allSets = [];
    exercises.forEach(function (ex) {
      var sets = parseSets(ex);
      if (sets.length) {
        sets.forEach(function (s) {
          allSets.push({ rpe: s.rpe, duration: s.duration_seconds, exRpe: ex.rpe });
        });
      } else {
        allSets.push({ rpe: ex.rpe, duration: ex.duration_seconds, exRpe: ex.rpe });
      }
    });

    if (!allSets.length) return "";

    var totalDur = allSets.reduce(function (sum, s) {
      return sum + (s.duration || 0);
    }, 0);
    var defaultWidthPct = 100 / allSets.length;

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

  // ── TSS prompt ─────────────────────────────────────────────────────────────

  function renderTssPrompt() {
    return (
      '<div class="sv-card sv-tss-prompt" id="sv-tss-prompt">' +
      '<h2 class="sv-section-title">Log Training Stress</h2>' +
      '<p class="sv-tss-hint">No TSS recorded yet. Enter a session RPE (1–10) to calculate training stress score.</p>' +
      '<div class="sv-tss-rpe-row">' +
      '<label class="sv-tss-label" for="sv-tss-rpe">Session RPE</label>' +
      '<input type="range" id="sv-tss-rpe" min="1" max="10" step="1" value="7" class="sv-tss-slider"/>' +
      '<span class="sv-tss-rpe-val" id="sv-tss-rpe-val">7</span>' +
      '</div>' +
      '<div class="sv-tss-actions">' +
      '<button type="button" class="sv-btn sv-tss-calc-btn" id="sv-tss-calc-btn">Calculate &amp; Save TSS</button>' +
      '<span id="sv-tss-msg" class="sv-tss-msg"></span>' +
      '</div>' +
      '</div>'
    );
  }

  // ── Workout → portable JSON ───────────────────────────────────────────────

  function workoutToJson(w) {
    var obj = {
      name: w.name || "",
      date: w.workout_date || "",
      type: w.workout_type || "",
    };
    if (w.remarks) obj.remarks = w.remarks;
    var exArr = (w.exercises || []).map(function (ex) {
      var e = { name: ex.name || "" };
      if (ex.sets != null) e.sets = ex.sets;
      if (ex.reps != null) e.reps = ex.reps;
      if (ex.weight_kg != null) e.weight_kg = parseFloat(ex.weight_kg);
      if (ex.rpe != null) e.rpe = ex.rpe;
      return e;
    });
    if (exArr.length) obj.exercises = exArr;
    return obj;
  }

  // ── JSON panel ─────────────────────────────────────────────────────────────

  function renderJsonPanel(w) {
    var json = JSON.stringify(workoutToJson(w), null, 2);
    return (
      '<div class="sv-card sv-json-panel" id="sv-json-panel">' +
      '<p class="sv-json-hint">Edit workout details and exercises. Supported exercise fields: <code>name</code>, <code>sets</code>, <code>reps</code>, <code>weight_kg</code>, <code>rpe</code> (1–10).</p>' +
      '<textarea id="sv-json-ta" class="sv-json-ta" spellcheck="false">' + esc(json) + '</textarea>' +
      '<div class="sv-json-actions">' +
      '<button type="button" class="sv-btn sv-json-save-btn" id="sv-json-save-btn">Save changes</button>' +
      '<span id="sv-json-msg" class="sv-json-msg"></span>' +
      '</div>' +
      '</div>'
    );
  }

  // ── State ─────────────────────────────────────────────────────────────────

  var _currentWorkout = null;
  var _activeTab = "view";

  // ── Tab wiring ─────────────────────────────────────────────────────────────

  function switchTab(tab) {
    _activeTab = tab;
    var viewPanel = document.getElementById("sv-view-panel");
    var jsonPanel = document.getElementById("sv-json-panel");
    var tabView = document.getElementById("sv-tab-view");
    var tabJson = document.getElementById("sv-tab-json");
    if (!viewPanel || !jsonPanel) return;
    if (tab === "json") {
      viewPanel.hidden = true;
      jsonPanel.hidden = false;
      if (tabView) tabView.classList.remove("sv-tab-on");
      if (tabJson) tabJson.classList.add("sv-tab-on");
    } else {
      viewPanel.hidden = false;
      jsonPanel.hidden = true;
      if (tabView) tabView.classList.add("sv-tab-on");
      if (tabJson) tabJson.classList.remove("sv-tab-on");
    }
  }

  // ── TSS wiring ─────────────────────────────────────────────────────────────

  function wireTssPrompt(workoutId) {
    var slider = document.getElementById("sv-tss-rpe");
    var valSpan = document.getElementById("sv-tss-rpe-val");
    var calcBtn = document.getElementById("sv-tss-calc-btn");
    var msg = document.getElementById("sv-tss-msg");
    if (!slider || !calcBtn) return;

    slider.addEventListener("input", function () {
      if (valSpan) valSpan.textContent = slider.value;
    });

    calcBtn.addEventListener("click", function () {
      var rpe = parseInt(slider.value, 10);
      calcBtn.disabled = true;
      if (msg) { msg.textContent = "Calculating…"; msg.className = "sv-tss-msg"; }
      fetch("/api/workouts/" + workoutId + "/compute-tss", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_rpe: rpe }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("Error " + r.status)); });
          return r.json();
        })
        .then(function (data) {
          _currentWorkout = data;
          // Re-render with updated data — TSS is now set so prompt disappears
          renderView({ workout: data });
          // Update stats tile immediately so user sees the change
        })
        .catch(function (err) {
          calcBtn.disabled = false;
          if (msg) { msg.textContent = err.message; msg.className = "sv-tss-msg sv-tss-msg-err"; }
        });
    });
  }

  // ── JSON save wiring ────────────────────────────────────────────────────────

  function wireJsonPanel(workoutId) {
    var saveBtn = document.getElementById("sv-json-save-btn");
    var ta = document.getElementById("sv-json-ta");
    var msg = document.getElementById("sv-json-msg");
    if (!saveBtn || !ta) return;

    saveBtn.addEventListener("click", function () {
      var parsed;
      try {
        parsed = JSON.parse(ta.value);
      } catch (e) {
        if (msg) { msg.textContent = "Invalid JSON: " + e.message; msg.className = "sv-json-msg sv-json-msg-err"; }
        return;
      }
      saveBtn.disabled = true;
      if (msg) { msg.textContent = "Saving…"; msg.className = "sv-json-msg"; }

      // PATCH workout fields (name, date, type, remarks)
      var patchBody = {};
      if (parsed.name != null) patchBody.name = parsed.name;
      if (parsed.date != null) patchBody.workout_date = parsed.date;
      if (parsed.type != null) patchBody.workout_type = parsed.type;
      if ("remarks" in parsed) patchBody.remarks = parsed.remarks || null;

      var exercises = parsed.exercises || [];

      fetch("/api/workouts/" + workoutId, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patchBody),
      })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("Patch failed: " + r.status)); });
          return r.json();
        })
        .then(function () {
          return fetch("/api/workouts/" + workoutId + "/exercises/replace", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ exercises: exercises }),
          });
        })
        .then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("Replace failed: " + r.status)); });
          return r.json();
        })
        .then(function (data) {
          _currentWorkout = data;
          if (msg) { msg.textContent = "Saved!"; msg.className = "sv-json-msg sv-json-msg-ok"; }
          saveBtn.disabled = false;
          // Re-render view panel with updated data, stay on JSON tab
          var viewPanel = document.getElementById("sv-view-panel");
          if (viewPanel) {
            var w = data;
            var exercises2 = w.exercises || [];
            var stats = computeStats(w, exercises2);
            var profBar = renderProfileBar(exercises2);
            var needTss = w.tss == null && isStrength(w.workout_type);
            viewPanel.innerHTML =
              renderStatsCard(stats) +
              (profBar ? renderProfileCard(profBar) : "") +
              renderExercisesCard(exercises2) +
              (needTss ? renderTssPrompt() : "");
            if (needTss) wireTssPrompt(workoutId);
          }
          // Update JSON textarea with canonical server response
          if (ta) ta.value = JSON.stringify(workoutToJson(data), null, 2);
        })
        .catch(function (err) {
          saveBtn.disabled = false;
          if (msg) { msg.textContent = err.message; msg.className = "sv-json-msg sv-json-msg-err"; }
        });
    });
  }

  // ── Card fragments ─────────────────────────────────────────────────────────

  function renderStatsCard(stats) {
    return (
      '<div class="sv-card sv-stats">' +
      '<h2 class="sv-section-title">Stats</h2>' +
      renderStatsGrid(stats) +
      "</div>"
    );
  }

  function renderProfileCard(profBar) {
    return (
      '<div class="sv-card sv-profile">' +
      '<h2 class="sv-section-title">Session Profile · Effort</h2>' +
      profBar +
      "</div>"
    );
  }

  function renderExercisesCard(exercises) {
    return (
      '<div class="sv-card sv-exercises">' +
      '<h2 class="sv-section-title">Exercises</h2>' +
      renderExercisesList(exercises) +
      "</div>"
    );
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function renderView(data) {
    var w = data.workout;
    _currentWorkout = w;
    var exercises = w.exercises || [];
    var typeLabel = (w.workout_type || "Strength").toUpperCase();
    var colors = badgeColors(w.workout_type);
    var workoutId = getWorkoutId();

    var header =
      '<div class="sv-card sv-header">' +
      '<span class="sv-badge" style="background:' + colors.bg + ";color:" + colors.text + '">' + esc(typeLabel) + "</span>" +
      '<h1 class="sv-workout-name">' + esc(w.name || "Untitled") + "</h1>" +
      '<div class="sv-date">' + fmtDate(w.workout_date) + "</div>" +
      "</div>";

    var tabs =
      '<div class="sv-tabs" id="sv-tabs">' +
      '<button type="button" class="sv-tab sv-tab-on" id="sv-tab-view" data-sv-tab="view">View</button>' +
      '<button type="button" class="sv-tab" id="sv-tab-json" data-sv-tab="json">JSON</button>' +
      "</div>";

    var stats = computeStats(w, exercises);
    var profBar = renderProfileBar(exercises);
    var needTss = w.tss == null && isStrength(w.workout_type);

    var viewPanel =
      '<div id="sv-view-panel">' +
      renderStatsCard(stats) +
      (profBar ? renderProfileCard(profBar) : "") +
      renderExercisesCard(exercises) +
      (needTss ? renderTssPrompt() : "") +
      "</div>";

    var jsonPanelHtml =
      '<div id="sv-json-wrapper">' +
      renderJsonPanel(w) +
      "</div>";
    // Hide json panel by default — we apply hidden attr after insertion
    var jsonPanelWrapped = jsonPanelHtml.replace('<div id="sv-json-wrapper">', '<div id="sv-json-wrapper" hidden>');

    var root = document.getElementById("sv-root");
    root.innerHTML = header + tabs + viewPanel + jsonPanelWrapped;
    root.setAttribute("aria-busy", "false");

    // Restore tab state if user was on JSON tab (e.g. after save re-render)
    if (_activeTab === "json") {
      var vp = document.getElementById("sv-view-panel");
      var jw = document.getElementById("sv-json-wrapper");
      var tv = document.getElementById("sv-tab-view");
      var tj = document.getElementById("sv-tab-json");
      if (vp) vp.hidden = true;
      if (jw) jw.hidden = false;
      if (tv) tv.classList.remove("sv-tab-on");
      if (tj) tj.classList.add("sv-tab-on");
    }

    if (needTss) wireTssPrompt(workoutId);
    wireJsonPanel(workoutId);
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

  // ── Global event delegation ────────────────────────────────────────────────

  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "sv-retry-btn") {
      _activeTab = "view";
      init();
    }
    // Tab switching
    var tab = e.target && e.target.getAttribute("data-sv-tab");
    if (tab) {
      _activeTab = tab;
      var vp = document.getElementById("sv-view-panel");
      var jw = document.getElementById("sv-json-wrapper");
      var tv = document.getElementById("sv-tab-view");
      var tj = document.getElementById("sv-tab-json");
      if (tab === "json") {
        if (vp) vp.hidden = true;
        if (jw) jw.hidden = false;
        if (tv) tv.classList.remove("sv-tab-on");
        if (tj) tj.classList.add("sv-tab-on");
      } else {
        if (vp) vp.hidden = false;
        if (jw) jw.hidden = true;
        if (tv) tv.classList.add("sv-tab-on");
        if (tj) tj.classList.remove("sv-tab-on");
      }
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
