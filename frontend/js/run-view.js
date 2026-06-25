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

  function fmtPace(distKm, durSec) {
    if (!distKm || !durSec) return "—";
    var secPerKm = durSec / distKm;
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    return m + ":" + String(s).padStart(2, "0") + " /km";
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

  function copyToClipboard(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(function () {});
    }
  }

  // ── State ──────────────────────────────────────────────────────────────────

  var _workoutId = null;
  var _fullData = null;
  var _lapMetric = "pace"; // 'pace' | 'hr' | 'power'

  // ── URL param parsing ─────────────────────────────────────────────────────

  function getWorkoutId() {
    var params = new URLSearchParams(window.location.search);
    return params.get("id");
  }

  // ── Segment-effort profile ─────────────────────────────────────────────────

  var EFFORT_COLORS = {
    easy: "#86efac", // green
    tempo: "#fcd34d", // amber
    hard: "#fb923c", // orange
    race: "#f87171", // red-ish
    recovery: "#cbd5e1", // grey
    warmup: "#bfdbfe", // light blue
    cooldown: "#a5f3fc", // cyan
  };

  function segmentColor(effort) {
    return EFFORT_COLORS[effort] || EFFORT_COLORS.easy;
  }

  function renderSegmentBar(segments, totalDist) {
    if (!segments || !segments.length) return "";
    var bars = segments.map(function (seg) {
      var pct = totalDist
        ? (seg.distance_km / totalDist) * 100
        : 100 / segments.length;
      var effort = (seg.band || seg.effort || "easy").toLowerCase();
      var color = segmentColor(effort);
      var heightPct =
        effort === "hard" || effort === "race"
          ? 100
          : effort === "tempo"
            ? 70
            : effort === "recovery"
              ? 30
              : 50;
      return (
        '<div class="rv-seg-bar-block" style="width:' +
        pct.toFixed(1) +
        "%;background:" +
        color +
        ";height:" +
        heightPct +
        '%"></div>'
      );
    });
    return '<div class="rv-seg-bar">' + bars.join("") + "</div>";
  }

  function renderSegmentRows(segments) {
    if (!segments || !segments.length)
      return '<p class="rv-empty">No segment data</p>';
    return segments
      .map(function (seg) {
        var effort = (seg.band || seg.effort || "easy").toLowerCase();
        var color = segmentColor(effort);
        return (
          '<div class="rv-seg-row">' +
          '<span class="rv-seg-bullet" style="background:' +
          color +
          '"></span>' +
          '<span class="rv-seg-name">' +
          esc(seg.label || seg.name || effort) +
          "</span>" +
          '<span class="rv-seg-dist">' +
          dash(seg.distance_km ? seg.distance_km.toFixed(2) + " km" : null) +
          "</span>" +
          '<span class="rv-seg-dur">' +
          fmtDuration(seg.duration_seconds) +
          "</span>" +
          '<span class="rv-seg-pace">' +
          fmtPace(seg.distance_km, seg.duration_seconds) +
          "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  // ── Session profile: per-lap bars + named zone brackets ───────────────────

  var PHASE_NAME = { warmup: "Warm-up", steady: "Steady", tempo: "Tempo", threshold: "Threshold", cooldown: "Cool-down" };
  var PHASE_H = { warmup: 45, steady: 60, tempo: 85, threshold: 95, cooldown: 30 };
  // Physiological intensity ranking — drives surge (up) vs dip (down) for
  // deviations; never hardcoded per session.
  var KEY_RANK = { cooldown: 0, warmup: 1, recovery: 0, easy: 1, steady: 2, tempo: 3, threshold: 4, hard: 5, race: 6 };
  function keyRank(k) { var r = KEY_RANK[k]; return r == null ? 2 : r; }

  // Map a phase label (or its band) to one of the five named colors.
  function phaseKey(label, band) {
    var s = (label || "").toLowerCase().replace(/[^a-z]/g, "");
    if (s.indexOf("warm") === 0) return "warmup";
    if (s.indexOf("cool") === 0) return "cooldown";
    if (s.indexOf("steady") === 0 || s.indexOf("easy") === 0) return "steady";
    if (s.indexOf("tempo") === 0) return "tempo";
    if (s.indexOf("threshold") === 0) return "threshold";
    var b = (band || "").toLowerCase();
    if (b === "tempo") return "tempo";
    if (b === "hard" || b === "race") return "threshold";
    return "steady";
  }

  function gridSpans(n) {
    var s = "";
    for (var i = 0; i < n; i++) s += "<span></span>";
    return s;
  }

  function fmtPaceSec(sec) {
    if (sec == null) return "—";
    var m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  var SP_LEGEND =
    '<div class="rv2-legend">' +
    '<span><i class="rv2-dot" style="background:var(--rv2-warmup)"></i>Warm-up</span>' +
    '<span><i class="rv2-dot" style="background:var(--rv2-steady)"></i>Steady</span>' +
    '<span><i class="rv2-dot" style="background:var(--rv2-tempo)"></i>Tempo</span>' +
    '<span><i class="rv2-dot" style="background:var(--rv2-threshold)"></i>Threshold</span>' +
    '<span><i class="rv2-dot" style="background:var(--rv2-cooldown)"></i>Cool-down</span>' +
    "</div>";

  function _avg(arr) {
    var v = arr.filter(function (x) { return x != null && !isNaN(x); });
    return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
  }
  function _lapRange(from, to) { return from === to ? "" + (from + 1) : (from + 1) + "–" + (to + 1); }

  // Session profile. Two regimes chosen automatically from the data:
  //  - STRUCTURED: a few clean phases → per-lap bars + named zone brackets.
  //  - VARIABLE/RACE: one dominant band with scattered deviations → bars + a
  //    "Sustained <band>" headline (avg power of the dominant laps only) and
  //    deviation chips (band, direction, count, group avg power, lap numbers),
  //    with up/down triangle markers on the deviating bars.
  function renderSessionProfile(data) {
    var dp = data.detected_profile || {};
    var phases = dp.phases || [];
    var splits = data.splits || [];

    // Fallback to the legacy phase-segment bar when no per-lap grouping exists.
    if (!phases.length || !splits.length) {
      var totalDist = (data.workout && data.workout.distance_km) || 0;
      return (
        renderSegmentBar(phases, totalDist) +
        '<div class="rv-seg-rows">' + renderSegmentRows(phases) + "</div>"
      );
    }

    // Per-lap phase key + name from the detected phases' lap_indexes.
    var lapPhase = [];
    phases.forEach(function (ph) {
      var key = phaseKey(ph.label, ph.band);
      (ph.lap_indexes || []).forEach(function (idx) {
        lapPhase[idx] = { key: key, name: PHASE_NAME[key] };
      });
    });
    var dbgLaps = (dp.debug && dp.debug.laps) || [];
    var n = splits.length;
    var keyOf = [];
    for (var i = 0; i < n; i++) {
      keyOf[i] = (lapPhase[i] && lapPhase[i].key) || phaseKey(null, (dbgLaps[i] || {}).band);
    }

    // STEP 1 — smooth single-lap flickers between two same-band neighbours,
    // so they don't fragment the structured view (recorded as deviations).
    for (var j = 1; j < n - 1; j++) {
      if (keyOf[j] !== keyOf[j - 1] && keyOf[j - 1] === keyOf[j + 1]) {
        keyOf[j] = "__dev:" + keyOf[j];  // mark; resolved below per regime
      }
    }
    var rawKey = keyOf.map(function (k) { return k.indexOf("__dev:") === 0 ? k.slice(6) : k; });
    var smoothKey = keyOf.map(function (k, idx) {
      return k.indexOf("__dev:") === 0 ? rawKey[idx - 1] : k;
    });

    // STEP 2 — regime detection on the smoothed sequence.
    function runsOf(seq) {
      var r = [], cur = null;
      seq.forEach(function (k, idx) {
        if (!cur || cur.key !== k) { cur = { key: k, from: idx, to: idx }; r.push(cur); }
        else cur.to = idx;
      });
      return r;
    }
    var counts = {};
    rawKey.forEach(function (k) { counts[k] = (counts[k] || 0) + 1; });
    var domKey = null, domN = 0;
    Object.keys(counts).forEach(function (k) { if (counts[k] > domN) { domN = counts[k]; domKey = k; } });
    var domShare = domN / n;
    var devRuns = runsOf(rawKey).filter(function (run) { return run.key !== domKey; });
    var shortDev = devRuns.filter(function (run) { return run.to - run.from + 1 <= 2; });
    var variable =
      dp.reps_detected != null ||
      domShare >= 0.65 ||
      (shortDev.length >= 2 && domShare >= 0.45);

    var basis = dp.basis && dp.basis !== "none" ? dp.basis.toUpperCase() : "—";
    var repsTxt = dp.reps_detected != null ? " · REPS " + dp.reps_detected : "";
    var titleHtml =
      '<div class="rv2-card-title"><span>Session profile · effort</span>' +
      '<span class="rv2-basis">BASIS · ' + basis + repsTxt + "</span></div>";

    // ── STRUCTURED ──
    if (!variable) {
      var sBars = splits.map(function (s, idx) {
        var k = smoothKey[idx];
        var w = parseFloat(s.distance_km) || 0.01;
        var ratio = dbgLaps[idx] && dbgLaps[idx].ratio != null ? dbgLaps[idx].ratio : null;
        var h = ratio != null ? Math.max(6, Math.min(100, Math.round(ratio * 100))) : PHASE_H[k];
        return '<div class="rv2-cell" style="flex:' + w + ' 0 0">' +
          '<div class="rv2-bar" style="height:' + h + "%;background:var(--rv2-" + k + ')"></div></div>';
      }).join("");
      var groups = [], cg = null;
      splits.forEach(function (s, idx) {
        var k = smoothKey[idx], w = parseFloat(s.distance_km) || 0.01;
        if (!cg || cg.key !== k) { cg = { key: k, from: idx, to: idx, w: w }; groups.push(cg); }
        else { cg.to = idx; cg.w += w; }
      });
      var brackets = groups.map(function (g) {
        var range = "lap " + _lapRange(g.from, g.to);
        return '<div class="rv2-cell rv2-bracket" style="flex:' + g.w + ' 0 0">' +
          '<div class="rv2-bracket-line"></div>' +
          '<div class="rv2-bracket-name nm-' + g.key + '">' + esc(PHASE_NAME[g.key] || g.key) + "</div>" +
          '<div class="rv2-bracket-range">' + range + "</div></div>";
      }).join("");
      return titleHtml +
        '<div class="rv2-sp-chart"><div class="rv2-grid">' + gridSpans(4) + "</div>" +
        '<div class="rv2-row rv2-sp-bars">' + sBars + "</div></div>" +
        '<div class="rv2-row rv2-bracket-row">' + brackets + "</div>" + SP_LEGEND;
    }

    // ── VARIABLE / RACE ──
    // Deviation = any maximal run of a non-dominant band; direction by rank.
    var devDir = {};   // lap index → 'up' | 'down'
    devRuns.forEach(function (run) {
      var dir = keyRank(run.key) > keyRank(domKey) ? "up" : "down";
      for (var k = run.from; k <= run.to; k++) devDir[k] = dir;
    });

    var vBars = splits.map(function (s, idx) {
      var k = rawKey[idx];
      var w = parseFloat(s.distance_km) || 0.01;
      var ratio = dbgLaps[idx] && dbgLaps[idx].ratio != null ? dbgLaps[idx].ratio : null;
      var h = ratio != null ? Math.max(6, Math.min(100, Math.round(ratio * 100))) : PHASE_H[k];
      var mark = devDir[idx]
        ? '<i class="rv2-dev-mark rv2-dev-' + devDir[idx] + '" style="color:var(--rv2-' + k + ')">' +
          (devDir[idx] === "up" ? "▲" : "▼") + "</i>"
        : "";
      return '<div class="rv2-cell" style="flex:' + w + ' 0 0">' + mark +
        '<div class="rv2-bar" style="height:' + h + "%;background:var(--rv2-" + k + ')"></div></div>';
    }).join("");

    // Headline: dominant band + avg power of the dominant laps only.
    var domIdx = [];
    for (var di = 0; di < n; di++) if (rawKey[di] === domKey) domIdx.push(di);
    var domPow = _avg(domIdx.map(function (idx) { return splits[idx].avg_power; }));
    var hlNum = "";
    if (domPow != null) {
      hlNum = '<div class="rv2-hl-num">' + Math.round(domPow) + '<span>W avg</span></div>';
    } else {
      var domPace = _avg(domIdx.map(function (idx) {
        var d = parseFloat(splits[idx].distance_km), du = splits[idx].duration_seconds;
        return d && du ? du / d : null;
      }));
      if (domPace != null) hlNum = '<div class="rv2-hl-num">' + fmtPaceSec(domPace) + '<span>/km avg</span></div>';
    }
    var headline =
      '<div class="rv2-headline">' +
      '<span class="rv2-hl-swatch" style="background:var(--rv2-' + domKey + ')"></span>' +
      '<div class="rv2-hl-text"><div class="rv2-hl-title">Sustained ' + esc(PHASE_NAME[domKey] || domKey) + "</div>" +
      '<div class="rv2-hl-sub">' + domN + " of " + n + " laps</div></div>" + hlNum + "</div>";

    // Deviation chips grouped by (band, direction).
    var grp = {};
    devRuns.forEach(function (run) {
      var dir = keyRank(run.key) > keyRank(domKey) ? "up" : "down";
      var gk = run.key + "|" + dir;
      if (!grp[gk]) grp[gk] = { key: run.key, dir: dir, runs: [], laps: [] };
      grp[gk].runs.push(run);
      for (var k = run.from; k <= run.to; k++) grp[gk].laps.push(k);
    });
    var chips = Object.keys(grp).sort(function (a, b) {
      return (grp[b].dir === "up") - (grp[a].dir === "up");  // surges first
    }).map(function (gk) {
      var g = grp[gk];
      var ranges = g.runs.map(function (r) { return _lapRange(r.from, r.to); }).join(", ");
      var gp = _avg(g.laps.map(function (idx) { return splits[idx].avg_power; }));
      var pw = gp != null ? Math.round(gp) + " W · " : "";
      var arrow = g.dir === "up" ? "↑" : "↓";
      return '<span class="rv2-chip rv2-chip-' + g.dir + '">' +
        '<span class="rv2-chip-arrow">' + arrow + "</span> " +
        esc(PHASE_NAME[g.key] || g.key) + " ×" + g.runs.length + " · " + pw + "lap " + ranges + "</span>";
    }).join("");

    return titleHtml +
      '<div class="rv2-sp-chart"><div class="rv2-grid">' + gridSpans(4) + "</div>" +
      '<div class="rv2-row rv2-sp-bars">' + vBars + "</div></div>" +
      headline +
      (chips ? '<div class="rv2-dev-chips">' + chips + "</div>" : "");
  }

  // ── Lap bar chart ─────────────────────────────────────────────────────────

  function lapMetricValue(lap, metric) {
    if (metric === "hr") return lap.avg_hr;
    if (metric === "power") return lap.avg_power;
    // pace = seconds per km (lower = faster)
    if (!lap.distance_km || !lap.duration_seconds) return null;
    return lap.duration_seconds / parseFloat(lap.distance_km);
  }

  // One combined chart: bars for the chosen metric (pace|power) on their own
  // scale + HR drawn as a line on its own independent scale. Dotted gridlines
  // behind, lap-number axis below, and a legend giving each series' real range.
  function renderLapChart(splits, metric) {
    if (!splits || !splits.length) return "";
    var barMetric = metric === "power" ? "power" : "pace";
    var barColor = barMetric === "power" ? "var(--rv2-power)" : "var(--rv2-bar)";

    var values = splits.map(function (s) { return lapMetricValue(s, barMetric); });
    var valid = values.filter(function (v) { return v != null && v > 0; });
    var vmin = valid.length ? Math.min.apply(null, valid) : 0;
    var vmax = valid.length ? Math.max.apply(null, valid) : 0;
    var vr = vmax - vmin || 1;

    var bars = splits.map(function (s, i) {
      var v = values[i];
      var z2 = window.Zone2.isZone2Lap(s.avg_hr) ? " rv-bar--z2" : "";
      if (v == null || !valid.length) {
        // null stays a (flat) dash — no fabricated height.
        return '<div class="rv2-cell" style="flex:1 0 0"><div class="rv2-cbar' + z2 +
          '" style="height:5%;background:#e2e8f0"></div></div>';
      }
      // Pace: faster (smaller sec/km) = taller, so invert. Power: more W = taller.
      var norm = barMetric === "pace" ? 1 - (v - vmin) / vr : (v - vmin) / vr;
      var h = Math.round(10 + norm * 86);
      return '<div class="rv2-cell" style="flex:1 0 0"><div class="rv2-cbar' + z2 +
        '" style="height:' + h + "%;background:" + barColor + '"></div></div>';
    }).join("");

    var axis = splits.map(function (s, i) {
      return '<div class="rv2-cell" style="flex:1 0 0">' + (i + 1) + "</div>";
    }).join("");

    // HR line — independent scale; null laps just omit a point (no fabrication).
    var hrVals = splits.map(function (s) { return s.avg_hr; });
    var hValid = hrVals.filter(function (v) { return v != null && v > 0; });
    var hmin = hValid.length ? Math.min.apply(null, hValid) : 0;
    var hmax = hValid.length ? Math.max.apply(null, hValid) : 0;
    var hrng = hmax - hmin || 1;
    var n = splits.length;
    var pts = [];
    splits.forEach(function (s, i) {
      if (s.avg_hr == null || s.avg_hr <= 0) return;
      var x = ((i + 0.5) / n) * 100;
      var y = 100 - (((s.avg_hr - hmin) / hrng) * 80 + 8);
      pts.push(x.toFixed(2) + "," + y.toFixed(2));
    });
    var svg = '<svg class="rv2-hr-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">';
    if (pts.length >= 2) {
      svg += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="var(--rv2-hr)" ' +
        'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
    }
    // Round-cap zero-length dots: constant pixel size (non-scaling stroke), so
    // they stay round instead of stretching with the non-uniform viewBox.
    pts.forEach(function (p) {
      var xy = p.split(",");
      svg += '<path d="M' + xy[0] + " " + xy[1] + 'l0 0" stroke="var(--rv2-hr)" ' +
        'stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
    });
    svg += "</svg>";

    var barLabel = barMetric === "power"
      ? "Power (" + (valid.length ? vmin + "–" + vmax : "—") + " W)"
      : "Pace (" + (valid.length ? fmtPaceSec(vmin) + "–" + fmtPaceSec(vmax) : "—") + "/km)";
    var hrLabel = "HR (" + (hValid.length ? hmin + "–" + hmax : "—") + " bpm)";
    var legend =
      '<div class="rv2-chart-legend">' +
      '<span><i class="rv2-swatch" style="background:' + barColor + '"></i>' + barLabel + "</span>" +
      '<span><i class="rv2-hr-key"></i>' + hrLabel + "</span></div>";

    return (
      '<div class="rv2-chart"><div class="rv2-grid">' + gridSpans(4) + "</div>" +
      '<div class="rv2-row rv2-chart-bars">' + bars + "</div>" + svg + "</div>" +
      '<div class="rv2-row rv2-axis">' + axis + "</div>" + legend
    );
  }

  // ── Lap table ─────────────────────────────────────────────────────────────

  function renderLapTable(splits, hasStryd) {
    if (!splits || !splits.length) return '<p class="rv-empty">No lap data</p>';
    var hasManualLaps = splits.some(function (s) {
      return s.lap_type === "manual";
    });
    var allAuto = !hasManualLaps && splits.every(function (s) {
      return (s.lap_type || "auto") === "auto";
    });
    var header = allAuto ? "Laps · 1 km splits" : "Laps";

    var rows = splits.map(function (s, i) {
      var isZ2 = window.Zone2.isZone2Lap(s.avg_hr);
      var lapNum = isZ2
        ? '<span class="rv-lap-num">' +
          (i + 1) +
          '</span><span class="rv-z2-pill">Z2</span>'
        : '<span class="rv-lap-num">' + (i + 1) + "</span>";
      var dist = parseFloat(s.distance_km);
      var distLabel = isNaN(dist) ? "—" : dist.toFixed(2) + " km";
      var rowClass = isZ2 ? " rv-lap-row--z2" : "";
      return (
        '<tr class="rv-lap-row' +
        rowClass +
        '">' +
        '<td class="rv-td">' +
        lapNum +
        "</td>" +
        '<td class="rv-td rv-mono">' +
        distLabel +
        "</td>" +
        '<td class="rv-td rv-mono">' +
        fmtPace(dist, s.duration_seconds) +
        "</td>" +
        '<td class="rv-td rv-mono">' +
        dash(s.avg_hr ? s.avg_hr + " bpm" : null) +
        "</td>" +
        '<td class="rv-td rv-mono rv-col-len">' +
        dash(s.stride_length_m != null ? s.stride_length_m + " m" : null) +
        "</td>" +
        '<td class="rv-td rv-mono rv-col-cad">' +
        dash(s.cadence_spm ? s.cadence_spm + " spm" : null) +
        "</td>" +
        '<td class="rv-td rv-mono">' +
        dash(s.avg_power ? s.avg_power + " W" : null) +
        "</td>" +
        "</tr>"
      );
    });

    return (
      '<div class="rv-laps-header">' +
      '<h3 class="rv-section-title">' +
      header +
      "</h3>" +
      "</div>" +
      // Toggle switches only the BAR metric; HR is always drawn as the line.
      '<div class="rv-metric-toggle" role="group" aria-label="Lap bar metric">' +
      '<button class="rv-mtog' +
      (_lapMetric === "power" ? "" : " rv-mtog--active") +
      '" data-metric="pace">Pace</button>' +
      '<button class="rv-mtog' +
      (_lapMetric === "power" ? " rv-mtog--active" : "") +
      '" data-metric="power">Power</button>' +
      "</div>" +
      '<div class="rv-lap-chart-wrap">' +
      renderLapChart(splits, _lapMetric) +
      "</div>" +
      '<div class="rv-lap-table-wrap">' +
      '<table class="rv-lap-table">' +
      "<thead><tr>" +
      '<th class="rv-th">Lap</th>' +
      '<th class="rv-th">Distance</th>' +
      '<th class="rv-th">Pace</th>' +
      '<th class="rv-th">HR</th>' +
      '<th class="rv-th rv-col-len">Stride</th>' +
      '<th class="rv-th rv-col-cad">Cadence</th>' +
      '<th class="rv-th">Power</th>' +
      "</tr></thead>" +
      "<tbody>" +
      rows.join("") +
      "</tbody>" +
      "</table>" +
      "</div>"
    );
  }

  // ── Tile helpers ──────────────────────────────────────────────────────────

  function tile(label, value, extra) {
    return (
      '<div class="rv-tile' +
      (extra || "") +
      '">' +
      '<div class="rv-tile-val rv-mono">' +
      dash(value) +
      "</div>" +
      '<div class="rv-tile-label">' +
      label +
      "</div>" +
      "</div>"
    );
  }

  function heroTile(label, value) {
    return tile(label, value, " rv-tile--hero");
  }

  // ── Source strip ──────────────────────────────────────────────────────────

  function renderSourceStrip(workout, strydPresent) {
    var parts = [];
    if (workout.strava_activity_url) {
      parts.push(
        '<a class="rv-src-link" href="' +
          esc(workout.strava_activity_url) +
          '" target="_blank" rel="noopener">View on Strava</a>',
      );
    }
    if (strydPresent) {
      parts.push('<span class="rv-src-badge rv-src-badge--stryd">Stryd</span>');
    }
    var src = (workout.source || "").toLowerCase();
    if (src.indexOf(",") !== -1) {
      var sources = src.split(",").map(function (s) { return s.trim(); });
      parts.push('<span class="rv-src-merged">Merged from ' + sources.join(" + ") + "</span>");
    }
    if (!parts.length) return "";
    return '<div class="rv-source-strip">' + parts.join(" ") + "</div>";
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function renderView(data) {
    var w = data.workout;
    var splits = data.splits || [];
    var strydPresent = !!(data.field_coverage && data.field_coverage.stryd);
    var stravaSrc = !!(data.field_coverage && data.field_coverage.strava);

    // Header
    var shortId = w.id ? w.id.slice(-8) : "—";
    var badges = "";
    if (stravaSrc)
      badges += '<span class="rv-src-badge rv-src-badge--strava">Strava</span>';
    if (strydPresent)
      badges += '<span class="rv-src-badge rv-src-badge--stryd">Stryd</span>';

    var header =
      '<div class="rv-card rv-header">' +
      '<div class="rv-header-left">' +
      '<span class="rv-badge">RUN</span>' +
      '<h1 class="rv-workout-name">' +
      esc(w.name || "Untitled Run") +
      "</h1>" +
      '<div class="rv-short-id">' +
      '<code class="rv-mono rv-id-code">' +
      shortId +
      "</code>" +
      '<button class="rv-copy-btn" title="Copy ID" data-copy="' +
      shortId +
      '">&#x2398;</button>' +
      "</div>" +
      '<div class="rv-date">' +
      (w.workout_date || "—") +
      "</div>" +
      "</div>" +
      '<div class="rv-header-right">' +
      badges +
      "</div>" +
      "</div>";

    // Basic tiles: Distance, Avg Pace, Duration
    var dist = w.distance_km ? w.distance_km.toFixed(2) + " km" : null;
    var pace = fmtPace(w.distance_km, w.duration_seconds);
    var dur = fmtDuration(w.duration_seconds);
    var heroSection =
      '<div class="rv-card rv-hero-row">' +
      tile("Distance", dist, " rv-tile--lg") +
      tile("Avg Pace", pace !== "—" ? pace : null, " rv-tile--lg") +
      tile("Duration", dur, " rv-tile--lg") +
      "</div>";

    // Load & Intensity tiles
    var z2min = w.zone2_minutes != null ? w.zone2_minutes + " min" : null;
    var elev = w.elevation_m != null ? w.elevation_m + " m" : null;
    var avgHr = w.avg_hr != null ? w.avg_hr + " bpm" : null;
    var maxHr = w.max_hr != null ? w.max_hr + " bpm" : null;
    var avgPwr =
      strydPresent && w.avg_power != null ? w.avg_power + " W" : null;
    var maxPwr =
      strydPresent && w.max_power != null ? w.max_power + " W" : null;
    var stride =
      strydPresent && w.avg_stride_m != null ? w.avg_stride_m + " m" : null;
    var cad =
      strydPresent && w.avg_cadence_spm != null
        ? w.avg_cadence_spm + " spm"
        : null;

    var intensitySection =
      '<div class="rv-card rv-intensity">' +
      '<h2 class="rv-section-title">Load &amp; Intensity</h2>' +
      '<div class="rv-tile-grid">' +
      heroTile("TSS", w.tss != null ? Math.round(w.tss) : null) +
      tile("Zone 2", z2min) +
      tile("Elevation", elev) +
      tile("Avg HR", avgHr) +
      tile("Max HR", maxHr) +
      tile("Avg Power", avgPwr) +
      tile("Max Power", maxPwr) +
      tile("Stride Length", stride) +
      tile("Cadence", cad) +
      "</div>" +
      '<p class="rv-footnote">NP · stride = avg per step · cadence = steps/min</p>' +
      "</div>";

    // Session Profile — per-lap bars + named zone brackets from detected_profile.
    var profileSection =
      '<div class="rv-card rv-profile">' +
      renderSessionProfile(data) +
      "</div>";

    // Laps section
    var lapsSection =
      '<div class="rv-card rv-laps" id="rv-laps">' +
      renderLapTable(splits, strydPresent) +
      "</div>";

    // Route placeholder
    var routeSection =
      '<div class="rv-card rv-route">' +
      '<h2 class="rv-section-title">Route</h2>' +
      '<div class="rv-map-placeholder">Map appears once GPS sync is added</div>' +
      "</div>";

    // Source strip — omit card wrapper entirely when there is nothing to show
    var sourceStripHtml = renderSourceStrip(w, strydPresent);
    var sourceSection = sourceStripHtml
      ? '<div class="rv-card rv-source">' + sourceStripHtml + "</div>"
      : "";

    document.getElementById("rv-root").innerHTML =
      header +
      heroSection +
      intensitySection +
      profileSection +
      lapsSection +
      routeSection +
      sourceSection;

    // Copy-to-clipboard with user feedback
    var copyBtn = document.querySelector(".rv-copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var text = copyBtn.dataset.copy;
        if (navigator.clipboard) {
          navigator.clipboard
            .writeText(text)
            .then(function () {
              copyBtn.textContent = "✓";
              copyBtn.title = "Copied!";
              setTimeout(function () {
                copyBtn.innerHTML = "&#x2398;";
                copyBtn.title = "Copy ID";
              }, 1500);
            })
            .catch(function () {});
        }
      });
    }

    // Lap metric toggle
    document.querySelectorAll(".rv-mtog").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _lapMetric = btn.dataset.metric;
        var lapsEl = document.getElementById("rv-laps");
        if (lapsEl) lapsEl.innerHTML = renderLapTable(splits, strydPresent);
        // Re-attach toggle listeners after re-render
        attachToggleListeners(splits, strydPresent);
      });
    });
  }

  function attachToggleListeners(splits, strydPresent) {
    document.querySelectorAll(".rv-mtog").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _lapMetric = btn.dataset.metric;
        var lapsEl = document.getElementById("rv-laps");
        if (lapsEl) lapsEl.innerHTML = renderLapTable(splits, strydPresent);
        attachToggleListeners(splits, strydPresent);
      });
    });
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  function init() {
    _workoutId = getWorkoutId();
    if (!_workoutId) {
      document.getElementById("rv-root").innerHTML =
        '<div class="rv-error">No workout ID supplied. Add ?id=&lt;workout-id&gt; to the URL.</div>';
      return;
    }
    fetch("/api/workouts/" + _workoutId + "/full", { credentials: "include" })
      .then(function (r) {
        if (r.status === 404) throw new Error("Workout not found");
        if (!r.ok) throw new Error("Failed to load workout (" + r.status + ")");
        return r.json();
      })
      .then(function (data) {
        _fullData = data;
        renderView(data);
      })
      .catch(function (err) {
        document.getElementById("rv-root").innerHTML =
          '<div class="rv-error">' + err.message + "</div>";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
