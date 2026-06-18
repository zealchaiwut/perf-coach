"use strict";

const WeightChart = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const VW = 900;
  const VH = 280;
  const PAD = { top: 18, right: 16, bottom: 30, left: 50 };
  const CW = VW - PAD.left - PAD.right; // 834
  const CH = VH - PAD.top - PAD.bottom; // 232

  // Zone layout: [past 5%][present 90%][future 5%] when a target exists (desktop).
  // On mobile/tablet (≤880px) rails are dropped — present fills full width.
  const RAIL_FR = 0.05;

  // Vertical zones: top 10% rail (out-of-range highs) / center 80% band (present data) / bottom 10% rail (goal).
  const V_TOP_RAIL = 0.1;
  const V_BAND = 0.8;
  const V_BOT_RAIL = 0.1;
  const MOBILE_CHART_H = 640; // taller viewBox height below this width (issue #515)
  const MOBILE_LAYOUT_W = 880; // drop past/future rails below this width
  const PAST_W = Math.round(CW * RAIL_FR);
  const FUTURE_W = Math.round(CW * RAIL_FR);
  const CUR_W3 = CW - PAST_W - FUTURE_W;

  const PAST_L = PAD.left;
  const PAST_R = PAST_L + PAST_W;
  const CUR_L3 = PAST_R; // current-zone left in 3-zone mode
  const CUR_R3 = CUR_L3 + CUR_W3;
  const FUTURE_L = CUR_R3;
  const FUTURE_R = PAD.left + CW;
  const C_PAST_LINE = "#cbd1da"; // thin grey past line
  const C_SEP = "#e5e7eb"; // zone separators

  const C = {
    actual: "#9ca3af",
    trend: "#2563eb",
    plan: "#16a34a",
    grid: "#e5e7eb",
    future_bg: "#f3f7ff",
    gap_behind: "#dc2626",
    gap_ahead: "#16a34a",
    gap_bg_behind: "#fee2e2",
    gap_bg_ahead: "#dcfce7",
    fill_ahead: "rgba(22, 163, 74, 0.17)",
    fill_behind: "rgba(220, 38, 38, 0.17)",
  };

  let _tooltip = null;
  let _activeDots = [];
  let _VH = VH; // render-time viewBox height (taller on mobile)
  let _CH = CH;

  // ── SVG helpers ────────────────────────────────────────────────────────

  function _el(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    if (attrs) {
      Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, String(v)));
    }
    return e;
  }

  // ── Y coordinate mapping ───────────────────────────────────────────────

  function _yCoord(val, yMin, yMax) {
    return PAD.top + _CH - ((val - yMin) / (yMax - yMin)) * _CH;
  }

  // ── Y bounds from API data ─────────────────────────────────────────────

  function _computeYBounds(data) {
    const vals = [];
    (data.actuals || []).forEach((p) => vals.push(p.weight_kg));
    (data.trend || []).forEach((p) => {
      if (p.weight_kg != null) vals.push(p.weight_kg);
    });
    if (data.today_marker) {
      if (data.today_marker.plan_kg != null)
        vals.push(data.today_marker.plan_kg);
      if (data.today_marker.trend_kg != null)
        vals.push(data.today_marker.trend_kg);
    }
    if (data.target && data.target.target_weight_kg != null) {
      vals.push(data.target.target_weight_kg);
    }
    if (!vals.length) return { yMin: 50, yMax: 100 };

    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const goalKg =
      data.target && data.target.target_weight_kg != null
        ? data.target.target_weight_kg
        : lo;

    return {
      yMin: Math.floor(Math.min(goalKg, lo) - 1),
      yMax: Math.ceil(hi + 1),
    };
  }

  // ── Present-band bounds (visible data in selected range) ──────────────
  // present_min = min(visible) - 10%*spread, present_max = max(visible) + 10%*spread

  function _computePresentBounds(data) {
    const vals = [];
    (data.actuals || []).forEach((p) => vals.push(p.weight_kg));
    (data.trend || []).forEach((p) => {
      if (p.weight_kg != null) vals.push(p.weight_kg);
    });
    if (data.today_marker) {
      if (data.today_marker.trend_kg != null)
        vals.push(data.today_marker.trend_kg);
      if (data.today_marker.plan_kg != null)
        vals.push(data.today_marker.plan_kg);
    }
    if (!vals.length) return { presentMin: 60, presentMax: 100 };
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const spread = hi - lo || 1;
    const buffer = spread * 0.1;
    return { presentMin: lo - buffer, presentMax: hi + buffer };
  }

  function _computeGlobalBounds(data, presentMin, presentMax) {
    const vals = [presentMin - 0.5, presentMax + 0.5];
    (data.past_actuals || []).forEach((p) => vals.push(p.weight_kg));
    if (data.target && data.target.target_weight_kg != null) {
      vals.push(data.target.target_weight_kg);
    }
    return {
      globalMin: Math.min(...vals),
      globalMax: Math.max(...vals),
    };
  }

  // ── Three-zone Y coordinate mapping ───────────────────────────────────
  // Top rail (V_TOP_RAIL): compresses values above presentMax.
  // Center band (V_BAND): linear scale between presentMin and presentMax.
  // Bottom rail (V_BOT_RAIL): compresses values below presentMin (incl. goal).

  function _yCoord3Zone(val, presentMin, presentMax, globalMin, globalMax) {
    const bandTop = PAD.top + _CH * V_TOP_RAIL;
    const bandBot = PAD.top + _CH * (V_TOP_RAIL + V_BAND);

    if (val >= presentMin && val <= presentMax) {
      const frac = (val - presentMin) / (presentMax - presentMin);
      return bandBot - frac * (bandBot - bandTop);
    } else if (val > presentMax) {
      // Top rail: compressed
      const railH = _CH * V_TOP_RAIL;
      const railFrac =
        globalMax > presentMax
          ? Math.min((val - presentMax) / (globalMax - presentMax), 1)
          : 0;
      return bandTop - railFrac * railH;
    } else {
      // Bottom rail: compressed (val < presentMin)
      const railH = _CH * V_BOT_RAIL;
      const railFrac =
        presentMin > globalMin
          ? Math.min((presentMin - val) / (presentMin - globalMin), 1)
          : 0;
      return bandBot + railFrac * railH;
    }
  }

  // ── Tooltip ────────────────────────────────────────────────────────────

  function _initTooltip(container) {
    if (_tooltip && container.contains(_tooltip)) return;
    _tooltip = document.createElement("div");
    _tooltip.className = "wc-tooltip";
    Object.assign(_tooltip.style, {
      position: "absolute",
      pointerEvents: "none",
      display: "none",
      background: "#1a1a1a",
      color: "#fff",
      padding: "5px 9px",
      borderRadius: "5px",
      fontSize: "0.8125rem",
      whiteSpace: "nowrap",
      zIndex: "10",
      boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
    });
    container.appendChild(_tooltip);
  }

  function _showTooltip(svgEl, clientX, clientY, date, kg) {
    if (!_tooltip) return;
    const rect = svgEl.getBoundingClientRect();
    const x = clientX - rect.left + 14;
    const y = Math.max(0, clientY - rect.top - 40);
    _tooltip.style.left = x + "px";
    _tooltip.style.top = y + "px";
    const d = new Date(date + "T00:00:00");
    const label = d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    _tooltip.textContent = `${label}  ·  ${kg.toFixed(1)} kg`;
    _tooltip.style.display = "block";
  }

  function _hideTooltip() {
    if (_tooltip) _tooltip.style.display = "none";
  }

  function _isLossGoal(data) {
    const t = data.target;
    if (!t || t.start_weight_kg == null || t.target_weight_kg == null)
      return true;
    return t.start_weight_kg > t.target_weight_kg;
  }

  function _trendAhead(trendKg, planKg, isLoss) {
    if (isLoss) return trendKg <= planKg;
    return trendKg >= planKg;
  }

  function _crossPoint(a, b) {
    const denom = b.t - a.t - (b.p - a.p);
    if (Math.abs(denom) < 1e-6) return { x: b.x, t: b.t, p: b.p };
    const frac = Math.max(0, Math.min(1, (a.p - a.t) / denom));
    return {
      x: a.x + frac * (b.x - a.x),
      t: a.t + frac * (b.t - a.t),
      p: a.p + frac * (b.p - a.p),
    };
  }

  function _drawGapPolygon(svg, pts, yFn, ahead) {
    if (pts.length < 2) return;
    let d = "M " + pts[0].x.toFixed(2) + " " + yFn(pts[0].t).toFixed(2);
    for (let k = 1; k < pts.length; k++) {
      d += " L " + pts[k].x.toFixed(2) + " " + yFn(pts[k].t).toFixed(2);
    }
    for (let k = pts.length - 1; k >= 0; k--) {
      d += " L " + pts[k].x.toFixed(2) + " " + yFn(pts[k].p).toFixed(2);
    }
    d += " Z";
    svg.appendChild(
      _el("path", {
        d,
        fill: ahead ? C.fill_ahead : C.fill_behind,
        stroke: "none",
      }),
    );
  }

  function _renderGapFill(svg, data, xIdx, y) {
    if (!data.plan_series || !data.plan_series.length) return;
    const planByDate = {};
    data.plan_series.forEach((p) => {
      planByDate[p.date] = p.plan_kg;
    });
    const isLoss = _isLossGoal(data);

    const segs = [];
    let cur = [];
    (data.trend || []).forEach((p, idx) => {
      if (p.weight_kg == null) {
        if (cur.length >= 2) segs.push(cur);
        cur = [];
      } else {
        const plan = planByDate[p.date];
        if (plan != null) {
          cur.push({ x: xIdx(idx), t: p.weight_kg, p: plan });
        }
      }
    });
    if (cur.length >= 2) segs.push(cur);

    segs.forEach((seg) => {
      let i = 0;
      while (i < seg.length - 1) {
        const ahead = _trendAhead(seg[i].t, seg[i].p, isLoss);
        let j = i + 1;
        while (
          j < seg.length &&
          _trendAhead(seg[j].t, seg[j].p, isLoss) === ahead
        )
          j++;
        const poly = seg.slice(i, j);
        if (j < seg.length) poly.push(_crossPoint(seg[j - 1], seg[j]));
        _drawGapPolygon(svg, poly, y, ahead);
        i = j < seg.length ? j : seg.length;
      }
    });
  }

  function _updateVerdictBanner(data) {
    const wrap = document.getElementById("chart-verdict");
    const pill = document.getElementById("chart-verdict-pill");
    const text = document.getElementById("chart-verdict-text");
    if (!wrap || !pill || !text) return;

    const tm = data.today_marker;
    const dir = tm && tm.gap_direction;
    if (!tm || !dir || dir === "no_data" || tm.gap_kg == null) {
      wrap.hidden = true;
      return;
    }

    wrap.hidden = false;
    const isAhead = dir === "ahead";
    const isBehind = dir === "behind";
    const absGap = Math.abs(tm.gap_kg).toFixed(1);
    const sign = isAhead ? "−" : "+";

    pill.className =
      "chart-verdict-pill" +
      (isAhead
        ? " chart-verdict-pill--ahead"
        : isBehind
          ? " chart-verdict-pill--behind"
          : " chart-verdict-pill--on-track");
    pill.textContent = isAhead
      ? "AHEAD " + sign + absGap + " kg"
      : isBehind
        ? "BEHIND " + sign + absGap + " kg"
        : "ON TRACK";

    const trendStr = tm.trend_kg != null ? tm.trend_kg.toFixed(1) : "—";
    const planStr = tm.plan_kg != null ? tm.plan_kg.toFixed(1) : "—";
    const sideWord = isAhead ? "below" : isBehind ? "above" : "on";
    const fillWord = isAhead ? "green" : "red";
    let summary =
      "Trend sits " +
      sideWord +
      " the plan line — gap shaded " +
      fillWord +
      ". 7-day avg " +
      trendStr +
      " vs plan " +
      planStr;

    const tgt = data.target;
    if (tgt && tgt.target_date) {
      const goalD = new Date(tgt.target_date + "T00:00:00");
      const goalLbl = goalD.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
      summary +=
        " · goal " +
        (tgt.target_weight_kg != null ? tgt.target_weight_kg.toFixed(0) : "") +
        " kg by " +
        goalLbl;
    }
    text.textContent = summary;
  }

  function _findNearestDot(svgEl, clientX, clientY) {
    const rect = svgEl.getBoundingClientRect();
    const scaleX = VW / (rect.width || 1);
    const scaleY = _VH / (rect.height || 1);
    const sx = (clientX - rect.left) * scaleX;
    const sy = (clientY - rect.top) * scaleY;
    let best = null,
      bestDist = Infinity;
    for (const dot of _activeDots) {
      const dist = Math.hypot(dot.cx - sx, dot.cy - sy);
      if (dist < bestDist && dist < 32 * scaleX) {
        best = dot;
        bestDist = dist;
      }
    }
    return best;
  }

  // ── X-axis labels ──────────────────────────────────────────────────────

  function _renderXLabels(svg, trendDates, range, xFn) {
    const n = trendDates.length;
    if (!n) return;
    // At most 7 evenly-spaced ticks, each on two lines (day over month) to keep
    // them readable and un-cluttered regardless of range length.
    const TICKS = Math.min(7, n);
    const longRange =
      range === "90d" || range === "6m" || range === "1y" || range === "all";
    const seen = new Set();
    for (let t = 0; t < TICKS; t++) {
      const idx = TICKS === 1 ? 0 : Math.round((t * (n - 1)) / (TICKS - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      const d = new Date(trendDates[idx] + "T00:00:00");
      const px = xFn(idx, n);
      const line1 = longRange
        ? d.toLocaleDateString("en-US", { month: "short" })
        : d.toLocaleDateString("en-US", { day: "numeric" });
      const line2 = longRange
        ? d.toLocaleDateString("en-US", { year: "2-digit" })
        : d.toLocaleDateString("en-US", { month: "short" });
      const t1 = _el("text", {
        x: px,
        y: PAD.top + _CH + 13,
        "text-anchor": "middle",
        "font-size": "11",
        fill: "#9ca3af",
      });
      t1.textContent = line1;
      svg.appendChild(t1);
      const t2 = _el("text", {
        x: px,
        y: PAD.top + _CH + 25,
        "text-anchor": "middle",
        "font-size": "10",
        fill: "#b0b6c0",
      });
      t2.textContent = line2;
      svg.appendChild(t2);
    }
  }

  // ── Main render ────────────────────────────────────────────────────────

  function render(data, range) {
    const container = document.getElementById("weight-chart");
    if (!container) return;

    // Hide loading placeholder
    const loading = document.getElementById("chart-loading");
    if (loading) loading.hidden = true;
    container.hidden = false;

    // Taller plot on mobile so the trend has vertical room to read (≈3.2:1
    // desktop sliver → ~1.9:1 on phones).
    const narrow = window.innerWidth <= MOBILE_LAYOUT_W;
    _VH = window.innerWidth <= MOBILE_CHART_H ? 520 : narrow ? 400 : VH;
    _CH = _VH - PAD.top - PAD.bottom;

    // Persistent (always-visible) labels for current weight, plan, gap, and
    // milestone values on narrow viewports — touch devices can't hover.
    const isMobile = window.innerWidth <= 480;
    const isMobileChart = narrow;

    const hasTarget = !!(data.plan_series && data.plan_series.length);
    const hasFuture = !!(
      data.future_milestones && data.future_milestones.length
    );

    // Three-zone on desktop when a target exists; mobile drops rails.
    const threeZone = hasTarget && !isMobileChart;
    const hasFutureZone = threeZone;
    const curL = threeZone ? CUR_L3 : PAD.left;
    const curR = threeZone ? CUR_R3 : PAD.left + CW - 80;
    const curW = curR - curL;

    // Reset container
    container.innerHTML = "";
    container.style.position = "relative";
    _initTooltip(container);

    // Build SVG
    const svg = _el("svg", {
      viewBox: "0 0 " + VW + " " + _VH,
      "aria-label": "Weight trend chart",
      role: "img",
    });
    svg.setAttribute("width", "100%");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.style.display = "block";
    svg.style.width = "100%";
    svg.style.height = "auto";
    svg.style.aspectRatio = VW + " / " + _VH;
    container.appendChild(svg);

    _activeDots = [];

    // Y scale — three-zone system: top 10% rail / center 80% present band / bottom 10% rail.
    const { yMin, yMax } = _computeYBounds(data); // kept for legacy tests
    const { presentMin, presentMax } = _computePresentBounds(data);
    const { globalMin, globalMax } = _computeGlobalBounds(
      data,
      presentMin,
      presentMax,
    );
    const y = (val) =>
      _yCoord3Zone(val, presentMin, presentMax, globalMin, globalMax);

    const trendDates = (data.trend || []).map((p) => p.date);
    const n = trendDates.length;

    function xIdx(idx) {
      return curL + (n > 1 ? (idx / (n - 1)) * curW : 0);
    }
    function xDate(dateStr) {
      const idx = trendDates.indexOf(dateStr);
      return idx < 0 ? null : xIdx(idx);
    }
    function xDateFn(idx) {
      return xIdx(idx);
    }

    const gridRight = threeZone ? FUTURE_R : curR;
    const gridLeft = threeZone ? PAST_L : curL;

    // ── 1. Zone tints + thin separators ─────────────────────────────────
    if (threeZone) {
      svg.appendChild(
        _el("rect", {
          // past: faint grey wash
          x: PAST_L,
          y: PAD.top,
          width: PAST_W,
          height: _CH,
          fill: "#f3f4f6",
          opacity: "0.7",
        }),
      );
      svg.appendChild(
        _el("rect", {
          // future: faint blue wash
          x: FUTURE_L,
          y: PAD.top,
          width: FUTURE_W,
          height: _CH,
          fill: C.future_bg,
        }),
      );
      [PAST_R, CUR_R3].forEach((sx) => {
        svg.appendChild(
          _el("line", {
            x1: sx,
            y1: PAD.top,
            x2: sx,
            y2: PAD.top + _CH,
            stroke: C_SEP,
            "stroke-width": "1",
          }),
        );
      });
      // Rail labels
      ["PAST", "FUTURE"].forEach((lbl, zi) => {
        const cx = zi === 0 ? (PAST_L + PAST_R) / 2 : (FUTURE_L + FUTURE_R) / 2;
        const t = _el("text", {
          x: cx,
          y: PAD.top + 11,
          "text-anchor": "middle",
          "font-size": "7.5",
          fill: "#b0b8cc",
          "font-weight": "600",
          "letter-spacing": "0.08em",
        });
        t.textContent = lbl;
        svg.appendChild(t);
      });
    }

    // ── 2. Gridlines — integer ticks within the present band (every 2 kg) ─
    for (let kg = Math.ceil(presentMin / 2) * 2; kg <= presentMax; kg += 2) {
      const gy = y(kg);
      svg.appendChild(
        _el("line", {
          x1: gridLeft,
          y1: gy,
          x2: gridRight,
          y2: gy,
          stroke: C.grid,
          "stroke-width": "0.75",
        }),
      );
      const lbl = _el("text", {
        x: gridLeft - 5,
        y: gy,
        "text-anchor": "end",
        "dominant-baseline": "middle",
        "font-size": "12",
        fill: "#9ca3af",
      });
      lbl.textContent = String(kg);
      svg.appendChild(lbl);
    }

    // ── 4. Green dashed plan line ───────────────────────────────────────
    if (data.plan_series && data.plan_series.length) {
      const pts = [];
      data.plan_series.forEach((p) => {
        const px = xDate(p.date);
        if (px != null) pts.push(`${px},${y(p.plan_kg)}`);
      });
      if (pts.length >= 2) {
        svg.appendChild(
          _el("polyline", {
            points: pts.join(" "),
            fill: "none",
            stroke: C.plan,
            "stroke-width": "1.5",
            "stroke-dasharray": "5 3",
          }),
        );
      }
    }

    // ── Gap-vs-plan area fill (green ahead / red behind; pauses on null gaps) ──
    _renderGapFill(svg, data, xIdx, y);

    // ── Past zone: thin grey line through earlier weigh-ins (no dots) ────
    if (threeZone && (data.past_actuals || []).length) {
      const pa = data.past_actuals;
      const t0 = new Date(pa[0].date + "T00:00:00").getTime();
      const t1 = new Date(
        (data.range && data.range.from
          ? data.range.from
          : pa[pa.length - 1].date) + "T00:00:00",
      ).getTime();
      const span = Math.max(1, t1 - t0);
      const xPast = (ds) =>
        PAST_L +
        ((new Date(ds + "T00:00:00").getTime() - t0) / span) * (PAST_W - 4);
      const ppts = pa.map((pt) => `${xPast(pt.date)},${y(pt.weight_kg)}`);
      if (ppts.length >= 2) {
        svg.appendChild(
          _el("polyline", {
            points: ppts.join(" "),
            fill: "none",
            stroke: C_PAST_LINE,
            "stroke-width": "1.2",
            "stroke-linejoin": "round",
            "stroke-linecap": "round",
          }),
        );
      }
      // bridge last past point → first present trend point for continuity
      const lastPast = pa[pa.length - 1];
      const firstTrend = (data.trend || []).find((t) => t.weight_kg != null);
      if (ppts.length && firstTrend) {
        svg.appendChild(
          _el("line", {
            x1: xPast(lastPast.date),
            y1: y(lastPast.weight_kg),
            x2: xIdx(trendDates.indexOf(firstTrend.date)),
            y2: y(firstTrend.weight_kg),
            stroke: C_PAST_LINE,
            "stroke-width": "1.2",
            "stroke-dasharray": "2 2",
          }),
        );
      }
    }

    // ── 5. Gray weigh-in dots (one per actual entry in present window) ─────
    const dotR = isMobileChart ? "5" : "3.5";
    (data.actuals || []).forEach((p) => {
      const px = xDate(p.date);
      if (px == null) return;
      const py = y(p.weight_kg);
      svg.appendChild(
        _el("circle", {
          cx: px,
          cy: py,
          r: dotR,
          fill: C.actual,
        }),
      );
      _activeDots.push({ cx: px, cy: py, date: p.date, kg: p.weight_kg });
    });

    // ── 6. Blue 7-day trend path ────────────────────────────────────────
    // Thin dashed bridge first: connects every trend point across missing-data
    // gaps. Drawn under the thick segments, so it only shows inside the gaps.
    const bridgePts = [];
    (data.trend || []).forEach((p, idx) => {
      if (p.weight_kg != null) bridgePts.push(`${xIdx(idx)},${y(p.weight_kg)}`);
    });
    if (bridgePts.length >= 2) {
      svg.appendChild(
        _el("polyline", {
          points: bridgePts.join(" "),
          fill: "none",
          stroke: C.trend,
          "stroke-width": "1",
          "stroke-dasharray": "2 3",
          opacity: "0.45",
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
        }),
      );
    }

    let trendSeg = [];
    (data.trend || []).forEach((p, idx) => {
      if (p.weight_kg == null) {
        if (trendSeg.length >= 2) {
          svg.appendChild(
            _el("polyline", {
              points: trendSeg.join(" "),
              fill: "none",
              stroke: C.trend,
              "stroke-width": "2.8",
              "stroke-linejoin": "round",
              "stroke-linecap": "round",
            }),
          );
        }
        trendSeg = [];
      } else {
        const px = xIdx(idx);
        trendSeg.push(`${px},${y(p.weight_kg)}`);
        _activeDots.push({
          cx: px,
          cy: y(p.weight_kg),
          date: p.date,
          kg: p.weight_kg,
        });
      }
    });
    if (trendSeg.length >= 2) {
      svg.appendChild(
        _el("polyline", {
          points: trendSeg.join(" "),
          fill: "none",
          stroke: C.trend,
          "stroke-width": "2.8",
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
        }),
      );
    }

    // ── 7. Green-stroked white plan dot + "plan X kg" label ────────────
    const tm = data.today_marker;
    let todayX = null,
      planDotY = null,
      trendDotY = null;

    if (tm && tm.date) {
      todayX = xDate(tm.date);
      if (todayX == null) todayX = curR - 4;
    }
    // When the today marker sits near the right edge, the "plan"/"you" labels
    // and the gap chip would overflow the viewBox — flip them to the left side.
    const labelLeft = todayX != null && (threeZone || todayX > VW - 92);

    if (tm && tm.plan_kg != null && todayX != null) {
      planDotY = y(tm.plan_kg);
      svg.appendChild(
        _el("circle", {
          cx: todayX,
          cy: planDotY,
          r: "5",
          fill: "#fff",
          stroke: C.plan,
          "stroke-width": "2",
        }),
      );
      _activeDots.push({
        cx: todayX,
        cy: planDotY,
        date: tm.date,
        kg: tm.plan_kg,
      });
      // Persistent plan label on mobile (hover not available on touch)
      if (isMobile) {
        const lx = labelLeft ? todayX - 8 : todayX + 8;
        const anchor = labelLeft ? "end" : "start";
        const planLbl = _el("text", {
          x: lx,
          y: planDotY - 10,
          "text-anchor": anchor,
          "font-size": "11",
          fill: C.plan,
          "font-weight": "600",
        });
        planLbl.textContent = tm.plan_kg.toFixed(1) + " kg";
        svg.appendChild(planLbl);
      }
    }

    // ── 8. Blue highlighted dot + "you X kg" label ─────────────────────
    if (tm && tm.trend_kg != null && todayX != null) {
      trendDotY = y(tm.trend_kg);
      svg.appendChild(
        _el("circle", {
          cx: todayX,
          cy: trendDotY,
          r: "5",
          fill: C.trend,
          stroke: "#fff",
          "stroke-width": "1.5",
        }),
      );
      _activeDots.push({
        cx: todayX,
        cy: trendDotY,
        date: tm.date,
        kg: tm.trend_kg,
      });
      // Persistent current-weight label on mobile; offset down when plan label is close
      if (isMobile) {
        const lx = labelLeft ? todayX - 8 : todayX + 8;
        const anchor = labelLeft ? "end" : "start";
        const labelOff =
          planDotY != null && Math.abs(trendDotY - planDotY) < 18 ? 14 : -10;
        const trendLbl = _el("text", {
          x: lx,
          y: trendDotY + labelOff,
          "text-anchor": anchor,
          "font-size": "11",
          fill: C.trend,
          "font-weight": "600",
        });
        trendLbl.textContent = tm.trend_kg.toFixed(1) + " kg";
        svg.appendChild(trendLbl);
      }
    }

    // ── 9. Red/green dashed vertical gap line + rounded gap chip ───────
    const gapDir = tm ? tm.gap_direction : null;
    if (
      gapDir &&
      gapDir !== "no_data" &&
      todayX != null &&
      planDotY != null &&
      trendDotY != null
    ) {
      const isAhead = gapDir === "ahead";
      const gapColor = isAhead ? C.gap_ahead : C.gap_behind;
      const gapBg = isAhead ? C.gap_bg_ahead : C.gap_bg_behind;
      const topY = Math.min(planDotY, trendDotY);
      const botY = Math.max(planDotY, trendDotY);

      svg.appendChild(
        _el("line", {
          x1: todayX,
          y1: topY + 5,
          x2: todayX,
          y2: botY - 5,
          stroke: gapColor,
          "stroke-width": "1.5",
          "stroke-dasharray": "3 2",
        }),
      );

      // On mobile, show persistent gap label since hover isn't available.
      // gap_kg from today_marker gives the numerical distance vs plan.
      if (isMobile && tm && tm.gap_kg != null) {
        const midY = (topY + botY) / 2;
        const lx = labelLeft ? todayX - 8 : todayX + 8;
        const anchor = labelLeft ? "end" : "start";
        const sign = isAhead ? "−" : "+";
        const gapLbl = _el("text", {
          x: lx,
          y: midY + 4,
          "text-anchor": anchor,
          "font-size": "10",
          fill: gapColor,
          "font-weight": "700",
        });
        gapLbl.textContent = sign + Math.abs(tm.gap_kg).toFixed(1) + " kg";
        svg.appendChild(gapLbl);
      }
      void gapBg;
    }

    // (Zone boundaries are drawn as thin separators above; no axis-break glyph.)

    // ── Future zone: next milestone diamond + goal dot only ───────────────
    if (hasFutureZone) {
      const milestones = data.future_milestones || [];
      const goalMs = milestones.find((m) => m.kind === "goal");
      const nextMs = milestones.find((m) => m.kind !== "goal");

      const tmPlan = data.today_marker ? data.today_marker.plan_kg : null;
      const fpts = [];
      if (tmPlan != null) fpts.push(curR + "," + y(tmPlan));

      const nextX = FUTURE_L + FUTURE_W * 0.38;
      const goalX = FUTURE_R - 8;

      if (nextMs) {
        fpts.push(nextX + "," + y(nextMs.plan_kg));
        const my = y(nextMs.plan_kg);
        const s = 6;
        svg.appendChild(
          _el("polygon", {
            points:
              nextX +
              "," +
              (my - s) +
              " " +
              (nextX + s) +
              "," +
              my +
              " " +
              nextX +
              "," +
              (my + s) +
              " " +
              (nextX - s) +
              "," +
              my,
            fill: "#fff",
            stroke: C.plan,
            "stroke-width": "2",
          }),
        );
        _activeDots.push({
          cx: nextX,
          cy: my,
          date: nextMs.date,
          kg: nextMs.plan_kg,
        });
      }

      if (goalMs) {
        fpts.push(goalX + "," + y(goalMs.plan_kg));
        const gy = y(goalMs.plan_kg);
        svg.appendChild(
          _el("circle", {
            cx: goalX,
            cy: gy,
            r: "6",
            fill: C.plan,
            stroke: "#fff",
            "stroke-width": "1.5",
          }),
        );
        _activeDots.push({
          cx: goalX,
          cy: gy,
          date: goalMs.date,
          kg: goalMs.plan_kg,
        });
      }

      if (fpts.length >= 2) {
        svg.appendChild(
          _el("polyline", {
            points: fpts.join(" "),
            fill: "none",
            stroke: C.plan,
            "stroke-width": "1.5",
            "stroke-dasharray": "2 3",
          }),
        );
      }
    }

    // ── Goal chip — bottom rail, always visible (desktop + mobile) ──────────
    // The three-zone Y mapping places the goal in the bottom 10% rail when it is
    // below the present band, keeping it visible without distorting the main scale.
    if (hasTarget && data.target && data.target.target_weight_kg != null) {
      const goalKg = data.target.target_weight_kg;
      const gy = y(goalKg);
      const gx = threeZone ? FUTURE_R - 8 : curR - 4;
      const chipW = 68;
      const chipH = 22;
      svg.appendChild(
        _el("rect", {
          x: gx - chipW,
          y: gy - chipH / 2,
          width: chipW,
          height: chipH,
          rx: "6",
          fill: "#fff",
          stroke: C.plan,
          "stroke-width": "1",
        }),
      );
      const chipT = _el("text", {
        x: gx - chipW / 2,
        y: gy,
        "text-anchor": "middle",
        "dominant-baseline": "middle",
        "font-size": "9",
        fill: C.plan,
        "font-weight": "700",
        "font-family": "JetBrains Mono, monospace",
      });
      chipT.textContent = goalKg.toFixed(0) + " · goal";
      svg.appendChild(chipT);
      _activeDots.push({
        cx: gx - chipW / 2,
        cy: gy,
        date: data.target.target_date || "",
        kg: goalKg,
      });
    }

    // ── "milestones ↓" link (shown when future zone is suppressed but target exists) ──
    if (hasTarget && hasFuture && !hasFutureZone) {
      const link = document.createElement("a");
      link.href = "#progress-card";
      link.className = "wc-milestones-link";
      link.textContent = "milestones ↓";
      Object.assign(link.style, {
        display: "block",
        textAlign: "right",
        fontSize: "12px",
        color: "#16a34a",
        textDecoration: "none",
        marginTop: "4px",
        paddingRight: "4px",
      });
      container.appendChild(link);
    }

    // ── X-axis labels ───────────────────────────────────────────────────
    _renderXLabels(svg, trendDates, range, xDateFn);

    // ── Tooltip events (mouse + touch) ──────────────────────────────────
    svg.addEventListener("mousemove", (ev) => {
      const dot = _findNearestDot(svg, ev.clientX, ev.clientY);
      if (dot) _showTooltip(svg, ev.clientX, ev.clientY, dot.date, dot.kg);
      else _hideTooltip();
    });
    svg.addEventListener("mouseleave", () => _hideTooltip());
    // touchstart: tap-to-show — immediately reveals the nearest point's value.
    // A second tap elsewhere dismisses the previous tooltip and shows the new one.
    svg.addEventListener(
      "touchstart",
      (ev) => {
        if (ev.touches.length) {
          const t = ev.touches[0];
          const dot = _findNearestDot(svg, t.clientX, t.clientY);
          if (dot) _showTooltip(svg, t.clientX, t.clientY, dot.date, dot.kg);
          else _hideTooltip();
        }
      },
      { passive: true },
    );
    svg.addEventListener(
      "touchmove",
      (ev) => {
        if (ev.touches.length) {
          const t = ev.touches[0];
          const dot = _findNearestDot(svg, t.clientX, t.clientY);
          if (dot) _showTooltip(svg, t.clientX, t.clientY, dot.date, dot.kg);
          else _hideTooltip();
        }
      },
      { passive: true },
    );
    svg.addEventListener("touchend", () => _hideTooltip());

    _updateVerdictBanner(data);
  }

  return { render };
})();
