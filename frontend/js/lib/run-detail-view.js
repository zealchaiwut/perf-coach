/* Run detail view v4 — Training > Log side panel (read-only runs).
   Data: GET /api/workouts/{id}/full?streams=none
   Exposed as window.RunDetailView */
(function (win) {
  "use strict";

  var TF = win.TrainingFormat || {};

  /** Run-subtype display labels for the header subtype tag (run_subtype column). */
  var RD4_SUBTYPE_LABELS = { interval: "interval", longrun: "long run", easy: "easy", tempo: "tempo" };

  /** Zone-2 HR band — becomes user preference later (issue #598). */
  var RUN_DETAIL_ZONE2_HR_MIN = 130;
  var RUN_DETAIL_ZONE2_HR_MAX = 155;

  var BAND_COLORS = {
    threshold: "#f97316",
    tempo: "#fbbf24",
    steady: "#22c55e",
    easy: "#86efac",
    hard: "#ef4444",
    recovery: "#cbd5e1",
    break: "#94a3b8",
  };

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function dash(v) {
    return v == null || v === "" ? "—" : String(v);
  }

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function fmtPace(secPerKm) {
    if (!secPerKm || !isFinite(secPerKm)) return "—";
    return Math.floor(secPerKm / 60) + ":" + pad(Math.round(secPerKm % 60));
  }

  function fmtDuration(sec) {
    if (sec == null || !isFinite(sec)) return "—";
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(s);
    return m + ":" + pad(s);
  }

  function fmtDateShort(iso) {
    if (!iso) return "—";
    var d = new Date(iso + (iso.length === 10 ? "T12:00:00" : ""));
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }

  function fmtTime(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  function median(nums) {
    var a = nums.filter(function (v) {
      return v != null && isFinite(v);
    });
    if (!a.length) return null;
    a.sort(function (x, y) {
      return x - y;
    });
    var mid = Math.floor(a.length / 2);
    return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }

  function percentile(nums, p) {
    var a = nums.filter(function (v) { return v != null && isFinite(v); });
    if (!a.length) return null;
    a.sort(function (x, y) { return x - y; });
    var i = (p / 100) * (a.length - 1);
    var lo = Math.floor(i), hi = Math.ceil(i);
    if (lo === hi) return a[lo];
    return a[lo] + (i - lo) * (a[hi] - a[lo]);
  }

  function decodePolyline(encoded) {
    if (!encoded) return [];
    var coords = [];
    var index = 0;
    var lat = 0;
    var lng = 0;
    while (index < encoded.length) {
      var b;
      var shift = 0;
      var result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      lat += result & 1 ? ~(result >> 1) : result >> 1;
      shift = 0;
      result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      lng += result & 1 ? ~(result >> 1) : result >> 1;
      coords.push([lat / 1e5, lng / 1e5]);
    }
    return coords;
  }

  function polylineToSvgPath(coords, w, h, padPx) {
    if (!coords.length) return "";
    var lats = coords.map(function (c) {
      return c[0];
    });
    var lngs = coords.map(function (c) {
      return c[1];
    });
    var minLat = Math.min.apply(null, lats);
    var maxLat = Math.max.apply(null, lats);
    var minLng = Math.min.apply(null, lngs);
    var maxLng = Math.max.apply(null, lngs);
    var latR = maxLat - minLat || 0.001;
    var lngR = maxLng - minLng || 0.001;
    var innerW = w - padPx * 2;
    var innerH = h - padPx * 2;
    var scale = Math.min(innerW / lngR, innerH / latR);
    var parts = coords.map(function (c, i) {
      var x = padPx + (c[1] - minLng) * scale;
      var y = padPx + (maxLat - c[0]) * scale;
      return (i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
    });
    return parts.join(" ");
  }

  function bandColor(band) {
    return BAND_COLORS[band] || BAND_COLORS.steady;
  }

  function labelBand(label) {
    var l = (label || "").toLowerCase();
    if (l.indexOf("warm") >= 0 || l.indexOf("cool") >= 0) return "steady";
    if (l.indexOf("tempo") >= 0) return "tempo";
    if (l.indexOf("threshold") >= 0) return "threshold";
    return "steady";
  }

  // Named-phase palette for the session-profile bars + zone brackets.
  // (warm-up/cool-down share the "easy" band but get distinct colors here.)
  var PHASE_NAME2 = { warmup: "Warm-up", steady: "Steady", tempo: "Tempo", threshold: "Threshold", cooldown: "Cool-down" };
  var PHASE_COLOR2 = { warmup: "#3b82f6", steady: "#22c55e", tempo: "#f59e0b", threshold: "#f97316", cooldown: "#a78bfa" };

  function phaseKey2(label, band) {
    var s = (label || "").toLowerCase().replace(/[^a-z]/g, "");
    if (s.indexOf("warm") === 0) return "warmup";
    if (s.indexOf("cool") === 0) return "cooldown";
    if (s.indexOf("tempo") === 0) return "tempo";
    if (s.indexOf("threshold") === 0) return "threshold";
    if (s.indexOf("steady") === 0 || s.indexOf("easy") === 0) return "steady";
    var b = (band || "").toLowerCase();
    if (b === "tempo") return "tempo";
    if (b === "hard" || b === "race" || b === "threshold") return "threshold";
    return "steady";
  }

  function fmtPaceSec2(sec) {
    if (sec == null) return "—";
    var mm = Math.floor(sec / 60), ss = Math.round(sec % 60);
    return mm + ":" + (ss < 10 ? "0" : "") + ss;
  }
  function gridSpans2(n) { var s = ""; for (var i = 0; i < n; i++) s += "<span></span>"; return s; }

  // Physiological intensity ranking — drives surge (up) vs dip (down) for
  // deviations in the variable/race regime; never hardcoded per session.
  var KEY_RANK2 = { cooldown: 0, warmup: 1, recovery: 0, easy: 1, steady: 2, tempo: 3, threshold: 4, hard: 5, race: 6 };
  function keyRank2(k) { var r = KEY_RANK2[k]; return r == null ? 2 : r; }
  function avg2(arr) {
    var v = arr.filter(function (x) { return x != null && !isNaN(x); });
    return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
  }
  function lapRange2(from1, to1) { return from1 === to1 ? "" + from1 : from1 + "–" + to1; }

  function normalizeStravaLap(lap, index) {
    var distM = lap.distance;
    var cad = lap.average_cadence;
    var cadSpm =
      cad != null ? (cad < 100 ? Math.round(cad * 2) : Math.round(cad)) : null;
    return {
      split_index: lap.lap_index != null ? lap.lap_index : index + 1,
      distance_km: distM != null ? distM / 1000 : null,
      duration_seconds:
        lap.moving_time != null ? lap.moving_time : lap.elapsed_time,
      avg_hr:
        lap.average_heartrate != null
          ? Math.round(lap.average_heartrate)
          : null,
      avg_power:
        lap.average_watts != null ? Math.round(lap.average_watts) : null,
      cadence_spm: cadSpm,
      stride_length_m: null,
      lap_type: "manual",
      _lapSource: "strava",
    };
  }

  function normalizeStrydLap(lap, index) {
    var distKm =
      lap.distance_km != null
        ? +lap.distance_km
        : lap.distance != null
          ? lap.distance / 1000
          : null;
    var dur =
      lap.duration_seconds ||
      lap.moving_time ||
      lap.elapsed_time ||
      lap.duration ||
      null;
    return {
      split_index:
        lap.index != null
          ? lap.index
          : lap.lap_index != null
            ? lap.lap_index
            : index + 1,
      distance_km: distKm,
      duration_seconds: dur,
      avg_hr:
        lap.avg_hr != null
          ? lap.avg_hr
          : lap.average_heart_rate != null
            ? Math.round(lap.average_heart_rate)
            : null,
      avg_power:
        lap.avg_power != null
          ? lap.avg_power
          : lap.average_power != null
            ? Math.round(lap.average_power)
            : lap.avg_power_w != null
              ? Math.round(lap.avg_power_w)
              : null,
      cadence_spm:
        lap.cadence_spm != null
          ? lap.cadence_spm
          : lap.average_cadence != null
            ? Math.round(lap.average_cadence)
            : null,
      stride_length_m:
        lap.stride_length_m != null ? +lap.stride_length_m : null,
      lap_type: "manual",
      _lapSource: "stryd",
    };
  }

  /** Manual/device laps: Stryd raw_payload.laps first, else Strava detail laps. */
  function collectManualLapSplits(strava, stryd) {
    var strydLaps =
      stryd && Array.isArray(stryd.laps) && stryd.laps.length ? stryd.laps : [];
    var stravaLaps =
      strava && Array.isArray(strava.laps) && strava.laps.length
        ? strava.laps
        : [];
    if (strydLaps.length) {
      return strydLaps
        .map(normalizeStrydLap)
        .sort(function (a, b) {
          return a.split_index - b.split_index;
        });
    }
    if (stravaLaps.length) {
      return stravaLaps
        .map(normalizeStravaLap)
        .sort(function (a, b) {
          return a.split_index - b.split_index;
        });
    }
    return [];
  }

  function buildTssOptions(full, w, strava, stryd) {
    var computedTss = full.computed_tss;
    var tssMethod = full.tss_method || w.tss_method || "computed";
    var options = [];
    if (computedTss != null) {
      options.push({
        id: "computed",
        label: "Computed",
        sublabel: tssMethod,
        value: Math.round(computedTss),
        isEffort: false,
      });
    }
    if (stryd && stryd.tss != null) {
      options.push({
        id: "stryd",
        label: "Stryd",
        sublabel: "stress",
        value: Math.round(stryd.tss),
        isEffort: false,
      });
    }
    if (strava && strava.suffer_score != null) {
      options.push({
        id: "strava",
        label: "Strava",
        sublabel: "relative effort",
        value: Math.round(strava.suffer_score),
        isEffort: true,
      });
    }
    if (w.tss_source === "manual" && w.tss != null) {
      options.push({
        id: "manual",
        label: "Manual",
        sublabel: "user entry",
        value: Math.round(w.tss),
        isEffort: false,
      });
    }
    return options;
  }

  function pickDefaultTssId(options) {
    for (var i = 0; i < options.length; i++) {
      if (options[i].id === "computed") return "computed";
    }
    return options.length ? options[0].id : null;
  }

  function tssOptionById(options, id) {
    for (var i = 0; i < options.length; i++) {
      if (options[i].id === id) return options[i];
    }
    return options[0] || null;
  }

  function renderTssTile(options, activeId) {
    var active = tssOptionById(options, activeId);
    if (!active) {
      return statTile("TSS", "—", "", { hero: true });
    }
    var lbl =
      active.isEffort
        ? "Relative effort · " + active.id
        : active.id === "computed"
          ? "TSS · " + (active.sublabel || "computed")
          : "TSS · " + active.id;
    var menu = options
      .map(function (o) {
        var cls =
          "rd4-tss-opt" + (o.id === activeId ? " rd4-tss-opt--on" : "");
        var line =
          o.isEffort
            ? o.label + " · " + o.sublabel
            : o.label + (o.sublabel ? " · " + o.sublabel : "");
        return (
          '<button type="button" class="' +
          cls +
          '" data-tss-source="' +
          esc(o.id) +
          '"><span class="rd4-tss-opt-lbl">' +
          esc(line) +
          '</span><span class="rd4-tss-opt-val">' +
          o.value +
          "</span></button>"
        );
      })
      .join("");
    return (
      '<div class="rd4-stat rd4-stat--hero rd4-stat--tss" id="rd4-tss-tile">' +
      '<div class="rd4-stat-lbl">' +
      esc(lbl) +
      ' <span class="rd4-tss-chev" aria-hidden="true">▾</span></div>' +
      '<div class="rd4-stat-val" id="rd4-tss-val">' +
      active.value +
      "</div>" +
      '<div class="rd4-tss-menu" id="rd4-tss-menu" hidden>' +
      menu +
      "</div></div>"
    );
  }

  function buildTssFootnote(options, activeId) {
    var active = tssOptionById(options, activeId);
    if (!active || active.id !== "computed") return "";
    var stryd = null;
    for (var i = 0; i < options.length; i++) {
      if (options[i].id === "stryd") stryd = options[i];
    }
    if (!stryd || stryd.value === active.value) return "";
    return (
      '<div class="rd4-tss-note">Stryd reports <strong>' +
      stryd.value +
      "</strong>; " +
      esc(active.sublabel || "computed") +
      " method computes <strong>" +
      active.value +
      "</strong></div>"
    );
  }

  function renderLapTableRows(lapMeta) {
    // Are there multiple true sets? Governs "Set N" vs "S1·R3" wording.
    var maxSet = 0;
    lapMeta.forEach(function (m) { if (m.set && m.set > maxSet) maxSet = m.set; });
    var multiSet = maxSet > 1;

    return lapMeta
      .map(function (m) {
        var s = m.split;
        var rowCls = "rd4-lap-row";
        if (m.zone2) rowCls += " rd4-lap-row--z2";
        if (m.anomaly) rowCls += " rd4-lap-row--break";
        // Pair tint: alternate the background per work+rest pair so each
        // numbered pair reads as one unit. Recovery rows also carry the linked
        // class so a shared left accent brackets the pair.
        var isWork = m.role === "work";
        var isRec = m.role === "recovery";
        if (isWork || isRec) {
          rowCls += " rd4-lap-row--pair";
          if (m.rep && m.rep % 2 === 0) rowCls += " rd4-lap-row--pair-alt";
          if (isWork) rowCls += " rd4-lap-row--work";
          if (isRec) rowCls += " rd4-lap-row--rest";
        }

        // The "break" pill is redundant now that paired recovery laps show
        // "↳ rest"; the gray row tint (.rd4-lap-row--break) still dims rest laps.
        // Set/rep badge in the LAP column.
        var badge = "";
        if (isWork) {
          var lbl = multiSet ? ("S" + m.set + "·R" + m.rep) : ("Set " + m.rep);
          badge = '<span class="rd4-set-badge" title="interval rep ' + m.rep + '">' + esc(lbl) + "</span>";
        } else if (isRec) {
          badge = '<span class="rd4-rest-badge" title="rest after rep ' + m.rep + '">&#8627; rest</span>';
        }

        var paceCls = m.fastest ? " rd4-fastest" : "";
        return (
          "<tr class=\"" +
          rowCls +
          '">' +
          '<td class="rd4-lap-idcell">' +
          "<span class=\"rd4-lap-num\">" + m.index + "</span>" +
          badge +
          "</td>" +
          "<td>" +
          (s.distance_km != null ? parseFloat(s.distance_km).toFixed(2) : "—") +
          "</td>" +
          '<td class="' +
          paceCls +
          '">' +
          fmtPace(m.paceSec) +
          "</td>" +
          "<td>" +
          dash(s.avg_hr) +
          "</td>" +
          "<td>" +
          dash(s.avg_power) +
          "</td>" +
          "<td>" +
          dash(s.cadence_spm) +
          "</td>" +
          "<td>" +
          (s.stride_length_m != null ? (+s.stride_length_m).toFixed(2) : "—") +
          "</td></tr>"
        );
      })
      .join("");
  }

  function buildLapMeta(splits, z2min, z2max, lapRoles) {
    var powers = splits.map(function (s) {
      return s.avg_power != null ? +s.avg_power : null;
    });
    var cadences = splits.map(function (s) {
      return s.cadence_spm != null ? +s.cadence_spm : null;
    });
    var medP = median(powers);
    var medC = median(cadences);
    var q3P = percentile(powers, 75);
    var q3C = percentile(cadences, 75);
    var paceSecs = splits.map(function (s) {
      var d = parseFloat(s.distance_km);
      return d && s.duration_seconds ? s.duration_seconds / d : null;
    });
    var minPace = paceSecs.filter(function (v) {
      return v != null;
    });
    minPace = minPace.length ? Math.min.apply(null, minPace) : null;

    var roles = lapRoles || null;
    return splits.map(function (s, i) {
      var d = parseFloat(s.distance_km);
      var paceSec = d && s.duration_seconds ? s.duration_seconds / d : null;
      var pwr = s.avg_power != null ? +s.avg_power : null;
      var cad = s.cadence_spm != null ? +s.cadence_spm : null;
      var stride = s.stride_length_m != null ? +s.stride_length_m : null;
      // Primary: both clearly below median (handles obvious rest laps).
      // Secondary OR: catches borderline rest laps in bimodal interval workouts
      // where the median falls between the two power clusters.
      var anomaly =
        (medP != null && pwr != null && pwr < medP * 0.78 &&
         medC != null && cad != null && cad < medC * 0.88) ||
        (q3P != null && pwr != null && pwr < q3P * 0.65 &&
         q3C != null && cad != null && cad < q3C * 0.86);
      // Backend interval role for this lap (0-based index), when confident.
      var role = roles ? roles[String(i)] : null;
      return {
        split: s,
        index: s.split_index != null ? s.split_index : i + 1,
        paceSec: paceSec,
        zone2:
          s.avg_hr != null && s.avg_hr >= z2min && s.avg_hr <= z2max,
        anomaly: anomaly,
        fastest: minPace != null && paceSec != null && paceSec <= minPace + 0.5,
        power: pwr,
        cadence: cad,
        stride: stride,
        // set/rep pairing from the backend (source of truth for numbering).
        role: role ? role.role : null,
        set: role ? role.set : null,
        rep: role ? role.rep : null,
      };
    });
  }

  function extractIntervalSet(lapMeta) {
    if (lapMeta.length < 3) return null;
    var firstRest = -1, lastRest = -1;
    for (var i = 0; i < lapMeta.length; i++) {
      if (lapMeta[i].anomaly) {
        if (firstRest === -1) firstRest = i;
        lastRest = i;
      }
    }
    if (firstRest === -1 || lastRest === firstRest) return null;
    // Include the non-anomaly lap immediately before firstRest if it exists
    // (the first fast interval precedes the first rest lap).
    var startIdx = (firstRest > 0 && !lapMeta[firstRest - 1].anomaly) ? firstRest - 1 : firstRest;
    var workLaps = [];
    for (var j = startIdx; j <= lastRest; j++) {
      if (!lapMeta[j].anomaly) workLaps.push(lapMeta[j]);
    }
    if (workLaps.length < 2) return null;
    return workLaps;
  }

  function renderIntervalBlock(workLaps, repsPerSet) {
    if (!workLaps || !workLaps.length) return "";
    function avg(arr) {
      var vals = arr.filter(function (v) { return v != null && isFinite(v); });
      return vals.length ? vals.reduce(function (a, b) { return a + b; }, 0) / vals.length : null;
    }
    var avgDist = avg(workLaps.map(function (m) { return m.split.distance_km ? +m.split.distance_km : null; }));
    var avgDur = avg(workLaps.map(function (m) { return m.split.duration_seconds ? +m.split.duration_seconds : null; }));
    var avgPwr = avg(workLaps.map(function (m) { return m.power; }));
    var avgHR = avg(workLaps.map(function (m) { return m.split.avg_hr ? +m.split.avg_hr : null; }));
    var avgPace = avg(workLaps.map(function (m) { return m.paceSec; }));

    // Numbering: rep count is the work-lap count. When the backend detected
    // multiple sets, break it down (e.g. "Set 1: 4 reps · Set 2: 4 reps").
    var multiSet = Array.isArray(repsPerSet) && repsPerSet.length > 1;
    var summaryParts = [workLaps.length + " reps"];
    if (multiSet) {
      summaryParts.push(repsPerSet.map(function (n, i) { return "Set " + (i + 1) + ": " + n + " reps"; }).join(" · "));
    }
    if (avgDist != null) summaryParts.push("avg " + (avgDist * 1000).toFixed(0) + " m");
    if (avgDur != null) {
      var m = Math.floor(avgDur / 60), s = Math.round(avgDur % 60);
      summaryParts.push(m + ":" + (s < 10 ? "0" : "") + s);
    }
    if (avgPwr != null) summaryParts.push(Math.round(avgPwr) + " W avg");

    var rows = workLaps.map(function (m, ri) {
      var d = m.split.distance_km ? (+(m.split.distance_km) * 1000).toFixed(0) + " m" : "—";
      var dur = m.split.duration_seconds
        ? (function () { var mn = Math.floor(m.split.duration_seconds / 60), sc = m.split.duration_seconds % 60; return mn + ":" + (sc < 10 ? "0" : "") + sc; })()
        : "—";
      var pace = m.paceSec ? (function () { var mn = Math.floor(m.paceSec / 60), sc = Math.round(m.paceSec % 60); return mn + ":" + (sc < 10 ? "0" : "") + sc; })() : "—";
      var pwr = m.power != null ? Math.round(m.power) + " W" : "—";
      var hr = m.split.avg_hr != null ? m.split.avg_hr + " bpm" : "—";
      // Prefer the backend rep number; fall back to positional index.
      var repNum = (m.rep != null) ? m.rep : (ri + 1);
      var repLbl = (multiSet && m.set != null) ? ("S" + m.set + "·R" + repNum) : ("Set " + repNum);
      return "<tr><td>" + esc(repLbl) + "</td><td>" + d + "</td><td>" + dur + "</td><td>" + pace + "</td><td>" + pwr + "</td><td>" + hr + "</td></tr>";
    });

    var avgRow = "<tr class=\"rd4-int-avg-row\"><td>avg</td>"
      + "<td>" + (avgDist != null ? (avgDist * 1000).toFixed(0) + " m" : "—") + "</td>"
      + "<td>" + (avgDur != null ? (function () { var mn = Math.floor(avgDur / 60), sc = Math.round(avgDur % 60); return mn + ":" + (sc < 10 ? "0" : "") + sc; })() : "—") + "</td>"
      + "<td>" + (avgPace != null ? (function () { var mn = Math.floor(avgPace / 60), sc = Math.round(avgPace % 60); return mn + ":" + (sc < 10 ? "0" : "") + sc; })() : "—") + "</td>"
      + "<td>" + (avgPwr != null ? Math.round(avgPwr) + " W" : "—") + "</td>"
      + "<td>" + (avgHR != null ? Math.round(avgHR) + " bpm" : "—") + "</td></tr>";

    return '<section class="rd4-card rd4-int-card">'
      + '<h2 class="rd4-sec-title">Interval Set</h2>'
      + '<p class="rd4-int-summary">' + esc(summaryParts.join(" · ")) + '</p>'
      + '<div class="rd4-lap-scroll"><table class="rd4-lap-table rd4-int-table"><thead><tr>'
      + '<th>Rep</th><th>Dist</th><th>Time</th><th>Pace</th><th>Pwr</th><th>HR</th>'
      + '</tr></thead><tbody>'
      + rows.join("") + avgRow
      + '</tbody></table></div></section>';
  }

  function lapBandMap(detected, lapCount) {
    var map = {};
    if (!detected || !detected.confident || !detected.phases) return map;
    detected.phases.forEach(function (ph) {
      var band = ph.band || labelBand(ph.label);
      (ph.lap_indexes || []).forEach(function (idx) {
        map[idx + 1] = band;
      });
    });
    return map;
  }

  function computeHalves(laps) {
    var totalDur = laps.reduce(function (a, m) {
      return a + (m.split.duration_seconds || 0);
    }, 0);
    if (!totalDur) return null;
    var half = totalDur / 2;
    var elapsed = 0;
    var h1p = [],
      h1h = [],
      h2p = [],
      h2h = [];
    laps.forEach(function (m) {
      var dur = m.split.duration_seconds || 0;
      var mid = elapsed + dur / 2;
      var p = m.power;
      var hr = m.split.avg_hr;
      if (mid <= half) {
        if (p != null) h1p.push(p);
        if (hr != null) h1h.push(hr);
      } else {
        if (p != null) h2p.push(p);
        if (hr != null) h2h.push(hr);
      }
      elapsed += dur;
    });
    if (!h1p.length || !h2p.length || !h1h.length || !h2h.length) return null;
    var avg = function (arr) {
      return arr.reduce(function (a, b) {
        return a + b;
      }, 0) / arr.length;
    };
    var p1 = avg(h1p);
    var p2 = avg(h2p);
    var hr1 = avg(h1h);
    var hr2 = avg(h2h);
    var eff1 = p1 / hr1;
    var eff2 = p2 / hr2;
    if (!eff1) return null;
    var decPct = Math.round((1 - eff2 / eff1) * 100);
    return { eff1: eff1, eff2: eff2, p1: Math.round(p1), p2: Math.round(p2), hr1: Math.round(hr1), hr2: Math.round(hr2), decPct: decPct };
  }

  function sourcePill(src) {
    if (src === "strava")
      return '<span class="rd4-pill rd4-pill--strava">STRAVA</span>';
    if (src === "stryd")
      return '<span class="rd4-pill rd4-pill--stryd">STRYD</span>';
    return "";
  }

  function statTile(label, value, unit, opts) {
    opts = opts || {};
    var cls = "rd4-stat" + (opts.hero ? " rd4-stat--hero" : "");
    return (
      '<div class="' +
      cls +
      '">' +
      '<div class="rd4-stat-lbl">' +
      esc(label) +
      (opts.pill || "") +
      "</div>" +
      '<div class="rd4-stat-val">' +
      esc(value) +
      (unit ? '<span class="rd4-stat-unit">' + esc(unit) + "</span>" : "") +
      "</div></div>"
    );
  }

  function render(full, prefs, syncMeta) {
    syncMeta = syncMeta || {};
    var w = full.workout || {};
    var unified = full.unified || {};
    var strava = (full.sources && full.sources.strava) || null;
    var stryd = (full.sources && full.sources.stryd) || null;
    var detected = full.detected_profile || {};
    var computed = full.computed || {};

    var splits = (full.splits || [])
      .slice()
      .sort(function (a, b) {
        return a.split_index - b.split_index;
      });
    var manualSplits = collectManualLapSplits(strava, stryd);

    var prefsRow = prefs && prefs.row ? prefs.row : {};
    var z2min =
      prefsRow.zone2_hr_min != null
        ? prefsRow.zone2_hr_min
        : RUN_DETAIL_ZONE2_HR_MIN;
    var z2max =
      prefsRow.zone2_hr_max != null
        ? prefsRow.zone2_hr_max
        : RUN_DETAIL_ZONE2_HR_MAX;

    var srcStrava =
      (w.source || "").indexOf("strava") >= 0 || !!(full.field_coverage && full.field_coverage.strava);
    var srcStryd =
      (w.source || "").indexOf("stryd") >= 0 || !!(full.field_coverage && full.field_coverage.stryd);

    var elevation =
      w.elevation_m != null ? w.elevation_m : unified.elevation_m;
    var maxHr = w.max_hr != null ? w.max_hr : unified.max_hr;
    var elevFromStrava = w.elevation_m == null && unified.elevation_m != null;
    var maxHrFromStrava = w.max_hr == null && unified.max_hr != null;

    var paceSec =
      w.duration_seconds && w.distance_km
        ? w.duration_seconds / w.distance_km
        : null;

    var startIso =
      (stryd && stryd.start_time) ||
      (strava && strava.start_time) ||
      null;
    var startTime = fmtTime(startIso);

    var tssOptions = buildTssOptions(full, w, strava, stryd);
    var defaultTssId = pickDefaultTssId(tssOptions);

    // Backend per-lap interval roles: aligned by 0-based position with the lap
    // set the backend ran detection on (detected.lap_source: "manual" laps for
    // interval sessions, else the stored "splits").
    var lapRoles =
      detected && detected.confident && detected.lap_roles
        ? detected.lap_roles
        : null;
    var rolesForManual = lapRoles && detected.lap_source === "manual" ? lapRoles : null;
    var rolesForSplits = lapRoles && detected.lap_source !== "manual" ? lapRoles : null;
    var distanceLapMeta = buildLapMeta(splits, z2min, z2max, rolesForSplits);
    var manualLapMeta = manualSplits.length
      ? buildLapMeta(manualSplits, z2min, z2max, rolesForManual)
      : [];
    var hasDistanceLaps = distanceLapMeta.length > 0;
    var hasManualLaps = manualLapMeta.length > 0;

    var bandMap = lapBandMap(detected, distanceLapMeta.length);
    var halves = computeHalves(distanceLapMeta);

    var vi =
      computed.variability_index != null
        ? computed.variability_index
        : w.np && w.avg_power
          ? (w.np / w.avg_power).toFixed(2)
          : null;

    // ── 1 Header ──
    var srcBadges =
      (srcStrava
        ? '<span class="rd4-srcbadge rd4-srcbadge--strava">Strava</span>'
        : "") +
      (srcStryd
        ? '<span class="rd4-srcbadge rd4-srcbadge--stryd">Stryd</span>'
        : "");

    var header =
      '<section class="rd4-card rd4-header">' +
      '<div class="rd4-header-top">' +
      // Type badge + optional run-subtype tag, grouped left: [RUN] [INTERVAL].
      '<span class="rd4-typebadges">' +
      '<span class="rd4-typebadge">RUN</span>' +
      (RD4_SUBTYPE_LABELS[(w.run_subtype || "").toLowerCase()]
        ? '<span class="rd4-typebadge rd4-subtypebadge">' +
          esc(RD4_SUBTYPE_LABELS[(w.run_subtype || "").toLowerCase()]) +
          "</span>"
        : "") +
      "</span>" +
      '<div class="rd4-srcbadges">' +
      srcBadges +
      "</div></div>" +
      '<div class="rd4-title-wrap">' +
      '<h1 class="rd4-title" id="rd4-title">' +
      esc(w.name || "Run") +
      "</h1>" +
      (w.id ? '<button type="button" class="rd4-name-edit" id="rd4-name-edit" aria-label="Edit workout name" title="Edit name">&#9998;</button>' : "") +
      "</div>" +
      (w.id
        ? '<div class="rd4-idrow"><code class="rd4-id">' +
          esc(String(w.id).slice(0, 8) + "…" + String(w.id).slice(-6)) +
          '</code><button type="button" class="rd4-idcopy" id="rd4-idcopy" aria-label="Copy workout ID">' +
          "&#x2398;</button></div>"
        : "") +
      '<div class="rd4-date">' +
      esc(fmtDateShort(w.workout_date)) +
      (startTime ? " · started " + esc(startTime) : "") +
      "</div>" +
      '<div class="rd4-hero-tiles">' +
      '<div class="rd4-hero-tile"><div class="rd4-hero-val">' +
      (w.distance_km != null ? parseFloat((+w.distance_km).toFixed(2)) : "—") +
      '<span class="rd4-hero-unit">km</span></div><div class="rd4-hero-lbl">Distance</div></div>' +
      '<div class="rd4-hero-tile"><div class="rd4-hero-val">' +
      fmtPace(paceSec) +
      '<span class="rd4-hero-unit">/km</span></div><div class="rd4-hero-lbl">Avg pace</div></div>' +
      "</div>" +
      '<div class="rd4-duration">Duration <strong>' +
      fmtDuration(w.duration_seconds) +
      "</strong></div></section>";

    // ── 2 Load & intensity ──
    var loadGrid =
      renderTssTile(tssOptions, defaultTssId) +
      statTile("Zone 2", dash(w.zone2_minutes), w.zone2_minutes != null ? "min" : "") +
      statTile(
        "Elevation",
        dash(elevation),
        elevation != null ? "m" : "",
        { pill: elevFromStrava ? sourcePill("strava") : "" },
      ) +
      statTile("Avg HR", dash(w.avg_hr), w.avg_hr != null ? "bpm" : "") +
      statTile(
        "Max HR",
        dash(maxHr),
        maxHr != null ? "bpm" : "",
        { pill: maxHrFromStrava ? sourcePill("strava") : "" },
      ) +
      statTile(
        "Avg power",
        dash(w.avg_power),
        w.avg_power != null ? "W" : "",
        { pill: w.avg_power != null ? sourcePill("stryd") : "" },
      ) +
      statTile(
        "NP",
        dash(w.np),
        w.np != null ? "W" : "",
        { pill: w.np != null ? sourcePill("stryd") : "" },
      ) +
      statTile(
        "Stride",
        dash(w.avg_stride_m),
        w.avg_stride_m != null ? "m" : "",
        { pill: w.avg_stride_m != null ? sourcePill("stryd") : "" },
      ) +
      statTile(
        "Cadence",
        dash(w.avg_cadence_spm),
        w.avg_cadence_spm != null ? "spm" : "",
        { pill: w.avg_cadence_spm != null ? sourcePill("stryd") : "" },
      );

    var tssNote = buildTssFootnote(tssOptions, defaultTssId);

    var load =
      '<section class="rd4-card"><h2 class="rd4-sec-title">Load &amp; intensity</h2>' +
      '<div class="rd4-stat-grid">' +
      loadGrid +
      "</div>" +
      tssNote +
      (vi != null
        ? '<div class="rd4-foot">Variability index <strong>' + esc(String(vi)) + "</strong></div>"
        : "") +
      "</section>";

    // ── 3 Power zones ──
    var pzBlock = "";
    var pz = (stryd && stryd.power_zones) || null;
    if (pz && pz.zones && pz.zones.length && pz.seconds_in_zones) {
      var totalSec = pz.seconds_in_zones.reduce(function (a, b) {
        return a + (b || 0);
      }, 0);
      var barSegs = "";
      var rows = "";
      var zoneColors = ["#86efac", "#bef264", "#fbbf24", "#fb923c", "#ef4444"];
      pz.zones.forEach(function (z, i) {
        var sec = pz.seconds_in_zones[i] || 0;
        var pct = totalSec ? Math.round((sec / totalSec) * 100) : 0;
        var mins = Math.round(sec / 60);
        var lo = z.power_low != null ? Math.round(z.power_low) : "—";
        var hi = z.power_high != null ? Math.round(z.power_high) : "—";
        barSegs +=
          '<div class="rd4-pz-seg" style="flex:' +
          (sec || 1) +
          " 1 0;background:" +
          (zoneColors[i] || "#ccc") +
          '" title="' +
          esc(z.name || "Zone") +
          '"></div>';
        rows +=
          '<div class="rd4-pz-row"><span class="rd4-pz-dot" style="background:' +
          (zoneColors[i] || "#ccc") +
          '"></span><span class="rd4-pz-name">' +
          esc(z.name || "Zone " + (i + 1)) +
          '</span><span class="rd4-pz-range">' +
          lo +
          "–" +
          hi +
          ' W</span><span class="rd4-pz-time">' +
          mins +
          'm</span><span class="rd4-pz-pct">' +
          pct +
          "%</span></div>";
      });
      pzBlock =
        '<section class="rd4-card"><h2 class="rd4-sec-title">Time in power zones ' +
        sourcePill("stryd") +
        '</h2><div class="rd4-pz-bar">' +
        barSegs +
        '</div><div class="rd4-pz-table">' +
        rows +
        "</div>" +
        (pz.ftp
          ? '<div class="rd4-foot">FTP ' + Math.round(pz.ftp) + " W (Stryd)</div>"
          : "") +
        "</section>";
    }

    // ── 4 Session profile ──
    var profileBlock = "";
    if (distanceLapMeta.length) {
      var maxPow = Math.max.apply(null, distanceLapMeta.map(function (m) { return m.power || 0; }));
      var hasPhases = !!(detected.confident && detected.phases && detected.phases.length);
      var nLaps = distanceLapMeta.length;

      // Per-lap phase (1-based lap → {key,name}) from detected.phases' lap_indexes.
      var lapPhase2 = {};
      if (hasPhases) {
        detected.phases.forEach(function (ph) {
          var key = phaseKey2(ph.label, ph.band);
          (ph.lap_indexes || []).forEach(function (idx) {
            lapPhase2[idx + 1] = { key: key, name: PHASE_NAME2[key] };
          });
        });
      }

      // Per-lap band key (array position i → key).
      var keyOf = distanceLapMeta.map(function (m) {
        var ph = lapPhase2[m.index];
        return ph ? ph.key : phaseKey2(null, bandMap[m.index]);
      });

      // STEP 1 — smooth single-lap flickers between two same-band neighbours.
      for (var sm = 1; sm < nLaps - 1; sm++) {
        if (keyOf[sm] !== keyOf[sm - 1] && keyOf[sm - 1] === keyOf[sm + 1]) keyOf[sm] = "__dev:" + keyOf[sm];
      }
      var rawKey = keyOf.map(function (k) { return k.indexOf("__dev:") === 0 ? k.slice(6) : k; });
      var smoothKey = keyOf.map(function (k, idx) { return k.indexOf("__dev:") === 0 ? rawKey[idx - 1] : k; });

      function runsOf2(seq) {
        var r = [], cur = null;
        seq.forEach(function (k, idx) {
          if (!cur || cur.key !== k) { cur = { key: k, from: idx, to: idx }; r.push(cur); } else cur.to = idx;
        });
        return r;
      }
      function lapW(i) { var m = distanceLapMeta[i]; return (m && m.split && m.split.distance_km) || 0.01; }
      function hpxOf(m) {
        var h = m.power && maxPow ? 25 + Math.round((m.power / maxPow) * 70) : 20;
        return Math.max(5, Math.round((h / 100) * 116));  // track is 120px (see .rd4-prof2-bars)
      }

      // STEP 2 — regime detection.
      var counts = {};
      rawKey.forEach(function (k) { counts[k] = (counts[k] || 0) + 1; });
      var domKey = null, domN = 0;
      Object.keys(counts).forEach(function (k) { if (counts[k] > domN) { domN = counts[k]; domKey = k; } });
      var domShare = nLaps ? domN / nLaps : 0;
      var devRuns = runsOf2(rawKey).filter(function (r) { return r.key !== domKey; });
      var shortDev = devRuns.filter(function (r) { return r.to - r.from + 1 <= 2; });
      // A low-intensity warm-up/cool-down bookend signals a deliberately
      // structured arc (warm-up → work → cool-down) → keep the bracket view.
      // Without one, a single dominant band is a *sustained* effort (a tempo
      // race, a steady block) → the headline reads better than many brackets.
      var LOW_BOOKEND = { warmup: 1, cooldown: 1, recovery: 1, easy: 1 };
      var lowBookend = !!(LOW_BOOKEND[smoothKey[0]] || LOW_BOOKEND[smoothKey[nLaps - 1]]);
      var variable = hasPhases && (
        detected.reps_detected != null ||
        domShare >= 0.65 ||
        (domShare >= 0.5 && !lowBookend) ||
        (shortDev.length >= 2 && domShare >= 0.45)
      );

      var basis = detected.basis && detected.basis !== "none" ? esc(detected.basis) : "—";
      var confNote = detected.confident === false
        ? '<p class="rd4-muted">Flat lap profile — phase detection not confident.</p>'
        : '<p class="rd4-muted">Detected profile · basis ' + basis +
          (detected.reps_detected != null ? " · reps " + detected.reps_detected : "") + "</p>";
      var head = '<section class="rd4-card"><h2 class="rd4-sec-title">Session profile · effort</h2>';

      if (!variable) {
        // ── STRUCTURED: bars + named brackets (grouped by smoothed key) ──
        var sBars = distanceLapMeta.map(function (m, i) {
          var k = smoothKey[i];
          var col = m.anomaly ? "#94a3b8" : PHASE_COLOR2[k] || bandColor(bandMap[m.index] || "steady");
          var z2 = m.zone2 ? " rd4-prof2-bar--z2" : "", brk = m.anomaly ? " rd4-prof2-bar--break" : "";
          return '<div class="rd4-cell2" style="flex:' + lapW(i) + ' 0 0">' +
            '<div class="rd4-prof2-bar' + z2 + brk + '" style="height:' + hpxOf(m) + "px;background:" + col + '"></div></div>';
        }).join("");
        var grp = [], cg = null;
        smoothKey.forEach(function (k, i) {
          if (!cg || cg.key !== k) { cg = { key: k, from: i, to: i, w: lapW(i) }; grp.push(cg); }
          else { cg.to = i; cg.w += lapW(i); }
        });
        var brackets = grp.map(function (g) {
          var range = "lap " + lapRange2(g.from + 1, g.to + 1);
          return '<div class="rd4-cell2 rd4-bracket2" style="flex:' + g.w + ' 0 0">' +
            '<div class="rd4-bracket2-line"></div>' +
            '<div class="rd4-bracket2-name" style="color:' + (PHASE_COLOR2[g.key] || "#22c55e") + '">' + esc(PHASE_NAME2[g.key] || g.key) + "</div>" +
            '<div class="rd4-bracket2-range">' + range + "</div></div>";
        }).join("");
        profileBlock = head +
          '<div class="rd4-prof2-chart"><div class="rd4-grid2">' + gridSpans2(4) + "</div>" +
          '<div class="rd4-row2 rd4-prof2-bars">' + sBars + "</div></div>" +
          '<div class="rd4-row2 rd4-bracket2-row">' + brackets + "</div>" + confNote + "</section>";
      } else {
        // ── VARIABLE / RACE: dominant headline + deviation chips ──
        var devDir = {};
        devRuns.forEach(function (r) {
          var dir = keyRank2(r.key) > keyRank2(domKey) ? "up" : "down";
          for (var i = r.from; i <= r.to; i++) devDir[i] = dir;
        });
        var vBars = distanceLapMeta.map(function (m, i) {
          var k = rawKey[i];
          var col = m.anomaly ? "#94a3b8" : PHASE_COLOR2[k] || bandColor(bandMap[m.index] || "steady");
          var mark = devDir[i] ? '<i class="rd4-dev-mark" style="color:' + col + '">' + (devDir[i] === "up" ? "▲" : "▼") + "</i>" : "";
          return '<div class="rd4-cell2" style="flex:' + lapW(i) + ' 0 0">' + mark +
            '<div class="rd4-prof2-bar" style="height:' + hpxOf(m) + "px;background:" + col + '"></div></div>';
        }).join("");

        var domIdx = [];
        for (var d2 = 0; d2 < nLaps; d2++) if (rawKey[d2] === domKey) domIdx.push(d2);
        var domPow = avg2(domIdx.map(function (i) { return distanceLapMeta[i].power; }));
        var hlNum = "";
        if (domPow != null) hlNum = '<div class="rd4-hl-num">' + Math.round(domPow) + '<span>W avg</span></div>';
        else {
          var domPace = avg2(domIdx.map(function (i) { return distanceLapMeta[i].paceSec; }));
          if (domPace != null) hlNum = '<div class="rd4-hl-num">' + fmtPaceSec2(domPace) + '<span>/km avg</span></div>';
        }
        var headline = '<div class="rd4-headline"><span class="rd4-hl-sw" style="background:' + (PHASE_COLOR2[domKey] || "#22c55e") + '"></span>' +
          '<div class="rd4-hl-t"><div class="rd4-hl-title">Sustained ' + esc(PHASE_NAME2[domKey] || domKey) + "</div>" +
          '<div class="rd4-hl-sub">' + domN + " of " + nLaps + " laps</div></div>" + hlNum + "</div>";

        var grp2 = {};
        devRuns.forEach(function (r) {
          var dir = keyRank2(r.key) > keyRank2(domKey) ? "up" : "down", gk = r.key + "|" + dir;
          if (!grp2[gk]) grp2[gk] = { key: r.key, dir: dir, runs: [], laps: [] };
          grp2[gk].runs.push(r);
          for (var i = r.from; i <= r.to; i++) grp2[gk].laps.push(i);
        });
        var chips = Object.keys(grp2).sort(function (a, b) { return (grp2[b].dir === "up") - (grp2[a].dir === "up"); }).map(function (gk) {
          var g = grp2[gk];
          var ranges = g.runs.map(function (r) { return lapRange2(r.from + 1, r.to + 1); }).join(", ");
          var gp = avg2(g.laps.map(function (i) { return distanceLapMeta[i].power; }));
          var pw = gp != null ? Math.round(gp) + " W · " : "";
          return '<span class="rd4-chip rd4-chip-' + g.dir + '"><span class="rd4-chip-ar">' + (g.dir === "up" ? "↑" : "↓") + "</span> " +
            esc(PHASE_NAME2[g.key] || g.key) + " ×" + g.runs.length + " · " + pw + "lap " + ranges + "</span>";
        }).join("");

        profileBlock = head +
          '<div class="rd4-prof2-chart"><div class="rd4-grid2">' + gridSpans2(4) + "</div>" +
          '<div class="rd4-row2 rd4-prof2-bars">' + vBars + "</div></div>" +
          headline + (chips ? '<div class="rd4-dev-chips">' + chips + "</div>" : "") + confNote + "</section>";
      }
    }

    // ── 5 Laps ──
    var lapsBlock = "";
    var activeLapMeta = hasDistanceLaps
      ? distanceLapMeta
      : manualLapMeta;
    if (activeLapMeta.length) {
      var lapTitle =
        hasDistanceLaps && hasManualLaps
          ? "Laps"
          : hasManualLaps
            ? "Laps · manual (" + manualLapMeta.length + ")"
            : "Laps · 1 km splits (" + distanceLapMeta.length + ")";
      var lapModeToggle =
        hasDistanceLaps && hasManualLaps
          ? '<div class="rd4-lapmode-toggle" id="rd4-lapmode-toggle">' +
            '<button type="button" class="rd4-lm-btn rd4-lm-btn--on" data-lap-mode="distance">1 km</button>' +
            '<button type="button" class="rd4-lm-btn" data-lap-mode="manual">Manual</button>' +
            "</div>"
          : "";
      var showDetailCols = typeof localStorage !== "undefined" && localStorage.getItem("rd4_lap_detail_cols") === "1";
      var lapsCardClass = "rd4-card rd4-laps-card" + (showDetailCols ? "" : " rd4-hide-detail-cols");
      var colToggleHtml = '<div class="rd4-lapmode-toggle" id="rd4-col-toggle">' +
        '<button type="button" class="rd4-lm-btn' + (showDetailCols ? " rd4-lm-btn--on" : "") + '" id="rd4-col-toggle-btn">Cad · Len</button>' +
        "</div>";

      lapsBlock =
        '<section class="' + lapsCardClass + '"><div class="rd4-laps-head">' +
        '<h2 class="rd4-sec-title" id="rd4-laps-title">' +
        esc(lapTitle) +
        "</h2>" +
        '<div class="rd4-laps-controls">' +
        lapModeToggle +
        // Toggle switches only the BAR metric; HR is always drawn as the line.
        '<div class="rd4-metric-toggle" id="rd4-metric-toggle">' +
        '<button type="button" class="rd4-mt-btn rd4-mt-btn--on" data-metric="pace">Pace</button>' +
        '<button type="button" class="rd4-mt-btn" data-metric="power">Power</button>' +
        "</div>" +
        colToggleHtml +
        "</div></div>" +
        '<div class="rd4-chart2"><div class="rd4-grid2" id="rd4-lap-grid"></div>' +
        '<div class="rd4-row2 rd4-chart2-bars" id="rd4-lap-chart"></div>' +
        '<svg class="rd4-hr-svg" id="rd4-lap-hr" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg>' +
        '<div class="rd4-lap-tip" id="rd4-lap-tip" hidden></div></div>' +
        '<div class="rd4-row2 rd4-axis2" id="rd4-lap-axis"></div>' +
        '<div class="rd4-chart2-legend" id="rd4-lap-legend"></div>' +
        '<div class="rv-z2-note rd4-z2-note"><span class="rd4-z2-swatch"></span> Zone 2 laps (HR ' +
        z2min +
        "–" +
        z2max +
        ") · grey = break / anomaly</div>" +
        '<div class="rd4-lap-scroll"><table class="rd4-lap-table"><thead><tr>' +
        "<th>Lap</th><th>Dist</th><th>Pace</th><th>HR</th><th>Pwr</th><th>Cad</th><th>Len</th>" +
        '</tr></thead><tbody id="rd4-lap-tbody">' +
        renderLapTableRows(activeLapMeta) +
        "</tbody></table></div></section>";
    }

    // ── 5b Interval set ──
    var intervalsBlock = "";
    if (activeLapMeta.length) {
      // Prefer the backend's role-tagged work laps (numbered) when they apply to
      // the active lap set; fall back to the frontend anomaly heuristic.
      var activeHasRoles = activeLapMeta.some(function (m) { return m.role === "work"; });
      var repsPerSet = (detected && detected.confident) ? detected.reps_per_set : null;
      var intervalWorkLaps = activeHasRoles
        ? activeLapMeta.filter(function (m) { return m.role === "work"; })
        : extractIntervalSet(activeLapMeta);
      intervalsBlock = renderIntervalBlock(intervalWorkLaps, activeHasRoles ? repsPerSet : null);
    }

    // ── 6 Aerobic decoupling ──
    var decBlock = "";
    if (halves && halves.decPct > 0) {
      decBlock =
        '<section class="rd4-card rd4-dec"><h2 class="rd4-sec-title">Aerobic decoupling · power vs HR</h2>' +
        '<div class="rd4-dec-head"><span class="rd4-dec-pct">-' +
        halves.decPct +
        '%</span><p class="rd4-dec-copy">Efficiency dropped in the second half (HR ~' +
        halves.hr1 +
        " → " +
        halves.hr2 +
        " bpm, power " +
        halves.p1 +
        " → " +
        halves.p2 +
        " W).</p></div>" +
        '<div class="rd4-dec-tiles">' +
        '<div class="rd4-dec-tile"><div class="rd4-dec-val">' +
        halves.eff1.toFixed(2) +
        ' W/bpm</div><div class="rd4-dec-lbl">First half</div></div>' +
        '<div class="rd4-dec-tile"><div class="rd4-dec-val">' +
        halves.eff2.toFixed(2) +
        ' W/bpm</div><div class="rd4-dec-lbl">Second half</div></div>' +
        "</div></section>";
    }

    // ── 7 Efficiency snapshot ──
    var effIdx =
      w.avg_power && w.avg_hr ? (w.avg_power / w.avg_hr).toFixed(2) : null;
    var strideCad =
      w.avg_stride_m && w.avg_cadence_spm
        ? ((w.avg_stride_m * w.avg_cadence_spm) / 60).toFixed(2)
        : null;
    var effSnap =
      '<section class="rd4-card"><h2 class="rd4-sec-title">Efficiency snapshot</h2>' +
      '<div class="rd4-eff-grid">' +
      statTile("Power ÷ HR", dash(effIdx), effIdx ? "W/bpm" : "") +
      statTile(
        "Stride × cadence",
        dash(strideCad),
        strideCad ? "m/s" : "",
      ) +
      statTile("Variability index", dash(vi), "") +
      "</div>";
    var vo = stryd && stryd.vertical_oscillation_cm;
    var gct = stryd && stryd.ground_contact_time_ms;
    var lss = stryd && stryd.leg_spring_stiffness;
    var formHidden =
      srcStryd &&
      (!vo || vo === 0) &&
      (!gct || gct === 0) &&
      (!lss || lss === 0);
    if (formHidden) {
      effSnap +=
        '<p class="rd4-muted">Form dynamics (vertical oscillation, ground contact, leg-spring) came through as 0 from Stryd on this activity — hidden until populated.</p>';
    }
    effSnap += "</section>";

    // ── 7b Session signal ──
    var signalBlock = "";
    var es = w.endurance_signal;
    var ss = w.speed_signal;
    var esNote = w.endurance_signal_note;
    var ssNote = w.speed_signal_note;
    var hint = w.contributes_to;
    var hasES = es != null;
    var hasSS = ss != null;
    // "One score everywhere": the CURRENT athlete score (today's, matching the
    // Performance tab) is the shared reference number; this session's own effect
    // is the signed CONTRIBUTION (Δ). Rendered as "score · contribution", e.g.
    // "90  +0.3". Δ is "—" when the session moved the score by nothing / the
    // backend hasn't supplied it; the score is omitted only when null.
    function sigCur(current) {
      return current == null ? "" : '<span class="rd4-signal-cur">' + Math.round(current) + "</span>";
    }
    function sigDelta(delta) {
      if (delta == null) return '<span class="rd4-signal-contrib rd4-signal-contrib--flat">—</span>';
      var n = parseFloat(delta.toFixed(1));
      var cls = n > 0 ? "up" : (n < 0 ? "down" : "flat");
      var txt = (n > 0 ? "+" : "") + n;
      return '<span class="rd4-signal-contrib rd4-signal-contrib--' + cls + '" title="this session\'s contribution">' + txt + "</span>";
    }
    function sigRow(lbl, delta, current, note) {
      return (
        '<div class="rd4-signal-row">' +
        '<span class="rd4-signal-lbl">' + lbl + "</span>" +
        '<span class="rd4-signal-vwrap">' +
        '<span class="rd4-signal-val">' + sigCur(current) + " " + sigDelta(delta) + "</span>" +
        (note ? '<span class="rd4-signal-note">· ' + esc(note) + "</span>" : "") +
        "</span>" +
        "</div>"
      );
    }
    var eDelta = w.endurance_score_delta;
    var eCur = w.endurance_score_current;
    var sDelta = w.speed_score_delta;
    var sCur = w.speed_score_current;
    var signalTitle =
      '<h2 class="rd4-sec-title">Fitness signal' +
      '<span class="rd4-new-badge">NEW</span>' +
      '<span class="rd4-signal-go">View in Performance →</span></h2>' +
      '<p class="rd4-signal-sub">Current athlete score · this session’s contribution</p>';
    if (!hasES && !hasSS && !esNote && !ssNote) {
      signalBlock =
        '<section class="rd4-card rd4-signal rd4-signal--link" role="button" tabindex="0" aria-label="Open Performance tab">' +
        signalTitle +
        '<p class="rd4-signal-none">' + esc(hint || "No signal recorded for this session.") + "</p>" +
        "</section>";
    } else {
      signalBlock =
        '<section class="rd4-card rd4-signal rd4-signal--link" role="button" tabindex="0" aria-label="Open Performance tab">' +
        signalTitle +
        '<div class="rd4-signal-rows">' +
        sigRow("Endurance signal", eDelta, eCur, esNote) +
        sigRow("Speed signal", sDelta, sCur, ssNote) +
        "</div>" +
        (hint ? '<p class="rd4-signal-hint">' + esc(hint) + "</p>" : "") +
        "</section>";
    }

    // ── 8 Route ──
    var routeBlock = "";
    var poly =
      unified.gps_polyline ||
      (strava && strava.map_polyline) ||
      null;
    if (poly) {
      var coords = decodePolyline(poly);
      var pathD = polylineToSvgPath(coords, 320, 140, 12);
      routeBlock =
        '<section class="rd4-card"><h2 class="rd4-sec-title">Route</h2>' +
        '<div class="rd4-map"><svg viewBox="0 0 320 140" class="rd4-map-svg" role="img" aria-label="Run route">' +
        '<path d="' +
        pathD +
        '" fill="none" stroke="#1e3a8a" stroke-width="2.5" stroke-linecap="round"/>' +
        "</svg>" +
        '<span class="rd4-map-badge">from Strava polyline</span></div>' +
        '<p class="rd4-muted">Elevation profile requires GPS stream (not stored).</p></section>';
    } else {
      routeBlock =
        '<section class="rd4-card"><h2 class="rd4-sec-title">Route</h2>' +
        '<div class="rd4-map-placeholder">No GPS polyline for this activity.</div></section>';
    }

    // ── 9 Source & sync ──
    var syncParts = [];
    if (syncMeta.stravaLatest && syncMeta.stravaLatest.synced_at)
      syncParts.push("Strava " + syncMeta.stravaLatest.synced_at);
    if (syncMeta.strydLatest && syncMeta.strydLatest.synced_at)
      syncParts.push("Stryd " + syncMeta.strydLatest.synced_at);
    var ids = [];
    if (strava && strava.strava_activity_id)
      ids.push("Strava " + strava.strava_activity_id);
    if (stryd && stryd.stryd_activity_id)
      ids.push("Stryd " + stryd.stryd_activity_id);

    var srcBlock =
      '<section class="rd4-card rd4-src"><h2 class="rd4-sec-title">Source &amp; sync</h2>' +
      '<div class="rd4-src-row">' +
      (w.strava_activity_url
        ? '<a class="rd4-srcbtn rd4-srcbtn--strava" href="' +
          esc(w.strava_activity_url) +
          '" target="_blank" rel="noopener">View on Strava</a>'
        : "") +
      (srcStryd
        ? '<span class="rd4-srcbtn rd4-srcbtn--stryd">Stryd · TSS ' +
          dash(stryd && stryd.tss != null ? Math.round(stryd.tss) : (w.tss != null ? Math.round(w.tss) : null)) +
          "</span>"
        : "") +
      "</div>" +
      '<p class="rd4-muted">Merged from ' +
      ids.join(" · ") +
      (syncParts.length ? " · last sync " + syncParts.join(", ") : "") +
      "</p></section>";

    return {
      html:
        '<div class="rd4-stack">' +
        header +
        signalBlock +
        load +
        pzBlock +
        profileBlock +
        lapsBlock +
        intervalsBlock +
        decBlock +
        effSnap +
        routeBlock +
        srcBlock +
        "</div>",
      lapSets: {
        distance: distanceLapMeta,
        manual: manualLapMeta,
      },
      hasDistanceLaps: hasDistanceLaps,
      hasManualLaps: hasManualLaps,
      tssOptions: tssOptions,
      defaultTssId: defaultTssId,
      workout: w,
    };
  }

  function wireInteractions(container, rendered) {
    if (!container) return;
    var w = rendered.workout;
    var lapSets = rendered.lapSets || { distance: [], manual: [] };
    var lapMode =
      rendered.hasDistanceLaps
        ? "distance"
        : rendered.hasManualLaps
          ? "manual"
          : "distance";
    var metric = "pace";
    var tssSource = rendered.defaultTssId;
    var tssOptions = rendered.tssOptions || [];

    function currentLaps() {
      return lapMode === "manual" ? lapSets.manual : lapSets.distance;
    }

    function refreshLapsUi() {
      var laps = currentLaps();
      var tbody = container.querySelector("#rd4-lap-tbody");
      if (tbody) tbody.innerHTML = renderLapTableRows(laps);
      var title = container.querySelector("#rd4-laps-title");
      if (title) {
        if (lapMode === "manual") {
          title.textContent =
            "Laps · manual (" + lapSets.manual.length + ")";
        } else {
          title.textContent =
            "Laps · 1 km splits (" + lapSets.distance.length + ")";
        }
      }
      drawChart(metric);
    }

    function refreshTssUi() {
      var tile = container.querySelector("#rd4-tss-tile");
      if (!tile || !tssOptions.length) return;
      var active = tssOptionById(tssOptions, tssSource);
      if (!active) return;
      var lblEl = tile.querySelector(".rd4-stat-lbl");
      var valEl = container.querySelector("#rd4-tss-val");
      var lbl =
        active.isEffort
          ? "Relative effort · " + active.id
          : active.id === "computed"
            ? "TSS · " + (active.sublabel || "computed")
            : "TSS · " + active.id;
      if (lblEl) {
        lblEl.innerHTML =
          esc(lbl) + ' <span class="rd4-tss-chev" aria-hidden="true">▾</span>';
      }
      if (valEl) valEl.textContent = String(active.value);
      var note = container.querySelector(".rd4-tss-note");
      var noteHtml = buildTssFootnote(tssOptions, tssSource);
      if (noteHtml) {
        if (note) note.outerHTML = noteHtml;
        else {
          var grid = container.querySelector(".rd4-stat-grid");
          if (grid && grid.parentNode) {
            grid.insertAdjacentHTML("afterend", noteHtml);
          }
        }
      } else if (note) {
        note.remove();
      }
      tile.querySelectorAll(".rd4-tss-opt").forEach(function (btn) {
        btn.classList.toggle(
          "rd4-tss-opt--on",
          btn.getAttribute("data-tss-source") === tssSource,
        );
      });
    }

    function _copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).catch(function () {
          _copyTextFallback(text);
        });
      }
      _copyTextFallback(text);
      return Promise.resolve();
    }

    function _copyTextFallback(text) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.cssText = "position:absolute;left:-9999px;top:0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch (_e) { /* no-op */ }
    }

    var cp = container.querySelector("#rd4-idcopy");
    if (cp && w.id) {
      cp.addEventListener("click", function () {
        _copyText(w.id).then(function () {
          cp.classList.add("rd4-idcopy--done");
          cp.setAttribute("title", "Copied!");
          cp.innerHTML = "✓";
          setTimeout(function () {
            cp.classList.remove("rd4-idcopy--done");
            cp.setAttribute("title", "Copy workout ID");
            cp.innerHTML = "&#x2398;";
          }, 1400);
        });
      });
    }

    // Inline workout name editing
    var nameEditBtn = container.querySelector("#rd4-name-edit");
    var titleEl = container.querySelector("#rd4-title");
    if (nameEditBtn && titleEl && w.id) {
      nameEditBtn.addEventListener("click", function () {
        var orig = titleEl.textContent;
        var inp = document.createElement("input");
        inp.type = "text";
        inp.className = "rd4-title-inp";
        inp.value = orig;
        inp.maxLength = 200;
        titleEl.style.display = "none";
        nameEditBtn.style.display = "none";
        titleEl.parentNode.insertBefore(inp, titleEl.nextSibling);
        inp.focus();
        inp.select();
        var done = false;
        function commit() {
          if (done) return;
          done = true;
          var val = inp.value.trim();
          if (!val || val === orig) { restore(orig); return; }
          fetch("/api/workouts/" + w.id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ name: val }),
          }).then(function (r) {
            if (!r.ok) throw new Error("save failed");
            w.name = val;
            restore(val);
            // Update list row title
            var listRow = document.querySelector('.entry-row[data-workout-id="' + w.id + '"]');
            if (listRow) {
              var listTitle = listRow.querySelector(".entry-title");
              if (listTitle) listTitle.textContent = val;
            }
          }).catch(function () {
            restore(orig);
          });
        }
        function restore(displayName) {
          if (inp.parentNode) inp.parentNode.removeChild(inp);
          titleEl.textContent = displayName;
          titleEl.style.display = "";
          nameEditBtn.style.display = "";
        }
        inp.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); commit(); }
          if (e.key === "Escape") { done = true; restore(orig); }
        });
        inp.addEventListener("blur", function () { setTimeout(commit, 120); });
      });
    }

    // One chart: bars for the chosen metric (pace|power) on their own scale +
    // HR as a line on its own independent scale. Dotted gridlines, lap axis,
    // and a legend giving each series' real range.
    function drawChart(m) {
      var chart = container.querySelector("#rd4-lap-chart");
      if (!chart) return;
      var barMetric = m === "power" ? "power" : "pace";
      var barColor = barMetric === "power" ? "#8b5cf6" : "#2563eb";
      var laps = currentLaps();

      var vals = laps.map(function (lap) {
        return barMetric === "power" ? lap.power : (lap.paceSec || null);
      });
      var nums = vals.filter(function (v) { return v != null && v > 0; });
      var mn = nums.length ? Math.min.apply(null, nums) : 0;
      var mx = nums.length ? Math.max.apply(null, nums) : 1;
      var rng = mx - mn || 1;

      // Multiple true sets? Governs the bar set-label wording.
      var chMaxSet = 0;
      laps.forEach(function (lap) { if (lap.set && lap.set > chMaxSet) chMaxSet = lap.set; });
      var chMultiSet = chMaxSet > 1;

      // (Set numbering lives on the table's "Set N" badges; the chart keeps
      // per-bar rep numbers + paired work/recovery tinting only — no under-axis
      // set chip, which overlapped the lap-number axis.)

      // Pixel heights against the chart's measured height — no CSS %-resolution.
      var CH = chart.clientHeight || 130;
      chart.innerHTML = laps
        .map(function (lap, i) {
          var v = vals[i];
          var cls = "rd4-cbar2";
          if (lap.zone2) cls += " rd4-cbar2--z2";
          if (lap.anomaly) cls += " rd4-cbar2--break";
          // Interval-pair styling: alternate tint per work rep so the reps are
          // visually countable; a rep number floats over each work bar, and the
          // first work bar of each set also carries a "Set N" tag.
          var cellCls = "rd4-cell2";
          var repLbl = "";
          if (lap.role === "work") {
            cls += " rd4-cbar2--work";
            cellCls += " rd4-cell2--work" + (lap.rep && lap.rep % 2 === 0 ? " rd4-cell2--work-alt" : "");
            var bl = chMultiSet ? (lap.set + "·" + lap.rep) : String(lap.rep);
            repLbl = '<span class="rd4-cbar-rep" title="rep ' + lap.rep + '">' + esc(bl) + "</span>";
          } else if (lap.role === "recovery") {
            cls += " rd4-cbar2--rest";
            cellCls += " rd4-cell2--rest";
          }
          if (v == null) {
            return '<div class="' + cellCls + '" data-i="' + i + '" style="flex:1 0 0">' + repLbl + '<div class="' + cls + '" style="height:' + Math.round(0.05 * CH) + 'px;background:#e2e8f0"></div></div>';
          }
          // Pace: faster (smaller sec/km) = taller → invert. Power: more = taller.
          var norm = barMetric === "pace" ? 1 - (v - mn) / rng : (v - mn) / rng;
          var hpx = Math.max(4, Math.round((10 + norm * 86) / 100 * CH));
          return '<div class="' + cellCls + '" data-i="' + i + '" style="flex:1 0 0">' + repLbl + '<div class="' + cls + '" style="height:' + hpx + "px;background:" + barColor + '"></div></div>';
        })
        .join("");

      // Hover: frame the bar under the cursor and show its lap values in a tip.
      var tip = container.querySelector("#rd4-lap-tip");
      var chart2 = chart.parentNode;
      function hideTip() {
        if (tip) tip.hidden = true;
        var hv = chart.querySelector(".rd4-cell2--hover");
        if (hv) hv.classList.remove("rd4-cell2--hover");
      }
      chart.onmousemove = function (e) {
        var cell = e.target.closest(".rd4-cell2");
        if (!cell || !tip) { hideTip(); return; }
        var li = +cell.getAttribute("data-i");
        var lap = laps[li];
        if (!lap) { hideTip(); return; }
        var paceTxt = lap.paceSec ? fmtPaceSec2(lap.paceSec) + "/km" : "—";
        var pwrTxt = lap.power != null ? lap.power + " W" : "—";
        var hrTxt = lap.split && lap.split.avg_hr != null ? lap.split.avg_hr + " bpm" : "—";
        tip.innerHTML =
          '<span class="rd4-lap-tip-h">Lap ' + lap.index + "</span>" +
          "<span>" + paceTxt + "</span><span>" + pwrTxt + "</span><span>" + hrTxt + "</span>";
        tip.hidden = false;
        var r2 = chart2.getBoundingClientRect();
        var x = e.clientX - r2.left;
        tip.style.left = Math.max(4, Math.min(x, r2.width - tip.offsetWidth - 4)) + "px";
        var cur = chart.querySelector(".rd4-cell2--hover");
        if (cur && cur !== cell) cur.classList.remove("rd4-cell2--hover");
        cell.classList.add("rd4-cell2--hover");
      };
      chart.onmouseleave = hideTip;

      // Labeled value gridlines: exactly 5 ticks from min→max (hard cap), placed
      // with the same normalization as the bars so lines and bar-tops share one
      // scale. Labels are rounded (nearest 5s / 5W) and de-duped.
      var gridEl = container.querySelector("#rd4-lap-grid");
      if (gridEl) {
        if (!nums.length) {
          gridEl.innerHTML = gridSpans2(4);
        } else {
          var GLINES = 5;
          var gridHtml = "";
          var seenLbl = {};
          for (var gi = 0; gi < GLINES; gi++) {
            var frac = gi / (GLINES - 1);            // 0 (=min value) … 1 (=max value)
            var tv = mn + frac * rng;
            var gnorm = barMetric === "pace" ? 1 - (tv - mn) / rng : (tv - mn) / rng;
            var top = 100 - (10 + gnorm * 86);
            var rounded = Math.round(tv / 5) * 5;    // nearest 5s (pace) / 5W (power)
            var glbl = barMetric === "power" ? rounded : fmtPaceSec2(rounded);
            if (seenLbl[glbl]) continue;             // drop duplicate labels when range is tiny
            seenLbl[glbl] = 1;
            gridHtml += '<div class="rd4-gl" style="top:' + top.toFixed(1) + '%"><span class="rd4-gl-lbl">' + glbl + "</span></div>";
          }
          gridEl.innerHTML = gridHtml;
        }
      }
      var axisEl = container.querySelector("#rd4-lap-axis");
      if (axisEl) {
        axisEl.innerHTML = laps.map(function (lap) {
          return '<div class="rd4-cell2">' + lap.index + "</div>";
        }).join("");
      }

      // HR line — independent scale; null laps omit a point (no fabrication).
      var hrs = laps.map(function (lap) { return lap.split.avg_hr; });
      var hValid = hrs.filter(function (v) { return v != null && v > 0; });
      var hmin = hValid.length ? Math.min.apply(null, hValid) : 0;
      var hmax = hValid.length ? Math.max.apply(null, hValid) : 0;
      var hrng = hmax - hmin || 1;
      var n = laps.length;
      var pts = [];
      laps.forEach(function (lap, i) {
        var hv = lap.split.avg_hr;
        if (hv == null || hv <= 0) return;
        var x = ((i + 0.5) / n) * 100;
        var y = 100 - (((hv - hmin) / hrng) * 80 + 8);
        pts.push(x.toFixed(2) + "," + y.toFixed(2));
      });
      var svg = container.querySelector("#rd4-lap-hr");
      if (svg) {
        var inner = "";
        if (pts.length >= 2) {
          inner += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="#ef4444" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
        }
        // Round-cap zero-length dots: constant pixel size (non-scaling stroke),
        // so they stay round instead of stretching with the non-uniform viewBox.
        pts.forEach(function (p) {
          var xy = p.split(",");
          inner += '<path d="M' + xy[0] + " " + xy[1] + 'l0 0" stroke="#ef4444" stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
        });
        svg.innerHTML = inner;
      }

      // legend with real ranges
      var legendEl = container.querySelector("#rd4-lap-legend");
      if (legendEl) {
        var barLabel = barMetric === "power"
          ? "Power (" + (nums.length ? mn + "–" + mx : "—") + " W)"
          : "Pace (" + (nums.length ? fmtPaceSec2(mn) + "–" + fmtPaceSec2(mx) : "—") + "/km)";
        var hrLabel = "HR (" + (hValid.length ? hmin + "–" + hmax : "—") + " bpm)";
        legendEl.innerHTML =
          '<span><i class="rd4-swatch2" style="background:' + barColor + '"></i>' + barLabel + "</span>" +
          '<span><i class="rd4-hr-key2"></i>' + hrLabel + "</span>";
      }
    }

    refreshLapsUi();

    var lapModeToggle = container.querySelector("#rd4-lapmode-toggle");
    if (lapModeToggle) {
      lapModeToggle.addEventListener("click", function (e) {
        var btn = e.target.closest(".rd4-lm-btn");
        if (!btn) return;
        lapMode = btn.getAttribute("data-lap-mode");
        lapModeToggle.querySelectorAll(".rd4-lm-btn").forEach(function (b) {
          b.classList.toggle("rd4-lm-btn--on", b === btn);
        });
        refreshLapsUi();
      });
    }

    // Session-signal card → jump to the Performance tab (page listens for this).
    var sigCard = container.querySelector(".rd4-signal--link");
    if (sigCard) {
      var goPerf = function () {
        document.dispatchEvent(new CustomEvent("rd4:open-performance-signal"));
      };
      sigCard.addEventListener("click", goPerf);
      sigCard.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goPerf(); }
      });
    }

    var toggle = container.querySelector("#rd4-metric-toggle");
    if (toggle) {
      toggle.addEventListener("click", function (e) {
        var btn = e.target.closest(".rd4-mt-btn");
        if (!btn) return;
        metric = btn.getAttribute("data-metric");
        toggle.querySelectorAll(".rd4-mt-btn").forEach(function (b) {
          b.classList.remove("rd4-mt-btn--on");
        });
        btn.classList.add("rd4-mt-btn--on");
        drawChart(metric);
      });
    }

    var colToggleBtn = container.querySelector("#rd4-col-toggle-btn");
    var lapsCardEl = container.querySelector(".rd4-laps-card");
    if (colToggleBtn && lapsCardEl) {
      colToggleBtn.addEventListener("click", function () {
        var hiding = lapsCardEl.classList.toggle("rd4-hide-detail-cols");
        colToggleBtn.classList.toggle("rd4-lm-btn--on", !hiding);
        try { localStorage.setItem("rd4_lap_detail_cols", hiding ? "0" : "1"); } catch (e) {}
      });
    }

    var tssTile = container.querySelector("#rd4-tss-tile");
    var tssMenu = container.querySelector("#rd4-tss-menu");
    if (tssTile && tssMenu) {
      tssTile.addEventListener("click", function (e) {
        if (e.target.closest(".rd4-tss-opt")) return;
        var open = !tssMenu.hidden;
        tssMenu.hidden = open;
        tssTile.classList.toggle("rd4-stat--tss-open", !open);
      });
      tssMenu.addEventListener("click", function (e) {
        var btn = e.target.closest(".rd4-tss-opt");
        if (!btn) return;
        tssSource = btn.getAttribute("data-tss-source");
        tssMenu.hidden = true;
        tssTile.classList.remove("rd4-stat--tss-open");
        refreshTssUi();
      });
      document.addEventListener("click", function (e) {
        if (!tssTile.contains(e.target)) {
          tssMenu.hidden = true;
          tssTile.classList.remove("rd4-stat--tss-open");
        }
      });
    }
  }

  win.RunDetailView = {
    RUN_DETAIL_ZONE2_HR_MIN: RUN_DETAIL_ZONE2_HR_MIN,
    RUN_DETAIL_ZONE2_HR_MAX: RUN_DETAIL_ZONE2_HR_MAX,
    render: function (contentEl, full, prefs, syncMeta) {
      if (!contentEl) return;
      var out = render(full, prefs, syncMeta);
      contentEl.innerHTML = out.html;
      wireInteractions(contentEl, out);
    },
  };
})(window);
