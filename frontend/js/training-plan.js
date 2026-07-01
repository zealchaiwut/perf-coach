(function () {
  "use strict";

  // ── State ─────────────────────────────────────────────────────────────────
  var _initialized = false;
  var _races = [];
  var _primaryRace = null;
  var _readiness = null;
  var _projection = null;
  var _editingRaceId = null;
  var _editingRaceType = "race";
  var _modalPriority = "A";
  var _confirmCallback = null;
  var _planId = null;
  // Per-race readiness cache: raceId -> readiness response (or null if none).
  var _raceReadiness = {};
  // Completed-race (Pick-from-history) state. When a past run is selected while
  // ADDING a race, we stash its finish time here and POST status:"done".
  var _pickedActualSeconds = null;
  var _historyLoaded = false;
  var _historyRuns = [];
  // Goal input mode: "time" (HH:MM:SS) or "pace" (M:SS /km, derived via distance).
  var _goalMode = "time";
  // Checkpoint measure mode: "distance" or "duration" (duration = stubbed).
  var _checkpointMeasure = "distance";

  var NS = "http://www.w3.org/2000/svg";

  // ── Helpers ───────────────────────────────────────────────────────────────
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function todayISO() {
    var d = new Date();
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
    );
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso + "T00:00:00");
    var months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
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
    var s = Math.round(totalSec % 60);
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

  // SVG builders
  function E(t, a) {
    var e = document.createElementNS(NS, t);
    for (var k in a) e.setAttribute(k, a[k]);
    return e;
  }
  function Path(pts, close) {
    return (
      pts
        .map(function (p, i) {
          return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1);
        })
        .join(" ") + (close ? "Z" : "")
    );
  }
  function clearSvg(svg) {
    while (svg && svg.firstChild) svg.removeChild(svg.firstChild);
  }

  // ── Plan ID ───────────────────────────────────────────────────────────────
  function _ensurePlanId(cb) {
    if (_planId) {
      cb();
      return;
    }
    var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (uid) {
      _planId = uid;
      cb();
      return;
    }
    fetch("/api/auth/me", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return null;
        return r.json();
      })
      .then(function (u) {
        if (u) _planId = u.id;
        cb();
      })
      .catch(function () {
        cb();
      });
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
      .catch(function (e) {
        console.warn("[plan] GET", url, e);
        cb(null);
      });
  }

  function apiPost(url, body, cb) {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, status: r.status, data: d };
        });
      })
      .then(cb)
      .catch(function (e) {
        cb({ ok: false, status: 0, data: { detail: e.message } });
      });
  }

  function apiPatch(url, body, cb) {
    fetch(url, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, status: r.status, data: d };
        });
      })
      .then(cb)
      .catch(function (e) {
        cb({ ok: false, status: 0, data: { detail: e.message } });
      });
  }

  function apiDelete(url, cb) {
    fetch(url, { method: "DELETE", credentials: "same-origin" })
      .then(function (r) {
        cb({ ok: r.ok, status: r.status });
      })
      .catch(function () {
        cb({ ok: false, status: 0 });
      });
  }

  // ── 1. A-race header ──────────────────────────────────────────────────────
  function renderRaceHeader() {
    var el = document.getElementById("plan-race-header-content");
    if (!el) return;

    if (!_primaryRace) {
      el.innerHTML =
        '<div class="pm-no-race">' +
        "<span>No A-priority race set. Add your main race to start planning.</span>" +
        '<button id="plan-header-add-btn" class="pm-ckbtn" type="button">+ Add Race</button>' +
        "</div>";
      var addBtn = document.getElementById("plan-header-add-btn");
      if (addBtn)
        addBtn.addEventListener("click", function () {
          openModal(null, "race");
        });
      return;
    }

    var r = _primaryRace;
    var distKm = parseFloat(r.distance || 0);
    var goalTime = r.goal_time_seconds ? fmtTime(r.goal_time_seconds) : "—";
    var goalPaceSec =
      r.goal_time_seconds && distKm ? r.goal_time_seconds / distKm : null;
    var goalPace = goalPaceSec ? fmtPace(goalPaceSec) : "";

    el.innerHTML =
      '<div class="pm-hdrbar">' +
      '<span class="pm-hdrlet">A</span>' +
      '<div class="pm-hdrid">' +
      '<div class="pm-hdrname">' + esc(r.name || "Unnamed") + "</div>" +
      '<div class="pm-hdrmeta">' +
      esc(formatDate(r.date)) + " · " + distKm.toFixed(2) + " km · A-priority" +
      "</div>" +
      "</div>" +
      '<div class="pm-hdrdiv"></div>' +
      '<div class="pm-hdrgoalbox">' +
      '<div class="pm-glab">Goal</div>' +
      '<div class="pm-gval">' + esc(goalTime) + "</div>" +
      (goalPace
        ? '<div class="pm-gsub">' + esc(goalPace) + " · target pace</div>"
        : "") +
      "</div>" +
      '<button id="plan-header-add-btn" class="pm-ckbtn" type="button">Change race</button>' +
      "</div>";

    var chBtn = document.getElementById("plan-header-add-btn");
    if (chBtn)
      chBtn.addEventListener("click", function () {
        openModal(_primaryRace, "race");
      });
  }

  // ── 2. Calibration status ─────────────────────────────────────────────────
  var _SUFF_BADGE = { Sufficient: "good", Low: "low", Insufficient: "low" };
  var _CONF_BADGE = { High: "good", Medium: "med", Low: "low" };

  function renderCalibration(data) {
    var dateEl = document.getElementById("plan-calib-date");
    var suffEl = document.getElementById("plan-calib-sufficiency");
    var confEl = document.getElementById("plan-calib-confidence");

    if (dateEl) {
      if (data && data.calibrated && data.last_calibration_date) {
        dateEl.textContent = formatDate(data.last_calibration_date);
      } else {
        dateEl.innerHTML =
          '<span class="pm-italic">Not yet calibrated</span>';
      }
    }
    if (suffEl) {
      if (data && data.data_sufficiency) {
        suffEl.innerHTML =
          '<span class="pm-badge ' +
          (_SUFF_BADGE[data.data_sufficiency] || "med") +
          '">' + esc(data.data_sufficiency) + "</span>";
      } else {
        suffEl.innerHTML = '<span class="pm-italic">—</span>';
      }
    }
    if (confEl) {
      if (data && data.band_confidence) {
        confEl.innerHTML =
          '<span class="pm-badge ' +
          (_CONF_BADGE[data.band_confidence] || "med") +
          '">' + esc(data.band_confidence) + "</span>";
      } else {
        confEl.innerHTML = '<span class="pm-italic">—</span>';
      }
    }
  }

  function loadCalibration() {
    apiGet("/api/calibration/status", renderCalibration);
  }

  // ── 3. Time-curve SVG (projected finish time) ─────────────────────────────
  // Ported from mock #timecurve. Piecewise x compresses the pre-race lead-in
  // and expands the race window; y-range tightened around the projected times.
  function renderTimeCurve() {
    var svg = document.getElementById("plan-timecurve");
    var emptyEl = document.getElementById("plan-time-curve-empty");
    var loadingEl = document.getElementById("plan-time-curve-loading");
    var projNow = document.getElementById("plan-projected-now");
    if (!svg) return;
    if (loadingEl) loadingEl.style.display = "none";
    clearSvg(svg);

    function _hideProjNow() {
      if (projNow) projNow.style.display = "none";
    }

    var tc = _readiness && _readiness.time_curve;
    var history = (tc && tc.history) || [];
    var projection = (tc && tc.projection) || [];
    var goalSec = tc && tc.goal_finish_seconds != null
      ? tc.goal_finish_seconds
      : (_primaryRace && _primaryRace.goal_time_seconds) || null;

    if (!_primaryRace || (history.length === 0 && projection.length === 0)) {
      svg.style.display = "none";
      if (emptyEl) emptyEl.style.display = "";
      _hideProjNow();
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";
    svg.style.display = "";

    // Current projected finish readout (first projection sample, else the last
    // history sample). Gives the user a directly readable prediction.
    var estInfo = _currentEstimate(_readiness);
    var valEl = document.getElementById("plan-projected-now-val");
    var metaEl = document.getElementById("plan-projected-now-meta");
    if (estInfo && projNow) {
      projNow.style.display = "";
      if (valEl) valEl.textContent = fmtTime(estInfo.est);
      if (metaEl) {
        var parts = [];
        var distKm = _primaryRace ? parseFloat(_primaryRace.distance || 0) : 0;
        if (distKm) parts.push(fmtPace(estInfo.est / distKm));
        if (estInfo.band != null)
          parts.push("±" + Math.max(1, Math.round(estInfo.band / 60)) + " min");
        if (goalSec != null) parts.push("goal " + fmtTime(goalSec));
        metaEl.textContent = parts.join(" · ");
      }
    } else {
      _hideProjNow();
    }

    var W = 1140, H = 200, p = { l: 54, r: 30, t: 14, b: 26 };

    // ── Tight y-domain ────────────────────────────────────────────────────────
    // Early low-fitness history estimates can be wildly large (e.g. 7h for a
    // half), which blows up an all-samples auto-scale and makes the current
    // projection unreadable. Anchor the domain on the values that matter — the
    // projection band, the goal, and only the RECENT tail of history — then
    // clamp outliers to that window instead of letting them stretch the axis.
    var coreSamples = [];
    projection.forEach(function (e) {
      if (e.estimated_finish_seconds != null) coreSamples.push(e.estimated_finish_seconds);
      if (e.upper_seconds != null) coreSamples.push(e.upper_seconds);
      if (e.lower_seconds != null) coreSamples.push(e.lower_seconds);
    });
    if (goalSec != null) coreSamples.push(goalSec);
    // Recent history tail (last ~21 points) to show the approach without the
    // noisy early ramp.
    var recentHist = history.slice(-21);
    recentHist.forEach(function (e) {
      if (e.estimated_finish_seconds != null) coreSamples.push(e.estimated_finish_seconds);
    });
    // Fallback: if the projection was empty, use whatever history we have.
    if (coreSamples.length === 0) {
      history.forEach(function (e) {
        if (e.estimated_finish_seconds != null) coreSamples.push(e.estimated_finish_seconds);
      });
    }
    if (coreSamples.length === 0) {
      svg.style.display = "none";
      if (emptyEl) emptyEl.style.display = "";
      _hideProjNow();
      return;
    }
    var vmin = Math.min.apply(null, coreSamples);
    var vmax = Math.max.apply(null, coreSamples);
    // Guarantee a sensible minimum span (5 min) so a nearly-flat series still
    // reads, and pad ~8% on each side.
    var span = Math.max(vmax - vmin, 300);
    var padY = span * 0.08;
    vmin -= padY;
    vmax += padY;
    function y(v) {
      // Clamp so outlier history points render at the axis edge instead of
      // rescaling the whole chart.
      var cv = Math.max(vmin, Math.min(vmax, v));
      return p.t + (1 - (cv - vmin) / (vmax - vmin || 1)) * (H - p.t - p.b);
    }

    // Piecewise x: history 0..nowT, projection nowT..1 (expanded).
    var nHist = history.length;
    var nProj = projection.length;
    var total = nHist + nProj;
    var nowT = total > 0 ? Math.max(0.08, Math.min(0.5, nHist / total)) : 0.15;
    function xHist(i) {
      return p.l + (nHist > 1 ? i / (nHist - 1) : 0) * (nowT) * (W - p.l - p.r);
    }
    function xProj(i) {
      var u = nProj > 1 ? i / (nProj - 1) : 1;
      return p.l + (nowT + u * (1 - nowT)) * (W - p.l - p.r);
    }

    // gridlines + labels
    var ticks = [vmin + (vmax - vmin) * 0.2, (vmin + vmax) / 2, vmax - (vmax - vmin) * 0.2];
    ticks.forEach(function (v) {
      svg.appendChild(E("line", { x1: p.l, x2: W - p.r, y1: y(v), y2: y(v), stroke: "#eef1f7" }));
      var lab = E("text", {
        x: p.l - 8, y: y(v) + 3, "font-size": 10,
        "font-family": "JetBrains Mono", fill: "#9aa3b8", "text-anchor": "end",
      });
      lab.textContent = fmtTime(Math.round(v));
      svg.appendChild(lab);
    });

    // projection shaded window
    var nowX = p.l + nowT * (W - p.l - p.r);
    svg.appendChild(E("rect", {
      x: nowX, y: p.t, width: W - p.r - nowX, height: H - p.t - p.b,
      fill: "#f4f7ff", "fill-opacity": 0.7,
    }));

    // confidence band
    var top = [], bot = [];
    projection.forEach(function (e, i) {
      if (e.upper_seconds != null) top.push([xProj(i), y(e.upper_seconds)]);
      if (e.lower_seconds != null) bot.push([xProj(i), y(e.lower_seconds)]);
    });
    if (top.length && bot.length) {
      svg.appendChild(E("path", {
        d: Path(top.concat(bot.reverse()), true),
        fill: "#4f6ef7", "fill-opacity": 0.12,
      }));
    }

    // history line
    var histPts = history
      .filter(function (e) { return e.estimated_finish_seconds != null; })
      .map(function (e, i) { return [xHist(i), y(e.estimated_finish_seconds)]; });
    if (histPts.length)
      svg.appendChild(E("path", {
        d: Path(histPts), fill: "none", stroke: "#4f6ef7", "stroke-width": 2.4,
      }));

    // projection center (dashed)
    var projPts = projection
      .map(function (e, i) {
        return e.estimated_finish_seconds != null
          ? [xProj(i), y(e.estimated_finish_seconds)]
          : null;
      })
      .filter(Boolean);
    if (projPts.length)
      svg.appendChild(E("path", {
        d: Path(projPts), fill: "none", stroke: "#4f6ef7",
        "stroke-width": 2.4, "stroke-dasharray": "5 4",
      }));

    // goal line
    if (goalSec != null) {
      svg.appendChild(E("line", {
        x1: p.l, x2: W - p.r, y1: y(goalSec), y2: y(goalSec),
        stroke: "#16a34a", "stroke-width": 1.5, "stroke-dasharray": "7 5",
      }));
      var gl = E("text", {
        x: p.l + 4, y: y(goalSec) - 5, "font-size": 9,
        "font-family": "Inter Tight", fill: "#16a34a", "font-weight": 700,
      });
      gl.textContent = "A goal " + fmtTime(goalSec);
      svg.appendChild(gl);
    }

    // NOW line
    svg.appendChild(E("line", {
      x1: nowX, x2: nowX, y1: p.t, y2: H - p.b,
      stroke: "#cbd5e1", "stroke-dasharray": "3 3",
    }));
    var nt = E("text", {
      x: nowX + 3, y: p.t + 8, "font-size": 8, "font-family": "JetBrains Mono",
      fill: "#9aa3b8", "text-anchor": "start", "font-weight": 700,
    });
    nt.textContent = "NOW";
    svg.appendChild(nt);

    // race markers along the projection window
    var markers = (_projection && _projection.race_markers) || [];
    var COL = { A: "#1b2340", B: "#d97706", C: "#6b7280" };
    var todayStr = todayISO();
    markers.forEach(function (m) {
      if (m.date < todayStr) return;
      var w = weeksUntil(m.date);
      var maxW = weeksUntil(_primaryRace && _primaryRace.date) || 1;
      var u = maxW > 0 ? 1 - Math.min(1, w / maxW) : 1;
      var mx = p.l + (nowT + u * (1 - nowT)) * (W - p.l - p.r);
      var c = COL[m.priority] || "#6b7280";
      svg.appendChild(E("line", {
        x1: mx, x2: mx, y1: p.t, y2: H - p.b, stroke: c,
        "stroke-width": m.priority === "A" ? 1.5 : 1,
        "stroke-dasharray": m.priority === "A" ? "none" : "2 3",
        "stroke-opacity": 0.6,
      }));
      var t = E("text", {
        x: mx, y: H - 7, "font-size": 9, "font-family": "JetBrains Mono",
        fill: "#9aa3b8", "text-anchor": "middle", "font-weight": 700,
      });
      t.textContent = m.priority || "•";
      svg.appendChild(t);
    });
  }

  // ── 3b. Race/checkpoint cards ─────────────────────────────────────────────
  var _LET_BG = { A: "#1b2340", B: "#3b4ba8", C: "#6b7280" };

  // Extract the current projected finish (seconds), band (seconds), and status
  // from a readiness response's time_curve + on_track blocks. Returns null when
  // no usable estimate is present.
  function _currentEstimate(rd) {
    if (!rd || !rd.time_curve) return null;
    var tc = rd.time_curve;
    var proj = tc.projection || [];
    var hist = tc.history || [];
    var est = null,
      band = null;
    if (proj.length > 0) {
      est = proj[0].estimated_finish_seconds;
      band = proj[0].confidence_band_seconds != null
        ? proj[0].confidence_band_seconds
        : null;
    } else if (hist.length > 0) {
      est = hist[hist.length - 1].estimated_finish_seconds;
    }
    if (est == null) return null;
    var goalSec = tc.goal_finish_seconds != null ? tc.goal_finish_seconds : null;
    var status = rd.on_track && rd.on_track.status_summary;
    return { est: est, band: band, goalSec: goalSec, status: status };
  }

  // Map a readiness on_track result to a status pill (label + ok/watch class).
  function _statusPill(estInfo) {
    if (!estInfo) return "";
    var status = estInfo.status;
    var cls, label;
    if (status === "on track" || status === "ahead") {
      cls = "ok";
      label = status === "ahead" ? "ahead" : "on track";
    } else if (status === "behind") {
      cls = "watch";
      // If we know goal + est, express the gap in minutes over.
      if (estInfo.goalSec != null && estInfo.est != null && estInfo.est > estInfo.goalSec) {
        var overMin = Math.round((estInfo.est - estInfo.goalSec) / 60);
        label = "~" + overMin + " min over";
      } else {
        label = "behind";
      }
    } else {
      return "";
    }
    return '<span class="pm-stat ' + cls + '">' + esc(label) + "</span>";
  }

  function renderRaceCards() {
    var container = document.getElementById("plan-races");
    var loadingEl = document.getElementById("plan-races-loading");
    var emptyEl = document.getElementById("plan-races-empty");
    if (!container) return;
    if (loadingEl) loadingEl.style.display = "none";

    // remove previously rendered cards
    Array.from(container.querySelectorAll(".pm-rc")).forEach(function (el) {
      el.remove();
    });

    var sorted = _races.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });

    if (sorted.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    var todayStr = todayISO();
    var primaryId = _primaryRace && _primaryRace.id;

    sorted.forEach(function (r) {
      var isCheckpoint = r.type === "checkpoint";
      // Real priority comes from the race row. Checkpoints have no priority and
      // render under the neutral "C" treatment; real races use r.priority.
      var priority = isCheckpoint ? "C" : r.priority || "A";
      var isTarget = r.id === primaryId;
      var upcoming = r.date >= todayStr;
      var distKm = parseFloat(r.distance || 0);
      var goalSec = r.goal_time_seconds || null;
      var goalPace = goalSec && distKm ? fmtPace(goalSec / distKm) : "";

      var card = document.createElement("div");
      card.className = "pm-rc" + (isTarget ? " target" : "");
      card.setAttribute("data-race-id", r.id);

      var recalHtml =
        _projection &&
        _projection.b_race_recalibration_date === r.date &&
        priority === "B"
          ? '<span class="pm-recal">↻ recalibrates here</span>'
          : "";
      var rightTag = isTarget
        ? '<span class="pm-tgt">TARGET</span>'
        : recalHtml;

      // A completed (done) race carries a real result. Show a DONE pill and the
      // actual finish time instead of the projected Estimated column.
      var isDone =
        r.status === "done" && r.actual_time_seconds != null;
      var statusPillHead = isDone
        ? '<span class="pm-upc pm-done">DONE</span>'
        : '<span class="pm-upc' + (upcoming ? "" : " pm-past") + '">' +
          (upcoming ? "UPCOMING" : "PAST") + "</span>";

      var head =
        '<div class="pm-rchd">' +
        '<span class="pm-rclet" style="background:' +
        (_LET_BG[priority] || "#6b7280") + '">' + esc(priority) + "</span>" +
        '<span class="pm-rcname">' + esc(r.name || "Unnamed") + "</span>" +
        '<span class="pm-typetag">' +
        (isCheckpoint ? "CHECKPOINT" : "RACE") + "</span>" +
        '<span class="pm-rcmeta">' +
        esc(formatDate(r.date)) + " · " + distKm.toFixed(2) + " km</span>" +
        statusPillHead +
        rightTag +
        '<span class="pm-rcactions">' +
        '<button class="pm-rcact" data-act="edit" type="button">Edit</button>' +
        '<button class="pm-rcact" data-act="del" type="button">✕</button>' +
        "</span>" +
        "</div>";

      // Second column: Actual (for done races) or Estimated (from readiness).
      var secondCol = "";
      if (isDone) {
        var actualSec = r.actual_time_seconds;
        var actualPace = distKm ? fmtPace(actualSec / distKm) : "";
        secondCol =
          '<div class="pm-col est">' +
          '<div class="pm-coll">Actual ' +
          '<span class="pm-stat ok">completed</span></div>' +
          '<div class="pm-colt">' + esc(fmtTime(actualSec)) + "</div>" +
          '<div class="pm-colp">' + esc(actualPace) + "</div></div>";
      } else {
        var estInfo = _currentEstimate(_raceReadiness[r.id]);
        if (estInfo) {
          var estPace = distKm ? fmtPace(estInfo.est / distKm) : "";
          var bandTxt =
            estInfo.band != null
              ? " · ±" + Math.max(1, Math.round(estInfo.band / 60)) + " min"
              : "";
          secondCol =
            '<div class="pm-col est">' +
            '<div class="pm-coll">Estimated ' + _statusPill(estInfo) + "</div>" +
            '<div class="pm-colt">' + esc(fmtTime(estInfo.est)) + "</div>" +
            '<div class="pm-colp">' + esc(estPace) + esc(bandTxt) + "</div></div>";
        }
      }

      var grid =
        '<div class="pm-rcgrid">' +
        '<div class="pm-col"><div class="pm-coll">Goal</div>' +
        '<div class="pm-colt">' + esc(goalSec ? fmtTime(goalSec) : "—") + "</div>" +
        '<div class="pm-colp">' + esc(goalPace || "—") + "</div></div>" +
        secondCol +
        "</div>";

      // Footer: End/Spd score tags (athlete-level scores from /api/projection —
      // shown on the primary race only, since scores are not per-race). No
      // half-equiv line: the readiness API does not expose a half-equivalent
      // time, so we do not fabricate one.
      var foot = "";
      if (
        isTarget &&
        _projection &&
        (typeof _projection.endurance_score === "number" ||
          typeof _projection.speed_score === "number")
      ) {
        var tags = "";
        if (typeof _projection.endurance_score === "number")
          tags +=
            '<span class="pm-sc e">End ' +
            Math.round(_projection.endurance_score) + "</span>";
        if (typeof _projection.speed_score === "number")
          tags +=
            '<span class="pm-sc s">Spd ' +
            Math.round(_projection.speed_score) + "</span>";
        if (tags)
          foot =
            '<div class="pm-rcfoot"><div class="pm-scoretags">' +
            tags +
            "</div></div>";
      }

      card.innerHTML = head + grid + foot;

      card.querySelector('[data-act="edit"]').addEventListener("click", function () {
        openModal(r, r.type || "race");
      });
      card.querySelector('[data-act="del"]').addEventListener("click", function () {
        _deleteRow(r.id, r.name || "entry");
      });

      container.appendChild(card);
    });
  }

  // ── 4. Form curve SVG (TSB) ───────────────────────────────────────────────
  // Ported from mock #pacecurve: recent-emphasis x (pow 1.55), fresh/overreach
  // zones. Fed the real daily TSB series from form_curve.
  function renderFormCurve() {
    var svg = document.getElementById("plan-pacecurve");
    var emptyEl = document.getElementById("plan-curve-empty");
    var bbEl = document.getElementById("plan-building-baseline");
    if (!svg) return;
    clearSvg(svg);

    if (_readiness && _readiness.building_baseline) {
      svg.style.display = "none";
      if (emptyEl) emptyEl.style.display = "none";
      if (bbEl) bbEl.style.display = "";
      return;
    }
    if (bbEl) bbEl.style.display = "none";

    var formCurve =
      (_readiness && _readiness.form_curve) ||
      (_projection && _projection.form_curve) ||
      [];

    if (formCurve.length < 2) {
      svg.style.display = "none";
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";
    svg.style.display = "";

    var W = 1140, H = 300, p = { l: 44, r: 20, t: 12, b: 28 };
    var vmin = -25, vmax = 10;
    // widen range if data exceeds defaults
    formCurve.forEach(function (pt) {
      if (pt.form < vmin) vmin = Math.floor(pt.form);
      if (pt.form > vmax) vmax = Math.ceil(pt.form);
    });
    function y(v) {
      return p.t + (1 - (v - vmin) / (vmax - vmin)) * (H - p.t - p.b);
    }
    function xf(u) {
      return Math.pow(u, 1.55);
    }
    function x(i, n) {
      return p.l + xf(n > 1 ? i / (n - 1) : 0) * (W - p.l - p.r);
    }

    // fresh (green) and overreach (red) zones
    svg.appendChild(E("rect", {
      x: p.l, y: y(vmax), width: W - p.l - p.r, height: y(5) - y(vmax),
      fill: "#dcfce7", "fill-opacity": 0.55,
    }));
    svg.appendChild(E("rect", {
      x: p.l, y: y(-18), width: W - p.l - p.r, height: y(vmin) - y(-18),
      fill: "#fee2e2", "fill-opacity": 0.55,
    }));

    [vmax, 0, -10, vmin].forEach(function (v) {
      svg.appendChild(E("line", {
        x1: p.l, x2: W - p.r, y1: y(v), y2: y(v), stroke: "#eef1f7",
      }));
      var lab = E("text", {
        x: p.l - 8, y: y(v) + 3, "font-size": 10, "font-family": "JetBrains Mono",
        fill: "#9aa3b8", "text-anchor": "end",
      });
      lab.textContent = Math.round(v);
      svg.appendChild(lab);
    });

    var N = formCurve.length;
    var pts = formCurve.map(function (pt, i) {
      return [x(i, N), y(pt.form)];
    });
    svg.appendChild(E("path", {
      d: Path(pts), fill: "none", stroke: "#4f6ef7", "stroke-width": 1.8,
      "stroke-linejoin": "round",
    }));

    // date ticks: first, ~mid, last
    var idxs = [0, Math.floor(N * 0.6), N - 1];
    idxs.forEach(function (i, k) {
      var xx = x(i, N);
      var t = E("text", {
        x: xx, y: H - 8, "font-size": 10, "font-family": "JetBrains Mono",
        fill: "#9aa3b8",
        "text-anchor": k === 0 ? "start" : k === idxs.length - 1 ? "end" : "middle",
      });
      var d = new Date(formCurve[i].date + "T00:00:00");
      var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      t.textContent = months[d.getMonth()] + " " + d.getDate();
      svg.appendChild(t);
    });
  }

  // ── 5. Schedule preview bars ──────────────────────────────────────────────
  function _computeScheduleSeries(rampRate, taperWindow, weeks) {
    weeks = weeks || 20;
    var BASE_TSS = 55;
    var PLATEAU = 100;
    var taper = Math.max(0, Math.min(Math.floor(taperWindow), weeks - 1));
    var arr = [];
    for (var w = 1; w <= weeks; w++) {
      var tss;
      if (w <= weeks - taper) {
        tss = Math.min(PLATEAU, BASE_TSS + rampRate * (w - 1));
      } else {
        var into = w - (weeks - taper);
        tss = PLATEAU * (into === 1 ? 0.62 : 0.42);
      }
      arr.push(tss);
    }
    return arr;
  }

  function renderSchedulePreview() {
    var host = document.getElementById("plan-sched");
    var labs = document.getElementById("plan-wklabels");
    if (!host) return;
    host.innerHTML = "";
    if (labs) labs.innerHTML = "";

    var rampIn = document.getElementById("plan-ramp-rate-input");
    var taperIn = document.getElementById("plan-taper-window-input");
    var rampRate = rampIn ? Math.max(0, parseFloat(rampIn.value) || 0) : 0;
    var taperWindow = taperIn ? Math.max(0, parseFloat(taperIn.value) || 0) : 0;

    // Prefer planned_load from the plan projection when available.
    var weeks = 20;
    var series;
    var planned = _projection && _projection.planned_load;
    if (Array.isArray(planned) && planned.length > 0) {
      // aggregate daily planned load into weeks
      var byWeek = [];
      for (var i = 0; i < planned.length; i += 7) {
        var chunk = planned.slice(i, i + 7);
        var sum = chunk.reduce(function (a, b) { return a + (b || 0); }, 0);
        byWeek.push(sum);
      }
      series = byWeek.length ? byWeek : _computeScheduleSeries(rampRate, taperWindow, weeks);
    } else {
      series = _computeScheduleSeries(rampRate, taperWindow, weeks);
    }

    var taper = Math.max(0, Math.min(Math.floor(taperWindow), series.length));
    var max = Math.max.apply(null, series.concat([1]));

    series.forEach(function (tss, i) {
      var bar = document.createElement("div");
      bar.className = "pm-bar" + (i >= series.length - taper ? " taper" : "");
      bar.style.height = (tss / max) * 100 + "%";
      bar.title = "Wk " + (i + 1) + " · " + Math.round(tss) + " TSS";
      host.appendChild(bar);
      if (labs) {
        var s = document.createElement("span");
        s.textContent = (i + 1) % 2 === 1 ? "Wk " + (i + 1) : "";
        labs.appendChild(s);
      }
    });
  }

  // ── 6. Specificity bars ───────────────────────────────────────────────────
  function renderSpecBars() {
    var host = document.getElementById("plan-spec-bars");
    var emptyEl = document.getElementById("plan-spec-empty");
    if (!host) return;

    var sp = _readiness && _readiness.specificity_progress;
    if (!sp || sp.reason) {
      host.innerHTML = "";
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    var rows = [];
    function pct(cur, tgt) {
      return tgt > 0 ? Math.min(100, Math.round((cur / tgt) * 100)) : 0;
    }
    if (sp.volume_at_pace)
      rows.push(["Goal-pace volume", pct(sp.volume_at_pace.current, sp.volume_at_pace.target)]);
    if (sp.longest_pace_effort)
      rows.push(["Longest-at-pace", pct(sp.longest_pace_effort.current, sp.longest_pace_effort.target)]);
    if (sp.longest_run_by_distance)
      rows.push(["Longest run (distance)", pct(sp.longest_run_by_distance.current, sp.longest_run_by_distance.target)]);
    if (sp.longest_run_by_duration)
      rows.push(["Longest run (duration)", pct(sp.longest_run_by_duration.current, sp.longest_run_by_duration.target)]);

    if (rows.length === 0) {
      host.innerHTML = "";
      if (emptyEl) emptyEl.style.display = "";
      return;
    }

    host.innerHTML = rows
      .map(function (r) {
        return (
          '<div class="pm-specrow">' +
          '<div class="pm-specname">' + esc(r[0]) + "</div>" +
          '<div class="pm-spectrack"><div class="pm-specfill" style="width:' +
          r[1] + '%"></div></div>' +
          '<div class="pm-specpct">' + r[1] + "%</div>" +
          "</div>"
        );
      })
      .join("");
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadRaces(done) {
    if (!_planId) {
      _races = [];
      _primaryRace = null;
      if (done) done();
      return;
    }
    apiGet(_planRaceUrl(), function (data) {
      _races = Array.isArray(data) ? data : [];
      _primaryRace =
        _races.find(function (r) {
          return r.type === "race" && r.priority === "A";
        }) ||
        _races.find(function (r) {
          return r.type === "race";
        }) ||
        null;
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
      // Cache under the race id so renderRaceCards can surface the Estimated
      // column for the primary race.
      _raceReadiness[_primaryRace.id] = data;
      if (done) done();
    });
  }

  function loadProjection(done) {
    apiGet("/api/projection", function (data) {
      _projection = data;
      if (done) done();
    });
  }

  // ── Plan settings ─────────────────────────────────────────────────────────
  function _validateSettingsInputs() {
    var rampIn = document.getElementById("plan-ramp-rate-input");
    var taperIn = document.getElementById("plan-taper-window-input");
    var rampErr = document.getElementById("plan-ramp-rate-error");
    var taperErr = document.getElementById("plan-taper-window-error");
    var valid = true;

    if (rampErr) rampErr.textContent = "";
    if (taperErr) taperErr.textContent = "";
    if (rampIn) rampIn.classList.remove("is-invalid");
    if (taperIn) taperIn.classList.remove("is-invalid");

    var rampVal = rampIn ? rampIn.value.trim() : "";
    var taperVal = taperIn ? taperIn.value.trim() : "";

    if (rampVal === "" || isNaN(Number(rampVal)) || Number(rampVal) < 0) {
      if (rampErr) rampErr.textContent = "Enter a number ≥ 0.";
      if (rampIn) rampIn.classList.add("is-invalid");
      valid = false;
    }
    if (taperVal === "" || isNaN(Number(taperVal)) || Number(taperVal) < 0) {
      if (taperErr) taperErr.textContent = "Enter a number ≥ 0.";
      if (taperIn) taperIn.classList.add("is-invalid");
      valid = false;
    }
    return valid;
  }

  function loadPlanSettings() {
    apiGet("/api/plans", function (data) {
      var plan = Array.isArray(data) && data.length > 0 ? data[0] : null;
      var rampIn = document.getElementById("plan-ramp-rate-input");
      var taperIn = document.getElementById("plan-taper-window-input");

      if (plan) {
        _planId = plan.id;
        if (rampIn) rampIn.value = plan.ramp_rate != null ? plan.ramp_rate : 0;
        if (taperIn)
          taperIn.value = plan.taper_length != null ? plan.taper_length : 0;
      } else {
        if (rampIn) rampIn.value = 0;
        if (taperIn) taperIn.value = 0;
      }
      renderSchedulePreview();
    });
  }

  function savePlanSettings() {
    if (!_validateSettingsInputs()) return;

    var rampIn = document.getElementById("plan-ramp-rate-input");
    var taperIn = document.getElementById("plan-taper-window-input");
    var savedEl = document.getElementById("plan-settings-saved");

    var rampRate = parseFloat(rampIn ? rampIn.value : 0);
    var taperLength = parseFloat(taperIn ? taperIn.value : 0);

    function onSaved(res) {
      if (!res.ok) {
        var rampErr = document.getElementById("plan-ramp-rate-error");
        if (rampErr)
          rampErr.textContent =
            res.data && res.data.detail ? res.data.detail : "Save failed.";
        return;
      }
      _planId = res.data.id;
      if (savedEl) {
        savedEl.style.display = "";
        setTimeout(function () {
          savedEl.style.display = "none";
        }, 2000);
      }
    }

    if (_planId) {
      apiPatch(
        "/api/plans/" + _planId,
        { ramp_rate: rampRate, taper_length: taperLength },
        onSaved,
      );
    } else {
      apiPost(
        "/api/plans",
        { name: "Training Plan", ramp_rate: rampRate, taper_length: taperLength },
        onSaved,
      );
    }
  }

  // ── Render orchestration ──────────────────────────────────────────────────
  function renderAll() {
    renderRaceHeader();
    renderTimeCurve();
    renderRaceCards();
    renderFormCurve();
    renderSpecBars();
    renderSchedulePreview();
  }

  function refresh() {
    _ensurePlanId(function () {
      loadProjection(function () {
        loadRaces(function () {
          loadReadiness(function () {
            renderAll();
          });
        });
      });
    });
    loadCalibration();
  }

  // ── Modal ─────────────────────────────────────────────────────────────────
  // The type segmented control has three tabs: race | checkpoint | history.
  // "history" is a UI-only mode for picking a past run; the actual entry it
  // creates is still a race (_editingRaceType), so we track the active tab
  // separately from the entry type.
  var _activeTab = "race";

  function _show(id, on) {
    var el = document.getElementById(id);
    if (el) el.style.display = on ? "" : "none";
  }

  // Set the active type tab and reconfigure which fields are visible.
  function _setModalType(tab) {
    if (["race", "checkpoint", "history"].indexOf(tab) < 0) tab = "race";
    // History is only offered when ADDING (not editing an existing entry).
    if (tab === "history" && _editingRaceId) tab = "race";
    _activeTab = tab;
    _editingRaceType = tab === "checkpoint" ? "checkpoint" : "race";

    var seg = document.getElementById("plan-modal-typeseg");
    if (seg) {
      Array.from(seg.querySelectorAll(".plan-modal-seg-btn")).forEach(
        function (b) {
          var active = b.getAttribute("data-type") === tab;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
          // The History tab is hidden while editing.
          if (b.getAttribute("data-type") === "history")
            b.style.display = _editingRaceId ? "none" : "";
        },
      );
    }

    var isHistory = tab === "history";
    var isCheckpoint = tab === "checkpoint";

    // History tab: show only the preloaded run list; hide the entry form.
    _show("plan-modal-history-tab", isHistory);
    // Entry form fields (hidden on the History tab until a run is picked).
    _show("plan-modal-name-field", !isHistory);
    _show("plan-modal-date-field", !isHistory);
    _show("plan-modal-goal-field", !isHistory && !isCheckpoint);
    _show("plan-modal-priority-field", !isHistory && !isCheckpoint);
    // Checkpoint measure toggle + distance/duration fields.
    _show("plan-modal-measure-field", isCheckpoint);
    if (isHistory) {
      _show("plan-modal-distance-field", false);
      _show("plan-modal-duration-field", false);
    } else {
      _applyCheckpointMeasure();
    }

    // Switching away from a completed-race context clears picked state.
    if (isCheckpoint && _pickedActualSeconds != null) _setActualState(null);

    if (isHistory) _loadHistory();

    var title = document.getElementById("plan-modal-title");
    if (title) {
      var editing = !!_editingRaceId;
      title.textContent =
        (editing ? "Edit " : "Add ") + (isCheckpoint ? "Checkpoint" : "Race");
    }
  }

  // ── Checkpoint measure (distance | duration) ──────────────────────────────
  function _applyCheckpointMeasure() {
    var isCheckpoint = _activeTab === "checkpoint";
    var byDuration = isCheckpoint && _checkpointMeasure === "duration";
    // Races always use distance; checkpoints follow the toggle.
    _show("plan-modal-distance-field", !byDuration);
    _show("plan-modal-duration-field", byDuration);
  }

  function _setCheckpointMeasure(measure) {
    _checkpointMeasure = measure === "duration" ? "duration" : "distance";
    var seg = document.getElementById("plan-modal-measureseg");
    if (seg)
      Array.from(seg.querySelectorAll(".plan-modal-seg-btn")).forEach(
        function (b) {
          var active = b.getAttribute("data-measure") === _checkpointMeasure;
          b.classList.toggle("active", active);
          b.setAttribute("aria-checked", active ? "true" : "false");
        },
      );
    _applyCheckpointMeasure();
  }

  // Set the active priority (A|B|C) in the priority segmented control.
  function _setModalPriority(priority) {
    _modalPriority = ["A", "B", "C"].indexOf(priority) >= 0 ? priority : "A";
    var seg = document.getElementById("plan-modal-priorityseg");
    if (!seg) return;
    Array.from(seg.querySelectorAll(".plan-modal-seg-btn")).forEach(
      function (b) {
        var active = b.getAttribute("data-priority") === _modalPriority;
        b.classList.toggle("active", active);
        b.setAttribute("aria-checked", active ? "true" : "false");
      },
    );
  }

  // ── Goal input mode (time | pace) ─────────────────────────────────────────
  // Parse a pace string "M:SS" (or "MM:SS") into seconds-per-km. Returns null
  // when blank/invalid.
  function _parsePace(str) {
    if (!str || !str.trim()) return null;
    var parts = str.trim().split(":").map(Number);
    if (parts.some(isNaN)) return null;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 1) return parts[0] * 60;
    return null;
  }

  function _paceToStr(secPerKm) {
    if (secPerKm == null) return "";
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    return m + ":" + pad(s);
  }

  // Read the current distance from the input (NaN-safe).
  function _currentDistance() {
    var distIn = document.getElementById("plan-modal-distance");
    var d = distIn ? parseFloat(distIn.value) : NaN;
    return isNaN(d) || d <= 0 ? null : d;
  }

  // Recompute the derived-value hint under the goal input for the active mode.
  function _updateGoalDerived() {
    var goalIn = document.getElementById("plan-modal-goal-time");
    var hint = document.getElementById("plan-modal-goal-derived");
    if (!goalIn || !hint) return;
    var dist = _currentDistance();
    var raw = goalIn.value.trim();
    if (!raw) {
      hint.textContent = dist ? "" : "Set distance to derive pace/time.";
      return;
    }
    if (_goalMode === "time") {
      var goalSec = parseGoalTime(raw);
      if (goalSec == null) {
        hint.textContent = "Enter time as HH:MM:SS or MM:SS.";
      } else if (dist) {
        hint.textContent = "= " + fmtPace(goalSec / dist);
      } else {
        hint.textContent = "Set distance to see pace.";
      }
    } else {
      var paceSec = _parsePace(raw);
      if (paceSec == null) {
        hint.textContent = "Enter pace as M:SS /km.";
      } else if (dist) {
        hint.textContent = "= goal " + fmtTime(Math.round(paceSec * dist));
      } else {
        hint.textContent = "Set distance to see goal time.";
      }
    }
  }

  // Switch goal input mode, converting the current value between time and pace
  // so the field stays consistent for the user.
  function _setGoalMode(mode) {
    var goalIn = document.getElementById("plan-modal-goal-time");
    var next = mode === "pace" ? "pace" : "time";
    var dist = _currentDistance();
    if (goalIn && next !== _goalMode && goalIn.value.trim() && dist) {
      if (next === "pace") {
        var gs = parseGoalTime(goalIn.value);
        if (gs != null) goalIn.value = _paceToStr(gs / dist);
      } else {
        var ps = _parsePace(goalIn.value);
        if (ps != null) goalIn.value = goalTimeToStr(Math.round(ps * dist));
      }
    }
    _goalMode = next;
    var seg = document.getElementById("plan-modal-goalmodeseg");
    if (seg)
      Array.from(seg.querySelectorAll(".plan-modal-seg-btn")).forEach(
        function (b) {
          var active = b.getAttribute("data-goalmode") === _goalMode;
          b.classList.toggle("active", active);
          b.setAttribute("aria-checked", active ? "true" : "false");
        },
      );
    if (goalIn)
      goalIn.placeholder = _goalMode === "pace" ? "M:SS /km" : "HH:MM:SS or MM:SS";
    _updateGoalDerived();
  }

  // Resolve the goal-time seconds from the field regardless of mode. Returns
  // { seconds, error } — error is a user-facing string when parsing fails.
  function _resolveGoalSeconds(dist) {
    var goalIn = document.getElementById("plan-modal-goal-time");
    var raw = goalIn ? goalIn.value.trim() : "";
    if (!raw) return { seconds: null, error: null };
    if (_goalMode === "pace") {
      var paceSec = _parsePace(raw);
      if (paceSec == null) return { seconds: null, error: "Enter pace as M:SS /km." };
      if (!dist) return { seconds: null, error: "Set a distance to convert pace to a goal time." };
      return { seconds: Math.round(paceSec * dist), error: null };
    }
    var gs = parseGoalTime(raw);
    if (gs == null) return { seconds: null, error: "Enter goal time as HH:MM:SS or MM:SS." };
    return { seconds: gs, error: null };
  }

  // ── Pick from history (completed-race picker) ─────────────────────────────
  // Reset picker + completed-race state (called on open/close).
  function _resetPicker() {
    _pickedActualSeconds = null;
    var actualField = document.getElementById("plan-modal-actual-field");
    if (actualField) actualField.style.display = "none";
  }

  // Show/hide the completed-race "Actual time" banner and remember the seconds.
  function _setActualState(seconds) {
    _pickedActualSeconds = seconds;
    var actualField = document.getElementById("plan-modal-actual-field");
    var valEl = document.getElementById("plan-modal-actual-val");
    if (seconds != null) {
      if (valEl) valEl.textContent = fmtTime(seconds);
      if (actualField) actualField.style.display = "";
    } else {
      if (actualField) actualField.style.display = "none";
    }
  }

  function _isoDaysAgo(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function _loadHistory() {
    var listEl = document.getElementById("plan-modal-history-list");
    var loadingEl = document.getElementById("plan-modal-history-loading");
    var emptyEl = document.getElementById("plan-modal-history-empty");

    function _renderHistoryList() {
      if (loadingEl) loadingEl.style.display = "none";
      if (!listEl) return;
      if (_historyRuns.length === 0) {
        if (emptyEl) emptyEl.style.display = "";
        listEl.innerHTML = "";
        return;
      }
      if (emptyEl) emptyEl.style.display = "none";
      listEl.innerHTML = "";
      _historyRuns.forEach(function (r, idx) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "plan-modal-history-row";
        btn.setAttribute("data-idx", idx);
        var distKm = parseFloat(r.distance_km || 0).toFixed(2);
        btn.innerHTML =
          '<span class="plan-modal-history-row-top">' +
          esc(formatDate(r.workout_date)) +
          " · " + distKm + " km · " + esc(fmtTime(r.duration_seconds)) +
          "</span>" +
          '<span class="plan-modal-history-row-name">' +
          esc(r.name || "Run") + "</span>";
        btn.addEventListener("click", function () {
          _pickRun(r);
        });
        listEl.appendChild(btn);
      });
    }

    if (_historyLoaded) {
      _renderHistoryList();
      return;
    }
    if (loadingEl) loadingEl.style.display = "";
    if (emptyEl) emptyEl.style.display = "none";

    // Last 3 months (90 days) of runs.
    var from = _isoDaysAgo(90);
    var to = todayISO();
    apiGet(
      "/api/workouts?from=" + from + "&to=" + to,
      function (data) {
        var rows = Array.isArray(data) ? data : [];
        // Runs only, > 10 km, with a usable finish time. Server does not filter
        // by distance, so filter client-side. Sort most-recent first.
        _historyRuns = rows
          .filter(function (w) {
            return (
              (w.workout_type || "").toLowerCase() === "run" &&
              w.distance_km != null &&
              parseFloat(w.distance_km) > 10 &&
              w.duration_seconds
            );
          })
          .sort(function (a, b) {
            return a.workout_date < b.workout_date ? 1 : a.workout_date > b.workout_date ? -1 : 0;
          });
        _historyLoaded = true;
        _renderHistoryList();
      },
    );
  }

  // Prefill the form from a picked past run and switch to completed-race mode.
  function _pickRun(run) {
    var nameIn = document.getElementById("plan-modal-name");
    var dateIn = document.getElementById("plan-modal-date");
    var distIn = document.getElementById("plan-modal-distance");
    var distKm = parseFloat(run.distance_km || 0);

    if (nameIn)
      nameIn.value =
        run.name && run.name.trim()
          ? run.name.trim()
          : Math.round(distKm) + "K race";
    if (dateIn) dateIn.value = run.workout_date || "";
    if (distIn) distIn.value = distKm ? distKm.toFixed(2) : "";

    // Leave the History tab and reveal the Race entry form pre-filled.
    _setModalType("race");
    // Past races are usually B-priority; default the selector to B.
    _setModalPriority("B");
    _setActualState(run.duration_seconds || null);
    // Refresh the goal-pace hint now that distance is set.
    _updateGoalDerived();
  }

  function openModal(race, raceType) {
    _editingRaceId = race ? race.id : null;

    var modal = document.getElementById("plan-race-modal");
    var nameIn = document.getElementById("plan-modal-name");
    var dateIn = document.getElementById("plan-modal-date");
    var distIn = document.getElementById("plan-modal-distance");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var deleteBtn = document.getElementById("plan-modal-delete-btn");
    var errEl = document.getElementById("plan-modal-error");

    if (!modal) return;

    var type = race ? race.type || "race" : raceType || "race";
    if (deleteBtn) deleteBtn.style.display = race ? "" : "none";
    if (errEl) errEl.textContent = "";

    if (race) {
      if (nameIn) nameIn.value = race.name || "";
      if (dateIn) dateIn.value = race.date || "";
      if (distIn) distIn.value = race.distance || "";
      if (goalIn) goalIn.value = goalTimeToStr(race.goal_time_seconds);
    } else {
      if (nameIn) nameIn.value = "";
      if (dateIn) dateIn.value = "";
      if (distIn) distIn.value = "";
      if (goalIn) goalIn.value = "";
    }

    // Reset picker/completed-race state every time the modal opens.
    _resetPicker();
    // Reset goal mode to Time and checkpoint measure to Distance on each open.
    _goalMode = "time";
    _setGoalMode("time");
    _setCheckpointMeasure("distance");

    // Tab + priority state (must run after _editingRaceId is set for the title).
    _setModalType(type);
    _setModalPriority(race && race.priority ? race.priority : "A");
    _updateGoalDerived();

    // Preload the history list up front so the History tab is instant.
    if (!_editingRaceId) _loadHistory();

    modal.style.display = "";
    if (nameIn && type !== "history") nameIn.focus();
  }

  function closeModal() {
    var modal = document.getElementById("plan-race-modal");
    if (modal) modal.style.display = "none";
    _resetPicker();
  }

  function saveModal() {
    var nameIn = document.getElementById("plan-modal-name");
    var dateIn = document.getElementById("plan-modal-date");
    var distIn = document.getElementById("plan-modal-distance");
    var goalIn = document.getElementById("plan-modal-goal-time");
    var errEl = document.getElementById("plan-modal-error");

    var name = nameIn ? nameIn.value.trim() : "";
    var date = dateIn ? dateIn.value : "";
    var dist = distIn ? parseFloat(distIn.value) : NaN;
    // Type comes from the active segmented tab, not a <select>.
    var type = _editingRaceType === "checkpoint" ? "checkpoint" : "race";

    if (!name) {
      if (errEl) errEl.textContent = "Name is required.";
      return;
    }
    if (!date) {
      if (errEl) errEl.textContent = "Date is required.";
      return;
    }

    // Duration-only checkpoint: the backend cannot store this yet (races.distance_km
    // is NOT NULL and there is no duration column). Block the save with a clear
    // message instead of sending invalid data. See report/TODO for the schema fix.
    if (type === "checkpoint" && _checkpointMeasure === "duration") {
      if (errEl)
        errEl.textContent =
          "Duration-only checkpoints can’t be saved yet (backend needs a " +
          "duration column). Switch to Distance for now.";
      return;
    }

    if (isNaN(dist) || dist <= 0) {
      if (errEl) errEl.textContent = "Distance must be a positive number.";
      return;
    }

    // Resolve goal seconds from whichever mode (time or pace) is active.
    var goalRes = _resolveGoalSeconds(dist);
    if (goalRes.error) {
      if (errEl) errEl.textContent = goalRes.error;
      return;
    }
    var goalSec = goalRes.seconds;

    // Plausibility guard: reject goals whose implied pace is outside a realistic
    // 2:30–15:00 /km band (catches "4:30" typed for 4:30:00). Measured actual
    // times bypass this — they are real data.
    if (goalSec !== null && dist > 0) {
      var paceSec = goalSec / dist;
      if (paceSec < 150 || paceSec > 900) {
        if (errEl)
          errEl.textContent =
            "Goal implies " + fmtPace(paceSec) + " over " + dist +
            " km — not a realistic pace. For longer races use HH:MM:SS " +
            "(e.g. 4:30:00), or switch to Pace mode.";
        return;
      }
    }

    var body = { name: name, date: date, distance: dist, type: type };
    if (goalSec !== null) body.goal_time_seconds = goalSec;
    // Priority is only meaningful for races (checkpoints are forced to C by the
    // backend). Send it from the priority segmented control on the Race tab.
    if (type === "race") body.priority = _modalPriority;
    // Completed-race mode: a past run was picked from history → mark done and
    // send the real finish time (calibration data). actual_time is measured, so
    // the goal-pace plausibility guard above does not apply to it.
    if (type === "race" && _pickedActualSeconds != null) {
      body.status = "done";
      body.actual_time_seconds = _pickedActualSeconds;
    } else {
      body.status = "planned";
    }
    if (errEl) errEl.textContent = "";

    if (_editingRaceId) {
      apiPatch(_planRaceUrl(_editingRaceId), body, function (res) {
        if (!res.ok) {
          if (errEl)
            errEl.textContent =
              res.data && res.data.detail
                ? JSON.stringify(res.data.detail)
                : "Save failed.";
          return;
        }
        closeModal();
        refresh();
      });
    } else {
      apiPost(_planRaceUrl(), body, function (res) {
        if (!res.ok) {
          if (errEl)
            errEl.textContent =
              res.data && res.data.detail
                ? JSON.stringify(res.data.detail)
                : "Save failed.";
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
    var race = _races.find(function (r) {
      return r.id === rid;
    });
    var label = race
      ? race.type === "checkpoint"
        ? "checkpoint"
        : "race"
      : "entry";
    closeModal();
    showConfirm(
      "Delete this " + label + "?",
      "This action cannot be undone.",
      function () {
        apiDelete(_planRaceUrl(rid), function (res) {
          if (res.ok) refresh();
        });
      },
    );
  }

  function _deleteRow(raceId, raceName) {
    var race = _races.find(function (r) {
      return r.id === raceId;
    });
    var label = race
      ? race.type === "checkpoint"
        ? "checkpoint"
        : "race"
      : "entry";
    showConfirm(
      "Delete this " + label + "?",
      "This action cannot be undone.",
      function () {
        apiDelete(_planRaceUrl(raceId), function (res) {
          if (res.ok) refresh();
        });
      },
    );
  }

  // ── Event wiring ──────────────────────────────────────────────────────────
  function wireEvents() {
    // Single "+ Add" button opens the modal defaulting to the Race tab.
    var addBtn = document.getElementById("plan-add-btn");
    if (addBtn)
      addBtn.addEventListener("click", function () {
        openModal(null, "race");
      });

    // Modal type tabs (Race | Checkpoint).
    var typeSeg = document.getElementById("plan-modal-typeseg");
    if (typeSeg)
      typeSeg.addEventListener("click", function (e) {
        var b = e.target.closest(".plan-modal-seg-btn");
        if (!b) return;
        _setModalType(b.getAttribute("data-type"));
      });

    // Modal priority segmented control (A | B | C).
    var prSeg = document.getElementById("plan-modal-priorityseg");
    if (prSeg)
      prSeg.addEventListener("click", function (e) {
        var b = e.target.closest(".plan-modal-seg-btn");
        if (!b) return;
        _setModalPriority(b.getAttribute("data-priority"));
      });

    // Checkpoint measure toggle (Distance | Duration).
    var measureSeg = document.getElementById("plan-modal-measureseg");
    if (measureSeg)
      measureSeg.addEventListener("click", function (e) {
        var b = e.target.closest(".plan-modal-seg-btn");
        if (!b) return;
        _setCheckpointMeasure(b.getAttribute("data-measure"));
      });

    // Goal mode toggle (Time | Pace).
    var goalModeSeg = document.getElementById("plan-modal-goalmodeseg");
    if (goalModeSeg)
      goalModeSeg.addEventListener("click", function (e) {
        var b = e.target.closest(".plan-modal-seg-btn");
        if (!b) return;
        _setGoalMode(b.getAttribute("data-goalmode"));
      });

    // Recompute the goal-derived hint as the user types goal or distance.
    var goalIn = document.getElementById("plan-modal-goal-time");
    if (goalIn) goalIn.addEventListener("input", _updateGoalDerived);
    var distIn = document.getElementById("plan-modal-distance");
    if (distIn) distIn.addEventListener("input", _updateGoalDerived);

    // Clear completed-race state (revert to a normal planned race).
    var actualClear = document.getElementById("plan-modal-actual-clear");
    if (actualClear)
      actualClear.addEventListener("click", function () {
        _setActualState(null);
      });

    // Distance quick-fill buttons.
    var distQuick = document.getElementById("plan-modal-distance-quick");
    if (distQuick)
      distQuick.addEventListener("click", function (e) {
        var b = e.target.closest(".plan-modal-quick-btn");
        if (!b) return;
        var distIn = document.getElementById("plan-modal-distance");
        if (distIn) distIn.value = b.getAttribute("data-km");
        _updateGoalDerived();
      });

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
    if (confirmDelete)
      confirmDelete.addEventListener("click", function () {
        var cb = _confirmCallback;
        closeConfirm();
        if (cb) cb();
      });

    var rampIn = document.getElementById("plan-ramp-rate-input");
    var taperIn = document.getElementById("plan-taper-window-input");
    var saveSettingsBtn = document.getElementById("plan-save-settings-btn");

    if (rampIn) rampIn.addEventListener("input", renderSchedulePreview);
    if (taperIn) taperIn.addEventListener("input", renderSchedulePreview);
    if (saveSettingsBtn)
      saveSettingsBtn.addEventListener("click", savePlanSettings);

    var planModal = document.getElementById("plan-race-modal");
    if (planModal)
      planModal.addEventListener("click", function (e) {
        if (e.target === planModal) closeModal();
      });
    var confirmModal = document.getElementById("plan-confirm-modal");
    if (confirmModal)
      confirmModal.addEventListener("click", function (e) {
        if (e.target === confirmModal) closeConfirm();
      });
  }

  // ── Public init ───────────────────────────────────────────────────────────
  function init() {
    if (!_initialized) {
      _initialized = true;
      wireEvents();
    }
    loadPlanSettings();
    refresh();
  }

  window.TrainingPlan = { init: init };
})();
