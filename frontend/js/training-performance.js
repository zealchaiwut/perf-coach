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
  // TrainingPlan entity UUID from GET /api/plans — used for all /api/plans/{id}/...
  // race/checkpoint/projection URLs.  Null until loadPlanSettings() completes;
  // the mutation buttons (Add/Edit/Delete) are only reachable after the page
  // has loaded, so _planEntityId will be set by then.
  var _planEntityId = null;
  // Athlete current performance scores (GET /api/athletes/{id}/performance).
  // Null until loaded; only rendered when .state === "scored".
  var _athletePerf = null;
  // Threshold pace (seconds/km) from /api/user-preferences — used to compute the
  // demonstrated "Fitness" score of a completed race. Null when unset.
  var _thresholdPace = null;
  // Completed-race (Pick-from-history) state. When a past run is selected while
  // ADDING a race, we stash its finish time here and POST status:"done".
  var _pickedActualSeconds = null;
  var _historyLoaded = false;
  var _historyRuns = [];
  // Goal input mode: "time" (HH:MM:SS) or "pace" (M:SS /km, derived via distance).
  var _goalMode = "time";
  // Checkpoint measure mode: "distance" or "duration" (duration = stubbed).
  var _checkpointMeasure = "distance";
  // Last computed Plan bundle (GET /api/plan/computed).
  var _bundle = null;

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

  // Measure the chart's real rendered width so the SVG viewBox is built to match
  // (1 unit ≈ 1 real pixel). The SVG is width:100%, so its own bounding box is
  // the true content width (no card padding) — this is what keeps mobile labels
  // at their nominal px instead of the ~3× downscale from a hardcoded 1140-unit
  // viewBox. Falls back to the parent width, floored at 280 (e.g. tab hidden).
  function measureChartW(svg) {
    var w = svg && svg.getBoundingClientRect ? svg.getBoundingClientRect().width : 0;
    if (!w && svg && svg.parentElement) {
      w = svg.parentElement.getBoundingClientRect().width;
    }
    return Math.max(280, Math.round(w || 0));
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
    window
      .fetchCurrentUser()
      .then(function (u) {
        if (u) _planId = u.id;
        cb();
      })
      .catch(function () {
        cb();
      });
  }

  function _planRaceUrl(raceId) {
    return "/api/plans/" + _planEntityId + "/races" + (raceId ? "/" + raceId : "");
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
        openRacePicker();
      });
  }

  // ── Change-race picker: pick which EXISTING race is the A-priority target ──
  // "Change race" used to just open the current target's own edit form — it
  // never let you pick a DIFFERENT already-listed race to promote. Only one
  // race is ever treated as the target/primary (_primaryRace = first
  // priority=="A" non-done race), so "changing" it means demoting the current
  // A (if any) to B and promoting the picked race to A — both plain PATCHes
  // against the existing race-update endpoint, no new backend surface needed.
  function _raceById(id) {
    for (var i = 0; i < _races.length; i++) {
      if (_races[i].id === id) return _races[i];
    }
    return null;
  }

  function _racePickerRowHtml(r, isCurrent) {
    var distKm = parseFloat(r.distance || 0);
    var letter = r.priority || "A";
    return (
      '<div class="plan-picker-row' + (isCurrent ? " is-current" : "") + '" data-race-id="' + r.id + '">' +
        '<span class="plan-picker-letter" style="background:' + (_LET_BG[letter] || "#6b7280") + '">' + esc(letter) + "</span>" +
        '<div class="plan-picker-info">' +
          '<div class="plan-picker-name">' + esc(r.name || "Unnamed") + "</div>" +
          '<div class="plan-picker-meta">' + esc(formatDate(r.date)) + (distKm ? " · " + distKm.toFixed(2) + " km" : "") + "</div>" +
        "</div>" +
        '<div class="plan-picker-actions">' +
          '<button type="button" class="plan-picker-editbtn" data-picker-edit="' + r.id + '">Edit</button>' +
          (isCurrent
            ? ""
            : '<button type="button" class="plan-picker-setbtn" data-picker-settarget="' + r.id + '">Set as target</button>') +
        "</div>" +
      "</div>"
    );
  }

  function openRacePicker() {
    var overlay = document.getElementById("plan-race-picker-modal");
    var list = document.getElementById("plan-race-picker-list");
    if (!overlay || !list) return;

    var candidates = _races.filter(function (r) {
      return r.type === "race" && r.status !== "done";
    });
    list.innerHTML = candidates.length
      ? candidates
          .map(function (r) {
            return _racePickerRowHtml(r, _primaryRace && r.id === _primaryRace.id);
          })
          .join("")
      : '<div class="plan-picker-empty">No upcoming races yet — add one to get started.</div>';

    list.querySelectorAll("[data-picker-settarget]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _setPrimaryRace(btn.getAttribute("data-picker-settarget"));
      });
    });
    list.querySelectorAll("[data-picker-edit]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-picker-edit");
        var race = _raceById(id);
        closeRacePicker();
        if (race) openModal(race, "race");
      });
    });

    overlay.style.display = "";
  }

  function closeRacePicker() {
    var overlay = document.getElementById("plan-race-picker-modal");
    if (overlay) overlay.style.display = "none";
  }

  // Promote raceId to A-priority, demoting whatever was previously A (if any
  // and if it's a different race) to B, so there's still only one target.
  function _setPrimaryRace(raceId) {
    var prevPrimary = _primaryRace;
    var doPromote = function () {
      apiPatch(_planRaceUrl(raceId), { priority: "A" }, function (res) {
        closeRacePicker();
        if (!res.ok) {
          console.warn("[plan] failed to set primary race", res);
          return;
        }
        refresh();
      });
    };
    if (prevPrimary && prevPrimary.id !== raceId && prevPrimary.priority === "A") {
      apiPatch(_planRaceUrl(prevPrimary.id), { priority: "B" }, function () {
        doPromote();
      });
    } else {
      doPromote();
    }
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
    // Applied model correction from real predicted-vs-actual race
    // calibrations ("model ran 4% pessimistic → estimates corrected −4%").
    var corrEl = document.getElementById("plan-calib-correction");
    if (corrEl) {
      var pct = data && typeof data.correction_pct === "number" ? data.correction_pct : null;
      var n = (data && data.n_calibrations) || 0;
      if (pct === null || n === 0) {
        corrEl.innerHTML = '<span class="pm-italic">No finished races yet</span>';
      } else if (Math.abs(pct) < 0.05) {
        corrEl.textContent = "None needed (" + n + " race" + (n === 1 ? "" : "s") + ")";
      } else {
        var dirTxt = pct > 0 ? "model ran optimistic" : "model ran pessimistic";
        corrEl.textContent = (pct > 0 ? "+" : "") + pct + "% — " + dirTxt +
          " (" + n + " race" + (n === 1 ? "" : "s") + ")";
      }
    }
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
      // How the estimate was formed from the athlete's own scores — the
      // interpretable decomposition (time_curve.estimate_basis).
      var basisEl = document.getElementById("plan-projected-basis");
      if (basisEl) {
        var basis = tc && tc.estimate_basis;
        if (basis && basis.blended_pace_seconds_per_km != null) {
          var bits = [];
          if (basis.endurance_score != null && basis.endurance_pace_seconds_per_km != null)
            bits.push("End " + Math.round(basis.endurance_score) + " → " + fmtPace(basis.endurance_pace_seconds_per_km));
          if (basis.speed_score != null && basis.speed_pace_seconds_per_km != null)
            bits.push("Spd " + Math.round(basis.speed_score) + " → " + fmtPace(basis.speed_pace_seconds_per_km));
          var wPct = basis.speed_weight != null ? Math.round(basis.speed_weight * 100) : null;
          bits.push("blended" + (wPct != null ? " (" + wPct + "% speed)" : "") + " → " +
            fmtPace(basis.blended_pace_seconds_per_km));
          basisEl.textContent = bits.join(" · ");
        } else {
          basisEl.textContent = "";
        }
      }
    } else {
      _hideProjNow();
    }

    // Responsive sizing: build the coordinate space to the measured render
    // width so 1 unit ≈ 1px on any viewport (fixes the ~3× mobile downscale).
    var W = measureChartW(svg);
    var mobile = W < 480;
    var H = mobile ? 240 : 200;
    // Trim l/r on mobile so the plot area isn't tiny inside the narrow card.
    var p = mobile
      ? { l: 46, r: 16, t: 14, b: 30 }
      : { l: 54, r: 30, t: 14, b: 26 };
    // viewBox + CSS height must move together, else it letterboxes.
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.style.height = H + "px";
    // Floor every label at 10px (several are 8–9 today → unreadable on mobile).
    var FS = function (n) { return Math.max(10, n); };
    // Thicker data lines on mobile.
    var LWmain = mobile ? 2.8 : 2.4;

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
        x: p.l - 8, y: y(v) + 3, "font-size": FS(10),
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
        d: Path(histPts), fill: "none", stroke: "#4f6ef7", "stroke-width": LWmain,
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
        "stroke-width": LWmain, "stroke-dasharray": "5 4",
      }));

    // goal line
    if (goalSec != null) {
      svg.appendChild(E("line", {
        x1: p.l, x2: W - p.r, y1: y(goalSec), y2: y(goalSec),
        stroke: "#16a34a", "stroke-width": 1.5, "stroke-dasharray": "7 5",
      }));
      var gl = E("text", {
        x: p.l + 4, y: y(goalSec) - 5, "font-size": FS(9),
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
      x: nowX + 3, y: p.t + 8, "font-size": FS(8), "font-family": "JetBrains Mono",
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
        x: mx, y: H - 7, "font-size": FS(9), "font-family": "JetBrains Mono",
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

  function _clamp01_100(v) {
    return Math.max(0, Math.min(100, v));
  }

  // Signed integer as "(+N)" / "(−N)" for a score delta.
  function _signed(n) {
    return "(" + (n >= 0 ? "+" : "−") + Math.abs(n) + ")";
  }

  // ── Score model (FIRST-PASS heuristic — tunable) ──────────────────────────
  // The required-/demonstrated-score model below is a first-pass distance
  // weighting: reference distance 21.1 km (half), speed/endurance split slope
  // 0.18 for required scores and 0.06 for demonstrated. Short races demand more
  // speed, long races more endurance. The operator may recalibrate these
  // constants and the overall scale later — nothing downstream depends on them.

  // Per-race REQUIRED End/Spd tags for UPCOMING cards. Scores are computed
  // server-side and delivered in the bundle as r.computed.scores (kind:
  // "required" with end/spd + d_end/d_spd). Returns "" when absent.
  function _requiredScoreFoot(r) {
    var sc = r.computed && r.computed.scores;
    if (!sc || sc.kind !== "required") return "";
    var tags =
      '<span class="pm-sc req">End ' + sc.end + " " + _signed(sc.d_end) + "</span>" +
      '<span class="pm-sc req">Spd ' + sc.spd + " " + _signed(sc.d_spd) + "</span>";
    return '<div class="pm-rcfoot"><div class="pm-scoretags">' + tags + "</div></div>";
  }

  // DEMONSTRATED End/Spd for a COMPLETED race — the athlete-scale score as of
  // the race date, computed server-side (bundle r.computed.scores, kind
  // "demonstrated"). Returns null when absent.
  function _demonstratedScores(r) {
    var sc = r.computed && r.computed.scores;
    if (!sc || sc.kind !== "demonstrated") return null;
    return { end: sc.end, spd: sc.spd };
  }

  // Format a signed delta of actual vs goal as "+M:SS" (over) / "−M:SS"
  // (under). Returns "" when there is no goal.
  function _actualDelta(actualSec, goalSec) {
    if (!goalSec || actualSec == null) return "";
    var diff = actualSec - goalSec;
    var sign = diff >= 0 ? "+" : "−";
    var abs = Math.abs(diff);
    var m = Math.floor(abs / 60);
    var s = Math.round(abs % 60);
    return sign + m + ":" + pad(s);
  }

  function _metaText(r, distKm) {
    return (
      formatDate(r.date) +
      " · " +
      (r.distance != null
        ? distKm.toFixed(2) + " km"
        : r.duration_seconds
          ? fmtTime(r.duration_seconds)
          : "—")
    );
  }

  // Priority/type badge. Checkpoints get a distinct "CP" text badge (teal) so
  // they never read as a C-priority race; races keep the A/B/C letter square.
  function _priorityBadge(isCheckpoint, priority) {
    if (isCheckpoint) {
      return '<span class="pm-rclet pm-rclet--cp">CP</span>';
    }
    return '<span class="pm-rclet" style="background:' +
      (_LET_BG[priority] || "#6b7280") + '">' + esc(priority) + "</span>";
  }

  // Build a full-width UPCOMING card (Goal + Estimated columns).
  function _buildUpcomingCard(r) {
    var isCheckpoint = r.type === "checkpoint";
    var priority = isCheckpoint ? "C" : r.priority || "A";
    var isTarget = _primaryRace && r.id === _primaryRace.id;
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
    var rightTag = isTarget ? '<span class="pm-tgt">TARGET</span>' : recalHtml;

    var head =
      '<div class="pm-rchd">' +
      _priorityBadge(isCheckpoint, priority) +
      '<span class="pm-rcname">' + esc(r.name || "Unnamed") + "</span>" +
      '<span class="pm-typetag">' +
      (isCheckpoint ? "CHECKPOINT" : "RACE") + "</span>" +
      '<span class="pm-rcmeta">' + esc(_metaText(r, distKm)) + "</span>" +
      '<span class="pm-upc">UPCOMING</span>' +
      rightTag +
      '<span class="pm-rcactions">' +
      '<button class="pm-rcact" data-act="edit" type="button">Edit</button>' +
      '<button class="pm-rcact" data-act="del" type="button">✕</button>' +
      "</span>" +
      "</div>";

    // Estimated column from the bundle's precomputed per-race estimate.
    var secondCol = "";
    var est = r.computed && r.computed.estimate;
    if (est && est.est != null) {
      var estPace = distKm ? fmtPace(est.est / distKm) : "";
      var bandTxt =
        est.band != null
          ? " · ±" + Math.max(1, Math.round(est.band / 60)) + " min"
          : "";
      secondCol =
        '<div class="pm-col est">' +
        '<div class="pm-coll">Estimated</div>' +
        '<div class="pm-colt">' + esc(fmtTime(est.est)) + "</div>" +
        '<div class="pm-colp">' + esc(estPace) + esc(bandTxt) + "</div></div>";
    }

    var grid =
      '<div class="pm-rcgrid">' +
      '<div class="pm-col"><div class="pm-coll">Goal</div>' +
      '<div class="pm-colt">' + esc(goalSec ? fmtTime(goalSec) : "—") + "</div>" +
      '<div class="pm-colp">' + esc(goalPace || "—") + "</div></div>" +
      secondCol +
      "</div>";

    // Per-race REQUIRED End/Spd scores for this race's goal, plus delta vs
    // current (shown only when goal + estimate + scores + tp are all present).
    var foot = _requiredScoreFoot(r);

    card.innerHTML = head + grid + foot;
    _wireCardActions(card, r);
    return card;
  }

  // Build a compact COMPLETED card (Goal + Actual columns, ~30% smaller). Shows
  // the actual-vs-goal delta next to Actual when a goal exists.
  function _buildCompletedCard(r) {
    var isCheckpoint = r.type === "checkpoint";
    var priority = isCheckpoint ? "C" : r.priority || "A";
    var distKm = parseFloat(r.distance || 0);
    var goalSec = r.goal_time_seconds || null;
    var goalPace = goalSec && distKm ? fmtPace(goalSec / distKm) : "";
    var actualSec = r.actual_time_seconds;
    var actualPace = actualSec != null && distKm ? fmtPace(actualSec / distKm) : "";
    var delta = _actualDelta(actualSec, goalSec);
    var deltaCls = delta && delta.charAt(0) === "+" ? "over" : "under";

    var card = document.createElement("div");
    card.className = "pm-rc pm-rc--done";
    card.setAttribute("data-race-id", r.id);

    // Demonstrated End/Spd scores from this race's own result (distance-split).
    var demo = _demonstratedScores(r);
    var demoTags = demo
      ? '<span class="pm-sc req">End ' + demo.end + "</span>" +
        '<span class="pm-sc req">Spd ' + demo.spd + "</span>"
      : "";

    var head =
      '<div class="pm-rchd">' +
      _priorityBadge(isCheckpoint, priority) +
      '<span class="pm-rcname">' + esc(r.name || "Unnamed") + "</span>" +
      '<span class="pm-typetag">' +
      (isCheckpoint ? "CHECKPOINT" : "RACE") + "</span>" +
      '<span class="pm-upc pm-done">DONE</span>' +
      demoTags +
      '<span class="pm-rcactions">' +
      '<button class="pm-rcact" data-act="edit" type="button">Edit</button>' +
      '<button class="pm-rcact" data-act="del" type="button">✕</button>' +
      "</span>" +
      "</div>" +
      '<div class="pm-rcmeta pm-rcmeta--done">' + esc(_metaText(r, distKm)) + "</div>";

    var actualLabel =
      "Actual" +
      (delta
        ? ' <span class="pm-delta ' + deltaCls + '">' + esc(delta) + "</span>"
        : "");

    var grid =
      '<div class="pm-rcgrid">' +
      '<div class="pm-col"><div class="pm-coll">Goal</div>' +
      '<div class="pm-colt">' + esc(goalSec ? fmtTime(goalSec) : "—") + "</div>" +
      '<div class="pm-colp">' + esc(goalPace || "—") + "</div></div>" +
      '<div class="pm-col est"><div class="pm-coll">' + actualLabel + "</div>" +
      '<div class="pm-colt">' + esc(actualSec != null ? fmtTime(actualSec) : "—") + "</div>" +
      '<div class="pm-colp">' + esc(actualPace || "—") + "</div></div>" +
      "</div>";

    card.innerHTML = head + grid;
    _wireCardActions(card, r);
    return card;
  }

  function _wireCardActions(card, r) {
    var editBtn = card.querySelector('[data-act="edit"]');
    if (editBtn)
      editBtn.addEventListener("click", function () {
        openModal(r, r.type || "race");
      });
    var delBtn = card.querySelector('[data-act="del"]');
    if (delBtn)
      delBtn.addEventListener("click", function () {
        _deleteRow(r.id, r.name || "entry");
      });
  }

  function renderRaceCards() {
    var container = document.getElementById("plan-races");
    var loadingEl = document.getElementById("plan-races-loading");
    var emptyEl = document.getElementById("plan-races-empty");
    if (!container) return;
    if (loadingEl) loadingEl.style.display = "none";

    // Remove previously rendered section wrapper (headers + grids + cards).
    var prev = container.querySelector(".pm-races-sections");
    if (prev) prev.remove();

    if (_races.length === 0) {
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    function byDate(a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    }
    var completed = _races
      .filter(function (r) {
        return r.status === "done" && r.actual_time_seconds != null;
      })
      .sort(byDate);
    var upcoming = _races
      .filter(function (r) {
        return !(r.status === "done" && r.actual_time_seconds != null);
      })
      .sort(byDate);

    var sections = document.createElement("div");
    sections.className = "pm-races-sections";

    // COMPLETED first — a two-per-row grid of compact cards.
    if (completed.length > 0) {
      var chdr = document.createElement("div");
      chdr.className = "pm-races-hdr";
      chdr.textContent = "Completed";
      sections.appendChild(chdr);

      var grid = document.createElement("div");
      grid.className = "pm-completed-grid";
      completed.forEach(function (r) {
        grid.appendChild(_buildCompletedCard(r));
      });
      sections.appendChild(grid);
    }

    // UPCOMING — full-width cards.
    if (upcoming.length > 0) {
      var uhdr = document.createElement("div");
      uhdr.className = "pm-races-hdr";
      uhdr.textContent = "Upcoming";
      sections.appendChild(uhdr);

      upcoming.forEach(function (r) {
        sections.appendChild(_buildUpcomingCard(r));
      });
    }

    container.appendChild(sections);
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

    // Responsive sizing: match the measured render width (1 unit ≈ 1px). This
    // card sits in a 2-col row on desktop (~half width) and full width on mobile,
    // so a hardcoded 1140 mis-scaled it on BOTH — measuring fixes both.
    var W = measureChartW(svg);
    var mobile = W < 480;
    var H = mobile ? 260 : 300;
    var p = mobile
      ? { l: 36, r: 14, t: 12, b: 30 }
      : { l: 44, r: 20, t: 12, b: 28 };
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.style.height = H + "px";
    var FS = function (n) { return Math.max(10, n); };
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
        x: p.l - 8, y: y(v) + 3, "font-size": FS(10), "font-family": "JetBrains Mono",
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
      d: Path(pts), fill: "none", stroke: "#4f6ef7", "stroke-width": mobile ? 2.4 : 1.8,
      "stroke-linejoin": "round",
    }));

    // date ticks: first, ~mid, last (3 — kept sparse so mobile isn't crowded).
    var idxs = [0, Math.floor(N * 0.6), N - 1];
    idxs.forEach(function (i, k) {
      var xx = x(i, N);
      var t = E("text", {
        x: xx, y: H - 8, "font-size": FS(10), "font-family": "JetBrains Mono",
        fill: "#9aa3b8",
        "text-anchor": k === 0 ? "start" : k === idxs.length - 1 ? "end" : "middle",
      });
      var d = new Date(formCurve[i].date + "T00:00:00");
      var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      t.textContent = months[d.getMonth()] + " " + d.getDate();
      svg.appendChild(t);
    });
  }

  // ── 5. Specificity bars ───────────────────────────────────────────────────
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
    // current/target come from the backend in the metric's own unit
    // (specificity_progress: km, or seconds for the duration row).
    function fmtDur(sec) {
      sec = Math.round(sec || 0);
      var h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
      return h > 0 ? h + "h " + String(m).padStart(2, "0") + "m" : m + "m";
    }
    function fmtVal(m) {
      if (m.unit === "seconds") return fmtDur(m.current) + " / " + fmtDur(m.target);
      return (Math.round(m.current * 10) / 10) + " / " + (Math.round(m.target * 10) / 10) + " km";
    }
    // Goal pace for the explainer copy, when derivable from the primary race.
    var goalPaceTxt = "";
    if (_primaryRace && _primaryRace.goal_time_seconds && _primaryRace.distance) {
      goalPaceTxt = " (" + fmtPace(_primaryRace.goal_time_seconds / parseFloat(_primaryRace.distance)) + ")";
    }

    if (sp.volume_at_pace)
      rows.push(["Goal-pace volume", pct(sp.volume_at_pace.current, sp.volume_at_pace.target), fmtVal(sp.volume_at_pace),
        "km run within ±15 s/km of goal pace" + goalPaceTxt + " · target 60% of race distance"]);
    if (sp.longest_pace_effort)
      rows.push(["Longest-at-pace", pct(sp.longest_pace_effort.current, sp.longest_pace_effort.target), fmtVal(sp.longest_pace_effort),
        "longest single run at goal pace" + goalPaceTxt + " ±15 s/km · target 90% of race distance"]);
    if (sp.longest_run_by_distance)
      rows.push(["Longest run (distance)", pct(sp.longest_run_by_distance.current, sp.longest_run_by_distance.target), fmtVal(sp.longest_run_by_distance),
        "longest single run, any pace · target 90% of race distance"]);
    if (sp.longest_run_by_duration)
      rows.push(["Longest run (duration)", pct(sp.longest_run_by_duration.current, sp.longest_run_by_duration.target), fmtVal(sp.longest_run_by_duration),
        "longest time on feet, any pace · target 90% of goal time"]);

    if (rows.length === 0) {
      host.innerHTML = "";
      if (emptyEl) emptyEl.style.display = "";
      return;
    }

    host.innerHTML = rows
      .map(function (r) {
        return (
          '<div class="pm-specitem">' +
          '<div class="pm-specrow">' +
          '<div class="pm-specname">' + esc(r[0]) + "</div>" +
          '<div class="pm-spectrack"><div class="pm-specfill" style="width:' +
          r[1] + '%"></div></div>' +
          '<div class="pm-specpct">' + r[1] + "%</div>" +
          "</div>" +
          '<div class="pm-specsub"><span class="pm-specval">' + esc(r[2]) + "</span> · " + esc(r[3]) + "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  // ── Plan entity id ────────────────────────────────────────────────────────
  // Ramp-rate/taper-window settings + schedule preview moved to the Plan tab
  // (training-plan.js) — this module still needs _planEntityId itself, since
  // every race/checkpoint URL (_planRaceUrl) is /api/plans/{id}/races|... .
  function _loadPlanEntityId() {
    apiGet("/api/plans", function (data) {
      var plan = Array.isArray(data) && data.length > 0 ? data[0] : null;
      if (plan) _planEntityId = plan.id;
    });
  }

  // ── Render orchestration ──────────────────────────────────────────────────
  function renderAll() {
    renderRaceHeader();
    renderTimeCurve();
    renderRaceCards();
    renderFormCurve();
    renderSpecBars();
    _renderPerfProjection();
  }

  // Map the single /api/plan/computed bundle into local state, then render
  // everything from it. No per-race fan-out or separate perf/calibration/
  // projection/prefs fetches on the render path — one call feeds all of it.
  function applyBundle(bundle) {
    if (!bundle) return;
    _bundle = bundle;

    _races = Array.isArray(bundle.races) ? bundle.races : [];
    _primaryRace =
      _races.find(function (r) {
        return r.type === "race" && r.priority === "A" && r.status !== "done";
      }) ||
      _races.find(function (r) {
        return r.type === "race" && r.status !== "done";
      }) ||
      null;

    var cs = bundle.current_scores || {};
    _athletePerf =
      cs.state === "scored"
        ? {
            state: "scored",
            endurance: { score: cs.endurance, direction: cs.endurance_dir },
            speed: { score: cs.speed, direction: cs.speed_dir },
          }
        : { state: cs.state };
    _thresholdPace =
      bundle.prefs && typeof bundle.prefs.threshold_pace === "number"
        ? bundle.prefs.threshold_pace
        : null;

    var proj = bundle.projection || {};
    _projection = {
      form_curve: proj.form_curve,
      projected_form: proj.projected_form,
      race_markers: proj.race_markers,
      b_race_recalibration_date: proj.b_race_recalibration_date,
      building_baseline: proj.building_baseline,
    };
    // Primary-race readiness now rides the cached bundle (folded server-side),
    // so the tab needs no separate /api/races/{id}/readiness call. Carries the
    // full readiness (time_curve, form_curve, on_track, specificity_progress,
    // building_baseline, projected_form). Null when there is no primary race —
    // renderTimeCurve/FormCurve/SpecBars all guard on that and degrade cleanly.
    _readiness = bundle.readiness || null;

    renderCalibration(bundle.calibration || {});
    renderAll();
  }

  function refresh() {
    // _planId (user id) still drives _ensurePlanId for /api/plan/computed.
    // _planEntityId (TrainingPlan UUID) is set by _loadPlanEntityId() and
    // drives all /api/plans/{id}/races|checkpoints|projection calls.
    _ensurePlanId(function () {
      apiGet("/api/plan/computed", function (bundle) {
        applyBundle(bundle);
      });
    });
    // Independent of the computed bundle so races/checkpoints keep working
    // even if the bundle call fails.
    _loadPlanEntityId();
  }

  // Force a server-side recompute (ignores cache), then re-render. Shows a
  // brief disabled/spinning state on the Recalculate button.
  function recompute() {
    var btn = document.getElementById("plan-recalc-btn");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-loading");
    }
    apiPost("/api/plan/recompute", {}, function (res) {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("is-loading");
      }
      if (res && res.ok && res.data) applyBundle(res.data);
    });
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
    // Goal-time field: a distance-defined checkpoint takes a goal time exactly
    // like a race (pace derives from the distance); a duration-defined
    // checkpoint has no distance, so hide the goal (the duration is the target).
    if (isCheckpoint) _show("plan-modal-goal-field", !byDuration);
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

    var body;
    if (type === "checkpoint" && _checkpointMeasure === "duration") {
      // Duration-defined checkpoint (issue #1226): no distance, no goal pace.
      var durIn = document.getElementById("plan-modal-duration");
      var durSec = durIn ? parseGoalTime(durIn.value) : null;
      if (durSec === null || durSec <= 0) {
        if (errEl) errEl.textContent = "Enter a valid duration (H:MM:SS).";
        return;
      }
      body = {
        name: name, date: date, type: "checkpoint",
        duration_seconds: durSec, status: "planned",
      };
    } else {
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

      body = { name: name, date: date, distance: dist, type: type };
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
          if (res.ok) {
            refresh();
          } else {
            if (window.UIStates && UIStates.showToast)
              UIStates.showToast("Delete failed. Please try again.", true);
          }
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
          if (res.ok) {
            refresh();
          } else {
            if (window.UIStates && UIStates.showToast)
              UIStates.showToast("Delete failed. Please try again.", true);
          }
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

    // Recalculate: force a fresh server-side compute of the bundle.
    var recalcBtn = document.getElementById("plan-recalc-btn");
    if (recalcBtn) recalcBtn.addEventListener("click", recompute);

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

    var pickerCancel = document.getElementById("plan-race-picker-cancel");
    if (pickerCancel) pickerCancel.addEventListener("click", closeRacePicker);

    var pickerNewRace = document.getElementById("plan-race-picker-newrace");
    if (pickerNewRace)
      pickerNewRace.addEventListener("click", function () {
        closeRacePicker();
        openModal(null, "race");
      });

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

  // ══════════════════════════════════════════════════════════════════════════
  // Ported from the removed Performance tab (training-performance.js): score
  // cards, "what's moving your scores", personal records, and projected-at-
  // next-checkpoint. Kept close to verbatim (own fetches, own state, _perf*
  // naming) rather than integrated with this module's own bundle/_planEntityId
  // plumbing. Projected-at-next-checkpoint is the exception: it reads _races
  // directly (see _renderPerfProjection, called from renderAll) so it agrees
  // with the race cards' own estimate instead of running a separate calc.
  // The rest is fetched once per page load (_perfBooted below), not on every
  // tab-switch.
  // ══════════════════════════════════════════════════════════════════════════
  var _perfBooted = false;
  var _perfAthleteId = null;
  var _perfTz = "UTC";
  var _perfFitnessChart = null;
  var _perfActiveRange = "90D";
  var _perfContribs = { endurance: null, speed: null };
  var _perfFeedRows = { endurance: null, speed: null };
  var PERF_RANGE_DAYS = { "30D": 30, "90D": 90, "6M": 180, "1Y": 365 };
  var PERF_TREND_COLOR = { endurance: "#16a34a", speed: "#ea580c" };

  function _perfBoot() {
    if (_perfBooted) return;
    _perfBooted = true;
    var userId = window.getCurrentUserId ? window.getCurrentUserId() : null;
    function resolvePrefsAndLoad() {
      fetch("/api/user-preferences", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
          var tz = data && data.row && data.row.timezone;
          if (tz && typeof tz === "string") _perfTz = tz;
        })
        .catch(function () {})
        .then(function () {
          _loadPerfScores();
          _loadPerfFeeds();
          _loadPerfPR();
          _renderPerfProjection();
        });
    }
    if (userId) { _perfAthleteId = userId; resolvePrefsAndLoad(); }
    else {
      window.addEventListener("userReady", function (e) {
        _perfAthleteId = e.detail.userId;
        resolvePrefsAndLoad();
      }, { once: true });
    }
  }

  function _perfToday() {
    return new Date().toLocaleDateString("en-CA", { timeZone: _perfTz });
  }
  function _perfDateMinusDays(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d.toLocaleDateString("en-CA", { timeZone: _perfTz });
  }
  function _perfFmtMmmD(iso) {
    var parts = String(iso).split("-");
    if (parts.length !== 3) return iso;
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    var mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()];
    return mon + " " + d.getUTCDate();
  }
  function _perfFmtPace(secPerKm) {
    if (secPerKm == null) return null;
    var s = Math.round(secPerKm);
    var m = Math.floor(s / 60), sec = s % 60;
    return m + ":" + String(sec).padStart(2, "0") + " /km";
  }

  // ── Score cards (Endurance | Speed) ─────────────────────────────────────────
  function _loadPerfScores() {
    if (!_perfAthleteId) return;
    fetch("/api/athletes/" + _perfAthleteId + "/performance")
      .then(function (r) { return r.json().catch(function () { return null; }); })
      .then(function (data) {
        var state = data && typeof data === "object" ? data.state : null;
        if (state === "scored") {
          _renderPerfScoreCard("endurance", data.endurance);
          _renderPerfScoreCard("speed", data.speed);
          _perfContribs.endurance = (data.endurance && data.endurance.run_contributions) || null;
          _perfContribs.speed = (data.speed && data.speed.run_contributions) || null;
          if (_perfFeedRows.endurance) _renderPerfFeed("endurance", _perfFeedRows.endurance);
          if (_perfFeedRows.speed) _renderPerfFeed("speed", _perfFeedRows.speed);
          return;
        }
        if (state === "needs_thresholds") {
          _renderPerfThresholdHint("endurance");
          _renderPerfThresholdHint("speed");
          return;
        }
        if (state === "building_baseline") {
          var reason = (data && data.reason) || "Keep training: your baseline is building.";
          _renderPerfBuildingBaseline("endurance", reason);
          _renderPerfBuildingBaseline("speed", reason);
          return;
        }
        _renderPerfScoreError("endurance");
        _renderPerfScoreError("speed");
      })
      .catch(function () {
        _renderPerfScoreError("endurance");
        _renderPerfScoreError("speed");
      });
  }

  function _perfCardParts(type) {
    var card = document.getElementById("perf-score-" + type);
    if (!card) return null;
    return {
      card: card,
      body: card.querySelector(".perf-card-body"),
      score: card.querySelector(".perf-score-val"),
      insight: card.querySelector(".perf-insight"),
      spark: card.querySelector(".perf-spark"),
      bb: card.querySelector(".perf-building-baseline"),
      thresh: card.querySelector(".perf-threshold-hint"),
      error: card.querySelector(".perf-error"),
      warn: card.querySelector(".perf-speed-warn"),
    };
  }

  function _resetPerfStates(p) {
    if (p.body) p.body.style.display = "none";
    if (p.bb) p.bb.hidden = true;
    if (p.thresh) p.thresh.hidden = true;
    if (p.error) p.error.hidden = true;
    if (p.warn) p.warn.hidden = true;
  }

  function _renderPerfScoreCard(type, data) {
    var p = _perfCardParts(type);
    if (!p) return;
    _resetPerfStates(p);
    if (!data || typeof data !== "object" || data.score == null) {
      _renderPerfScoreError(type);
      return;
    }
    var score = data.score;
    var trend = Array.isArray(data.trend) ? data.trend : [];
    if (p.body) p.body.style.display = "";
    if (p.score) p.score.textContent = Math.round(score);
    if (p.insight) p.insight.textContent = _perfInsightText(trend, data.model);
    // How the score moves — constants straight from the backend model
    // payload (vdot.py), never hardcoded here.
    var modelEl = p.card.querySelector(".perf-model-line");
    if (modelEl) {
      var m = data.model;
      if (m) {
        modelEl.hidden = false;
        modelEl.textContent =
          "Score = your best " + m.top_k + " efforts (each fades −" + m.decay_per_week +
          "/wk after " + m.grace_weeks + " wk) + consistency: +" + m.consistency_bonus_per_run +
          " per session in the last " + m.consistency_window_days + " days, max +" +
          m.consistency_bonus_cap + ".";
      } else {
        modelEl.hidden = true;
      }
    }
    if (p.spark && trend.length >= 2) _drawPerfTrend(p.spark, trend, PERF_TREND_COLOR[type]);
    else if (p.spark) p.spark.innerHTML = "";
    if (p.warn) p.warn.hidden = data.low_data_warning !== true;
  }

  function _perfTrendDelta(trend) {
    if (!Array.isArray(trend) || trend.length < 2) return null;
    var first = trend[0], last = trend[trend.length - 1];
    if (first == null || last == null) return null;
    return Math.round(last - first);
  }

  // By construction of the score model (decayed top-K mean + consistency
  // bonus), a run can never LOWER the score — any decline is time decay
  // between peak efforts (or the consistency window emptying), and any rise
  // means new efforts entered the top-K or the consistency bonus grew. Say
  // WHICH, with the actual decay rate from the model payload.
  function _perfInsightText(trend, model) {
    var delta = _perfTrendDelta(trend);
    var rate = model && model.decay_per_week != null ? model.decay_per_week : null;
    if (delta === null) return "Holding steady.";
    if (delta < 0) {
      return "Down " + Math.abs(delta) + " over this window — time decay between peak efforts" +
        (rate != null ? " (−" + rate + "/wk per anchor effort)" : "") + ", not any single run.";
    }
    if (delta > 0) {
      return "Up " + delta + " over this window — newer efforts and steady training.";
    }
    return "Holding steady over this window.";
  }

  function _drawPerfTrend(svg, pts, color) {
    var W = 340, H = 56;
    var mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = "";
    var P2 = pts.map(function (v, i) {
      return [i / (pts.length - 1) * W, H - (v - mn) / (mx - mn + 0.001) * (H - 10) - 5];
    });
    var d = P2.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
    svg.appendChild(E("path", { d: d, fill: "none", stroke: color, "stroke-width": 2.2, "stroke-linejoin": "round" }));
    var last = P2[P2.length - 1];
    svg.appendChild(E("circle", { cx: last[0], cy: last[1], r: 3.5, fill: color }));
  }

  function _renderPerfThresholdHint(type) {
    var p = _perfCardParts(type);
    if (!p) return;
    _resetPerfStates(p);
    if (p.thresh) p.thresh.hidden = false;
    _emptyPerfFeed(type, "Set thresholds to see the sessions feeding this score.");
  }
  function _renderPerfBuildingBaseline(type, reason) {
    var p = _perfCardParts(type);
    if (!p) return;
    _resetPerfStates(p);
    if (p.bb) { p.bb.hidden = false; var r = p.bb.querySelector(".perf-bb-reason"); if (r) r.textContent = reason; }
  }
  function _renderPerfScoreError(type) {
    var p = _perfCardParts(type);
    if (!p) return;
    _resetPerfStates(p);
    if (p.error) p.error.hidden = false;
  }

  // ── Feeding lists ────────────────────────────────────────────────────────
  function _emptyPerfFeed(type, msg) {
    var host = document.getElementById("perf-feed-" + type);
    if (host) host.innerHTML = '<p class="perf-feed-empty">' + esc(msg) + "</p>";
  }
  function _loadPerfFeeds() {
    if (!_perfAthleteId) return;
    var from = _perfDateMinusDays(120), to = _perfToday();
    fetch("/api/training-log?from=" + from + "&to=" + to + "&include_rest=false", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var entries = _flattenPerfEntries(data);
        _renderPerfFeed("endurance", _pickPerfEndurance(entries));
        _renderPerfFeed("speed", _pickPerfSpeed(entries));
      })
      .catch(function () {
        _emptyPerfFeed("endurance", "Could not load recent sessions.");
        _emptyPerfFeed("speed", "Could not load recent sessions.");
      });
  }
  function _flattenPerfEntries(data) {
    var out = [];
    ((data && data.weeks) || []).forEach(function (wk) {
      (wk.entries || wk.workouts || []).forEach(function (e) { if (e && e.type !== "rest") out.push(e); });
    });
    out.sort(function (a, b) { return (a.date < b.date) ? 1 : (a.date > b.date ? -1 : 0); });
    return out;
  }
  function _pickPerfEndurance(entries) {
    var runs = entries.filter(function (e) {
      var t = (e.type || "").toLowerCase();
      return (t === "run" || t === "long_run" || t === "longrun") && (e.distance_km || 0) >= 8;
    });
    if (!runs.length) runs = entries.filter(function (e) { return (e.type || "").toLowerCase().indexOf("run") !== -1; });
    return runs.slice(0, 5);
  }
  function _isPerfInterval(e) {
    if ((e.run_subtype || "").toLowerCase() === "interval") return true;
    var t = (e.type || "").toLowerCase();
    return t === "workout" || t === "track" || t === "tempo";
  }
  function _pickPerfSpeed(entries) { return entries.filter(_isPerfInterval).slice(0, 5); }

  function _renderPerfFeed(type, rows) {
    _perfFeedRows[type] = rows;
    var host = document.getElementById("perf-feed-" + type);
    if (!host) return;
    if (!rows.length) {
      _emptyPerfFeed(type, type === "endurance" ? "No long runs in the last 120 days." : "No interval sessions in the last 120 days.");
      return;
    }
    var contribMap = _perfContribs[type] || null;
    host.innerHTML = rows.map(function (w) {
      var meta = [];
      if (w.distance_km != null) meta.push(w.distance_km.toFixed(1) + " km");
      var pace = _perfFmtPace(w.average_pace_seconds_per_km);
      if (pace) meta.push(pace);
      if (w.avg_hr != null) meta.push("HR " + w.avg_hr);
      var src = w.has_stryd ? "st" : (w.has_strava ? "s" : "");
      var srcHtml = src ? '<span class="perf-src perf-src--' + src + '">' + (src === "s" ? "S" : "St") + "</span>" : "";
      // Marginal contribution to the CURRENT score, keyed by workout id
      // (run_contributions — the single source shared with the workout-detail
      // panel). A session with no entry didn't qualify for this score at all
      // → honest 0.0, never a raw-TSS fallback.
      var contrib = (contribMap && w.id != null) ? contribMap[String(w.id)] : undefined;
      var n = (typeof contrib === "number") ? Math.round(contrib * 10) / 10 : 0;
      var cls = n > 0 ? "up" : (n < 0 ? "down" : "flat");
      var txt = (n > 0 ? "+" : "") + n.toFixed(1);
      var chipHtml = '<span class="perf-dchip perf-dchip--' + cls + '" title="contribution to ' + type + ' score">' + txt + "</span>";
      var href = "/log?workout=" + encodeURIComponent(w.id);
      return '<a class="perf-frow" href="' + href + '">' +
        '<span class="perf-fdate">' + esc(_perfFmtMmmD(w.date)) + "</span>" +
        '<span class="perf-fmain">' +
          '<span class="perf-fn">' + esc(w.title || "Workout") + "</span>" +
          '<span class="perf-fm">' + esc(meta.join(" · ") || "—") + "</span>" +
        "</span>" + srcHtml + chipHtml +
        '<span class="perf-farr">→</span>' +
      "</a>";
    }).join("");
  }

  // ── Projected at next checkpoint ─────────────────────────────────────────────
  // Reads _races directly (already loaded by applyBundle()) instead of its own
  // /api/plans/{id}/projection fetch — that endpoint runs a SEPARATE, less-
  // integrated estimate model (score_to_estimated_finish_time off a flat
  // projected-load assumption) that disagreed with the authoritative one every
  // race card already shows (r.computed.estimate, from _race_readiness_impl's
  // time_curve — the same engine behind the time-curve chart at the top of
  // this tab). Reported live: this card said 2:15:11 while the SAME race's
  // card below said 2:30:42. Fixed by sourcing both from the one estimate.
  var RIEGEL_EXPONENT = 1.06; // backend/services/riegel.py — single source of truth
  function _renderPerfProjection() {
    var body = document.getElementById("perf-proj-body");
    var empty = document.getElementById("perf-proj-empty");
    var metaEl = document.getElementById("perf-proj-meta");
    var endEl = document.getElementById("perf-proj-endurance");
    var spdEl = document.getElementById("perf-proj-speed");
    if (!body && !empty) return;

    var todayStr = todayISO();
    var upcoming = _races
      .filter(function (r) { return r.date && r.date >= todayStr && r.status !== "done"; })
      .sort(function (a, b) { return a.date < b.date ? -1 : (a.date > b.date ? 1 : 0); });
    var next = upcoming.length ? upcoming[0] : null;
    var est = next && next.computed && next.computed.estimate;

    if (!next || !est || est.est == null) {
      if (body) body.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;
    if (metaEl) metaEl.textContent = (next.name || "Checkpoint") + " · " + formatDate(next.date);
    if (endEl) {
      endEl.innerHTML = esc(fmtTime(est.est));
      var tile = endEl.closest(".perf-projtile");
      var lbl = tile ? tile.querySelector(".perf-projtile-l") : null;
      if (lbl) lbl.textContent = "Est. finish";
    }
    if (spdEl) {
      var halfSeconds = Math.round(est.est * Math.pow(0.5, RIEGEL_EXPONENT));
      spdEl.innerHTML = esc(fmtTime(halfSeconds));
      var tile2 = spdEl.closest(".perf-projtile");
      var lbl2 = tile2 ? tile2.querySelector(".perf-projtile-l") : null;
      if (lbl2) lbl2.textContent = "Half equiv.";
    }
  }

  // ── Personal records grid ───────────────────────────────────────────────────
  var PERF_PR_LABELS = {
    longestByDistance: "Longest run (km)", longestByDuration: "Longest run (time)",
    weeklyDistanceRecord: "Best week (km)", weeklyLoadRecord: "Best week (TSS)",
    "1km": "Best 1 km", "1mile": "Best 1 mile", "5km": "Best 5 km", "10km": "Best 10 km",
    half_marathon: "Best half marathon", marathon: "Best marathon",
    best1Min: "Best 1-min power", best5Min: "Best 5-min power", best20Min: "Best 20-min power",
  };
  function _loadPerfPR() {
    if (!_perfAthleteId) return;
    fetch("/api/athletes/" + _perfAthleteId + "/run-personal-records")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) { _renderPerfPR(data); })
      .catch(function () { _renderPerfPR(null); });
  }
  function _renderPerfPR(data) {
    var strip = document.getElementById("perf-pr-strip");
    if (!strip) return;
    if (!data) { strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>'; return; }
    var items = [];
    [
      { key: "volumeRecords", keys: ["longestByDistance", "longestByDuration", "weeklyDistanceRecord", "weeklyLoadRecord"] },
      { key: "speedRecords", keys: ["5km", "10km", "half_marathon", "marathon", "1mile", "1km"] },
      { key: "powerRecords", keys: ["best20Min", "best5Min", "best1Min"] },
    ].forEach(function (cat) {
      var group = data[cat.key];
      if (!group || typeof group !== "object" || group.reason) return;
      cat.keys.forEach(function (k) {
        var rec = group[k];
        if (rec && typeof rec === "object") items.push({ label: k, rec: rec });
      });
    });
    if (!items.length) { strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>'; return; }
    strip.innerHTML = items.map(function (item) {
      var label = PERF_PR_LABELS[item.label] || item.label;
      var rec = item.rec;
      if (rec.reason) {
        return '<div class="perf-prtile perf-prtile--unavailable">' +
          '<div class="perf-pr-name">' + esc(label) + "</div>" +
          '<div class="perf-pr-reason">' + esc(rec.reason) + "</div></div>";
      }
      var v = _formatPerfPrValue(item.label, rec.value);
      var date = rec.date || "—";
      var src = rec.sourceWorkout && rec.sourceWorkout.id
        ? '<a class="perf-pr-link" href="/log?workout=' + esc(String(rec.sourceWorkout.id)) + '">View workout</a>'
        : "";
      return '<div class="perf-prtile">' +
        '<div class="perf-pr-name">' + esc(label) + "</div>" +
        '<div class="perf-pr-val">' + v + "</div>" +
        '<div class="perf-pr-date">' + esc(date) + "</div>" + src + "</div>";
    }).join("");
  }
  function _formatPerfPrValue(key, value) {
    if (value == null) return "—";
    var timeKeys = ["5km", "10km", "half_marathon", "marathon", "1km", "1mile", "longestByDuration"];
    if (timeKeys.indexOf(key) !== -1) {
      var s = Math.round(value);
      var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      if (h > 0) return h + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
      return m + ":" + String(sec).padStart(2, "0");
    }
    if (key === "best1Min" || key === "best5Min" || key === "best20Min") return Math.round(value) + "<small> W</small>";
    if (key === "longestByDistance" || key === "weeklyDistanceRecord") return parseFloat(value).toFixed(1) + "<small> km</small>";
    if (key === "weeklyLoadRecord") return Math.round(value) + "<small> TSS</small>";
    return esc(String(value));
  }

  // ── Public init ───────────────────────────────────────────────────────────
  function init() {
    if (!_initialized) {
      _initialized = true;
      wireEvents();
      _perfBoot();
      document.querySelectorAll(".perf-retry-btn").forEach(function (btn) {
        btn.addEventListener("click", function () { _loadPerfScores(); });
      });
    }
    refresh();
  }

  // Redraw both charts on viewport resize / rotation so they adapt (they're
  // drawn once on load otherwise). Debounced ~150ms; both fns guard internally
  // (they return early when their SVG or data is missing), and each call is
  // wrapped so a not-yet-loaded chart can't break the other.
  var _resizeTimer = null;
  window.addEventListener("resize", function () {
    if (_resizeTimer) clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(function () {
      try { renderTimeCurve(); } catch (e) {}
      try { renderFormCurve(); } catch (e) {}
    }, 150);
  });

  window.TrainingPerformance = { init: init };
})();
