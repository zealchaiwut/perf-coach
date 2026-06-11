'use strict';

const WeightChart = (() => {
  const NS  = 'http://www.w3.org/2000/svg';
  const VW  = 900;
  const VH  = 280;
  const PAD = { top: 18, right: 16, bottom: 30, left: 50 };
  const CW  = VW - PAD.left - PAD.right;  // 834
  const CH  = VH - PAD.top  - PAD.bottom; // 232

  // Zone layout: [past 20%][current 60%][future 20%] when a target exists.
  // Without a target the current range fills the full width. Thin separators
  // divide the zones.
  const PAST_W   = Math.round(CW * 0.20);
  const FUTURE_W = Math.round(CW * 0.20);
  const CUR_W3   = CW - PAST_W - FUTURE_W;   // current-zone width in 3-zone mode

  const PAST_L   = PAD.left;
  const PAST_R   = PAST_L + PAST_W;
  const CUR_L3   = PAST_R;                    // current-zone left in 3-zone mode
  const CUR_R3   = CUR_L3 + CUR_W3;
  const FUTURE_L = CUR_R3;
  const FUTURE_R = PAD.left + CW;
  const C_PAST_LINE = '#cbd1da';             // thin grey past line
  const C_SEP       = '#e5e7eb';             // zone separators

  const C = {
    actual:       '#9ca3af',
    trend:        '#2563eb',
    plan:         '#16a34a',
    grid:         '#e5e7eb',
    future_bg:    '#f3f7ff',
    gap_behind:   '#dc2626',
    gap_ahead:    '#16a34a',
    gap_bg_behind:'#fee2e2',
    gap_bg_ahead: '#dcfce7',
  };

  let _tooltip   = null;
  let _activeDots = [];

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
    return PAD.top + CH - ((val - yMin) / (yMax - yMin)) * CH;
  }

  // ── Y bounds from API data ─────────────────────────────────────────────

  function _computeYBounds(data) {
    const vals = [];
    (data.actuals || []).forEach(p => vals.push(p.weight_kg));
    (data.trend   || []).forEach(p => { if (p.weight_kg != null) vals.push(p.weight_kg); });
    if (data.today_marker) {
      if (data.today_marker.plan_kg  != null) vals.push(data.today_marker.plan_kg);
      if (data.today_marker.trend_kg != null) vals.push(data.today_marker.trend_kg);
    }
    if (data.target && data.target.target_weight_kg != null) {
      vals.push(data.target.target_weight_kg);
    }
    if (!vals.length) return { yMin: 50, yMax: 100 };

    const lo     = Math.min(...vals);
    const hi     = Math.max(...vals);
    const goalKg = (data.target && data.target.target_weight_kg != null)
      ? data.target.target_weight_kg
      : lo;

    return {
      yMin: Math.floor(Math.min(goalKg, lo) - 1),
      yMax: Math.ceil(hi + 1),
    };
  }

  // ── Tooltip ────────────────────────────────────────────────────────────

  function _initTooltip(container) {
    if (_tooltip && container.contains(_tooltip)) return;
    _tooltip = document.createElement('div');
    _tooltip.className = 'wc-tooltip';
    Object.assign(_tooltip.style, {
      position: 'absolute', pointerEvents: 'none', display: 'none',
      background: '#1a1a1a', color: '#fff',
      padding: '5px 9px', borderRadius: '5px',
      fontSize: '0.8125rem', whiteSpace: 'nowrap',
      zIndex: '10', boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
    });
    container.appendChild(_tooltip);
  }

  function _showTooltip(svgEl, clientX, clientY, date, kg) {
    if (!_tooltip) return;
    const rect = svgEl.getBoundingClientRect();
    const x = clientX - rect.left + 14;
    const y = Math.max(0, clientY - rect.top - 40);
    _tooltip.style.left = x + 'px';
    _tooltip.style.top  = y + 'px';
    const d = new Date(date + 'T00:00:00');
    const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    _tooltip.textContent = `${label}  ·  ${kg.toFixed(1)} kg`;
    _tooltip.style.display = 'block';
  }

  function _hideTooltip() {
    if (_tooltip) _tooltip.style.display = 'none';
  }

  function _findNearestDot(svgEl, clientX, clientY) {
    const rect   = svgEl.getBoundingClientRect();
    const scaleX = VW / (rect.width  || 1);
    const scaleY = VH / (rect.height || 1);
    const sx = (clientX - rect.left) * scaleX;
    const sy = (clientY - rect.top)  * scaleY;
    let best = null, bestDist = Infinity;
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
    const longRange = (range === '90d' || range === '6m' || range === '1y' || range === 'all');
    const seen = new Set();
    for (let t = 0; t < TICKS; t++) {
      const idx = TICKS === 1 ? 0 : Math.round((t * (n - 1)) / (TICKS - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      const d  = new Date(trendDates[idx] + 'T00:00:00');
      const px = xFn(idx, n);
      const line1 = longRange
        ? d.toLocaleDateString('en-US', { month: 'short' })
        : d.toLocaleDateString('en-US', { day: 'numeric' });
      const line2 = longRange
        ? d.toLocaleDateString('en-US', { year: '2-digit' })
        : d.toLocaleDateString('en-US', { month: 'short' });
      const t1 = _el('text', { x: px, y: PAD.top + CH + 13, 'text-anchor': 'middle', 'font-size': '11', fill: '#9ca3af' });
      t1.textContent = line1; svg.appendChild(t1);
      const t2 = _el('text', { x: px, y: PAD.top + CH + 25, 'text-anchor': 'middle', 'font-size': '10', fill: '#b0b6c0' });
      t2.textContent = line2; svg.appendChild(t2);
    }
  }

  // ── Main render ────────────────────────────────────────────────────────

  function render(data, range) {
    const container = document.getElementById('weight-chart');
    if (!container) return;

    // Hide loading placeholder
    const loading = document.getElementById('chart-loading');
    if (loading) loading.hidden = true;
    container.hidden = false;

    const hasTarget    = !!(data.plan_series && data.plan_series.length);
    const hasFuture    = !!(data.future_milestones && data.future_milestones.length);

    // Three-zone layout whenever a target exists: [past][current][future].
    const threeZone     = hasTarget;
    const hasFutureZone = threeZone;  // reused by the milestone-rendering branch
    const curL = threeZone ? CUR_L3 : PAD.left;
    const curR = threeZone ? CUR_R3 : (PAD.left + CW - 80);
    const curW = curR - curL;

    // Reset container
    container.innerHTML = '';
    container.style.position = 'relative';
    _initTooltip(container);

    // Build SVG
    const svg = _el('svg', {
      viewBox: '0 0 900 280',
      'aria-label': 'Weight trend chart',
      role: 'img',
    });
    svg.setAttribute('width', '100%');
    container.appendChild(svg);

    _activeDots = [];

    // Y scale
    const { yMin, yMax } = _computeYBounds(data);
    const y = (val) => _yCoord(val, yMin, yMax);

    const trendDates = (data.trend || []).map(p => p.date);
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
    const gridLeft  = threeZone ? PAST_L : curL;

    // ── 1. Zone tints + thin separators ─────────────────────────────────
    if (threeZone) {
      svg.appendChild(_el('rect', {  // past: faint grey wash
        x: PAST_L, y: PAD.top, width: PAST_W, height: CH,
        fill: '#f3f4f6', opacity: '0.7',
      }));
      svg.appendChild(_el('rect', {  // future: faint blue wash
        x: FUTURE_L, y: PAD.top, width: FUTURE_W, height: CH,
        fill: C.future_bg,
      }));
      [PAST_R, CUR_R3].forEach(sx => {
        svg.appendChild(_el('line', {
          x1: sx, y1: PAD.top, x2: sx, y2: PAD.top + CH,
          stroke: C_SEP, 'stroke-width': '1',
        }));
      });
    }

    // ── 2. Gridlines (every 2 kg) ───────────────────────────────────────
    for (let kg = Math.ceil(yMin / 2) * 2; kg <= yMax; kg += 2) {
      const gy = y(kg);
      svg.appendChild(_el('line', {
        x1: gridLeft, y1: gy, x2: gridRight, y2: gy,
        stroke: C.grid, 'stroke-width': '0.75',
      }));
      const lbl = _el('text', {
        x: gridLeft - 5, y: gy,
        'text-anchor': 'end', 'dominant-baseline': 'middle',
        'font-size': '12', fill: '#9ca3af',
      });
      lbl.textContent = String(kg);
      svg.appendChild(lbl);
    }

    // ── 3. Dotted target line (goal weight, full width) ─────────────────
    if (data.target && data.target.target_weight_kg != null) {
      const tgy = y(data.target.target_weight_kg);
      svg.appendChild(_el('line', {
        x1: gridLeft, y1: tgy, x2: gridRight, y2: tgy,
        stroke: C.plan, 'stroke-width': '1',
        'stroke-dasharray': '3 4', opacity: '0.35',
      }));
    }

    // ── 4. Green dashed plan line ───────────────────────────────────────
    if (data.plan_series && data.plan_series.length) {
      const pts = [];
      data.plan_series.forEach(p => {
        const px = xDate(p.date);
        if (px != null) pts.push(`${px},${y(p.plan_kg)}`);
      });
      if (pts.length >= 2) {
        svg.appendChild(_el('polyline', {
          points: pts.join(' '),
          fill: 'none', stroke: C.plan,
          'stroke-width': '1.5', 'stroke-dasharray': '5 3',
        }));
      }
    }

    // ── Past zone: thin grey line through earlier weigh-ins (no dots) ────
    if (threeZone && (data.past_actuals || []).length) {
      const pa = data.past_actuals;
      const t0 = new Date(pa[0].date + 'T00:00:00').getTime();
      const t1 = new Date((data.range && data.range.from ? data.range.from : pa[pa.length - 1].date) + 'T00:00:00').getTime();
      const span = Math.max(1, t1 - t0);
      const xPast = ds => PAST_L + ((new Date(ds + 'T00:00:00').getTime() - t0) / span) * (PAST_W - 4);
      const ppts = pa.map(pt => `${xPast(pt.date)},${y(pt.weight_kg)}`);
      if (ppts.length >= 2) {
        svg.appendChild(_el('polyline', {
          points: ppts.join(' '), fill: 'none',
          stroke: C_PAST_LINE, 'stroke-width': '1.2',
          'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        }));
      }
      // bridge last past point → first present trend point for continuity
      const lastPast = pa[pa.length - 1];
      const firstTrend = (data.trend || []).find(t => t.weight_kg != null);
      if (ppts.length && firstTrend) {
        svg.appendChild(_el('line', {
          x1: xPast(lastPast.date), y1: y(lastPast.weight_kg),
          x2: xIdx(trendDates.indexOf(firstTrend.date)), y2: y(firstTrend.weight_kg),
          stroke: C_PAST_LINE, 'stroke-width': '1.2', 'stroke-dasharray': '2 2',
        }));
      }
    }

    // ── 5. Gray weigh-in dots ───────────────────────────────────────────
    (data.actuals || []).forEach(p => {
      const px = xDate(p.date);
      if (px == null) return;
      const py = y(p.weight_kg);
      svg.appendChild(_el('circle', {
        cx: px, cy: py, r: '3.5', fill: C.actual,
      }));
      _activeDots.push({ cx: px, cy: py, date: p.date, kg: p.weight_kg });
    });

    // ── 6. Blue 7-day trend path (skips null gaps) ──────────────────────
    let trendSeg = [];
    (data.trend || []).forEach((p, idx) => {
      if (p.weight_kg == null) {
        if (trendSeg.length >= 2) {
          svg.appendChild(_el('polyline', {
            points: trendSeg.join(' '),
            fill: 'none', stroke: C.trend, 'stroke-width': '2.8',
            'stroke-linejoin': 'round', 'stroke-linecap': 'round',
          }));
        }
        trendSeg = [];
      } else {
        const px = xIdx(idx);
        trendSeg.push(`${px},${y(p.weight_kg)}`);
        _activeDots.push({ cx: px, cy: y(p.weight_kg), date: p.date, kg: p.weight_kg });
      }
    });
    if (trendSeg.length >= 2) {
      svg.appendChild(_el('polyline', {
        points: trendSeg.join(' '),
        fill: 'none', stroke: C.trend, 'stroke-width': '2.8',
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      }));
    }

    // ── 7. Green-stroked white plan dot + "plan X kg" label ────────────
    const tm = data.today_marker;
    let todayX = null, planDotY = null, trendDotY = null;

    if (tm && tm.date) {
      todayX = xDate(tm.date);
      if (todayX == null) todayX = curR - 4;
    }
    // When the today marker sits near the right edge, the "plan"/"you" labels
    // and the gap chip would overflow the viewBox — flip them to the left side.
    const labelLeft = todayX != null && (threeZone || todayX > VW - 92);

    if (tm && tm.plan_kg != null && todayX != null) {
      planDotY = y(tm.plan_kg);
      svg.appendChild(_el('circle', {
        cx: todayX, cy: planDotY, r: '5',
        fill: '#fff', stroke: C.plan, 'stroke-width': '2',
      }));
      // Value shown on hover (label hidden to reduce clutter)
      _activeDots.push({ cx: todayX, cy: planDotY, date: tm.date, kg: tm.plan_kg });
    }

    // ── 8. Blue highlighted dot + "you X kg" label ─────────────────────
    if (tm && tm.trend_kg != null && todayX != null) {
      trendDotY = y(tm.trend_kg);
      svg.appendChild(_el('circle', {
        cx: todayX, cy: trendDotY, r: '5',
        fill: C.trend, stroke: '#fff', 'stroke-width': '1.5',
      }));
      _activeDots.push({ cx: todayX, cy: trendDotY, date: tm.date, kg: tm.trend_kg });
    }

    // ── 9. Red/green dashed vertical gap line + rounded gap chip ───────
    const gapDir = tm ? tm.gap_direction : null;
    if (gapDir && gapDir !== 'no_data' && todayX != null &&
        planDotY != null && trendDotY != null) {
      const isAhead  = gapDir === 'ahead';
      const gapColor = isAhead ? C.gap_ahead   : C.gap_behind;
      const gapBg    = isAhead ? C.gap_bg_ahead : C.gap_bg_behind;
      const topY     = Math.min(planDotY, trendDotY);
      const botY     = Math.max(planDotY, trendDotY);

      svg.appendChild(_el('line', {
        x1: todayX, y1: topY + 5,
        x2: todayX, y2: botY - 5,
        stroke: gapColor, 'stroke-width': '1.5',
        'stroke-dasharray': '3 2',
      }));

      // Gap value (vs plan) shown on hover over the today markers; the chip
      // label is hidden to reduce clutter. The dashed gap line stays as a cue.
      void gapBg;
    }

    // (Zone boundaries are drawn as thin separators above; no axis-break glyph.)

    // ── Future zone content ─────────────────────────────────────────────
    if (hasFutureZone) {
      // "MILESTONES AHEAD" tag
      const tagW = 96, tagH = 16;
      const tagY = PAD.top + 6;
      const tagX = FUTURE_L + (FUTURE_W - tagW) / 2;
      svg.appendChild(_el('rect', {
        x: tagX, y: tagY, width: tagW, height: tagH, rx: '4',
        fill: '#dbeafe',
      }));
      const tagT = _el('text', {
        x: FUTURE_L + FUTURE_W / 2, y: tagY + tagH / 2,
        'text-anchor': 'middle', 'dominant-baseline': 'middle',
        'font-size': '8', fill: '#1d4ed8', 'font-weight': '700',
      });
      tagT.textContent = 'MILESTONES AHEAD';
      svg.appendChild(tagT);

      // Milestone markers (evenly spaced x-positions)
      const milestones = data.future_milestones;
      const mc = milestones.length;

      // Green dotted line: today's plan point → each future milestone
      const fpts = [];
      const tmPlan = data.today_marker ? data.today_marker.plan_kg : null;
      if (tmPlan != null) fpts.push(`${curR},${y(tmPlan)}`);
      milestones.forEach((m, i) => {
        fpts.push(`${FUTURE_L + ((i + 1) / (mc + 1)) * FUTURE_W},${y(m.plan_kg)}`);
      });
      if (fpts.length >= 2) {
        svg.appendChild(_el('polyline', {
          points: fpts.join(' '), fill: 'none', stroke: C.plan,
          'stroke-width': '1.5', 'stroke-dasharray': '2 3',
        }));
      }

      milestones.forEach((m, i) => {
        const mx = FUTURE_L + ((i + 1) / (mc + 1)) * FUTURE_W;
        const my = y(m.plan_kg);
        const isGoal = m.kind === 'goal';

        if (isGoal) {
          // Solid green circle for goal
          svg.appendChild(_el('circle', {
            cx: mx, cy: my, r: '6',
            fill: C.plan, stroke: '#fff', 'stroke-width': '1.5',
          }));
        } else {
          // White-filled green diamond for intermediate milestone
          const s = 6;
          svg.appendChild(_el('polygon', {
            points: `${mx},${my - s} ${mx + s},${my} ${mx},${my + s} ${mx - s},${my}`,
            fill: '#fff', stroke: C.plan, 'stroke-width': '2',
          }));
        }

        // Milestone value/date shown on hover (labels hidden to reduce clutter)
        _activeDots.push({ cx: mx, cy: my, date: m.date, kg: m.plan_kg });
      });
    }

    // ── "milestones ↓" link (shown when future zone is suppressed but target exists) ──
    if (hasTarget && hasFuture && !hasFutureZone) {
      const link = document.createElement('a');
      link.href = '#progress-card';
      link.className = 'wc-milestones-link';
      link.textContent = 'milestones ↓';
      Object.assign(link.style, {
        display: 'block',
        textAlign: 'right',
        fontSize: '12px',
        color: '#16a34a',
        textDecoration: 'none',
        marginTop: '4px',
        paddingRight: '4px',
      });
      container.appendChild(link);
    }

    // ── X-axis labels ───────────────────────────────────────────────────
    _renderXLabels(svg, trendDates, range, xDateFn);

    // ── Tooltip events (mouse + touch) ──────────────────────────────────
    svg.addEventListener('mousemove', ev => {
      const dot = _findNearestDot(svg, ev.clientX, ev.clientY);
      if (dot) _showTooltip(svg, ev.clientX, ev.clientY, dot.date, dot.kg);
      else _hideTooltip();
    });
    svg.addEventListener('mouseleave', () => _hideTooltip());
    svg.addEventListener('touchmove', ev => {
      if (ev.touches.length) {
        const t = ev.touches[0];
        const dot = _findNearestDot(svg, t.clientX, t.clientY);
        if (dot) _showTooltip(svg, t.clientX, t.clientY, dot.date, dot.kg);
      }
    }, { passive: true });
    svg.addEventListener('touchend', () => _hideTooltip());
  }

  return { render };
})();
