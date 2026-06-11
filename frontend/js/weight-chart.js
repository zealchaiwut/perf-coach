'use strict';

const WeightChart = (() => {
  const NS  = 'http://www.w3.org/2000/svg';
  const VW  = 900;
  const VH  = 280;
  const PAD = { top: 18, right: 16, bottom: 30, left: 50 };
  const CW  = VW - PAD.left - PAD.right;  // 834
  const CH  = VH - PAD.top  - PAD.bottom; // 232

  // Zone layout constants (with active target)
  const MAIN_W_WITH_TARGET = Math.round(CW * 0.65); // ~542
  const FUTURE_W           = Math.round(CW * 0.30); // ~250
  const BREAK_W            = CW - MAIN_W_WITH_TARGET - FUTURE_W;

  const MAIN_L   = PAD.left;
  const BREAK_L  = MAIN_L + MAIN_W_WITH_TARGET;
  const BREAK_R  = BREAK_L + BREAK_W;
  const FUTURE_L = BREAK_R;
  const FUTURE_R = PAD.left + CW;

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
    trendDates.forEach((date, idx) => {
      const d = new Date(date + 'T00:00:00');
      let show = false;
      if (range === '7d')        show = idx % 2 === 0 || idx === n - 1;
      else if (range === '30d')  show = d.getDate() % 7 === 1 || idx === 0 || idx === n - 1;
      else if (range === '90d')  show = d.getDate() === 1 || idx === 0 || idx === n - 1;
      else                        show = d.getDate() === 1 || idx === n - 1;
      if (!show) return;

      const px = xFn(idx, n);
      const lbl = (range === '7d' || range === '30d')
        ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });

      const txt = _el('text', {
        x: px, y: PAD.top + CH + 14,
        'text-anchor': 'middle', 'font-size': '12', fill: '#9ca3af',
      });
      txt.textContent = lbl;
      svg.appendChild(txt);
    });
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

    // Short ranges (7d, 30d) and small viewports suppress the future zone
    const isShortRange    = (range === '7d' || range === '30d');
    const isSmallViewport = window.innerWidth < 640;
    const hasFutureZone   = hasTarget && hasFuture && !isShortRange && !isSmallViewport;

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

    // X scale — main zone stretches full width when no future zone
    const mainR    = hasFutureZone ? BREAK_L : (PAD.left + CW);
    const curMainW = mainR - MAIN_L;

    const trendDates = (data.trend || []).map(p => p.date);
    const n = trendDates.length;

    function xIdx(idx) {
      return MAIN_L + (n > 1 ? (idx / (n - 1)) * curMainW : 0);
    }
    function xDate(dateStr) {
      const idx = trendDates.indexOf(dateStr);
      return idx < 0 ? null : xIdx(idx);
    }
    function xDateFn(idx) {
      return xIdx(idx);
    }

    const gridRight = hasFutureZone ? FUTURE_R : (PAD.left + CW);

    // ── 1. Future tint ──────────────────────────────────────────────────
    if (hasFutureZone) {
      svg.appendChild(_el('rect', {
        x: FUTURE_L, y: PAD.top,
        width: FUTURE_W, height: CH,
        fill: C.future_bg,
      }));
    }

    // ── 2. Gridlines (every 2 kg) ───────────────────────────────────────
    for (let kg = Math.ceil(yMin / 2) * 2; kg <= yMax; kg += 2) {
      const gy = y(kg);
      svg.appendChild(_el('line', {
        x1: MAIN_L, y1: gy, x2: gridRight, y2: gy,
        stroke: C.grid, 'stroke-width': '0.75',
      }));
      const lbl = _el('text', {
        x: MAIN_L - 5, y: gy,
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
        x1: MAIN_L, y1: tgy, x2: gridRight, y2: tgy,
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
      if (todayX == null) todayX = mainR - 4;
    }
    // When the today marker sits near the right edge, the "plan"/"you" labels
    // and the gap chip would overflow the viewBox — flip them to the left side.
    const labelLeft = todayX != null && todayX > VW - 92;

    if (tm && tm.plan_kg != null && todayX != null) {
      planDotY = y(tm.plan_kg);
      svg.appendChild(_el('circle', {
        cx: todayX, cy: planDotY, r: '5',
        fill: '#fff', stroke: C.plan, 'stroke-width': '2',
      }));
      const planLbl = _el('text', {
        x: labelLeft ? todayX - 9 : todayX + 8, y: planDotY - 4,
        'text-anchor': labelLeft ? 'end' : 'start',
        'font-size': '13', fill: C.plan, 'font-weight': '600',
      });
      planLbl.textContent = `plan ${tm.plan_kg.toFixed(1)} kg`;
      svg.appendChild(planLbl);
    }

    // ── 8. Blue highlighted dot + "you X kg" label ─────────────────────
    if (tm && tm.trend_kg != null && todayX != null) {
      trendDotY = y(tm.trend_kg);
      svg.appendChild(_el('circle', {
        cx: todayX, cy: trendDotY, r: '5',
        fill: C.trend, stroke: '#fff', 'stroke-width': '1.5',
      }));
      const youLbl = _el('text', {
        x: labelLeft ? todayX - 9 : todayX + 8, y: trendDotY - 4,
        'text-anchor': labelLeft ? 'end' : 'start',
        'font-size': '13', fill: C.trend, 'font-weight': '600',
      });
      youLbl.textContent = `you ${tm.trend_kg.toFixed(1)} kg`;
      svg.appendChild(youLbl);
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

      const gapText = tm.gap_kg != null
        ? `${tm.gap_kg >= 0 ? '+' : ''}${tm.gap_kg.toFixed(1)} kg`
        : '';
      const chipW = 66, chipH = 20, chipRx = 10;
      const chipY = botY + 8;
      // Keep the chip inside the plot: when near the right edge, end it at the
      // marker instead of centring (which would overflow the viewBox).
      const chipCx = labelLeft ? (todayX - chipW / 2 - 2) : todayX;
      const chipX  = chipCx - chipW / 2;

      svg.appendChild(_el('rect', {
        x: chipX, y: chipY, width: chipW, height: chipH, rx: chipRx,
        fill: gapBg,
      }));
      const chipTxt = _el('text', {
        x: chipCx, y: chipY + chipH / 2,
        'text-anchor': 'middle', 'dominant-baseline': 'middle',
        'font-size': '13', fill: gapColor, 'font-weight': '700',
      });
      chipTxt.textContent = gapText;
      svg.appendChild(chipTxt);
    }

    // ── Axis-break glyph (two slanted ticks) ───────────────────────────
    if (hasFutureZone) {
      const bx   = (BREAK_L + BREAK_R) / 2;
      const bMid = PAD.top + CH / 2;
      const tickH = 10;
      const rad   = 22 * Math.PI / 180;
      const dx    = Math.sin(rad) * tickH;
      const dy    = Math.cos(rad) * tickH;

      [-12, 12].forEach(offset => {
        const my = bMid + offset;
        svg.appendChild(_el('line', {
          x1: bx - dx, y1: my - dy,
          x2: bx + dx, y2: my + dy,
          stroke: '#9ca3af', 'stroke-width': '1.5', 'stroke-linecap': 'round',
        }));
      });
    }

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

        const kgT = _el('text', {
          x: mx, y: my + 17,
          'text-anchor': 'middle', 'font-size': '13', fill: C.plan, 'font-weight': '600',
        });
        kgT.textContent = `${m.plan_kg.toFixed(1)} kg`;
        svg.appendChild(kgT);

        const dt = new Date(m.date + 'T00:00:00');
        const dtT = _el('text', {
          x: mx, y: my + 29,
          'text-anchor': 'middle', 'font-size': '10', fill: '#9ca3af',
        });
        dtT.textContent = dt.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
        svg.appendChild(dtT);
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
