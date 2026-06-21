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
    var parts = [totalCount + " workout" + (totalCount !== 1 ? "s" : "")];
    if (totalTSS > 0) parts.push("TSS " + Math.round(totalTSS));
    if (totalMinutes > 0) {
      var h = Math.floor(totalMinutes / 60);
      var m = Math.round(totalMinutes % 60);
      parts.push(h > 0 ? h + "h " + m + "m" : m + "m");
    }
    subtitleEl.textContent = parts.join(" · ");
  }

  // ── Build filter bar (issue #637: type pills + search, client-side) ─────────
  function buildFilterBar() {
    var bar = document.getElementById("filter-bar");
    if (!bar) return;

    // Type pills row — All / Run / Lift / WOD / Bike
    var chipsRow = document.createElement('div');
    chipsRow.className = 'fb-chips-row';
    var TYPE_OPTS   = ['all','run','lift','wod','bike'];
    var TYPE_LABELS = { all:'All', run:'Run', lift:'Lift', wod:'WOD', bike:'Bike' };
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

  function renderReadinessWidget(data) {
    var el = document.getElementById('readiness-widget');
    if (!el) return;

    if (data.building_baseline) {
      el.innerHTML =
        '<div class="rw-header"><span class="rw-title">Readiness</span></div>' +
        '<p class="rw-baseline-msg">Building baseline — log more workouts to unlock your Fitness, Fatigue, and Freshness scores.</p>';
      el.hidden = false;
      return;
    }

    function tile(val, abbr, label, sparkId) {
      return '<div class="rw-tile">' +
               '<div class="rw-tile-val">' + esc(fmtLoadNum(val)) + '</div>' +
               '<div class="rw-tile-label">' + abbr + '</div>' +
               '<div class="rw-tile-sub">' + label + '</div>' +
               '<div class="rw-spark-wrap"><canvas class="rw-tile-sparkline" id="' + sparkId + '"></canvas></div>' +
             '</div>';
    }

    var rlabel = data.readiness_label || '';
    var rlabelClass = rlabel === 'Fresh' ? 'rw-label--fresh'
                    : rlabel === 'Fatigued' ? 'rw-label--fatigued'
                    : 'rw-label--optimal';

    el.innerHTML =
      '<div class="rw-header">' +
        '<span class="rw-title">Readiness</span>' +
        (rlabel ? '<span class="rw-label ' + rlabelClass + '">' + esc(rlabel) + '</span>' : '') +
      '</div>' +
      '<div class="rw-tiles">' +
        tile(data.ctl, 'CTL', 'Fitness',   'rw-spark-ctl') +
        tile(data.atl, 'ATL', 'Fatigue',   'rw-spark-atl') +
        tile(data.tsb, 'TSB', 'Freshness', 'rw-spark-tsb') +
      '</div>';
    el.hidden = false;

    var series = data.series || [];
    _renderSparkline('rw-spark-ctl', series.map(function (d) { return d.ctl; }), '#3b82f6');
    _renderSparkline('rw-spark-atl', series.map(function (d) { return d.atl; }), '#ef4444');
    _renderSparkline('rw-spark-tsb', series.map(function (d) { return d.tsb; }), '#10b981');
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

        if (volumeChart) {
          volumeChart.destroy();
          volumeChart = null;
        }
        volumeChart = new Chart(canvas.getContext("2d"), {
          type: "bar",
          data: {
            labels: labels,
            datasets: [
              {
                label: "Run TSS",
                data: runTssVals,
                backgroundColor: makeBarBg(
                  'rgba(96,165,250,0.95)', 'rgba(37,99,235,0.88)',
                  'rgba(96,165,250,0.38)', 'rgba(37,99,235,0.28)'
                ),
                borderRadius: 4,
                maxBarThickness: 36,
                stack: "tss",
                order: 2,
                yAxisID: "y",
              },
              {
                label: 'Lift TSS',
                data: strengthTssVals,
                backgroundColor: makeBarBg(
                  'rgba(167,139,250,0.95)', 'rgba(109,40,217,0.88)',
                  'rgba(167,139,250,0.38)', 'rgba(109,40,217,0.28)'
                ),
                borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
                maxBarThickness: 36,
                stack: "tss",
                order: 2,
                yAxisID: "y",
              },
              {
                label: 'km',
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
                  text: "km",
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
  function renderDayGroupedList(container, weeks) {
    if (!container) return;
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
    // Ensure newest-first day order.
    days.sort(function (a, b) { return a < b ? 1 : a > b ? -1 : 0; });

    days.forEach(function (dateStr) {
      var d = new Date(dateStr + 'T00:00:00');
      var dayGroup = document.createElement('div');
      dayGroup.className = 'day-group';
      dayGroup.dataset.date = dateStr;

      var header = document.createElement('div');
      header.className = 'day-group-header';
      var dayLabel = isNaN(d.getDay()) ? dateStr :
        DAY_ABBR[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
      header.textContent = dayLabel;
      dayGroup.appendChild(header);

      var rowsEl = document.createElement('div');
      rowsEl.className = 'day-group-rows';
      dayMap[dateStr].forEach(function (entry) {
        rowsEl.appendChild(buildEntryRow(entry));
      });
      dayGroup.appendChild(rowsEl);

      container.appendChild(dayGroup);
    });
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

  function buildEntryRow(w) {
    var row = document.createElement("div");
    row.className = "entry-row";
    if (w.id && activeDetailWorkoutId === w.id) {
      row.classList.add("is-active");
    }

    if (w.id) {
      row.setAttribute("tabindex", "0");
      row.setAttribute("role", "button");
      // Accessible name: type, title, date, and primary metric.
      var ariaBits = [];
      var tk = normalizeTypeKey(w.type);
      ariaBits.push(
        { run: "Run", lift: "Lift", wod: "WOD", bike: "Bike" }[tk] ||
          w.type ||
          "Workout",
      );
      ariaBits.push(w.title || "Workout");
      if (w.date) ariaBits.push(fmtDate(w.date));
      if (tk === "run" && w.distance_km != null)
        ariaBits.push((+w.distance_km).toFixed(1) + " kilometers");
      else if (w.duration_seconds)
        ariaBits.push(Math.round(w.duration_seconds / 60) + " minutes");
      row.setAttribute("aria-label", ariaBits.join(", ") + ". Open details");
      row.dataset.workoutId = w.id;
      var rowRef = row;
      row.addEventListener("click", function () {
        openDetailPanel(w.id, rowRef);
      });
      row.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDetailPanel(w.id, rowRef);
        }
      });
    }

    var dateCol = document.createElement("div");
    dateCol.className = "entry-date";
    var d = new Date((w.date || "") + "T00:00:00");
    var dayNumEl = document.createElement("div");
    dayNumEl.className = "entry-day-num";
    dayNumEl.textContent = isNaN(d.getDate()) ? "" : d.getDate();
    var dayNameEl = document.createElement("div");
    dayNameEl.className = "entry-day-name";
    dayNameEl.textContent = isNaN(d.getDay()) ? "" : DAY_ABBR[d.getDay()];
    dateCol.appendChild(dayNumEl);
    dateCol.appendChild(dayNameEl);

    var typeKey = normalizeTypeKey(w.type);
    var TYPE_LABELS = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
    var typeSlug = TYPE_LABELS[typeKey] ? typeKey : 'other';
    row.classList.add('entry-row--' + typeSlug);
    // issue #637: data attributes for client-side filtering
    row.dataset.workoutType  = typeKey;
    row.dataset.workoutTitle = (w.title || '').toLowerCase();
    var badge = document.createElement('span');
    badge.className = 'entry-type entry-type--' + typeSlug;
    var dot = document.createElement('span');
    dot.className = 'entry-type-dot';
    badge.appendChild(dot);
    var typeLbl = document.createElement("span");
    typeLbl.className = "entry-type-label";
    typeLbl.textContent = (TYPE_LABELS[typeKey] || w.type || "").toUpperCase();
    badge.appendChild(typeLbl);

    var body = document.createElement("div");
    body.className = "entry-body";

    var titleEl = document.createElement("div");
    titleEl.className = "entry-title";
    titleEl.textContent = w.title || "Workout";
    body.appendChild(titleEl);

    var metaParts = [];
    if (w.duration_seconds) metaParts.push(fmtDurationRow(w.duration_seconds));
    if (typeKey === "run" && w.average_pace_seconds_per_km) {
      metaParts.push(fmtPace(w.average_pace_seconds_per_km));
    }
    if (w.avg_hr != null) metaParts.push("HR " + w.avg_hr);
    metaParts = metaParts.filter(Boolean);

    if (metaParts.length) {
      var metaEl = document.createElement("div");
      metaEl.className = "entry-meta";
      metaEl.textContent = metaParts.join(" · ");
      body.appendChild(metaEl);
    }

    var metricEl = document.createElement("div");
    metricEl.className = "entry-metric";
    var metricPrimary = document.createElement("div");
    metricPrimary.className = "entry-metric-primary";
    var metricSecondary = document.createElement("div");
    metricSecondary.className = "entry-metric-secondary";
    if (typeKey === "run" && w.distance_km != null) {
      metricPrimary.textContent = (+w.distance_km).toFixed(1) + " km";
      if (w.duration_seconds)
        metricSecondary.textContent = fmtDurationRow(w.duration_seconds);
    } else if (w.duration_seconds) {
      var mins = Math.round(w.duration_seconds / 60);
      metricPrimary.textContent = mins + " min";
    }
    metricEl.appendChild(metricPrimary);
    if (metricSecondary.textContent) metricEl.appendChild(metricSecondary);

    var tssEl = null;
    if (w.tss != null) {
      tssEl = document.createElement("span");
      var tc = w.tss > 80 ? "tss-high" : w.tss > 50 ? "tss-mid" : "tss-low";
      tssEl.className = "tss-pill " + tc;
      tssEl.textContent = "TSS " + Math.round(w.tss);
    }

    var sourcesWrap = document.createElement("div");
    sourcesWrap.className = "source-badges-wrap";
    var isStrava = !!w.has_strava;
    var isStryd = !!w.has_stryd;
    if (isStrava) {
      var sbadge = document.createElement("span");
      sbadge.className = "source-badge source-badge--strava";
      sbadge.textContent = "St";
      sourcesWrap.appendChild(sbadge);
    }
    if (isStryd) {
      var sbadgeStryd = document.createElement("span");
      sbadgeStryd.className = "source-badge source-badge--stryd";
      sbadgeStryd.textContent = "S";
      sourcesWrap.appendChild(sbadgeStryd);
    }
    if (!isStrava && !isStryd) {
      var sbadgeM = document.createElement("span");
      sbadgeM.className = "source-badge source-badge--manual";
      sbadgeM.setAttribute("aria-label", "Manual");
      sbadgeM.innerHTML = "&#9998;";
      sourcesWrap.appendChild(sbadgeM);
    }

    var chevron = document.createElement("span");
    chevron.className = "entry-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.innerHTML = "&#8250;";

    row.appendChild(dateCol);
    row.appendChild(badge);
    row.appendChild(body);
    row.appendChild(metricEl);
    if (tssEl) row.appendChild(tssEl);
    row.appendChild(sourcesWrap);
    row.appendChild(chevron);

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

    var formWrap = document.getElementById("dp-form-wrap");
    var formActions = document.getElementById("dp-actions-form");
    if (formWrap) formWrap.style.display = "none";
    if (formActions) formActions.style.display = "none";

    setHistoryTab("history");

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
      menuDelete.style.display = hasWorkout && !isStrava ? "" : "none";
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

    var shotBtn = document.getElementById("dp-screenshot-btn");
    if (shotBtn) shotBtn.disabled = true;

    var scrollEl = document.getElementById("dp-scroll");
    var savedScrollTop = scrollEl ? scrollEl.scrollTop : 0;
    if (scrollEl) scrollEl.scrollTop = 0;

    var panel = document.getElementById("detail-panel");
    var panelWidth = panel ? panel.getBoundingClientRect().width : 520;
    var captureWidth = Math.max(Math.round(panelWidth - 36), 280);

    var host = document.createElement("div");
    host.className = "dp-screenshot-capture";
    host.setAttribute("aria-hidden", "true");
    host.style.cssText =
      "position:fixed;left:-10000px;top:0;width:" +
      captureWidth +
      "px;background:#fff;padding:0;box-sizing:border-box;pointer-events:none;z-index:-1;";

    var clone = contentEl.cloneNode(true);
    host.appendChild(clone);
    document.body.appendChild(host);

    var overflowPatches = expandScreenshotOverflow(clone);

    window
      .html2canvas(host, {
        backgroundColor: "#ffffff",
        scale: window.devicePixelRatio > 1 ? 2 : 1.5,
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
      var exCards = "";
      exercises.forEach(function (ex) {
        var vol = _calcExVolume(ex);
        totalVol += vol;
        var rpe = _avgRpeFromEx(ex);
        if (rpe != null) {
          rpeSum += parseFloat(rpe);
          rpeCount += 1;
        }
        var volStr =
          vol > 0 ? Math.round(vol).toLocaleString() + " kg" : "\u2014";
        exCards +=
          '<div class="dp-ex-card dp-exercise-item">' +
          '<div class="dp-ex-card-head">' +
          '<span class="dp-ex-card-name">' +
          esc(ex.name || "\u2014") +
          "</span>" +
          '<span class="dp-ex-card-vol">' +
          esc(volStr) +
          "</span>" +
          "</div>" +
          '<div class="dp-ex-card-body">' +
          '<span class="dp-ex-card-sub">' +
          esc(_formatStrengthExSub(ex)) +
          "</span>" +
          (rpe
            ? '<span class="dp-ex-card-rpe">RPE ' + esc(rpe) + "</span>"
            : "") +
          "</div>" +
          "</div>";
      });
      var avgRpeFoot = rpeCount ? (rpeSum / rpeCount).toFixed(1) : "\u2014";
      var volFoot =
        totalVol > 0 ? Math.round(totalVol).toLocaleString() + " kg" : "\u2014";
      exercisesHtml =
        '<div class="dp-section">' +
        rpeProfile +
        '<div class="dp-section-title">Exercises</div>' +
        '<div class="dp-ex-list">' +
        exCards +
        "</div>" +
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
  function deleteWorkout(workoutId) {
    if (!confirm("Delete this workout? This cannot be undone.")) return;

    fetch("/api/workouts/" + workoutId, { method: "DELETE" })
      .then(function (res) {
        if (!res.ok && res.status !== 204)
          throw new Error("HTTP " + res.status);
        UIStates.showToast("Workout deleted");
        closeDetailPanel();
        fetchAndRender();
      })
      .catch(function () {
        UIStates.showToast("Could not delete workout. Please try again.", true);
      });
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
    var allBtn = document.getElementById("sync-all-btn");
    if (allBtn) allBtn.disabled = busy;
    // Legacy: also disable old Strava-only button if it exists
    var stravaBtn = document.getElementById("sync-strava-btn");
    if (stravaBtn) stravaBtn.disabled = busy;
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
          _loadSyncChip();
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

  function _syncSinceDate(latest) {
    if (!latest || !latest.synced_at) return null;
    var d = new Date(latest.synced_at);
    if (isNaN(d.getTime())) return null;
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }

  function _syncWaitForComplete() {
    return new Promise(function (resolve) {
      function poll() {
        fetch("/api/sync/status")
          .then(function (res) {
            return res.ok ? res.json() : null;
          })
          .then(function (data) {
            if (!data || data.status !== "running") {
              resolve();
            } else {
              setTimeout(poll, 2000);
            }
          })
          .catch(resolve);
      }
      poll();
    });
  }

  function _syncProvider(url, sinceDate) {
    var body = sinceDate
      ? JSON.stringify({ since_date: sinceDate })
      : "{}";
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    }).then(function (r) {
      if (r.status === 202 || r.status === 409) {
        return _syncWaitForComplete();
      }
      return null;
    });
  }

  function _onSyncAllClick() {
    _syncSetBusy(true);
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
    ])
      .then(function (latest) {
        var stravaSince = _syncSinceDate(latest[0]);
        var strydSince = _syncSinceDate(latest[1]);
        return _syncProvider("/api/strava/sync", stravaSince).then(function () {
          return _syncProvider("/api/stryd/sync", strydSince);
        });
      })
      .then(function () {
        if (window.syncBarRefresh) window.syncBarRefresh();
        _loadSyncChip();
      })
      .catch(function () {
        /* best-effort */
      })
      .finally(function () {
        _syncSetBusy(false);
      });
  }

  function _onSyncStravaClick() {
    _onSyncAllClick();
  }

  function handleEditorSaved(result) {
    if (!result || !result.ok) return;

    if (result.isEdit && activeDetailWorkoutId) {
      setPanelMode("view");
      fetchAndRenderDetail(activeDetailWorkoutId);
      fetchAndRender();
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
        if (activeDetailWorkoutId) deleteWorkout(activeDetailWorkoutId);
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

    var syncStravaBtn = document.getElementById("sync-strava-btn");
    if (syncStravaBtn)
      syncStravaBtn.addEventListener("click", _onSyncStravaClick);

    var syncAllBtn = document.getElementById("sync-all-btn");
    if (syncAllBtn) syncAllBtn.addEventListener("click", _onSyncAllClick);

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
  });

  window.addEventListener("userChanged", function () {
    loadAndRender(currentMonday);
  });

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
        if (!d) { d = { types: [], totalTss: 0 }; calDayData[entry.date] = d; }
        var t = (entry.type || '').toLowerCase();
        if (t && d.types.indexOf(t) === -1) d.types.push(t);
        if (entry.tss > 0) d.totalTss += entry.tss;
      });
    });
  }

  function renderCalendar() {
    var el = document.getElementById('log-calendar');
    if (!el) return;

    var now   = new Date();
    if (!calCurrentMonth) {
      calCurrentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    }

    var year  = calCurrentMonth.getFullYear();
    var month = calCurrentMonth.getMonth();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var todayStr = pad(today.getFullYear()) + '-' + pad(today.getMonth() + 1) + '-' + pad(today.getDate());

    // Last day of month
    var lastDayNum = new Date(year, month + 1, 0).getDate();

    // Compute max TSS in this month for bar scaling
    var maxTss = 0;
    for (var d = 1; d <= lastDayNum; d++) {
      var ds = year + '-' + pad(month + 1) + '-' + pad(d);
      var dd = calDayData[ds];
      if (dd && dd.totalTss > maxTss) maxTss = dd.totalTss;
    }
    if (maxTss < 1) maxTss = 1;

    // Week starts Monday: offset = (firstDay.getDay() + 6) % 7
    var firstDow    = new Date(year, month, 1).getDay();
    var startOffset = (firstDow + 6) % 7;
    var totalCells  = startOffset + lastDayNum;
    var rows        = Math.ceil(totalCells / 7);

    var isCurrentMonth = year === now.getFullYear() && month === now.getMonth();

    var html = '<div class="cal-nav">' +
      '<button type="button" id="log-cal-prev" class="cal-nav-btn" aria-label="Previous month">&#8249;</button>' +
      '<span id="log-cal-title" class="cal-month-label">' + CAL_MONTH_NAMES[month] + ' ' + year + '</span>' +
      '<button type="button" id="log-cal-today" class="cal-nav-btn cal-nav-btn--today"' +
        (isCurrentMonth ? ' disabled' : '') + '>Today</button>' +
      '<button type="button" id="log-cal-next" class="cal-nav-btn" aria-label="Next month">&#8250;</button>' +
    '</div>' +
    '<div class="cal-grid" role="grid" aria-label="' + CAL_MONTH_NAMES[month] + ' ' + year + '">';

    // Weekday headers
    CAL_WEEKDAY_ABBR.forEach(function (abbr) {
      html += '<div class="cal-weekday" role="columnheader">' + esc(abbr) + '</div>';
    });

    // Day cells
    var dayNum = 1;
    for (var row = 0; row < rows; row++) {
      for (var col = 0; col < 7; col++) {
        var cellIdx = row * 7 + col;
        if (cellIdx < startOffset || dayNum > lastDayNum) {
          html += '<div class="cal-cell cal-cell--empty" aria-hidden="true"></div>';
        } else {
          var dStr       = year + '-' + pad(month + 1) + '-' + pad(dayNum);
          var dd2        = calDayData[dStr];
          var isToday    = dStr === todayStr;
          var isSel      = dStr === calSelectedDate;
          var isFuture   = dStr > todayStr;

          var cls = 'cal-cell';
          if (isToday)  cls += ' cal-cell--today';
          if (isSel)    cls += ' is-selected';
          if (isFuture) cls += ' cal-cell--future';

          var ariaLbl = new Date(year, month, dayNum).toLocaleDateString('en-US', {
            weekday: 'long', month: 'long', day: 'numeric'
          });
          if (dd2 && dd2.types.length) ariaLbl += '. Workouts: ' + dd2.types.join(', ');

          html += '<button type="button" class="' + cls + '"' +
            ' data-date="' + dStr + '"' +
            ' aria-label="' + esc(ariaLbl) + '"' +
            ' aria-pressed="' + (isSel ? 'true' : 'false') + '">';

          html += '<span class="cal-day-num">' + dayNum + '</span>';

          // Type dots
          html += '<div class="cal-dots">';
          if (dd2 && dd2.types.length) {
            TYPE_ORDER
              .filter(function (t) { return dd2.types.indexOf(t) !== -1; })
              .forEach(function (t) {
                var col2 = TYPE_COLORS[t] || '#888';
                html += '<span class="cal-dot" style="background:' + col2 + '" aria-hidden="true"></span>';
              });
          }
          html += '</div>';

          // Load bar
          html += '<div class="cal-load">';
          if (dd2 && dd2.totalTss > 0) {
            var barPct = Math.min(100, Math.round(dd2.totalTss / maxTss * 100));
            html += '<div class="cal-load-bar" style="width:' + barPct + '%" aria-hidden="true"></div>';
          }
          html += '</div>';

          html += '</button>';
          dayNum++;
        }
      }
    }

    html += '</div>'; // .cal-grid
    el.innerHTML = html;

    // Wire navigation buttons
    var prevBtn  = document.getElementById('log-cal-prev');
    var nextBtn  = document.getElementById('log-cal-next');
    var todayBtn = document.getElementById('log-cal-today');

    if (prevBtn) prevBtn.addEventListener('click', function () {
      calCurrentMonth = new Date(year, month - 1, 1);
      renderCalendar();
    });

    if (nextBtn) nextBtn.addEventListener('click', function () {
      calCurrentMonth = new Date(year, month + 1, 1);
      renderCalendar();
    });

    if (todayBtn) todayBtn.addEventListener('click', function () {
      var t = new Date();
      var tStr = pad(t.getFullYear()) + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
      calCurrentMonth = new Date(t.getFullYear(), t.getMonth(), 1);
      if (calDayData[tStr]) calSelectedDate = tStr;
      renderCalendar();
      if (calSelectedDate === tStr) calScrollToDate(tStr);
    });

    // Wire day cell clicks via delegation
    var grid = el.querySelector('.cal-grid');
    if (grid) {
      grid.addEventListener('click', function (e) {
        var cell = e.target.closest('.cal-cell:not(.cal-cell--empty)');
        if (!cell) return;
        var date = cell.getAttribute('data-date');
        if (!date) return;
        calSelectedDate = date;
        // Update highlight in place (no full re-render)
        el.querySelectorAll('.cal-cell').forEach(function (c) {
          var sel = c.getAttribute('data-date') === date;
          c.classList.toggle('is-selected', sel);
          c.setAttribute('aria-pressed', sel ? 'true' : 'false');
        });
        calScrollToDate(date);
      });

      // Keyboard: Enter/Space triggers click; arrows move focus within grid
      grid.addEventListener('keydown', function (e) {
        var cell = e.target.closest('.cal-cell:not(.cal-cell--empty)');
        if (!cell) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          cell.click();
          return;
        }
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' &&
            e.key !== 'ArrowUp'   && e.key !== 'ArrowDown') return;
        e.preventDefault();
        var cells = Array.prototype.slice.call(
          grid.querySelectorAll('.cal-cell:not(.cal-cell--empty)')
        );
        var idx = cells.indexOf(cell);
        var delta = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 7, ArrowUp: -7 }[e.key];
        var newIdx = idx + delta;
        if (newIdx >= 0 && newIdx < cells.length) cells[newIdx].focus();
      });
    }
  }

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
