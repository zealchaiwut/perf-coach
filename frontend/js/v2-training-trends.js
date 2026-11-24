(function () {
  "use strict";

  var RANGES = [
    { key: "4w", label: "4 wk" },
    { key: "3m", label: "3 mo" },
    { key: "6m", label: "6 mo" },
    { key: "12m", label: "12 mo" },
  ];

  var esc = window.AppCommon && window.AppCommon.escapeHtml
    ? window.AppCommon.escapeHtml
    : function (s) { return String(s == null ? "" : s); };

  var state = { range: "3m" };

  function readQuery() {
    var q = new URLSearchParams(window.location.search);
    var r = (q.get("range") || "3m").toLowerCase();
    if (RANGES.some(function (x) { return x.key === r; })) state.range = r;
  }

  function writeQuery() {
    var q = new URLSearchParams();
    if (state.range !== "3m") q.set("range", state.range);
    var url = window.location.pathname + (q.toString() ? "?" + q.toString() : "");
    window.history.replaceState({}, "", url);
  }

  function fetchJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  function fmtShortDate(iso) {
    try {
      var d = new Date(iso + "T12:00:00");
      return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    } catch (e) {
      return iso;
    }
  }

  function xIndex(dates, target) {
    if (!dates.length) return 0;
    if (target <= dates[0]) return 0;
    if (target >= dates[dates.length - 1]) return dates.length - 1;
    for (var i = 0; i < dates.length - 1; i++) {
      if (target >= dates[i] && target <= dates[i + 1]) {
        var span = dates[i + 1] - dates[i] || 1;
        return i + (target - dates[i]) / span;
      }
    }
    return dates.length - 1;
  }

  function renderFitnessCard(fit) {
    var curves = fit.curves || [];
    var cur = fit.current || {};
    var W = 1000, top = 18, bottom = 200, left = 28;
    var plotW = W - left;
    var tsbColor = (cur.tsb != null && cur.tsb >= 0) ? "#15803d" : "#0b1530";
    var tiles =
      '<div class="rv-trends-kpis">' +
      '<div><span class="rv-subtitle" style="font-size:12px">CTL · fitness</span>' +
      '<span class="rv-mono rv-trends-kpi-val">' + esc(cur.ctl != null ? cur.ctl : "—") + '</span></div>' +
      '<div><span class="rv-subtitle" style="font-size:12px">ATL · fatigue</span>' +
      '<span class="rv-mono rv-trends-kpi-val">' + esc(cur.atl != null ? cur.atl : "—") + "</span></div>" +
      '<div><span class="rv-subtitle" style="font-size:12px">TSB · freshness</span>' +
      '<span class="rv-mono rv-trends-kpi-val" style="color:' + tsbColor + '">' +
      (cur.tsb != null ? (cur.tsb > 0 ? "+" : "") + cur.tsb : "—") + "</span></div></div>";

    if (!curves.length) {
      return '<section class="rv-card rv-stack" data-trends-fitness>' +
        '<div class="rv-row" style="align-items:flex-start;flex-wrap:wrap"><div>' +
        '<span class="rv-label">Fitness and freshness</span>' +
        '<p class="rv-subtitle">' + esc(fit.subtitle || "") + "</p></div>" + tiles + "</div>" +
        '<p class="rv-subtitle">No load data in this range yet.</p></section>';
    }

    var vals = curves.map(function (c) { return Math.max(c.ctl || 0, c.atl || 0); });
    var lo = 0;
    var hi = Math.max.apply(null, vals.concat([10]));
    hi = hi * 1.08;
    var Y = function (v) { return Math.round((top + (hi - v) / (hi - lo) * (bottom - top)) * 10) / 10; };
    var n = curves.length;
    var X = function (i) { return Math.round(left + (i / Math.max(n - 1, 1)) * plotW * 10) / 10; };
    var dates = curves.map(function (c) { return new Date(c.date + "T12:00:00").getTime(); });
    var parts = [];
    parts.push('<line x1="' + left + '" y1="' + bottom + '" x2="' + W + '" y2="' + bottom + '" stroke="#e3e9f5"/>');
    var mid = lo + (hi - lo) * 0.35;
    var hiLine = lo + (hi - lo) * 0.68;
    parts.push('<line x1="' + left + '" y1="' + Y(mid) + '" x2="' + W + '" y2="' + Y(mid) + '" stroke="#eef1f7" stroke-dasharray="4 5"/>');
    parts.push('<line x1="' + left + '" y1="' + Y(hiLine) + '" x2="' + W + '" y2="' + Y(hiLine) + '" stroke="#eef1f7" stroke-dasharray="4 5"/>');

    (fit.phase_spans || []).forEach(function (sp) {
      var i0 = xIndex(dates, new Date(sp.start + "T12:00:00").getTime());
      var i1 = xIndex(dates, new Date(sp.end + "T12:00:00").getTime());
      var x0 = X(i0);
      var x1 = X(i1);
      var fill = sp.phase === "race_week" ? "#fff1f2" : "#fbffe0";
      var labelColor = sp.phase === "race_week" ? "#9f1239" : "#6b4408";
      parts.push('<rect data-phase="' + esc(sp.phase) + '" x="' + x0 + '" y="' + top + '" width="' + Math.max(x1 - x0, 2) + '" height="' + (bottom - top) + '" fill="' + fill + '"/>');
      parts.push('<text x="' + (x0 + 6) + '" y="' + (top + 14) + '" font-size="11" fill="' + labelColor + '" font-weight="700">' + esc(sp.label) + "</text>");
    });

    var atlPts = curves.map(function (c, i) { return X(i) + "," + Y(c.atl || 0); }).join(" ");
    var ctlPts = curves.map(function (c, i) { return X(i) + "," + Y(c.ctl || 0); }).join(" ");
    parts.push('<polyline points="' + atlPts + '" fill="none" stroke="#b45309" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="6 4" data-series="atl"/>');
    parts.push('<polyline points="' + ctlPts + '" fill="none" stroke="#1f3b8a" stroke-width="3.5" stroke-linejoin="round" data-series="ctl"/>');
    var last = curves[curves.length - 1];
    parts.push('<circle cx="' + X(n - 1) + '" cy="' + Y(last.ctl || 0) + '" r="5" fill="#1f3b8a"/>');
    parts.push('<text x="4" y="' + (Y(mid) + 4) + '" font-size="11" fill="#56627f" font-family="JetBrains Mono, monospace">' + esc(Math.round(mid)) + "</text>");
    parts.push('<text x="4" y="' + (Y(hiLine) + 4) + '" font-size="11" fill="#56627f" font-family="JetBrains Mono, monospace">' + esc(Math.round(hiLine)) + "</text>");
    parts.push('<text x="' + left + '" y="216" font-size="11" fill="#56627f">' + esc(fmtShortDate(curves[0].date)) + "</text>");
    parts.push('<text x="' + (left + plotW / 2) + '" y="216" font-size="11" fill="#56627f" text-anchor="middle">' +
      esc(fmtShortDate(curves[Math.floor(n / 2)].date)) + "</text>");
    parts.push('<text x="' + W + '" y="216" font-size="11" fill="#56627f" text-anchor="end">' + esc(fmtShortDate(curves[n - 1].date)) + "</text>");

    var aria = "CTL and ATL from " + curves[0].date + " to " + curves[n - 1].date;
    var svg = '<svg viewBox="0 0 ' + W + ' 220" class="rv-trends-svg" role="img" aria-label="' + esc(aria) + '" data-fitness-chart>' + parts.join("") + "</svg>";
    var keys =
      '<div class="rv-trends-keys">' +
      '<span class="rv-trends-key"><span class="rv-trends-swatch rv-trends-swatch--ctl"></span>CTL · fitness</span>' +
      '<span class="rv-trends-key"><span class="rv-trends-swatch rv-trends-swatch--atl"></span>ATL · fatigue</span>' +
      '<span class="rv-trends-key"><span class="rv-trends-swatch rv-trends-swatch--taper"></span>Taper window</span></div>';

    return '<section class="rv-card rv-stack" data-trends-fitness>' +
      '<div class="rv-row" style="align-items:flex-start;flex-wrap:wrap;gap:16px">' +
      '<div style="flex:1;min-width:200px"><span class="rv-label">Fitness and freshness</span>' +
      '<p class="rv-subtitle">' + esc(fit.subtitle || "") + "</p></div>" + tiles + "</div>" +
      svg + keys + "</section>";
  }

  function renderWeeklyLoad(wl) {
    var weeks = wl.weeks || [];
    var avg = wl.block_average || {};
    if (!weeks.length) {
      return '<section class="rv-card rv-stack" data-trends-load><span class="rv-label">Weekly load</span>' +
        '<p class="rv-subtitle">No weeks in range.</p></section>';
    }
    var W = 1000, bottom = 140, top = 12;
    var maxT = Math.max.apply(null, weeks.map(function (w) {
      return Math.max(w.tss_total || 0, w.outline_tss || 0, w.target_tss || 0, 1);
    }));
    maxT *= 1.12;
    var barW = Math.min(72, Math.floor((W - 40) / Math.max(weeks.length, 1)) - 6);
    var gap = (W - 20 - barW * weeks.length) / Math.max(weeks.length - 1, 1);
    var parts = [];
    parts.push('<line x1="0" y1="' + bottom + '" x2="' + W + '" y2="' + bottom + '" stroke="#e3e9f5"/>');
    var x = 10;
    weeks.forEach(function (w) {
      var h = (w.tss_total || 0) / maxT * (bottom - top);
      var y = bottom - h;
      var fill = w.planned_down_week ? "#9cb7ea" : "#1f3b8a";
      if (w.is_current_week) {
        parts.push('<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + Math.max(h, 2) + '" rx="4" fill="' + fill + '"/>');
        var oh = (w.outline_tss || w.target_tss || w.tss_total) / maxT * (bottom - top);
        var oy = bottom - oh;
        parts.push('<rect x="' + x + '" y="' + oy + '" width="' + barW + '" height="' + Math.max(oh, 4) + '" rx="4" fill="#ffffff" stroke="#1f3b8a" stroke-width="2" stroke-dasharray="5 4" data-current-week/>');
      } else {
        parts.push('<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + Math.max(h, 2) + '" rx="4" fill="' + fill + '"' +
          (w.planned_down_week ? ' data-down-week="1"' : "") + "/>");
      }
      if (w.tss_total > maxT * 0.55) {
        parts.push('<text x="' + (x + barW / 2) + '" y="' + (y - 4) + '" font-size="11" fill="#0b1530" text-anchor="middle" font-family="JetBrains Mono, monospace">' +
          esc(Math.round(w.tss_total)) + "</text>");
      }
      x += barW + gap;
    });
    parts.push('<text x="10" y="160" font-size="11" fill="#56627f">' + esc(fmtShortDate(weeks[0].week_start)) + "</text>");
    var last = weeks[weeks.length - 1];
    parts.push('<text x="' + (W - 10) + '" y="160" font-size="11" fill="#56627f" text-anchor="end">' +
      esc(last.is_current_week ? "this week" : fmtShortDate(last.week_start)) + "</text>");
    var svg = '<svg viewBox="0 0 ' + W + ' 170" class="rv-trends-svg" role="img" aria-label="Weekly TSS bars" data-weekly-load-chart>' + parts.join("") + "</svg>";
    var foot =
      '<div class="rv-row rv-trends-load-foot"><span class="rv-subtitle">Average across the block</span>' +
      '<span class="rv-mono" style="font-size:15px;font-weight:600">' + esc(Math.round(avg.tss_total || 0)) + " TSS · " +
      esc(avg.distance_km != null ? avg.distance_km : 0) + " km · " + esc(avg.hours != null ? avg.hours : 0) + " h</span></div>";
    return '<section class="rv-card rv-stack" data-trends-load><div><span class="rv-label">Weekly load</span>' +
      '<p class="rv-subtitle">TSS per week · lighter bars are planned down weeks</p></div>' +
      svg + foot + "</section>";
  }

  function miniSparkline(vals, stroke) {
    if (!vals || vals.length < 2) return "";
    var W = 200, H = 40;
    var min = Math.min.apply(null, vals);
    var max = Math.max.apply(null, vals);
    var span = max - min || 1;
    var pts = vals.map(function (v, i) {
      var x = Math.round(i / (vals.length - 1) * W * 10) / 10;
      var y = Math.round((H - 6) - (v - min) / span * (H - 12) * 10) / 10;
      return x + "," + y;
    }).join(" ");
    return '<svg viewBox="0 0 ' + W + " " + H + '" class="rv-trends-spark-mini" aria-hidden="true">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="2.5" stroke-linejoin="round"/></svg>';
  }

  function deltaChip(d) {
    if (!d) return "";
    var good = d.indexOf("+") === 0;
    var flat = d === "flat";
    var cls = flat ? "rv-chip" : (good ? "rv-chip rv-chip--done" : "rv-chip rv-chip--race");
    return '<span class="' + cls + '">' + esc(d) + "</span>";
  }

  function renderDecoupling(dc) {
    var pts = (dc && dc.points) || [];
    var W = 1000, bottom = 150, top = 10;
    if (!pts.length) {
      return '<section class="rv-card rv-stack" data-trends-decoupling><span class="rv-label">Decoupling per long run</span>' +
        '<p class="rv-subtitle">No qualifying long runs in this range yet.</p></section>';
    }
    var maxP = Math.max.apply(null, pts.map(function (p) { return p.decoupling_percent; }).concat([12]));
    maxP *= 1.1;
    var X = function (i) { return Math.round(20 + (i / Math.max(pts.length - 1, 1)) * (W - 40) * 10) / 10; };
    var Y = function (p) { return Math.round(top + (maxP - p) / maxP * (bottom - top) * 10) / 10; };
    var parts = ['<line x1="0" y1="' + bottom + '" x2="' + W + '" y2="' + bottom + '" stroke="#e3e9f5"/>'];
    if (dc.reference_pct != null) {
      var ry = Y(dc.reference_pct);
      parts.push('<line x1="0" y1="' + ry + '" x2="' + W + '" y2="' + ry + '" stroke="#15803d" stroke-width="1.5" stroke-dasharray="5 5"/>');
      parts.push('<text x="' + (W - 4) + '" y="' + (ry - 4) + '" font-size="11" fill="#15803d" text-anchor="end" font-weight="700">' +
        esc(dc.reference_pct) + '% · well-fuelled, well-paced</text>');
    }
    if (dc.median_last_4_pct != null) {
      var my = Y(dc.median_last_4_pct);
      parts.push('<line x1="' + (W * 0.65) + '" y1="' + my + '" x2="' + W + '" y2="' + my + '" stroke="#0b1530" stroke-width="2"/>');
      parts.push('<text x="' + (W - 4) + '" y="' + (my - 4) + '" font-size="11" fill="#0b1530" text-anchor="end" font-weight="700">median of last 4 · ' +
        esc(dc.median_last_4_pct) + '%</text>');
    }
    pts.forEach(function (p, i) {
      var hot = dc.median_last_4_pct != null && p.decoupling_percent >= 2 * dc.median_last_4_pct;
      parts.push('<circle cx="' + X(i) + '" cy="' + Y(p.decoupling_percent) + '" r="7" fill="' + (hot ? "#b45309" : "#1f3b8a") + '"/>');
    });
    var svg = '<svg viewBox="0 0 ' + W + ' 170" class="rv-trends-svg" data-decoupling-chart>' + parts.join("") + "</svg>";
    var note = dc.note ? '<p class="rv-subtitle" style="margin:0;line-height:1.5">' + esc(dc.note) + "</p>" : "";
    return '<section class="rv-card rv-stack" data-trends-decoupling><div><span class="rv-label">Decoupling per long run</span>' +
      '<p class="rv-subtitle">Lower is better · this is what the durability score reads</p></div>' + svg + note + "</section>";
  }

  function renderFormTiles(ft) {
    var tiles = (ft && ft.tiles) || [];
    if (!tiles.length) {
      return '<section class="rv-card rv-stack"><span class="rv-label">Stryd form metrics</span><p class="rv-subtitle">No easy runs with form data.</p></section>';
    }
    var cells = tiles.map(function (t) {
      var stroke = t.economy_focus ? "#b45309" : "#1f3b8a";
      var vals = (t.sparkline || []).map(function (p) { return p.value; });
      var val = t.value != null ? t.value + (t.value_suffix || "") : "—";
      return '<div class="rv-trends-form-tile' + (t.economy_focus ? " rv-trends-form-tile--economy" : "") + '">' +
        '<div class="rv-row"><span style="font-size:14px;font-weight:600">' + esc(t.label) + "</span>" + deltaChip(t.delta_28d) + "</div>" +
        '<span class="rv-mono" style="font-size:22px;font-weight:600">' + esc(val) + "</span>" +
        miniSparkline(vals, stroke) + "</div>";
    }).join("");
    return '<section class="rv-card rv-stack" data-trends-form><div class="rv-row" style="align-items:flex-start">' +
      '<div><span class="rv-label">Stryd form metrics</span><p class="rv-subtitle">Easy runs only · 28-day change</p></div></div>' +
      '<div class="rv-trends-form-grid">' + cells + "</div></section>";
  }

  function renderZoneMix(zm) {
    var months = (zm && zm.months) || [];
    if (!months.length) {
      return '<section class="rv-card rv-stack" data-trends-zones><span class="rv-label">Time in zone by month</span>' +
        '<p class="rv-subtitle">Connect Stryd for power-zone minutes.</p></section>';
    }
    var colors = ["#dbeafe", "#6d93e8", "#1f3b8a", "#b45309", "#7a1a1a"];
    var rows = months.map(function (m) {
      var segs = (m.zone_pct || []).map(function (pct, i) {
        return '<span style="width:' + esc(pct) + '%;background:' + colors[i] + '"></span>';
      }).join("");
      var total = (m.partial ? esc(m.total_hours) + " h so far" : esc(m.total_hours) + " h total");
      return '<div class="rv-trends-zone-row"><span style="font-size:14px;font-weight:600">' + esc(m.label) + '</span>' +
        '<div class="rv-trends-zone-bar">' + segs + "</div>" +
        '<span class="rv-mono rv-subtitle" style="text-align:right">' + total + "</span></div>";
    }).join("");
    var keys = colors.map(function (c, i) {
      return '<span class="rv-trends-key"><span style="width:11px;height:11px;border-radius:3px;background:' + c + '"></span>Z' + (i + 1) + "</span>";
    }).join("");
    return '<section class="rv-card rv-stack" data-trends-zones><div class="rv-row"><span class="rv-label">Time in zone by month</span>' +
      '<div class="rv-trends-keys">' + keys + '</div></div><div class="rv-stack" style="gap:12px">' + rows + '</div></section>';
  }

  function renderRangeButtons() {
    var host = document.getElementById("v2-trends-range-btns");
    if (!host) return;
    host.innerHTML = RANGES.map(function (r) {
      var on = r.key === state.range ? " is-active" : "";
      return '<button type="button" class="rv-trends-range-btn' + on + '" data-range="' + esc(r.key) + '">' + esc(r.label) + "</button>";
    }).join("");
    host.querySelectorAll("[data-range]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.range = btn.getAttribute("data-range");
        writeQuery();
        renderRangeButtons();
        load();
      });
    });
  }

  function render(host, data) {
    host.innerHTML =
      renderFitnessCard(data.fitness || {}) +
      '<div class="rv-trends-mid">' + renderWeeklyLoad(data.weekly_load || {}) + renderDecoupling(data.decoupling || {}) + "</div>" +
      renderFormTiles(data.form_tiles || {}) +
      renderZoneMix(data.zone_mix || {});
  }

  function load() {
    var host = document.getElementById("v2-trends-host");
    if (!host) return;
    host.innerHTML = '<p class="rv-section-state" role="status">Loading…</p>';
    fetchJSON("/api/training/trends/revamp?range=" + encodeURIComponent(state.range))
      .then(function (data) { render(host, data); })
      .catch(function () {
        host.innerHTML = '<p class="rv-section-state" role="alert">Could not load trends.</p>';
      });
  }

  readQuery();
  renderRangeButtons();
  load();
})();