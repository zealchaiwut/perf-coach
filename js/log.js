(function () {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  var allWorkouts = [];
  var filters = { search: '', type: 'all', dateRange: '30d', customFrom: '', customTo: '' };
  var viewedWeekMonday = null;
  var currentWeekMonday = null;

  var TYPE_LABELS = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
  var DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']; // Mon-Sun

  // ── Date helpers ─────────────────────────────────────────────────────────

  function pad(n) { return String(n).padStart(2, '0'); }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function addDays(isoDate, days) {
    var d = new Date(isoDate + 'T00:00:00');
    d.setDate(d.getDate() + days);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function getMondayOfWeek(isoDate) {
    var d = new Date(isoDate + 'T00:00:00');
    var day = d.getDay(); // 0=Sun
    var diff = day === 0 ? -6 : 1 - day;
    d.setDate(d.getDate() + diff);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var DAY_NAMES = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  var DAY_SHORT = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

  function formatWeekLabel(mondayISO) {
    var mon = new Date(mondayISO + 'T00:00:00');
    var sun = new Date(mondayISO + 'T00:00:00');
    sun.setDate(sun.getDate() + 6);
    var base = MONTHS[mon.getMonth()] + ' ' + mon.getDate();
    if (mon.getMonth() === sun.getMonth()) {
      return base + ' – ' + sun.getDate();
    }
    return base + ' – ' + MONTHS[sun.getMonth()] + ' ' + sun.getDate();
  }

  function formatDayFull(isoDate) {
    var d = new Date(isoDate + 'T00:00:00');
    return DAY_NAMES[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
  }

  function formatDuration(minutes) {
    if (!minutes) return '';
    var h = Math.floor(minutes / 60);
    var m = minutes % 60;
    if (h > 0 && m > 0) return h + 'h ' + m + ' min';
    if (h > 0) return h + 'h';
    return m + ' min';
  }

  // ── URL params ────────────────────────────────────────────────────────────

  function readURLFilters() {
    var params = new URLSearchParams(window.location.search);
    filters.search = params.get('search') || '';
    filters.type   = params.get('types')  || 'all';
    var range = params.get('range');
    var from  = params.get('from');
    var to    = params.get('to');
    if (range && ['7d','30d','90d','all'].indexOf(range) !== -1) {
      filters.dateRange = range;
    } else if (from || to) {
      filters.dateRange  = 'custom';
      filters.customFrom = from || '';
      filters.customTo   = to   || '';
    } else {
      filters.dateRange = '30d';
    }
  }

  function writeURLFilters() {
    var params = new URLSearchParams();
    if (filters.search) params.set('search', filters.search);
    if (filters.type && filters.type !== 'all') params.set('types', filters.type);
    if (filters.dateRange === 'custom') {
      if (filters.customFrom) params.set('from', filters.customFrom);
      if (filters.customTo)   params.set('to',   filters.customTo);
    } else if (filters.dateRange !== '30d') {
      params.set('range', filters.dateRange);
    }
    var qs = params.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  // ── Data loading ──────────────────────────────────────────────────────────

  function getDateRange() {
    var today = todayISO();
    if (filters.dateRange === '7d')  return { from: addDays(today, -6),  to: today };
    if (filters.dateRange === '30d') return { from: addDays(today, -29), to: today };
    if (filters.dateRange === '90d') return { from: addDays(today, -89), to: today };
    if (filters.dateRange === 'all') return { from: null, to: null };
    if (filters.dateRange === 'custom') {
      return { from: filters.customFrom || null, to: filters.customTo || null };
    }
    return { from: addDays(today, -29), to: today };
  }

  async function loadWorkouts() {
    document.getElementById('log-loading').hidden = false;
    document.getElementById('log-empty').hidden   = true;
    document.getElementById('workout-list').innerHTML = '';

    try {
      var range = getDateRange();
      var params = new URLSearchParams();
      if (range.from) params.set('from', range.from);
      if (range.to)   params.set('to',   range.to);
      if (filters.type && filters.type !== 'all') params.set('types', filters.type);
      if (filters.search) params.set('search', filters.search);
      params.set('include_rest', filters.type === 'all' || !filters.type ? 'true' : 'false');
      var uid = (typeof getCurrentUserId === 'function') ? getCurrentUserId() : null;
      if (uid) params.set('user_id', uid);
      var url = '/training_log?' + params.toString();
      var res = await fetch(url);
      if (!res.ok) throw new Error('server ' + res.status);
      var data = await res.json();
      allWorkouts = [];
      (data.weeks || []).forEach(function (w) {
        allWorkouts = allWorkouts.concat(w.entries || w.workouts || []);
      });
    } catch (e) {
      var mockWorkouts = (typeof MOCK_TRAINING_WORKOUTS !== 'undefined') ? MOCK_TRAINING_WORKOUTS.slice() : [];
      var mockRest     = (typeof MOCK_REST_DAYS       !== 'undefined') ? MOCK_REST_DAYS.slice()       : [];
      allWorkouts = mockWorkouts.concat(mockRest);
    }

    document.getElementById('log-loading').hidden = true;
    applyAndRender();
  }

  // ── Filtering ─────────────────────────────────────────────────────────────

  function filterWorkouts(items) {
    var range = getDateRange();
    // Custom with no dates set → show nothing (empty state)
    if (filters.dateRange === 'custom' && !filters.customFrom && !filters.customTo) return [];
    return items.filter(function (w) {
      if (range.from && w.date < range.from) return false;
      if (range.to   && w.date > range.to)   return false;
      // Rest days are hidden when a specific workout type is selected
      if (filters.type !== 'all' && w.type === 'rest') return false;
      if (filters.type !== 'all' && w.type !== filters.type) return false;
      if (filters.search) {
        var q = filters.search.toLowerCase();
        if (w.type === 'rest') {
          var rn = ((w.metrics && w.metrics.notes) || '').toLowerCase();
          if (rn.indexOf(q) === -1) return false;
        } else {
          var title = (w.title || '').toLowerCase();
          var notes = (w.notes || '').toLowerCase();
          if (title.indexOf(q) === -1 && notes.indexOf(q) === -1) return false;
        }
      }
      return true;
    });
  }

  // ── Grouping ──────────────────────────────────────────────────────────────

  function groupByWeek(items) {
    var map = {};
    items.forEach(function (w) {
      var monday = getMondayOfWeek(w.date);
      if (!map[monday]) map[monday] = [];
      map[monday].push(w);
    });
    return Object.keys(map).sort().reverse().map(function (monday) {
      var all = map[monday];

      // Workout-only entries drive the summary
      var workoutEntries = all.filter(function (w) { return w.type !== 'rest'; });

      // Suppress rest days for dates that also have a workout
      var workoutDates = {};
      workoutEntries.forEach(function (w) { workoutDates[w.date] = true; });

      var visible = all
        .filter(function (w) { return w.type !== 'rest' || !workoutDates[w.date]; })
        .sort(function (a, b) { return b.date.localeCompare(a.date); });

      var s = computeSummary(workoutEntries);
      return { week_start: monday, week_end: addDays(monday, 6), label: formatWeekLabel(monday), summary: s, workouts: visible };
    });
  }

  function computeSummary(workouts) {
    var count = workouts.length, dist = 0, tss = 0, mins = 0;
    workouts.forEach(function (w) {
      if (w.distance_km) dist += w.distance_km;
      if (w.tss)         tss  += w.tss;
      if (w.duration_min) mins += w.duration_min;
    });
    return { workout_count: count, total_distance_km: Math.round(dist * 10) / 10, total_tss: tss, total_time_minutes: mins };
  }

  // ── Apply & render ────────────────────────────────────────────────────────

  function applyAndRender() {
    writeURLFilters();
    syncFilterUI();

    var filtered = filterWorkouts(allWorkouts);
    var weeks    = groupByWeek(filtered);
    var listEl   = document.getElementById('workout-list');
    var emptyEl  = document.getElementById('log-empty');

    if (weeks.length === 0) {
      listEl.innerHTML = '';
      emptyEl.hidden   = false;
    } else {
      emptyEl.hidden = true;
      renderWorkoutList(weeks);
    }
    renderWeekStrip();
  }

  // ── Sync filter UI ────────────────────────────────────────────────────────

  function syncFilterUI() {
    document.querySelectorAll('.filter-chip[data-type]').forEach(function (chip) {
      chip.classList.toggle('active', chip.dataset.type === filters.type);
    });

    var searchEl = document.getElementById('search-input');
    if (searchEl && searchEl.value !== filters.search) searchEl.value = filters.search;

    document.querySelectorAll('input[name="dr"]').forEach(function (inp) {
      inp.checked = inp.value === filters.dateRange;
    });

    var customEl = document.getElementById('dr-custom');
    if (customEl) customEl.hidden = filters.dateRange !== 'custom';

    if (filters.dateRange === 'custom') {
      var fromEl = document.getElementById('dr-from');
      var toEl   = document.getElementById('dr-to');
      if (fromEl) fromEl.value = filters.customFrom;
      if (toEl)   toEl.value   = filters.customTo;
    }

    updateDateRangeChipLabel();
  }

  function updateDateRangeChipLabel() {
    var btn = document.getElementById('date-range-chip');
    if (!btn) return;
    var labels = { '7d': 'Last 7 days', '30d': 'Last 30 days', '90d': 'Last 90 days', 'all': 'All time' };
    var arrow = ' ▾'; // ▾
    if (filters.dateRange === 'custom') {
      if (filters.customFrom && filters.customTo) {
        btn.textContent = filters.customFrom + ' – ' + filters.customTo + arrow;
      } else {
        btn.textContent = 'Custom' + arrow;
      }
    } else {
      btn.textContent = (labels[filters.dateRange] || 'Last 30 days') + arrow;
    }
  }

  // ── Week strip ────────────────────────────────────────────────────────────

  function renderWeekStrip() {
    var today  = todayISO();
    var monday = viewedWeekMonday;

    var labelEl = document.getElementById('week-label');
    if (labelEl) labelEl.textContent = (monday === currentWeekMonday) ? 'This week' : formatWeekLabel(monday);

    // Build dot map from ALL workouts (unfiltered) for this week's 7 days
    var weekDates = [];
    for (var i = 0; i < 7; i++) weekDates.push(addDays(monday, i));

    var dotMap = {};
    weekDates.forEach(function (d) { dotMap[d] = []; });
    allWorkouts.forEach(function (w) {
      if (w.type === 'rest') return;
      if (Object.prototype.hasOwnProperty.call(dotMap, w.date)) {
        if (dotMap[w.date].indexOf(w.type) === -1) dotMap[w.date].push(w.type);
      }
    });

    var pillsEl = document.getElementById('week-pills');
    if (!pillsEl) return;
    pillsEl.innerHTML = '';

    weekDates.forEach(function (dateStr, idx) {
      var d      = new Date(dateStr + 'T00:00:00');
      var dayNum = d.getDate();
      var pill   = document.createElement('button');
      pill.className = 'day-pill' + (dateStr === today ? ' is-today' : '');
      pill.dataset.date = dateStr;
      pill.setAttribute('role', 'listitem');
      pill.setAttribute('aria-label', formatDayFull(dateStr));

      var dotsHtml = (dotMap[dateStr] || []).map(function (t) {
        return '<span class="dot dot--' + t + '" aria-hidden="true"></span>';
      }).join('');

      pill.innerHTML =
        '<span class="day-pill-letter" aria-hidden="true">' + DAY_LETTERS[idx] + '</span>' +
        '<span class="day-pill-num">'    + dayNum + '</span>' +
        '<span class="day-pill-dots" aria-hidden="true">' + dotsHtml + '</span>';

      pill.addEventListener('click', function () {
        var target = document.getElementById('day-' + dateStr);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });

      pillsEl.appendChild(pill);
    });
  }

  // ── Workout list ──────────────────────────────────────────────────────────

  function renderWorkoutList(weeks) {
    var listEl = document.getElementById('workout-list');
    listEl.innerHTML = '';
    weeks.forEach(function (week) { listEl.appendChild(buildWeekGroup(week)); });
  }

  function buildWeekGroup(week) {
    var s        = week.summary;
    var distText = s.total_distance_km > 0 ? s.total_distance_km + ' km' : null;
    var timeText = formatDuration(s.total_time_minutes);
    var parts    = [s.workout_count + ' workout' + (s.workout_count !== 1 ? 's' : '')];
    if (distText) parts.push(distText);
    parts.push('TSS ' + s.total_tss);
    if (timeText) parts.push(timeText);

    var groupEl = document.createElement('div');
    groupEl.className = 'week-group';

    var header = document.createElement('div');
    header.className = 'week-group-header';
    header.innerHTML =
      '<div class="week-group-title">' + escHtml(week.label) + '</div>' +
      '<div class="week-summary">' +
        parts.map(function (p, i) {
          return (i > 0 ? '<span class="week-summary-sep">·</span>' : '') +
            '<span class="week-summary-stat">' + escHtml(String(p)) + '</span>';
        }).join('') +
      '</div>';
    groupEl.appendChild(header);

    // Group workouts by day (descending)
    var dayMap = {};
    week.workouts.forEach(function (w) {
      if (!dayMap[w.date]) dayMap[w.date] = [];
      dayMap[w.date].push(w);
    });
    Object.keys(dayMap).sort().reverse().forEach(function (dateStr) {
      var section = document.createElement('div');
      section.className = 'day-section';
      section.id        = 'day-' + dateStr;

      var label     = document.createElement('div');
      label.className  = 'day-section-label';
      label.textContent = formatDayFull(dateStr);
      section.appendChild(label);

      dayMap[dateStr].forEach(function (w) {
        section.appendChild(w.type === 'rest' ? buildRestDayRow(w) : buildWorkoutRow(w));
      });
      groupEl.appendChild(section);
    });

    return groupEl;
  }

  function buildWorkoutRow(w) {
    var row = document.createElement('div');
    row.className = 'workout-row';
    row.dataset.id = w.id;
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');

    var d       = new Date(w.date + 'T00:00:00');
    var dayNum  = d.getDate();
    var dayName = DAY_SHORT[d.getDay()];

    // Meta line
    var meta = [formatDuration(w.duration_min)].filter(Boolean);
    if (w.type === 'run' || w.type === 'bike') {
      if (w.distance_km)  meta.push(w.distance_km + ' km');
      if (w.pace_per_km)  meta.push(w.pace_per_km + '/km');
      if (w.avg_hr)       meta.push('HR ' + w.avg_hr);
    } else if (w.type === 'lift') {
      if (w.top_weight_kg) meta.push(w.top_weight_kg + ' kg top set');
    } else if (w.type === 'wod') {
      if (w.avg_hr) meta.push('HR ' + w.avg_hr);
      if (w.notes)  meta.push(w.notes);
    }

    // Primary metric
    var metric = '';
    if (w.type === 'run')  metric = w.pace_per_km ? w.pace_per_km + '/km' : (w.distance_km ? w.distance_km + ' km' : '');
    else if (w.type === 'bike')  metric = w.distance_km ? w.distance_km + ' km' : '';
    else if (w.type === 'lift')  metric = w.top_weight_kg ? w.top_weight_kg + ' kg' : '';
    else if (w.type === 'wod')   metric = formatDuration(w.duration_min);

    // TSS pill
    var tssCls = 'tss-grey';
    if (w.tss > 80)      tssCls = 'tss-red';
    else if (w.tss > 50) tssCls = 'tss-amber';
    var tssHtml = (w.tss != null)
      ? '<span class="tss-pill ' + tssCls + '">TSS ' + w.tss + '</span>'
      : '';

    row.innerHTML =
      '<div class="wr-date">' +
        '<span class="wr-day-num">'  + dayNum  + '</span>' +
        '<span class="wr-day-name">' + dayName + '</span>' +
      '</div>' +
      '<span class="wr-badge wr-badge--' + w.type + '">' + escHtml(TYPE_LABELS[w.type] || w.type) + '</span>' +
      '<div class="wr-content">' +
        '<div class="wr-title">' + escHtml(w.title) + '</div>' +
        '<div class="wr-meta">'  + escHtml(meta.join(' · ')) + '</div>' +
      '</div>' +
      '<div class="wr-metric">' + escHtml(metric) + '</div>' +
      tssHtml +
      '<span class="source-pill">' + escHtml(w.source) + '</span>' +
      '<span class="wr-chevron" aria-hidden="true">›</span>';

    row.addEventListener('click', function () { /* detail panel — issue #2 */ });
    row.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
    });

    return row;
  }

  function buildRestDayRow(entry) {
    var row = document.createElement('div');
    row.className = 'workout-row rest-day-row';

    var d       = new Date(entry.date + 'T00:00:00');
    var dayNum  = d.getDate();
    var dayName = DAY_SHORT[d.getDay()];

    var m = entry.metrics || {};
    var meta = [];
    if (m.energy        != null) meta.push('Energy ' + m.energy + '/5');
    if (m.sleep_quality != null) meta.push('Sleep ' + m.sleep_quality + '/5');
    if (m.resting_hr    != null) meta.push('RHR ' + m.resting_hr + ' bpm');
    if (m.hrv           != null) meta.push('HRV ' + m.hrv + ' ms');
    if (m.sleep_hours   != null) meta.push(m.sleep_hours + 'h sleep');
    if (m.notes) {
      var n = m.notes.length > 80 ? m.notes.substring(0, 80) + '…' : m.notes;
      meta.push(n);
    }

    row.innerHTML =
      '<div class="wr-date">' +
        '<span class="wr-day-num">'  + dayNum  + '</span>' +
        '<span class="wr-day-name">' + dayName + '</span>' +
      '</div>' +
      '<span class="wr-badge wr-badge--rest">Rest</span>' +
      '<div class="wr-content">' +
        '<div class="wr-title">Rest day</div>' +
        '<div class="wr-meta">' + escHtml(meta.join(' · ')) + '</div>' +
      '</div>' +
      '<span class="wr-chevron" aria-hidden="true">›</span>';

    return row;
  }

  // ── Export ────────────────────────────────────────────────────────────────

  function handleExport() {
    var visible = filterWorkouts(allWorkouts).filter(function (w) { return w.type !== 'rest'; });
    if (!visible.length) { alert('No workouts to export.'); return; }

    var cols = ['date','type','title','distance','duration','tss','avg_hr','source'];
    var rows = visible.map(function (w) {
      return [
        w.date,
        w.type,
        '"' + (w.title  || '').replace(/"/g, '""') + '"',
        w.distance_km   != null ? w.distance_km   : '',
        w.duration_min  != null ? w.duration_min  : '',
        w.tss           != null ? w.tss           : '',
        w.avg_hr        != null ? w.avg_hr        : '',
        '"' + (w.source || '').replace(/"/g, '""') + '"',
      ].join(',');
    });

    var csv  = [cols.join(',')].concat(rows).join('\n');
    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href     = url;
    a.download = 'training-log.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function escHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Event wiring ──────────────────────────────────────────────────────────

  function initEvents() {
    // Week navigation
    document.getElementById('week-prev-btn').addEventListener('click', function () {
      viewedWeekMonday = addDays(viewedWeekMonday, -7);
      renderWeekStrip();
    });
    document.getElementById('week-next-btn').addEventListener('click', function () {
      viewedWeekMonday = addDays(viewedWeekMonday, 7);
      renderWeekStrip();
    });

    // Search (debounced)
    var searchEl = document.getElementById('search-input');
    var searchTimer;
    searchEl.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        filters.search = searchEl.value.trim();
        applyAndRender();
      }, 300);
    });

    // Type chips
    document.querySelectorAll('.filter-chip[data-type]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        filters.type = chip.dataset.type;
        applyAndRender();
      });
    });

    // Date range chip toggle
    var drChip = document.getElementById('date-range-chip');
    var drDD   = document.getElementById('date-range-dropdown');
    drChip.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = !drDD.hidden;
      drDD.hidden = open;
      drChip.setAttribute('aria-expanded', String(!open));
    });

    // Date range radio buttons
    document.querySelectorAll('input[name="dr"]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        if (!inp.checked) return;
        filters.dateRange = inp.value;
        var customEl = document.getElementById('dr-custom');
        if (customEl) customEl.hidden = filters.dateRange !== 'custom';
        updateDateRangeChipLabel();
        if (filters.dateRange !== 'custom') {
          drDD.hidden = true;
          drChip.setAttribute('aria-expanded', 'false');
          applyAndRender();
        }
      });
    });

    // Custom range apply
    document.getElementById('dr-apply').addEventListener('click', function () {
      filters.customFrom = document.getElementById('dr-from').value;
      filters.customTo   = document.getElementById('dr-to').value;
      drDD.hidden = true;
      drChip.setAttribute('aria-expanded', 'false');
      applyAndRender();
    });

    // Close dropdown on outside click
    document.addEventListener('click', function (e) {
      if (!drDD.hidden && !drDD.contains(e.target) && e.target !== drChip) {
        drDD.hidden = true;
        drChip.setAttribute('aria-expanded', 'false');
      }
    });

    // Export
    document.getElementById('log-export-btn').addEventListener('click', handleExport);

    // Log workout → navigate to training page (detail panel ships in issue #2)
    document.getElementById('log-add-btn').addEventListener('click', function () {
      window.location.href = 'training.html';
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    var today        = todayISO();
    currentWeekMonday = getMondayOfWeek(today);
    viewedWeekMonday  = currentWeekMonday;

    readURLFilters();
    initEvents();
    loadWorkouts();
  });

}());
