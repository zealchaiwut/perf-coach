(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var filters = { type: 'all', search: '', from: '', to: '' };

  // ── Helpers ───────────────────────────────────────────────────────────────
  function pad(n) { return String(n).padStart(2, '0'); }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function addDays(iso, n) {
    var d = new Date(iso + 'T00:00:00');
    d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  var MONTHS   = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var DAY_ABBR = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // Format duration for workout row meta: m:ss under 1h, h:mm:ss otherwise
  function fmtDurationRow(secs) {
    if (!secs || secs <= 0) return '';
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = Math.round(secs % 60);
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  // Format total time for week summary: h:mm
  function fmtTotalTime(totalMinutes) {
    if (!totalMinutes || totalMinutes <= 0) return '';
    var h = Math.floor(totalMinutes / 60);
    var m = Math.round(totalMinutes % 60);
    return h + ':' + pad(m);
  }

  function fmtPace(secsPerKm) {
    if (!secsPerKm) return '';
    var m = Math.floor(secsPerKm / 60), s = Math.round(secsPerKm % 60);
    return m + ':' + pad(s) + ' /km';
  }

  // Format a date "26 May" or "1 Jun"
  function fmtShortDate(isoStr) {
    var d = new Date(isoStr + 'T00:00:00');
    return d.getDate() + ' ' + MONTHS[d.getMonth()];
  }

  // ── URL sync ──────────────────────────────────────────────────────────────
  function readURLParams() {
    var p = new URLSearchParams(window.location.search);
    filters.type   = p.get('type')   || 'all';
    filters.search = p.get('search') || '';
    filters.from   = p.get('from')   || '';
    filters.to     = p.get('to')     || '';
  }

  function writeURLParams() {
    var p = new URLSearchParams();
    if (filters.type && filters.type !== 'all') p.set('type',   filters.type);
    if (filters.search)                          p.set('search', filters.search);
    if (filters.from)                            p.set('from',   filters.from);
    if (filters.to)                              p.set('to',     filters.to);
    var qs = p.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }

  // ── Date-range chip label ─────────────────────────────────────────────────
  function drLabel() {
    if (filters.from && filters.to)  return filters.from + ' – ' + filters.to;
    if (filters.from)                return 'From ' + filters.from;
    if (filters.to)                  return 'To ' + filters.to;
    return 'Last 30 days';
  }

  // ── Build filter bar ──────────────────────────────────────────────────────
  function buildFilterBar() {
    var bar = document.getElementById('filter-bar');
    if (!bar) return;

    var searchWrap = document.createElement('div');
    searchWrap.className = 'fb-search-wrap';
    var searchInput = document.createElement('input');
    searchInput.type        = 'text';
    searchInput.id          = 'log-search';
    searchInput.placeholder = 'Search workouts';
    searchInput.value       = filters.search;
    searchWrap.appendChild(searchInput);
    bar.appendChild(searchWrap);

    var chipsRow = document.createElement('div');
    chipsRow.className = 'fb-chips-row';
    var TYPE_OPTS   = ['all','run','lift','wod','bike'];
    var TYPE_LABELS = { all:'All', run:'Run', lift:'Lift', wod:'WOD', bike:'Bike' };
    TYPE_OPTS.forEach(function (t) {
      var chip = document.createElement('button');
      chip.type        = 'button';
      chip.className   = 'type-chip' + (t === filters.type ? ' active' : '');
      chip.dataset.type = t;
      chip.textContent = TYPE_LABELS[t];
      chip.addEventListener('click', function () {
        filters.type = t;
        document.querySelectorAll('.type-chip').forEach(function (c) {
          c.classList.toggle('active', c.dataset.type === t);
        });
        writeURLParams();
        fetchAndRender();
      });
      chipsRow.appendChild(chip);
    });
    bar.appendChild(chipsRow);

    var drWrap  = document.createElement('div');
    drWrap.className = 'fb-daterange-wrap';

    var drChip  = document.createElement('button');
    drChip.type = 'button';
    drChip.id   = 'dr-chip';
    drChip.className = 'dr-chip';
    drChip.setAttribute('aria-expanded', 'false');
    drChip.textContent = drLabel() + ' ▾';

    var drPanel = document.createElement('div');
    drPanel.id     = 'dr-panel';
    drPanel.className = 'dr-panel';
    drPanel.hidden = true;

    var fromLabel = document.createElement('label');
    fromLabel.textContent = 'From';
    fromLabel.htmlFor = 'dr-from';
    var fromInput = document.createElement('input');
    fromInput.type  = 'date';
    fromInput.id    = 'dr-from';
    fromInput.value = filters.from;

    var toLabel = document.createElement('label');
    toLabel.textContent = 'To';
    toLabel.htmlFor = 'dr-to';
    var toInput = document.createElement('input');
    toInput.type  = 'date';
    toInput.id    = 'dr-to';
    toInput.value = filters.to;

    var applyBtn = document.createElement('button');
    applyBtn.type      = 'button';
    applyBtn.className = 'btn-sm';
    applyBtn.textContent = 'Apply';

    drPanel.appendChild(fromLabel);
    drPanel.appendChild(fromInput);
    drPanel.appendChild(toLabel);
    drPanel.appendChild(toInput);
    drPanel.appendChild(applyBtn);
    drWrap.appendChild(drChip);
    drWrap.appendChild(drPanel);
    bar.appendChild(drWrap);

    var loadingEl = document.createElement('span');
    loadingEl.id        = 'log-loading-indicator';
    loadingEl.className = 'log-loading-indicator';
    loadingEl.hidden    = true;
    loadingEl.setAttribute('role', 'status');
    loadingEl.setAttribute('aria-live', 'polite');
    loadingEl.textContent = 'Loading…';
    bar.appendChild(loadingEl);

    var searchTimer;
    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        filters.search = searchInput.value;
        writeURLParams();
        fetchAndRender();
      }, 300);
    });

    drChip.addEventListener('click', function (e) {
      e.stopPropagation();
      var nowOpen = drPanel.hidden;
      drPanel.hidden = !nowOpen;
      drChip.setAttribute('aria-expanded', String(nowOpen));
    });

    applyBtn.addEventListener('click', function () {
      filters.from = fromInput.value;
      filters.to   = toInput.value;
      drPanel.hidden = true;
      drChip.setAttribute('aria-expanded', 'false');
      drChip.textContent = drLabel() + ' ▾';
      writeURLParams();
      fetchAndRender();
    });

    document.addEventListener('click', function (e) {
      if (!drPanel.hidden && !drPanel.contains(e.target) && e.target !== drChip) {
        drPanel.hidden = true;
        drChip.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // ── Fetch & render ────────────────────────────────────────────────────────
  function fetchAndRender() {
    var loadingEl = document.getElementById('log-loading-indicator');
    var listEl    = document.getElementById('log-list');
    if (loadingEl) loadingEl.hidden = false;
    if (listEl) listEl.innerHTML = '<p class="log-empty">Loading workouts...</p>';

    var today = todayISO();
    var params = new URLSearchParams();

    var userId = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (userId) params.set('user_id', userId);

    if (filters.type && filters.type !== 'all') params.set('types', filters.type);
    if (filters.search) params.set('search', filters.search);
    params.set('from', filters.from || addDays(today, -29));
    params.set('to',   filters.to   || today);

    fetch('/api/training-log?' + params.toString())
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        renderList(listEl, data.weeks || []);
      })
      .catch(function () {
        if (listEl) listEl.innerHTML = '<p class="log-error">Failed to load workouts.</p>';
      })
      .finally(function () {
        if (loadingEl) loadingEl.hidden = true;
      });
  }

  // ── Log list rendering ────────────────────────────────────────────────────
  function renderList(container, weeks) {
    if (!container) return;
    container.innerHTML = '';

    // Filter out weeks that have only rest entries
    var workoutWeeks = weeks.filter(function (wk) {
      return (wk.entries || []).some(function (e) { return e.type !== 'rest'; });
    });

    if (!workoutWeeks.length) {
      var msg = document.createElement('p');
      msg.className   = 'log-empty';
      msg.textContent = 'No workouts in this range.';
      container.appendChild(msg);
      return;
    }
    workoutWeeks.forEach(function (week) { container.appendChild(buildWeekGroup(week)); });
  }

  function buildWeekGroup(week) {
    var s = week.summary || {};
    var dateRange = '';
    if (week.week_start && week.week_end) {
      dateRange = fmtShortDate(week.week_start) + ' – ' + fmtShortDate(week.week_end);
    }

    var count = s.workout_count || 0;
    var countStr = count + ' workout' + (count !== 1 ? 's' : '');
    var totalTime = fmtTotalTime(s.total_time_minutes);

    var summaryParts = [countStr];
    var dist = s.total_distance_km;
    if (dist && dist > 0) summaryParts.push((+dist).toFixed(1) + ' km');
    if (s.total_tss > 0) summaryParts.push('TSS ' + (+s.total_tss).toFixed(0));
    if (totalTime) summaryParts.push(totalTime);

    var groupEl = document.createElement('div');
    groupEl.className = 'week-group';

    var header = document.createElement('div');
    header.className = 'week-group-header';

    var titleEl = document.createElement('div');
    titleEl.className = 'week-group-title';
    titleEl.textContent = week.label || '';

    var rangeEl = document.createElement('div');
    rangeEl.className = 'week-group-daterange';
    rangeEl.textContent = dateRange;

    var summaryEl = document.createElement('div');
    summaryEl.className = 'week-group-summary';
    summaryParts.forEach(function (part, i) {
      if (i > 0) {
        var sep = document.createElement('span');
        sep.className = 'summary-sep';
        sep.textContent = '·';
        summaryEl.appendChild(sep);
      }
      var span = document.createElement('span');
      span.textContent = part;
      summaryEl.appendChild(span);
    });

    header.appendChild(titleEl);
    header.appendChild(rangeEl);
    header.appendChild(summaryEl);
    groupEl.appendChild(header);

    var workoutEntries = (week.entries || []).filter(function (e) { return e.type !== 'rest'; });
    workoutEntries.forEach(function (entry) { groupEl.appendChild(buildEntryRow(entry)); });

    return groupEl;
  }

  function buildEntryRow(w) {
    var row = document.createElement('div');
    row.className = 'entry-row';
    row.style.cursor = 'pointer';
    row.addEventListener('click', function () {
      console.log(w.id);
    });

    // Date column
    var dateCol = document.createElement('div');
    dateCol.className = 'entry-date';
    var d = new Date((w.date || '') + 'T00:00:00');
    var dayNumEl = document.createElement('div');
    dayNumEl.className = 'entry-day-num';
    dayNumEl.textContent = isNaN(d.getDate()) ? '' : d.getDate();
    var dayNameEl = document.createElement('div');
    dayNameEl.className = 'entry-day-name';
    dayNameEl.textContent = isNaN(d.getDay()) ? '' : DAY_ABBR[d.getDay()];
    dateCol.appendChild(dayNumEl);
    dateCol.appendChild(dayNameEl);

    // Type badge
    var typeKey = (w.type || '').toLowerCase();
    var TYPE_LABELS = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
    var badge = document.createElement('span');
    badge.className = 'entry-badge entry-badge--' + (TYPE_LABELS[typeKey] ? typeKey : 'other');
    badge.textContent = TYPE_LABELS[typeKey] || (w.type || '');

    // Body (title + meta)
    var body = document.createElement('div');
    body.className = 'entry-body';

    var titleEl = document.createElement('div');
    titleEl.className = 'entry-title';
    titleEl.textContent = w.title || 'Workout';
    body.appendChild(titleEl);

    var metaParts = [];
    if (w.duration_seconds) metaParts.push(fmtDurationRow(w.duration_seconds));
    if (typeKey === 'run' && w.distance_km != null && w.duration_seconds) {
      metaParts.push(fmtPace(w.average_pace_seconds_per_km));
    }
    if (w.avg_hr != null) metaParts.push('HR ' + w.avg_hr);

    // Filter out any empty strings
    metaParts = metaParts.filter(Boolean);

    if (metaParts.length) {
      var metaEl = document.createElement('div');
      metaEl.className = 'entry-meta';
      metaEl.textContent = metaParts.join(' · ');
      body.appendChild(metaEl);
    }

    // Primary metric
    var metricEl = document.createElement('div');
    metricEl.className = 'entry-metric';
    if (typeKey === 'run' && w.distance_km != null) {
      metricEl.textContent = (+w.distance_km).toFixed(1) + ' km';
    } else if (w.duration_seconds) {
      var mins = Math.round(w.duration_seconds / 60);
      metricEl.textContent = mins + ' min';
    }

    // TSS pill
    var tssEl = null;
    if (w.tss != null) {
      tssEl = document.createElement('span');
      var tc = w.tss > 80 ? 'tss-high' : w.tss > 50 ? 'tss-mid' : 'tss-low';
      tssEl.className = 'tss-pill ' + tc;
      tssEl.textContent = 'TSS ' + Math.round(w.tss);
    }

    // Source pill
    var sourceEl = document.createElement('span');
    sourceEl.className = 'source-pill';
    var src = (w.source || w.tss_source || '').toLowerCase();
    sourceEl.textContent = src === 'strava' ? 'Strava' : 'Manual';

    row.appendChild(dateCol);
    row.appendChild(badge);
    row.appendChild(body);
    row.appendChild(metricEl);
    if (tssEl) row.appendChild(tssEl);
    row.appendChild(sourceEl);

    return row;
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    readURLParams();
    buildFilterBar();
    fetchAndRender();

    window.addEventListener('userChanged', function () {
      fetchAndRender();
    });

    var exportBtn = document.getElementById('log-export-btn');
    if (exportBtn) exportBtn.addEventListener('click', function () {
      alert('Export coming soon.');
    });

    var newBtn = document.getElementById('log-new-btn');
    if (newBtn) newBtn.addEventListener('click', function () {
      window.location.href = 'training.html';
    });
  });

}());
