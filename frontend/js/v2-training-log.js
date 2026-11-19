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
    el.innerHTML = '<p class="rv-section-state" role="status">' + esc(msg || 'Loading…') + '</p>';
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
    if (status === 'planned') return 'rv-session--run rv-month-card--planned';
    if (kind === 'rest') return 'rv-session--rest';
    if (kind === 'race') return 'rv-session--race';
    if (kind === 'quality_run') return 'rv-session--quality';
    if (kind === 'run') return 'rv-session--run';
    return 'rv-session--support';
  }

  function whoColor(who) {
    var w = (who || '').toUpperCase();
    if (w.indexOf('MISSED') >= 0 || w.indexOf('CHECKPOINT') >= 0) return '#7a3a10';
    if (w.indexOf('SUPPORT') >= 0 || w.indexOf('STRENGTH') >= 0) return '#4c1d95';
    if (w.indexOf('RACE') >= 0) return '#6b4408';
    return '#1e3fb0';
  }

  function renderMonth(data) {
    var body = document.getElementById('v2-month-body');
    var nav = document.getElementById('v2-month-nav');
    if (!body || !nav) return;
    var label = new Date(data.month + '-01').toLocaleString('en', { month: 'long', year: 'numeric' });
    nav.innerHTML =
      '<button type="button" class="rv-btn rv-btn--secondary" aria-label="Previous month" id="v2-month-prev">‹</button>' +
      '<span style="font-weight:700;min-width:150px;text-align:center">' + esc(label) + '</span>' +
      '<button type="button" class="rv-btn rv-btn--secondary" aria-label="Next month" id="v2-month-next">›</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-month-today">Today</button>' +
      '<span class="rv-subtitle" style="margin:0;font-family:var(--rv-mono)">So far: ' +
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
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Week'].forEach(function (h) {
      html.push('<div class="rv-month-head">' + h + '</div>');
    });
    (data.weeks || []).forEach(function (week) {
      week.days.forEach(function (day) {
        var cls = 'rv-month-day';
        if (!day.in_month) cls += ' rv-month-day--out';
        if (day.is_today) cls += ' rv-month-day--today';
        html.push('<div class="' + cls + '" role="gridcell">');
        html.push('<div class="rv-month-daynum">' + esc(day.date.slice(-2)) + (day.is_today ? ' <span class="rv-chip" style="min-height:auto;padding:0 6px;font-size:10px">Today</span>' : '') + '</div>');
        (day.items || []).forEach(function (item) {
          var cardCls = 'rv-month-card ' + sessionCardClass(item.kind, item.status);
          var clickable = item.status === 'done' && item.workout_id && (item.kind === 'run' || item.kind === 'quality_run');
          if (clickable) cardCls += ' rv-month-card--clickable';
          var meta = [];
          if (item.tss != null) meta.push(Math.round(item.tss) + ' TSS');
          if (item.distance_km != null) meta.push(item.distance_km + ' km');
          if (item.duration_min != null) meta.push(item.duration_min + ' min');
          var who = item.who || String(item.kind || '').replace('_', ' ').toUpperCase();
          var tag = item.status === 'done' ? 'Done' : (item.status === 'planned' ? '' : item.status);
          html.push(
            '<h3 class="' + cardCls + '" tabindex="' + (clickable ? '0' : '-1') + '" data-workout-id="' + esc(item.workout_id || '') + '">' +
            '<span class="rv-month-who" style="color:' + esc(whoColor(who)) + '">' + esc(who) + '</span>' +
            '<span class="rv-month-card-title">' + esc(item.name) + '</span>' +
            (meta.length ? '<div class="rv-subtitle" style="margin:0;font-family:var(--rv-mono);font-size:10px">' + esc(meta.join(' · ')) + '</div>' : '') +
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
      function open() { if (window.V2RunDrawer) window.V2RunDrawer.open(id, state.runIds); }
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

  function drawChart(weeks) {
    var el = document.getElementById('v2-chart-body');
    if (!el) return;
    if (!weeks.length) {
      sectionError(el, 'No weekly data yet.');
      return;
    }
    var maxTss = Math.max.apply(null, weeks.map(function (w) {
      return (w.tss_run || 0) + (w.tss_strength || 0) + (w.tss_support_other || 0) + (w.planned_tss || 0);
    }).concat([1]));
    var maxKm = Math.max.apply(null, weeks.map(function (w) { return w.distance_km || 0; }).concat([1]));
    var w = 1000;
    var h = 220;
    var pad = 40;
    var slot = (w - pad * 2) / weeks.length;
    var parts = ['<svg viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="Weekly training volume">'];
    var linePts = [];
    weeks.forEach(function (wk, i) {
      var run = wk.tss_run || 0;
      var lift = (wk.tss_strength || 0) + (wk.tss_support_other || 0);
      var total = run + lift;
      var planned = wk.planned_tss || 0;
      var x = pad + i * slot + slot * 0.15;
      var bw = slot * 0.7;
      var runH = total ? (run / maxTss) * (h - pad * 2) : 0;
      var liftH = total ? (lift / maxTss) * (h - pad * 2) : 0;
      var yBase = h - pad;
      var isCur = wk.partial;
      var fill = isCur ? '#3b6fe0' : '#bfd3f8';
      if (total <= 0 && planned > 0) {
        var ph = (planned / maxTss) * (h - pad * 2);
        parts.push('<rect x="' + x + '" y="' + (yBase - ph) + '" width="' + bw + '" height="' + ph + '" rx="4" fill="#ffffff" stroke="#6d93e8" stroke-width="2" stroke-dasharray="5 4"/>');
      } else if (total <= 0) {
        parts.push('<rect x="' + x + '" y="' + (yBase - 4) + '" width="' + bw + '" height="4" rx="2" fill="#eef1f7"/>');
      } else {
        parts.push('<rect x="' + x + '" y="' + (yBase - runH - liftH) + '" width="' + bw + '" height="' + runH + '" rx="3" fill="' + fill + '"/>');
        if (liftH > 0) parts.push('<rect x="' + x + '" y="' + (yBase - runH - liftH) + '" width="' + bw + '" height="' + liftH + '" fill="#c9b6f2"/>');
        if (isCur && planned > total) {
          var rem = ((planned - total) / maxTss) * (h - pad * 2);
          parts.push('<rect x="' + x + '" y="' + (yBase - runH - liftH - rem) + '" width="' + bw + '" height="' + rem + '" rx="3" fill="none" stroke="#6d93e8" stroke-width="2" stroke-dasharray="4 3"/>');
        }
      }
      var kmY = pad + (1 - (wk.distance_km || 0) / maxKm) * (h - pad * 2);
      if (isCur) {
        parts.push('<circle cx="' + (x + bw / 2) + '" cy="' + kmY + '" r="5" fill="#d97706"/>');
      }
      linePts.push((x + bw / 2) + ',' + kmY);
      parts.push('<text x="' + (x + bw / 2) + '" y="' + (h - 8) + '" font-size="11" text-anchor="middle" fill="#56627f">' +
        esc(wk.week_start.slice(5)) + '</text>');
      parts.push('<rect tabindex="0" role="button" aria-label="Week ' + esc(wk.week_start) + '" x="' + x + '" y="' + pad + '" width="' + bw + '" height="' + (h - pad * 2) + '" fill="transparent" data-week="' + esc(wk.week_start) + '"/>');
    });
    if (linePts.length) {
      parts.push('<polyline points="' + linePts.join(' ') + '" fill="none" stroke="#d97706" stroke-width="2.5"/>');
    }
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
    var startDate = new Date(end);
    startDate.setDate(startDate.getDate() - 7 * 8);
    var fromW = startDate.toISOString().slice(0, 10);
    fetch('/api/weekly-rollup?from=' + encodeURIComponent(fromW) + '&to=' + encodeURIComponent(end))
      .then(function (r) { if (!r.ok) throw new Error('chart'); return r.json(); })
      .then(function (data) { drawChart((data && data.weeks) || []); })
      .catch(function () { sectionError(el, 'Could not load weekly volume.'); });
  }

  function listRange() {
    var end = todayISO();
    var start = new Date(end);
    if (state.range === 'all') start.setFullYear(start.getFullYear() - 3);
    else if (state.range === 'block') start.setDate(start.getDate() - 7 * 8);
    else start.setDate(start.getDate() - 7 * 8);
    return { from: start.toISOString().slice(0, 10), to: end };
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

  function badges(entry) {
    var b = [];
    if (entry.is_stryd_synced || entry.has_stryd) b.push('STRYD');
    if (entry.plan_match) b.push('Matched coach plan');
    else if (entry.row_kind !== 'missed_plan' && entry.id && String(entry.id).indexOf('plan:') !== 0) b.push('Unplanned');
    if (entry.speed_signal != null) b.push('Hard effort');
    return b;
  }

  function renderList(data) {
    var el = document.getElementById('v2-list-body');
    var weeks = data.weeks || [];
    state.runIds = [];
    weeks.forEach(function (wk) {
      (wk.entries || []).forEach(function (e) {
        if (typeMatches(e) && e.id && String(e.id).indexOf('plan:') !== 0 && (e.type || '').toLowerCase().indexOf('run') >= 0) {
          state.runIds.push(String(e.id));
        }
      });
    });
    var html = [];
    var shown = 0;
    weeks.forEach(function (wk, idx) {
      var entries = (wk.entries || []).filter(function (e) {
        if (!typeMatches(e)) return false;
        if (state.search && (e.title || '').toLowerCase().indexOf(state.search.toLowerCase()) < 0) return false;
        return true;
      });
      if (!entries.length) return;
      var open = state.openWeeks[wk.week_start] || state.showAllWeeks || idx < 2;
      var sum = wk.summary || {};
      html.push('<section class="rv-week-block" id="week-' + esc(wk.week_start) + '" tabindex="-1">');
      html.push('<button type="button" class="rv-week-head" data-week-toggle="' + esc(wk.week_start) + '">' +
        '<strong>' + esc(wk.label || wk.week_start) + '</strong>' +
        '<span class="rv-subtitle" style="margin:0;font-family:var(--rv-mono)">' +
        Math.round(sum.total_tss || 0) + ' TSS · ' + (sum.total_distance_km || 0) + ' km</span></button>');
      if (open) {
        entries.forEach(function (entry) {
          var missed = entry.row_kind === 'missed_plan';
          var rowCls = 'rv-session-row' + (missed ? ' rv-session-row--missed' : '');
          var run = (entry.type || '').toLowerCase().indexOf('run') >= 0 && !missed;
          if (run) rowCls += ' rv-session-row--clickable';
          var meta = [];
          if (entry.duration_minutes != null) meta.push(entry.duration_minutes + ' min');
          if (entry.distance_km != null) meta.push(entry.distance_km + ' km');
          if (entry.average_pace_seconds_per_km) meta.push(Math.round(entry.average_pace_seconds_per_km / 60) + ' min/km');
          if (entry.avg_power) meta.push(entry.avg_power + ' W');
          if (entry.avg_hr) meta.push(entry.avg_hr + ' bpm');
          html.push('<div class="' + rowCls + '"' + (run ? ' data-run-id="' + esc(entry.id) + '" tabindex="0" role="button"' : '') + '>');
          html.push('<span class="rv-subtitle" style="margin:0">' + esc(entry.date.slice(-2)) + '</span>');
          html.push('<span class="rv-sync-dot rv-sync-dot--green" aria-hidden="true"></span>');
          html.push('<div><strong>' + esc(entry.title || 'Session') + '</strong>' +
            '<div class="rv-subtitle" style="margin:0;font-family:var(--rv-mono)">' + esc(meta.join(' · ')) + '</div>' +
            '<p style="margin:4px 0 0;font-size:12px">' + esc(badges(entry).join(' · ')) + '</p></div>');
          html.push(
            '<div class="rv-session-side">' +
            '<span class="rv-mono">' + (entry.tss != null ? Math.round(entry.tss) : '—') + ' TSS</span>' +
            (run ? '<div class="rv-list-feel" data-feel-host="' + esc(entry.id) + '" data-feel-val="' + esc(entry.feeling || '') + '"></div>' : '') +
            (missed
              ? '<div class="rv-missed-actions">' +
                '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-plan-open="' + esc((entry.plan_match && entry.plan_match.planned_id) || String(entry.id).replace('plan:', '')) + '">Review in Plan</button>' +
                ((entry.type || '').toLowerCase() === 'mobility'
                  ? '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-plan-skip="' + esc((entry.plan_match && entry.plan_match.planned_id) || String(entry.id).replace('plan:', '')) + '">Skip</button>'
                  : '') +
                '</div>'
              : '') +
            '</div>'
          );
          html.push('</div>');
        });
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
    if (!state.showAllWeeks && shown > 2) {
      html.push('<p style="text-align:center;margin:12px 0"><button type="button" class="rv-btn rv-btn--secondary" id="v2-show-older-weeks">Show older weeks</button></p>');
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
    el.querySelectorAll('[data-week-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-week-toggle');
        state.openWeeks[key] = !state.openWeeks[key];
        loadList();
      });
    });
    el.querySelectorAll('[data-run-id]').forEach(function (row) {
      function open() { window.V2RunDrawer.open(row.getAttribute('data-run-id'), state.runIds); }
      row.addEventListener('click', open);
      row.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
    });
  }

  function renderFilters() {
    var el = document.getElementById('v2-list-filters');
    if (!el) return;
    var filters = ['all', 'runs', 'strength', 'plyo', 'mobility', 'missed'];
    el.innerHTML = filters.map(function (f) {
      var on = state.filter === f ? ' rv-btn--primary' : ' rv-btn--secondary';
      return '<button type="button" class="rv-btn' + on + '" data-filter="' + f + '">' + f + '</button>';
    }).join('') +
      '<input type="search" class="rv-btn rv-btn--secondary" style="min-width:180px" id="v2-search" placeholder="Search name" value="' + esc(state.search) + '"/>' +
      '<select id="v2-range" class="rv-btn rv-btn--secondary"><option value="8w">Last 8 weeks</option><option value="block">This block</option><option value="all">All time</option></select>';
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
    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), { onRefresh: refreshAll });
    }
    refreshAll();
    window.addEventListener('v2:log-refresh', refreshAll);
  }

  document.addEventListener('DOMContentLoaded', init);
})();