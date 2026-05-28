(function () {
  'use strict';

  var TYPE_COLOR = { run: '#3b82f6', lift: '#8b5cf6', wod: '#f97316', bike: '#14b8a6' };
  var TYPE_LABEL = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
  var TYPE_BADGE_BG    = { run: '#dbeafe', lift: '#ede9fe', wod: '#ffedd5', bike: '#ccfbf1' };
  var TYPE_BADGE_COLOR = { run: '#1d4ed8', lift: '#6d28d9', wod: '#c2410c', bike: '#0f766e' };
  var DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  var state = { search: '', type: 'all', range: '30d', weekOffset: 0 };
  var visibleWorkouts = [];
  // allWorkoutsByDate: { 'YYYY-MM-DD': ['run', 'lift', ...], ... }
  // Populated from the API response; used by the week strip for dots.
  var allWorkoutsByDate = null;

  // ── Date helpers ──────────────────────────────────────────────────────────

  function ymd(date) {
    return date.toISOString().slice(0, 10);
  }

  function todayYMD() {
    return ymd(new Date());
  }

  // Returns the Monday of the week that is `offset` weeks from the current week.
  function getWeekMonday(offset) {
    var today = new Date();
    var dow = today.getDay(); // 0=Sun
    var daysToMon = dow === 0 ? -6 : 1 - dow;
    var mon = new Date(today);
    mon.setDate(today.getDate() + daysToMon + offset * 7);
    mon.setHours(0, 0, 0, 0);
    return mon;
  }

  function isoToDate(iso) {
    return new Date(iso + 'T00:00:00');
  }

  function isoWeekNum(date) {
    var d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    var dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    var yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  }

  function weekDateRange(weekStart, weekEnd) {
    var s = isoToDate(weekStart);
    var e = isoToDate(weekEnd);
    var startStr = MONTH_NAMES[s.getMonth()] + ' ' + s.getDate();
    if (s.getMonth() !== e.getMonth()) {
      return startStr + ' – ' + MONTH_NAMES[e.getMonth()] + ' ' + e.getDate();
    }
    return startStr + ' – ' + e.getDate();
  }

  // ── State ↔ URL ───────────────────────────────────────────────────────────

  function loadFromURL() {
    var p = new URLSearchParams(location.search);
    if (p.get('search')) state.search = p.get('search');
    if (p.get('types'))  state.type   = p.get('types');
    if (p.get('range'))  state.range  = p.get('range');

    document.getElementById('search-input').value = state.search;
    document.querySelectorAll('.type-filter-chip').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.type === state.type);
    });
    document.getElementById('date-range').value = state.range;
  }

  function syncToURL() {
    var p = new URLSearchParams();
    if (state.search)           p.set('search', state.search);
    if (state.type !== 'all')   p.set('types',  state.type);
    if (state.range !== '30d')  p.set('range',  state.range);
    var qs = p.toString();
    history.replaceState(null, '', qs ? ('?' + qs) : location.pathname);
  }

  // ── Week strip ────────────────────────────────────────────────────────────

  function weekLabel(mon) {
    var thisMonKey = ymd(getWeekMonday(0));
    if (ymd(mon) === thisMonKey) return 'This week';
    var sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    var startStr = mon.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return startStr + ' – ' + sun.getDate();
  }

  function renderWeekStrip() {
    var mon = getWeekMonday(state.weekOffset);
    document.getElementById('week-label').textContent = weekLabel(mon);

    var today = todayYMD();
    var dotsByDate = {};
    if (allWorkoutsByDate !== null) {
      dotsByDate = allWorkoutsByDate;
    } else {
      // Fallback to mock data until the first API response arrives
      var mockWks = typeof MOCK_WORKOUTS !== 'undefined' ? MOCK_WORKOUTS : [];
      mockWks.forEach(function (w) {
        if (!dotsByDate[w.date]) dotsByDate[w.date] = [];
        if (dotsByDate[w.date].indexOf(w.type) === -1) dotsByDate[w.date].push(w.type);
      });
    }

    var container = document.getElementById('week-pills');
    container.innerHTML = '';
    for (var i = 0; i < 7; i++) {
      var d = new Date(mon);
      d.setDate(mon.getDate() + i);
      var dateStr = ymd(d);
      var isToday = dateStr === today;

      var btn = document.createElement('button');
      btn.className = 'day-pill' + (isToday ? ' today' : '');
      btn.dataset.date = dateStr;

      var types = dotsByDate[dateStr] || [];
      var dotsHTML = types.map(function (t) {
        return '<span class="dot" style="background:' + (TYPE_COLOR[t] || '#ccc') + '"></span>';
      }).join('');

      btn.innerHTML =
        '<span class="day-name">' + DAY_NAMES[d.getDay()] + '</span>' +
        '<span class="day-num">'  + d.getDate() + '</span>' +
        '<div class="day-dots">'  + dotsHTML + '</div>';

      btn.addEventListener('click', scrollToDate.bind(null, dateStr));
      container.appendChild(btn);
    }
  }

  function scrollToDate(dateStr) {
    var row = document.querySelector('.workout-row[data-date="' + dateStr + '"], .rest-day-row[data-date="' + dateStr + '"]');
    if (row) {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    // Fall back: scroll to the week section containing this date
    var sections = document.querySelectorAll('.week-section');
    for (var i = 0; i < sections.length; i++) {
      var s = sections[i];
      if (dateStr >= s.dataset.weekStart && dateStr <= s.dataset.weekEnd) {
        s.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
    }
  }

  // ── Date range resolution ─────────────────────────────────────────────────

  function getFromTo() {
    var today = todayYMD();
    if (state.range === 'all') return { from: '2000-01-01', to: today };
    var days = parseInt(state.range, 10);
    var from = new Date();
    from.setDate(from.getDate() - days + 1);
    from.setHours(0, 0, 0, 0);
    return { from: ymd(from), to: today };
  }

  // ── Mock API ──────────────────────────────────────────────────────────────
  // Simulates GET /api/training-log?from=&to=&types=&search=&include_rest=
  // Returns { weeks: [...] } matching the documented JSON shape.

  function mockFetch(params) {
    var allWorkouts = typeof MOCK_WORKOUTS !== 'undefined' ? MOCK_WORKOUTS : [];
    var allRestDays = typeof MOCK_REST_DAYS !== 'undefined' ? MOCK_REST_DAYS : [];

    var filtered = allWorkouts.filter(function (w) {
      if (w.date < params.from || w.date > params.to) return false;
      if (params.types && params.types !== 'all' && w.type !== params.types) return false;
      if (params.search) {
        var q = params.search.toLowerCase();
        var inTitle = w.title.toLowerCase().indexOf(q) !== -1;
        var inNotes = (w.notes || '').toLowerCase().indexOf(q) !== -1;
        if (!inTitle && !inNotes) return false;
      }
      return true;
    });

    var workoutDates = {};
    allWorkouts.forEach(function (w) {
      if (w.date >= params.from && w.date <= params.to) workoutDates[w.date] = true;
    });

    var filteredRest = [];
    if (!params.types || params.types === 'all') {
      filteredRest = allRestDays.filter(function (r) {
        if (r.date < params.from || r.date > params.to) return false;
        return !workoutDates[r.date];
      });
    }

    filtered.sort(function (a, b) { return b.date < a.date ? -1 : b.date > a.date ? 1 : 0; });
    filteredRest.sort(function (a, b) { return b.date < a.date ? -1 : b.date > a.date ? 1 : 0; });

    var weeksMap = {};
    var weekOrder = [];

    function getOrCreateWeek(dateStr) {
      var d = isoToDate(dateStr);
      var dow = d.getDay();
      var daysToMon = dow === 0 ? -6 : 1 - dow;
      var mon = new Date(d);
      mon.setDate(d.getDate() + daysToMon);
      var key = ymd(mon);
      if (!weeksMap[key]) {
        var sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);
        weeksMap[key] = {
          week_start: key,
          week_end: ymd(sun),
          label: weekLabel(mon),
          workouts: [],
          restDays: [],
        };
        weekOrder.push(key);
      }
      return key;
    }

    filtered.forEach(function (w) {
      var key = getOrCreateWeek(w.date);
      weeksMap[key].workouts.push(w);
    });

    filteredRest.forEach(function (r) {
      var key = getOrCreateWeek(r.date);
      weeksMap[key].restDays.push(r);
    });

    weekOrder.sort(function (a, b) { return b < a ? -1 : b > a ? 1 : 0; });

    var weeks = weekOrder.map(function (key) {
      var week = weeksMap[key];
      var ws = week.workouts;
      var entries = ws.concat(week.restDays);
      entries.sort(function (a, b) { return b.date < a.date ? -1 : b.date > a.date ? 1 : 0; });
      return {
        week_start: week.week_start,
        week_end: week.week_end,
        label: week.label,
        entries: entries,
        workouts: ws,
        summary: {
          workout_count:      ws.length,
          total_distance_km:  ws.reduce(function (s, w) { return s + (w.distance_km || 0); }, 0),
          total_tss:          ws.reduce(function (s, w) { return s + (w.tss || 0); }, 0),
          total_time_minutes: ws.reduce(function (s, w) { return s + (w.duration_minutes || 0); }, 0),
        },
      };
    });

    return { weeks: weeks };
  }

  // ── Formatters ────────────────────────────────────────────────────────────

  function fmtDuration(minutes) {
    var h = Math.floor(minutes / 60);
    var m = minutes % 60;
    if (h === 0) return m + 'm';
    return m === 0 ? h + 'h' : h + 'h ' + m + 'm';
  }

  function fmtPace(distKm, durMin) {
    if (!distKm) return '';
    var secPerKm = (durMin * 60) / distKm;
    var pMin = Math.floor(secPerKm / 60);
    var pSec = String(Math.round(secPerKm % 60)).padStart(2, '0');
    return pMin + ':' + pSec + '/km';
  }

  function metaLine(w) {
    var parts = [fmtDuration(w.duration_minutes)];
    if (w.distance_km) parts.push(w.distance_km + ' km');
    if (w.type === 'run'  && w.distance_km) parts.push(fmtPace(w.distance_km, w.duration_minutes));
    if (w.type === 'bike' && w.distance_km) {
      parts.push(((w.distance_km / w.duration_minutes) * 60).toFixed(1) + ' km/h');
    }
    if (w.weight_context) parts.push(w.weight_context);
    if (w.avg_hr) parts.push(w.avg_hr + ' bpm avg');
    return parts.join(' · ');
  }

  function primaryMetric(w) {
    if (w.distance_km) return w.distance_km + ' km';
    if (w.weight_context) return w.weight_context;
    return fmtDuration(w.duration_minutes);
  }

  function tssPillClass(tss) {
    if (!tss || tss <= 50) return 'tss-grey';
    if (tss <= 80) return 'tss-amber';
    return 'tss-red';
  }

  // ── Renderers ─────────────────────────────────────────────────────────────

  function renderRestDayRow(entry) {
    var d = isoToDate(entry.date);
    var m = entry.metrics || {};
    var sleep_hours = entry.sleep_hours != null ? entry.sleep_hours : m.sleep_hours;
    var energy      = entry.energy     != null ? entry.energy     : m.energy;
    var mood        = entry.mood       != null ? entry.mood       : m.mood;
    var resting_hr  = entry.resting_hr != null ? entry.resting_hr : m.resting_hr;
    var hrv         = m.hrv;
    var notes       = m.notes;

    var parts = [];
    if (sleep_hours != null) parts.push('sleep ' + sleep_hours + 'h');
    if (energy != null)      parts.push('energy ' + energy);
    if (mood != null)        parts.push('mood ' + mood);
    var label = 'Rest day' + (parts.length ? ' - ' + parts.join(', ') : '');

    var notesPart = '';
    if (notes) {
      var truncated = notes.length > 80 ? notes.slice(0, 80) + '…' : notes;
      notesPart = '<span class="rest-notes">' + escHtml(truncated) + '</span>';
    }

    var div = document.createElement('div');
    div.className = 'rest-day-row';
    div.dataset.date = entry.date;

    div.innerHTML =
      '<div class="workout-date-col">' +
        '<span class="workout-day-num">'  + d.getDate() + '</span>' +
        '<span class="workout-day-name">' + DAY_NAMES[d.getDay()] + '</span>' +
      '</div>' +
      '<span class="rest-badge">Rest</span>' +
      '<div class="rest-metrics">' +
        '<span class="rest-day-label">' + escHtml(label) + '</span>' +
        notesPart +
      '</div>';

    return div;
  }

  function renderWorkoutRow(w) {
    var d = isoToDate(w.date);
    var badgeBg    = TYPE_BADGE_BG[w.type]    || '#f0f0f0';
    var badgeColor = TYPE_BADGE_COLOR[w.type] || '#555';
    var typeLabel  = TYPE_LABEL[w.type]       || w.type;

    var div = document.createElement('div');
    div.className = 'workout-row';
    div.dataset.date = w.date;

    div.innerHTML =
      '<div class="workout-date-col">' +
        '<span class="workout-day-num">'  + d.getDate() + '</span>' +
        '<span class="workout-day-name">' + DAY_NAMES[d.getDay()] + '</span>' +
      '</div>' +
      '<span class="workout-type-badge" style="background:' + badgeBg + ';color:' + badgeColor + '">' + typeLabel + '</span>' +
      '<div class="workout-info">' +
        '<div class="workout-title">'     + escHtml(w.title)       + '</div>' +
        '<div class="workout-meta-line">' + metaLine(w)             + '</div>' +
      '</div>' +
      '<div class="workout-primary-metric">' + primaryMetric(w) + '</div>' +
      '<span class="tss-pill ' + tssPillClass(w.tss) + '">' + (w.tss ? 'TSS ' + w.tss : '—') + '</span>' +
      '<span class="source-pill source-' + (w.source || 'manual').toLowerCase() + '">' + ((w.source || '').toLowerCase() === 'strava' ? 'Strava' : 'Manual') + '</span>' +
      '<span class="workout-chevron">›</span>';

    // Row click — detail panel ships in a follow-up ticket
    div.addEventListener('click', function () {
      console.log('workout:select', w.id, w.title);
    });
    return div;
  }

  function renderWeekSection(week) {
    var s = week.summary;
    var summaryItems = [s.workout_count + ' workout' + (s.workout_count !== 1 ? 's' : '')];
    if (s.total_distance_km > 0) summaryItems.push(s.total_distance_km.toFixed(1) + ' km');
    summaryItems.push('TSS ' + Math.round(s.total_tss));
    summaryItems.push(fmtDuration(Math.round(s.total_time_minutes)));

    var weekStartDate = isoToDate(week.week_start);
    var weekHeading   = 'Week ' + isoWeekNum(weekStartDate);
    var dateRange     = weekDateRange(week.week_start, week.week_end);

    var section = document.createElement('section');
    section.className = 'week-section';
    section.dataset.weekStart = week.week_start;
    section.dataset.weekEnd   = week.week_end;
    section.id = 'week-' + week.week_start;

    var header = document.createElement('div');
    header.className = 'week-section-header';
    header.innerHTML =
      '<div class="week-section-label-group">' +
        '<span class="week-section-label">' + weekHeading + '</span>' +
        '<span class="week-section-daterange">' + dateRange + '</span>' +
      '</div>' +
      '<div class="week-section-summary">' +
        summaryItems.map(function (t) { return '<span>' + t + '</span>'; }).join('') +
      '</div>';
    section.appendChild(header);

    var rows = document.createElement('div');
    rows.className = 'workout-rows';
    (week.entries || week.workouts).forEach(function (e) {
      rows.appendChild(e.type === 'rest' ? renderRestDayRow(e) : renderWorkoutRow(e));
    });
    section.appendChild(rows);

    return section;
  }

  function renderList(weeks) {
    var list = document.getElementById('workout-list');
    var emptyMsg = document.getElementById('log-empty-msg');
    // Remove loading-msg and any previous week sections
    Array.from(list.children).forEach(function (child) {
      if (child.id !== 'log-empty-msg') child.remove();
    });

    if (!weeks || weeks.length === 0) {
      if (emptyMsg) {
        var titleEl = emptyMsg.querySelector('.empty-state-title');
        var descEl  = emptyMsg.querySelector('.empty-state-desc');
        var ctaEl   = document.getElementById('log-empty-cta');
        var hasFilters = state.search || state.type !== 'all' || state.range !== '30d';
        if (titleEl) titleEl.textContent = hasFilters ? 'No workouts in this range' : 'No workouts here yet';
        if (descEl)  descEl.textContent  = hasFilters ? 'Try adjusting your filters or date range.' : 'Log your first workout to start tracking your training.';
        if (ctaEl)   ctaEl.style.display = hasFilters ? 'none' : '';
        emptyMsg.style.display = '';
      }
      return;
    }

    if (emptyMsg) emptyMsg.style.display = 'none';
    weeks.forEach(function (week) { list.appendChild(renderWeekSection(week)); });
  }

  // ── Apply filters ─────────────────────────────────────────────────────────

  async function applyFilters() {
    syncToURL();
    var list = document.getElementById('workout-list');
    var emptyMsg = document.getElementById('log-empty-msg');
    // Show loading, hide empty state, clear previous results
    Array.from(list.children).forEach(function (child) {
      if (child.id !== 'log-empty-msg') child.remove();
    });
    if (emptyMsg) emptyMsg.style.display = 'none';
    var loadingEl = document.createElement('div');
    loadingEl.className = 'skeleton-list';
    loadingEl.innerHTML =
      '<div class="skeleton-row"></div>' +
      '<div class="skeleton-row"></div>' +
      '<div class="skeleton-row"></div>';
    list.insertBefore(loadingEl, emptyMsg || null);

    var range = getFromTo();
    var data;

    try {
      var url = '/api/training-log?from=' + range.from + '&to=' + range.to +
        (state.type !== 'all' ? '&types=' + encodeURIComponent(state.type) : '') +
        (state.search ? '&search=' + encodeURIComponent(state.search) : '');
      var res = await fetch(url);
      if (!res.ok) throw new Error('server error');
      data = await res.json();
    } catch (_) {
      data = mockFetch({ from: range.from, to: range.to, types: state.type, search: state.search });
    }

    visibleWorkouts = (data.weeks || []).reduce(function (acc, w) { return acc.concat(w.workouts); }, []);

    // Rebuild dot index from the loaded workouts (all non-rest entries in the response)
    var newDotsByDate = {};
    (data.weeks || []).forEach(function (week) {
      (week.workouts || []).forEach(function (w) {
        if (!newDotsByDate[w.date]) newDotsByDate[w.date] = [];
        if (newDotsByDate[w.date].indexOf(w.type) === -1) newDotsByDate[w.date].push(w.type);
      });
    });
    allWorkoutsByDate = newDotsByDate;

    setSyncText(visibleWorkouts);
    renderList(data.weeks || []);
    renderWeekStrip();
  }

  // ── Export CSV ────────────────────────────────────────────────────────────

  function csvField(val) {
    var s = val == null ? '' : String(val);
    if (s.indexOf(',') !== -1 || s.indexOf('"') !== -1 || s.indexOf('\n') !== -1) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }

  function exportCSV() {
    var range = getFromTo();
    var rows = [['date', 'type', 'title', 'distance_km', 'duration_minutes', 'tss', 'avg_hr', 'source'].join(',')];
    visibleWorkouts.forEach(function (w) {
      rows.push([
        csvField(w.date),
        csvField(w.type),
        csvField(w.title),
        csvField(w.distance_km != null ? w.distance_km : ''),
        csvField(w.duration_minutes != null ? w.duration_minutes : ''),
        csvField(w.tss != null ? w.tss : ''),
        csvField(w.avg_hr != null ? w.avg_hr : ''),
        csvField(w.source),
      ].join(','));
    });

    var blob = new Blob([rows.join('\r\n')], { type: 'text/csv' });
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href     = url;
    a.download = 'training-log-' + range.from + '-to-' + range.to + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Utility ───────────────────────────────────────────────────────────────

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Event listeners ───────────────────────────────────────────────────────

  function setupListeners() {
    document.getElementById('week-prev').addEventListener('click', function () {
      state.weekOffset--;
      renderWeekStrip();
    });

    document.getElementById('week-next').addEventListener('click', function () {
      state.weekOffset++;
      renderWeekStrip();
    });

    var searchTimeout;
    document.getElementById('search-input').addEventListener('input', function (e) {
      clearTimeout(searchTimeout);
      var val = e.target.value;
      searchTimeout = setTimeout(function () {
        state.search = val.trim();
        applyFilters();
      }, 300);
    });

    document.querySelectorAll('.type-filter-chip').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('.type-filter-chip').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.type = btn.dataset.type;
        applyFilters();
      });
    });

    document.getElementById('date-range').addEventListener('change', function (e) {
      state.range = e.target.value;
      applyFilters();
    });

    document.getElementById('log-export-btn').addEventListener('click', exportCSV);

    document.getElementById('log-workout-btn').addEventListener('click', function () {
      location.href = 'training.html';
    });
  }

  // ── Sync subtitle ─────────────────────────────────────────────────────────

  function setSyncText(workoutsForSync) {
    var el = document.getElementById('log-sync-sub');
    if (!el) return;
    var source = workoutsForSync;
    if (!source || source.length === 0) {
      source = typeof MOCK_WORKOUTS !== 'undefined' ? MOCK_WORKOUTS : [];
    }
    if (source.length === 0) return;
    var latest = source.slice().sort(function (a, b) { return b.date < a.date ? -1 : 1; })[0];
    var d = isoToDate(latest.date);
    el.textContent = 'Last synced: ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    setSyncText(null); // initial render with mock data; will be updated after API call
    loadFromURL();
    setupListeners();
    renderWeekStrip();
    applyFilters();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
