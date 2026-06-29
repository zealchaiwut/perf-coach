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
  var _planId = null;

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

  // ── Plan ID ───────────────────────────────────────────────────────────────
  function _ensurePlanId(cb) {
    if (_planId) { cb(); return; }
    var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (uid) { _planId = uid; cb(); return; }
    fetch("/api/auth/me", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) return null; return r.json(); })
      .then(function (u) { if (u) _planId = u.id; cb(); })
      .catch(function () { cb(); });
  }

  function _planRaceUrl(raceId) {
    return "/plans/" + _planId + "/races" + (raceId ? "/" + raceId : "");
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
    var weeks = weeksUntil(r.date);
    var weeksHtml = weeks !== null && weeks > 0
      ? '<span class="plan-weeks-chip">⏱ ' + weeks + ' week' + (weeks === 1 ? "" : "s") + ' to go</span>'
      : "";

    var goalTime = r.goal_time_seconds ? fmtTime(r.goal_time_seconds) : null;
    var goalPaceSecPerKm = r.goal_time_seconds && r.distance
      ? r.goal_time_seconds / parseFloat(r.distance)
      : null;
    var goalPace = goalPaceSecPerKm ? fmtPace(goalPaceSecPerKm) : null;

    el.innerHTML =
      '<div class="plan-race-hd">' +
      '<div class="plan-race-hd-info">' +
      '<h2 class="plan-race-hd-name">' +
      esc(r.name) +
      '</h2>' +
      '<div class="plan-race-meta">' +
      '<div class="plan-race-meta-item"><span class="plan-meta-label">Date</span><span class="plan-meta-value">' + esc(formatDate(r.date)) + '</span></div>' +
      '<div class="plan-race-meta-item"><span class="plan-meta-label">Distance</span><span class="plan-meta-value">' + parseFloat(r.distance).toFixed(3).replace(/\.?0+$/, "") + ' km</span></div>' +
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

    if (_formCurveChart) {
      _formCurveChart.destroy();
      _formCurveChart = null;
    }

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

    if (_primaryRace && _primaryRace.date) {
      annotations.raceLine = {
        type: "line",
        xMin: _primaryRace.date,
        xMax: _primaryRace.date,
        borderColor: "rgba(21, 128, 61, 0.8)",
        borderWidth: 2,
        label: { content: "Race day", enabled: true, position: "start", backgroundColor: "rgba(21,128,61,0.8)", color: "#fff", font: { size: 10 } },
      };
    }

    _races.forEach(function (race) {
      if (race.type === "race" && race.id !== (_primaryRace && _primaryRace.id)) {
        annotations["brace_" + race.id] = {
          type: "line",
          xMin: race.date,
          xMax: race.date,
          borderColor: "rgba(3, 105, 161, 0.6)",
          borderWidth: 1,
          borderDash: [3, 3],
        };
      }
      if (race.type === "checkpoint") {
        annotations["cp_" + race.id] = {
          type: "line",
          xMin: race.date,
          xMax: race.date,
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
            data: allDates.map(function () { return 5; }),
            borderWidth: 0,
            backgroundColor: "rgba(34, 197, 94, 0.1)",
            fill: { target: { value: 100 } },
            tension: 0,
            pointRadius: 0,
          },
          {
            label: "Buried zone",
            data: allDates.map(function () { return -30; }),
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

    var sorted = _races.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });

    var races = sorted.filter(function (r) { return r.type !== "checkpoint"; });
    var checkpoints = sorted.filter(function (r) { return r.type === "checkpoint"; });

    if (sorted.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      Array.from(container.querySelectorAll(".plan-editor-section")).forEach(function (el) { el.remove(); });
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    Array.from(container.querySelectorAll(".plan-editor-section")).forEach(function (el) { el.remove(); });

    function buildSection(label, items) {
      var sec = document.createElement("div");
      sec.className = "plan-editor-section";

      var hdr = document.createElement("div");
      hdr.className = "plan-editor-section-hdr";
      hdr.textContent = label;
      sec.appendChild(hdr);

      if (items.length === 0) {
        var emp = document.createElement("p");
        emp.className = "plan-list-empty";
        emp.textContent = "No " + label.toLowerCase() + " added yet.";
        sec.appendChild(emp);
        return sec;
      }

      items.forEach(function (r) {
        var row = document.createElement("div");
        row.className = "plan-race-row";
        row.dataset.raceId = r.id;

        var info = document.createElement("div");
        info.className = "plan-race-row-info";

        var name = document.createElement("p");
        name.className = "plan-race-row-name";
        name.textContent = r.name || "(unnamed)";
        info.appendChild(name);

        var meta = document.createElement("div");
        meta.className = "plan-race-row-meta";
        meta.innerHTML =
          '<span>' + esc(formatDate(r.date)) + '</span>' +
          ' <span>' + parseFloat(r.distance || 0).toFixed(2) + ' km</span>' +
          (r.goal_time_seconds ? ' <span>' + esc(fmtTime(r.goal_time_seconds)) + '</span>' : '');
        info.appendChild(meta);
        row.appendChild(info);

        var actions = document.createElement("div");
        actions.className = "plan-race-row-actions";

        var editBtn = document.createElement("button");
        editBtn.type = "button";
        editBtn.className = "plan-row-action-btn";
        editBtn.textContent = "Edit";
        editBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          openModal(r, r.type || "race");
        });

        var delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "plan-row-action-btn plan-row-action-btn--delete";
        delBtn.textContent = "Delete";
        delBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          _deleteRow(r.id, r.name || "entry");
        });

        actions.appendChild(editBtn);
        actions.appendChild(delBtn);
        row.appendChild(actions);

        sec.appendChild(row);
      });

      return sec;
    }

    container.appendChild(buildSection("Races", races));
    container.appendChild(buildSection("Checkpoints", checkpoints));
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
    if (!_planId) { _races = []; _primaryRace = null; if (done) done(); return; }
    apiGet(_planRaceUrl(), function (data) {
      _races = Array.isArray(data) ? data : [];
      _primaryRace = _races.find(function (r) { return r.type === "race"; }) || null;
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
    _ensurePlanId(function () {
      loadRaces(function () {
        loadReadiness(function () {
          renderAll();
        });
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
    var typeIn = document.getElementById("plan-modal-type");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var deleteBtn = document.getElementById("plan-modal-delete-btn");
    var errEl = document.getElementById("plan-modal-error");

    if (!modal) return;

    var isCheckpoint = _editingRaceType === "checkpoint";

    if (title) title.textContent = race
      ? (isCheckpoint ? "Edit Checkpoint" : "Edit Race")
      : (isCheckpoint ? "Add Checkpoint" : "Add Race");
    if (deleteBtn) deleteBtn.style.display = race ? "" : "none";
    if (errEl) errEl.textContent = "";

    if (race) {
      if (nameIn) nameIn.value = race.name || "";
      if (dateIn) dateIn.value = race.date || "";
      if (distIn) distIn.value = race.distance || "";
      if (typeIn) typeIn.value = race.type || "race";
      if (goalIn) goalIn.value = goalTimeToStr(race.goal_time_seconds);
    } else {
      if (nameIn) nameIn.value = "";
      if (dateIn) dateIn.value = "";
      if (distIn) distIn.value = "";
      if (typeIn) typeIn.value = isCheckpoint ? "checkpoint" : "race";
      if (goalIn) goalIn.value = "";
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
    var typeIn = document.getElementById("plan-modal-type");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var errEl = document.getElementById("plan-modal-error");

    var name = nameIn ? nameIn.value.trim() : "";
    var date = dateIn ? dateIn.value : "";
    var dist = distIn ? parseFloat(distIn.value) : NaN;
    var type = typeIn ? typeIn.value : _editingRaceType;
    var goalSec = goalIn ? parseGoalTime(goalIn.value) : null;

    if (!name) { if (errEl) errEl.textContent = "Name is required."; return; }
    if (!date) { if (errEl) errEl.textContent = "Date is required."; return; }
    if (isNaN(dist) || dist <= 0) { if (errEl) errEl.textContent = "Distance must be a positive number."; return; }

    var body = {
      name: name,
      date: date,
      distance: dist,
      type: type,
    };
    if (goalSec !== null) body.goal_time_seconds = goalSec;

    if (errEl) errEl.textContent = "";

    if (_editingRaceId) {
      apiPatch(_planRaceUrl(_editingRaceId), body, function (res) {
        if (!res.ok) {
          if (errEl) errEl.textContent = (res.data && res.data.detail) ? JSON.stringify(res.data.detail) : "Save failed.";
          return;
        }
        closeModal();
        refresh();
      });
    } else {
      apiPost(_planRaceUrl(), body, function (res) {
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
    var label = race ? (race.type === "checkpoint" ? "checkpoint" : "race") : "entry";
    closeModal();
    showConfirm(
      "Delete this " + label + "?",
      "This action cannot be undone.",
      function () {
        apiDelete(_planRaceUrl(rid), function (res) {
          if (res.ok) refresh();
        });
      }
    );
  }

  function _deleteRow(raceId, raceName) {
    var race = _races.find(function (r) { return r.id === raceId; });
    var label = race ? (race.type === "checkpoint" ? "checkpoint" : "race") : "entry";
    showConfirm(
      "Delete this " + label + "?",
      "This action cannot be undone.",
      function () {
        apiDelete(_planRaceUrl(raceId), function (res) {
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

  // ── Public init ───────────────────────────────────────────────────────────
  function init() {
    if (!_initialized) {
      _initialized = true;
      wireEvents();
    }
    refresh();
  }

  window.TrainingPlan = { init: init };

})();
