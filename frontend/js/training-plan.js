(function () {
  "use strict";

  // ── State ─────────────────────────────────────────────────────────────────
  var _initialized = false;
  var _races = [];
  var _primaryRace = null;
  var _readiness = null;
  var _formCurveChart = null;
  var _editingRaceId = null;
  var _editingRaceType = "race";
  var _confirmCallback = null;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function pad(n) { return String(n).padStart(2, "0"); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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

  function fmtKm(v) {
    if (v == null) return "—";
    return parseFloat(v).toFixed(2);
  }

  // ── API calls ─────────────────────────────────────────────────────────────
  function apiGet(url, cb) {
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(cb)
      .catch(function (e) { console.warn("[plan] GET", url, e); cb(null); });
  }

  function apiPost(url, body, cb) {
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

  function apiPut(url, body, cb) {
    fetch(url, {
      method: "PUT",
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

  // ── Race header ───────────────────────────────────────────────────────────
  function renderRaceHeader() {
    var el = document.getElementById("plan-race-header-content");
    if (!el) return;

    if (!_primaryRace) {
      el.innerHTML =
        '<div class="plan-no-race">' +
        '<span>No A-priority race set. Add your main race to start planning.</span>' +
        '<button id="plan-header-add-btn" class="plan-add-btn" type="button">+ Add Race</button>' +
        '</div>';
      var addBtn = document.getElementById("plan-header-add-btn");
      if (addBtn) addBtn.addEventListener("click", function () { openModal(null, "race"); });
      return;
    }

    var r = _primaryRace;
    var weeks = weeksUntil(r.race_date);
    var weeksHtml = weeks !== null && weeks > 0
      ? '<span class="plan-weeks-chip">⏱ ' + weeks + ' week' + (weeks === 1 ? "" : "s") + ' to go</span>'
      : "";

    var goalTime = r.goal_time_seconds ? fmtTime(r.goal_time_seconds) : null;
    // AC9: compute goal pace client-side when server field is absent
    var goalPaceSecPerKm = r.goal_pace_seconds_per_km ||
      (r.goal_time_seconds && r.distance_km
        ? r.goal_time_seconds / parseFloat(r.distance_km)
        : null);
    var goalPace = goalPaceSecPerKm ? fmtPace(goalPaceSecPerKm) : null;

    el.innerHTML =
      '<div class="plan-race-hd">' +
      '<div class="plan-race-hd-info">' +
      '<h2 class="plan-race-hd-name">' +
      '<span class="plan-priority-badge pri-' + esc(r.priority.toLowerCase()) + '">' + esc(r.priority) + '</span>' +
      esc(r.name) +
      '</h2>' +
      '<div class="plan-race-meta">' +
      '<div class="plan-race-meta-item"><span class="plan-meta-label">Date</span><span class="plan-meta-value">' + esc(formatDate(r.race_date)) + '</span></div>' +
      '<div class="plan-race-meta-item"><span class="plan-meta-label">Distance</span><span class="plan-meta-value">' + parseFloat(r.distance_km).toFixed(3).replace(/\.?0+$/, "") + ' km</span></div>' +
      (goalTime ? '<div class="plan-race-meta-item"><span class="plan-meta-label">Goal time</span><span class="plan-meta-value">' + esc(goalTime) + '</span></div>' : '') +
      (goalPace ? '<div class="plan-race-meta-item"><span class="plan-meta-label">Goal pace</span><span class="plan-meta-value">' + esc(goalPace) + '</span></div>' : '') +
      '</div>' +
      weeksHtml +
      '</div>' +
      '</div>';
  }

  // ── Verdict banner ────────────────────────────────────────────────────────
  function renderVerdict() {
    var el = document.getElementById("plan-verdict");
    if (!el) return;

    if (!_readiness || !_primaryRace) {
      el.style.display = "none";
      return;
    }

    var onTrack = _readiness.on_track;
    var status = onTrack && onTrack.status_summary;
    var cls, label;

    // AC2: show raw status text from the endpoint; hide for other statuses
    if (status === "on track" || status === "ahead") {
      cls = "verdict-on-track";
      label = status;
    } else if (status === "behind") {
      cls = "verdict-at-risk";
      label = status;
    } else {
      el.style.display = "none";
      return;
    }

    el.className = "plan-verdict " + cls;
    el.textContent = label;
    el.style.display = "";
  }

  // ── Performance curve ─────────────────────────────────────────────────────
  function renderCurve() {
    var emptyEl = document.getElementById("plan-curve-empty");
    var baselineEl = document.getElementById("plan-building-baseline");
    var wrapEl = document.getElementById("plan-curve-wrap");
    if (!emptyEl || !baselineEl || !wrapEl) return;

    if (!_readiness || !_primaryRace) {
      emptyEl.style.display = "";
      baselineEl.style.display = "none";
      wrapEl.style.display = "none";
      return;
    }

    if (_readiness.building_baseline) {
      emptyEl.style.display = "none";
      baselineEl.style.display = "";
      wrapEl.style.display = "none";
      return;
    }

    var formCurve = _readiness.form_curve || [];
    var projectedForm = _readiness.projected_form || null;

    if (formCurve.length === 0 && !projectedForm) {
      emptyEl.style.display = "";
      baselineEl.style.display = "none";
      wrapEl.style.display = "none";
      return;
    }

    emptyEl.style.display = "none";
    baselineEl.style.display = "none";
    wrapEl.style.display = "";

    var canvas = document.getElementById("plan-form-curve");
    if (!canvas || typeof Chart === "undefined") return;

    var today = todayISO();
    var historicalDates = [];
    var historicalValues = [];
    var projectedDates = [];
    var projectedValues = [];
    var buriedData = [];
    var freshData = [];

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

    var buriedCeiling = -30;
    var freshFloor = 5;

    allDates.forEach(function (d) {
      buriedData.push(buriedCeiling);
      freshData.push(freshFloor);
    });

    if (_formCurveChart) {
      _formCurveChart.destroy();
      _formCurveChart = null;
    }

    // Taper marker: taper_recommendation.taper_start_date
    var taperDate = _readiness.taper_recommendation && _readiness.taper_recommendation.taper_start_date
      ? _readiness.taper_recommendation.taper_start_date
      : null;

    var annotations = {};
    if (taperDate) {
      annotations.taperLine = {
        type: "line",
        xMin: taperDate,
        xMax: taperDate,
        borderColor: "rgba(180, 83, 9, 0.7)",
        borderWidth: 1.5,
        borderDash: [4, 4],
        label: { content: "Taper", enabled: true, position: "start", backgroundColor: "rgba(180,83,9,0.8)", color: "#fff", font: { size: 10 } },
      };
    }

    // Race day marker
    if (_primaryRace && _primaryRace.race_date) {
      annotations.raceLine = {
        type: "line",
        xMin: _primaryRace.race_date,
        xMax: _primaryRace.race_date,
        borderColor: "rgba(21, 128, 61, 0.8)",
        borderWidth: 2,
        label: { content: "Race day", enabled: true, position: "start", backgroundColor: "rgba(21,128,61,0.8)", color: "#fff", font: { size: 10 } },
      };
    }

    // B-race and checkpoint markers from the races list
    _races.forEach(function (race) {
      if (race.priority === "B" && race.id !== (_primaryRace && _primaryRace.id)) {
        annotations["brace_" + race.id] = {
          type: "line",
          xMin: race.race_date,
          xMax: race.race_date,
          borderColor: "rgba(3, 105, 161, 0.6)",
          borderWidth: 1,
          borderDash: [3, 3],
        };
      }
      if (race.race_type === "checkpoint") {
        annotations["cp_" + race.id] = {
          type: "line",
          xMin: race.race_date,
          xMax: race.race_date,
          borderColor: "rgba(100, 116, 139, 0.5)",
          borderWidth: 1,
          borderDash: [2, 4],
        };
      }
    });

    _formCurveChart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: allDates,
        datasets: [
          {
            label: "Historical form",
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
            backgroundColor: "rgba(34, 197, 94, 0.1)",
            fill: { target: { value: 100 } },
            tension: 0,
            pointRadius: 0,
          },
          {
            label: "Buried zone",
            data: allDates.map(function () { return buriedCeiling; }),
            borderWidth: 0,
            backgroundColor: "rgba(239, 68, 68, 0.1)",
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
              label: function (ctx) { return ctx.dataset.label + ": " + (ctx.raw != null ? ctx.raw.toFixed(1) : "—"); },
            },
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

  // ── Races list ────────────────────────────────────────────────────────────
  function renderRacesList() {
    var container = document.getElementById("plan-races");
    var loadingEl = document.getElementById("plan-races-loading");
    var emptyEl = document.getElementById("plan-races-empty");
    if (!container) return;

    if (loadingEl) loadingEl.style.display = "none";

    var filtered = _races.slice().sort(function (a, b) {
      return a.race_date < b.race_date ? -1 : a.race_date > b.race_date ? 1 : 0;
    });

    if (filtered.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    var html = "";
    filtered.forEach(function (r) {
      var typeBadge = '<span class="plan-race-type-badge type-' + esc(r.race_type || "race") + '">' + esc(r.race_type === "checkpoint" ? "Checkpoint" : "Race") + '</span>';
      var metBadge = '<span class="plan-met-badge met-' + esc(r.met_status || "upcoming") + '">' + esc(metLabel(r.met_status)) + '</span>';
      var priLabel = r.priority ? '<span class="plan-priority-badge pri-' + esc(r.priority.toLowerCase()) + '" style="width:auto;height:auto;padding:1px 6px;font-size:10px;">' + esc(r.priority) + '</span>' : "";

      html +=
        '<div class="plan-race-row" data-race-id="' + esc(r.id) + '" tabindex="0" role="button" aria-label="Edit ' + esc(r.name) + '">' +
        '<div class="plan-race-row-info">' +
        '<p class="plan-race-row-name">' + esc(r.name || "(unnamed)") + '</p>' +
        '<div class="plan-race-row-meta">' +
        typeBadge +
        ' ' + priLabel +
        ' <span>' + esc(formatDate(r.race_date)) + '</span>' +
        ' <span>' + parseFloat(r.distance_km || 0).toFixed(2) + ' km</span>' +
        ' ' + metBadge +
        '</div>' +
        '</div>' +
        '<span style="color:#ccc;font-size:16px;">›</span>' +
        '</div>';
    });

    // Remove existing race rows
    Array.from(container.querySelectorAll(".plan-race-row")).forEach(function (el) { el.remove(); });
    container.insertAdjacentHTML("beforeend", html);

    container.querySelectorAll(".plan-race-row").forEach(function (row) {
      function handler() {
        var raceId = row.dataset.raceId;
        var race = _races.find(function (r) { return r.id === raceId; });
        if (race) openModal(race, race.race_type || "race");
      }
      row.addEventListener("click", handler);
      row.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") handler(); });
    });
  }

  function metLabel(status) {
    if (status === "met") return "Met";
    if (status === "missed") return "Missed";
    return "Upcoming";
  }

  // ── Specificity bars ──────────────────────────────────────────────────────
  function renderSpecBars() {
    var barsEl = document.getElementById("plan-spec-bars");
    var emptyEl = document.getElementById("plan-spec-empty");
    if (!barsEl || !emptyEl) return;

    if (!_readiness || !_readiness.specificity_progress) {
      barsEl.style.display = "none";
      emptyEl.style.display = "";
      return;
    }

    var sp = _readiness.specificity_progress;
    if (sp.reason) {
      barsEl.style.display = "none";
      emptyEl.style.display = "";
      return;
    }

    barsEl.style.display = "";
    emptyEl.style.display = "none";

    function updateBar(currentId, targetId, fillId, current, target) {
      var cEl = document.getElementById(currentId);
      var tEl = document.getElementById(targetId);
      var fEl = document.getElementById(fillId);
      if (cEl) cEl.textContent = fmtKm(current);
      if (tEl) tEl.textContent = fmtKm(target);
      if (fEl) {
        var pct = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;
        fEl.style.transform = "scaleX(" + (pct / 100) + ")";
      }
    }

    if (sp.volume_at_pace) {
      updateBar("plan-spec-volume-current", "plan-spec-volume-target", "plan-spec-volume-fill",
        sp.volume_at_pace.current, sp.volume_at_pace.target);
    }
    if (sp.longest_pace_effort) {
      updateBar("plan-spec-pace-current", "plan-spec-pace-target", "plan-spec-pace-fill",
        sp.longest_pace_effort.current, sp.longest_pace_effort.target);
    }
    if (sp.longest_run_by_distance) {
      updateBar("plan-spec-slower-current", "plan-spec-slower-target", "plan-spec-slower-fill",
        sp.longest_run_by_distance.current, sp.longest_run_by_distance.target);
    }
    if (sp.longest_run_by_duration) {
      var durCurrent = sp.longest_run_by_duration.current || 0;
      var durTarget = sp.longest_run_by_duration.target || 0;
      var cEl = document.getElementById("plan-spec-duration-current");
      var tEl = document.getElementById("plan-spec-duration-target");
      var fEl = document.getElementById("plan-spec-duration-fill");
      if (cEl) cEl.textContent = fmtTime(durCurrent) || "—";
      if (tEl) tEl.textContent = fmtTime(durTarget) || "—";
      if (fEl) {
        var pct = durTarget > 0 ? Math.min(100, Math.round((durCurrent / durTarget) * 100)) : 0;
        fEl.style.transform = "scaleX(" + (pct / 100) + ")";
      }
    }
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadRaces(done) {
    apiGet("/api/races", function (data) {
      _races = Array.isArray(data) ? data : [];
      _primaryRace = _races.find(function (r) { return r.priority === "A" && r.race_type !== "checkpoint" && r.status !== "abandoned"; }) || null;
      if (done) done();
    });
  }

  function loadReadiness(done) {
    if (!_primaryRace) {
      _readiness = null;
      if (done) done();
      return;
    }
    apiGet("/api/races/" + _primaryRace.id + "/readiness", function (data) {
      _readiness = data;
      if (done) done();
    });
  }

  function renderAll() {
    renderRaceHeader();
    renderVerdict();
    renderCurve();
    renderRacesList();
    renderSpecBars();
  }

  function refresh() {
    loadRaces(function () {
      loadReadiness(function () {
        renderAll();
      });
    });
  }

  // ── Modal ─────────────────────────────────────────────────────────────────
  function openModal(race, raceType) {
    _editingRaceId = race ? race.id : null;
    _editingRaceType = raceType || "race";

    var modal = document.getElementById("plan-race-modal");
    var title = document.getElementById("plan-modal-title");
    var nameIn = document.getElementById("plan-modal-name");
    var dateIn = document.getElementById("plan-modal-date");
    var distIn = document.getElementById("plan-modal-distance");
    var priIn = document.getElementById("plan-modal-priority");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var statusIn = document.getElementById("plan-modal-status");
    var deleteBtn = document.getElementById("plan-modal-delete-btn");
    var errEl = document.getElementById("plan-modal-error");
    var priField = document.getElementById("plan-modal-priority-field");

    if (!modal) return;

    var isCheckpoint = _editingRaceType === "checkpoint";

    if (title) title.textContent = race
      ? (isCheckpoint ? "Edit Checkpoint" : "Edit Race")
      : (isCheckpoint ? "Add Checkpoint" : "Add Race");
    if (priField) priField.style.display = isCheckpoint ? "none" : "";
    if (deleteBtn) deleteBtn.style.display = race ? "" : "none";
    if (errEl) errEl.textContent = "";

    if (race) {
      if (nameIn) nameIn.value = race.name || "";
      if (dateIn) dateIn.value = race.race_date || "";
      if (distIn) distIn.value = race.distance_km || "";
      if (priIn) priIn.value = race.priority || "A";
      if (goalIn) goalIn.value = goalTimeToStr(race.goal_time_seconds);
      if (statusIn) statusIn.value = race.status || "planned";
    } else {
      if (nameIn) nameIn.value = "";
      if (dateIn) dateIn.value = "";
      if (distIn) distIn.value = "";
      if (priIn) priIn.value = isCheckpoint ? "C" : "A";
      if (goalIn) goalIn.value = "";
      if (statusIn) statusIn.value = "planned";
    }

    modal.style.display = "";
    if (nameIn) nameIn.focus();
  }

  function closeModal() {
    var modal = document.getElementById("plan-race-modal");
    if (modal) modal.style.display = "none";
  }

  function saveModal() {
    var nameIn = document.getElementById("plan-modal-name");
    var dateIn = document.getElementById("plan-modal-date");
    var distIn = document.getElementById("plan-modal-distance");
    var priIn = document.getElementById("plan-modal-priority");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var statusIn = document.getElementById("plan-modal-status");
    var errEl = document.getElementById("plan-modal-error");

    var name = nameIn ? nameIn.value.trim() : "";
    var date = dateIn ? dateIn.value : "";
    var dist = distIn ? parseFloat(distIn.value) : NaN;
    var pri = priIn ? priIn.value : (_editingRaceType === "checkpoint" ? "C" : "A");
    var goalSec = goalIn ? parseGoalTime(goalIn.value) : null;
    var status = statusIn ? statusIn.value : "planned";

    if (!date) { if (errEl) errEl.textContent = "Date is required."; return; }
    if (isNaN(dist) || dist <= 0) { if (errEl) errEl.textContent = "Distance must be a positive number."; return; }

    var body = {
      name: name,
      race_date: date,
      distance_km: dist,
      priority: pri,
      status: status,
      race_type: _editingRaceType,
    };
    if (goalSec !== null) body.goal_time_seconds = goalSec;

    if (errEl) errEl.textContent = "";

    if (_editingRaceId) {
      apiPut("/api/races/" + _editingRaceId, body, function (res) {
        if (!res.ok) {
          if (errEl) errEl.textContent = (res.data && res.data.detail) ? JSON.stringify(res.data.detail) : "Save failed.";
          return;
        }
        closeModal();
        refresh();
      });
    } else {
      apiPost("/api/races", body, function (res) {
        if (!res.ok) {
          if (errEl) errEl.textContent = (res.data && res.data.detail) ? JSON.stringify(res.data.detail) : "Save failed.";
          return;
        }
        closeModal();
        refresh();
      });
    }
  }

  // ── Confirm dialog ────────────────────────────────────────────────────────
  function showConfirm(title, msg, onConfirm) {
    var overlay = document.getElementById("plan-confirm-modal");
    var titleEl = document.getElementById("plan-confirm-title");
    var msgEl = document.getElementById("plan-confirm-msg");
    if (!overlay) return;
    _confirmCallback = onConfirm;
    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = msg;
    overlay.style.display = "";
  }

  function closeConfirm() {
    var overlay = document.getElementById("plan-confirm-modal");
    if (overlay) overlay.style.display = "none";
    _confirmCallback = null;
  }

  function deleteEditing() {
    if (!_editingRaceId) return;
    var rid = _editingRaceId;
    var race = _races.find(function (r) { return r.id === rid; });
    var label = race ? (race.race_type === "checkpoint" ? "checkpoint" : "race") : "entry";
    closeModal();
    showConfirm(
      "Delete this " + label + "?",
      "This action cannot be undone.",
      function () {
        apiDelete("/api/races/" + rid, function (res) {
          if (res.ok) refresh();
        });
      }
    );
  }

  // ── Event wiring ──────────────────────────────────────────────────────────
  function wireEvents() {
    var addRaceBtn = document.getElementById("plan-add-race-btn");
    if (addRaceBtn) addRaceBtn.addEventListener("click", function () { openModal(null, "race"); });

    var addCpBtn = document.getElementById("plan-add-checkpoint-btn");
    if (addCpBtn) addCpBtn.addEventListener("click", function () { openModal(null, "checkpoint"); });

    var modalClose = document.getElementById("plan-modal-close");
    if (modalClose) modalClose.addEventListener("click", closeModal);

    var modalCancel = document.getElementById("plan-modal-cancel");
    if (modalCancel) modalCancel.addEventListener("click", closeModal);

    var modalSave = document.getElementById("plan-modal-save");
    if (modalSave) modalSave.addEventListener("click", saveModal);

    var modalDelete = document.getElementById("plan-modal-delete-btn");
    if (modalDelete) modalDelete.addEventListener("click", deleteEditing);

    var confirmCancel = document.getElementById("plan-confirm-cancel");
    if (confirmCancel) confirmCancel.addEventListener("click", closeConfirm);

    var confirmDelete = document.getElementById("plan-confirm-delete");
    if (confirmDelete) confirmDelete.addEventListener("click", function () {
      var cb = _confirmCallback;
      closeConfirm();
      if (cb) cb();
    });

    // Close modals on overlay click
    var planModal = document.getElementById("plan-race-modal");
    if (planModal) {
      planModal.addEventListener("click", function (e) {
        if (e.target === planModal) closeModal();
      });
    }
    var confirmModal = document.getElementById("plan-confirm-modal");
    if (confirmModal) {
      confirmModal.addEventListener("click", function (e) {
        if (e.target === confirmModal) closeConfirm();
      });
    }
  }

  // ── Monthly review panel (issue #1059) ───────────────────────────────────

  function _signClass(val) {
    if (val == null) return "";
    return val > 0 ? "positive" : val < 0 ? "negative" : "";
  }

  function _fmtDelta(val, decimals, suffix) {
    if (val == null) return "—";
    var s = val > 0 ? "+" : "";
    return s + parseFloat(val).toFixed(decimals || 1) + (suffix || "");
  }

  function _supercompDotClass(state) {
    if (!state) return "";
    var s = String(state).toLowerCase();
    if (s === "peak") return "supercomp-peak";
    if (s === "building") return "supercomp-building";
    if (s === "recovering") return "supercomp-recovering";
    return "";
  }

  function renderMonthlyReview(data) {
    var panel = document.getElementById("plan-monthly-review");
    if (!panel) return;

    if (!data || !data.next_checkpoint) {
      panel.setAttribute("hidden", "");
      return;
    }

    // Checkpoint name
    var nameEl = document.getElementById("plan-month-checkpoint-name");
    if (nameEl) nameEl.textContent = data.next_checkpoint.name || "";

    // Chips: Endurance score, Speed score, Weight change, Fitness change, Form
    var chipsEl = document.getElementById("plan-month-chips");
    if (chipsEl) {
      var chips = [
        { val: data.endurance_score_change, label: "Endurance", decimals: 1, suffix: "" },
        { val: data.speed_score_change, label: "Speed", decimals: 1, suffix: "" },
        { val: data.weight_change_kg, label: "Weight", decimals: 1, suffix: " kg" },
        { val: data.fitness_ctl_change, label: "Fitness (CTL)", decimals: 1, suffix: "" },
        { val: data.form_recovered !== undefined ? (data.form_recovered ? 1 : -1) : null, label: "Form", special: "form_recovered", raw: data.form_recovered },
      ];
      var html = "";
      chips.forEach(function (c) {
        var display, cls;
        if (c.special === "form_recovered") {
          display = c.raw === true ? "Recovered" : c.raw === false ? "Fatigued" : "—";
          cls = c.raw === true ? "positive" : c.raw === false ? "negative" : "";
        } else {
          display = _fmtDelta(c.val, c.decimals, c.suffix);
          cls = _signClass(c.val);
        }
        html +=
          '<div class="plan-month-chip">' +
          '<span class="plan-month-chip-val ' + cls + '">' + esc(display) + '</span>' +
          '<span class="plan-month-chip-lbl">' + esc(c.label) + '</span>' +
          '</div>';
      });
      chipsEl.innerHTML = html;
    }

    // Supercompensation state
    var supercompEl = document.getElementById("plan-month-supercomp");
    var supercompLbl = document.getElementById("plan-month-supercomp-label");
    var supercompDot = supercompEl ? supercompEl.querySelector(".plan-month-supercomp-dot") : null;
    if (supercompLbl) supercompLbl.textContent = data.supercompensation_state || "—";
    if (supercompDot) {
      supercompDot.className = "plan-month-supercomp-dot " + _supercompDotClass(data.supercompensation_state);
    }

    // CTA
    var ctaEl = document.getElementById("plan-month-cta");
    if (ctaEl) ctaEl.textContent = data.call_to_action || "";

    panel.removeAttribute("hidden");
  }

  function loadMonthlyReview() {
    var panel = document.getElementById("plan-monthly-review");
    if (panel) panel.setAttribute("hidden", "");

    apiGet("/api/auth/me", function (me) {
      if (!me || !me.id) return;
      fetch("/api/athletes/" + me.id + "/summary/monthly", { credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) return null;
          return r.json();
        })
        .then(function (data) {
          renderMonthlyReview(data);
        })
        .catch(function () {
          // keep panel hidden on error
        });
    });
  }

  function wireMonthlyReviewLogLink() {
    var link = document.getElementById("plan-month-log-link");
    if (!link) return;
    link.addEventListener("click", function () {
      // Switch to the Log sub-tab
      var logBtn = document.querySelector('.training-sub-tab[data-tab="log"]');
      if (logBtn) logBtn.click();
    });
  }

  // ── Public init ───────────────────────────────────────────────────────────
  function init() {
    if (!_initialized) {
      _initialized = true;
      wireEvents();
      wireMonthlyReviewLogLink();
    }
    refresh();
    loadMonthlyReview();
  }

  window.TrainingPlan = { init: init };

})();
