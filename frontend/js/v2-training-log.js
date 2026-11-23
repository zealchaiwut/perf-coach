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
    entriesByPlanId: {},
    rollupsByWeek: {},
    chartWeeks: [],
    weekCache: {},
    weekInflight: {},
    monthSeq: 0,
    chartSeq: 0,
    listSeq: 0,
    weekRollupSeq: {},
    blockStart: null,
    searchWeeks: [],
    allCursor: null,
    allLoading: false,
    knownRaces: [],
  };
  var weekObserver = null;
  var monthCtrl = null;
  var chartCtrl = null;
  var searchTimer = null;

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
    state.knownRaces = [];
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
          if (item.kind === 'race') {
            state.knownRaces.push({ name: item.name, race_date: day.date });
          }
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
    var seq = ++state.monthSeq;
    if (monthCtrl) monthCtrl.abort();
    monthCtrl = new AbortController();
    fetch('/api/training/month?month=' + encodeURIComponent(state.month), { signal: monthCtrl.signal })
      .then(function (r) { if (!r.ok) throw new Error('Month failed'); return r.json(); })
      .then(function (data) {
        if (seq !== state.monthSeq) return;
        renderMonth(data);
      })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (seq !== state.monthSeq) return;
        sectionError(body, 'Could not load month board.');
      });
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
        var ws = node.getAttribute('data-week');
        expandWeek(ws, true);
      }
      node.addEventListener('click', jump);
      node.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); jump(); } });
    });
  }

  function mondayISO(iso) {
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    var d = new Date(iso + 'T00:00:00Z');
    var wd = d.getUTCDay();
    var back = wd === 0 ? 6 : wd - 1;
    return add ? add(iso, -back) : iso;
  }

  function newestTwoMondays() {
    var thisMon = mondayISO(todayISO());
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    return [thisMon, add ? add(thisMon, -7) : thisMon];
  }

  function loadChart() {
    var el = document.getElementById('v2-chart-body');
    sectionLoading(el, 'Loading chart…');
    var end = todayISO();
    var fromW = window.AppCommon && window.AppCommon.addDaysISO
      ? window.AppCommon.addDaysISO(mondayISO(end), -7 * 8)
      : end;
    var seq = ++state.chartSeq;
    if (chartCtrl) chartCtrl.abort();
    chartCtrl = new AbortController();
    var timer = setTimeout(function () { chartCtrl.abort(); }, 25000);
    fetch('/api/weekly-rollup?from=' + encodeURIComponent(fromW) + '&to=' + encodeURIComponent(end), { signal: chartCtrl.signal })
      .then(function (r) { if (!r.ok) throw new Error('chart'); return r.json(); })
      .then(function (data) {
        clearTimeout(timer);
        if (seq !== state.chartSeq) return;
        var weeks = (data && data.weeks) || [];
        state.chartWeeks = weeks.slice();
        state.rollupsByWeek = {};
        weeks.forEach(function (w) { state.rollupsByWeek[w.week_start] = w; });
        if (data.next_race && data.next_race.name) {
          state.raceLine = data.next_race.name;
        } else {
          state.raceLine = '';
        }
        state.blockStart = data.block_start || null;
        if (state.range === 'block' && !state.blockStart) {
          state.range = '8w';
          writeQuery();
        }
        renderFilters();
        paintSubtitle(null);
        drawChart(weeks);
        paintList();
      })
      .catch(function (e) {
        clearTimeout(timer);
        if (seq !== state.chartSeq) return;
        sectionError(el, e && e.name === 'AbortError' ? 'Chart timed out — try again.' : 'Could not load weekly volume.');
      });
  }

  function listRange() {
    var mondays = newestTwoMondays();
    var from = mondays[mondays.length - 1];
    var end = todayISO();
    return { from: from, to: end };
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

  function sourceMark(kind, label) {
    return '<span class="rv-src-mark rv-src-mark--' + kind + '" title="' + esc(label) + '" aria-label="' + esc(label) + '"></span>';
  }

  function knownRaces(roll) {
    var seen = {};
    var out = [];
    function add(r) {
      if (!r) return;
      var name = r.name || '';
      var when = r.race_date || '';
      var key = when + '|' + name;
      if (!name && !when) return;
      if (seen[key]) return;
      seen[key] = 1;
      out.push({ name: name, race_date: when });
    }
    ((roll && roll.race_items) || []).forEach(add);
    Object.keys(state.rollupsByWeek || {}).forEach(function (ws) {
      (((state.rollupsByWeek[ws] || {}).race_items) || []).forEach(add);
    });
    (state.knownRaces || []).forEach(add);
    return out;
  }

  function isRaceLike(entry, roll) {
    var t = (entry.type || '').toLowerCase();
    if (t.indexOf('race') >= 0) return true;
    var title = (entry.title || '').toLowerCase();
    return knownRaces(roll).some(function (r) {
      var n = String(r.name || '').toLowerCase();
      if (!n) return false;
      return r.race_date === entry.date && title.indexOf(n) >= 0;
    });
  }

  function headerPlannedTss(roll, entries) {
    var we = roll.week_end || '';
    if (we && we < todayISO()) return 0;
    var n = Number(roll.planned_tss_training) || 0;
    ((roll && roll.race_items) || []).forEach(function (r) {
      if (r.tss == null || r.tss_source === 'logged') return;
      var logged = (entries || []).some(function (e) {
        return isLogged(e) && e.date === r.race_date;
      });
      if (!logged) n += Number(r.tss) || 0;
    });
    return n;
  }

  function badgeChips(entry, roll) {
    var chips = [];
    var missed = entry.row_kind === 'missed_plan';
    if (missed) {
      chips.push('<span class="rv-chip rv-chip--missed">PLANNED, NOT DONE</span>');
      return chips.join('');
    }
    if (entry.has_strava) chips.push(sourceMark('strava', 'Strava'));
    if (entry.is_stryd_synced || entry.has_stryd) chips.push(sourceMark('stryd', 'Stryd'));
    if (isStrengthType(entry)) {
      chips.push('<span class="rv-chip rv-chip--who-support">STRENGTH</span>');
    }
    if (isRaceLike(entry, roll)) {
      chips.push('<span class="rv-chip rv-chip--race-flag">RACE</span>');
    } else if (entry.plan_match) {
      chips.push('<span class="rv-chip rv-chip--good">MATCHED COACH PLAN</span>');
    } else if (
      isStrengthType(entry) &&
      (entry.source || '') === 'manual' &&
      entry.id &&
      String(entry.id).indexOf('plan:') !== 0
    ) {
      chips.push('<span class="rv-chip rv-chip--warn">UNPLANNED · TYPED AT THE GYM</span>');
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
      if (entry.exercise_count) bits.push(esc(entry.exercise_count + ' exercises'));
      if (entry.tss != null) bits.push(esc(Math.round(entry.tss) + ' TSS planned'));
      return bits.join(' · ');
    }
    var tpe = (entry.type || '').toLowerCase();
    var strength = isStrengthType(entry) || tpe.indexOf('plyo') >= 0 || tpe.indexOf('mobility') >= 0;
    if (strength) {
      var sbits = [];
      var mins = fmtMins(entry.duration_seconds);
      if (mins) sbits.push(esc(mins));
      if (entry.exercise_count) sbits.push(esc(entry.exercise_count + ' exercises'));
      if (entry.set_count) sbits.push(esc(entry.set_count + ' sets'));
      return sbits.join(' · ');
    }
    var rbits = [];
    var dur = fmtHms(entry.duration_seconds);
    if (dur) rbits.push('<b>' + esc(dur) + '</b>');
    var km = fmtKm(entry.distance_km);
    if (km) rbits.push('<b>' + esc(km) + '</b>');
    var pace = fmtPaceSpk(entry.average_pace_seconds_per_km);
    if (pace) rbits.push(esc(pace));
    if (entry.avg_power) rbits.push(esc(Math.round(entry.avg_power) + ' W'));
    if (entry.avg_hr) rbits.push(esc('HR ' + Math.round(entry.avg_hr)));
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

  function prefillFromPlanned(entry) {
    var structure = entry.planned_structure || {};
    var exercises = structure.exercises || [];
    return {
      planned_id: (entry.plan_match && entry.plan_match.planned_id) || String(entry.id || '').replace('plan:', ''),
      name: entry.title || (entry.plan_match && entry.plan_match.planned_name) || 'Session',
      workout_type: entry.type || 'run',
      workout_date: entry.date,
      duration_seconds: entry.duration_seconds || null,
      exercises_json: exercises,
    };
  }

  function findEntryByPlanId(pid) {
    return state.entriesByPlanId[pid] || null;
  }

  function matchPlanned(pid, workoutId) {
    return fetch('/api/planned-sessions/' + encodeURIComponent(pid) + '/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ workout_id: workoutId }),
    });
  }

  function logItLate(pid, entry) {
    entry = entry || findEntryByPlanId(pid) || {};
    var pre = prefillFromPlanned(entry);
    pre.planned_id = pid || pre.planned_id;
    var tpe = (pre.workout_type || '').toLowerCase();
    if (window.V2StrengthDrawer && window.V2StrengthDrawer.isStrengthType(tpe)) {
      window.V2StrengthDrawer.openEdit(null, {
        name: pre.name,
        workout_date: pre.workout_date,
        duration_seconds: pre.duration_seconds,
        exercises_json: pre.exercises_json,
        planned_id: pre.planned_id,
        workout_type: tpe.indexOf('plyo') >= 0 ? 'plyo' : 'strength',
      });
      return;
    }
    var body = {
      name: pre.name,
      workout_date: pre.workout_date,
      workout_type: pre.workout_type || 'run',
      duration_seconds: pre.duration_seconds,
    };
    fetch('/api/workouts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    })
      .then(function (r) { if (!r.ok) throw new Error('create'); return r.json(); })
      .then(function (w) {
        return matchPlanned(pre.planned_id, w.id).then(function () { return w; });
      })
      .then(function (w) {
        var ws = mondayISO(pre.workout_date || todayISO());
        fetchWeek(ws, { force: true });
        refreshWeekRollup(ws);
        if (window.V2RunDrawer) window.V2RunDrawer.open(w.id, state.runIds.concat([w.id]));
      })
      .catch(function () { toast('Could not open late log'); });
  }

  function renderSessionRow(entry, highlight, roll) {
    roll = roll || state.rollupsByWeek[mondayISO(entry.date)] || {};
    var missed = entry.row_kind === 'missed_plan';
    var tpe = (entry.type || '').toLowerCase();
    var run = isRunType(entry) && !missed;
    var str = !missed && window.V2StrengthDrawer && window.V2StrengthDrawer.isStrengthType(tpe);
    var race = isRaceLike(entry, roll);
    var rowCls = 'rv-session-row';
    if (missed) rowCls += ' rv-session-row--missed';
    if (highlight) rowCls += ' rv-session-row--today';
    if (race) rowCls += ' rv-session-row--race';
    if (run || str) rowCls += ' rv-session-row--clickable';
    var day = isoParts(entry.date).d;
    var wd = WEEKDAYS_SHORT[weekdayIndex(entry.date)] || '';
    var meta = sessionMeta(entry);
    var attrs = (run || str)
      ? ' data-run-id="' + esc(entry.id) + '" data-workout-type="' + esc(entry.type || '') + '" tabindex="0" role="button"'
      : '';
    var weekTss = Number(roll.tss_total) || 0;
    var share = '';
    if (!missed && entry.tss != null && weekTss > 0) {
      var pct = Math.round((Number(entry.tss) / weekTss) * 100);
      share =
        '<span class="rv-session-share"><span class="rv-session-sbar"><span class="rv-session-share-fill' +
        (race ? ' rv-session-share-fill--race' : '') +
        '" style="width:' + pct + '%"></span></span><span class="rv-session-share-pct">' + pct + '%</span></span>';
    }
    var feel = '';
    if (!missed && entry.id && String(entry.id).indexOf('plan:') !== 0) {
      feel = '<span class="rv-list-feel" data-feel-id="' + esc(entry.id) + '" data-feeling="' + esc(entry.feeling || '') + '"></span>';
    }
    var tssBlock;
    if (missed) {
      var pid = (entry.plan_match && entry.plan_match.planned_id) || String(entry.id).replace('plan:', '');
      tssBlock =
        '<div class="rv-missed-actions">' +
        '<button type="button" class="rv-btn rv-btn--ghost-amber" data-log-late="' + esc(pid) + '">Log it late</button>' +
        '<button type="button" class="rv-btn rv-btn--ghost-amber" data-plan-skip="' + esc(pid) + '">Skip</button>' +
        '</div><span class="rv-session-tss-block" aria-hidden="true"></span>';
    } else {
      tssBlock =
        '<span class="rv-session-tss-block"><span class="rv-session-tss">' +
        (entry.tss != null ? Math.round(entry.tss) : '—') +
        '</span>' + share + '</span>';
    }
    return (
      '<div class="' + rowCls + '"' + attrs + '>' +
      '<span class="rv-session-date"><span class="rv-session-day">' + esc(String(day)) + '</span><span class="rv-session-wd">' + esc(wd) + '</span></span>' +
      '<div class="rv-session-main">' +
      '<div class="rv-session-title-row"><strong class="rv-session-title">' + esc(entry.title || 'Session') + '</strong>' + badgeChips(entry, roll) + '</div>' +
      (meta ? '<div class="rv-session-metrics">' + meta + '</div>' : '') +
      '</div>' + feel + tssBlock + '</div>'
    );
  }

  function fmtSignedDelta(n) {
    var v = Math.round(Number(n) || 0);
    if (v > 0) return '+' + v;
    if (v < 0) return '\u2212' + Math.abs(v);
    return '0';
  }

  function weekBarHtml(roll, entries, opts) {
    opts = opts || {};
    var ws = roll.week_start;
    var we = roll.week_end || weekEndISO(ws);
    var today = todayISO();
    var thisMon = mondayISO(today);
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    var lastMon = add ? add(thisMon, -7) : thisMon;
    var isCurrent = ws === thisMon;
    var isLast = ws === lastMon;
    var logged = (entries || []).filter(isLogged);
    var emptyCurrent = isCurrent && !logged.length;
    var tss = Number(roll.tss_total) || 0;
    var target = roll.target_tss;
    var hasTarget = target != null && isFinite(Number(target));
    var tnum = hasTarget ? Number(target) : 0;
    var over = hasTarget && !emptyCurrent && tss > tnum;
    var tssCls = 'rv-log-wkbar-big';
    if (emptyCurrent) tssCls += ' rv-log-wkbar-big--empty';
    else if (over) tssCls += ' rv-log-wkbar-big--over';
    var phase = phaseLabel(roll.phase);
    var races = knownRaces(roll).filter(function (r) {
      return r.race_date && r.race_date >= ws && r.race_date <= we;
    });
    var raceName = races.length ? races[0].name : '';
    var sub = [];
    if (isCurrent) sub.push('This week');
    else if (isLast) sub.push('Last week');
    if (phase) sub.push(esc(phase));
    if (raceName) sub.push(esc(raceName) + ' week');
    var planned = headerPlannedTss(roll, entries);
    var plannedCount = (entries || []).filter(function (e) { return !isLogged(e); }).length;
    if (emptyCurrent) {
      if (plannedCount) sub.push(plannedCount + ' planned, nothing logged yet');
      else sub.push('nothing logged yet');
    } else {
      var sc = roll.session_count != null ? Number(roll.session_count) : logged.length;
      if (sc) sub.push(sc + (sc === 1 ? ' session' : ' sessions'));
    }
    var raceTss = Number(roll.race_planned_tss) || 0;
    if (raceTss > 0) sub.push('race ' + Math.round(raceTss));
    if ((isCurrent || ws > thisMon) && planned > 0 && !emptyCurrent) {
      sub.push('planned ' + Math.round(planned));
    }
    var meter = '';
    if (hasTarget) {
      var scale = Math.max(tnum / 0.87, tss);
      var fillPct = scale > 0 ? Math.min(100, (tss / scale) * 100) : 0;
      var tickPct = scale > 0 ? Math.min(100, (tnum / scale) * 100) : 87;
      var fillEl = '';
      if (!emptyCurrent && (over || fillPct > 0)) {
        fillEl = '<span class="rv-log-wkbar-fill' + (over ? ' rv-log-wkbar-fill--over' : '') + '" style="width:' + (over ? 100 : fillPct) + '%"></span>';
      }
      var label;
      if (emptyCurrent) {
        label = '<b>0%</b> of ' + Math.round(tnum) + ' target · <a class="rv-log-wkbar-plan" href="/v2/training/plan">Open in Plan ›</a>';
      } else if (over) {
        label = '<b class="rv-log-wkbar-over">+' + Math.round(tss - tnum) + '</b> over ' + Math.round(tnum) + ' target';
      } else {
        var pctOf = tnum > 0 ? Math.round((tss / tnum) * 100) : 0;
        label = '<b>' + pctOf + '%</b> of ' + Math.round(tnum) + ' target';
      }
      if (!emptyCurrent && roll.tss_delta_prev != null && isFinite(Number(roll.tss_delta_prev))) {
        var delta = Number(roll.tss_delta_prev);
        var deltaCls = 'rv-log-wkbar-delta' + (delta < 0 ? ' rv-log-wkbar-delta--down' : '');
        label += ' · <span class="' + deltaCls + '">' + fmtSignedDelta(delta) + ' vs prev</span>';
      }
      meter =
        '<div class="rv-log-wkbar-meter">' +
        '<div class="rv-log-wkbar-track">' + fillEl +
        '<span class="rv-log-wkbar-tick" style="left:' + tickPct + '%"></span></div>' +
        '<span class="rv-log-wkbar-ml">' + label + '</span></div>';
    }
    var kmHtml = '';
    if (!emptyCurrent && roll.distance_km) {
      kmHtml = '<div class="rv-log-wkbar-stat"><span class="rv-log-wkbar-mid">' +
        esc(Number(roll.distance_km).toFixed(1)) +
        '</span><span class="rv-log-wkbar-unit">km</span></div>';
    }
    if (emptyCurrent && !meter) {
      meter = '<a class="rv-log-wkbar-plan" href="/v2/training/plan">Open in Plan ›</a>';
    }
    var cls = 'rv-log-wkbar' + (emptyCurrent ? ' rv-log-wkbar--empty' : '');
    var inner =
      '<div class="rv-log-wkbar-left"><span class="rv-log-wkbar-range">' + esc(fmtWeekRange(ws, we)) + '</span>' +
      (sub.length ? '<span class="rv-log-wkbar-sub">' + sub.join(' · ') + '</span>' : '') +
      '</div><div class="rv-log-wkbar-stats">' +
      '<div class="rv-log-wkbar-stat"><span class="' + tssCls + '">' + (emptyCurrent ? 0 : Math.round(tss)) + '</span><span class="rv-log-wkbar-unit">TSS</span></div>' +
      kmHtml + meter + '</div>';
    if (opts.collapsed) {
      return '<button type="button" class="' + cls + ' rv-week-collapsed" aria-expanded="false" data-expand-week="' + esc(ws) + '">' + inner + '</button>';
    }
    return '<div class="' + cls + '">' + inner + '</div>';
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
      '<span class="rv-planned-empty-chips">' + chips.join('') + '</span>' +
      '<a class="rv-week-plan-link" href="/v2/training/plan">open in Plan</a></div>'
    );
  }

  function paintList() {
    state.entriesByPlanId = {};
    var el = document.getElementById('v2-list-body');
    if (!el) return;
    var weeks = (state.chartWeeks || []).slice().sort(function (a, b) {
      return (b.week_start || '').localeCompare(a.week_start || '');
    });
    if (!weeks.length) {
      var cachedKeys = Object.keys(state.weekCache);
      weeks = cachedKeys.sort().reverse().map(function (ws) {
        return state.rollupsByWeek[ws] || { week_start: ws, week_end: weekEndISO(ws) };
      });
    }
    var newest = newestTwoMondays();
    var searching = !!state.search;
    if (searching) {
      weeks = (state.searchWeeks || []).slice().sort(function (a, b) {
        return (b.week_start || '').localeCompare(a.week_start || '');
      });
    }
    state.runIds = [];
    var loggedCount = 0;
    var today = todayISO();
    var highlightId = null;
    Object.keys(state.weekCache).forEach(function (ws) {
      (state.weekCache[ws].entries || []).forEach(function (e) {
        if (e.row_kind === 'missed_plan') {
          var pid = (e.plan_match && e.plan_match.planned_id) || String(e.id || '').replace('plan:', '');
          if (pid) state.entriesByPlanId[pid] = e;
        }
        if (isLogged(e)) {
          loggedCount += 1;
          if (e.date === today && highlightId == null) highlightId = e.id;
          if (highlightId == null) highlightId = e.id;
        }
        if (typeMatches(e) && isLogged(e) && isRunType(e)) state.runIds.push(String(e.id));
      });
    });
    paintSubtitle(loggedCount);
    var html = [];
    var shown = 0;
    weeks.forEach(function (roll, idx) {
      var ws = roll.week_start;
      var we = roll.week_end || weekEndISO(ws);
      var cache = state.weekCache[ws] || { loaded: false, entries: [], error: null };
      var entries = (cache.entries || []).filter(function (e) {
        if (!typeMatches(e)) return false;
        if (state.search && (e.title || '').toLowerCase().indexOf(state.search.toLowerCase()) < 0) return false;
        return true;
      });
      var expanded = searching || !!state.expandedWeeks[ws] || newest.indexOf(ws) !== -1;
      html.push('<section class="rv-week-block" id="week-' + esc(ws) + '" tabindex="-1">');
      html.push(weekBarHtml(roll, entries, { collapsed: !expanded }));
      if (!expanded) {
        html.push('</section>');
        shown += 1;
        return;
      }
      if (state.weekInflight[ws] && !cache.loaded) {
        html.push('<p class="rv-section-state">Loading week…</p>');
      } else if (cache.error) {
        html.push(
          '<p class="rv-section-state" role="alert">Could not load this week. ' +
          '<button type="button" class="rv-btn rv-btn--secondary" data-retry-week="' + esc(ws) + '">Retry</button></p>'
        );
      } else {
        var logged = entries.filter(isLogged);
        var thisMon = mondayISO(todayISO());
        var emptyCurrent = ws === thisMon && !logged.length;
        if (emptyCurrent) {
          /* grey bar in weekBarHtml replaces the dashed planned-sessions card */
        } else if (logged.length) {
          var openAll = !!state.openWeeks[ws] || entries.length <= 3;
          var visible = openAll ? entries : entries.slice(0, 3);
          html.push('<div class="rv-week-body"><div class="rv-week-sessions">');
          visible.forEach(function (entry) {
            html.push(renderSessionRow(entry, entry.id === highlightId, roll));
          });
          if (!openAll) {
            var rest = entries.slice(3);
            var restTss = 0;
            var restKm = 0;
            rest.forEach(function (e) {
              restTss += Number(e.tss) || 0;
              restKm += Number(e.distance_km) || 0;
            });
            html.push(
              '<button type="button" class="rv-week-more" data-week-more="' + esc(ws) + '">' +
              '<span>' + rest.length + ' more sessions this week</span>' +
              '<span class="rv-week-more-meta">' + Math.round(restTss) + ' TSS' +
              (restKm ? ' · ' + restKm.toFixed(1) + ' km' : '') + ' ›</span></button>'
            );
          }
          html.push('</div></div>');
        }
      }
      html.push('</section>');
      shown += 1;
      if (state.range === 'all' && !searching && idx === weeks.length - 1) {
        html.push('<div class="rv-older-sentinel" data-load-older-month="1" aria-hidden="true"></div>');
      }
    });
    if (!shown) {
      var empty = state.search
        ? 'No sessions match “' + esc(state.search) + '”.'
        : 'No sessions match these filters.';
      el.innerHTML = '<p class="rv-section-state">' + empty + ' <button type="button" class="rv-btn rv-btn--secondary" id="v2-clear-filters">Clear filters</button></p>';
      var clr = document.getElementById('v2-clear-filters');
      if (clr) clr.onclick = function () {
        state.filter = 'all';
        state.search = '';
        state.searchWeeks = [];
        writeQuery();
        renderFilters();
        paintList();
      };
      return;
    }
    el.innerHTML = html.join('');
    if (window.V2FeelButtons) {
      el.querySelectorAll('[data-feel-id]').forEach(function (host) {
        window.V2FeelButtons.mount(host, host.getAttribute('data-feel-id'), host.getAttribute('data-feeling') || null, function (val) {
          applyFeelInPlace(host.getAttribute('data-feel-id'), val);
        });
      });
    }
    el.querySelectorAll('[data-plan-skip]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var pid = btn.getAttribute('data-plan-skip');
        fetch('/api/planned-sessions/' + encodeURIComponent(pid) + '/skip', { method: 'POST', credentials: 'same-origin' })
          .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
          .then(function () {
            var ws = applySkipInPlace(pid);
            if (ws) refreshWeekRollup(ws);
            else paintList();
            toast('Skipped planned session');
          })
          .catch(function () { toast('Could not skip session'); });
      });
    });
    el.querySelectorAll('[data-log-late]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var pid = btn.getAttribute('data-log-late');
        var row = btn.closest('.rv-session-row');
        var entry = findEntryByPlanId(pid);
        logItLate(pid, entry, row);
      });
    });
    el.querySelectorAll('[data-week-more]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.openWeeks[btn.getAttribute('data-week-more')] = true;
        paintList();
      });
    });
    el.querySelectorAll('[data-expand-week]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        expandWeek(btn.getAttribute('data-expand-week'), false);
      });
    });
    el.querySelectorAll('[data-retry-week]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        fetchWeek(btn.getAttribute('data-retry-week'), { force: true });
      });
    });
    bindWeekObserver(el);
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
      '<select id="v2-range" class="rv-input rv-list-range"><option value="8w">Last 8 weeks</option>' +
      (state.blockStart ? '<option value="block">This block</option>' : '') +
      '<option value="all">All time</option></select></div>';
    var rangeEl = document.getElementById('v2-range');
    if (state.range === 'block' && !state.blockStart) state.range = '8w';
    rangeEl.value = state.range;
    el.querySelectorAll('[data-filter]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.filter = btn.getAttribute('data-filter');
        writeQuery();
        renderFilters();
        paintList();
      });
    });
    document.getElementById('v2-search').addEventListener('input', function (ev) {
      var val = ev.target.value;
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.search = val.trim();
        writeQuery();
        runSearch();
      }, 300);
    });
    document.getElementById('v2-range').addEventListener('change', function (ev) {
      state.range = ev.target.value;
      writeQuery();
      applyRange();
    });
  }

  function weekEndISO(ws) {
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    return add ? add(ws, 6) : ws;
  }

  function flattenWeekEntries(data) {
    var out = [];
    (data.weeks || []).forEach(function (wk) {
      (wk.entries || []).forEach(function (e) { out.push(e); });
    });
    return out;
  }

  function applyLogPayload(data, expectedMondays) {
    (data.weeks || []).forEach(function (wk) {
      if (!wk.week_start) return;
      state.weekCache[wk.week_start] = { loaded: true, entries: wk.entries || [], error: null };
    });
    (expectedMondays || []).forEach(function (ws) {
      if (!state.weekCache[ws] || !state.weekCache[ws].loaded) {
        state.weekCache[ws] = { loaded: true, entries: [], error: null };
      }
    });
  }

  function bindWeekObserver(root) {
    if (weekObserver) {
      weekObserver.disconnect();
      weekObserver = null;
    }
    if (!root || typeof IntersectionObserver === 'undefined') return;
    weekObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        if (en.target.getAttribute('data-load-older-month')) {
          loadOlderAllMonth();
          return;
        }
        var ws = en.target.getAttribute('data-expand-week');
        if (ws) expandWeek(ws, false);
      });
    }, { rootMargin: '200px' });
    root.querySelectorAll('[data-expand-week]').forEach(function (btn) {
      weekObserver.observe(btn);
    });
    root.querySelectorAll('[data-load-older-month]').forEach(function (node) {
      weekObserver.observe(node);
    });
  }

  function applyFeelInPlace(workoutId, feeling) {
    Object.keys(state.weekCache).forEach(function (ws) {
      (state.weekCache[ws].entries || []).forEach(function (e) {
        if (String(e.id) === String(workoutId)) e.feeling = feeling;
      });
    });
  }

  function applySkipInPlace(plannedId) {
    var hit = null;
    Object.keys(state.weekCache).forEach(function (ws) {
      var cache = state.weekCache[ws];
      if (!cache || !cache.entries) return;
      cache.entries = cache.entries.filter(function (e) {
        var pid = (e.plan_match && e.plan_match.planned_id) || String(e.id || '').replace('plan:', '');
        if (String(pid) === String(plannedId)) {
          hit = ws;
          return false;
        }
        return true;
      });
    });
    delete state.entriesByPlanId[plannedId];
    paintList();
    return hit;
  }

  function refreshWeekRollup(ws) {
    if (!ws) return;
    var seq = (state.weekRollupSeq[ws] || 0) + 1;
    state.weekRollupSeq[ws] = seq;
    var ctrl = new AbortController();
    fetch('/api/weekly-rollup?week_start=' + encodeURIComponent(ws), { signal: ctrl.signal, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('rollup'); return r.json(); })
      .then(function (row) {
        if (seq !== state.weekRollupSeq[ws]) return;
        var prevDelta = (state.rollupsByWeek[ws] || {}).tss_delta_prev;
        if (row.tss_delta_prev == null && prevDelta != null) row.tss_delta_prev = prevDelta;
        state.rollupsByWeek[ws] = row;
        var found = false;
        state.chartWeeks = (state.chartWeeks || []).map(function (w) {
          if (w.week_start === ws) { found = true; return row; }
          return w;
        });
        if (!found) state.chartWeeks.push(row);
        drawChart(state.chartWeeks.slice());
        paintList();
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
      });
  }

  function fetchInitialWeeks(opts) {
    opts = opts || {};
    var mondays = newestTwoMondays();
    mondays.forEach(function (ws) { state.expandedWeeks[ws] = true; });
    var from = mondays[mondays.length - 1];
    var to = todayISO();
    var inflightKey = '_initial';
    var seq = ++state.listSeq;
    if (!opts.force && mondays.every(function (ws) {
      return state.weekCache[ws] && state.weekCache[ws].loaded;
    })) {
      paintList();
      return Promise.resolve();
    }
    if (!opts.force && state.weekInflight[inflightKey]) return state.weekInflight[inflightKey];
    if (state.weekInflight[inflightKey] && state.weekInflight[inflightKey].abort) {
      try { state.weekInflight[inflightKey].abort(); } catch (e) { /* ignore */ }
    }
    var ctrl = new AbortController();
    var url = '/api/training-log?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to) + '&include_plan=1';
    var p = fetch(url, { signal: ctrl.signal, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('list'); return r.json(); })
      .then(function (data) {
        if (seq !== state.listSeq) return;
        applyLogPayload(data, mondays);
        delete state.weekInflight[inflightKey];
        paintList();
      })
      .catch(function (err) {
        if (state.weekInflight[inflightKey] === p) delete state.weekInflight[inflightKey];
        if (err && err.name === 'AbortError') return;
        if (seq !== state.listSeq) return;
        mondays.forEach(function (ws) {
          state.weekCache[ws] = { loaded: false, entries: [], error: true };
        });
        paintList();
      });
    p.abort = function () { ctrl.abort(); };
    state.weekInflight[inflightKey] = p;
    paintList();
    return p;
  }

  function fetchWeek(ws, opts) {
    opts = opts || {};
    if (state.weekCache[ws] && state.weekCache[ws].loaded && !opts.force) {
      return Promise.resolve(state.weekCache[ws]);
    }
    if (state.weekInflight[ws] && !opts.force) return state.weekInflight[ws];
    if (state.weekInflight[ws] && state.weekInflight[ws].abort) {
      try { state.weekInflight[ws].abort(); } catch (e) { /* ignore */ }
    }
    var ctrl = new AbortController();
    var we = weekEndISO(ws);
    var url = '/api/training-log?from=' + encodeURIComponent(ws) + '&to=' + encodeURIComponent(we) + '&include_plan=1';
    state.weekCache[ws] = state.weekCache[ws] || { loaded: false, entries: [], error: null };
    state.weekCache[ws].error = null;
    var p = fetch(url, { signal: ctrl.signal, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('list'); return r.json(); })
      .then(function (data) {
        if (state.weekInflight[ws] !== p) return;
        state.weekCache[ws] = { loaded: true, entries: flattenWeekEntries(data), error: null };
        delete state.weekInflight[ws];
        paintList();
        return state.weekCache[ws];
      })
      .catch(function (err) {
        if (state.weekInflight[ws] === p) delete state.weekInflight[ws];
        if (err && err.name === 'AbortError') return;
        state.weekCache[ws] = { loaded: false, entries: [], error: true };
        paintList();
      });
    p.abort = function () { ctrl.abort(); };
    state.weekInflight[ws] = p;
    paintList();
    return p;
  }

  function expandWeek(ws, scroll) {
    state.expandedWeeks[ws] = true;
    fetchWeek(ws).then(function () {
      if (!scroll) return;
      var target = document.getElementById('week-' + ws);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        target.focus();
      }
    });
    paintList();
  }

  function loadList(force) {
    var el = document.getElementById('v2-list-body');
    if (!el) return;
    fetchInitialWeeks({ force: !!force });
  }

  function searchBounds() {
    var end = todayISO();
    var add = window.AppCommon && window.AppCommon.addDaysISO;
    if (state.range === 'block' && state.blockStart) return { from: state.blockStart, to: end };
    if (state.range === 'all') return { from: add ? add(end, -365) : end, to: end };
    return { from: add ? add(mondayISO(end), -7 * 8) : end, to: end };
  }

  function runSearch() {
    if (!state.search) {
      state.searchWeeks = [];
      paintList();
      return;
    }
    var b = searchBounds();
    var seq = ++state.listSeq;
    var url = '/api/training-log?from=' + encodeURIComponent(b.from) +
      '&to=' + encodeURIComponent(b.to) +
      '&search=' + encodeURIComponent(state.search) +
      '&include_plan=1';
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('search'); return r.json(); })
      .then(function (data) {
        if (seq !== state.listSeq) return;
        state.searchWeeks = data.weeks || [];
        applyLogPayload(data, null);
        (state.searchWeeks || []).forEach(function (wk) {
          if (wk.week_start) state.expandedWeeks[wk.week_start] = true;
        });
        paintList();
      })
      .catch(function () {
        if (seq !== state.listSeq) return;
        state.searchWeeks = [];
        paintList();
      });
  }

  function mergeRollupWeeks(weeks) {
    (weeks || []).forEach(function (w) {
      if (!w || !w.week_start) return;
      state.rollupsByWeek[w.week_start] = w;
      var found = false;
      state.chartWeeks = (state.chartWeeks || []).map(function (cur) {
        if (cur.week_start === w.week_start) { found = true; return w; }
        return cur;
      });
      if (!found) state.chartWeeks.push(w);
    });
  }

  function monthBounds(ym) {
    var start = ym + '-01';
    var parts = ym.split('-');
    var lastDay = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10), 0).getDate();
    var end = ym + '-' + (lastDay < 10 ? '0' : '') + lastDay;
    var today = todayISO();
    if (end > today) end = today;
    return { from: mondayISO(start), to: end };
  }

  function prevMonth(ym) {
    var parts = ym.split('-');
    var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 2, 1);
    var m = d.getMonth() + 1;
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m;
  }

  function loadOlderAllMonth() {
    if (state.range !== 'all' || state.search || state.allLoading) return;
    var cursor = state.allCursor || todayISO().slice(0, 7);
    var next = prevMonth(cursor);
    state.allLoading = true;
    var b = monthBounds(next);
    fetch('/api/weekly-rollup?from=' + encodeURIComponent(b.from) + '&to=' + encodeURIComponent(b.to), { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('month'); return r.json(); })
      .then(function (data) {
        state.allCursor = next;
        mergeRollupWeeks(data.weeks || []);
        state.allLoading = false;
        paintList();
      })
      .catch(function () { state.allLoading = false; });
  }

  function applyRange() {
    if (state.search) {
      runSearch();
      return;
    }
    if (state.range === 'all') {
      var oldest = (state.chartWeeks || []).reduce(function (acc, w) {
        if (!w.week_start) return acc;
        return !acc || w.week_start < acc ? w.week_start : acc;
      }, null);
      state.allCursor = (oldest || todayISO()).slice(0, 7);
    } else if (state.range === 'block' && state.blockStart) {
      fetch('/api/weekly-rollup?from=' + encodeURIComponent(state.blockStart) + '&to=' + encodeURIComponent(todayISO()), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('block'); return r.json(); })
        .then(function (data) {
          mergeRollupWeeks(data.weeks || []);
          paintList();
        })
        .catch(function () { paintList(); });
    }
    loadList();
  }

  function toast(msg) {
    var t = document.getElementById('v2-toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('is-visible');
    setTimeout(function () { t.classList.remove('is-visible'); }, 2800);
  }

  function refreshAll() {
    if (window.V2RunDrawer && window.V2RunDrawer.clearLookups) window.V2RunDrawer.clearLookups();
    loadMonth();
    loadChart();
    loadList(true);
  }

  function init() {
    readQuery();
    writeQuery();
    renderFilters();
    paintSubtitle(null);
    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), { onRefresh: refreshAll });
    }
    refreshAll();
    if (state.search) runSearch();
    window.addEventListener('v2:log-refresh', refreshAll);
    window.V2TrainingLogReload = refreshAll;
  }

  document.addEventListener('DOMContentLoaded', init);
})();