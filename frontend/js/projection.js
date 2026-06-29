(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  var _chart = null;
  var _planId = null;
  var _races = [];
  var _editingRaceId = null;
  var _editingRaceType = "race";
  var _confirmCallback = null;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function pad(n) { return String(n).padStart(2, "0"); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso + "T00:00:00");
    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
  }

  function weeksUntil(isoDate) {
    if (!isoDate) return null;
    var now = new Date();
    now.setHours(0, 0, 0, 0);
    var race = new Date(isoDate + "T00:00:00");
    var diff = race - now;
    if (diff <= 0) return 0;
    return Math.ceil(diff / (7 * 24 * 60 * 60 * 1000));
  }

  function fmtPace(secPerKm) {
    if (!secPerKm) return "—";
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    return m + ":" + pad(s) + " /km";
  }

  function fmtTime(totalSec) {
    if (!totalSec) return "—";
    var h = Math.floor(totalSec / 3600);
    var m = Math.floor((totalSec % 3600) / 60);
    var s = totalSec % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(s);
    return m + ":" + pad(s);
  }

  function parseGoalTime(str) {
    if (!str || !str.trim()) return null;
    var parts = str.split(":").map(Number);
    if (parts.some(isNaN)) return null;
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return null;
  }

  function goalTimeToStr(sec) {
    if (!sec) return "";
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(s);
    return m + ":" + pad(s);
  }

  // ── Plan ID (user ID is plan ID) ──────────────────────────────────────────
  function _ensurePlanId(cb) {
    if (_planId) { cb(); return; }
    var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (uid) { _planId = uid; cb(); return; }
    fetch("/api/auth/me", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) return null; return r.json(); })
      .then(function (u) { if (u) _planId = u.id; cb(); })
      .catch(function () { cb(); });
  }

  function _raceUrl(raceId) {
    return "/plans/" + _planId + "/races" + (raceId ? "/" + raceId : "");
  }

  // ── API helpers ───────────────────────────────────────────────────────────
  function apiGet(url, cb) {
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) return null; return r.json(); })
      .then(function (d) { cb(d); })
      .catch(function () { cb(null); });
  }

  function apiPostSimple(url, body, cb) {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
      })
      .then(cb)
      .catch(function (e) { cb({ ok: false, status: 0, data: { detail: e.message } }); });
  }

  function apiPatch(url, body, cb) {
    fetch(url, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
      })
      .then(cb)
      .catch(function (e) { cb({ ok: false, status: 0, data: { detail: e.message } }); });
  }

  function apiDelete(url, cb) {
    fetch(url, { method: "DELETE", credentials: "same-origin" })
      .then(function (r) { cb({ ok: r.ok, status: r.status }); })
      .catch(function (e) { cb({ ok: false, status: 0 }); });
  }

  // ── Score display ─────────────────────────────────────────────────────────
  function _fmtScore(v) {
    if (v == null || typeof v !== "number") return "—";
    return v.toFixed(1);
  }

  function renderScores(data) {
    var endEl = document.getElementById("proj-endurance-score");
    var speedEl = document.getElementById("proj-speed-score");
    var stateEl = document.getElementById("proj-score-state");

    if (!data) {
      if (endEl) endEl.textContent = "—";
      if (speedEl) speedEl.textContent = "—";
      if (stateEl) stateEl.textContent = "";
      return;
    }

    var state = data.score_state || "building_baseline";

    if (endEl) endEl.textContent = _fmtScore(data.endurance_score);
    if (speedEl) speedEl.textContent = _fmtScore(data.speed_score);

    if (stateEl) {
      if (state === "needs_thresholds") {
        stateEl.textContent = "Set thresholds in Settings to compute scores.";
      } else if (state === "building_baseline") {
        stateEl.textContent = "Building baseline — log more runs to see scores.";
      } else if (state === "error") {
        stateEl.textContent = "Could not compute scores.";
      } else {
        stateEl.textContent = "";
      }
    }
  }

  // ── Pace / form curve chart ───────────────────────────────────────────────
  function _renderCurve(data) {
    var emptyEl = document.getElementById("proj-curve-empty");
    var wrapEl = document.getElementById("proj-curve-wrap");
    var canvas = document.getElementById("proj-curve-canvas");

    if (!data || (!data.form_curve || data.form_curve.length === 0) && !data.projected_form) {
      if (emptyEl) emptyEl.style.display = "";
      if (wrapEl) wrapEl.style.display = "none";
      return;
    }

    if (emptyEl) emptyEl.style.display = "none";
    if (wrapEl) wrapEl.style.display = "";

    if (!canvas || typeof Chart === "undefined") return;

    var formCurve = data.form_curve || [];
    var projectedForm = data.projected_form || null;
    var raceMarkers = data.race_markers || [];
    var bRaceDate = data.b_race_recalibration_date || null;

    var historicalDates = [];
    var historicalValues = [];
    var projectedDates = [];
    var projectedValues = [];

    formCurve.forEach(function (pt) {
      historicalDates.push(pt.date);
      historicalValues.push(parseFloat(pt.form.toFixed(2)));
    });

    if (projectedForm) {
      Object.keys(projectedForm).sort().forEach(function (d) {
        projectedDates.push(d);
        projectedValues.push(parseFloat(projectedForm[d].toFixed(2)));
      });
    }

    var allDates = historicalDates.concat(projectedDates);
    var allValues = historicalValues.concat(projectedValues.map(function () { return null; }));
    var projOnlyValues = historicalDates.map(function () { return null; }).concat(projectedValues);

    if (_chart) {
      _chart.destroy();
      _chart = null;
    }

    // Build chart.js annotation objects for each race marker + B-race recalibration
    var annotations = {};

    // A/B/C race markers
    var PRIORITY_COLORS = {
      "A": { border: "rgba(21, 128, 61, 0.85)", bg: "rgba(21,128,61,0.85)" },
      "B": { border: "rgba(3, 105, 161, 0.7)", bg: "rgba(3,105,161,0.7)" },
      "C": { border: "rgba(100, 116, 139, 0.6)", bg: "rgba(100,116,139,0.6)" },
    };

    raceMarkers.forEach(function (race, idx) {
      var col = PRIORITY_COLORS[race.priority] || PRIORITY_COLORS["C"];
      var annotationKey = "race_" + idx + "_" + race.priority;
      annotations[annotationKey] = {
        type: "line",
        xMin: race.date,
        xMax: race.date,
        borderColor: col.border,
        borderWidth: race.priority === "A" ? 2 : 1.5,
        borderDash: race.priority === "A" ? [] : [4, 3],
        label: {
          content: race.priority + " Race" + (race.name ? ": " + race.name.slice(0, 20) : ""),
          enabled: true,
          position: "start",
          backgroundColor: col.bg,
          color: "#fff",
          font: { size: 9 },
        },
      };

      // B-race "recalibrates here" marker — drawn as a separate label annotation
      if (race.recalibrates_here && race.priority === "B") {
        annotations["b_recalibrate_" + idx] = {
          type: "line",
          xMin: race.date,
          xMax: race.date,
          borderColor: "rgba(217, 119, 6, 0.85)",
          borderWidth: 2,
          borderDash: [2, 2],
          label: {
            content: "↺ recalibrates here",
            enabled: true,
            position: "end",
            backgroundColor: "rgba(217,119,6,0.9)",
            color: "#fff",
            font: { size: 9 },
            yAdjust: 20,
          },
        };
      }
    });

    // Fresh / buried zone bands
    var freshFloor = 5;
    var buriedCeiling = -30;

    _chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: allDates,
        datasets: [
          {
            label: "Form (TSB)",
            data: allValues,
            borderColor: "#3563d4",
            borderWidth: 2,
            fill: false,
            tension: 0.35,
            pointRadius: 0,
            spanGaps: false,
          },
          {
            label: "Projected form",
            data: projOnlyValues,
            borderColor: "#3563d4",
            borderWidth: 2,
            borderDash: [6, 3],
            fill: false,
            tension: 0.35,
            pointRadius: 0,
            spanGaps: false,
          },
          {
            label: "Fresh zone",
            data: allDates.map(function () { return freshFloor; }),
            borderWidth: 0,
            backgroundColor: "rgba(34,197,94,0.1)",
            fill: { target: { value: 100 } },
            tension: 0,
            pointRadius: 0,
          },
          {
            label: "Buried zone",
            data: allDates.map(function () { return buriedCeiling; }),
            borderWidth: 0,
            backgroundColor: "rgba(239,68,68,0.1)",
            fill: { target: { value: -100 } },
            tension: 0,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ": " + (ctx.raw != null ? ctx.raw.toFixed(1) : "—");
              },
            },
          },
          annotation: {
            annotations: annotations,
          },
        },
        scales: {
          x: {
            type: "category",
            ticks: { maxTicksLimit: 8, font: { size: 10 }, color: "#9aa3b2" },
            grid: { display: false },
          },
          y: {
            ticks: { font: { size: 10 }, color: "#9aa3b2" },
            grid: { color: "#f0f2f8" },
          },
        },
        animation: { duration: 300 },
      },
    });
  }

  // ── Race list (plan editor) ───────────────────────────────────────────────
  function renderRacesList() {
    var container = document.getElementById("proj-races-list");
    var emptyEl = document.getElementById("proj-races-empty");
    if (!container) return;

    var sorted = _races.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });

    // Clear existing rows
    Array.from(container.querySelectorAll(".proj-race-row")).forEach(function (el) { el.remove(); });

    if (sorted.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    sorted.forEach(function (race) {
      var weeks = weeksUntil(race.date);
      var weeksText = weeks !== null && weeks > 0 ? " · " + weeks + "w" : "";
      var row = document.createElement("div");
      row.className = "proj-race-row";
      row.setAttribute("data-race-id", race.id);

      var priorityClass = "proj-priority-" + (race.priority || "").toLowerCase();
      var goalStr = race.goal_time_seconds ? fmtTime(race.goal_time_seconds) : "—";

      row.innerHTML =
        '<div class="proj-race-info">' +
        '<span class="proj-race-priority ' + priorityClass + '">' + esc(race.priority || race.type || "?") + '</span>' +
        '<span class="proj-race-name">' + esc(race.name || "Unnamed") + '</span>' +
        '<span class="proj-race-meta">' + esc(formatDate(race.date)) + weeksText +
        " · " + parseFloat(race.distance || 0).toFixed(1) + " km" +
        (race.goal_time_seconds ? " · Goal: " + esc(goalStr) : "") +
        "</span>" +
        "</div>" +
        '<div class="proj-race-actions">' +
        '<button class="proj-race-edit-btn" data-id="' + esc(race.id) + '" type="button">Edit</button>' +
        '<button class="proj-race-del-btn" data-id="' + esc(race.id) + '" type="button">✕</button>' +
        "</div>";

      container.appendChild(row);

      row.querySelector(".proj-race-edit-btn").addEventListener("click", function () {
        openModal(race);
      });
      row.querySelector(".proj-race-del-btn").addEventListener("click", function () {
        _deleteRow(race.id, race.name);
      });
    });
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadProjection(cb) {
    apiGet("/api/projection", function (data) {
      renderScores(data);
      _renderCurve(data);
      if (cb) cb();
    });
  }

  function loadRaces(cb) {
    if (!_planId) { _races = []; if (cb) cb(); return; }
    apiGet(_raceUrl(), function (data) {
      _races = Array.isArray(data) ? data : [];
      renderRacesList();
      if (cb) cb();
    });
  }

  function refresh() {
    _ensurePlanId(function () {
      // Load races and projection data in parallel; both update independently
      loadRaces();
      loadProjection();
    });
  }

  // ── Modal ─────────────────────────────────────────────────────────────────
  function openModal(race) {
    _editingRaceId = race ? race.id : null;

    var modal = document.getElementById("proj-race-modal");
    var title = document.getElementById("proj-modal-title");
    var nameIn = document.getElementById("proj-modal-name");
    var dateIn = document.getElementById("proj-modal-date");
    var distIn = document.getElementById("proj-modal-distance");
    var priorityIn = document.getElementById("proj-modal-priority");
    var goalIn = document.getElementById("proj-modal-goal-time");
    var deleteBtn = document.getElementById("proj-modal-delete-btn");
    var errEl = document.getElementById("proj-modal-error");

    if (!modal) return;

    if (title) title.textContent = race ? "Edit Race" : "Add Race";
    if (deleteBtn) deleteBtn.style.display = race ? "" : "none";
    if (errEl) errEl.textContent = "";

    if (race) {
      if (nameIn) nameIn.value = race.name || "";
      if (dateIn) dateIn.value = race.date || "";
      if (distIn) distIn.value = race.distance || "";
      if (priorityIn) priorityIn.value = race.priority || "A";
      if (goalIn) goalIn.value = goalTimeToStr(race.goal_time_seconds);
    } else {
      if (nameIn) nameIn.value = "";
      if (dateIn) dateIn.value = "";
      if (distIn) distIn.value = "";
      if (priorityIn) priorityIn.value = "A";
      if (goalIn) goalIn.value = "";
    }

    modal.style.display = "";
    if (nameIn) nameIn.focus();
  }

  function closeModal() {
    var modal = document.getElementById("proj-race-modal");
    if (modal) modal.style.display = "none";
  }

  function saveModal() {
    var nameIn = document.getElementById("proj-modal-name");
    var dateIn = document.getElementById("proj-modal-date");
    var distIn = document.getElementById("proj-modal-distance");
    var priorityIn = document.getElementById("proj-modal-priority");
    var goalIn = document.getElementById("proj-modal-goal-time");
    var errEl = document.getElementById("proj-modal-error");

    var name = nameIn ? nameIn.value.trim() : "";
    var date = dateIn ? dateIn.value : "";
    var dist = distIn ? parseFloat(distIn.value) : NaN;
    var priority = priorityIn ? priorityIn.value : "A";
    var goalSec = goalIn ? parseGoalTime(goalIn.value) : null;

    if (!date) { if (errEl) errEl.textContent = "Date is required."; return; }
    if (!dist || isNaN(dist) || dist <= 0) { if (errEl) errEl.textContent = "Distance must be a positive number."; return; }

    var body = {
      name: name,
      date: date,
      distance: dist,
      type: "race",
      priority: priority,
    };
    if (goalSec !== null) body.goal_time_seconds = goalSec;
    if (errEl) errEl.textContent = "";

    if (_editingRaceId) {
      // Patch existing race — use the /plans route for type/name/date/distance,
      // and separately patch priority via /api/races/{id}
      apiPatch(_raceUrl(_editingRaceId), body, function (res) {
        if (!res.ok) {
          if (errEl) errEl.textContent = (res.data && res.data.detail) ? JSON.stringify(res.data.detail) : "Save failed.";
          return;
        }
        // Also patch priority via the /api/races endpoint
        fetch("/api/races/" + _editingRaceId, {
          method: "PATCH",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ priority: priority }),
        }).finally(function () {
          closeModal();
          refresh();
        });
      });
    } else {
      apiPostSimple(_raceUrl(), body, function (res) {
        if (!res.ok) {
          if (errEl) errEl.textContent = (res.data && res.data.detail) ? JSON.stringify(res.data.detail) : "Save failed.";
          return;
        }
        // Patch priority on the newly created race
        var newId = res.data && res.data.id;
        if (newId && priority !== "A") {
          fetch("/api/races/" + newId, {
            method: "PATCH",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ priority: priority }),
          }).finally(function () {
            closeModal();
            refresh();
          });
        } else {
          closeModal();
          refresh();
        }
      });
    }
  }

  // ── Delete ────────────────────────────────────────────────────────────────
  function _showConfirm(title, msg, onConfirm) {
    var overlay = document.getElementById("proj-confirm-modal");
    var titleEl = document.getElementById("proj-confirm-title");
    var msgEl = document.getElementById("proj-confirm-msg");
    if (!overlay) return;
    _confirmCallback = onConfirm;
    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = msg;
    overlay.style.display = "";
  }

  function _closeConfirm() {
    var overlay = document.getElementById("proj-confirm-modal");
    if (overlay) overlay.style.display = "none";
    _confirmCallback = null;
  }

  function _deleteRow(raceId, raceName) {
    _showConfirm(
      "Delete race?",
      "\"" + (raceName || "Unnamed") + "\" will be permanently deleted.",
      function () {
        apiDelete(_raceUrl(raceId), function (res) {
          if (res.ok) refresh();
        });
      }
    );
  }

  function deleteEditing() {
    if (!_editingRaceId) return;
    var rid = _editingRaceId;
    var race = _races.find(function (r) { return r.id === rid; });
    closeModal();
    _showConfirm(
      "Delete race?",
      "This action cannot be undone.",
      function () {
        apiDelete(_raceUrl(rid), function (res) {
          if (res.ok) refresh();
        });
      }
    );
  }

  // ── Event wiring ──────────────────────────────────────────────────────────
  function _wire() {
    var addBtn = document.getElementById("proj-add-race-btn");
    if (addBtn) addBtn.addEventListener("click", function () { openModal(null); });

    var modalClose = document.getElementById("proj-modal-close");
    if (modalClose) modalClose.addEventListener("click", closeModal);

    var modalCancel = document.getElementById("proj-modal-cancel");
    if (modalCancel) modalCancel.addEventListener("click", closeModal);

    var modalSave = document.getElementById("proj-modal-save");
    if (modalSave) modalSave.addEventListener("click", saveModal);

    var modalDelete = document.getElementById("proj-modal-delete-btn");
    if (modalDelete) modalDelete.addEventListener("click", deleteEditing);

    var confirmCancel = document.getElementById("proj-confirm-cancel");
    if (confirmCancel) confirmCancel.addEventListener("click", _closeConfirm);

    var confirmOk = document.getElementById("proj-confirm-ok");
    if (confirmOk) confirmOk.addEventListener("click", function () {
      var cb = _confirmCallback;
      _closeConfirm();
      if (cb) cb();
    });

    var raceModal = document.getElementById("proj-race-modal");
    if (raceModal) raceModal.addEventListener("click", function (e) {
      if (e.target === raceModal) closeModal();
    });

    var confirmModal = document.getElementById("proj-confirm-modal");
    if (confirmModal) confirmModal.addEventListener("click", function (e) {
      if (e.target === confirmModal) _closeConfirm();
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    _wire();
    refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
