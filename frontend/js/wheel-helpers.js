/* Shared day-wheel helpers — solid pie-wedges + center hub.
   Used by habits.js (habits page hero) and home-strip-habits.js (home widget).
   Exposed as window.WheelHelpers. */
(function (win) {
  'use strict';

  var WHEEL_COLORS = {
    full:    '#16a34a',  /* done — all daily habits */
    partial: '#d97706',  /* some daily habits */
    zero:    '#e4e8f0',  /* past day, none done → track */
    today:   '#3563d4',  /* current day */
    future:  '#e4e8f0',  /* upcoming */
  };

  var WHEEL_DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

  /* viewBox 148×148 geometry */
  var GEO = {
    cx: 74,
    cy: 74,
    hubR: 26,
    innerR: 29,
    outerR: 68,
    gapPx: 3,
    strokePx: 3,
    letterR: 58,
    slotDeg: 360 / 7,
  };

  function polarToCartesian(cx, cy, r, angleDeg) {
    var rad = (angleDeg - 90) * Math.PI / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  /* Legacy thin arc path — kept for tests / backward compatibility. */
  function arcPath(cx, cy, r, startDeg, endDeg) {
    var s = polarToCartesian(cx, cy, r, startDeg);
    var e = polarToCartesian(cx, cy, r, endDeg);
    var large = (endDeg - startDeg) > 180 ? 1 : 0;
    return 'M ' + s.x.toFixed(3) + ' ' + s.y.toFixed(3) +
           ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' +
           e.x.toFixed(3) + ' ' + e.y.toFixed(3);
  }

  /* Solid pie-wedge from inner radius ri to outer radius ro (degrees, clockwise from top). */
  function wedgePath(cx, cy, ri, ro, startDeg, endDeg) {
    var span = endDeg - startDeg;
    var large = span > 180 ? 1 : 0;
    var pIn0  = polarToCartesian(cx, cy, ri, startDeg);
    var pOut0 = polarToCartesian(cx, cy, ro, startDeg);
    var pOut1 = polarToCartesian(cx, cy, ro, endDeg);
    var pIn1  = polarToCartesian(cx, cy, ri, endDeg);
    return 'M ' + pIn0.x.toFixed(3) + ' ' + pIn0.y.toFixed(3) +
           ' L ' + pOut0.x.toFixed(3) + ' ' + pOut0.y.toFixed(3) +
           ' A ' + ro + ' ' + ro + ' 0 ' + large + ' 1 ' + pOut1.x.toFixed(3) + ' ' + pOut1.y.toFixed(3) +
           ' L ' + pIn1.x.toFixed(3) + ' ' + pIn1.y.toFixed(3) +
           ' A ' + ri + ' ' + ri + ' 0 ' + large + ' 0 ' + pIn0.x.toFixed(3) + ' ' + pIn0.y.toFixed(3) +
           ' Z';
  }

  function gapDeg(geo) {
    var midR = (geo.innerR + geo.outerR) / 2;
    return (geo.gapPx / midR) * (180 / Math.PI);
  }

  function wedgeFill(state) {
    return WHEEL_COLORS[state] || WHEEL_COLORS.zero;
  }

  function wedgeLetterFill(state) {
    if (state === 'future' || state === 'zero') return '#8b95ad';
    return '#ffffff';
  }

  function wedgeLetterWeight(state) {
    return state === 'today' ? '700' : '600';
  }

  function countFullDays(dayScores) {
    var n = 0;
    (dayScores || []).forEach(function (ds) {
      if (ds.of > 0 && ds.done === ds.of) n += 1;
    });
    return n;
  }

  function habitIconHTML(icon, color, size) {
    var bg = color || '#9ca3af';
    var s = size || 26;
    var fs = Math.round(s * 0.5);
    if (icon) {
      return '<span class="habit-icon-chip" style="background:' + bg +
             ';width:' + s + 'px;height:' + s + 'px;font-size:' + fs +
             'px"><i class="ti ' + icon + '" aria-hidden="true"></i></span>';
    }
    return '<span class="habit-icon-chip" style="background:' + bg +
           ';width:' + s + 'px;height:' + s + 'px;font-size:' +
           Math.round(s * 0.45) + 'px;font-weight:700">?</span>';
  }

  function _wedgeAngles(index, geo) {
    var g = gapDeg(geo);
    var wedgeSpan = geo.slotDeg - g;
    var start = -90 + index * geo.slotDeg + g / 2;
    var end = start + wedgeSpan;
    var center = start + wedgeSpan / 2;
    return { start: start, end: end, center: center };
  }

  function _appendWheelParts(parts, wheel, geo, opts) {
    var NS = 'http://www.w3.org/2000/svg';
    opts = opts || {};

    parts.push('<circle cx="' + geo.cx + '" cy="' + geo.cy + '" r="' + geo.hubR +
      '" fill="#ffffff" stroke="#ffffff" stroke-width="1"/>');

    (wheel || []).forEach(function (seg, i) {
      var ang = _wedgeAngles(i, geo);
      var fill = wedgeFill(seg.state);
      parts.push('<path d="' + wedgePath(geo.cx, geo.cy, geo.innerR, geo.outerR, ang.start, ang.end) + '"' +
        ' fill="' + fill + '" stroke="#ffffff" stroke-width="' + geo.strokePx + '" stroke-linejoin="round"/>');

      var lpos = polarToCartesian(geo.cx, geo.cy, geo.letterR, ang.center);
      parts.push('<text x="' + lpos.x.toFixed(2) + '" y="' + lpos.y.toFixed(2) + '"' +
        ' text-anchor="middle" dominant-baseline="central"' +
        ' font-size="9" font-family="Inter Tight,system-ui,sans-serif"' +
        ' font-weight="' + wedgeLetterWeight(seg.state) + '"' +
        ' fill="' + wedgeLetterFill(seg.state) + '">' +
        WHEEL_DAY_LETTERS[i] + '</text>');
    });

    if (opts.embedCenterText) {
      var pct = opts.pctElapsed != null ? Math.round(opts.pctElapsed) + '%' : '—';
      parts.push('<text x="' + geo.cx + '" y="' + (geo.cy - (opts.fullDays != null ? 3 : 0)) + '"' +
        ' text-anchor="middle" dominant-baseline="central"' +
        ' font-size="15" font-weight="700" font-family="JetBrains Mono,monospace"' +
        ' fill="#0b1530" class="hw-wheel-pct">' + pct + '</text>');
      if (opts.fullDays != null) {
        parts.push('<text x="' + geo.cx + '" y="' + (geo.cy + 11) + '"' +
          ' text-anchor="middle" dominant-baseline="central"' +
          ' font-size="6.5" font-weight="700" font-family="Inter Tight,system-ui,sans-serif"' +
          ' letter-spacing="0.08em" fill="#8b95ad" class="hw-wheel-days">' +
          opts.fullDays + ' OF 7 DAYS</text>');
      }
    }
  }

  /* Build wheel SVG HTML string (home widget). */
  function buildWheelSvg(wheel, pctElapsed, extra) {
    extra = extra || {};
    var svgClass = extra.svgClass || 'hw-wheel-svg';
    var parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 148 148" class="' +
      svgClass + '" aria-hidden="true">'];
    _appendWheelParts(parts, wheel, GEO, {
      embedCenterText: true,
      pctElapsed: pctElapsed,
      fullDays: extra.fullDays,
    });
    parts.push('</svg>');
    return parts.join('');
  }

  /* Populate an existing <svg> element (habits page hero). */
  function renderWheelDom(svgEl, wheel) {
    if (!svgEl) return;
    var NS = 'http://www.w3.org/2000/svg';

    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    var hub = document.createElementNS(NS, 'circle');
    hub.setAttribute('cx', String(GEO.cx));
    hub.setAttribute('cy', String(GEO.cy));
    hub.setAttribute('r', String(GEO.hubR));
    hub.setAttribute('fill', '#ffffff');
    svgEl.appendChild(hub);

    (wheel || []).forEach(function (seg, i) {
      var ang = _wedgeAngles(i, GEO);
      var path = document.createElementNS(NS, 'path');
      path.setAttribute('d', wedgePath(GEO.cx, GEO.cy, GEO.innerR, GEO.outerR, ang.start, ang.end));
      path.setAttribute('fill', wedgeFill(seg.state));
      path.setAttribute('stroke', '#ffffff');
      path.setAttribute('stroke-width', String(GEO.strokePx));
      path.setAttribute('stroke-linejoin', 'round');
      svgEl.appendChild(path);

      var lpos = polarToCartesian(GEO.cx, GEO.cy, GEO.letterR, ang.center);
      var txt = document.createElementNS(NS, 'text');
      txt.setAttribute('x', lpos.x.toFixed(2));
      txt.setAttribute('y', lpos.y.toFixed(2));
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('dominant-baseline', 'central');
      txt.setAttribute('font-size', '9');
      txt.setAttribute('font-family', 'Inter Tight, system-ui, sans-serif');
      txt.setAttribute('font-weight', wedgeLetterWeight(seg.state));
      txt.setAttribute('fill', wedgeLetterFill(seg.state));
      txt.textContent = WHEEL_DAY_LETTERS[i];
      svgEl.appendChild(txt);
    });
  }

  win.WheelHelpers = {
    WHEEL_COLORS:      WHEEL_COLORS,
    WHEEL_DAY_LETTERS: WHEEL_DAY_LETTERS,
    GEO:               GEO,
    polarToCartesian:  polarToCartesian,
    arcPath:           arcPath,
    wedgePath:         wedgePath,
    wedgeFill:         wedgeFill,
    countFullDays:     countFullDays,
    habitIconHTML:     habitIconHTML,
    buildWheelSvg:     buildWheelSvg,
    renderWheelDom:    renderWheelDom,
  };
})(window);
