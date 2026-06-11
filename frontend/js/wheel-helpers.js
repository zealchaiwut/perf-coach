/* Shared wheel helpers — used by habits.js (habits page) and
   home-strip-habits.js (home page habits widget).
   Exposed as window.WheelHelpers to avoid re-authoring the arc math. */
(function (win) {
  'use strict';

  var WHEEL_COLORS = {
    full:    '#16a34a',
    partial: '#f59e0b',
    zero:    '#9ca3af',
    today:   '#2563eb',
    future:  '#d1d9e9',
  };

  var WHEEL_DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

  function polarToCartesian(cx, cy, r, angleDeg) {
    var rad = (angleDeg - 90) * Math.PI / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function arcPath(cx, cy, r, startDeg, endDeg) {
    var s = polarToCartesian(cx, cy, r, startDeg);
    var e = polarToCartesian(cx, cy, r, endDeg);
    var large = (endDeg - startDeg) > 180 ? 1 : 0;
    return 'M ' + s.x.toFixed(3) + ' ' + s.y.toFixed(3) +
           ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' +
           e.x.toFixed(3) + ' ' + e.y.toFixed(3);
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

  /* Build a 148×148 SVG wheel from a wheel array.
     Returns SVG element HTML string. */
  function buildWheelSvg(wheel, pctElapsed) {
    var CX = 74, CY = 74, R = 52, SW = 11, ARC_DEG = 44, SLOT_DEG = 360 / 7, LETTER_R = 63;
    var NS = 'http://www.w3.org/2000/svg';
    var parts = [];

    parts.push('<svg xmlns="' + NS + '" viewBox="0 0 148 148" class="hw-wheel-svg" aria-hidden="true">');

    (wheel || []).forEach(function (seg, i) {
      var slotCenter = -90 + i * SLOT_DEG;
      var arcStart   = slotCenter - ARC_DEG / 2;
      var arcEnd     = slotCenter + ARC_DEG / 2;
      var isToday    = seg.state === 'today';
      var stroke     = WHEEL_COLORS[seg.state] || WHEEL_COLORS.zero;

      parts.push('<path d="' + arcPath(CX, CY, R, arcStart, arcEnd) + '"' +
        ' fill="none" stroke="' + stroke + '" stroke-width="' + SW +
        '" stroke-linecap="round"/>');

      var lpos = polarToCartesian(CX, CY, LETTER_R, slotCenter);
      parts.push('<text x="' + lpos.x.toFixed(2) + '" y="' + lpos.y.toFixed(2) + '"' +
        ' text-anchor="middle" dominant-baseline="central"' +
        ' font-size="8" font-family="Inter Tight,system-ui,sans-serif"' +
        ' font-weight="' + (isToday ? '700' : '400') + '"' +
        ' fill="' + (isToday ? '#2563eb' : '#8b95ad') + '">' +
        WHEEL_DAY_LETTERS[i] + '</text>');
    });

    var pct = pctElapsed != null ? Math.round(pctElapsed) + '%' : '—';
    parts.push('<text x="74" y="74" text-anchor="middle" dominant-baseline="central"' +
      ' font-size="15" font-weight="700" font-family="Inter Tight,system-ui,sans-serif"' +
      ' fill="#0b1530" class="hw-wheel-pct">' + pct + '</text>');

    parts.push('</svg>');
    return parts.join('');
  }

  win.WheelHelpers = {
    WHEEL_COLORS:      WHEEL_COLORS,
    WHEEL_DAY_LETTERS: WHEEL_DAY_LETTERS,
    polarToCartesian:  polarToCartesian,
    arcPath:           arcPath,
    habitIconHTML:     habitIconHTML,
    buildWheelSvg:     buildWheelSvg,
  };
})(window);
