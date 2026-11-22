(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };
  var todayISO = window.AppCommon ? window.AppCommon.todayISO : function () { return new Date().toISOString().slice(0, 10); };

  var state = {
    month: null,
    filter: 'all',
    search: '',
    range: '8w',
    listFrom: null,
    listTo: null,
    openWeeks: {},
    runIds: [],
    showAllWeeks: false,
    expandedWeeks: {},
    raceLine: '',
  };

  function readQuery() {
    var q = new URLSearchParams(window.location.search);
    state.month = q.get('month') || todayISO().slice(0, 7);
    state.filter = q.get('filter') || 'all';
    state.search = q.get('search') || '';
    state.range = q.get('range') || '8w';
  }

  function writeQuery() {
    var q = new URLSearchParams();
    q.set('month', state.month);
    if (state.filter !== 'all') q.set('filter', state.filter);
    if (state.search) q.set('search', state.search);
    if (state.range !== '8w') q.set('range', state.range);
    var url = window.location.pathname + '?' + q.toString();
    window.history.replaceState({}, '', url);
  }

  function sectionLoading(el, msg) {
    el.innerHTML = '<div class="rv-skeleton-stack" role="status" aria-busy="true"><span class="rv-skeleton rv-skeleton--bar"></span>' +
      '<span class="rv-skeleton rv-skeleton--line"></span><span class="rv-skeleton rv-skeleton--line short"></span>' +
      '<span class="rv-subtitle">' + esc(msg || 'Loading…') + '</span></div>';
  }

  function sectionError(el, msg) {
    el.innerHTML = '<p class="rv-section-state" role="alert">' + esc(msg) + '</p>';
  }

  function monthShift(delta) {
    var parts = state.month.split('-');
    var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1 + delta, 1);
    state.month = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    writeQuery();
    loadMonth();
  }

  function sessionCardClass(kind, status) {
    if (status === 'missed') return 'rv-session--missed';
    if (status === 'planned') {
      if (kind === 'mobility' || kind === 'plyo') return 'rv-month-card--planned-mobility';
      return 'rv-month-card--planned';
    }
    if (kind === 'rest') return 'rv-session--rest';
    if (kind === 'race') return 'rv-session--race';
    if (kind === 'quality_run') return 'rv-session--quality';
    if (kind === 'run') return 'rv-session--run';
    return 'rv-session--support';
  }

  function whoChipHtml(kind, who) {
    var label = (who || String(kind || 'run').replace(/_/g, ' ')).toUpperCase();
    if (label.length > 14) label = label.split(' ')[0];
    var cls = 'rv-chip rv-chip--who';
    if (kind === 'strength' || kind === 'support') cls = 'rv-chip rv-chip--who-support';
    else if (kind === 'quality_run') cls = 'rv-chip rv-chip--who-quality';
    else if (kind === 'race') cls = 'rv-chip rv-chip--who-race';
    else if (kind === 'rest') cls = 'rv-chip rv-chip--outline';
    return '<span class="' + cls + '">' + esc(label) + '</span>';
  }

  function listTypeChip(entry) {
    var t = (entry.type || 'run').toLowerCase();
    if (entry.row_kind === 'missed_plan') return '<span class="rv-chip rv-chip--outline">MISSED</span>';
    if (t.indexOf('strength') >= 0) return '<span class="rv-chip rv-chip--who-support">STRENGTH</span>';
    if (t.indexOf('plyo') >= 0) return '<span class="rv-chip rv-chip--who-support">PLYO</span>';
    if (t.indexOf('mobility') >= 0) return '<span class="rv-chip rv-chip--who-support">MOBILITY</span>';
    if (t.indexOf('race') >= 0) return '<span class="rv-chip rv-chip--who-race">RACE</span>';
    return '<span class="rv-chip rv-chip--who">RUN</span>';
  }

  function renderMonth(data) {
    var body = document.getElementById('v2-month-body');
    var nav = document.getElementById('v2-month-nav');
    if (!body || !nav) return;
    var label = new Date(data.month + '-01').toLocaleString('en', { month: 'long', year: 'numeric' });
    nav.innerHTML =
      '<div class="rv-month-nav-controls">' +
      '<button type="button" class="rv-month-nav-btn" aria-label="Previous month" id="v2-month-prev">‹</button>' +
      '<span class="rv-month-nav-label">' + esc(label) + '</span>' +
      '<button type="button" class="rv-month-nav-btn" aria-label="Next month" id="v2-month-next">›</button>' +
      '<button type="button" class="rv-month-nav-btn rv-month-nav-today" id="v2-month-today">Today</button>' +
      '</div>' +
      '<span class="rv-month-nav-summary">So far: ' +
      Math.round(data.summary.tss_total || 0) + ' TSS · ' + (data.summary.distance_km || 0) + ' km · ' +
      (data.summary.session_count || 0) + ' sessions' +
      (data.summary.plan_kept_label ? ' · plan kept ' + esc(data.summary.plan_kept_label) : '') +
      '</span>';
    document.getElementById('v2-month-prev').onclick = function () { monthShift(-1); };
    document.getElementById('v2-month-next').onclick = function () { monthShift(1); };
    document.getElementById('v2-month-today').onclick = function () {
      state.month = todayISO().slice(0, 7);
      writeQuery();
      loadMonth();
    };

    var html = ['<div class="rv-month-grid" role="grid">'];
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (h) {
      html.push('<div class="rv-month-head">' + h + '</div>');
    });
    html.push('<div class="rv-month-head rv-month-head--week">Week</div>');
    (data.weeks || []).forEach(function (week) {
      week.days.forEach(function (day) {
        var cls = 'rv-month-day';
        if (!day.in_month) cls += ' rv-month-day--out';
        if (day.is_today) cls += ' rv-month-day--today';
        html.push('<div class="' + cls + '" role="gridcell">');
        html.push(
          '<div class="rv-month-daynum">' +
          esc(String(parseInt(day.date.slice(-2), 10))) +
          (day.is_today ? '<span class="rv-month-today-chip">TODAY</span>' : '') +
          '</div>'
        );
        (day.items || []).forEach(function (item) {
          var cardCls = 'rv-month-card rv-session ' + sessionCardClass(item.kind, item.status);
          var isRun = item.kind === 'run' || item.kind === 'quality_run';
          var isStr = item.kind === 'strength' || item.kind === 'support';
          var clickable = item.status === 'done' && item.workout_id && (isRun || isStr);
          if (clickable) cardCls += ' rv-month-card--clickable';
          var meta = [];
          if (item.tss != null) meta.push(Math.round(item.tss) + ' TSS');
          if (item.distance_km != null) meta.push(item.distance_km + ' km');
          if (item.duration_min != null) meta.push(item.duration_min + ' min');
          var who = item.who || String(item.kind || '').replace('_', ' ').toUpperCase();
          var tag = item.status === 'done' ? 'DONE' : '';
          html.push(
            '<h3 class="' + cardCls + '" tabindex="' + (clickable ? '0' : '-1') + '" data-workout-id="' + esc(item.workout_id || '') + '" data-session-kind="' + esc(item.kind || '') + '">' +
            whoChipHtml(item.kind, who) +
            '<span class="rv-month-card-title">' + esc(item.name) + '</span>' +
            (meta.length ? '<div class="rv-month-card-meta">' + esc(meta.join(' · ')) + '</div>' : '') +
            (tag ? '<span class="rv-chip rv-chip--done">' + esc(tag) + '</span>' : '') +
            '</h3>'
          );
        });
        html.push('</div>');
      });
      var r = week.rollup || {};
      var tm = week.target_meta || {};
      var bar = '';
      var cap = '';
      if (tm.bar_pct != null && tm.target_tss != null) {
        var barColor = tm.on_target ? '#6d93e8' : '#b45309';
        bar = '<div class="rv-month-target-bar"><span style="width:' + tm.bar_pct + '%;background:' + barColor + '"></span></div>';
        if (tm.on_target) cap = 'on target · ' + Math.round(tm.target_tss);
        else if (tm.delta > 0) cap = '+' + tm.delta + ' over ' + Math.round(tm.target_tss);
        else cap = tm.delta + ' under ' + Math.round(tm.target_tss);
      } else if (tm.target_tss != null) {
        cap = 'target ' + Math.round(tm.target_tss);
      }
      html.push(
        '<div class="rv-month-week" role="gridcell">' +
        '<strong class="rv-mono" style="font-size:1.1rem">' + Math.round(r.tss_total || 0) + '</strong>' +
        '<span class="rv-subtitle" style="margin:0;font-family:var(--rv-mono)">' + (r.distance_km || 0) + ' km</span>' +
        bar +
        (cap ? '<span class="rv-month-target-cap">' + esc(cap) + '</span>' : '') +
        '</div>'
      );
    });
    html.push(
      '</div><div class="rv-month-legend">' +
      '<span class="rv-key"><i class="rv-swatch rv-swatch--run"></i>Run</span>' +
      '<span class="rv-key"><i class="rv-swatch rv-swatch--quality"></i>Quality run</span>' +
      '<span class="rv-key"><i class="rv-swatch rv-swatch--support"></i>Strength / mobility</span>' +
      '<span class="rv-key"><i class="rv-swatch rv-swatch--race"></i>Race</span>' +
      '<span class="rv-key"><i class="rv-swatch rv-swatch--missed"></i>Missed</span></div>'
    );
    body.innerHTML = html.join('');
    body.querySelectorAll('[data-workout-id]').forEach(function (el) {
      var id = el.getAttribute('data-workout-id');
      if (!id) return;
      function open() {
        var kind = el.getAttribute('data-session-kind') || '';
        if (window.V2StrengthDrawer && window.V2StrengthDrawer.isStrengthType(kind) && window.V2StrengthDrawer.openView) {
          window.V2StrengthDrawer.openView(id);
        } else if (window.V2RunDrawer) {
          window.V2RunDrawer.open(id, state.runIds);
        }
      }
      el.addEventListener('click', open);
      el.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
    });
  }

  function loadMonth() {
    var body = document.getElementById('v2-month-body');
    sectionLoading(body, 'Loading month…');
    fetch('/api/training/month?month=' + encodeURIComponent(state.month))
      .then(function (r) { if (!r.ok) throw new Error('Month failed'); return r.json(); })
      .then(renderMonth)
      .catch(function () { sectionError(body, 'Could not load month board.'); });
  }

  var MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  var WEEKDAYS_SHORT = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

  function isoParts(iso) {
    var p = String(iso || '').slice(0, 10).split('-');
    return { y: parseInt(p[0], 10), m: parseInt(p[1], 10), d: parseInt(p[2], 10) };
  }

  function fmtDayMonth(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso;
    return p.d + ' ' + MONTHS_SHORT[p.m - 1];
  }

  function weekdayIndex(iso) {
    var p = isoParts(iso);
    var t = Date.UTC(p.y, p.m - 1, p.d);
    return new Date(t).getUTCDay();
  }

  function fmtWeekRange(start, end) {
    var a = isoParts(start);
    var b = isoParts(end || start);
    if (!a.m) return start;
    if (a.m === b.m) return a.d + ' – ' + b.d + ' ' + MONTHS_SHORT[a.m - 1];
    return a.d + ' ' + MONTHS_SHORT[a.m - 1] + ' – ' + b.d + ' ' + MONTHS_SHORT[b.m - 1];
  }

  function topRoundRect(x, y, w, h, r, fill) {
    if (h <= 0) return '';
    if (r > h) r = h;
    if (r > w / 2) r = w / 2;
    return '<path d="M' + x + ',' + (y + h) + ' L' + x + ',' + (y + r) +
      ' Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      ' L' + (x + w - r) + ',' + y +
      ' Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) +
      ' L' + (x + w) + ',' + (y + h) + ' Z" fill="' + fill + '"/>';
  }

  function drawChart(weeks) {
    var el = document.getElementById('v2-chart-body');
    if (!el) return;
    if (!weeks.length) {
      sectionError(el, 'No weekly data yet.');
      return;
    }
    if (weeks.length > 9) weeks = weeks.slice(-9);
    var BASE = 190;
    var TOP = 20;
    var PLOT = 170;
    var BAR_W = 56;
    var FIRST_CX = 55;
    var SLOT = 111;
    var maxTss = 1;
    var maxKm = 1;
    weeks.forEach(function (w) {
      var t = (w.tss_run || 0) + (w.tss_strength || 0) + (w.tss_support_other || 0);
      if ((w.planned_tss || 0) > t) t = w.planned_tss;
      if (t > maxTss) maxTss = t;
      if ((w.distance_km || 0) > maxKm) maxKm = w.distance_km;
    });
    function yTss(v) { return BASE - (v / maxTss) * PLOT; }
    function yKm(v) { return BASE - (v / maxKm) * PLOT; }
    function cx(i) { return FIRST_CX + i * SLOT; }

    var currentIdx = -1;
    var lastDoneIdx = -1;
    var peakIdx = 0;
    var peakVal = -1;
    weeks.forEach(function (wk, i) {
      var total = (wk.tss_run || 0) + (wk.tss_strength || 0) + (wk.tss_support_other || 0);
      if (total > peakVal) { peakVal = total; peakIdx = i; }
      if (wk.partial) currentIdx = i;
      if (total > 0 || wk.partial) lastDoneIdx = i;
    });
    if (currentIdx < 0) currentIdx = lastDoneIdx < 0 ? weeks.length - 1 : lastDoneIdx;
    if (lastDoneIdx < 0) lastDoneIdx = currentIdx;

    var parts = ['<svg viewBox="0 0 1000 220" style="width:100%;height:240px;display:block" role="img" aria-label="Weekly training volume">'];
    parts.push('<line x1="0" y1="20" x2="1000" y2="20" stroke="#eef1f7"/>');
    parts.push('<line x1="0" y1="105" x2="1000" y2="105" stroke="#eef1f7"/>');
    parts.push('<line x1="0" y1="190" x2="1000" y2="190" stroke="#dfe5f1"/>');

    var kmPts = [];
    weeks.forEach(function (wk, i) {
      var run = wk.tss_run || 0;
      var lift = (wk.tss_strength || 0) + (wk.tss_support_other || 0);
      var total = run + lift;
      var planned = wk.planned_tss || 0;
      var x = cx(i) - BAR_W / 2;
      var isCur = i === currentIdx;
      var plannedOnly = total <= 0 && planned > 0;
      if (plannedOnly) {
        var ph = Math.max(4, (planned / maxTss) * PLOT);
        parts.push('<rect x="' + x + '" y="' + (BASE - ph) + '" width="' + BAR_W + '" height="' + ph + '" rx="4" fill="#ffffff" stroke="#6d93e8" stroke-width="2" stroke-dasharray="5 4"/>');
      } else if (total <= 0) {
        parts.push('<rect x="' + x + '" y="' + (BASE - 4) + '" width="' + BAR_W + '" height="4" rx="2" fill="#eef1f7"/>');
      } else {
        var runH = (run / maxTss) * PLOT;
        var liftH = (lift / maxTss) * PLOT;
        var fill = isCur ? '#3b6fe0' : '#bfd3f8';
        if (liftH > 0.5) {
          parts.push('<rect x="' + x + '" y="' + (BASE - runH) + '" width="' + BAR_W + '" height="' + runH + '" fill="' + fill + '"/>');
          parts.push(topRoundRect(x, BASE - runH - liftH, BAR_W, liftH, 4, '#c9b6f2'));
        } else {
          parts.push('<rect x="' + x + '" y="' + (BASE - runH) + '" width="' + BAR_W + '" height="' + runH + '" rx="4" fill="' + fill + '"/>');
        }
      }
      kmPts.push({ x: cx(i), y: yKm(wk.distance_km || 0), i: i, total: total, planned: planned, plannedOnly: plannedOnly, isCur: isCur });
    });

    var solid = [];
    weeks.forEach(function (wk, i) {
      if (i <= lastDoneIdx) solid.push(kmPts[i].x + ',' + kmPts[i].y);
    });
    if (solid.length > 1) {
      parts.push('<polyline points="' + solid.join(' ') + '" fill="none" stroke="#d97706" stroke-width="2.5" stroke-linejoin="round"/>');
    } else if (solid.length === 1) {
      parts.push('<polyline points="' + solid[0] + ' ' + solid[0] + '" fill="none" stroke="#d97706" stroke-width="2.5"/>');
    }
    for (var d = lastDoneIdx; d < weeks.length - 1; d++) {
      if (d < 0) continue;
      var a = kmPts[d];
      var b = kmPts[d + 1];
      parts.push('<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" stroke="#d97706" stroke-width="2.5" stroke-dasharray="5 4"/>');
    }

    kmPts.forEach(function (pt) {
      var r = pt.isCur ? 5 : 4;
      parts.push('<circle cx="' + pt.x + '" cy="' + pt.y + '" r="' + r + '" fill="#d97706"/>');
    });

    kmPts.forEach(function (pt, i) {
      if (pt.isCur && pt.total > 0) {
        parts.push('<text x="' + pt.x + '" y="' + (pt.y + 4) + '" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle" font-family="JetBrains Mono, monospace">' + Math.round(pt.total) + '</text>');
      } else if (pt.plannedOnly && pt.planned > 0) {
        parts.push('<text x="' + pt.x + '" y="' + (yTss(pt.planned) - 8) + '" font-size="11" fill="#1f3b8a" text-anchor="middle" font-family="JetBrains Mono, monospace">' + Math.round(pt.planned) + '</text>');
      } else if (i === peakIdx && peakVal > 0 && i !== currentIdx) {
        parts.push('<text x="' + pt.x + '" y="' + (Math.min(yTss(peakVal), pt.y) - 8) + '" font-size="11" fill="#0b1530" text-anchor="middle" font-family="JetBrains Mono, monospace">' + Math.round(peakVal) + '</text>');
      }
    });

    weeks.forEach(function (wk, i) {
      var isCur = i === currentIdx;
      parts.push(
        '<text x="' + cx(i) + '" y="208" font-size="11.5" fill="' + (isCur ? '#0b1530' : '#56627f') + '"' +
        (isCur ? ' font-weight="700"' : '') + ' text-anchor="middle">' + esc(fmtDayMonth(wk.week_start)) + '</text>'
      );
      parts.push(
        '<rect tabindex="0" role="button" aria-label="Week ' + esc(wk.week_start) + '" x="' + (cx(i) - BAR_W / 2) +
        '" y="' + TOP + '" width="' + BAR_W + '" height="' + PLOT + '" fill="transparent" data-week="' + esc(wk.week_start) + '"/>'
      );
    });
    parts.push('</svg>');
    el.innerHTML = parts.join('');
    el.querySelectorAll('[data-week]').forEach(function (node) {
      function jump() {
        var id = 'week-' + node.getAttribute('data-week');
        var target = document.getElementById(id);
        if (target) {
          state.openWeeks[node.getAttribute('data-week')] = true;
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          target.focus();
        }
      }
      node.addEventListener('click', jump);
      node.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); jump(); } });
    });
  }

  function loadChart() {
    var el = document.getElementById('v2-chart-body');
    sectionLoading(el, 'Loading chart…');
    var end = todayISO();
    var fromW = window.AppCommon && window.AppCommon.addDaysISO
      ? window.AppCommon.addDaysISO(end, -7 * 8)
      : end;
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 25000);
    fetch('/api/weekly-rollup?from=' + encodeURIComponent(fromW) + '&to=' + encodeURIComponent(end), { signal: ctrl.signal })
      .then(function (r) { if (!r.ok) throw new Error('chart'); return r.json(); })
      .then(function (data) { clearTimeout(timer); drawChart((data && data.weeks) || []); })
      .catch(function (e) {
        clearTimeout(timer);
        sectionError(el, e && e.name === 'AbortError' ? 'Chart timed out — try again.' : 'Could not load weekly volume.');
      });
  }

  function listRange() {
    var end = todayISO();
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    if (state.range === 'all') {
      return { from: add ? add(end, -365 * 3) : end, to: end };
    }
    return { from: add ? add(end, -7 * 8) : end, to: end };
  }

  function typeMatches(entry) {
    var t = (entry.type || '').toLowerCase();
    if (state.filter === 'all') return true;
    if (state.filter === 'runs') return t.indexOf('run') >= 0;
    if (state.filter === 'strength') return t.indexOf('strength') >= 0 || t.indexOf('lift') >= 0;
    if (state.filter === 'plyo') return t.indexOf('plyo') >= 0;
    if (state.filter === 'mobility') return t.indexOf('mobility') >= 0;
    if (state.filter === 'missed') return entry.row_kind === 'missed_plan';
    return true;
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function fmtHms(sec) {
    if (sec == null || sec === '') return null;
    sec = Math.round(Number(sec));
    if (!isFinite(sec) || sec < 0) return null;
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    return h + ':' + pad2(m) + ':' + pad2(s);
  }

  function fmtMins(sec) {
    if (sec == null || sec === '') return null;
    var n = Math.round(Number(sec) / 60);
    if (!isFinite(n)) return null;
    return n + ' min';
  }

  function fmtPaceSpk(spk) {
    if (!spk) return null;
    var m = Math.floor(spk / 60);
    var s = Math.round(spk % 60);
    return m + ':' + pad2(s) + ' /km';
  }

  function fmtKm(km) {
    if (km == null || km === '') return null;
    var n = Number(km);
    if (!isFinite(n)) return null;
    return n.toFixed(1) + ' km';
  }

  function isLogged(entry) {
    return entry.row_kind !== 'missed_plan' && String(entry.id || '').indexOf('plan:') !== 0;
  }

  function isRunType(entry) {
    return (entry.type || '').toLowerCase().indexOf('run') >= 0;
  }

  function isStrengthType(entry) {
    var t = (entry.type || '').toLowerCase();
    return t.indexOf('strength') >= 0 || t.indexOf('lift') >= 0 || t.indexOf('gym') >= 0;
  }

  function phaseLabel(raw) {
    if (!raw) return '';
    return String(raw).replace(/_/g, '-').replace(/\s+/g, ' ').trim();
  }

  function badgeChips(entry) {
    var chips = [];
    var missed = entry.row_kind === 'missed_plan';
    if (missed) {
      chips.push('<span class="rv-chip rv-chip--missed">PLANNED, NOT DONE</span>');
      return chips.join('');
    }
    if (entry.is_stryd_synced || entry.has_stryd) {
      chips.push('<span class="rv-chip rv-chip--dark">STRYD</span>');
    }
    if (isStrengthType(entry)) {
      chips.push('<span class="rv-chip rv-chip--who-support">STRENGTH</span>');
    }
    if (entry.plan_match) {
      chips.push('<span class="rv-chip rv-chip--good">MATCHED COACH PLAN</span>');
    } else if (entry.id && String(entry.id).indexOf('plan:') !== 0) {
      var unplanned = isStrengthType(entry) && (entry.source || '') === 'manual'
        ? 'UNPLANNED · TYPED AT THE GYM'
        : 'UNPLANNED';
      chips.push('<span class="rv-chip rv-chip--warn">' + unplanned + '</span>');
    }
    if (entry.speed_signal != null) {
      chips.push('<span class="rv-chip rv-chip--warn">HARD EFFORT · SPEED SIGNAL</span>');
    }
    return chips.join('');
  }

  function typeDot(entry) {
    if (entry.row_kind === 'missed_plan') return '<span class="rv-session-dot rv-session-dot--missed" aria-hidden="true"></span>';
    if (isStrengthType(entry) || (entry.type || '').toLowerCase().indexOf('plyo') >= 0 || (entry.type || '').toLowerCase().indexOf('mobility') >= 0) {
      return '<span class="rv-session-dot rv-session-dot--support" aria-hidden="true"></span>';
    }
    return '<span class="rv-session-dot rv-session-dot--run" aria-hidden="true"></span>';
  }

  function sessionMeta(entry) {
    var missed = entry.row_kind === 'missed_plan';
    if (missed) {
      var bits = [];
      if (entry.exercise_count) bits.push(entry.exercise_count + ' exercises');
      if (entry.tss != null) bits.push(Math.round(entry.tss) + ' TSS planned');
      return bits.join(' · ');
    }
    var tpe = (entry.type || '').toLowerCase();
    var strength = isStrengthType(entry) || tpe.indexOf('plyo') >= 0 || tpe.indexOf('mobility') >= 0;
    if (strength) {
      var sbits = [];
      var mins = fmtMins(entry.duration_seconds);
      if (mins) sbits.push(mins);
      if (entry.exercise_count) sbits.push(entry.exercise_count + ' exercises');
      if (entry.set_count) sbits.push(entry.set_count + ' sets');
      return sbits.join(' · ');
    }
    var rbits = [];
    var dur = fmtHms(entry.duration_seconds);
    if (dur) rbits.push(dur);
    var km = fmtKm(entry.distance_km);
    if (km) rbits.push(km);
    var pace = fmtPaceSpk(entry.average_pace_seconds_per_km);
    if (pace) rbits.push(pace);
    if (entry.avg_power) rbits.push(Math.round(entry.avg_power) + ' W');
    if (entry.avg_hr) rbits.push('HR ' + Math.round(entry.avg_hr));
    return rbits.join(' · ');
  }

  function paintSubtitle(sessionCount) {
    var el = document.getElementById('rv-training-subtitle');
    if (!el) return;
    var today = todayISO();
    var p = isoParts(today);
    var line = WEEKDAYS[weekdayIndex(today)] + ', ' + p.d + ' ' + MONTHS_LONG[p.m - 1];
    if (state.raceLine) line += ' · ' + state.raceLine;
    if (sessionCount != null) line += ' · ' + sessionCount + ' total';
    el.textContent = line;
  }

  function loadRaceLine() {
    fetch('/api/races', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (body) {
        var races = (Array.isArray(body) ? body : (body.races || body.items || []))
          .filter(function (race) { return (race.status || 'planned') === 'planned'; });
        if (!races.length) return;
        races.sort(function (a, b) { return (a.race_date || '').localeCompare(b.race_date || ''); });
        var next = races[0];
        state.raceLine = next.name || 'Race';
        paintSubtitle(null);
      })
      .catch(function () { /* keep date only */ });
  }

  function renderSessionRow(entry, highlight) {
    var missed = entry.row_kind === 'missed_plan';
    var tpe = (entry.type || '').toLowerCase();
    var run = isRunType(entry) && !missed;
    var str = !missed && window.V2StrengthDrawer && window.V2StrengthDrawer.isStrengthType(tpe);
    var rowCls = 'rv-session-row';
    if (missed) rowCls += ' rv-session-row--missed';
    if (highlight) rowCls += ' rv-session-row--today';
    if (run || str) rowCls += ' rv-session-row--clickable';
    var day = isoParts(entry.date).d;
    var wd = WEEKDAYS_SHORT[weekdayIndex(entry.date)] || '';
    var meta = sessionMeta(entry);
    var attrs = (run || str)
      ? ' data-run-id="' + esc(entry.id) + '" data-workout-type="' + esc(entry.type || '') + '" tabindex="0" role="button"'
      : '';
    var side;
    if (missed) {
      var pid = (entry.plan_match && entry.plan_match.planned_id) || String(entry.id).replace('plan:', '');
      side =
        '<div class="rv-missed-actions">' +
        '<button type="button" class="rv-btn rv-btn--ghost-amber" data-plan-open="' + esc(pid) + '">Review in Plan</button>' +
        '<button type="button" class="rv-btn rv-btn--ghost-amber" data-plan-skip="' + esc(pid) + '">Skip</button>' +
        '</div><span class="rv-session-tss-block" aria-hidden="true"></span>';
    } else if (str) {
      side =
        '<span class="rv-session-open">Open</span>' +
        '<span class="rv-session-tss-block"><span class="rv-session-tss">' + (entry.tss != null ? Math.round(entry.tss) : '—') + '</span><span class="rv-session-tss-unit">TSS</span></span>';
    } else {
      side =
        (run ? '<div class="rv-list-feel" data-feel-host="' + esc(entry.id) + '" data-feel-val="' + esc(entry.feeling || '') + '"></div>' : '<span></span>') +
        '<span class="rv-session-tss-block"><span class="rv-session-tss">' + (entry.tss != null ? Math.round(entry.tss) : '—') + '</span><span class="rv-session-tss-unit">TSS</span></span>';
    }
    return (
      '<div class="' + rowCls + '"' + attrs + '>' +
      '<span class="rv-session-date"><span class="rv-session-day">' + esc(String(day)) + '</span><span class="rv-session-wd">' + esc(wd) + '</span></span>' +
      typeDot(entry) +
      '<div class="rv-session-main">' +
      '<div class="rv-session-title-row"><strong class="rv-session-title">' + esc(entry.title || 'Session') + '</strong>' + badgeChips(entry) + '</div>' +
      (meta ? '<div class="rv-session-metrics">' + esc(meta) + '</div>' : '') +
      '</div>' + side + '</div>'
    );
  }

  function plannedEmptyCard(entries) {
    var counts = { run: 0, mobility: 0, race: 0, strength: 0, plyo: 0 };
    entries.forEach(function (e) {
      var t = (e.type || '').toLowerCase();
      if (t.indexOf('race') >= 0) counts.race += 1;
      else if (t.indexOf('mobility') >= 0) counts.mobility += 1;
      else if (t.indexOf('plyo') >= 0) counts.plyo += 1;
      else if (t.indexOf('strength') >= 0 || t.indexOf('lift') >= 0) counts.strength += 1;
      else counts.run += 1;
    });
    var chips = [];
    if (counts.run) chips.push('<span class="rv-chip rv-chip--who">' + counts.run + ' RUN</span>');
    if (counts.mobility) chips.push('<span class="rv-chip rv-chip--who-support">' + counts.mobility + ' MOBILITY</span>');
    if (counts.plyo) chips.push('<span class="rv-chip rv-chip--who-support">' + counts.plyo + ' PLYO</span>');
    if (counts.strength) chips.push('<span class="rv-chip rv-chip--who-support">' + counts.strength + ' STRENGTH</span>');
    if (counts.race) chips.push('<span class="rv-chip rv-chip--who-race">RACE</span>');
    return (
      '<div class="rv-planned-empty">' +
      '<span class="rv-chart-sub">' + entries.length + ' planned sessions, nothing logged yet</span>' +
      '<span class="rv-planned-empty-chips">' + chips.join('') + '</span></div>'
    );
  }

  function renderList(data) {
    var el = document.getElementById('v2-list-body');
    var weeks = data.weeks || [];
    state.runIds = [];
    var loggedCount = 0;
    weeks.forEach(function (wk) {
      (wk.entries || []).forEach(function (e) {
        if (isLogged(e)) loggedCount += 1;
        if (typeMatches(e) && isLogged(e) && isRunType(e)) {
          state.runIds.push(String(e.id));
        }
      });
    });
    paintSubtitle(loggedCount);
    var html = [];
    var shown = 0;
    var today = todayISO();
    var highlightId = null;
    weeks.forEach(function (wk) {
      (wk.entries || []).forEach(function (e) {
        if (isLogged(e) && e.date === today && highlightId == null) highlightId = e.id;
      });
    });
    if (highlightId == null) {
      weeks.some(function (wk) {
        return (wk.entries || []).some(function (e) {
          if (isLogged(e)) { highlightId = e.id; return true; }
          return false;
        });
      });
    }
    var matchingWeeks = weeks.map(function (wk) {
      return {
        wk: wk,
        entries: (wk.entries || []).filter(function (e) {
          if (!typeMatches(e)) return false;
          if (state.search && (e.title || '').toLowerCase().indexOf(state.search.toLowerCase()) < 0) return false;
          return true;
        }),
      };
    }).filter(function (row) { return row.entries.length; });
    matchingWeeks.forEach(function (row, idx) {
      var wk = row.wk;
      var entries = row.entries;
      if (!state.showAllWeeks && idx >= 2) {
        shown += 1;
        return;
      }
      var sum = wk.summary || {};
      var roll = wk.rollup || {};
      var phase = phaseLabel(roll.phase);
      var range = fmtWeekRange(wk.week_start, wk.week_end);
      var left = range + (phase ? ' · ' + phase : '');
      var logged = entries.filter(isLogged);
      var plannedOnly = !logged.length;
      var plannedTss = sum.planned_tss != null ? sum.planned_tss : roll.planned_tss;
      var target = sum.target_tss != null ? sum.target_tss : roll.target_tss;
      var right;
      if (plannedOnly && (plannedTss || wk.week_start > today)) {
        right = '<a class="rv-week-plan-link" href="/v2/training/plan">' +
          Math.round(plannedTss || sum.total_tss || 0) + ' TSS planned · open in Plan</a>';
      } else {
        var km = fmtKm(sum.total_distance_km);
        right = '<span class="rv-week-stats">' + Math.round(sum.total_tss || 0) + ' TSS' +
          (km ? ' · ' + km : '') +
          (target != null ? '<span class="rv-week-target"> · target ' + Math.round(target) + '</span>' : '') +
          '</span>';
      }
      html.push('<section class="rv-week-block" id="week-' + esc(wk.week_start) + '" tabindex="-1">');
      html.push(
        '<div class="rv-week-head">' +
        '<span class="rv-week-range">' + esc(left) + '</span>' + right + '</div>'
      );
      if (plannedOnly) {
        html.push(plannedEmptyCard(entries));
      } else {
        var expanded = !!state.expandedWeeks[wk.week_start];
        var visible = expanded || entries.length <= 2 ? entries : entries.slice(0, 2);
        html.push('<div class="rv-week-sessions">');
        visible.forEach(function (entry) {
          html.push(renderSessionRow(entry, entry.id === highlightId));
        });
        if (!expanded && entries.length > 2) {
          var rest = entries.slice(2);
          var restTss = 0;
          var restKm = 0;
          rest.forEach(function (e) {
            restTss += Number(e.tss) || 0;
            restKm += Number(e.distance_km) || 0;
          });
          html.push(
            '<button type="button" class="rv-week-more" data-week-more="' + esc(wk.week_start) + '">' +
            '<span>' + rest.length + ' more sessions this week</span>' +
            '<span class="rv-week-more-meta">' + Math.round(restTss) + ' TSS' +
            (restKm ? ' · ' + restKm.toFixed(1) + ' km' : '') + ' ›</span></button>'
          );
        }
        html.push('</div>');
      }
      html.push('</section>');
      shown += 1;
    });
    if (!shown) {
      el.innerHTML = '<p class="rv-section-state">No sessions match these filters. <button type="button" class="rv-btn rv-btn--secondary" id="v2-clear-filters">Clear filters</button></p>';
      var clr = document.getElementById('v2-clear-filters');
      if (clr) clr.onclick = function () { state.filter = 'all'; state.search = ''; writeQuery(); renderFilters(); loadList(); };
      return;
    }
    if (!state.showAllWeeks && matchingWeeks.length > 2) {
      html.push('<p class="rv-older-wrap"><button type="button" class="rv-btn rv-btn--secondary" id="v2-show-older-weeks">Show older weeks</button></p>');
    }
    el.innerHTML = html.join('');
    el.querySelectorAll('[data-feel-host]').forEach(function (host) {
      if (window.V2FeelButtons) {
        var val = host.getAttribute('data-feel-val') || null;
        window.V2FeelButtons.mount(host, host.getAttribute('data-feel-host'), val === '' ? null : val);
      }
    });
    el.querySelectorAll('[data-plan-skip]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var pid = btn.getAttribute('data-plan-skip');
        fetch('/api/planned-sessions/' + encodeURIComponent(pid) + '/skip', { method: 'POST', credentials: 'same-origin' })
          .then(function (r) { if (!r.ok) throw new Error(); loadList(); loadMonth(); toast('Skipped planned session'); })
          .catch(function () { toast('Could not skip session'); });
      });
    });
    el.querySelectorAll('[data-plan-open]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        window.location.href = '/v2/training/plan';
      });
    });
    var older = document.getElementById('v2-show-older-weeks');
    if (older) {
      older.addEventListener('click', function () {
        state.showAllWeeks = true;
        loadList();
      });
    }
    el.querySelectorAll('[data-week-more]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.expandedWeeks[btn.getAttribute('data-week-more')] = true;
        loadList();
      });
    });
    el.querySelectorAll('[data-run-id]').forEach(function (row) {
      function open() {
        var id = row.getAttribute('data-run-id');
        var wt = row.getAttribute('data-workout-type') || '';
        if (window.V2StrengthDrawer && window.V2StrengthDrawer.isStrengthType(wt)) {
          window.V2StrengthDrawer.openView(id);
        } else if (window.V2RunDrawer) {
          window.V2RunDrawer.open(id, state.runIds);
        }
      }
      row.addEventListener('click', open);
      row.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
    });
  }

  function renderFilters() {
    var el = document.getElementById('v2-list-filters');
    if (!el) return;
    var filters = ['all', 'runs', 'strength', 'plyo', 'mobility', 'missed'];
    var labels = { all: 'All', runs: 'Runs', strength: 'Strength', plyo: 'Plyo', mobility: 'Mobility', missed: 'Missed' };
    el.innerHTML =
      '<div class="rv-chip-row rv-list-filter-chips">' + filters.map(function (f) {
        var on = state.filter === f ? ' is-on' : '';
        return '<button type="button" class="rv-chip' + on + '" data-filter="' + f + '">' + labels[f] + '</button>';
      }).join('') + '</div>' +
      '<div class="rv-list-filter-tools">' +
      '<label class="sr-only" for="v2-search">Search sessions</label>' +
      '<input type="search" class="rv-input rv-list-search" id="v2-search" placeholder="Search sessions" value="' + esc(state.search) + '"/>' +
      '<label class="sr-only" for="v2-range">Date range</label>' +
      '<select id="v2-range" class="rv-input rv-list-range"><option value="8w">Last 8 weeks</option><option value="block">This block</option><option value="all">All time</option></select></div>';
    document.getElementById('v2-range').value = state.range;
    el.querySelectorAll('[data-filter]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.filter = btn.getAttribute('data-filter');
        writeQuery();
        renderFilters();
        loadList();
      });
    });
    document.getElementById('v2-search').addEventListener('change', function (ev) {
      state.search = ev.target.value.trim();
      writeQuery();
      loadList();
    });
    document.getElementById('v2-range').addEventListener('change', function (ev) {
      state.range = ev.target.value;
      writeQuery();
      loadList();
    });
  }

  function loadList() {
    var el = document.getElementById('v2-list-body');
    sectionLoading(el, 'Loading sessions…');
    var span = listRange();
    var url = '/api/training-log?from=' + encodeURIComponent(span.from) + '&to=' + encodeURIComponent(span.to) +
      '&include_plan=1&canonical_week_totals=1';
    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error('list'); return r.json(); })
      .then(renderList)
      .catch(function () { sectionError(el, 'Could not load session list.'); });
  }

  function toast(msg) {
    var t = document.getElementById('v2-toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('is-visible');
    setTimeout(function () { t.classList.remove('is-visible'); }, 2800);
  }

  function refreshAll() {
    loadMonth();
    loadChart();
    loadList();
  }

  function init() {
    readQuery();
    writeQuery();
    renderFilters();
    paintSubtitle(null);
    loadRaceLine();
    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), { onRefresh: refreshAll });
    }
    refreshAll();
    window.addEventListener('v2:log-refresh', refreshAll);
    window.V2TrainingLogReload = refreshAll;
  }

  document.addEventListener('DOMContentLoaded', init);
})();