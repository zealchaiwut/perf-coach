"use strict";

const WeightChart = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const VW = 900;
  const VH = 280;
  const PAD = { top: 18, right: 16, bottom: 40, left: 50 };
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
    let presentMin = lo - buffer;
    let presentMax = hi + buffer;
    // Enforce a minimum visible window so flat data doesn't collapse to a
    // single gridline. Expand symmetrically around the midpoint to MIN_SPAN.
    const MIN_SPAN = 3;
    if (presentMax - presentMin < MIN_SPAN) {
      const mid = (presentMin + presentMax) / 2;
      presentMin = mid - MIN_SPAN / 2;
      presentMax = mid + MIN_SPAN / 2;
    }
    return { presentMin, presentMax };
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
        y: PAD.top + _CH + 15,
        "text-anchor": "middle",
        "font-size": "17",
        fill: "#6b7280",
        "font-weight": "600",
      });
      t1.textContent = line1;
      svg.appendChild(t1);
      const t2 = _el("text", {
        x: px,
        y: PAD.top + _CH + 30,
        "text-anchor": "middle",
        "font-size": "15",
        fill: "#9ca3af",
      });
      t2.textContent = line2;
      svg.appendChild(t2);
    }
  }

  // ── Main render ────────────────────────────────────────────────────────

  // ── Mode (Basic / Advanced) ──────────────────────────────────────────────
  // Basic draws a strict subset of Advanced — identical colors, scale, and X
  // positions — so nothing moves or recolors on toggle. History always occupies
  // the left 80%; the forecast region (right 20%) is blank in Basic.
  let _mode = (function () {
    try { return localStorage.getItem("weightChartMode") === "advanced" ? "advanced" : "basic"; }
    catch (e) { return "basic"; }
  })();
  let _lastData = null;
  let _lastRange = null;
  const HIST_FRAC = 0.8;          // history occupies the left 80% in BOTH modes
  const GOAL_TOL_KG = 0.3;        // ± tolerance band around the goal (no pref field yet)

  function getMode() { return _mode; }
  function setMode(m) {
    _mode = m === "advanced" ? "advanced" : "basic";
    try { localStorage.setItem("weightChartMode", _mode); } catch (e) {}
    if (_lastData) render(_lastData, _lastRange);
  }

  function render(data, range) {
    _lastData = data;
    _lastRange = range;

    const container = document.getElementById("weight-chart");
    if (!container) return;
    const loading = document.getElementById("chart-loading");
    if (loading) loading.hidden = true;
    container.hidden = false;

    const advanced = _mode === "advanced";

    // Taller plot on mobile so the trend has vertical room to read.
    const narrow = window.innerWidth <= MOBILE_LAYOUT_W;
    _VH = window.innerWidth <= MOBILE_CHART_H ? 520 : narrow ? 400 : VH;
    _CH = _VH - PAD.top - PAD.bottom;
    // ≤480px: bigger tap targets + the goal chip flips to avoid the right axis.
    const isMobile = window.innerWidth <= 480;
    // threeZone kept as a flag for parity with prior behaviour/tests; the
    // redesign uses a single history/forecast split rather than past/future rails.
    const threeZone = false;

    // ── Unit (respect kg / lbs; data is kg) ──
    const unit = data.unit === "lbs" ? "lbs" : "kg";
    const toU = unit === "lbs" ? (kg) => kg * 2.2046226218 : (kg) => kg;
    const TOL = toU(GOAL_TOL_KG);

    container.innerHTML = "";
    container.style.position = "relative";
    _initTooltip(container);

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

    // Verdict banner ("ON TRACK" / "AHEAD" / "BEHIND") is an Advanced-only cue.
    const _verdict = document.getElementById("chart-verdict");
    if (advanced) _updateVerdictBanner(data);
    else if (_verdict) _verdict.hidden = true;

    // ── Layout: left 80% history, right 20% forecast ──
    const AX = 46;                       // right-axis label gutter
    const L = PAD.left - 36;             // pull plot left; labels live on the right
    const R = VW - AX;
    const plotW = R - L;
    const T = PAD.top;
    const B = T + _CH;
    const nowX = L + plotW * HIST_FRAC;

    const trend = data.trend || [];
    const trendDates = trend.map((p) => p.date);
    const n = trendDates.length;
    function xIdx(idx) { return L + (n > 1 ? (idx / (n - 1)) * (plotW * HIST_FRAC) : 0); }
    function xDate(dateStr) { const i = trendDates.indexOf(dateStr); return i < 0 ? null : xIdx(i); }

    const target = data.target || null;
    const goalKg = target && target.target_weight_kg != null ? target.target_weight_kg : null;
    const goalU = goalKg != null ? toU(goalKg) : null;

    // ── Value scale (display unit) — keep the goal band slim (~1/5 height) by
    // leaving room below the goal; enforce a 3-unit minimum span. ──
    // Vertical scale from the present band (recomputed per range tab), lowered
    // so the goal-zone band fits with room below. presentMin/presentMax also
    // bound the gridlines, consistent with the three-zone scale helpers.
    const _pb = _computePresentBounds(data); // kg
    let presentMin = toU(_pb.presentMin);
    let presentMax = toU(_pb.presentMax);
    if (goalU != null) presentMin = Math.min(presentMin, goalU - TOL - 0.4);
    let span = presentMax - presentMin;
    if (span < 3) { const mid = (presentMin + presentMax) / 2; presentMin = mid - 1.5; presentMax = mid + 1.5; span = 3; }
    const hi = presentMax, lo = presentMin;
    const y = (valU) => T + ((presentMax - valU) / span) * _CH;

    // ════ 1. Forecast tint (advanced) — BEFORE gridlines ════
    if (advanced) {
      svg.appendChild(_el("rect", { x: nowX, y: T, width: R - nowX, height: _CH, fill: C.future_bg }));
      const fl = _el("text", {
        x: nowX + 6, y: T + 12, "font-size": "10", "font-weight": "700",
        "letter-spacing": "0.08em", fill: "#94a3b8",
      });
      fl.textContent = "FORECAST";
      svg.appendChild(fl);
    }

    // ════ 2. Goal zone band (shared) — slim tinted green band, full width ════
    let bandTop = null, bandBot = null, goalY = null;
    const hasTarget = goalU != null;
    if (hasTarget) {
      goalY = y(goalU);
      bandTop = y(goalU + TOL);
      bandBot = y(goalU - TOL);
      svg.appendChild(_el("rect", { x: L, y: bandTop, width: plotW, height: bandBot - bandTop, fill: "rgba(22,163,74,0.10)" }));
      svg.appendChild(_el("line", { x1: L, y1: bandTop, x2: R, y2: bandTop, stroke: "rgba(22,163,74,0.35)", "stroke-width": "1", "stroke-dasharray": "3 3" }));
      svg.appendChild(_el("line", { x1: L, y1: bandBot, x2: R, y2: bandBot, stroke: "rgba(22,163,74,0.35)", "stroke-width": "1", "stroke-dasharray": "3 3" }));
      svg.appendChild(_el("line", { x1: L, y1: goalY, x2: R, y2: goalY, stroke: C.plan, "stroke-width": "1.5", "stroke-dasharray": "6 4" }));
      // Goal-zone chip (shown on desktop + mobile when hasTarget). On very
      // narrow viewports it flips toward the left so it clears the right axis.
      const labelLeft = isMobile || (L + 90) < R;
      const chipT = _el("text", {
        x: labelLeft ? L + 4 : R - 90, y: bandTop - 5, dy: "0",
        "font-size": "11", "font-weight": "700", fill: "#15803d",
      });
      chipT.textContent = "Goal zone · " + goalU.toFixed(1) + " " + unit;
      svg.appendChild(chipT);
    }

    // ════ 3. Gridlines (shared) — adaptive integer step; right-axis labels ════
    const _bandSpan = span;
    const _tickStep = _bandSpan <= 6 ? 1 : _bandSpan <= 15 ? 2 : 5;
    for (let kg = Math.ceil(presentMin / _tickStep) * _tickStep; kg <= presentMax; kg += _tickStep) {
      const gy = y(kg);
      svg.appendChild(_el("line", { x1: L, y1: gy, x2: R, y2: gy, stroke: C.grid, "stroke-width": "0.75", "stroke-dasharray": "2 3" }));
      const lbl = _el("text", { x: R + 6, y: gy + 4, "text-anchor": "start", "font-size": "12", fill: "#9ca3af" });
      lbl.textContent = String(Math.round(kg));
      svg.appendChild(lbl);
    }

    // Plan helpers (history + forecast). plan_series spans the history dates.
    const planByDate = {};
    (data.plan_series || []).forEach((p) => { planByDate[p.date] = toU(p.plan_kg); });
    const hasPlan = !!(data.plan_series && data.plan_series.length);
    const isLoss = _isLossGoal(data);

    // ════ 4. Ahead/behind shading (advanced) — between trend & plan, per day ════
    if (advanced && hasPlan) {
      for (let s = 0; s < n - 1; s++) {
        const d0 = trendDates[s], d1 = trendDates[s + 1];
        const p0 = planByDate[d0], p1 = planByDate[d1];
        const t0 = trend[s].weight_kg != null ? toU(trend[s].weight_kg) : null;
        const t1 = trend[s + 1].weight_kg != null ? toU(trend[s + 1].weight_kg) : null;
        if (p0 == null || p1 == null || t0 == null || t1 == null) continue;
        const ahead = _trendAhead((t0 + t1) / 2, (p0 + p1) / 2, isLoss);
        const poly = [
          xIdx(s) + "," + y(t0), xIdx(s + 1) + "," + y(t1),
          xIdx(s + 1) + "," + y(p1), xIdx(s) + "," + y(p0),
        ].join(" ");
        svg.appendChild(_el("polygon", { points: poly, fill: ahead ? C.fill_ahead : C.fill_behind }));
      }
    }

    // ════ 5. Plan line (advanced) — green dash across history, BEFORE dots ════
    if (advanced && hasPlan) {
      const pts = [];
      trendDates.forEach((d, i) => { if (planByDate[d] != null) pts.push(xIdx(i) + "," + y(planByDate[d])); });
      if (pts.length >= 2) {
        svg.appendChild(_el("polyline", {
          points: pts.join(" "), fill: "none", stroke: C.plan,
          "stroke-width": "2", "stroke-dasharray": "6 4", "stroke-linecap": "round",
        }));
      }
    }

    // ════ 6. Daily weigh-in lollipops (shared) — faint stem to trend + dot ════
    // Trend value at each date for the stem anchor.
    const trendByDate = {};
    trend.forEach((p) => { if (p.weight_kg != null) trendByDate[p.date] = toU(p.weight_kg); });
    (data.actuals || []).forEach((p) => {
      if (p.weight_kg == null) return;
      const px = xDate(p.date);
      if (px == null) return;
      const wy = y(toU(p.weight_kg));
      const ty = trendByDate[p.date] != null ? y(trendByDate[p.date]) : wy;
      svg.appendChild(_el("line", { x1: px, y1: wy, x2: px, y2: ty, stroke: "rgba(59,130,246,0.30)", "stroke-width": "1" }));
    });
    // dots (C.actual) rendered before the trend path
    (data.actuals || []).forEach((p) => {
      if (p.weight_kg == null) return;
      const px = xDate(p.date);
      if (px == null) return;
      const wy = y(toU(p.weight_kg));
      svg.appendChild(_el("circle", { cx: px, cy: wy, r: isMobile ? "3.5" : "3", fill: C.actual }));
      _activeDots.push({ cx: px, cy: wy, date: p.date, kg: p.weight_kg });
    });

    // ════ 7. Trend line (shared, solid blue) — AFTER dots ════
    const trendPts = [];
    trend.forEach((p, i) => { if (p.weight_kg != null) trendPts.push(xIdx(i) + "," + y(toU(p.weight_kg))); });
    if (trendPts.length >= 2) {
      svg.appendChild(_el("polyline", {
        points: trendPts.join(" "), fill: "none", stroke: C.trend,
        "stroke-width": "2.8", "stroke-linejoin": "round", "stroke-linecap": "round",
      }));
    }

    // ════ 8. Advanced forecast layers: NOW, projection (line only), goal dot ════
    const tm = data.today_marker || {};
    if (advanced) {
      const nowY = tm.trend_kg != null ? y(toU(tm.trend_kg)) : (trendPts.length ? y(toU(trend[n - 1].weight_kg)) : T + _CH / 2);
      // NOW divider — "you are here" on the trend (no axis break; the band is
      // one continuous present zone with the forecast to its right).
      svg.appendChild(_el("line", { x1: nowX, y1: T, x2: nowX, y2: B, stroke: "#1e3a8a", "stroke-width": "1", "stroke-dasharray": "2 2", opacity: "0.5" }));
      const nl = _el("text", { x: nowX - 4, y: T + 11, "text-anchor": "end", "font-size": "10", "font-weight": "800", "letter-spacing": "0.06em", fill: "#1e3a8a" });
      nl.textContent = "NOW";
      svg.appendChild(nl);

      if (goalY != null) {
        // plan continues (fainter) to the goal at the right edge
        if (hasPlan) {
          const lastPlan = planByDate[trendDates[n - 1]];
          if (lastPlan != null) {
            svg.appendChild(_el("line", { x1: nowX, y1: y(lastPlan), x2: R, y2: goalY, stroke: C.plan, "stroke-width": "1.5", "stroke-dasharray": "5 4", opacity: "0.45" }));
          }
        }
        // projection: blue dashed line from NOW to goal — NO filled cone
        svg.appendChild(_el("line", { x1: nowX, y1: nowY, x2: R, y2: goalY, stroke: C.trend, "stroke-width": "2", "stroke-dasharray": "5 4", opacity: "0.8" }));
      }
      // NOW point on the trend
      svg.appendChild(_el("circle", { cx: nowX, cy: nowY, r: "3.5", fill: C.trend }));
      // gap value (today vs plan) available on hover at the NOW point
      if (tm.gap_kg != null) {
        const gapLabel = tm.gap_direction === "behind" ? "+" + Math.abs(tm.gap_kg).toFixed(1) : "−" + Math.abs(tm.gap_kg).toFixed(1);
        const gchip = _el("text", { x: nowX, y: nowY - 8, "text-anchor": "middle", "font-size": "9", "font-weight": "700",
          fill: tm.gap_direction === "behind" ? "#dc2626" : "#16a34a" });
        gchip.textContent = gapLabel + " " + unit;
        // background pill colors kept for parity: ahead #dcfce7 / behind #fee2e2
        const pillBg = tm.gap_direction === "behind" ? "#fee2e2" : "#dcfce7";
        const pad2 = 3;
        const approxW = gchip.textContent.length * 5 + pad2 * 2;
        svg.appendChild(_el("rect", { x: nowX - approxW / 2, y: nowY - 18, width: approxW, height: 13, rx: "3", fill: pillBg, opacity: "0.95" }));
        svg.appendChild(gchip);
      }
      // goal dot (green ring) where the projection meets the goal
      if (goalY != null) {
        svg.appendChild(_el("circle", { cx: R, cy: goalY, r: "6", fill: "#fff", stroke: C.plan, "stroke-width": "2.5" }));
      }
      // milestone hover points (values shown on hover)
      (data.future_milestones || []).forEach((m) => {
        if (m.plan_kg == null) return;
        const mx = R;  // milestones live in the forecast region; expose value on the goal dot area
        _activeDots.push({ cx: mx, cy: goalY != null ? goalY : nowY, date: m.date, kg: m.plan_kg });
      });
      // today marker hover (plan + trend values)
      if (tm.plan_kg != null || tm.trend_kg != null) {
        _activeDots.push({ cx: nowX, cy: nowY, date: tm.date, kg: tm.trend_kg != null ? tm.trend_kg : tm.plan_kg });
      }
    }

    // ════ 9. Goal-zone right-axis markers (shared) ════
    if (goalU != null) {
      const gv = _el("text", { x: R + 6, y: goalY + 4, "text-anchor": "start", "font-size": "12", "font-weight": "700", fill: "#15803d" });
      gv.textContent = goalU.toFixed(1);
      svg.appendChild(gv);
      const ub = _el("text", { x: R + 6, y: bandTop + 3, "text-anchor": "start", "font-size": "9", fill: "#16a34a", opacity: "0.85" });
      ub.textContent = (goalU + TOL).toFixed(1);
      svg.appendChild(ub);
      const lb = _el("text", { x: R + 6, y: bandBot + 3, "text-anchor": "start", "font-size": "9", fill: "#16a34a", opacity: "0.85" });
      lb.textContent = (goalU - TOL).toFixed(1);
      svg.appendChild(lb);
    }

    // ════ 10. X-axis date labels (shared) ════
    // "milestones ↓" cue (advanced) — points the eye to the milestones list
    // in the progress-card below the chart.
    if (advanced && (data.future_milestones || []).length) {
      const ml = _el("text", { x: R, y: B + 24, "text-anchor": "end", "font-size": "10", "font-weight": "700", fill: "#16a34a" });
      ml.textContent = "milestones ↓";
      svg.appendChild(ml);
    }

    _renderXLabels(svg, trendDates, range, xIdx);

    // ════ 11. Tooltip (hover + touch) ════
    svg.addEventListener("mousemove", (ev) => {
      const near = _findNearestDot(svg, ev.clientX, ev.clientY);
      if (near) _showTooltip(svg, ev.clientX, ev.clientY, near.date, near.kg);
      else _hideTooltip();
    });
    svg.addEventListener("mouseleave", () => _hideTooltip());
    svg.addEventListener(
      "touchstart",
      (ev) => {
        const t = ev.touches[0];
        if (!t) return;
        const near = _findNearestDot(svg, t.clientX, t.clientY);
        if (near) _showTooltip(svg, t.clientX, t.clientY, near.date, near.kg);
      },
      { passive: true },
    );
    svg.addEventListener(
      "touchmove",
      (ev) => {
        const t = ev.touches[0];
        if (!t) return;
        const near = _findNearestDot(svg, t.clientX, t.clientY);
        if (near) _showTooltip(svg, t.clientX, t.clientY, near.date, near.kg);
      },
      { passive: true },
    );
    svg.addEventListener("touchend", () => _hideTooltip());
  }

  return { render: render, setMode: setMode, getMode: getMode };
})();
