(function () {
  "use strict";

  // Shared format helpers (issue #531) — single home for type normalization,
  // pace/duration formatting, and segment definitions. training-log.html loads
  // lib/training-format.js before this script.
  var TF = window.TrainingFormat;

  // ── State ─────────────────────────────────────────────────────────────────
  var filters = { type: "all", search: "", from: "", to: "" };
  var lastWeeks = [];
  var flatWorkouts = []; // ordered array of { id, title, type } for navigation
  var activePosIndex = -1; // position in flatWorkouts of open workout
  var activeDetailWorkoutId = null;
  var activeTriggerEl = null;
  var activeRowEl = null;
  var panelMode = "view"; // 'view' | 'edit' | 'create'
  var cachedDetailWorkout = null;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function todayISO() {
    var d = new Date();
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
    );
  }

  function addDays(iso, n) {
    var d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + n);
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
    );
  }

  var MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  var DAY_ABBR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function csvField(val) {
    var s = val == null ? "" : String(val);
    if (
      s.indexOf(",") !== -1 ||
      s.indexOf('"') !== -1 ||
      s.indexOf("\n") !== -1 ||
      s.indexOf("\r") !== -1
    ) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }

  // issue #531: empty for falsy/non-positive, else the shared h:mm:ss/m:ss form.
  function fmtDurationRow(secs) {
    if (!secs || secs <= 0) return "";
    return TF.formatDuration(secs);
  }

  function fmtTotalTime(totalMinutes) {
    if (!totalMinutes || totalMinutes <= 0) return "";
    var h = Math.floor(totalMinutes / 60);
    var m = Math.round(totalMinutes % 60);
    return h + ":" + pad(m);
  }

  function fmtDuration(secs) {
    if (!secs) return "";
    var h = Math.floor(secs / 3600),
      m = Math.floor((secs % 3600) / 60);
    if (h > 0 && m > 0) return h + "h " + m + "min";
    if (h > 0) return h + "h";
    return m + "min";
  }

  // issue #531: render an already-computed seconds-per-km via the shared
  // pace formatter; '' keeps the prior empty-input behavior.
  function fmtPace(secsPerKm) {
    var core = TF.formatPace(secsPerKm, 1);
    return core ? core + " /km" : "";
  }

  function fmtShortDate(isoStr) {
    var d = new Date(isoStr + "T00:00:00");
    return d.getDate() + " " + MONTHS[d.getMonth()];
  }

  // issue #531: shared h:mm:ss/m:ss formatter; '—' for missing values.
  function fmtDurationDetail(secs) {
    return secs == null ? "—" : TF.formatDuration(secs);
  }

  // issue #531: compute seconds-per-km here (the #118 contract), then render
  // the m:ss part via the shared pace formatter; '—' when inputs are missing.
  function fmtPaceFromSec(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return "—";
    var secsPerKm = durSeconds / distKm;
    var core = TF.formatPace(secsPerKm, 1);
    return core ? core + " /km" : "—";
  }

  function fmtSpeedKmh(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return "—";
    var speed = distKm / (durSeconds / 3600);
    return speed.toFixed(1) + " km/h";
  }

  // issue #526: parse a user-entered split duration ("m:ss" or "h:mm:ss") into
  // whole seconds. Returns null for any malformed value so the manual split
  // editor can surface a field-level "valid duration format" error before it
  // ever calls the splits endpoint. Plain "0:00" parses to 0 (caller rejects
  // non-positive durations separately).
  function parseDurationStr(str) {
    if (str == null) return null;
    var t = String(str).trim();
    if (!/^\d{1,3}(:\d{1,2}){1,2}$/.test(t)) return null;
    var parts = t.split(":").map(Number);
    var h = 0,
      m,
      s;
    if (parts.length === 3) {
      h = parts[0];
      m = parts[1];
      s = parts[2];
    } else {
      m = parts[0];
      s = parts[1];
    }
    if (m > 59 || s > 59) return null;
    return h * 3600 + m * 60 + s;
  }

  // Map free-text workout_type values onto canonical keys (issue #531: the
  // shared normalizer, so the log and the editor detect runs identically).
  var normalizeTypeKey = TF.normalizeType;

  // Segment label → intensity key (timeline colors + segment dots), derived
  // from the shared segment definitions (issue #531).
  var RUN_SEGMENT_INTENSITY = TF.segmentIntensityByLabel;
  var RUN_SEGMENT_LABELS = RUN_SEGMENT_INTENSITY; // truthy lookup by label

  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    return (
      DAY_ABBR[d.getDay()] + ", " + MONTHS[d.getMonth()] + " " + d.getDate()
    );
  }

  function em() {
    return "—";
  }

  // ── URL sync ──────────────────────────────────────────────────────────────
  function readURLParams() {
    var p = new URLSearchParams(window.location.search);
    filters.type = p.get("type") || "all";
    filters.search = p.get("search") || "";
    filters.from = p.get("from") || "";
    filters.to = p.get("to") || "";
  }

  function writeURLParams() {
    var p = new URLSearchParams(window.location.search);
    if (filters.type && filters.type !== "all") p.set("type", filters.type);
    else p.delete("type");
    if (filters.search) p.set("search", filters.search);
    else p.delete("search");
    if (filters.from) p.set("from", filters.from);
    else p.delete("from");
    if (filters.to) p.set("to", filters.to);
    else p.delete("to");
    var qs = p.toString();
    history.replaceState(
      null,
      "",
      window.location.pathname + (qs ? "?" + qs : ""),
    );
  }

  // ── Deep-link helpers ─────────────────────────────────────────────────────
  // Set/clear ?workout=<id> in the URL without disturbing other params.
  function setWorkoutURLParam(workoutId) {
    var p = new URLSearchParams(window.location.search);
    p.set("workout", workoutId);
    history.replaceState(null, "", window.location.pathname + "?" + p.toString());
  }

  function clearWorkoutURLParam() {
    var p = new URLSearchParams(window.location.search);
    p.delete("workout");
    var qs = p.toString();
    history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
  }

  // Called once after the first successful fetchAndRender — opens the panel
  // for ?workout=<id> if present.  The flag prevents re-triggering on
  // subsequent list refreshes (sync, edit, etc.).
  var _deepLinkHandled = false;
  function handleDeepLink() {
    if (_deepLinkHandled) return;
    var wid = new URLSearchParams(window.location.search).get("workout");
    if (!wid) return;
    _deepLinkHandled = true;
    openDetailPanel(wid, null);
  }

  // ── Date-range chip label ─────────────────────────────────────────────────
  function drLabel() {
    if (filters.from && filters.to) return filters.from + " – " + filters.to;
    if (filters.from) return "From " + filters.from;
    if (filters.to) return "To " + filters.to;
    return "Last 30 days";
  }

  // ── Header stats subtitle ─────────────────────────────────────────────────
  function updateHeaderStats(data) {
    var subtitleEl = document.getElementById("log-subtitle");
    if (!subtitleEl) return;
    var weeks = data.weeks || [];
    var totalCount = 0,
      totalTSS = 0,
      totalMinutes = 0;
    weeks.forEach(function (week) {
      var s = week.summary || {};
      totalCount += s.workout_count || 0;
      totalTSS += s.total_tss || 0;
      totalMinutes += s.total_time_minutes || 0;
    });
    // Total TSS / total hours intentionally hidden — keep just the count.
    var parts = [totalCount + " workout" + (totalCount !== 1 ? "s" : "")];
    subtitleEl.textContent = parts.join(" · ");
  }

  // ── Build filter bar (issue #637: type pills + search, client-side) ─────────
  function buildFilterBar() {
    var bar = document.getElementById("filter-bar");
    if (!bar) return;

    // Type pills row — All / Run / Lift (WOD and Bike disabled for now)
    var chipsRow = document.createElement('div');
    chipsRow.className = 'fb-chips-row';
    var TYPE_OPTS   = ['all','run','lift'];
    var TYPE_LABELS = { all:'All', run:'Run', lift:'Lift', wod:'WOD', bike:'Bike' };
    // A stale ?type=wod/bike URL would filter to a now-hidden pill — fall back to All.
    if (TYPE_OPTS.indexOf(filters.type) === -1) filters.type = 'all';
    TYPE_OPTS.forEach(function (t) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "type-chip" + (t === filters.type ? " active" : "");
      chip.dataset.type = t;
      chip.textContent = TYPE_LABELS[t];
      chip.addEventListener("click", function () {
        filters.type = t;
        document.querySelectorAll(".type-chip").forEach(function (c) {
          c.classList.toggle("active", c.dataset.type === t);
        });
        writeURLParams();
        applyClientFilter();
      });
      chipsRow.appendChild(chip);
    });
    bar.appendChild(chipsRow);

    // Search field
    var searchWrap = document.createElement('div');
    searchWrap.className = 'fb-search-wrap';
    var searchInner = document.createElement('div');
    searchInner.className = 'fb-search';
    var searchIcon = document.createElement('i');
    searchIcon.className = 'ti ti-search';
    searchIcon.setAttribute('aria-hidden', 'true');
    searchInner.appendChild(searchIcon);
    var searchInput = document.createElement('input');
    searchInput.type         = 'search';
    searchInput.id           = 'log-search';
    searchInput.placeholder  = 'Search workouts';
    searchInput.setAttribute('aria-label', 'Search workouts');
    searchInput.value        = filters.search;
    searchInput.spellcheck   = false;
    searchInput.autocomplete = 'off';
    searchInner.appendChild(searchInput);
    searchWrap.appendChild(searchInner);
    bar.appendChild(searchWrap);

    var loadingEl = document.createElement("span");
    loadingEl.id = "log-loading-indicator";
    loadingEl.className = "log-loading-indicator";
    loadingEl.hidden = true;
    loadingEl.setAttribute("role", "status");
    loadingEl.setAttribute("aria-live", "polite");
    loadingEl.textContent = "Loading…";
    bar.appendChild(loadingEl);

    var searchTimer;
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        filters.search = searchInput.value;
        writeURLParams();
        applyClientFilter();
      }, 200);
    });
  }

  // ── Client-side filter (issue #637) ──────────────────────────────────────
  function applyClientFilter() {
    var typeKey    = (filters.type || 'all').toLowerCase();
    var searchTerm = (filters.search || '').toLowerCase().trim();
    var anyVisible = false;

    document.querySelectorAll('.day-group').forEach(function (group) {
      var groupHasVisible = false;
      group.querySelectorAll('.entry-row').forEach(function (row) {
        var matchesType = typeKey === 'all' ||
          (row.dataset.workoutType || '').toLowerCase() === typeKey;
        var matchesSearch = !searchTerm ||
          (row.dataset.workoutTitle || '').toLowerCase().indexOf(searchTerm) !== -1;
        var visible = matchesType && matchesSearch;
        row.style.display = visible ? '' : 'none';
        if (visible) groupHasVisible = true;
      });
      group.style.display = groupHasVisible ? '' : 'none';
      if (groupHasVisible) anyVisible = true;
    });

    var filterEmpty = document.getElementById('log-empty-filter');
    var mainEmpty   = document.getElementById('log-empty-msg');
    var listEl      = document.getElementById('log-list');
    var hasAnyRows  = listEl && listEl.querySelector('.entry-row') !== null;

    if (filterEmpty) {
      filterEmpty.style.display = (hasAnyRows && !anyVisible) ? '' : 'none';
    }
    if (mainEmpty) {
      mainEmpty.style.display = (!hasAnyRows && !anyVisible) ? '' : 'none';
    }
  }

  // ── List state helpers ────────────────────────────────────────────────────
  function hideListMessages() {
    var errEl = document.getElementById("log-error-msg");
    var emptyEl = document.getElementById("log-empty-msg");
    if (errEl) errEl.style.display = "none";
    if (emptyEl) emptyEl.style.display = "none";
  }

  function showListSkeleton() {
    var listEl = document.getElementById("log-list");
    if (!listEl) return;
    var html = "";
    for (var i = 0; i < 5; i++) {
      html += '<div class="skeleton-row"></div>';
    }
    listEl.innerHTML = html;
  }

  function renderListError() {
    var listEl = document.getElementById("log-list");
    var errEl = document.getElementById("log-error-msg");
    if (listEl) listEl.innerHTML = "";
    if (errEl) errEl.style.display = "";
  }

  // ── Flat workout list (for prev/next navigation) ──────────────────────────
  function buildFlatWorkouts() {
    flatWorkouts = [];
    lastWeeks.forEach(function (week) {
      var entries = (week.entries || []).slice().sort(function (a, b) {
        return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
      });
      entries.forEach(function (entry) {
        if (entry.type !== "rest" && entry.id) {
          flatWorkouts.push({
            id: entry.id,
            title: entry.title || "Workout",
            type: entry.type,
          });
        }
      });
    });
  }

  // ── In-memory single-workout patch (perf/hot-paths Task 4) ─────────────────
  // Edit/delete mutations return the updated workout dict (or need no body for
  // delete); patch lastWeeks directly instead of re-fetching the full history.
  // Field names mirror GET /api/training-log's per-entry shape (main.py's
  // workout_entries list comprehension), which differs from the workout
  // detail dict returned by PATCH/POST (workout_type vs type, name vs title,
  // workout_date vs date).
  function _paceSecPerKm(type, durationSeconds, distanceKm) {
    var t = (type || "").toLowerCase().trim();
    var isPaced =
      t === "run" || t === "running" || t === "race" ||
      t.indexOf("bike") === 0 || t.indexOf("ride") === 0 || t.indexOf("cycl") === 0;
    if (!isPaced) return null;
    if (durationSeconds == null || distanceKm == null || +distanceKm === 0) return null;
    return Math.round((durationSeconds / distanceKm) * 100) / 100;
  }

  function _workoutDictToEntry(w) {
    var source = w.source || w.tss_source || "manual";
    return {
      date: w.workout_date,
      type: w.workout_type,
      id: w.id,
      title: w.name,
      duration_seconds: w.duration_seconds,
      duration_minutes:
        w.duration_seconds != null ? Math.round((w.duration_seconds / 60) * 100) / 100 : null,
      distance_km: w.distance_km != null ? w.distance_km : null,
      avg_hr: w.avg_hr,
      elevation_m: w.elevation_m,
      average_pace_seconds_per_km: _paceSecPerKm(w.workout_type, w.duration_seconds, w.distance_km),
      tss: w.tss != null ? w.tss : null,
      source: source,
      strava_activity_url: w.strava_activity_url,
      is_stryd_synced: !!w.stryd_activity_pk,
      has_strava: source.indexOf("strava") !== -1 || !!w.strava_activity_pk,
      has_stryd: source.indexOf("stryd") !== -1 || !!w.stryd_activity_pk,
      notes: w.remarks || "",
      weight_context: w.remarks,
    };
  }

  // Replace an existing entry's fields in place. Returns false (caller should
  // fall back to fetchAndRender()) if the workout isn't in the loaded weeks —
  // this only handles edits to already-visible workouts, not new ones that
  // may need a new week bucket.
  function patchWorkoutInPlace(workoutDict) {
    if (!workoutDict || !workoutDict.id) return false;
    for (var wi = 0; wi < lastWeeks.length; wi++) {
      var week = lastWeeks[wi];
      var entries = week.entries || [];
      for (var ei = 0; ei < entries.length; ei++) {
        if (entries[ei].id === workoutDict.id) {
          var newEntry = _workoutDictToEntry(workoutDict);
          entries[ei] = newEntry;
          var workouts = week.workouts || [];
          for (var wj = 0; wj < workouts.length; wj++) {
            if (workouts[wj].id === workoutDict.id) {
              workouts[wj] = newEntry;
              break;
            }
          }
          return true;
        }
      }
    }
    return false;
  }

  // Remove an entry in place (workout delete). Returns false if not found.
  function removeWorkoutInPlace(workoutId) {
    for (var wi = 0; wi < lastWeeks.length; wi++) {
      var week = lastWeeks[wi];
      var entries = week.entries || [];
      var found = false;
      for (var ei = 0; ei < entries.length; ei++) {
        if (entries[ei].id === workoutId) {
          entries.splice(ei, 1);
          found = true;
          break;
        }
      }
      if (found) {
        var workouts = week.workouts || [];
        for (var wj = 0; wj < workouts.length; wj++) {
          if (workouts[wj].id === workoutId) {
            workouts.splice(wj, 1);
            break;
          }
        }
        return true;
      }
    }
    return false;
  }

  // Re-render the list from the in-memory lastWeeks without re-fetching.
  // Deliberately skips renderVolumeChart()/updateHeaderStats()/updateCalendar()/
  // fetchReadinessWidget() — those depend on server-computed aggregates a
  // single-workout patch can't cheaply reproduce; they refresh on the next
  // full fetchAndRender() (sync completion, restore, or page load).
  function rerenderListInPlace() {
    buildFlatWorkouts();
    var listEl = document.getElementById("log-list");
    renderList(listEl, lastWeeks);
    applyClientFilter();
    if (activeDetailWorkoutId) {
      activePosIndex = findPosIndex(activeDetailWorkoutId);
      syncActiveRow();
      updatePositionPill();
    }
  }

  // ── Fetch & render ────────────────────────────────────────────────────────
  // issue #637: load full history (from 2010-01-01 to today); filtering is
  // client-side via applyClientFilter() so no type/search params are sent.
  function fetchAndRender() {
    var loadingEl = document.getElementById("log-loading-indicator");
    if (loadingEl) loadingEl.hidden = false;

    hideListMessages();
    showListSkeleton();

    var today = todayISO();
    var params = new URLSearchParams();

    params.set('from', '2010-01-01');
    params.set('to',   today);
    params.set('include_rest', 'false');
    // issue #528: pull CTL/ATL/TSB on the SAME request as the list so the
    // readiness widget is fed from one computation (no duplicate load_context).
    params.set("include_load_context", "true");

    fetch("/api/training-log?" + params.toString())
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        lastWeeks = data.weeks || [];
        buildFlatWorkouts();
        var listEl = document.getElementById("log-list");
        renderList(listEl, lastWeeks);
        updateHeaderStats(data);
        // issue #528: volume chart re-renders on every fetch; readiness is #640 widget only.
        renderVolumeChart();
        // issue #638: update month calendar with newly loaded data
        updateCalendar();
        // Apply current type/search client filter after rendering
        applyClientFilter();
        fetchReadinessWidget();
        // Re-sync active row highlight if panel is still open
        if (activeDetailWorkoutId) {
          activePosIndex = findPosIndex(activeDetailWorkoutId);
          syncActiveRow();
          updatePositionPill();
        }
        // Open ?workout=<id> deep link on first load
        handleDeepLink();
      })
      .catch(function (_) {
        renderListError();
      })
      .finally(function () {
        if (loadingEl) loadingEl.hidden = true;
      });
  }

  // ── Training-load surfaces (issue #528) ─────────────────────────────────────
  var volumeChart = null;
  var _lastReadinessData = null;

  // The readiness sparklines are <canvas> elements sized to their container's
  // pixel width at render time, and the volume chart is a Chart.js canvas.
  // When the detail panel opens/closes on desktop it resizes the left column,
  // so re-draw both at the new width (after the grid has settled).
  function reflowPanelCharts() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (_lastReadinessData) renderReadinessWidget(_lastReadinessData);
        if (volumeChart && typeof volumeChart.resize === "function") volumeChart.resize();
      });
    });
  }

  function fmtLoadNum(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return String(Math.round(v * 10) / 10);
  }

  // Legacy load-widget (#528): superseded by readiness-widget (#640). Keep hidden.
  function renderLoadWidget(lc) {
    var el = document.getElementById("load-widget");
    if (el) el.hidden = true;
  }

  // ── Readiness widget (issue #697) ────────────────────────────────────────────
  // Fetches /api/readiness and renders Fitness/Fatigue/Freshness tiles
  // with a readiness label and per-metric sparklines. Hidden on error.

  function _renderSparkline(id, vals, color) {
    var canvas = document.getElementById(id);
    if (!canvas || !vals || !vals.length) return;

    var wrap = canvas.parentElement;
    var width = Math.max((wrap && wrap.clientWidth) || canvas.clientWidth || 80, 40);
    var height = 28;
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';

    var nums = vals.map(function (v) {
      return v == null ? null : Number(v);
    }).filter(function (v) { return v !== null && isFinite(v); });
    if (nums.length < 2) return;

    var min = Math.min.apply(null, nums);
    var max = Math.max.apply(null, nums);
    if (min === max) {
      min -= 1;
      max += 1;
    }

    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    var padX = 1;
    var padY = 2;
    var usableW = width - padX * 2;
    var usableH = height - padY * 2;
    var started = false;

    vals.forEach(function (v, i) {
      var n = v == null ? null : Number(v);
      if (n === null || !isFinite(n)) return;
      var x = padX + (i / Math.max(vals.length - 1, 1)) * usableW;
      var y = padY + usableH - ((n - min) / (max - min)) * usableH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });

    if (started) ctx.stroke();
  }

  // Readiness zone bar: three named zones + a marker at the current value, so
  // you can read good/normal/caution at a glance. TSB uses the established form
  // zones (Fatigued < -10 · Optimal -10..+5 · Fresh >= +5); CTL/ATL are zoned
  // relative to the athlete's own recent range (low / mid / high third).
  var RW_AMBER = '#f59e0b', RW_BLUE = '#3b82f6', RW_GREEN = '#22c55e';

  function _zoneBarHtml(metric, val, series) {
    if (val == null || isNaN(val)) return '';
    var segs, lo, hi, name, color;

    if (metric === 'tsb') {
      lo = -30; hi = 25;
      var b1 = -10, b2 = 5;  // FORM_BURIED_CEILING / FORM_FRESH_FLOOR
      segs = [
        { w: b1 - lo, c: RW_AMBER },   // Fatigued
        { w: b2 - b1, c: RW_GREEN },   // Optimal
        { w: hi - b2, c: RW_BLUE },    // Fresh
      ];
      if (val < b1) { name = 'Fatigued'; color = RW_AMBER; }
      else if (val < b2) { name = 'Optimal'; color = RW_GREEN; }
      else { name = 'Fresh'; color = RW_BLUE; }
    } else {
      var vals = (series || []).map(function (d) { return d[metric]; })
        .filter(function (v) { return v != null && !isNaN(v); });
      lo = vals.length ? Math.min.apply(null, vals) : val;
      hi = vals.length ? Math.max.apply(null, vals) : val;
      if (!(hi - lo > 1e-6)) {                    // flat/empty → pad around value
        var pad = Math.max(5, Math.abs(val) * 0.3);
        lo = val - pad; hi = val + pad;
      }
      var t1 = lo + (hi - lo) / 3, t2 = lo + 2 * (hi - lo) / 3;
      var third = (hi - lo) / 3;
      var labels, colors;
      if (metric === 'ctl') {            // higher = fitter → top third is best
        labels = ['Low', 'Building', 'Strong'];
        colors = [RW_AMBER, RW_BLUE, RW_GREEN];
      } else {                           // atl: lower = more recovered
        labels = ['Light', 'Moderate', 'High'];
        colors = [RW_GREEN, RW_BLUE, RW_AMBER];
      }
      segs = [
        { w: third, c: colors[0] },
        { w: third, c: colors[1] },
        { w: third, c: colors[2] },
      ];
      var idx = val < t1 ? 0 : val < t2 ? 1 : 2;
      name = labels[idx]; color = colors[idx];
    }

    var span = (hi - lo) || 1;
    var markerPct = Math.max(0, Math.min(100, (val - lo) / span * 100));
    var bar = segs.map(function (s) {
      return '<span style="width:' + (s.w / span * 100).toFixed(2) + '%;background:' + s.c + '"></span>';
    }).join('');
    return '<div class="rw-zone">' +
             '<div class="rw-zone-bar">' + bar +
               '<i class="rw-zone-mark" style="left:' + markerPct.toFixed(1) + '%"></i></div>' +
             '<div class="rw-zone-name" style="color:' + color + '">' + name + '</div>' +
           '</div>';
  }

  // Draw a small SVG trend line into an <svg> element from a numeric series.
  function _lrxTrendLine(svgId, pts, color) {
    var svg = document.getElementById(svgId);
    if (!svg || !pts || pts.length < 2) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 120, H = 52;
    var mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
    var d = pts
      .map(function (v, i) {
        var x = (i / (pts.length - 1)) * W;
        var y = H - ((v - mn) / (mx - mn + 0.001)) * (H - 6) - 3;
        return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      })
      .join(" ");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    var NS = "http://www.w3.org/2000/svg";
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "1.8");
    svg.appendChild(path);
  }

  // Readiness band model: [min,max] for marker placement + status thresholds.
  // First-pass ranges (tunable): CTL/ATL 0–60, TSB −25..+15.
  function _lrxReadStatus(metric, v) {
    if (metric === "ctl") {
      if (v < 20) return { word: "DETRAINING", color: "var(--lrx-amber)" };
      if (v < 40) return { word: "STEADY", color: "var(--lrx-lavHi)" };
      return { word: "STRONG", color: "var(--lrx-green)" };
    }
    if (metric === "atl") {
      if (v < 25) return { word: "LOW", color: "var(--lrx-green)" };
      if (v < 45) return { word: "MODERATE", color: "var(--lrx-lavHi)" };
      return { word: "HIGH", color: "var(--lrx-amber)" };
    }
    // tsb
    if (v < -10) return { word: "OVERREACHED", color: "var(--lrx-amber)" };
    if (v <= 5) return { word: "OPTIMAL", color: "var(--lrx-green)" };
    return { word: "FRESH", color: "var(--lrx-run)" };
  }

  function _lrxMarkerPct(metric, v) {
    var min = metric === "tsb" ? -25 : 0;
    var max = metric === "tsb" ? 15 : 60;
    var pct = ((v - min) / (max - min)) * 100;
    return Math.max(2, Math.min(98, pct));
  }

  var _LRX_BAND = {
    ctl: "linear-gradient(90deg,#fbbf24,#60a5fa,#22c55e)",
    atl: "linear-gradient(90deg,#22c55e,#eab308,#ef4444)",
    tsb: "linear-gradient(90deg,#f59e0b,#22c55e,#60a5fa)",
  };
  var _LRX_TREND_COLOR = { ctl: "#4f6ef7", atl: "#dc2626", tsb: "#16a34a" };

  function renderReadinessWidget(data) {
    var el = document.getElementById('readiness-widget');
    if (!el) return;
    _lastReadinessData = data;

    if (data.building_baseline) {
      el.innerHTML =
        '<div class="lrx-chead"><span class="lrx-sectitle">Readiness</span></div>' +
        '<p class="rw-baseline-msg">Building baseline — log more workouts to unlock your Fitness, Fatigue, and Freshness scores.</p>';
      el.hidden = false;
      return;
    }

    var series = data.series || [];
    var rlabel = data.readiness_label || '';

    function rcard(metric, val, abbr, label, chartId) {
      var st = _lrxReadStatus(metric, val);
      var pct = _lrxMarkerPct(metric, val);
      return '<div class="lrx-rcard">' +
        '<div class="rv">' + esc(fmtLoadNum(val)) + '</div>' +
        '<div class="rl">' + abbr + ' · ' + label + '</div>' +
        '<div class="lrx-rband" style="background:' + _LRX_BAND[metric] + '">' +
          '<div class="mk" style="left:' + pct.toFixed(0) + '%"></div></div>' +
        '<div class="lrx-rstatus" style="color:' + st.color + '">' + st.word + '</div>' +
        '<svg class="lrx-rchart" id="' + chartId + '"></svg>' +
      '</div>';
    }

    el.innerHTML =
      '<div class="lrx-chead">' +
        '<span class="lrx-sectitle">Readiness</span>' +
        (rlabel ? '<span class="lrx-chip b">' + esc(rlabel) + '</span>' : '') +
      '</div>' +
      '<div class="lrx-readfull">' +
        rcard('ctl', data.ctl, 'CTL', 'Fitness',   'lrx-r-ctl') +
        rcard('atl', data.atl, 'ATL', 'Fatigue',   'lrx-r-atl') +
        rcard('tsb', data.tsb, 'TSB', 'Freshness', 'lrx-r-tsb') +
      '</div>';
    el.hidden = false;
    _lrxTrendLine('lrx-r-ctl', series.map(function (d) { return d.ctl; }), _LRX_TREND_COLOR.ctl);
    _lrxTrendLine('lrx-r-atl', series.map(function (d) { return d.atl; }), _LRX_TREND_COLOR.atl);
    _lrxTrendLine('lrx-r-tsb', series.map(function (d) { return d.tsb; }), _LRX_TREND_COLOR.tsb);
  }

  function fetchReadinessWidget() {
    var el = document.getElementById('readiness-widget');
    if (!el) return;
    fetch('/api/readiness')
      .then(function (res) {
        if (!res.ok) {
          el.hidden = true;
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (!data || Array.isArray(data)) return;
        renderReadinessWidget(data);
      })
      .catch(function () {
        if (el) el.hidden = true;
      });
  }

  function volumeWeekLabel(monday) {
    return monday.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  }

  function weekVolumeByType(workouts) {
    var runTss = 0;
    var strengthTss = 0;
    var distKm = 0;
    (workouts || []).forEach(function (w) {
      var tss = w.tss || 0;
      var norm = TF.normalizeType(w.type);
      if (norm === "run" || norm === "bike") {
        runTss += tss;
      } else if (norm === "lift" || norm === "wod") {
        strengthTss += tss;
      } else if ((w.distance_km || 0) > 0) {
        runTss += tss;
      } else if (tss > 0) {
        strengthTss += tss;
      }
      distKm += w.distance_km || 0;
    });
    return {
      runTss: Math.round(runTss),
      strengthTss: Math.round(strengthTss),
      distKm: Math.round(distKm * 10) / 10,
    };
  }

  // Weekly volume chart: stacked run + lift TSS bars with run-km line overlay.
  function renderVolumeChart() {
    var card = document.getElementById("volume-chart-card");
    var canvas = document.getElementById("volume-chart");
    // Guard: no-op when the surfaces or Chart.js are absent (other pages).
    if (!card || !canvas || typeof Chart === "undefined") return;

    var toISO = filters.to || todayISO();
    var toMonday = getMondayOf(new Date(toISO + "T00:00:00"));
    // Minimum window: 8 week-buckets ending at the selected week.
    var minStart = new Date(toMonday);
    minStart.setDate(minStart.getDate() - 7 * 7);

    var startMonday = minStart;
    if (filters.from) {
      var fm = getMondayOf(new Date(filters.from + "T00:00:00"));
      if (fm < minStart) startMonday = fm;
    }

    var fromStr = toISODate(startMonday);
    // Separate fetch WITHOUT include_load_context so load_context stays a
    // single computation on the main list request (AC5).
    fetch(
      "/api/training-log?from=" +
        fromStr +
        "&to=" +
        toISO +
        "&include_rest=false",
    )
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var weeks = data.weeks || [];
        var byStart = {};
        weeks.forEach(function (w) {
          byStart[w.week_start] = w;
        });

        var labels = [];
        var runTssVals = [];
        var strengthTssVals = [];
        var distVals = [];
        var nowMondayStr = toISODate(getMondayOf(new Date()));
        var currentWeekIdx = -1;
        var cur = new Date(startMonday);
        var wkIdx = 0;
        while (cur <= toMonday) {
          var wkIso = toISODate(cur);
          if (wkIso === nowMondayStr) currentWeekIdx = wkIdx;
          var wk = byStart[wkIso] || {};
          var agg = weekVolumeByType(wk.workouts || []);
          labels.push(volumeWeekLabel(cur));
          runTssVals.push(agg.runTss);
          strengthTssVals.push(agg.strengthTss);
          distVals.push(agg.distKm);
          cur.setDate(cur.getDate() + 7);
          wkIdx++;
        }

        var hasData =
          runTssVals.some(function (v) {
            return v > 0;
          }) ||
          strengthTssVals.some(function (v) {
            return v > 0;
          }) ||
          distVals.some(function (v) {
            return v > 0;
          });
        if (!hasData) {
          if (volumeChart) {
            volumeChart.destroy();
            volumeChart = null;
          }
          card.hidden = true;
          return;
        }

        // Read tick colour from CSS structural token (--text-tertiary).
        var rootStyle = getComputedStyle(document.documentElement);
        var tickColor = rootStyle.getPropertyValue('--text-tertiary').trim() || '#69748c';
        var tickFont  = { size: 10 };

        // Gradient background factory for stacked bars with current-week emphasis.
        // Scriptable: Chart.js calls this per data-point so gradients are recreated
        // on resize — keeping the chart responsive.
        function makeBarBg(hiA, loA, hiB, loB) {
          return function (context) {
            var area = context.chart.chartArea;
            var isCurrent = context.dataIndex === currentWeekIdx;
            if (!area) {
              return isCurrent ? loA : loB;
            }
            var g = context.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            g.addColorStop(0, isCurrent ? hiA : hiB);
            g.addColorStop(1, isCurrent ? loA : loB);
            return g;
          };
        }

        var runBg = makeBarBg(
          'rgba(96,165,250,0.95)', 'rgba(37,99,235,0.88)',
          'rgba(96,165,250,0.38)', 'rgba(37,99,235,0.28)'
        );
        var liftBg = makeBarBg(
          'rgba(167,139,250,0.95)', 'rgba(109,40,217,0.88)',
          'rgba(167,139,250,0.38)', 'rgba(109,40,217,0.28)'
        );

        // Update the existing chart in place when possible (avoids the
        // destroy/recreate flash on every fetch, including single-workout
        // edits) — only rebuild when the instance is missing entirely.
        if (volumeChart) {
          volumeChart.data.labels = labels;
          volumeChart.data.datasets[0].data = runTssVals;
          volumeChart.data.datasets[0].backgroundColor = runBg;
          volumeChart.data.datasets[1].data = strengthTssVals;
          volumeChart.data.datasets[1].backgroundColor = liftBg;
          volumeChart.data.datasets[2].data = distVals;
          volumeChart.update();
          card.hidden = false;
          return;
        }

        volumeChart = new Chart(canvas.getContext("2d"), {
          type: "bar",
          data: {
            labels: labels,
            datasets: [
              {
                label: "Run TSS",
                data: runTssVals,
                backgroundColor: runBg,
                borderRadius: 4,
                maxBarThickness: 36,
                stack: "tss",
                order: 2,
                yAxisID: "y",
              },
              {
                label: 'Lift TSS',
                data: strengthTssVals,
                backgroundColor: liftBg,
                borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
                maxBarThickness: 36,
                stack: "tss",
                order: 2,
                yAxisID: "y",
              },
              {
                label: 'Distance',
                type: 'line',
                data: distVals,
                borderColor: "#f59e0b",
                backgroundColor: "#f59e0b",
                pointBackgroundColor: "#f59e0b",
                pointBorderColor: "#fff",
                pointBorderWidth: 1.5,
                pointRadius: 4,
                pointHoverRadius: 5,
                borderWidth: 2,
                tension: 0.25,
                yAxisID: "y1",
                order: 1,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
              legend: {
                display: true,
                position: "bottom",
                labels: {
                  boxWidth: 10,
                  boxHeight: 10,
                  font: { size: 11 },
                  padding: 14,
                  color: tickColor,
                },
              },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    var val = ctx.parsed.y;
                    if (ctx.dataset.yAxisID === "y1") {
                      return ctx.dataset.label + ": " + val + " km";
                    }
                    return ctx.dataset.label + ": " + val + " TSS";
                  },
                  footer: function (items) {
                    if (!items.length) return "";
                    var run =
                      items[0].chart.data.datasets[0].data[
                        items[0].dataIndex
                      ] || 0;
                    var str =
                      items[0].chart.data.datasets[1].data[
                        items[0].dataIndex
                      ] || 0;
                    return "Total TSS: " + (run + str);
                  },
                },
              },
            },
            scales: {
              x: {
                stacked: true,
                grid: { display: false },
                ticks: { font: tickFont, color: tickColor },
                title: {
                  display: true,
                  text: "Week",
                  color: tickColor,
                  font: { size: 10 },
                },
              },
              y: {
                stacked: true,
                position: "left",
                beginAtZero: true,
                ticks: { font: tickFont, color: tickColor },
                title: {
                  display: true,
                  text: "TSS",
                  color: tickColor,
                  font: { size: 10 },
                },
              },
              y1: {
                position: "right",
                beginAtZero: true,
                grid: { drawOnChartArea: false },
                ticks: { font: tickFont, color: tickColor },
                title: {
                  display: true,
                  text: "Distance",
                  color: tickColor,
                  font: { size: 10 },
                },
              },
            },
          },
        });
        card.hidden = false;
      })
      .catch(function () {
        /* leave prior chart / hidden card untouched */
      });
  }

  // ── Log list rendering ────────────────────────────────────────────────────

  // issue #637: day-grouped list — replaces week-grouped rendering for Log sub-tab.
  // Month separator with a monthly rollup (Run TSS / Lift TSS / Time / KM).
  function buildSeparator(titleText, agg, variant) {
    // Week separators use the mock's .lrx-wkhdr (label + "N TSS · N km").
    // Month separators are rendered as a light label row (kept minimal so the
    // week headers carry the totals, matching the mock's week-grouped list).
    if (variant === 'week-sep') {
      var sep = document.createElement('div');
      sep.className = 'lrx-wkhdr';
      var tss = agg ? Math.round((agg.runTss || 0) + (agg.liftTss || 0)) : 0;
      var km = agg ? (Math.round(agg.km * 10) / 10) : 0;
      var wl = document.createElement('span');
      wl.className = 'wl';
      wl.textContent = (titleText || '').replace(/^Week of\s*/, '');
      var wr = document.createElement('span');
      wr.className = 'wr';
      wr.textContent = tss + ' TSS · ' + km + ' km';
      sep.appendChild(wl);
      sep.appendChild(wr);
      return sep;
    }

    var sep = document.createElement('div');
    sep.className = 'month-sep' + (variant ? ' ' + variant : '');

    var title = document.createElement('div');
    title.className = 'month-sep-title';
    title.textContent = titleText;
    sep.appendChild(title);

    var stats = document.createElement('div');
    stats.className = 'month-sep-stats';
    var parts = [
      ['Run TSS', agg ? Math.round(agg.runTss) : 0],
      ['Lift TSS', agg ? Math.round(agg.liftTss) : 0],
      ['Time', (agg && agg.secs) ? fmtDuration(agg.secs) : '0min'],
      ['KM', agg ? (Math.round(agg.km * 10) / 10) : 0],
    ];
    parts.forEach(function (p) {
      var chip = document.createElement('span');
      chip.className = 'month-stat';
      var val = document.createElement('span');
      val.className = 'month-stat-val';
      val.textContent = p[1];
      var lbl = document.createElement('span');
      lbl.className = 'month-stat-lbl';
      lbl.textContent = p[0];
      chip.appendChild(val);
      chip.appendChild(lbl);
      stats.appendChild(chip);
    });
    sep.appendChild(stats);
    return sep;
  }

  function _monthTitle(dateStr) {
    var d = new Date(dateStr + 'T00:00:00');
    return isNaN(d.getMonth()) ? (dateStr || '').slice(0, 7)
      : MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  }
  function _mondayOf(dateStr) {
    var d = new Date(dateStr + 'T00:00:00');
    var dow = d.getDay(), diff = dow === 0 ? -6 : 1 - dow;
    d.setDate(d.getDate() + diff);
    return d;
  }
  function _weekKey(dateStr) {
    var m = _mondayOf(dateStr);
    return m.getFullYear() + '-' + pad(m.getMonth() + 1) + '-' + pad(m.getDate());
  }
  function _weekTitle(dateStr) {
    var mon = _mondayOf(dateStr), sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    var a = MONTHS[mon.getMonth()] + ' ' + mon.getDate();
    var b = mon.getMonth() === sun.getMonth() ? ('' + sun.getDate())
      : (MONTHS[sun.getMonth()] + ' ' + sun.getDate());
    return 'Week of ' + a + ' – ' + b;
  }

  // Incremental render state — the full history can be hundreds of workouts, so
  // render in batches and reveal more as the user scrolls (issue: lazy load).
  var _listState = null;
  var _LIST_BATCH = 30; // target workouts per batch; whole days are kept intact

  function renderDayGroupedList(container, weeks) {
    if (!container) return;
    if (_listState && _listState.observer) _listState.observer.disconnect();
    container.innerHTML = "";

    // Flatten all workout entries from all weeks, newest-first (API already orders by date desc).
    var entries = [];
    (weeks || []).forEach(function (week) {
      (week.entries || []).forEach(function (entry) {
        if (entry.type !== 'rest') entries.push(entry);
      });
    });

    if (!entries.length) {
      var emptyEl = document.getElementById('log-empty-msg');
      if (emptyEl) emptyEl.style.display = '';
      _listState = null;
      return;
    }

    hideListMessages();

    // Group by calendar date (ISO string), preserving newest-first order.
    var days = [];
    var dayMap = {};
    entries.forEach(function (entry) {
      var date = entry.date || '';
      if (!dayMap[date]) {
        dayMap[date] = [];
        days.push(date);
      }
      dayMap[date].push(entry);
    });
    days.sort(function (a, b) { return a < b ? 1 : a > b ? -1 : 0; });

    // Full month + week rollups up front, so each separator shows correct totals
    // even before the whole period has been rendered.
    function addAgg(map, key, e) {
      if (!map[key]) map[key] = { runTss: 0, liftTss: 0, secs: 0, km: 0 };
      var tk = normalizeTypeKey(e.type), tss = Number(e.tss) || 0;
      if (tk === 'run') map[key].runTss += tss;
      else if (tk === 'lift') map[key].liftTss += tss;
      if (e.duration_seconds) map[key].secs += Number(e.duration_seconds) || 0;
      if (e.distance_km) map[key].km += Number(e.distance_km) || 0;
    }
    var monthAgg = {}, weekAgg = {};
    entries.forEach(function (e) {
      var mk = (e.date || '').slice(0, 7);
      if (mk) addAgg(monthAgg, mk, e);
      if (e.date) addAgg(weekAgg, _weekKey(e.date), e);
    });

    _listState = {
      container: container, days: days, dayMap: dayMap,
      monthAgg: monthAgg, weekAgg: weekAgg,
      cursor: 0, lastMonthKey: null, lastWeekKey: null,
      sentinel: null, observer: null,
    };
    renderNextBatch();
  }

  function renderNextBatch() {
    var st = _listState;
    if (!st) return;
    if (st.sentinel && st.sentinel.parentNode) st.sentinel.parentNode.removeChild(st.sentinel);

    var rendered = 0;
    while (st.cursor < st.days.length && rendered < _LIST_BATCH) {
      var dateStr = st.days[st.cursor++];
      var monthKey = dateStr.slice(0, 7);
      if (monthKey !== st.lastMonthKey) {
        st.lastMonthKey = monthKey;
        st.lastWeekKey = null;
        st.container.appendChild(buildSeparator(_monthTitle(dateStr), st.monthAgg[monthKey], ''));
      }
      var wk = _weekKey(dateStr);
      if (wk !== st.lastWeekKey) {
        st.lastWeekKey = wk;
        st.container.appendChild(buildSeparator(_weekTitle(dateStr), st.weekAgg[wk], 'week-sep'));
      }

      var d = new Date(dateStr + 'T00:00:00');
      var dayGroup = document.createElement('div');
      dayGroup.className = 'day-group';
      dayGroup.dataset.date = dateStr;

      var header = document.createElement('div');
      header.className = 'day-group-header';
      header.textContent = isNaN(d.getDay()) ? dateStr :
        DAY_ABBR[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
      dayGroup.appendChild(header);

      var rowsEl = document.createElement('div');
      rowsEl.className = 'day-group-rows';
      st.dayMap[dateStr].forEach(function (entry) {
        rowsEl.appendChild(buildEntryRow(entry));
        rendered++;
      });
      dayGroup.appendChild(rowsEl);
      st.container.appendChild(dayGroup);
    }

    if (st.cursor < st.days.length) {
      var sentinel = document.createElement('div');
      sentinel.className = 'log-load-more-sentinel lrx-sentinel';
      sentinel.innerHTML = '<span class="lrx-spin"></span> Loading older weeks…';
      st.container.appendChild(sentinel);
      st.sentinel = sentinel;
      if ('IntersectionObserver' in window) {
        if (!st.observer) {
          st.observer = new IntersectionObserver(function (ents) {
            if (ents.some(function (en) { return en.isIntersecting; })) renderNextBatch();
          }, { rootMargin: '600px 0px' });
        }
        st.observer.observe(sentinel);
      } else {
        sentinel.className = 'log-load-more lrx-sentinel';
        sentinel.textContent = 'Load more';
        sentinel.addEventListener('click', renderNextBatch);
      }
    } else {
      st.sentinel = null;
      if (st.observer) st.observer.disconnect();
      // End-of-log marker (mock: "— end of log —").
      var endEl = document.createElement('div');
      endEl.className = 'lrx-sentinel';
      endEl.textContent = '— end of log —';
      st.container.appendChild(endEl);
    }
  }

  function renderList(container, weeks) {
    renderDayGroupedList(container, weeks);
  }

  function renderRestDayRow(entry) {
    var row = document.createElement("div");
    row.className = "rest-day-row";
    row.setAttribute("aria-label", "Rest day");

    var dateCol = document.createElement("div");
    dateCol.className = "entry-date";
    var d = new Date((entry.date || "") + "T00:00:00");
    var dayNumEl = document.createElement("div");
    dayNumEl.className = "entry-day-num";
    dayNumEl.textContent = isNaN(d.getDate()) ? "" : d.getDate();
    var dayNameEl = document.createElement("div");
    dayNameEl.className = "entry-day-name";
    dayNameEl.textContent = isNaN(d.getDay()) ? "" : DAY_ABBR[d.getDay()];
    dateCol.appendChild(dayNumEl);
    dateCol.appendChild(dayNameEl);
    row.appendChild(dateCol);

    var iconEl = document.createElement("span");
    iconEl.className = "rest-moon-icon";
    iconEl.setAttribute("aria-hidden", "true");
    iconEl.textContent = "🌙";
    row.appendChild(iconEl);

    var info = document.createElement("div");
    info.className = "rest-metrics";

    var labelParts = [];
    if (entry.sleep_hours != null)
      labelParts.push("sleep " + entry.sleep_hours + "h");
    if (entry.energy != null) labelParts.push("energy " + entry.energy + "/5");
    if (entry.mood != null) labelParts.push("mood " + entry.mood + "/5");
    if (entry.resting_hr != null) labelParts.push("RHR " + entry.resting_hr);

    var label = document.createElement("span");
    label.className = "rest-day-label";
    label.textContent =
      "Rest day" + (labelParts.length ? " \xb7 " + labelParts.join(", ") : "");
    info.appendChild(label);

    row.appendChild(info);
    return row;
  }

  function weekDisplayLabel(week) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var dow = today.getDay();
    var diff = dow === 0 ? -6 : 1 - dow;
    var thisMon = new Date(today);
    thisMon.setDate(thisMon.getDate() + diff);
    thisMon.setHours(0, 0, 0, 0);
    var lastMon = new Date(thisMon);
    lastMon.setDate(lastMon.getDate() - 7);
    var weekStart = new Date(week.week_start + "T00:00:00");
    weekStart.setHours(0, 0, 0, 0);
    if (weekStart.getTime() === thisMon.getTime()) return "THIS WEEK";
    if (weekStart.getTime() === lastMon.getTime()) return "LAST WEEK";
    return week.label || "";
  }

  function buildWeekGroup(week) {
    var s = week.summary || {};
    var ws = week.workouts || [];

    var dateRange = "";
    if (week.week_start && week.week_end) {
      dateRange =
        fmtShortDate(week.week_start) + " – " + fmtShortDate(week.week_end);
    }

    var count = s.workout_count || ws.length;
    var countStr = count + " workout" + (count !== 1 ? "s" : "");
    var totalTime = fmtTotalTime(s.total_time_minutes);

    var summaryParts = [countStr];
    var dist = s.total_distance_km;
    if (dist && dist > 0) summaryParts.push((+dist).toFixed(1) + " km");
    if (s.total_tss > 0) summaryParts.push("TSS " + (+s.total_tss).toFixed(0));
    if (totalTime) summaryParts.push(totalTime);

    var groupEl = document.createElement("div");
    groupEl.className = "week-group";

    var header = document.createElement("div");
    header.className = "week-header";

    var titleEl = document.createElement("h2");
    titleEl.className = "week-header-title";
    titleEl.textContent = weekDisplayLabel(week);

    var rangeEl = document.createElement("div");
    rangeEl.className = "week-header-range";
    rangeEl.textContent = dateRange;

    var summaryEl = document.createElement("div");
    summaryEl.className = "week-header-summary";
    summaryParts.forEach(function (part, i) {
      if (i > 0) {
        var sep = document.createElement("span");
        sep.className = "summary-sep";
        sep.textContent = "\xb7";
        summaryEl.appendChild(sep);
      }
      var span = document.createElement("span");
      span.textContent = part;
      summaryEl.appendChild(span);
    });

    header.appendChild(titleEl);
    header.appendChild(rangeEl);
    header.appendChild(summaryEl);
    groupEl.appendChild(header);

    var card = document.createElement("div");
    card.className = "week-card";

    var entries = (week.entries || []).slice().sort(function (a, b) {
      return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
    });
    entries.forEach(function (entry) {
      card.appendChild(
        entry.type === "rest" ? renderRestDayRow(entry) : buildEntryRow(entry),
      );
    });

    groupEl.appendChild(card);
    return groupEl;
  }

  // issue #530: a workout is Strava-sourced if its `source` contains 'strava' OR it
  // carries a Strava activity URL (some imports leave `source` unset). Shared by
  // the list and detail views so both attribute the source identically.
  // issue #601: uses substring includes() so merged 'strava,stryd' source is detected.
  function isStravaWorkout(workout) {
    if (!workout) return false;
    return (
      (workout.source || "").includes("strava") || !!workout.strava_activity_url
    );
  }

  // Synced = backed by a Strava/Stryd activity. Deleting these tombstones the
  // activity (so it won't resync); they can be restored from the Removed list.
  function isSyncedWorkout(workout) {
    if (!workout) return false;
    var src = workout.source || "";
    return (
      src.includes("strava") ||
      src.includes("stryd") ||
      !!workout.strava_activity_url ||
      !!workout.has_strava ||
      !!workout.has_stryd
    );
  }

  // Reworked to the mock's .lrx-logrow (typed left accent, day block, name +
  // meta, TSS at right) while keeping ALL existing wiring: entry-row classes +
  // data-workout-* attrs (filtering/syncActiveRow), click/keydown → detail.
  function buildEntryRow(w) {
    var typeKey = normalizeTypeKey(w.type);
    // Mock has two families: run(blue) and lift(violet). bike→run, wod→lift.
    var fam = (typeKey === "run" || typeKey === "bike") ? "run" : "lift";
    var TYPE_LABELS = { run: "Run", lift: "Lift", wod: "WOD", bike: "Bike" };
    var typeSlug = TYPE_LABELS[typeKey] ? typeKey : "other";

    var row = document.createElement("div");
    row.className = "entry-row lrx-logrow " + fam + " entry-row--" + typeSlug;
    if (w.id && activeDetailWorkoutId === w.id) row.classList.add("is-active");
    row.dataset.workoutType = typeKey;
    row.dataset.workoutTitle = (w.title || "").toLowerCase();

    if (w.id) {
      row.setAttribute("tabindex", "0");
      row.setAttribute("role", "button");
      var ariaBits = [];
      ariaBits.push(TYPE_LABELS[typeKey] || w.type || "Workout");
      ariaBits.push(w.title || "Workout");
      if (w.date) ariaBits.push(fmtDate(w.date));
      if (typeKey === "run" && w.distance_km != null)
        ariaBits.push((+w.distance_km).toFixed(1) + " kilometers");
      else if (w.duration_seconds)
        ariaBits.push(Math.round(w.duration_seconds / 60) + " minutes");
      row.setAttribute("aria-label", ariaBits.join(", ") + ". Open details");
      row.dataset.workoutId = w.id;
      var rowRef = row;
      row.addEventListener("click", function () { openDetailPanel(w.id, rowRef); });
      row.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetailPanel(w.id, rowRef); }
      });
    }

    // Day block (number + month abbr).
    var d = new Date((w.date || "") + "T00:00:00");
    var lday = document.createElement("div");
    lday.className = "lday";
    lday.innerHTML =
      '<div class="d">' + (isNaN(d.getDate()) ? "" : d.getDate()) + "</div>" +
      '<div class="m">' + (isNaN(d.getMonth()) ? "" : MONTHS[d.getMonth()]) + "</div>";

    // Name + type badge + meta line.
    var metaParts = [];
    if (w.duration_seconds) metaParts.push(fmtDurationRow(w.duration_seconds));
    if (typeKey === "run" && w.distance_km != null)
      metaParts.push((+w.distance_km).toFixed(1) + " km");
    if (typeKey === "run" && w.average_pace_seconds_per_km)
      metaParts.push(fmtPace(w.average_pace_seconds_per_km));
    if (w.avg_hr != null) metaParts.push("HR " + w.avg_hr);
    metaParts = metaParts.filter(Boolean);

    var lname = document.createElement("div");
    lname.className = "lname";
    var nEl = document.createElement("div");
    nEl.className = "n";
    var badge = document.createElement("span");
    badge.className = "lrx-tbadge " + fam;
    badge.textContent = fam === "run" ? "run" : "lift";
    nEl.appendChild(badge);
    nEl.appendChild(document.createTextNode(" " + (w.title || "Workout")));
    lname.appendChild(nEl);
    if (metaParts.length) {
      var metaEl = document.createElement("div");
      metaEl.className = "meta";
      metaEl.textContent = metaParts.join(" · ");
      lname.appendChild(metaEl);
    }

    // Right-side stat: TSS (or em-dash for strength with no TSS).
    var lstat = document.createElement("div");
    lstat.className = "lstat";
    var b = document.createElement("b");
    b.textContent = w.tss != null ? Math.round(w.tss) + " TSS" : "—";
    lstat.appendChild(b);

    row.appendChild(lday);
    row.appendChild(lname);
    row.appendChild(lstat);
    return row;
  }

  // ── Sync active row highlight after list re-render ───────────────────────
  function syncActiveRow() {
    document.querySelectorAll(".entry-row").forEach(function (r) {
      r.classList.remove("is-active");
    });
    if (!activeDetailWorkoutId) return;
    var row = document.querySelector(
      '.entry-row[data-workout-id="' + activeDetailWorkoutId + '"]',
    );
    if (row) {
      activeRowEl = row;
      row.classList.add("is-active");
    }
  }

  // ── CSV Export ────────────────────────────────────────────────────────────
  function exportCSV() {
    var today = todayISO();
    var fromDate = filters.from || today;
    var toDate = filters.to || today;
    var filename = "training-log-" + fromDate + "-to-" + toDate + ".csv";

    var rows = [
      "date,type,title,distance_km,duration_minutes,avg_hr,tss,source",
    ];
    lastWeeks.forEach(function (week) {
      (week.entries || []).forEach(function (entry) {
        if (entry.type === "rest") return;
        rows.push(
          [
            csvField(entry.date),
            csvField(entry.type),
            csvField(entry.title),
            csvField(entry.distance_km != null ? entry.distance_km : ""),
            csvField(
              entry.duration_seconds != null
                ? Math.round((entry.duration_seconds / 60) * 10) / 10
                : "",
            ),
            csvField(entry.avg_hr != null ? entry.avg_hr : ""),
            csvField(entry.tss != null ? entry.tss : ""),
            csvField(entry.source),
          ].join(","),
        );
      });
    });

    var csv = rows.join("\r\n");
    var blob = new Blob([csv], { type: "text/csv" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Detail panel position helpers ─────────────────────────────────────────
  function findPosIndex(workoutId) {
    for (var i = 0; i < flatWorkouts.length; i++) {
      if (flatWorkouts[i].id === workoutId) return i;
    }
    return -1;
  }

  function updatePositionPill() {
    var pill = document.getElementById("dp-position-pill");
    var prevBtn = document.getElementById("dp-prev-btn");
    var nextBtn = document.getElementById("dp-next-btn");
    var total = flatWorkouts.length;

    if (pill) {
      pill.textContent = total > 0 ? activePosIndex + 1 + " of " + total : "";
    }
    if (prevBtn) prevBtn.disabled = activePosIndex <= 0;
    if (nextBtn) nextBtn.disabled = activePosIndex >= total - 1;
  }

  function isDesktop() {
    return window.innerWidth >= 880;
  }

  // ── Detail panel open / close / modes ─────────────────────────────────────
  function openPanelShell(triggerEl) {
    var overlay = document.getElementById("detail-overlay");
    var panel = document.getElementById("detail-panel");
    var wrapper = document.getElementById("layout-wrapper");

    if (panel) panel.classList.add("is-open");

    if (isDesktop()) {
      if (wrapper) wrapper.classList.add("has-panel");
      reflowPanelCharts();
    } else {
      if (overlay) {
        overlay.classList.add("is-open");
        overlay.removeAttribute("aria-hidden");
      }
      document.body.style.overflow = "hidden";
    }

    if (triggerEl) {
      activeTriggerEl = triggerEl;
    }
  }

  function resetTopbarChrome() {
    closeOverflowMenu();
    var panel = document.getElementById("detail-panel");
    if (panel) panel.classList.remove("detail-panel--form");
    var posGroup = document.querySelector(".dp-position-group");
    var overflowBtn = document.getElementById("dp-overflow-btn");
    var topbarEnd = document.querySelector(".dp-topbar-end");
    if (posGroup) posGroup.style.display = "";
    if (overflowBtn) overflowBtn.style.display = "";
    if (topbarEnd) topbarEnd.style.display = "";
    var navLinks = document.querySelector(".global-nav .gn-links");
    if (navLinks) navLinks.scrollLeft = 0;
  }

  function setHistoryTab(tab) {
    document.querySelectorAll(".log-history-tab").forEach(function (el) {
      var active = el.dataset.tab === tab;
      el.classList.toggle("is-active", active);
      el.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  function setPanelMode(mode) {
    panelMode = mode;
    var panel = document.getElementById("detail-panel");
    var formWrap = document.getElementById("dp-form-wrap");
    var loadingEl = document.getElementById("dp-loading");
    var errorEl = document.getElementById("dp-error");
    var contentEl = document.getElementById("dp-content");
    var formActions = document.getElementById("dp-actions-form");
    var formTitle = document.getElementById("dp-form-title");
    var pill = document.getElementById("dp-position-pill");

    var isForm = mode === "edit" || mode === "create";

    if (panel) panel.classList.toggle("detail-panel--form", isForm);
    if (formWrap) formWrap.style.display = isForm ? "" : "none";
    if (formActions) formActions.style.display = isForm ? "" : "none";

    if (isForm) {
      closeOverflowMenu();
      if (loadingEl) loadingEl.style.display = "none";
      if (errorEl) errorEl.style.display = "none";
      if (contentEl) contentEl.innerHTML = "";
      if (formTitle)
        formTitle.textContent =
          mode === "create" ? "Log workout" : "Edit workout";
      if (pill) pill.textContent = mode === "create" ? "New" : "Editing";
      var saveBtn = document.getElementById("dp-save-btn");
      if (saveBtn)
        saveBtn.textContent = mode === "edit" ? "Save changes" : "Save workout";
    } else if (pill) {
      updatePositionPill();
    }
  }

  function openDetailPanel(workoutId, triggerEl) {
    if (activeRowEl) activeRowEl.classList.remove("is-active");
    activeRowEl = triggerEl || null;
    if (activeRowEl) activeRowEl.classList.add("is-active");

    activeDetailWorkoutId = workoutId;
    activeTriggerEl = triggerEl || null;
    activePosIndex = findPosIndex(workoutId);
    cachedDetailWorkout = null;

    closeOverflowMenu();
    setPanelMode("view");
    setHistoryTab("history");
    openPanelShell(triggerEl);
    updatePositionPill();
    fetchAndRenderDetail(workoutId);
    setWorkoutURLParam(workoutId);
  }

  function createPresetDate() {
    if (filters.from && filters.from === filters.to) return filters.from;
    return todayISO();
  }

  function openPanelCreate(presetDate) {
    if (activeRowEl) {
      activeRowEl.classList.remove("is-active");
      activeRowEl = null;
    }

    activeDetailWorkoutId = null;
    activePosIndex = -1;
    cachedDetailWorkout = null;

    closeOverflowMenu();
    var dateToUse = presetDate || createPresetDate();
    if (window.TrainingEditor) {
      TrainingEditor.resetForm();
      TrainingEditor.setEditingId(null);
      var dateEl = document.getElementById("workout-date");
      if (dateEl) dateEl.value = dateToUse;
      TrainingEditor.applyDefaultWorkoutName();
    }
    setPanelMode("create");
    setHistoryTab("new");
    openPanelShell(null);

    var scrollEl = document.getElementById("dp-scroll");
    if (scrollEl) scrollEl.scrollTop = 0;
    var nameInput = document.getElementById("workout-name");
    if (nameInput) nameInput.focus();
  }

  function switchToEditMode() {
    if (!activeDetailWorkoutId) return;
    closeOverflowMenu();
    setPanelMode("edit");

    function applyEdit(workout) {
      cachedDetailWorkout = workout;
      if (window.TrainingEditor) {
        TrainingEditor.fillForm(workout);
        TrainingEditor.setEditingId(workout.id);
      }
      var scrollEl = document.getElementById("dp-scroll");
      if (scrollEl) scrollEl.scrollTop = 0;
      var nameInput = document.getElementById("workout-name");
      if (nameInput) nameInput.focus();
    }

    if (
      cachedDetailWorkout &&
      cachedDetailWorkout.id === activeDetailWorkoutId
    ) {
      applyEdit(cachedDetailWorkout);
      return;
    }

    fetch("/api/workouts/" + activeDetailWorkoutId)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(applyEdit)
      .catch(function () {
        UIStates.showToast("Could not load workout for editing.", true);
        setPanelMode("view");
      });
  }

  function cancelPanelForm() {
    if (panelMode === "create") {
      closeDetailPanel();
      return;
    }
    if (panelMode === "edit" && activeDetailWorkoutId) {
      setPanelMode("view");
      fetchAndRenderDetail(activeDetailWorkoutId);
    }
  }

  function closeDetailPanel() {
    if (activeRowEl) {
      activeRowEl.classList.remove("is-active");
      activeRowEl = null;
    }

    var trigger = activeTriggerEl;
    activeDetailWorkoutId = null;
    activeTriggerEl = null;
    activePosIndex = -1;
    cachedDetailWorkout = null;
    panelMode = "view";

    closeOverflowMenu();
    resetTopbarChrome();

    var overlay = document.getElementById("detail-overlay");
    var panel = document.getElementById("detail-panel");
    var wrapper = document.getElementById("layout-wrapper");

    if (panel) {
      panel.classList.remove("is-open");
    }
    if (overlay) {
      overlay.classList.remove("is-open");
      overlay.setAttribute("aria-hidden", "true");
    }
    if (wrapper) wrapper.classList.remove("has-panel");
    document.body.style.overflow = "";
    if (isDesktop()) reflowPanelCharts();

    var formWrap = document.getElementById("dp-form-wrap");
    var formActions = document.getElementById("dp-actions-form");
    if (formWrap) formWrap.style.display = "none";
    if (formActions) formActions.style.display = "none";

    setHistoryTab("history");
    clearWorkoutURLParam();

    if (trigger) trigger.focus();
  }

  // ── Navigate prev / next ──────────────────────────────────────────────────
  function navigateDetail(direction) {
    if (panelMode !== "view") return;
    var newIndex = activePosIndex + direction;
    if (newIndex < 0 || newIndex >= flatWorkouts.length) return;

    var fw = flatWorkouts[newIndex];
    activePosIndex = newIndex;
    activeDetailWorkoutId = fw.id;

    syncActiveRow();
    updatePositionPill();
    fetchAndRenderDetail(fw.id);
  }

  function updateOverflowMenu(workout) {
    var menuEdit = document.getElementById("dp-menu-edit");
    var menuDup = document.getElementById("dp-menu-duplicate");
    var menuStrava = document.getElementById("dp-menu-strava");
    var menuDelete = document.getElementById("dp-menu-delete");

    var hasWorkout = !!workout;
    if (menuEdit) menuEdit.style.display = hasWorkout ? "" : "none";
    if (menuDup) menuDup.style.display = hasWorkout ? "" : "none";

    var isStrava = hasWorkout && isStravaWorkout(workout);
    if (menuStrava) {
      if (isStrava && workout.strava_activity_url) {
        menuStrava.href = workout.strava_activity_url;
        menuStrava.style.display = "";
      } else {
        menuStrava.style.display = "none";
      }
    }
    if (menuDelete) {
      // Always allow removal. Synced workouts are tombstoned (won't resync) and
      // are restorable; manual workouts are permanently deleted.
      menuDelete.style.display = hasWorkout ? "" : "none";
      menuDelete.textContent =
        hasWorkout && isSyncedWorkout(workout) ? "Remove from log" : "Delete";
    }
  }

  function openOverflowMenu() {
    var menu = document.getElementById("dp-overflow-menu");
    var btn = document.getElementById("dp-overflow-btn");
    if (!menu) return;
    menu.removeAttribute("hidden");
    menu.classList.add("is-open");
    if (btn) btn.setAttribute("aria-expanded", "true");
  }

  function closeOverflowMenu() {
    var menu = document.getElementById("dp-overflow-menu");
    var btn = document.getElementById("dp-overflow-btn");
    if (!menu) return;
    menu.classList.remove("is-open");
    menu.setAttribute("hidden", "");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function toggleOverflowMenu() {
    var menu = document.getElementById("dp-overflow-menu");
    if (!menu) return;
    if (menu.classList.contains("is-open")) closeOverflowMenu();
    else openOverflowMenu();
  }

  var _detailScreenshotBusy = false;

  function slugifyScreenshotName(name) {
    return (
      String(name || "workout")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 60) || "workout"
    );
  }

  function buildDetailScreenshotFilename() {
    var w = cachedDetailWorkout;
    var parts = [slugifyScreenshotName(w && w.name)];
    if (w && w.workout_date) parts.push(w.workout_date);
    return parts.join("-") + ".png";
  }

  function expandScreenshotOverflow(root) {
    var touched = [];
    if (!root) return touched;
    root.querySelectorAll("*").forEach(function (el) {
      var cs = window.getComputedStyle(el);
      var patch = {};
      if (
        cs.overflow === "auto" ||
        cs.overflow === "scroll" ||
        cs.overflow === "hidden"
      ) {
        patch.overflow = el.style.overflow;
        el.style.overflow = "visible";
      }
      if (cs.maxHeight && cs.maxHeight !== "none") {
        patch.maxHeight = el.style.maxHeight;
        el.style.maxHeight = "none";
      }
      if (Object.keys(patch).length) touched.push({ el: el, patch: patch });
    });
    return touched;
  }

  function restoreScreenshotOverflow(touched) {
    touched.forEach(function (item) {
      Object.keys(item.patch).forEach(function (key) {
        item.el.style[key] = item.patch[key];
      });
    });
  }

  /** Run detail: header, Load & intensity, and laps only (skip route, sync, etc.). */
  function buildScreenshotClone(contentEl) {
    var stack = contentEl.querySelector(".rd4-stack");
    if (!stack) return contentEl.cloneNode(true);

    var out = document.createElement("div");
    out.className = "rd4-stack";

    var header = stack.querySelector(".rd4-header");
    if (header) out.appendChild(header.cloneNode(true));

    stack.querySelectorAll(".rd4-card").forEach(function (card) {
      if (
        card.classList.contains("rd4-header") ||
        card.classList.contains("rd4-laps-card")
      )
        return;
      var title = card.querySelector(".rd4-sec-title");
      if (!title) return;
      var label = title.textContent.replace(/\s+/g, " ").trim();
      if (/^load\s*&\s*intensity$/i.test(label)) {
        out.appendChild(card.cloneNode(true));
      }
    });

    var laps = stack.querySelector(".rd4-laps-card");
    if (laps) out.appendChild(laps.cloneNode(true));

    return out.childElementCount ? out : contentEl.cloneNode(true);
  }

  // Show a lightweight picker when a run has both km and manual lap types.
  // Returns a Promise that resolves once the user picks (or immediately if no
  // choice is needed).  As a side-effect it clicks the appropriate lap toggle
  // button so the DOM is in the chosen state before the caller clones it.
  function _promptLapModeIfNeeded(contentEl) {
    return new Promise(function (resolve) {
      var toggle = contentEl.querySelector("#rd4-lapmode-toggle");
      if (!toggle || toggle.querySelectorAll(".rd4-lm-btn").length < 2) {
        resolve();
        return;
      }
      var activeBtn = toggle.querySelector(".rd4-lm-btn--on") || toggle.querySelector(".rd4-lm-btn");
      var activeMode = activeBtn ? activeBtn.getAttribute("data-lap-mode") : "distance";

      var overlay = document.createElement("div");
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.35);z-index:9999;" +
        "display:flex;align-items:center;justify-content:center;";

      var box = document.createElement("div");
      box.style.cssText =
        "background:#fff;border-radius:14px;padding:22px 24px;max-width:260px;" +
        "width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.18);";
      box.innerHTML =
        '<p style="margin:0 0 14px;font-size:13px;font-weight:800;letter-spacing:.05em;' +
        'text-transform:uppercase;color:#9aa3b2;">Screenshot — lap view</p>';

      function makeBtn(label, mode) {
        var b = document.createElement("button");
        b.textContent = label;
        var isActive = mode === activeMode;
        b.style.cssText =
          "display:block;width:100%;padding:11px;margin-bottom:8px;cursor:pointer;" +
          "border-radius:9px;font-size:14px;font-weight:600;" +
          "border:1.5px solid " + (isActive ? "#2563eb" : "#e0e4f0") + ";" +
          "background:" + (isActive ? "#2563eb" : "#fff") + ";" +
          "color:" + (isActive ? "#fff" : "#374151") + ";";
        b.addEventListener("click", function () {
          document.body.removeChild(overlay);
          var target = toggle.querySelector('.rd4-lm-btn[data-lap-mode="' + mode + '"]');
          if (target && !target.classList.contains("rd4-lm-btn--on")) target.click();
          resolve();
        });
        return b;
      }

      box.appendChild(makeBtn("1 km splits", "distance"));
      box.appendChild(makeBtn("Manual laps", "manual"));
      overlay.appendChild(box);
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) { document.body.removeChild(overlay); resolve(); }
      });
      document.body.appendChild(overlay);
    });
  }

  function saveDetailScreenshot() {
    if (_detailScreenshotBusy) return;
    if (panelMode !== "view") return;

    if (typeof window.html2canvas !== "function") {
      UIStates.showToast(
        "Screenshot tool failed to load. Refresh and try again.",
        true,
      );
      return;
    }

    var contentEl = document.getElementById("dp-content");
    var loadingEl = document.getElementById("dp-loading");
    if (!contentEl || !contentEl.firstElementChild) {
      UIStates.showToast("Nothing to capture yet.", true);
      return;
    }
    if (loadingEl && loadingEl.style.display !== "none") {
      UIStates.showToast("Still loading workout…", true);
      return;
    }

    closeOverflowMenu();
    _detailScreenshotBusy = true;

    _promptLapModeIfNeeded(contentEl).then(function () {
      var shotBtn = document.getElementById("dp-screenshot-btn");
      if (shotBtn) shotBtn.disabled = true;

      var scrollEl = document.getElementById("dp-scroll");
      var savedScrollTop = scrollEl ? scrollEl.scrollTop : 0;
      if (scrollEl) scrollEl.scrollTop = 0;

      // Fixed 540px × scale 2 → 1080px PNG (Instagram post width).
      var captureWidth = 540;

      var host = document.createElement("div");
      host.className = "dp-screenshot-capture";
      host.setAttribute("aria-hidden", "true");
      host.style.cssText =
        "position:fixed;left:-10000px;top:0;width:" +
        captureWidth +
        "px;background:#fff;padding:0;box-sizing:border-box;pointer-events:none;";

      var clone = buildScreenshotClone(contentEl);
      host.appendChild(clone);
      document.body.appendChild(host);

      var overflowPatches = expandScreenshotOverflow(clone);

      window
        .html2canvas(host, {
          backgroundColor: "#ffffff",
          scale: 2,
          logging: false,
          useCORS: true,
          width: captureWidth,
          windowWidth: captureWidth,
        })
        .then(function (canvas) {
          return new Promise(function (resolve, reject) {
            canvas.toBlob(function (blob) {
              if (!blob) {
                reject(new Error("empty blob"));
                return;
              }
              resolve(blob);
            }, "image/png");
          });
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var link = document.createElement("a");
          link.href = url;
          link.download = buildDetailScreenshotFilename();
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
          UIStates.showToast("Workout saved as image");
        })
        .catch(function (err) {
          console.error("detail screenshot failed", err);
          UIStates.showToast("Could not save image. Try again.", true);
        })
        .finally(function () {
          restoreScreenshotOverflow(overflowPatches);
          if (host.parentNode) host.parentNode.removeChild(host);
          if (scrollEl) scrollEl.scrollTop = savedScrollTop;
          _detailScreenshotBusy = false;
          if (shotBtn) shotBtn.disabled = false;
        });
    });
  }

  // ── Fetch and render detail ───────────────────────────────────────────────
  function fetchAndRenderDetail(workoutId) {
    var loadingEl = document.getElementById("dp-loading");
    var errorEl = document.getElementById("dp-error");
    var contentEl = document.getElementById("dp-content");
    var scrollEl = document.getElementById("dp-scroll");

    if (loadingEl) loadingEl.style.display = "";
    if (errorEl) errorEl.style.display = "none";
    if (contentEl) contentEl.innerHTML = "";
    if (scrollEl) scrollEl.scrollTop = 0;

    updateOverflowMenu(null);

    fetch("/api/workouts/" + workoutId)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (workout) {
        cachedDetailWorkout = workout;
        updateOverflowMenu(workout);

        var _tk = normalizeTypeKey(workout.workout_type);
        var isRun = _tk === "run";
        var isBike = _tk === "bike";

        if (isRun) {
          // Redesigned run view draws from the union endpoint (power/splits/etc).
          // Combine with the cached prefs fetch so Zone 2 band reflects user settings.
          Promise.all([
            fetch("/api/workouts/" + workoutId + "/full?streams=none")
              .then(function (r) {
                return r.ok ? r.json() : null;
              })
              .catch(function () {
                return null;
              }),
            _userPrefsFetch,
            fetch("/api/sync/strava/latest")
              .then(function (r) {
                return r.ok ? r.json() : null;
              })
              .catch(function () {
                return null;
              }),
            fetch("/api/sync/stryd/latest")
              .then(function (r) {
                return r.ok ? r.json() : null;
              })
              .catch(function () {
                return null;
              }),
          ]).then(function (results) {
            var full = results[0];
            var prefs = results[1];
            var stravaLatest = results[2];
            var strydLatest = results[3];
            if (loadingEl) loadingEl.style.display = "none";
            if (full && full.workout)
              renderRunView(full, prefs, stravaLatest, strydLatest);
            else renderDetailContent(workout, []);
          });
        } else if (isBike) {
          fetch("/api/workouts/" + workoutId + "/splits")
            .then(function (r) {
              return r.ok ? r.json() : [];
            })
            .catch(function () {
              return [];
            })
            .then(function (splits) {
              if (loadingEl) loadingEl.style.display = "none";
              renderDetailContent(workout, splits);
            });
        } else {
          if (loadingEl) loadingEl.style.display = "none";
          renderDetailContent(workout, []);
        }
      })
      .catch(function (_) {
        cachedDetailWorkout = null;
        updateOverflowMenu(null);
        if (loadingEl) loadingEl.style.display = "none";
        if (errorEl) errorEl.style.display = "";
        var retryBtn = document.getElementById("dp-retry-btn");
        if (retryBtn) {
          retryBtn.onclick = function () {
            fetchAndRenderDetail(workoutId);
          };
        }
      });
  }

  // ── Detail view helpers (run + strength profile mockup) ─────────────────

  function _parseSetsJson(ex) {
    if (!ex.sets_json) return null;
    try {
      var arr = JSON.parse(ex.sets_json);
      return Array.isArray(arr) ? arr : null;
    } catch (e) {
      return null;
    }
  }

  function _rpeBarClass(rpe) {
    if (rpe == null || isNaN(rpe)) return "rpe-mid";
    if (rpe <= 5) return "rpe-low";
    if (rpe <= 7) return "rpe-mid";
    if (rpe <= 8.5) return "rpe-high";
    return "rpe-max";
  }

  function _rpeBarHeight(rpe) {
    if (rpe == null || isNaN(rpe)) return 45;
    return Math.max(22, Math.min(95, Math.round(18 + (rpe / 10) * 78)));
  }

  function _effortBarClass(intensity) {
    if (intensity === "tempo") return "tempo";
    if (intensity === "intervals") return "hard";
    if (intensity === "rest") return "recovery";
    return "easy";
  }

  function _calcExVolume(ex) {
    var sets = _parseSetsJson(ex);
    if (sets && sets.length) {
      return sets.reduce(function (v, s) {
        return v + (s.weight || 0) * (s.reps || 0);
      }, 0);
    }
    if (ex.weight_kg != null && ex.reps != null && ex.sets != null) {
      return ex.weight_kg * ex.reps * ex.sets;
    }
    return 0;
  }

  function _formatStrengthExSub(ex) {
    var sets = _parseSetsJson(ex);
    if (sets && sets.length) {
      var working = sets.filter(function (s) {
        return s.type !== "warmup";
      });
      var use = working.length ? working : sets;
      var n = use.length;
      var top = use.reduce(function (best, s) {
        return (s.weight || 0) > (best.weight || 0) ? s : best;
      }, use[0]);
      var w = top.weight != null ? top.weight + " kg" : "";
      var reps = top.reps != null ? top.reps : "";
      if (n && reps && w)
        return n + " sets \u00d7 " + reps + " reps \u00b7 " + w;
      if (n && reps) return n + " sets \u00d7 " + reps + " reps";
    }
    var sub = "";
    if (ex.sets != null && ex.reps != null)
      sub = ex.sets + " sets \u00d7 " + ex.reps + " reps";
    else if (ex.sets != null) sub = ex.sets + " sets";
    if (ex.weight_kg != null)
      sub += (sub ? " \u00b7 " : "") + ex.weight_kg + " kg";
    return sub || "\u2014";
  }

  function _avgRpeFromEx(ex) {
    var sets = _parseSetsJson(ex);
    if (sets && sets.length) {
      var withRpe = sets.filter(function (s) {
        return s.rpe != null;
      });
      if (withRpe.length) {
        var sum = withRpe.reduce(function (a, s) {
          return a + s.rpe;
        }, 0);
        return (sum / withRpe.length).toFixed(1);
      }
    }
    return ex.rpe != null ? String(ex.rpe) : null;
  }

  // Aggregate a numeric per-set field: show the common value when every set
  // agrees, otherwise the average (user preference: "if not the same, use avg").
  function _setAgg(values) {
    var nums = values.filter(function (v) {
      return v != null && !isNaN(v);
    });
    if (!nums.length) return { value: null, uniform: true };
    var first = nums[0];
    var uniform = nums.every(function (v) {
      return v === first;
    });
    if (uniform) return { value: first, uniform: true };
    var sum = nums.reduce(function (a, v) {
      return a + Number(v);
    }, 0);
    return { value: sum / nums.length, uniform: false };
  }

  // Build a per-exercise row summary for the strength detail table.
  function _strengthExRow(ex) {
    var sets = _parseSetsJson(ex);
    var use = null;
    if (sets && sets.length) {
      var working = sets.filter(function (s) {
        return s.type !== "warmup";
      });
      use = working.length ? working : sets;
    }
    var count, repsAgg, wAgg, rpeAgg;
    if (use) {
      count = use.length;
      repsAgg = _setAgg(use.map(function (s) { return s.reps; }));
      wAgg = _setAgg(use.map(function (s) { return s.weight; }));
      rpeAgg = _setAgg(use.map(function (s) { return s.rpe; }));
    } else {
      count = ex.sets != null ? ex.sets : null;
      repsAgg = { value: ex.reps != null ? ex.reps : null, uniform: true };
      wAgg = { value: ex.weight_kg != null ? ex.weight_kg : null, uniform: true };
      rpeAgg = { value: ex.rpe != null ? ex.rpe : null, uniform: true };
    }

    var setsTxt = "—";
    if (count != null) {
      if (repsAgg.value != null) {
        var repsTxt = repsAgg.uniform
          ? String(repsAgg.value)
          : "~" + Math.round(repsAgg.value);
        setsTxt = count + " × " + repsTxt;
      } else {
        setsTxt = count + (count === 1 ? " set" : " sets");
      }
    }

    var wTxt = "—";
    if (wAgg.value != null) {
      var wNum = wAgg.uniform ? wAgg.value : Math.round(wAgg.value);
      wTxt = (wAgg.uniform ? "" : "avg ") + wNum + " kg";
    }

    var rpeVal = rpeAgg.value;
    var rpeTxt = "—";
    if (rpeVal != null) {
      var rpeNum = rpeAgg.uniform ? rpeVal : Number(rpeVal).toFixed(1);
      rpeTxt = (rpeAgg.uniform ? "" : "avg ") + rpeNum;
    }

    var vol = _calcExVolume(ex);
    return {
      name: ex.name || "—",
      setsTxt: setsTxt,
      weightTxt: wTxt,
      rpeTxt: rpeTxt,
      rpeClass: _rpeBarClass(rpeVal),
      volTxt: vol > 0 ? Math.round(vol).toLocaleString() + " kg" : "—",
    };
  }

  function buildEffortProfileView(segData) {
    if (!segData || !segData.length) return "";
    var allTime = segData.every(function (s) {
      return s.totSec > 0;
    });
    var allDist = segData.every(function (s) {
      return s.totKm > 0;
    });
    var axis = allTime ? "time" : allDist ? "dist" : "equal";
    var axisTotal =
      segData.reduce(function (a, s) {
        return (
          a +
          (axis === "time" ? s.totSec || 0 : axis === "dist" ? s.totKm || 0 : 1)
        );
      }, 0) || 1;
    var bars = segData
      .map(function (s) {
        var mag =
          axis === "time" ? s.totSec || 0 : axis === "dist" ? s.totKm || 0 : 1;
        var pct = Math.max(mag / axisTotal, 0.04);
        var cls = _effortBarClass(s.intensity);
        var h =
          s.intensity === "intervals"
            ? 92
            : s.intensity === "tempo"
              ? 72
              : s.intensity === "rest"
                ? 26
                : 40;
        return (
          '<div class="dp-profile-bar ' +
          cls +
          '" style="flex:' +
          (pct * 1000).toFixed(0) +
          " 1 0;height:" +
          h +
          '%" title="' +
          esc(s.name) +
          '"></div>'
        );
      })
      .join("");
    return (
      '<div class="dp-profile-card">' +
      '<div class="dp-profile-head">' +
      '<span class="dp-profile-title">Session profile \u00b7 Effort</span>' +
      '<span class="dp-profile-sub">Height = effort</span>' +
      "</div>" +
      '<div class="dp-profile-chart">' +
      '<div class="dp-profile-bars">' +
      bars +
      "</div>" +
      '<div class="dp-profile-axis-x"><span>Start</span><span>Finish</span></div>' +
      "</div>" +
      '<div class="dp-profile-legend">' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#16a34a"></span>Easy</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#d97706"></span>Tempo</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#ea580c"></span>Hard</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#64748b"></span>Recovery</span>' +
      "</div>" +
      "</div>"
    );
  }

  function buildRpeProfileView(exercises) {
    var blocks = [];
    (exercises || []).forEach(function (ex) {
      var sets = _parseSetsJson(ex);
      var name = ex.name || "Exercise";
      if (sets && sets.length) {
        sets.forEach(function (s) {
          var rpe = s.rpe != null ? s.rpe : ex.rpe != null ? ex.rpe : 6;
          var w =
            s.rest && s.rest > 0
              ? s.rest + (s.reps || 5) * 4
              : (s.reps || 5) * 10 + 50;
          blocks.push({ label: name, rpe: rpe, width: w });
        });
      } else if (ex.sets || ex.reps) {
        blocks.push({
          label: name,
          rpe: ex.rpe != null ? ex.rpe : 6,
          width: 80,
        });
      }
    });
    if (!blocks.length) return "";
    var bars = blocks
      .map(function (b) {
        var cls = _rpeBarClass(b.rpe);
        var h = _rpeBarHeight(b.rpe);
        var tip = b.label + (b.rpe != null ? " \u00b7 " + b.rpe : "");
        return (
          '<div class="dp-profile-bar ' +
          cls +
          '" style="flex:' +
          b.width.toFixed(1) +
          " 1 0;height:" +
          h +
          '%" title="' +
          esc(tip) +
          '"></div>'
        );
      })
      .join("");
    return (
      '<div class="dp-profile-card">' +
      '<div class="dp-profile-head">' +
      '<span class="dp-profile-title">Session profile \u00b7 RPE \u00d7 duration</span>' +
      '<span class="dp-profile-sub">Width = time \u00b7 height = RPE</span>' +
      "</div>" +
      '<div class="dp-profile-chart">' +
      '<div class="dp-profile-bars">' +
      bars +
      "</div>" +
      '<div class="dp-profile-axis-x"><span>Start</span><span>Finish</span></div>' +
      "</div>" +
      '<div class="dp-profile-legend">' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#16a34a"></span>RPE \u22645</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#eab308"></span>6\u20137</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#ea580c"></span>8\u20139</span>' +
      '<span class="dp-leg"><span class="dp-leg-dot" style="background:#dc2626"></span>10</span>' +
      "</div>" +
      "</div>"
    );
  }

  // ── Render detail content ─────────────────────────────────────────────────
  // Clipboard fallback for non-secure contexts / older browsers.
  function _fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) {
      /* no-op */
    }
  }

  // ── Run VIEW (read-only, mock-matched) ─────────────────────────────────────
  // Zone-2 HR band. Module constants are the fallback; user-saved values from
  // GET /api/user-preferences take precedence when present (issue #598).
  var ZONE2_HR_MIN = 130;
  var ZONE2_HR_MAX = 155;

  // Fetch user preferences once per page load and cache the promise.
  // renderRunView reads zone2_hr_min/max from the resolved value.
  var _userPrefsFetch = fetch("/api/user-preferences")
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .catch(function () {
      return null;
    });

  function renderRunView(full, prefs, stravaLatest, strydLatest) {
    var contentEl = document.getElementById("dp-content");
    if (!contentEl || !window.RunDetailView) return;
    window.RunDetailView.render(contentEl, full, prefs, {
      stravaLatest: stravaLatest,
      strydLatest: strydLatest,
    });
  }

  function renderDetailContent(workout, splits) {
    var contentEl = document.getElementById("dp-content");
    if (!contentEl) return;

    var typeKey = normalizeTypeKey(workout.workout_type);
    var isRun = typeKey === "run";
    var isBike = typeKey === "bike";
    var isCardio = isRun || isBike;
    var exercises = workout.exercises || [];

    // ── Hero block ──────────────────────────────────────────────────────────
    var typeIcons = { run: "🏃", lift: "🏋️", wod: "🔥", bike: "🚴" };
    var typeLabels = { run: "Run", lift: "Lift", wod: "WOD", bike: "Bike" };
    var iconChar = typeIcons[typeKey] || "💪";
    var typeLabel =
      typeLabels[typeKey] || (workout.workout_type || "Workout").toUpperCase();

    var sourceHtml = "";
    var dpIsStrava = isStravaWorkout(workout);
    var dpIsStryd = !!workout.is_stryd_synced;
    if (dpIsStrava) {
      sourceHtml +=
        '<span class="dp-src-badge dp-src-badge--strava" title="strava">St</span>';
    }
    if (dpIsStryd) {
      sourceHtml +=
        '<span class="dp-src-badge dp-src-badge--stryd" title="stryd">S</span>';
    }
    if (!dpIsStrava && !dpIsStryd) {
      sourceHtml +=
        '<span class="dp-src-badge dp-src-badge--manual" title="manual">&#10002;</span>';
    }

    var heroHtml =
      '<div class="dp-hero">' +
      '<div class="dp-hero-typebadge">' +
      '<div class="dp-icon-pill dp-icon-pill--' +
      esc(typeKey || "other") +
      '">' +
      esc(iconChar) +
      "</div>" +
      '<span class="dp-type-pill">' +
      esc(typeLabel) +
      "</span>" +
      "</div>" +
      '<h1 id="dp-title">' +
      esc(workout.name || "Workout") +
      "</h1>" +
      (workout.id
        ? '<div class="dp-id-row">' +
          '<code class="dp-id" id="dp-id-value">' +
          esc(workout.id) +
          "</code>" +
          '<button type="button" class="dp-id-copy" id="dp-id-copy" aria-label="Copy workout ID" title="Copy ID">' +
          '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
          "</button>" +
          "</div>"
        : "") +
      '<div class="dp-hero-meta">' +
      esc(fmtDate(workout.workout_date)) +
      (sourceHtml
        ? '<span class="dp-hero-sources">' + sourceHtml + "</span>"
        : "") +
      "</div>" +
      "</div>";

    // ── Stats ─────────────────────────────────────────────────────────────────
    var statsHtml = "";
    if (isRun) {
      var hasDist = workout.distance_km != null;
      var hasPace = !!(workout.duration_seconds && workout.distance_km);
      var distVal = hasDist
        ? parseFloat((+workout.distance_km).toFixed(1))
        : null;
      var paceVal = null;
      if (hasPace) {
        var spk = workout.duration_seconds / workout.distance_km;
        paceVal = Math.floor(spk / 60) + ":" + pad(Math.round(spk % 60));
      }
      var m1v = hasDist
        ? distVal
        : workout.duration_seconds != null
          ? fmtDurationDetail(workout.duration_seconds)
          : "\u2014";
      var m1u = hasDist ? "km" : "";
      var m1l = hasDist ? "Distance" : "Duration";
      var m2v = hasPace
        ? paceVal
        : workout.avg_hr != null
          ? workout.avg_hr
          : "\u2014";
      var m2u = hasPace ? "/km" : workout.avg_hr != null ? "bpm" : "";
      var m2l = hasPace ? "Avg pace" : "Avg HR";
      var durLine =
        workout.duration_seconds != null
          ? '<div class="dp-run-duration"><span class="dp-run-duration-k">Duration</span>' +
            esc(fmtDurationDetail(workout.duration_seconds)) +
            "</div>"
          : "";
      statsHtml =
        '<div class="dp-section">' +
        '<div class="dp-run-hero">' +
        '<div class="dp-run-metric">' +
        '<div class="dp-run-metric-val">' +
        esc(String(m1v)) +
        (m1u ? '<span class="dp-run-metric-unit">' + m1u + "</span>" : "") +
        "</div>" +
        '<div class="dp-run-metric-label">' +
        esc(m1l) +
        "</div>" +
        "</div>" +
        '<div class="dp-run-metric">' +
        '<div class="dp-run-metric-val">' +
        esc(String(m2v)) +
        (m2u ? '<span class="dp-run-metric-unit">' + m2u + "</span>" : "") +
        "</div>" +
        '<div class="dp-run-metric-label">' +
        esc(m2l) +
        "</div>" +
        "</div>" +
        "</div>" +
        durLine +
        "</div>";
    } else if (isBike) {
      var distStr =
        workout.distance_km != null
          ? (+workout.distance_km).toFixed(2) +
            '<span class="dp-stat-unit">km</span>'
          : "\u2014";
      var durStr =
        workout.duration_seconds != null
          ? esc(fmtDurationDetail(workout.duration_seconds))
          : "\u2014";
      var spdStr =
        workout.duration_seconds && workout.distance_km
          ? esc(fmtSpeedKmh(workout.duration_seconds, workout.distance_km))
          : "\u2014";
      var hrStr =
        workout.avg_hr != null
          ? esc(workout.avg_hr) + '<span class="dp-stat-unit">bpm</span>'
          : "\u2014";
      var elevStr =
        workout.elevation_m != null
          ? esc(workout.elevation_m) + '<span class="dp-stat-unit">m</span>'
          : "\u2014";
      var tssStr =
        workout.tss != null ? esc((+workout.tss).toFixed(0)) : "\u2014";
      statsHtml =
        '<div class="dp-section">' +
        '<div class="dp-section-title">Stats</div>' +
        '<div class="dp-stats-grid">' +
        '<div class="dp-stat"><div class="dp-stat-label">Distance</div><div class="dp-stat-value">' +
        distStr +
        "</div></div>" +
        '<div class="dp-stat"><div class="dp-stat-label">Duration</div><div class="dp-stat-value">' +
        durStr +
        "</div></div>" +
        '<div class="dp-stat"><div class="dp-stat-label">Avg speed</div><div class="dp-stat-value">' +
        spdStr +
        "</div></div>" +
        '<div class="dp-stat"><div class="dp-stat-label">Avg HR</div><div class="dp-stat-value">' +
        hrStr +
        "</div></div>" +
        '<div class="dp-stat"><div class="dp-stat-label">Elev</div><div class="dp-stat-value">' +
        elevStr +
        "</div></div>" +
        '<div class="dp-stat"><div class="dp-stat-label">TSS</div><div class="dp-stat-value">' +
        tssStr +
        "</div></div>" +
        "</div>" +
        "</div>";
    } else {
      // Strength / WOD
      var durStr2 =
        workout.duration_seconds != null
          ? esc(fmtDurationDetail(workout.duration_seconds))
          : "\u2014";
      var exCount = exercises.length;
      var totalReps = exercises.reduce(function (s, ex) {
        var sets = _parseSetsJson(ex);
        if (sets && sets.length) {
          return (
            s +
            sets.reduce(function (a, set) {
              return a + (set.reps || 0);
            }, 0)
          );
        }
        return s + (ex.sets || 0) * (ex.reps || 0);
      }, 0);
      var rpeVals = [];
      exercises.forEach(function (ex) {
        var sets = _parseSetsJson(ex);
        if (sets)
          sets.forEach(function (set) {
            if (set.rpe != null) rpeVals.push(set.rpe);
          });
        else if (ex.rpe != null) rpeVals.push(ex.rpe);
      });
      var avgRpe = rpeVals.length
        ? (
            rpeVals.reduce(function (a, b) {
              return a + b;
            }, 0) / rpeVals.length
          ).toFixed(1)
        : null;
      var hrStr2 =
        workout.avg_hr != null ? esc(String(workout.avg_hr)) : "\u2014";
      var tssStr2 =
        workout.tss != null ? esc((+workout.tss).toFixed(0)) : "\u2014";

      function liftStat(val, lbl, hi) {
        return (
          '<div class="dp-lift-stat' +
          (hi ? " highlight" : "") +
          '">' +
          '<div class="dp-lift-stat-val">' +
          val +
          "</div>" +
          '<div class="dp-lift-stat-label">' +
          lbl +
          "</div></div>"
        );
      }
      statsHtml =
        '<div class="dp-section">' +
        '<div class="dp-lift-stats">' +
        liftStat(durStr2, "Duration", true) +
        liftStat(esc(String(exCount)), "Exercises", false) +
        liftStat(
          totalReps > 0 ? esc(String(totalReps)) : "\u2014",
          "Total reps",
          false,
        ) +
        liftStat(avgRpe != null ? esc(avgRpe) : "\u2014", "Avg RPE", false) +
        liftStat(hrStr2, "Avg HR", false) +
        liftStat(tssStr2, "TSS", false) +
        "</div>" +
        "</div>";
    }

    // ── Segments section (structured runs from the run builder) ─────────────
    var segmentsHtml = "";
    var segExs = exercises.filter(function (ex) {
      return RUN_SEGMENT_LABELS[(ex.name || "").toLowerCase()];
    });
    var isStructuredRun =
      isRun && segExs.length > 0 && segExs.length === exercises.length;
    if (isStructuredRun) {
      var segData = exercises.map(function (ex) {
        var sets = ex.sets != null ? ex.sets : null;
        var repKm = ex.distance_km != null ? parseFloat(ex.distance_km) : null;
        var repSec = ex.duration_seconds != null ? ex.duration_seconds : null;
        var mult = sets && sets > 0 ? sets : 1;
        return {
          name: ex.name,
          intensity:
            RUN_SEGMENT_INTENSITY[(ex.name || "").toLowerCase()] || "easy",
          sets: sets,
          repKm: repKm,
          repSec: repSec,
          mult: mult,
          hr: ex.avg_hr,
          totKm: repKm != null ? repKm * mult : null,
          totSec: repSec != null ? repSec * mult : null,
        };
      });

      var allTime = segData.every(function (s) {
        return s.totSec > 0;
      });
      var allDist = segData.every(function (s) {
        return s.totKm > 0;
      });
      var axis = allTime ? "time" : allDist ? "dist" : "equal";
      var axisTotal =
        segData.reduce(function (a, s) {
          return (
            a +
            (axis === "time"
              ? s.totSec || 0
              : axis === "dist"
                ? s.totKm || 0
                : 1)
          );
        }, 0) || 1;

      var tlBlocks = "";
      segData.forEach(function (s) {
        var mag =
          axis === "time" ? s.totSec || 0 : axis === "dist" ? s.totKm || 0 : 1;
        var pct = Math.max(mag / axisTotal, 0.02);
        var detail =
          axis === "time"
            ? fmtDurationDetail(Math.round(s.totSec || 0))
            : s.totKm != null
              ? parseFloat(s.totKm.toFixed(2)) + " km"
              : "";
        tlBlocks +=
          '<div class="dp-tl-seg dp-tl-seg--' +
          s.intensity +
          '" ' +
          'style="flex:' +
          (pct * 1000).toFixed(0) +
          ' 1 0;" ' +
          'title="' +
          esc(s.name + (detail ? " \u00b7 " + detail : "")) +
          '">' +
          '<span class="dp-tl-label">' +
          esc(s.name) +
          "</span>" +
          "</div>";
      });

      var sgRows = "";
      var sgKm = 0,
        sgSec = 0,
        sgHrs = [],
        sgHrSum = 0;
      segData.forEach(function (s) {
        if (s.totKm) sgKm += s.totKm;
        if (s.totSec) sgSec += s.totSec;
        if (s.hr != null) {
          sgHrs.push(s.hr);
          sgHrSum += s.hr;
        }
        var distFmt =
          s.repKm != null
            ? s.repKm >= 1
              ? (+s.repKm).toFixed(1) + " km"
              : Math.round(s.repKm * 1000) + "m"
            : null;
        var timeFmt = s.repSec != null ? fmtDurationDetail(s.repSec) : null;
        var qty =
          s.sets != null
            ? s.sets + " \u00d7 " + (distFmt || timeFmt || "\u2014")
            : [distFmt, timeFmt].filter(Boolean).join(" \u00b7 ") || "\u2014";
        var paceFmt =
          s.repSec && s.repKm ? fmtPaceFromSec(s.repSec, s.repKm) : "\u2014";
        sgRows +=
          '<div class="dp-seg-row">' +
          '<div class="dp-seg-dot dp-seg-dot--' +
          s.intensity +
          '"></div>' +
          "<div>" +
          '<div class="dp-interval-name">' +
          esc(s.name) +
          "</div>" +
          '<div class="dp-interval-sub">' +
          esc(qty) +
          "</div>" +
          "</div>" +
          '<div class="dp-seg-pace">' +
          (paceFmt !== "\u2014"
            ? '<span class="dp-seg-pace-at">@ </span>' + esc(paceFmt)
            : esc(paceFmt)) +
          "</div>" +
          '<div class="dp-interval-hr">' +
          (s.hr != null ? esc(s.hr + " bpm") : "") +
          "</div>" +
          "</div>";
      });

      var sgPace = sgSec && sgKm ? fmtPaceFromSec(sgSec, sgKm) : null;
      var sgHr = sgHrs.length
        ? Math.round(sgHrSum / sgHrs.length) + " bpm"
        : null;
      var footRight =
        [sgPace, sgHr].filter(Boolean).join(" \u00b7 ") || "\u2014";

      segmentsHtml =
        buildEffortProfileView(segData) +
        '<div class="dp-section">' +
        '<div class="dp-segments-card">' +
        '<div class="dp-segments-head">Segments</div>' +
        sgRows +
        '<div class="dp-seg-footer">' +
        "<span>Avg pace \u00b7 avg HR</span>" +
        "<strong>" +
        esc(footRight) +
        "</strong>" +
        "</div>" +
        "</div>" +
        "</div>";
    }

    // ── Intervals section (legacy runs with distance_km exercises) ──────────
    var intervalsHtml = "";
    if (isRun && !isStructuredRun) {
      var intervalExs = exercises.filter(function (ex) {
        return ex.distance_km != null;
      });
      if (intervalExs.length) {
        var totalRepDist = 0,
          totalRepDur = 0;
        var hrExs = [],
          hrSum = 0;
        var rows = "";
        intervalExs.forEach(function (ex, i) {
          var distKm = parseFloat(ex.distance_km);
          var dur = ex.duration_seconds;
          var hr = ex.avg_hr;
          totalRepDist += distKm || 0;
          totalRepDur += dur || 0;
          if (hr != null) {
            hrExs.push(hr);
            hrSum += hr;
          }

          var distFmt =
            distKm >= 1
              ? (+distKm).toFixed(1) + " km"
              : Math.round(distKm * 1000) + "m";
          var paceFmt = dur && distKm ? fmtPaceFromSec(dur, distKm) : "—";
          var hrFmt = hr != null ? hr + " bpm" : "—";

          rows +=
            '<div class="dp-interval-row">' +
            '<div class="dp-rep-badge">' +
            esc(String(i + 1)) +
            "</div>" +
            "<div>" +
            '<div class="dp-interval-name">' +
            esc(ex.name || "Rep " + (i + 1)) +
            "</div>" +
            '<div class="dp-interval-sub">' +
            esc(distFmt) +
            "</div>" +
            "</div>" +
            "<div>" +
            '<div class="dp-interval-pace">' +
            esc(paceFmt) +
            "</div>" +
            "</div>" +
            '<div class="dp-interval-hr">' +
            esc(hrFmt) +
            "</div>" +
            "</div>";
        });

        var avgRepPace =
          totalRepDur && totalRepDist
            ? fmtPaceFromSec(totalRepDur, totalRepDist)
            : "—";
        var avgRepHR = hrExs.length
          ? Math.round(hrSum / hrExs.length) + " bpm"
          : "—";

        intervalsHtml =
          '<div class="dp-section">' +
          '<div class="dp-section-title">Intervals · ' +
          esc(String(intervalExs.length)) +
          "×" +
          (function () {
            var d0 = parseFloat(intervalExs[0].distance_km);
            return d0 >= 1
              ? (+d0).toFixed(1) + "km"
              : Math.round(d0 * 1000) + "m";
          })() +
          "</div>" +
          '<div class="dp-intervals">' +
          rows +
          '<div class="dp-interval-footer">' +
          "<span>Avg rep pace · avg HR</span>" +
          "<span><strong>" +
          esc(avgRepPace) +
          "</strong> · <strong>" +
          esc(avgRepHR) +
          "</strong></span>" +
          "</div>" +
          "</div>" +
          "</div>";
      }
    }

    // ── Per-km splits section (RUN/BIKE, only if no interval exercises) ──────
    // issue #526: manual runs/bikes get an *editable* splits authoring surface
    // (mounted after innerHTML below); synced runs keep the read-only table.
    var splitsHtml = "";
    var dpIsManual = !dpIsStrava && !dpIsStryd;
    var splitsEditable =
      (isRun || isBike) && !intervalsHtml && !segmentsHtml && dpIsManual;
    if (
      (isRun || isBike) &&
      !intervalsHtml &&
      !segmentsHtml &&
      !splitsEditable &&
      splits &&
      splits.length
    ) {
      var splitRows = "";
      splits.forEach(function (s) {
        var distKm = parseFloat(s.distance_km);
        var pace =
          s.duration_seconds && distKm
            ? fmtPaceFromSec(s.duration_seconds, distKm)
            : "—";
        var hrFmt = s.avg_hr != null ? s.avg_hr + "" : "—";

        splitRows +=
          '<div class="dp-split-row">' +
          '<div class="dp-split-km">Km ' +
          esc(String(s.split_index)) +
          "</div>" +
          "<div></div>" +
          '<div class="dp-split-pace">' +
          esc(pace) +
          "</div>" +
          '<div class="dp-split-hr">' +
          esc(hrFmt) +
          "</div>" +
          "</div>";
      });

      splitsHtml =
        '<div class="dp-section">' +
        '<div class="dp-section-title">Per-km splits</div>' +
        '<div class="dp-splits">' +
        '<div class="dp-split-header">' +
        '<div>Km</div><div></div><div style="text-align:right">Pace</div><div style="text-align:right">HR</div>' +
        "</div>" +
        splitRows +
        "</div>" +
        "</div>";
    } else if (splitsEditable) {
      // Editable mount point — filled by mountSplitsEditor() after innerHTML set.
      splitsHtml =
        '<div class="dp-section" id="dp-splits-section">' +
        '<div class="dp-section-title">Per-km splits</div>' +
        '<div id="dp-splits-mount"></div>' +
        "</div>";
    }

    // ── Exercises section (LIFT / WOD) ─────────────────────────────────────
    var exercisesHtml = "";
    if (!isCardio && exercises.length) {
      var rpeProfile = buildRpeProfileView(exercises);
      var totalVol = 0;
      var rpeSum = 0,
        rpeCount = 0;
      var exRows = "";
      exercises.forEach(function (ex) {
        totalVol += _calcExVolume(ex);
        var rpe = _avgRpeFromEx(ex);
        if (rpe != null) {
          rpeSum += parseFloat(rpe);
          rpeCount += 1;
        }
        var r = _strengthExRow(ex);
        exRows +=
          "<tr>" +
          '<td class="dp-ex-td-name">' + esc(r.name) + "</td>" +
          '<td class="dp-ex-td-num">' + esc(r.setsTxt) + "</td>" +
          '<td class="dp-ex-td-num">' + esc(r.weightTxt) + "</td>" +
          '<td class="dp-ex-td-num">' +
          (r.rpeTxt !== "\u2014"
            ? '<span class="dp-ex-rpe-pill ' + r.rpeClass + '">' + esc(r.rpeTxt) + "</span>"
            : "\u2014") +
          "</td>" +
          '<td class="dp-ex-td-num">' + esc(r.volTxt) + "</td>" +
          "</tr>";
      });
      var avgRpeFoot = rpeCount ? (rpeSum / rpeCount).toFixed(1) : "\u2014";
      var volFoot =
        totalVol > 0 ? Math.round(totalVol).toLocaleString() + " kg" : "\u2014";
      exercisesHtml =
        '<div class="dp-section">' +
        rpeProfile +
        '<div class="dp-section-title">Exercises</div>' +
        '<div class="dp-ex-table-wrap"><table class="dp-ex-table">' +
        "<thead><tr>" +
        "<th>Exercise</th><th>Sets</th><th>Weight</th><th>RPE</th><th>Volume</th>" +
        "</tr></thead><tbody>" +
        exRows +
        "</tbody></table></div>" +
        '<div class="dp-seg-footer" style="margin-top:10px;border-radius:10px;">' +
        "<span>Total volume \u00b7 avg RPE</span>" +
        "<strong>" +
        esc(volFoot) +
        " \u00b7 " +
        esc(avgRpeFoot) +
        "</strong>" +
        "</div>" +
        "</div>";
    }

    // ── Notes section ────────────────────────────────────────────────────────
    var notesHtml = "";
    if (workout.remarks) {
      notesHtml =
        '<div class="dp-section">' +
        '<div class="dp-section-title">Notes</div>' +
        '<p class="dp-notes-card">' +
        esc(workout.remarks) +
        "</p>" +
        "</div>";
    }

    contentEl.innerHTML =
      '<div class="dp-view-stack">' +
      heroHtml +
      statsHtml +
      segmentsHtml +
      intervalsHtml +
      splitsHtml +
      exercisesHtml +
      notesHtml +
      "</div>";

    // Workout-id copy button (dev/testing helper — grab the id for /api/workouts/{id}/full).
    var copyBtn = document.getElementById("dp-id-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var wid = workout.id || "";
        var flash = function () {
          copyBtn.classList.add("dp-id-copy--done");
          copyBtn.setAttribute("title", "Copied!");
          setTimeout(function () {
            copyBtn.classList.remove("dp-id-copy--done");
            copyBtn.setAttribute("title", "Copy ID");
          }, 1200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard
            .writeText(wid)
            .then(flash)
            .catch(function () {
              _fallbackCopy(wid);
              flash();
            });
        } else {
          _fallbackCopy(wid);
          flash();
        }
      });
    }

    // issue #526: mount the editable manual-split authoring surface.
    if (splitsEditable) mountSplitsEditor(workout, splits);
  }

  // ── Manual split authoring (issue #526) ────────────────────────────────────
  // Editable splits surface for MANUAL runs/bikes. Reuses the synced split
  // table component (dp-splits / dp-split-row) plus an editable variant, so
  // there is no separate UI path (AC4). Saved splits, edit-in-place, per-row
  // delete and an Add Split control all funnel through one full-replace POST to
  // /api/workouts/{id}/splits (the endpoint replaces the whole set per call).
  function mountSplitsEditor(workout, initialSplits) {
    var mount = document.getElementById("dp-splits-mount");
    if (!mount) return;

    var totalKm =
      workout.distance_km != null ? parseFloat(workout.distance_km) : null;

    // Working copy of the current splits (mutated locally, then persisted).
    var rows = (initialSplits || []).map(function (s) {
      return {
        distance_km: parseFloat(s.distance_km),
        duration_seconds: s.duration_seconds,
        avg_hr: s.avg_hr != null ? s.avg_hr : null,
      };
    });

    var editing = -1; // index of the row in edit mode, or -1
    var adding = false; // whether the new-row form is open
    var saving = false; // in-flight POST guard

    function sumKmExcept(exceptIdx) {
      return rows.reduce(function (acc, r, i) {
        return i === exceptIdx ? acc : acc + (r.distance_km || 0);
      }, 0);
    }

    // Full-replace POST of the working set; split_index re-numbered 1..n.
    function persist() {
      var payload = {
        splits: rows.map(function (r, i) {
          return {
            split_index: i + 1,
            distance_km: r.distance_km,
            duration_seconds: r.duration_seconds,
            avg_hr: r.avg_hr != null ? r.avg_hr : null,
          };
        }),
      };
      return fetch("/api/workouts/" + workout.id + "/splits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (res) {
        return res
          .json()
          .catch(function () {
            return [];
          })
          .then(function (data) {
            return { ok: res.ok, status: res.status, data: data };
          });
      });
    }

    function showError(msg) {
      var errEl = mount.querySelector(".dp-split-error");
      if (errEl) {
        errEl.textContent = msg;
        errEl.style.display = "";
      }
    }

    // Read + validate one edit/add form. Returns a row object or null (and
    // surfaces a field-level message). `exceptIdx` excludes the row being
    // edited from the running distance total.
    function readForm(exceptIdx) {
      var distInput = mount.querySelector(".dp-split-dist-input");
      var durInput = mount.querySelector(".dp-split-dur-input");
      var hrInput = mount.querySelector(".dp-split-hr-input");

      var distKm = parseFloat(((distInput && distInput.value) || "").trim());
      if (isNaN(distKm) || distKm <= 0) {
        showError("distance_km must be > 0");
        if (distInput) distInput.classList.add("dp-split-input--invalid");
        return null;
      }

      var durSecs = parseDurationStr(durInput && durInput.value);
      if (durSecs == null || durSecs <= 0) {
        showError("Enter a valid duration (m:ss)");
        if (durInput) durInput.classList.add("dp-split-input--invalid");
        return null;
      }

      var hrRaw = ((hrInput && hrInput.value) || "").trim();
      var hr = null;
      if (hrRaw !== "") {
        hr = parseInt(hrRaw, 10);
        if (isNaN(hr) || hr < 20 || hr > 250) {
          showError("avg_hr must be between 20 and 250");
          if (hrInput) hrInput.classList.add("dp-split-input--invalid");
          return null;
        }
      }

      if (totalKm != null && sumKmExcept(exceptIdx) + distKm > totalKm + 1e-9) {
        showError("Splits exceed total workout distance");
        if (distInput) distInput.classList.add("dp-split-input--invalid");
        return null;
      }

      return { distance_km: distKm, duration_seconds: durSecs, avg_hr: hr };
    }

    function commit(row, idx) {
      if (saving) return;
      saving = true;
      var prev = rows.slice();
      if (idx == null) rows.push(row);
      else rows[idx] = row;
      persist()
        .then(function (result) {
          saving = false;
          if (!result.ok) {
            rows = prev; // roll back the optimistic mutation
            var detail =
              (result.data && result.data.detail) || "Could not save splits.";
            showError(
              typeof detail === "string" ? detail : "Could not save splits.",
            );
            return;
          }
          // Reflect the server's canonical set immediately (no page reload).
          rows = (result.data || []).map(function (s) {
            return {
              distance_km: parseFloat(s.distance_km),
              duration_seconds: s.duration_seconds,
              avg_hr: s.avg_hr != null ? s.avg_hr : null,
            };
          });
          editing = -1;
          adding = false;
          render();
          if (window.UIStates && UIStates.showToast)
            UIStates.showToast("Splits saved");
        })
        .catch(function () {
          saving = false;
          rows = prev;
          showError("Could not save splits.");
        });
    }

    function removeAt(idx) {
      if (saving) return;
      saving = true;
      var prev = rows.slice();
      rows.splice(idx, 1);
      persist()
        .then(function (result) {
          saving = false;
          if (!result.ok) {
            rows = prev;
            var detail =
              (result.data && result.data.detail) || "Could not delete split.";
            showError(
              typeof detail === "string" ? detail : "Could not delete split.",
            );
            render();
            return;
          }
          rows = (result.data || []).map(function (s) {
            return {
              distance_km: parseFloat(s.distance_km),
              duration_seconds: s.duration_seconds,
              avg_hr: s.avg_hr != null ? s.avg_hr : null,
            };
          });
          editing = -1;
          adding = false;
          render();
          if (window.UIStates && UIStates.showToast)
            UIStates.showToast("Split deleted");
        })
        .catch(function () {
          saving = false;
          rows = prev;
          showError("Could not delete split.");
        });
    }

    // Build the input cells shared by the edit and add forms.
    function formCells(row) {
      var distVal = row ? String(row.distance_km) : "";
      var durVal = row ? TF.formatDuration(row.duration_seconds) || "" : "";
      var hrVal = row && row.avg_hr != null ? String(row.avg_hr) : "";
      return (
        "" +
        '<input class="dp-split-input dp-split-dist-input" type="number" step="0.01" min="0" ' +
        'placeholder="km" value="' +
        esc(distVal) +
        '" aria-label="Split distance (km)">' +
        '<input class="dp-split-input dp-split-dur-input" type="text" ' +
        'placeholder="m:ss" value="' +
        esc(durVal) +
        '" aria-label="Split duration (m:ss)">' +
        '<input class="dp-split-input dp-split-hr-input" type="number" step="1" min="20" max="250" ' +
        'placeholder="HR" value="' +
        esc(hrVal) +
        '" aria-label="Split avg HR (optional)">'
      );
    }

    function render() {
      var html = '<div class="dp-splits dp-splits--editable">';
      html +=
        '<div class="dp-split-header">' +
        '<div>Km</div><div>Dist</div><div style="text-align:right">Pace</div><div></div>' +
        "</div>";

      rows.forEach(function (r, i) {
        if (editing === i) {
          html +=
            '<div class="dp-split-row dp-split-edit-row" data-idx="' +
            i +
            '">' +
            '<div class="dp-split-km">Km ' +
            (i + 1) +
            "</div>" +
            formCells(r) +
            '<div class="dp-split-row-actions">' +
            '<button type="button" class="dp-split-btn dp-split-save" data-idx="' +
            i +
            '">Save</button>' +
            '<button type="button" class="dp-split-btn dp-split-cancel">Cancel</button>' +
            "</div>" +
            "</div>";
        } else {
          var pace =
            r.duration_seconds && r.distance_km
              ? fmtPaceFromSec(r.duration_seconds, r.distance_km)
              : "—";
          var distLbl =
            r.distance_km != null && !isNaN(r.distance_km)
              ? parseFloat(r.distance_km.toFixed(2)) + " km"
              : "—";
          html +=
            '<div class="dp-split-row" data-idx="' +
            i +
            '">' +
            '<div class="dp-split-km">Km ' +
            (i + 1) +
            "</div>" +
            '<div class="dp-split-dist">' +
            esc(distLbl) +
            "</div>" +
            '<div class="dp-split-pace">' +
            esc(pace) +
            "</div>" +
            '<div class="dp-split-row-actions">' +
            '<button type="button" class="dp-split-btn dp-split-edit" data-idx="' +
            i +
            '" aria-label="Edit split">Edit</button>' +
            '<button type="button" class="dp-split-btn dp-split-delete" data-idx="' +
            i +
            '" aria-label="Delete split">Delete</button>' +
            "</div>" +
            "</div>";
        }
      });

      if (adding) {
        html +=
          '<div class="dp-split-row dp-split-edit-row dp-split-add-row">' +
          '<div class="dp-split-km">Km ' +
          (rows.length + 1) +
          "</div>" +
          formCells(null) +
          '<div class="dp-split-row-actions">' +
          '<button type="button" class="dp-split-btn dp-split-save-new">Save</button>' +
          '<button type="button" class="dp-split-btn dp-split-cancel">Cancel</button>' +
          "</div>" +
          "</div>";
      }

      html += "</div>"; // .dp-splits
      html +=
        '<div class="dp-split-error" role="alert" style="display:none"></div>';
      if (!adding && editing === -1) {
        html +=
          '<button type="button" class="dp-split-btn dp-split-add">+ Add Split</button>';
      }
      mount.innerHTML = html;
      wire();
    }

    function wire() {
      var addBtn = mount.querySelector(".dp-split-add");
      if (addBtn)
        addBtn.addEventListener("click", function () {
          adding = true;
          editing = -1;
          render();
        });

      var saveNew = mount.querySelector(".dp-split-save-new");
      if (saveNew)
        saveNew.addEventListener("click", function () {
          var row = readForm(null);
          if (row) commit(row, null);
        });

      Array.prototype.forEach.call(
        mount.querySelectorAll(".dp-split-edit"),
        function (btn) {
          btn.addEventListener("click", function () {
            editing = parseInt(btn.getAttribute("data-idx"), 10);
            adding = false;
            render();
          });
        },
      );

      Array.prototype.forEach.call(
        mount.querySelectorAll(".dp-split-save"),
        function (btn) {
          btn.addEventListener("click", function () {
            var idx = parseInt(btn.getAttribute("data-idx"), 10);
            var row = readForm(idx);
            if (row) commit(row, idx);
          });
        },
      );

      Array.prototype.forEach.call(
        mount.querySelectorAll(".dp-split-delete"),
        function (btn) {
          btn.addEventListener("click", function () {
            removeAt(parseInt(btn.getAttribute("data-idx"), 10));
          });
        },
      );

      Array.prototype.forEach.call(
        mount.querySelectorAll(".dp-split-cancel"),
        function (btn) {
          btn.addEventListener("click", function () {
            editing = -1;
            adding = false;
            render();
          });
        },
      );
    }

    render();
  }

  // ── Delete workout ────────────────────────────────────────────────────────
  function deleteWorkout(workoutId, isSynced) {
    var msg = isSynced
      ? "Remove this workout from your log? It won't be re-synced from Strava/Stryd. You can restore it later from Removed workouts."
      : "Delete this workout? This cannot be undone.";
    if (!confirm(msg)) return;

    fetch("/api/workouts/" + workoutId, { method: "DELETE" })
      .then(function (res) {
        if (!res.ok && res.status !== 204)
          throw new Error("HTTP " + res.status);
        UIStates.showToast(isSynced ? "Removed from log" : "Workout deleted");
        closeDetailPanel();
        if (removeWorkoutInPlace(workoutId)) {
          rerenderListInPlace();
        } else {
          fetchAndRender();
        }
      })
      .catch(function () {
        UIStates.showToast("Could not remove workout. Please try again.", true);
      });
  }

  // ── Removed workouts modal (restore tombstoned synced activities) ─────────
  function openRemovedModal() {
    var modal = document.getElementById("removed-modal");
    if (!modal) return;
    modal.hidden = false;
    loadRemovedList();
  }

  function closeRemovedModal() {
    var modal = document.getElementById("removed-modal");
    if (modal) modal.hidden = true;
  }

  function loadRemovedList() {
    var list = document.getElementById("removed-modal-list");
    if (!list) return;
    list.innerHTML = '<div class="removed-empty">Loading…</div>';
    fetch("/api/workouts/removed")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (rows) {
        if (!rows || !rows.length) {
          list.innerHTML = '<div class="removed-empty">No removed workouts.</div>';
          return;
        }
        list.innerHTML = "";
        rows.forEach(function (r) {
          var row = document.createElement("div");
          row.className = "removed-row";
          var src = (r.source || "").toLowerCase();
          var meta = [fmtDate(r.workout_date), src ? src.charAt(0).toUpperCase() + src.slice(1) : ""]
            .filter(Boolean).join(" · ");
          row.innerHTML =
            '<div class="removed-row-info">' +
            '<div class="removed-row-name">' + esc(r.name || "Workout") + "</div>" +
            '<div class="removed-row-meta">' + esc(meta) + "</div>" +
            "</div>" +
            '<button class="removed-row-restore" type="button">Restore</button>';
          row.querySelector(".removed-row-restore").addEventListener("click", function () {
            restoreRemoved(r.id, row);
          });
          list.appendChild(row);
        });
      })
      .catch(function () {
        list.innerHTML = '<div class="removed-empty">Could not load removed workouts.</div>';
      });
  }

  function restoreRemoved(removedId, rowEl) {
    var btn = rowEl ? rowEl.querySelector(".removed-row-restore") : null;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Restoring…";
    }
    fetch("/api/workouts/removed/" + removedId + "/restore", { method: "POST" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        UIStates.showToast("Workout restored");
        if (rowEl && rowEl.parentNode) rowEl.parentNode.removeChild(rowEl);
        var list = document.getElementById("removed-modal-list");
        if (list && !list.querySelector(".removed-row"))
          list.innerHTML = '<div class="removed-empty">No removed workouts.</div>';
        fetchAndRender();
      })
      .catch(function () {
        UIStates.showToast("Could not restore workout. Please try again.", true);
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Restore";
        }
      });
  }

  function wireRemovedModal() {
    var openBtn = document.getElementById("log-removed-btn");
    if (openBtn) openBtn.addEventListener("click", openRemovedModal);
    var closeBtn = document.getElementById("removed-modal-close");
    if (closeBtn) closeBtn.addEventListener("click", closeRemovedModal);
    var backdrop = document.getElementById("removed-modal-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeRemovedModal);
  }

  // ── Swipe gesture support (mobile) ───────────────────────────────────────
  function initSwipe() {
    var panel = document.getElementById("dp-scroll");
    if (!panel) return;

    var touchStartX = 0,
      touchStartY = 0;

    panel.addEventListener(
      "touchstart",
      function (e) {
        if (e.touches.length !== 1) return;
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
      },
      { passive: true },
    );

    panel.addEventListener(
      "touchend",
      function (e) {
        if (isDesktop()) return;
        var dx = e.changedTouches[0].clientX - touchStartX;
        var dy = e.changedTouches[0].clientY - touchStartY;
        if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        if (dx < 0)
          navigateDetail(1); // swipe left → next
        else navigateDetail(-1); // swipe right → prev
      },
      { passive: true },
    );
  }

  // ── Sync button state ─────────────────────────────────────────────────────
  var _syncPollTimer = null;
  var _syncLastTerminalStatus = null;

  function _relTime(isoStr) {
    if (!isoStr) return "Never";
    var diff = Date.now() - new Date(isoStr).getTime();
    var secs = Math.floor(diff / 1000);
    if (secs < 60) return "just now";
    var mins = Math.floor(secs / 60);
    if (mins < 60) return mins + "m ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    return Math.floor(hrs / 24) + "d ago";
  }

  function _loadSyncChip() {
    var elStrava = document.getElementById("sync-time-strava");
    var elStryd = document.getElementById("sync-time-stryd");
    Promise.all([
      fetch("/api/sync/strava/latest")
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .catch(function () {
          return null;
        }),
      fetch("/api/sync/stryd/latest")
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .catch(function () {
          return null;
        }),
    ]).then(function (results) {
      if (elStrava)
        elStrava.textContent = _relTime(results[0] && results[0].synced_at);
      if (elStryd)
        elStryd.textContent = _relTime(results[1] && results[1].synced_at);
    });
  }

  function _syncSetBusy(busy) {
    ["sync-btn-strava", "sync-btn-stryd", "sync-all-btn", "sync-strava-btn"].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.disabled = busy;
    });
    var toggleBtn = document.getElementById("sync-toggle-btn");
    if (toggleBtn) toggleBtn.disabled = busy;
  }

  function _syncToast(msg, isError) {
    var fb = document.getElementById("log-sync-feedback");
    if (fb) {
      fb.textContent = msg;
      fb.className = isError ? "sync-feedback--error" : "sync-feedback--ok";
    }
    if (window.UIStates && UIStates.showToast) {
      UIStates.showToast(msg, isError);
    }
  }

  function _syncClearFeedback() {
    var fb = document.getElementById("log-sync-feedback");
    if (fb) {
      fb.textContent = "";
      fb.className = "";
    }
  }

  function _syncTerminalKey(data) {
    if (!data) return "";
    return (
      String(data.status || "") +
      "|" +
      String(data.finished_at || "") +
      "|" +
      String(data.error || "")
    );
  }

  function _syncHandleTerminal(data, opts) {
    opts = opts || {};
    if (!data || data.status === "running" || data.status === "idle") return;
    var key = _syncTerminalKey(data);
    if (key && key === _syncLastTerminalStatus) return;
    _syncLastTerminalStatus = key;

    if (data.status === "error") {
      _syncToast(data.error || "Sync failed", true);
      _loadSyncChip();
      if (opts.refreshList !== false) fetchAndRender();
      return;
    }
    if (data.status === "success" && opts.toastSuccess) {
      _syncToast("Sync complete");
      _loadSyncChip();
      if (opts.refreshList !== false) fetchAndRender();
    }
  }

  function _syncPollStatus() {
    fetch("/api/sync/status")
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (data) {
        if (!data) {
          _syncStopStatusPoll();
          _syncSetBusy(false);
          return;
        }
        if (data.status === "running") {
          _syncSetBusy(true);
          if (!_syncPollTimer) {
            _syncPollTimer = setInterval(_syncPollStatus, 3000);
          }
        } else {
          _syncStopStatusPoll();
          _syncSetBusy(false);
          _syncHandleTerminal(data, { toastSuccess: false });
        }
      })
      .catch(function () {
        _syncStopStatusPoll();
        _syncSetBusy(false);
      });
  }

  function _syncStopStatusPoll() {
    if (_syncPollTimer) {
      clearInterval(_syncPollTimer);
      _syncPollTimer = null;
    }
  }

  function _syncApiError(r) {
    return r.text().then(function (text) {
      var msg = text || "HTTP " + r.status;
      try {
        var parsed = JSON.parse(text);
        if (parsed && parsed.detail) {
          msg = typeof parsed.detail === "string"
            ? parsed.detail
            : JSON.stringify(parsed.detail);
        }
      } catch (e) { /* keep raw text */ }
      return msg;
    });
  }

  function _syncFriendlyMsg(msg) {
    if (msg === "CSRF token missing or invalid") {
      return "Session security token expired — reload the page and try again.";
    }
    return msg;
  }

  function _syncWaitForComplete() {
    return new Promise(function (resolve, reject) {
      function poll() {
        fetch("/api/sync/status")
          .then(function (res) {
            return res.ok ? res.json() : null;
          })
          .then(function (data) {
            if (!data || data.status === "idle") {
              resolve();
              return;
            }
            if (data.status === "error") {
              reject(new Error(data.error || "Sync failed"));
              return;
            }
            if (data.status !== "running") {
              resolve();
              return;
            }
            setTimeout(poll, 2000);
          })
          .catch(function () {
            resolve();
          });
      }
      poll();
    });
  }

  function _syncBuildBody(options) {
    options = options || {};
    if (options.full) return JSON.stringify({ full: true });
    if (options.sinceDate) return JSON.stringify({ since_date: options.sinceDate });
    return "{}";
  }

  function _syncProvider(label, url, options) {
    var body = _syncBuildBody(options);
    var start = window.ensureCsrfReady
      ? window.ensureCsrfReady(true)
      : Promise.resolve();
    return start
      .then(function () {
        return fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body,
        });
      })
      .then(function (r) {
        if (r.status === 202 || r.status === 409) {
          return _syncWaitForComplete();
        }
        if (!r.ok) {
          return _syncApiError(r).then(function (msg) {
            throw new Error(label + ": " + _syncFriendlyMsg(msg));
          });
        }
        return null;
      });
  }

  function _syncAllProviders() {
    var incremental = { full: false };
    var errors = [];

    return _syncProvider("Strava", "/api/strava/sync", incremental)
      .catch(function (err) {
        errors.push((err && err.message) || "Strava: Sync failed");
      })
      .then(function () {
        return _syncProvider("Stryd", "/api/stryd/sync", incremental).catch(function (err) {
          errors.push((err && err.message) || "Stryd: Sync failed");
        });
      })
      .then(function () {
        if (errors.length) throw new Error(errors.join(" · "));
      });
  }

  function _onSyncAllClick() {
    _syncClearFeedback();
    _syncSetBusy(true);
    var ready = window.ensureCsrfReady ? window.ensureCsrfReady(true) : Promise.resolve();
    ready
      .then(function () {
        return _syncAllProviders();
      })
      .then(function () {
        if (window.syncBarRefresh) window.syncBarRefresh();
        return fetch("/api/sync/status")
          .then(function (r) {
            return r.ok ? r.json() : null;
          })
          .then(function (data) {
            if (data && data.status === "error") {
              throw new Error(data.error || "Sync failed");
            }
            _syncLastTerminalStatus = _syncTerminalKey(
              data && data.status === "success" ? data : { status: "success", finished_at: "manual" },
            );
            _loadSyncChip();
            fetchAndRender();
            _syncToast("Sync complete");
          });
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : "Sync failed";
        _syncToast(msg, true);
      })
      .finally(function () {
        _syncSetBusy(false);
      });
  }

  function _onSyncStravaClick() {
    _onSyncAllClick();
  }

  function _onSyncProviderClick(label, url) {
    _syncClearFeedback();
    _syncSetBusy(true);
    var ready = window.ensureCsrfReady ? window.ensureCsrfReady(true) : Promise.resolve();
    ready
      .then(function () {
        return _syncProvider(label, url, { full: false });
      })
      .then(function () {
        if (window.syncBarRefresh) window.syncBarRefresh();
        return fetch("/api/sync/status")
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (data && data.status === "error") {
              throw new Error(data.error || "Sync failed");
            }
            _syncLastTerminalStatus = _syncTerminalKey(
              data && data.status === "success" ? data : { status: "success", finished_at: "manual" }
            );
            _loadSyncChip();
            fetchAndRender();
            _syncToast(label + ": synced new activities");
          });
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : "Sync failed";
        _syncToast(msg, true);
      })
      .finally(function () {
        _syncSetBusy(false);
      });
  }

  function _initSyncWidget() {
    var toggleBtn = document.getElementById("sync-toggle-btn");
    var panel = document.getElementById("sync-panel");
    if (!toggleBtn || !panel) return;

    toggleBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = !panel.hidden;
      panel.hidden = isOpen;
      toggleBtn.setAttribute("aria-expanded", String(!isOpen));
    });

    document.addEventListener("click", function (e) {
      if (!panel.hidden && !panel.contains(e.target) && e.target !== toggleBtn) {
        panel.hidden = true;
        toggleBtn.setAttribute("aria-expanded", "false");
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !panel.hidden) {
        panel.hidden = true;
        toggleBtn.setAttribute("aria-expanded", "false");
      }
    });

    Promise.all([
      fetch("/api/strava/status").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch("/api/stryd/status").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    ]).then(function (results) {
      var stravaConnected = results[0] && results[0].connected;
      var strydConnected = results[1] && results[1].connected;
      var stravaBtn = document.getElementById("sync-btn-strava");
      var strydBtn = document.getElementById("sync-btn-stryd");
      var stravaTimeEl = document.getElementById("sync-time-strava");
      var strydTimeEl = document.getElementById("sync-time-stryd");
      if (!stravaConnected) {
        if (stravaBtn) stravaBtn.disabled = true;
        if (stravaTimeEl) stravaTimeEl.textContent = "Not connected";
      }
      if (!strydConnected) {
        if (strydBtn) strydBtn.disabled = true;
        if (strydTimeEl) strydTimeEl.textContent = "Not connected";
      }
    });

    var stravaBtn = document.getElementById("sync-btn-strava");
    if (stravaBtn) {
      stravaBtn.addEventListener("click", function () {
        panel.hidden = true;
        toggleBtn.setAttribute("aria-expanded", "false");
        _onSyncProviderClick("Strava", "/api/strava/sync");
      });
    }

    var strydBtn = document.getElementById("sync-btn-stryd");
    if (strydBtn) {
      strydBtn.addEventListener("click", function () {
        panel.hidden = true;
        toggleBtn.setAttribute("aria-expanded", "false");
        _onSyncProviderClick("Stryd", "/api/stryd/sync");
      });
    }
  }

  function handleEditorSaved(result) {
    if (!result || !result.ok) return;

    if (result.isEdit && activeDetailWorkoutId) {
      setPanelMode("view");
      fetchAndRenderDetail(activeDetailWorkoutId);
      if (result.data && patchWorkoutInPlace(result.data)) {
        rerenderListInPlace();
      } else {
        fetchAndRender();
      }
    } else {
      var newId = result.data && result.data.id;
      closeDetailPanel();
      fetchAndRender();
      if (newId) {
        setTimeout(function () {
          var row = document.querySelector(
            '.entry-row[data-workout-id="' + newId + '"]',
          );
          openDetailPanel(newId, row);
        }, 100);
      }
    }
    refreshRepeatAvailability();
  }

  function wirePanelForm() {
    var newBtn = document.getElementById("log-new-btn");
    if (newBtn)
      newBtn.addEventListener("click", function () {
        openPanelCreate(createPresetDate());
      });

    wireRemovedModal();

    var emptyCta = document.getElementById("log-empty-cta");
    if (emptyCta)
      emptyCta.addEventListener("click", function () {
        openPanelCreate(createPresetDate());
      });

    document.querySelectorAll(".log-history-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        if (tab.dataset.tab === "new") {
          openPanelCreate(createPresetDate());
        } else {
          setHistoryTab("history");
        }
      });
    });

    var saveBtn = document.getElementById("dp-save-btn");
    if (saveBtn && window.TrainingEditor) {
      saveBtn.addEventListener("click", function () {
        TrainingEditor.saveWorkout();
      });
    }

    var cancelBtn = document.getElementById("dp-cancel-btn");
    if (cancelBtn) cancelBtn.addEventListener("click", cancelPanelForm);

    if (window.TrainingEditor) {
      TrainingEditor.setHooks({ onSaved: handleEditorSaved });
    }

    var screenshotBtn = document.getElementById("dp-screenshot-btn");
    if (screenshotBtn) {
      screenshotBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        saveDetailScreenshot();
      });
    }

    var overflowBtn = document.getElementById("dp-overflow-btn");
    if (overflowBtn) {
      overflowBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleOverflowMenu();
      });
    }

    var menuEdit = document.getElementById("dp-menu-edit");
    if (menuEdit) menuEdit.addEventListener("click", switchToEditMode);

    var menuDup = document.getElementById("dp-menu-duplicate");
    if (menuDup)
      menuDup.addEventListener("click", function () {
        closeOverflowMenu();
        openDuplicateModal();
      });

    var menuDelete = document.getElementById("dp-menu-delete");
    if (menuDelete)
      menuDelete.addEventListener("click", function () {
        closeOverflowMenu();
        if (activeDetailWorkoutId)
          deleteWorkout(activeDetailWorkoutId, isSyncedWorkout(cachedDetailWorkout));
      });

    document.addEventListener("click", function (e) {
      var menu = document.getElementById("dp-overflow-menu");
      var btn = document.getElementById("dp-overflow-btn");
      if (menu && btn && (menu.contains(e.target) || btn.contains(e.target)))
        return;
      closeOverflowMenu();
    });
  }

  // ── Repeat last workout (issue #524) ──────────────────────────────────────
  // The /log page surfaces the action; the prefill itself reuses the existing
  // repeatLastWorkout entry point on the form page (out of scope to duplicate).
  function repeatLastEntryPoint() {
    window.location.href = "/training?repeat=1";
  }

  // Enable the button only when a previous workout exists; otherwise disable it
  // with an explanatory empty-state title (AC6). Checks a long window so a user
  // with history but an empty current week still sees it enabled.
  function refreshRepeatAvailability() {
    var btn = document.getElementById("log-repeat-last-btn");
    if (!btn) return;
    var to = todayISO();
    var from = addDays(to, -1095); // ~3 years, matches the form-side repeat window
    fetch("/api/workouts?from=" + from + "&to=" + to)
      .then(function (res) {
        return res.ok ? res.json() : [];
      })
      .then(function (workouts) {
        var has = Array.isArray(workouts) && workouts.length > 0;
        btn.disabled = !has;
        btn.title = has
          ? "Repeat your most recent workout"
          : "No previous workout to repeat";
      })
      .catch(function () {
        /* leave the button disabled on error */
      });
  }

  // ── Duplicate to date (issue #524) ────────────────────────────────────────
  function openDuplicateModal() {
    if (!activeDetailWorkoutId) return;
    var modal = document.getElementById("dup-modal");
    var input = document.getElementById("dup-date-input");
    var err = document.getElementById("dup-date-error");
    if (err) err.textContent = "";
    if (input) {
      input.max = todayISO(); // no future dates (mirrors the backend rule)
      input.value = todayISO();
    }
    if (modal) {
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    }
    if (input) input.focus();
  }

  function closeDuplicateModal() {
    var modal = document.getElementById("dup-modal");
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  }

  function dupModalIsOpen() {
    var modal = document.getElementById("dup-modal");
    return !!(modal && modal.classList.contains("is-open"));
  }

  function confirmDuplicate() {
    var input = document.getElementById("dup-date-input");
    var err = document.getElementById("dup-date-error");
    var btn = document.getElementById("dup-confirm-btn");
    if (!activeDetailWorkoutId || !input) return;
    var date = input.value;
    if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      if (err) err.textContent = "Pick a valid date.";
      return;
    }
    if (date > todayISO()) {
      if (err) err.textContent = "Date cannot be in the future.";
      return;
    }
    if (btn) btn.disabled = true;
    fetch("/api/workouts/" + activeDetailWorkoutId + "/duplicate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workout_date: date }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function () {
        closeDuplicateModal();
        closeDetailPanel();
        UIStates.showToast("Workout duplicated");
        fetchAndRender();
        refreshRepeatAvailability();
      })
      .catch(function () {
        if (err) err.textContent = "Could not duplicate. Please try again.";
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    readURLParams();
    buildFilterBar();
    fetchAndRender();
    initSwipe();
    refreshRepeatAvailability();

    _syncPollStatus();

    window.addEventListener("userChanged", function () {
      fetchAndRender();
      refreshRepeatAvailability();
    });

    var repeatBtn = document.getElementById("log-repeat-last-btn");
    if (repeatBtn)
      repeatBtn.addEventListener("click", function () {
        if (!repeatBtn.disabled) repeatLastEntryPoint();
      });

    var dupCloseBtn = document.getElementById("dup-close-btn");
    if (dupCloseBtn) dupCloseBtn.addEventListener("click", closeDuplicateModal);
    var dupCancelBtn = document.getElementById("dup-cancel-btn");
    if (dupCancelBtn)
      dupCancelBtn.addEventListener("click", closeDuplicateModal);
    var dupBackdrop = document.getElementById("dup-backdrop");
    if (dupBackdrop) dupBackdrop.addEventListener("click", closeDuplicateModal);
    var dupForm = document.getElementById("dup-form");
    if (dupForm)
      dupForm.addEventListener("submit", function (e) {
        e.preventDefault();
        confirmDuplicate();
      });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && dupModalIsOpen()) closeDuplicateModal();
    });

    _initSyncWidget();
    _loadSyncChip();

    var exportBtn = document.getElementById("log-export-btn");
    if (exportBtn) exportBtn.addEventListener("click", exportCSV);

    var closeBtn = document.getElementById("dp-close-btn");
    if (closeBtn)
      closeBtn.addEventListener("click", function () {
        if (panelMode === "edit" || panelMode === "create") cancelPanelForm();
        else closeDetailPanel();
      });

    var prevBtn = document.getElementById("dp-prev-btn");
    if (prevBtn)
      prevBtn.addEventListener("click", function () {
        navigateDetail(-1);
      });

    var nextBtn = document.getElementById("dp-next-btn");
    if (nextBtn)
      nextBtn.addEventListener("click", function () {
        navigateDetail(1);
      });

    var overlay = document.getElementById("detail-overlay");
    if (overlay)
      overlay.addEventListener("click", function () {
        if (panelMode === "edit" || panelMode === "create") cancelPanelForm();
        else closeDetailPanel();
      });

    wirePanelForm();

    var listRetryBtn = document.getElementById("log-retry-btn");
    if (listRetryBtn)
      listRetryBtn.addEventListener("click", function () {
        fetchAndRender();
      });

    document.addEventListener("keydown", function (e) {
      var panel = document.getElementById("detail-panel");
      if (!panel || !panel.classList.contains("is-open")) return;
      if (e.key === "Escape") {
        if (panelMode === "edit" || panelMode === "create") cancelPanelForm();
        else closeDetailPanel();
        return;
      }
      if (panelMode !== "view") return;
      if (e.key === "ArrowUp" || e.key === "ArrowLeft") navigateDetail(-1);
      if (e.key === "ArrowDown" || e.key === "ArrowRight") navigateDetail(1);
    });
  });

  // ── Week strip ────────────────────────────────────────────────────────────
  var DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  var TYPE_COLORS = {
    run: "#3b82f6",
    lift: "#8b5cf6",
    wod: "#f97316",
    bike: "#14b8a6",
  };

  var TYPE_ORDER = ["run", "lift", "wod", "bike"];

  function toISODate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function getMondayOf(d) {
    var date = new Date(d);
    date.setHours(0, 0, 0, 0);
    var dow = date.getDay();
    var diff = dow === 0 ? -6 : 1 - dow;
    date.setDate(date.getDate() + diff);
    return date;
  }

  function parseWeekParam() {
    var params = new URLSearchParams(window.location.search);
    var w = params.get("week");
    if (w && /^\d{4}-\d{2}-\d{2}$/.test(w)) {
      var d = new Date(w + "T00:00:00");
      if (!isNaN(d.getTime())) return getMondayOf(d);
    }
    return getMondayOf(new Date());
  }

  function pushWeekParam(monday) {
    var params = new URLSearchParams(window.location.search);
    params.set("week", toISODate(monday));
    history.pushState({}, "", window.location.pathname + "?" + params);
  }

  function weekContainsToday(monday) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    return today >= monday && today <= sunday;
  }

  function buildWeekLabel(monday) {
    if (weekContainsToday(monday)) return "This week";
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    var month = monday.toLocaleDateString("en-US", { month: "short" });
    return month + " " + monday.getDate() + " – " + sunday.getDate();
  }

  var currentMonday    = parseWeekParam();
  var stripSelectedDate = null;   // ISO date of the highlighted mobile strip pill

  async function loadAndRender(monday) {
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);

    var fromStr = toISODate(monday);
    var toStr = toISODate(sunday);

    var url =
      "/api/training-log?from=" +
      fromStr +
      "&to=" +
      toStr +
      "&include_rest=false";

    var dotsByDate   = {};
    var countsByDate = {};
    try {
      var res = await fetch(url);
      if (res.ok) {
        var data = await res.json();
        (data.weeks || []).forEach(function (week) {
          (week.entries || []).forEach(function (entry) {
            var t = (entry.type || "").toLowerCase();
            if (TYPE_COLORS[t]) {
              if (!dotsByDate[entry.date]) dotsByDate[entry.date] = [];
              if (dotsByDate[entry.date].indexOf(t) === -1)
                dotsByDate[entry.date].push(t);
            }
            countsByDate[entry.date] = (countsByDate[entry.date] || 0) + 1;
          });
        });
      }
    } catch (_) {
      // network error — render with empty dots
    }

    render(monday, dotsByDate, countsByDate);
  }

  function render(monday, dotsByDate, countsByDate) {
    var strip = document.getElementById('week-strip');
    if (!strip) return;

    countsByDate = countsByDate || {};

    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var todayStr = toISODate(today);
    var isCurrentWeek = weekContainsToday(monday);

    // issue #639: track the selected day on the mobile strip independently of
    // the list filter (strip selection scrolls, not filters the list).

    var pillsHtml = "";
    for (var i = 0; i < 7; i++) {
      var d = new Date(monday);
      d.setDate(d.getDate() + i);
      var dateStr = toISODate(d);
      var isToday = dateStr === todayStr;
      var isSelected = dateStr === stripSelectedDate;

      var typesForDay = dotsByDate[dateStr] || [];
      var dotsHtml = TYPE_ORDER.filter(function (t) {
        return typesForDay.indexOf(t) !== -1;
      })
        .map(function (t) {
          return (
            '<span class="wd-dot" style="background:' +
            TYPE_COLORS[t] +
            '"></span>'
          );
        })
        .join("");

      // Descriptive aria-label: "Wednesday June 18, 2 activities" (issue #639 AC10).
      var ariaLabel = d.toLocaleDateString('en-US', {
        weekday: 'long', month: 'long', day: 'numeric'
      });
      var actCount = countsByDate[dateStr] || 0;
      ariaLabel += actCount > 0
        ? ', ' + actCount + ' ' + (actCount === 1 ? 'activity' : 'activities')
        : ', no activities';

      pillsHtml +=
        '<button type="button" class="day-pill' +
        (isToday ? " today" : "") +
        (isSelected ? " is-selected" : "") +
        '"' +
        ' data-date="' +
        dateStr +
        '"' +
        ' aria-pressed="' +
        (isSelected ? "true" : "false") +
        '"' +
        ' aria-label="' +
        esc(ariaLabel) +
        '">' +
        '<span class="day-name">' +
        DAY_NAMES[i] +
        "</span>" +
        '<span class="day-num">' +
        d.getDate() +
        "</span>" +
        '<div class="wd-dots">' +
        dotsHtml +
        "</div>" +
        "</button>";
    }

    strip.innerHTML =
      '<div class="ws-nav">' +
      '<button id="week-prev" class="ws-chevron" aria-label="Previous week">&#8249;</button>' +
      '<span id="week-label" class="ws-label">' +
      buildWeekLabel(monday) +
      "</span>" +
      '<button id="week-today" class="ws-today-btn"' +
      (isCurrentWeek ? " disabled" : "") +
      ">Today</button>" +
      '<button id="week-next" class="ws-chevron" aria-label="Next week">&#8250;</button>' +
      "</div>" +
      '<div class="ws-pills">' +
      pillsHtml +
      "</div>";

    document.getElementById("week-prev").addEventListener("click", function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() - 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday);
    });

    document.getElementById("week-next").addEventListener("click", function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() + 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday);
    });

    document
      .getElementById("week-today")
      .addEventListener("click", function () {
        currentMonday = getMondayOf(new Date());
        pushWeekParam(currentMonday);
        loadAndRender(currentMonday);
      });

    // issue #639: wire each day pill to the scroll-based selection handler.
    // Real <button>s already fire click on Enter & Space.
    var pillEls = strip.querySelectorAll('.day-pill');
    Array.prototype.forEach.call(pillEls, function (pill) {
      pill.addEventListener('click', function () {
        stripSelectDay(pill.getAttribute('data-date'));
      });
    });

    // Bring the selected pill — or today's pill on the current week — into view.
    var focusDate = stripSelectedDate
                  ? stripSelectedDate
                  : (isCurrentWeek ? todayStr : null);
    if (focusDate) {
      var target = strip.querySelector(
        '.day-pill[data-date="' + focusDate + '"]',
      );
      if (target) scrollPillIntoView(target);
    }
  }

  // Centre a pill within the horizontally-scrolling strip without disturbing
  // vertical page scroll. issue #523 (AC3 — works on all screen widths).
  function scrollPillIntoView(pill) {
    var container = pill.parentElement; // .ws-pills
    if (!container) return;
    var offset =
      pill.offsetLeft - (container.clientWidth - pill.clientWidth) / 2;
    container.scrollLeft = Math.max(0, offset);
  }

  // issue #639: scroll the history list to the first entry for dateStr.
  // If no entry exists for that exact date, scroll to the nearest preceding entry.
  // Never filters or hides entries — full history stays visible.
  function stripScrollToDate(dateStr) {
    var listEl = document.getElementById('log-list');
    if (!listEl) return;
    var target = listEl.querySelector('.day-group[data-date="' + dateStr + '"]');
    if (target) { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    // Find nearest preceding day-group (groups are newest-first in DOM)
    var groups = Array.prototype.slice.call(
      listEl.querySelectorAll('.day-group[data-date]')
    );
    var nearest = null;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].dataset.date <= dateStr) { nearest = groups[i]; break; }
    }
    if (nearest) {
      nearest.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (groups.length) {
      groups[groups.length - 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // issue #639: tapping a mobile week-strip pill selects it (persistent highlight)
  // and scrolls the log list — it never filters or hides other entries.
  function stripSelectDay(dateStr) {
    if (!dateStr) return;
    stripSelectedDate = dateStr;
    loadAndRender(currentMonday); // re-render strip to update is-selected
    stripScrollToDate(dateStr);
  }

  // Keep the date-range chip / inputs in sync when a pill drives the filter.
  function syncDateRangeChip() {
    var chip = document.getElementById("dr-chip");
    if (chip) chip.textContent = drLabel() + " ▾";
    var fromInput = document.getElementById("dr-from");
    if (fromInput) fromInput.value = filters.from;
    var toInput = document.getElementById("dr-to");
    if (toInput) toInput.value = filters.to;
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadAndRender(currentMonday);
  });

  window.addEventListener("userReady", function () {
    loadAndRender(currentMonday);
    _positionNav();
  });

  window.addEventListener("userChanged", function () {
    loadAndRender(currentMonday);
  });

  // Measure the two stacked nav bars (global nav + sticky training header) so the
  // detail-drawer overlay starts exactly below them, and the training header
  // sticks right under the global nav — robust across breakpoints/heights.
  function _positionNav() {
    var gnav = document.querySelector(".global-nav");
    var hdr = document.querySelector(".log-page-header");
    var gh = gnav ? gnav.offsetHeight : 60;
    if (hdr) hdr.style.top = gh + "px";
    var hh = hdr ? hdr.offsetHeight : 56;
    document.documentElement.style.setProperty(
      "--log-nav-total",
      gh + hh + "px",
    );

    // Align the two nav clusters with the columns below them: brand+tabs to the
    // content column's left edge, actions to the detail drawer's left edge.
    var inner = document.querySelector(".log-page-header-inner");
    var col = document.getElementById("list-main");
    var actions = document.querySelector(".log-page-header-actions");
    if (inner) {
      var innerLeft = inner.getBoundingClientRect().left;
      if (col) {
        var contentLeft = col.getBoundingClientRect().left;
        inner.style.paddingLeft = Math.max(0, contentLeft - innerLeft) + "px";
      }
      if (actions) {
        var DRAWER_W = 440, DRAWER_INSET = 12;
        var drawerLeft = window.innerWidth - DRAWER_INSET - DRAWER_W;
        actions.style.left = Math.max(0, drawerLeft - innerLeft) + "px";
        actions.style.right = "auto";
      }
    }
  }
  window.addEventListener("load", _positionNav);
  window.addEventListener("resize", _positionNav);
  _positionNav();

  // ── Month Calendar (issue #638) ───────────────────────────────────────────
  // Desktop-only (CSS hides #log-calendar below 1024 px). Reads from lastWeeks
  // already in memory — no additional API calls.

  var calCurrentMonth = null;   // Date at the 1st of displayed month
  var calSelectedDate = null;   // ISO date string of the highlighted cell
  var calDayData      = {};     // date → { types: string[], totalTss: number }

  var CAL_MONTH_NAMES = [
    'January','February','March','April','May','June',
    'July','August','September','October','November','December'
  ];

  var CAL_WEEKDAY_ABBR = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

  function buildCalDayData(weeks) {
    calDayData = {};
    (weeks || []).forEach(function (week) {
      (week.entries || []).forEach(function (entry) {
        if (entry.type === 'rest' || !entry.date) return;
        var d = calDayData[entry.date];
        if (!d) { d = { types: [], totalTss: 0, km: 0 }; calDayData[entry.date] = d; }
        var t = (entry.type || '').toLowerCase();
        if (t && d.types.indexOf(t) === -1) d.types.push(t);
        if (entry.tss > 0) d.totalTss += entry.tss;
        if (entry.distance_km > 0) d.km += entry.distance_km;
      });
    });
  }

  // Normalize a raw workout_type to the two calendar dot families.
  function _calDotType(t) {
    t = (t || '').toLowerCase();
    if (t === 'run' || t === 'bike') return 'run';
    return 'lift'; // strength/lift/wod → violet
  }

  // Displayed month as 'YYYY-MM' — consumed by the summary (decision 3).
  function _calMonthKey() {
    if (!calCurrentMonth) return null;
    return calCurrentMonth.getFullYear() + '-' + pad(calCurrentMonth.getMonth() + 1);
  }
  function _calMarkMonthScoped() {
    var t = document.getElementById('log-cal-title');
    if (t) t.classList.add('scoped');
    _calClearWeekSel();
  }
  function _calClearScope() {
    var t = document.getElementById('log-cal-title');
    if (t) t.classList.remove('scoped');
    _calClearWeekSel();
  }
  function _calClearWeekSel() {
    var el = document.getElementById('log-calendar');
    if (el) el.querySelectorAll('.lrx-calrow.sel').forEach(function (r) { r.classList.remove('sel'); });
    _clearLogWeekHl();
  }
  function _clearLogWeekHl() {
    document.querySelectorAll('#log-list .day-group.lrx-week-hl')
      .forEach(function (g) { g.classList.remove('lrx-week-hl'); });
  }
  // Highlight the log-list day-groups within [ws, we] (ISO dates) and scroll the
  // first into view, so clicking a calendar week points at it in the list too.
  function _highlightLogWeek(ws, we) {
    if (!ws || !we) return;
    var first = null;
    document.querySelectorAll('#log-list .day-group').forEach(function (g) {
      var d = g.dataset.date;
      var inWk = d && d >= ws && d <= we;
      g.classList.toggle('lrx-week-hl', inWk);
      if (inWk && !first) first = g;
    });
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function renderCalendar() {
    var el = document.getElementById('log-calendar');
    if (!el) return;

    var now = new Date();
    if (!calCurrentMonth) {
      calCurrentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    }

    var year  = calCurrentMonth.getFullYear();
    var month = calCurrentMonth.getMonth();
    var todayStr = pad(now.getFullYear()) + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());
    var lastDayNum = new Date(year, month + 1, 0).getDate();
    var isCurrentMonth = year === now.getFullYear() && month === now.getMonth();

    // Week starts Monday.
    var firstDow    = new Date(year, month, 1).getDay();
    var startOffset = (firstDow + 6) % 7;
    var totalCells  = startOffset + lastDayNum;
    var rows        = Math.ceil(totalCells / 7);

    // Build per-week aggregates (Mon–Sun rows over this month's cells).
    var weekAgg = [];
    var dayNum = 1;
    for (var row = 0; row < rows; row++) {
      var w = { tss: 0, km: 0, sessions: 0, startDate: null, endDate: null };
      for (var col = 0; col < 7; col++) {
        var cellIdx = row * 7 + col;
        if (cellIdx >= startOffset && dayNum <= lastDayNum) {
          var ds = year + '-' + pad(month + 1) + '-' + pad(dayNum);
          if (!w.startDate) w.startDate = ds;
          w.endDate = ds;
          var dd = calDayData[ds];
          if (dd) { w.tss += dd.totalTss; w.km += dd.km; if (dd.totalTss > 0 || dd.types.length) w.sessions += 1; }
          dayNum++;
        }
      }
      weekAgg.push(w);
    }
    var maxWk = Math.max.apply(null, weekAgg.map(function (w) { return w.tss; }).concat([1]));

    var html =
      '<div class="lrx-chead">' +
        '<div class="lrx-calnav">' +
          '<button type="button" id="log-cal-prev" class="lrx-arw" aria-label="Previous month">&#8249;</button>' +
          '<span id="log-cal-title" class="mtitle" role="button" tabindex="0">' +
            CAL_MONTH_NAMES[month] + ' ' + year + '</span>' +
          '<button type="button" id="log-cal-next" class="lrx-arw" aria-label="Next month">&#8250;</button>' +
        '</div>' +
        '<button type="button" id="log-cal-today" class="lrx-today"' +
          (isCurrentMonth ? ' disabled' : '') + '>Today</button>' +
      '</div>' +
      '<table class="lrx-cal"><thead><tr>';
    CAL_WEEKDAY_ABBR.forEach(function (a) { html += '<th>' + esc(a) + '</th>'; });
    html += '<th class="wk">Week</th></tr></thead><tbody>';

    dayNum = 1;
    for (var r2 = 0; r2 < rows; r2++) {
      var wa = weekAgg[r2];
      html += '<tr class="lrx-calrow" data-wk-start="' + esc(wa.startDate || '') +
              '" data-wk-end="' + esc(wa.endDate || '') + '">';
      for (var c2 = 0; c2 < 7; c2++) {
        var ci = r2 * 7 + c2;
        if (ci < startOffset || dayNum > lastDayNum) {
          html += '<td class="out"></td>';
        } else {
          var dStr = year + '-' + pad(month + 1) + '-' + pad(dayNum);
          var dd2  = calDayData[dStr];
          var dots = '';
          if (dd2 && dd2.types.length) {
            var fam = {};
            dd2.types.forEach(function (t) { fam[_calDotType(t)] = 1; });
            ['run', 'lift'].forEach(function (f) {
              if (fam[f]) dots += '<div class="lrx-dot ' + f + '"></div>';
            });
          }
          html += '<td data-date="' + dStr + '"><span class="dnum">' + dayNum + '</span>' + dots + '</td>';
          dayNum++;
        }
      }
      var barPct = wa.tss > 0 ? (wa.tss / maxWk * 100) : 0;
      html += '<td class="lrx-wkcell">' +
                '<div class="wt">' + Math.round(wa.tss) + ' TSS</div>' +
                '<div class="wkkm">' + wa.km.toFixed(1) + ' km</div>' +
                '<div class="lrx-wkbar"><span style="width:' + barPct.toFixed(0) + '%"></span></div>' +
              '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>' +
      '<div class="lrx-callegend">' +
        '<span><b style="background:var(--lrx-run)"></b>Run</span>' +
        '<span><b style="background:var(--lrx-lift)"></b>Lift</span>' +
        '<span style="color:var(--lrx-faint)">click a week to scope · click the month title for the month total</span>' +
      '</div>';
    el.innerHTML = html;

    // Nav
    var prevBtn = document.getElementById('log-cal-prev');
    var nextBtn = document.getElementById('log-cal-next');
    var todayBtn = document.getElementById('log-cal-today');
    var title = document.getElementById('log-cal-title');
    if (prevBtn) prevBtn.addEventListener('click', function () {
      calCurrentMonth = new Date(year, month - 1, 1); renderCalendar(); _calSyncScopeFollow();
    });
    if (nextBtn) nextBtn.addEventListener('click', function () {
      calCurrentMonth = new Date(year, month + 1, 1); renderCalendar(); _calSyncScopeFollow();
    });
    if (todayBtn) todayBtn.addEventListener('click', function () {
      calCurrentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      renderCalendar();
      if (window.LogSummary && window.LogSummary.showThisWeek) window.LogSummary.showThisWeek();
    });
    // Month title → scope summary to the displayed whole month (decision 3).
    if (title) {
      var scopeMonth = function () {
        _calMarkMonthScoped();
        if (window.LogSummary && window.LogSummary.scopeMonth) {
          window.LogSummary.scopeMonth(_calMonthKey());
        }
      };
      title.addEventListener('click', scopeMonth);
      title.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); scopeMonth(); }
      });
    }

    // Week-row click → scope the summary to that week ONLY (decision 2). Day
    // cells inside still scroll the log list to that date (keep existing UX).
    var tbody = el.querySelector('tbody');
    if (tbody) {
      tbody.addEventListener('click', function (e) {
        var cell = e.target.closest('td[data-date]');
        var rowEl = e.target.closest('.lrx-calrow');
        if (cell && cell.getAttribute('data-date')) {
          calScrollToDate(cell.getAttribute('data-date'));
        }
        if (!rowEl) return;
        _calClearScope();
        rowEl.classList.add('sel');
        var ws = rowEl.getAttribute('data-wk-start');
        var we = rowEl.getAttribute('data-wk-end');
        // Aggregate this row's totals from calDayData.
        var tss = 0, km = 0, sess = 0;
        el.querySelectorAll('.lrx-calrow.sel td[data-date]').forEach(function (td) {
          var dd = calDayData[td.getAttribute('data-date')];
          if (dd) { tss += dd.totalTss; km += dd.km; if (dd.totalTss > 0 || dd.types.length) sess += 1; }
        });
        var label = _calWkLabel(ws, we);
        if (window.LogSummary && window.LogSummary.scopeWeek) {
          window.LogSummary.scopeWeek({
            label: label, distance_km: km, total_tss: tss, session_count: sess,
          });
        }
        // Also highlight + scroll to that week's groups in the log list below.
        _highlightLogWeek(ws, we);
      });
    }
  }

  // "Jun 29 – Jul 5" style label from ISO start/end dates.
  function _calWkLabel(startIso, endIso) {
    function short(iso) {
      if (!iso) return '';
      var p = iso.split('-');
      var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }
    return short(startIso) + ' – ' + short(endIso);
  }

  // When paging months while the month-scope is active, keep the summary on
  // the newly displayed month (decision 3).
  function _calSyncScopeFollow() {
    var title = document.getElementById('log-cal-title');
    if (title && title.classList.contains('scoped') &&
        window.LogSummary && window.LogSummary.scopeMonth) {
      window.LogSummary.scopeMonth(_calMonthKey());
    }
  }

  // Public API for the summary card to query/mark scope.
  window.LogCalendar = {
    getDisplayedMonth: _calMonthKey,
    markMonthScoped: _calMarkMonthScoped,
    clearScope: _calClearScope,
  };

  function calScrollToDate(dateStr) {
    var listEl = document.getElementById('log-list');
    if (!listEl) return;
    // Try exact match first
    var target = listEl.querySelector('.day-group[data-date="' + dateStr + '"]');
    if (target) { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    // Find nearest preceding entry (groups are newest-first in DOM)
    var groups = Array.prototype.slice.call(
      listEl.querySelectorAll('.day-group[data-date]')
    );
    var nearest = null;
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].dataset.date <= dateStr) { nearest = groups[i]; break; }
    }
    if (nearest) {
      nearest.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (groups.length) {
      groups[groups.length - 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function updateCalendar() {
    buildCalDayData(lastWeeks);
    renderCalendar();
  }
}());

// ── Summary Digest Card (issue #1058) ─────────────────────────────────────────
(function () {
  'use strict';

  var _athleteId   = null;
  var _activePeriod = 'week';
  // Displayed calendar month (YYYY-MM) the monthly summary should follow, and
  // whether a calendar week-scope is currently pinned (summary-only).
  var _scopeMonth = null;

  // Cache: keyed by 'week' or 'month' (+ month key), value = fetched data
  var _summaryCache = {};

  function _setScopeLabel(text) {
    var el = document.getElementById('lrx-scope');
    if (el) el.textContent = text;
  }
  function _monthLabel(ym) {
    // ym = 'YYYY-MM' → 'July 2026'
    if (!ym) return '';
    var parts = ym.split('-');
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
    return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _fmtDelta(val, unit) {
    if (val == null) return null;
    var n = Number(val);
    if (!isFinite(n)) return null;
    var sign = n > 0 ? '+' : '';
    return sign + n.toFixed(unit === 'kg' ? 1 : 1) + (unit ? ' ' + unit : '');
  }

  function _chipClass(val) {
    if (val == null) return 'sd-chip--neu';
    var n = Number(val);
    if (n > 0) return 'sd-chip--pos';
    if (n < 0) return 'sd-chip--neg';
    return 'sd-chip--neu';
  }

  // ── Skeleton ─────────────────────────────────────────────────────────────────

  function _renderSkeleton() {
    return (
      '<div class="sd-skeleton-tiles">' +
        '<div class="sd-skeleton-tile"></div>' +
        '<div class="sd-skeleton-tile"></div>' +
        '<div class="sd-skeleton-tile"></div>' +
      '</div>' +
      '<div class="sd-skeleton-chips">' +
        '<div class="sd-skeleton-chip"></div>' +
        '<div class="sd-skeleton-chip"></div>' +
        '<div class="sd-skeleton-chip"></div>' +
      '</div>'
    );
  }

  // ── Guardrail warning ────────────────────────────────────────────────────────

  function _renderGuardrailWarn(data) {
    if (data.guardrail_state !== 'warn') return '';
    var msg = data.guardrail_message || 'Training load caution — review your workload this week.';
    return (
      '<div class="sd-guardrail-warn">' +
        '<span class="sd-guardrail-warn-icon" aria-hidden="true">&#9888;</span>' +
        '<span>' + _esc(msg) + '</span>' +
      '</div>'
    );
  }

  // ── Shared tiles + chips (weekly and monthly share the same top block) ───────

  // Mock sumtiles: label, big value+unit, and a delta line. The summary
  // endpoint has no volume/session week-over-week deltas, so the delta line is
  // driven by the available *_change fields where meaningful: Load ← form TSB
  // change (form trend); Volume/Sessions have no comparable delta → flat "—".
  function _sdDelta(change, unit, noun) {
    if (change == null || !isFinite(Number(change))) {
      return '<div class="lrx-delta flat">—</div>';
    }
    var n = Number(change);
    var cls = n > 0 ? 'up' : n < 0 ? 'down' : 'flat';
    var arrow = n > 0 ? '▲ ' : n < 0 ? '▼ ' : '= ';
    var txt = arrow + (n > 0 ? '+' : '') + n.toFixed(1) + (unit ? ' ' + unit : '') +
              (noun ? ' ' + noun : '');
    return '<div class="lrx-delta ' + cls + '">' + _esc(txt) + '</div>';
  }
  function _sdTiles(data) {
    function tile(label, val, unit, deltaHtml) {
      return (
        '<div class="lrx-sumtile">' +
          '<div class="lab">' + label + '</div>' +
          '<div class="val">' + _esc(val) +
            (unit ? ' <small>' + unit + '</small>' : '') +
          '</div>' + (deltaHtml || '<div class="lrx-delta flat">—</div>') +
        '</div>'
      );
    }
    return (
      '<div class="lrx-sumgrid">' +
        tile('Volume', (data.distance_km || 0).toFixed(1), 'km', null) +
        tile('Load', Math.round(data.total_tss || 0), 'TSS',
             _sdDelta(data.form_tsb_change, null, 'form')) +
        tile('Sessions', data.session_count || 0, '', null) +
      '</div>'
    );
  }

  // Form-state descriptor derived client-side from the weekly TSB change — the
  // weekly summary endpoint has no form-band field. Tune thresholds as needed.
  function _formBand(tsbChange) {
    if (tsbChange == null) return null;
    var n = Number(tsbChange);
    if (!isFinite(n)) return null;
    if (n >= 3) return 'fresh';
    if (n <= -12) return 'overreaching';
    if (n <= -3) return 'productive';
    return 'steady';
  }

  // Separate Endurance / Speed / Weight / Form chips (design mock).
  // chip colour: g = good/up, r = bad/down, b = neutral/info (mock classes).
  function _lrxChipClass(val) {
    if (val == null) return 'b';
    var n = Number(val);
    if (n > 0) return 'g';
    if (n < 0) return 'r';
    return 'b';
  }
  function _sdChips(data) {
    var chips = '';
    var has = false;
    function add(label, val, cls, suffix) {
      chips +=
        '<span class="lrx-chip ' + cls + '">' + label + ' ' + _esc(val) +
        (suffix ? ' · ' + _esc(suffix) : '') + '</span>';
      has = true;
    }
    if (data.endurance_score_change != null && data.endurance_score_change !== 0) {
      var eStr = _fmtDelta(data.endurance_score_change, '');
      if (eStr) add('Endurance', eStr, _lrxChipClass(data.endurance_score_change));
    }
    if (data.speed_score_change != null && data.speed_score_change !== 0) {
      var sStr = _fmtDelta(data.speed_score_change, '');
      if (sStr) add('Speed', sStr, _lrxChipClass(data.speed_score_change));
    }
    if (data.weight_change_kg != null) {
      var wStr = _fmtDelta(data.weight_change_kg, 'kg');
      // Weight up is neutral-ish; keep the mock's green for a logged change.
      if (wStr) add('Weight', wStr, 'g');
    }
    if (data.form_tsb_change != null && data.form_tsb_change !== 0) {
      var fStr = _fmtDelta(data.form_tsb_change, '');
      if (fStr) add('Form', fStr, 'b', _formBand(data.form_tsb_change));
    }
    return has ? '<div class="lrx-chips">' + chips + '</div>' : '';
  }

  // ── Render weekly view ───────────────────────────────────────────────────────

  function _renderWeek(data) {
    var noteHtml = data.note ? '<div class="sd-note">' + _esc(data.note) + '</div>' : '';
    return _sdTiles(data) + _sdChips(data) + noteHtml + _renderGuardrailWarn(data);
  }

  // ── Render monthly view ──────────────────────────────────────────────────────

  function _renderMonth(data) {
    var tiles = _sdTiles(data);
    var chipsHtml = _sdChips(data);

    // Supercompensation section
    var state = data.supercompensation_state || 'flat';
    var badgeClass = state === 'working' ? 'sd-supercomp-badge--working'
                   : state === 'digging' ? 'sd-supercomp-badge--digging'
                   : 'sd-supercomp-badge--flat';
    var badgeLabel = state === 'working' ? 'Primed' : state === 'digging' ? 'Digging' : 'Maintaining';

    var supercompHtml =
      '<div class="sd-supercomp">' +
        '<div class="sd-supercomp-row">' +
          '<span class="sd-supercomp-badge ' + badgeClass + '">' + _esc(badgeLabel) + '</span>' +
          (data.call_to_action ? '<span class="sd-supercomp-cta">' + _esc(data.call_to_action) + '</span>' : '') +
        '</div>' +
        '<div class="sd-supercomp-links">' +
          '<a class="sd-supercomp-link" href="training-log.html#plan">&#8594; Plan</a>' +
          '<a class="sd-supercomp-link" href="training-log.html#performance">&#8594; Performance</a>' +
        '</div>' +
      '</div>';

    return tiles + chipsHtml + supercompHtml + _renderGuardrailWarn(data);
  }

  // ── Fetch & render ───────────────────────────────────────────────────────────

  function _renderError() {
    var body = document.getElementById('sd-body');
    if (!body) return;
    body.innerHTML = '<div class="sd-error">Could not load summary.</div>';
  }

  function _applyData(period, data) {
    var body = document.getElementById('sd-body');
    if (!body) return;
    var card = document.getElementById('summary-digest-card');

    if (period === 'week') {
      body.innerHTML = _renderWeek(data);
    } else {
      body.innerHTML = _renderMonth(data);
    }

    if (card) card.hidden = false;
  }

  function _fetchSummary(period) {
    if (!_athleteId) return;

    // Cache key includes the scoped month so paging months fetches each.
    var cacheKey = period === 'month' && _scopeMonth ? 'month:' + _scopeMonth : period;

    if (_summaryCache[cacheKey]) {
      _applyData(period, _summaryCache[cacheKey]);
      return;
    }

    var body = document.getElementById('sd-body');
    if (body) body.innerHTML = _renderSkeleton();

    var card = document.getElementById('summary-digest-card');
    if (card) card.hidden = false;

    var endpoint = period === 'week'
      ? '/api/athletes/' + _athleteId + '/summary/weekly'
      : '/api/athletes/' + _athleteId + '/summary/monthly' +
        (_scopeMonth ? '?month=' + _scopeMonth : '');

    fetch(endpoint)
      .then(function (res) {
        if (!res.ok) {
          // Monthly returns 424 when no training data; treat as empty rather than crash
          if (period === 'month' && res.status === 424) {
            _summaryCache[cacheKey] = {
              distance_km: 0, total_tss: 0, session_count: 0,
              supercompensation_state: 'flat', call_to_action: null,
              weight_change_kg: null, endurance_score_change: 0,
              speed_score_change: 0
            };
            _applyData(period, _summaryCache[cacheKey]);
            return null;
          }
          throw new Error('HTTP ' + res.status);
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        _summaryCache[cacheKey] = data;
        if (_activePeriod === period) _applyData(period, data);
      })
      .catch(function () {
        if (_activePeriod === period) _renderError();
      });
  }

  // ── Toggle ───────────────────────────────────────────────────────────────────

  function _syncSeg(period) {
    document.querySelectorAll('.sd-toggle-btn').forEach(function (btn) {
      var active = btn.getAttribute('data-period') === period;
      btn.classList.toggle('is-active', active);
      btn.classList.toggle('on', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function _setActivePeriod(period) {
    _activePeriod = period;
    _syncSeg(period);
    if (period === 'week') {
      // Manual "This week" clears any calendar month/week scope.
      _scopeMonth = null;
      _setScopeLabel('This week');
      if (window.LogCalendar && window.LogCalendar.clearScope) window.LogCalendar.clearScope();
    } else {
      // Follow the displayed calendar month (decision 3).
      if (window.LogCalendar && window.LogCalendar.getDisplayedMonth) {
        _scopeMonth = window.LogCalendar.getDisplayedMonth();
      }
      _setScopeLabel(_monthLabel(_scopeMonth) || 'This month');
      if (window.LogCalendar && window.LogCalendar.markMonthScoped) window.LogCalendar.markMonthScoped();
    }
    _fetchSummary(period);
  }

  // ── Public API for calendar binding ───────────────────────────────────────────
  // scopeWeek: render a specific week's totals into the summary (summary-only;
  // does NOT filter the log list — decision 2).
  function _scopeWeek(w) {
    _activePeriod = 'week';
    _syncSeg(null); // no seg lit while a specific week is scoped
    _setScopeLabel('Week of ' + w.label);
    var body = document.getElementById('sd-body');
    var card = document.getElementById('summary-digest-card');
    if (card) card.hidden = false;
    if (body) {
      var data = {
        distance_km: w.distance_km || 0,
        total_tss: w.total_tss || 0,
        session_count: w.session_count || 0,
      };
      body.innerHTML =
        '<div class="lrx-sumgrid">' +
        '<div class="lrx-sumtile"><div class="lab">Volume</div><div class="val">' +
          data.distance_km.toFixed(1) + ' <small>km</small></div>' +
          '<div class="lrx-delta flat">selected week</div></div>' +
        '<div class="lrx-sumtile"><div class="lab">Load</div><div class="val">' +
          Math.round(data.total_tss) + ' <small>TSS</small></div>' +
          '<div class="lrx-delta flat">selected week</div></div>' +
        '<div class="lrx-sumtile"><div class="lab">Sessions</div><div class="val">' +
          data.session_count + '</div>' +
          '<div class="lrx-delta flat">selected week</div></div>' +
        '</div>';
    }
  }

  // scopeMonth: switch the summary to the displayed calendar month.
  function _scopeMonthFor(ym) {
    _scopeMonth = ym;
    _activePeriod = 'month';
    _syncSeg('month');
    _setScopeLabel(_monthLabel(ym) || 'This month');
    _fetchSummary('month');
  }

  window.LogSummary = {
    scopeWeek: _scopeWeek,
    scopeMonth: _scopeMonthFor,
    showThisWeek: function () { _setActivePeriod('week'); },
  };

  // ── Init ─────────────────────────────────────────────────────────────────────

  function _init(athleteId) {
    _athleteId = athleteId;

    var toggleContainer = document.querySelector('.sd-toggle');
    if (toggleContainer) {
      toggleContainer.addEventListener('click', function (e) {
        var btn = e.target.closest('.sd-toggle-btn');
        if (!btn) return;
        var period = btn.getAttribute('data-period');
        if (period) _setActivePeriod(period);
      });
    }

    // Fetch weekly summary immediately (default tab)
    _fetchSummary('week');
  }

  // Grab the user ID — user.js fires userReady once auth/me resolves
  window.addEventListener('userReady', function (e) {
    var uid = e.detail && e.detail.userId;
    if (uid && !_athleteId) _init(uid);
  });

  // Fallback: if user.js already ran before this listener registered
  document.addEventListener('DOMContentLoaded', function () {
    var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (uid && !_athleteId) _init(uid);
  });
}());
