/* Run detail view v4 — Training > Log side panel (read-only runs).
   Data: GET /api/workouts/{id}/full?streams=none
   Exposed as window.RunDetailView */
(function (win) {
  "use strict";

  var TF = win.TrainingFormat || {};

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
    return lapMeta
      .map(function (m) {
        var s = m.split;
        var rowCls = "rd4-lap-row";
        if (m.zone2) rowCls += " rd4-lap-row--z2";
        if (m.anomaly) rowCls += " rd4-lap-row--break";
        var pills = "";
        if (m.zone2) pills += '<span class="rd4-z2-pill">Z2</span>';
        if (m.anomaly) pills += '<span class="rd4-break-pill">break</span>';
        if (s._lapSource)
          pills +=
            '<span class="rd4-lap-src rd4-lap-src--' +
            s._lapSource +
            '">' +
            s._lapSource.toUpperCase() +
            "</span>";
        var paceCls = m.fastest ? " rd4-fastest" : "";
        return (
          "<tr class=\"" +
          rowCls +
          '">' +
          "<td>" +
          m.index +
          pills +
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

  function buildLapMeta(splits, z2min, z2max) {
    var powers = splits.map(function (s) {
      return s.avg_power != null ? +s.avg_power : null;
    });
    var cadences = splits.map(function (s) {
      return s.cadence_spm != null ? +s.cadence_spm : null;
    });
    var medP = median(powers);
    var medC = median(cadences);
    var paceSecs = splits.map(function (s) {
      var d = parseFloat(s.distance_km);
      return d && s.duration_seconds ? s.duration_seconds / d : null;
    });
    var minPace = paceSecs.filter(function (v) {
      return v != null;
    });
    minPace = minPace.length ? Math.min.apply(null, minPace) : null;

    return splits.map(function (s, i) {
      var d = parseFloat(s.distance_km);
      var paceSec = d && s.duration_seconds ? s.duration_seconds / d : null;
      var pwr = s.avg_power != null ? +s.avg_power : null;
      var cad = s.cadence_spm != null ? +s.cadence_spm : null;
      var stride = s.stride_length_m != null ? +s.stride_length_m : null;
      var anomaly =
        medP != null &&
        pwr != null &&
        pwr < medP * 0.78 &&
        medC != null &&
        cad != null &&
        cad < medC * 0.88;
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
      };
    });
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

    var distanceLapMeta = buildLapMeta(splits, z2min, z2max);
    var manualLapMeta = manualSplits.length
      ? buildLapMeta(manualSplits, z2min, z2max)
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
      '<span class="rd4-typebadge">RUN</span>' +
      '<div class="rd4-srcbadges">' +
      srcBadges +
      "</div></div>" +
      "<h1 class=\"rd4-title\">" +
      esc(w.name || "Run") +
      "</h1>" +
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
      var maxPow = Math.max.apply(
        null,
        distanceLapMeta.map(function (m) {
          return m.power || 0;
        }),
      );
      var bars = distanceLapMeta
        .map(function (m) {
          var band = m.anomaly
            ? "break"
            : bandMap[m.index] ||
              (detected.confident ? "steady" : "steady");
          var h = m.power && maxPow ? 25 + Math.round((m.power / maxPow) * 70) : 20;
          var col = bandColor(band);
          var z2ring = m.zone2 ? " rd4-prof-bar--z2" : "";
          var brk = m.anomaly ? " rd4-prof-bar--break" : "";
          return (
            '<div class="rd4-prof-bar' +
            z2ring +
            brk +
            '" style="height:' +
            h +
            "%;background:" +
            col +
            '"></div>'
          );
        })
        .join("");

      var phaseStrip = "";
      if (detected.confident && detected.phases && detected.phases.length) {
        phaseStrip = detected.phases
          .map(function (ph) {
            var col = bandColor(ph.band || labelBand(ph.label));
            return (
              '<span class="rd4-phase-chip" style="border-color:' +
              col +
              '">' +
              esc(ph.label || ph.band || "Phase") +
              "</span>"
            );
          })
          .join("");
      }

      var confNote =
        detected.confident === false
          ? '<p class="rd4-muted">Flat lap profile — phase detection not confident.</p>'
          : '<p class="rd4-muted">Detected profile · basis ' +
            esc(detected.basis || "power") +
            (detected.reps_detected != null
              ? " · reps " + detected.reps_detected
              : "") +
            "</p>";

      profileBlock =
        '<section class="rd4-card"><h2 class="rd4-sec-title">Session profile · effort</h2>' +
        '<div class="rd4-prof-track">' +
        bars +
        "</div>" +
        (phaseStrip ? '<div class="rd4-phase-strip">' + phaseStrip + "</div>" : "") +
        confNote +
        "</section>";
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

      lapsBlock =
        '<section class="rd4-card rd4-laps-card"><div class="rd4-laps-head">' +
        '<h2 class="rd4-sec-title" id="rd4-laps-title">' +
        esc(lapTitle) +
        "</h2>" +
        '<div class="rd4-laps-controls">' +
        lapModeToggle +
        '<div class="rd4-metric-toggle" id="rd4-metric-toggle">' +
        '<button type="button" class="rd4-mt-btn rd4-mt-btn--on" data-metric="power">Power</button>' +
        '<button type="button" class="rd4-mt-btn" data-metric="pace">Pace</button>' +
        '<button type="button" class="rd4-mt-btn" data-metric="hr">HR</button>' +
        "</div></div></div>" +
        '<div class="rd4-lap-chart" id="rd4-lap-chart"></div>' +
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

    // ── 6 Aerobic decoupling ──
    var decBlock = "";
    if (halves && halves.decPct > 0) {
      decBlock =
        '<section class="rd4-card rd4-dec"><h2 class="rd4-sec-title">Aerobic decoupling · power vs HR</h2>' +
        '<div class="rd4-dec-head"><span class="rd4-dec-pct">+' +
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
          dash(stryd && stryd.tss != null ? Math.round(stryd.tss) : storedTss) +
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
        load +
        pzBlock +
        profileBlock +
        lapsBlock +
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
    var metric = "power";
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

    var cp = container.querySelector("#rd4-idcopy");
    if (cp && w.id) {
      cp.addEventListener("click", function () {
        var t = w.id;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(t).catch(function () {});
        }
        cp.classList.add("rd4-idcopy--done");
        setTimeout(function () {
          cp.classList.remove("rd4-idcopy--done");
        }, 1200);
      });
    }

    function drawChart(m) {
      var chart = container.querySelector("#rd4-lap-chart");
      if (!chart) return;
      var laps = currentLaps();
      var vals = laps.map(function (lap) {
        if (m === "hr") return lap.split.avg_hr;
        if (m === "power") return lap.power;
        return lap.paceSec ? -lap.paceSec : null;
      });
      var nums = vals.filter(function (v) {
        return v != null;
      });
      var mn = nums.length ? Math.min.apply(null, nums) : 0;
      var mx = nums.length ? Math.max.apply(null, nums) : 1;
      chart.innerHTML = laps
        .map(function (lap, i) {
          var v = vals[i];
          var h =
            v == null || mx === mn
              ? 22
              : 18 + Math.round(((v - mn) / (mx - mn)) * 72);
          var cls = "rd4-lapbar";
          if (lap.zone2) cls += " rd4-lapbar--z2";
          if (lap.anomaly) cls += " rd4-lapbar--break";
          return (
            '<div class="' +
            cls +
            '" style="height:' +
            h +
            '%" title="Lap ' +
            lap.index +
            '"></div>'
          );
        })
        .join("");
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
