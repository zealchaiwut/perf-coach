/* Weight timeline chart — annotated trend axis (issue: weight tab revamp). */
(function (global) {
  "use strict";

  var PAD = { left: 30, right: 20, top: 20, bottom: 34 };
  var C = {
    trend: "#4f6ef7",
    dot: "#4f6ef7",
    grid: "#f1f3f8",
    axis: "#9ca3af",
    decision: "#8b5cf6",
    sprint: "#eef1fe",
    lean: "#4f6ef7",
    fat: "#f0a878",
  };

  /** Pure domain helper — exported for tests. */
  function timelineDomain(trendValues) {
    var vals = (trendValues || []).filter(function (v) { return v != null && !isNaN(v); });
    if (!vals.length) return { lo: 80, hi: 90 };
    var minT = Math.min.apply(null, vals);
    var maxT = Math.max.apply(null, vals);
    var lo = Math.floor((minT - 0.35) * 2) / 2;
    var hi = Math.ceil((maxT + 0.35) * 2) / 2;
    if (hi <= lo) hi = lo + 0.5;
    return { lo: lo, hi: hi };
  }

  function _el(tag, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) {
      el.setAttribute(k, attrs[k]);
    });
    return el;
  }

  function _fmtShort(dateStr) {
    var d = new Date(dateStr + "T00:00:00");
    if (isNaN(d)) return dateStr;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  function _clip(val, lo, hi) {
    return Math.max(lo, Math.min(hi, val));
  }

  function render(data, opts) {
    opts = opts || {};
    var container = document.getElementById("weight-timeline");
    if (!container) return;
    container.innerHTML = "";

    var trend = (data && data.trend) || [];
    var ewma = (data && data.ewma) || [];
    var actuals = (data && data.actuals) || [];
    var composition = data && data.composition;
    var showComposition = !!opts.showComposition;
    var decisions = opts.decisions || [];
    var sprints = opts.sprints || [];

    if (!trend.length) {
      container.textContent = "Not enough data for timeline yet.";
      return;
    }

    var width = container.clientWidth || container.offsetWidth || 660;
    if (width < 280) width = 280;
    var height = 230;
    var plotW = width - PAD.left - PAD.right;
    var plotH = height - PAD.top - PAD.bottom;

    var trendVals = trend.map(function (p) { return p.weight_kg; }).filter(function (v) { return v != null; });
    var domain = timelineDomain(trendVals);
    var lo = domain.lo;
    var hi = domain.hi;
    var span = hi - lo || 0.5;

    var dates = trend.map(function (p) { return p.date; });
    var n = dates.length;

    function xAt(i) {
      return PAD.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
    }
    function xDate(d) {
      var i = dates.indexOf(d);
      return i < 0 ? null : xAt(i);
    }
    function yVal(v) {
      return PAD.top + ((hi - v) / span) * plotH;
    }

    var svg = _el("svg", {
      width: String(width),
      height: String(height),
      role: "img",
      "aria-label": "Weight timeline",
    });

    sprints.forEach(function (s) {
      if (!s.start || !s.end) return;
      var x0 = xDate(s.start);
      var x1 = xDate(s.end);
      if (x0 == null || x1 == null) return;
      var left = Math.min(x0, x1);
      var w = Math.abs(x1 - x0) || 8;
      svg.appendChild(_el("rect", {
        x: left, y: PAD.top, width: w, height: plotH,
        fill: C.sprint,
      }));
    });

    for (var kg = lo; kg <= hi + 0.001; kg += 0.5) {
      var gy = yVal(kg);
      svg.appendChild(_el("line", {
        x1: PAD.left, y1: gy, x2: width - PAD.right, y2: gy,
        stroke: C.grid, "stroke-width": "1",
      }));
      if (Math.abs(kg * 2 - Math.round(kg * 2)) < 0.01) {
        var lbl = _el("text", {
          x: "2", y: gy + 3, "font-size": "9", fill: C.axis,
          "font-family": "JetBrains Mono, ui-monospace, monospace",
        });
        lbl.textContent = kg.toFixed(1);
        svg.appendChild(lbl);
      }
    }

    if (showComposition && composition && composition.readable && composition.latest) {
      var comp = composition.latest;
      if (comp.lean_mass_kg != null && comp.fat_mass_kg != null) {
        trend.forEach(function (p, i) {
          if (p.weight_kg == null) return;
          var leanH = (comp.lean_mass_kg / p.weight_kg) * 4;
          var fatH = (comp.fat_mass_kg / p.weight_kg) * 4;
          var cx = xAt(i);
          var baseY = yVal(p.weight_kg);
          svg.appendChild(_el("rect", {
            x: cx - 2, y: baseY, width: 4, height: leanH, fill: C.lean, opacity: "0.35",
          }));
          svg.appendChild(_el("rect", {
            x: cx - 2, y: baseY + leanH, width: 4, height: fatH, fill: C.fat, opacity: "0.35",
          }));
        });
      }
    }

    actuals.forEach(function (p) {
      if (p.weight_kg == null) return;
      var px = xDate(p.date);
      if (px == null) return;
      var clipped = _clip(p.weight_kg, lo, hi);
      svg.appendChild(_el("circle", {
        cx: px, cy: yVal(clipped), r: "2.6", fill: C.dot, opacity: "0.26",
      }));
    });

    var ewmaByDate = {};
    ewma.forEach(function (p) {
      if (p.weight_kg != null) ewmaByDate[p.date] = p.weight_kg;
    });
    var pts = [];
    trend.forEach(function (p, i) {
      var v = ewmaByDate[p.date] != null ? ewmaByDate[p.date] : p.weight_kg;
      if (v == null) return;
      pts.push(xAt(i).toFixed(1) + "," + yVal(v).toFixed(1));
    });
    if (pts.length >= 2) {
      svg.appendChild(_el("path", {
        d: "M" + pts.join(" L"),
        fill: "none", stroke: C.trend, "stroke-width": "2.5", "stroke-linecap": "round",
      }));
      var last = pts[pts.length - 1].split(",");
      svg.appendChild(_el("circle", {
        cx: last[0], cy: last[1], r: "4.5", fill: C.trend,
      }));
    }

    decisions.forEach(function (d) {
      var day = d.decided_on || d.date;
      if (!day) return;
      var px = xDate(day);
      if (px == null) return;
      svg.appendChild(_el("line", {
        x1: px, y1: PAD.top - 4, x2: px, y2: PAD.top + plotH,
        stroke: C.decision, "stroke-width": "1", "stroke-dasharray": "3 3",
      }));
      svg.appendChild(_el("circle", {
        cx: px, cy: PAD.top - 2, r: "3.5", fill: C.decision,
      }));
    });

    var goalKg = data.target && data.target.target_weight_kg;
    if (goalKg != null && goalKg >= lo && goalKg <= hi) {
      var goalY = yVal(goalKg);
      svg.appendChild(_el("line", {
        x1: PAD.left, y1: goalY, x2: width - PAD.right, y2: goalY,
        stroke: "#16a34a", "stroke-width": "1", "stroke-dasharray": "4 4", opacity: "0.5",
      }));
    }

    var axisY = PAD.top + plotH + 6;
    svg.appendChild(_el("line", {
      x1: PAD.left, y1: axisY, x2: width - PAD.right, y2: axisY,
      stroke: "#e8eaf0", "stroke-width": "1",
    }));
    var tickIdx = [0, Math.floor((n - 1) / 3), Math.floor(((n - 1) * 2) / 3), n - 1];
    tickIdx.forEach(function (idx) {
      if (idx < 0 || idx >= n) return;
      var tx = _el("text", {
        x: xAt(idx), y: axisY + 14, "font-size": "9", fill: C.axis,
        "text-anchor": idx === 0 ? "start" : idx === n - 1 ? "end" : "middle",
        "font-family": "JetBrains Mono, ui-monospace, monospace",
      });
      tx.textContent = _fmtShort(dates[idx]);
      svg.appendChild(tx);
    });

    container.appendChild(svg);
  }

  global.WeightTimeline = {
    render: render,
    timelineDomain: timelineDomain,
  };
}(typeof window !== "undefined" ? window : globalThis));
