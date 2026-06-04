(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var filters               = { type: 'all', search: '', from: '', to: '' };
  var lastWeeks             = [];
  var flatWorkouts          = [];   // ordered array of { id, title, type } for navigation
  var activePosIndex        = -1;   // position in flatWorkouts of open workout
  var activeDetailWorkoutId = null;
  var activeTriggerEl       = null;
  var activeRowEl           = null;

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

  function csvField(val) {
    var s = val == null ? '' : String(val);
    if (s.indexOf(',') !== -1 || s.indexOf('"') !== -1 || s.indexOf('\n') !== -1 || s.indexOf('\r') !== -1) {
      return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }

  function fmtDurationRow(secs) {
    if (!secs || secs <= 0) return '';
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = Math.round(secs % 60);
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  function fmtTotalTime(totalMinutes) {
    if (!totalMinutes || totalMinutes <= 0) return '';
    var h = Math.floor(totalMinutes / 60);
    var m = Math.round(totalMinutes % 60);
    return h + ':' + pad(m);
  }

  function fmtDuration(secs) {
    if (!secs) return '';
    var h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
    if (h > 0 && m > 0) return h + 'h ' + m + 'min';
    if (h > 0) return h + 'h';
    return m + 'min';
  }

  function fmtPace(secsPerKm) {
    if (!secsPerKm) return '';
    var m = Math.floor(secsPerKm / 60), s = Math.round(secsPerKm % 60);
    return m + ':' + pad(s) + ' /km';
  }

  function fmtShortDate(isoStr) {
    var d = new Date(isoStr + 'T00:00:00');
    return d.getDate() + ' ' + MONTHS[d.getMonth()];
  }

  function fmtDurationDetail(secs) {
    if (secs == null) return '—';
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  function fmtPaceFromSec(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var secsPerKm = durSeconds / distKm;
    var pm = Math.floor(secsPerKm / 60);
    var ps = Math.round(secsPerKm % 60);
    return pm + ':' + pad(ps) + ' /km';
  }

  function fmtSpeedKmh(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var speed = distKm / (durSeconds / 3600);
    return speed.toFixed(1) + ' km/h';
  }

  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return DAY_ABBR[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
  }

  function em() { return '—'; }

  // ── URL sync ──────────────────────────────────────────────────────────────
  function readURLParams() {
    var p = new URLSearchParams(window.location.search);
    filters.type   = p.get('type')   || 'all';
    filters.search = p.get('search') || '';
    filters.from   = p.get('from')   || '';
    filters.to     = p.get('to')     || '';
  }

  function writeURLParams() {
    var p = new URLSearchParams(window.location.search);
    if (filters.type && filters.type !== 'all') p.set('type', filters.type);
    else p.delete('type');
    if (filters.search) p.set('search', filters.search);
    else p.delete('search');
    if (filters.from) p.set('from', filters.from);
    else p.delete('from');
    if (filters.to) p.set('to', filters.to);
    else p.delete('to');
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

  // ── Header stats subtitle ─────────────────────────────────────────────────
  function updateHeaderStats(data) {
    var subtitleEl = document.getElementById('log-subtitle');
    if (!subtitleEl) return;
    var weeks = data.weeks || [];
    var totalCount = 0, totalTSS = 0, totalMinutes = 0;
    weeks.forEach(function (week) {
      var s = week.summary || {};
      totalCount   += (s.workout_count      || 0);
      totalTSS     += (s.total_tss          || 0);
      totalMinutes += (s.total_time_minutes || 0);
    });
    var parts = [totalCount + ' workout' + (totalCount !== 1 ? 's' : '')];
    if (totalTSS > 0) parts.push('TSS ' + Math.round(totalTSS));
    if (totalMinutes > 0) {
      var h = Math.floor(totalMinutes / 60);
      var m = Math.round(totalMinutes % 60);
      parts.push(h > 0 ? h + 'h ' + m + 'm' : m + 'm');
    }
    subtitleEl.textContent = parts.join(' · ');
  }

  // ── Build filter bar ──────────────────────────────────────────────────────
  function buildFilterBar() {
    var bar = document.getElementById('filter-bar');
    if (!bar) return;

    var searchWrap = document.createElement('div');
    searchWrap.className = 'fb-search-wrap';
    var searchInput = document.createElement('input');
    searchInput.type         = 'text';
    searchInput.id           = 'log-search';
    searchInput.placeholder  = 'Search workouts';
    searchInput.value        = filters.search;
    searchInput.spellcheck   = false;
    searchInput.autocomplete = 'off';
    searchWrap.appendChild(searchInput);
    bar.appendChild(searchWrap);

    var chipsRow = document.createElement('div');
    chipsRow.className = 'fb-chips-row';
    var TYPE_OPTS   = ['all','run','lift','wod','bike'];
    var TYPE_LABELS = { all:'All', run:'Run', lift:'Lift', wod:'WOD', bike:'Bike' };
    TYPE_OPTS.forEach(function (t) {
      var chip = document.createElement('button');
      chip.type         = 'button';
      chip.className    = 'type-chip' + (t === filters.type ? ' active' : '');
      chip.dataset.type = t;
      chip.textContent  = TYPE_LABELS[t];
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

    var divider = document.createElement('div');
    divider.className = 'fb-divider';
    divider.setAttribute('aria-hidden', 'true');
    bar.appendChild(divider);

    var drWrap = document.createElement('div');
    drWrap.className = 'fb-daterange-wrap';

    var drChip = document.createElement('button');
    drChip.type      = 'button';
    drChip.id        = 'dr-chip';
    drChip.className = 'dr-chip';
    drChip.setAttribute('aria-expanded', 'false');
    drChip.textContent = drLabel() + ' ▾';

    var drPanel = document.createElement('div');
    drPanel.id      = 'dr-panel';
    drPanel.className = 'dr-panel';
    drPanel.hidden  = true;

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

  // ── List state helpers ────────────────────────────────────────────────────
  function hideListMessages() {
    var errEl   = document.getElementById('log-error-msg');
    var emptyEl = document.getElementById('log-empty-msg');
    if (errEl)   errEl.style.display   = 'none';
    if (emptyEl) emptyEl.style.display = 'none';
  }

  function showListSkeleton() {
    var listEl = document.getElementById('log-list');
    if (!listEl) return;
    var html = '';
    for (var i = 0; i < 5; i++) {
      html += '<div class="skeleton-row"></div>';
    }
    listEl.innerHTML = html;
  }

  function renderListError() {
    var listEl = document.getElementById('log-list');
    var errEl  = document.getElementById('log-error-msg');
    if (listEl) listEl.innerHTML = '';
    if (errEl)  errEl.style.display = '';
  }

  // ── Flat workout list (for prev/next navigation) ──────────────────────────
  function buildFlatWorkouts() {
    flatWorkouts = [];
    lastWeeks.forEach(function (week) {
      var entries = (week.entries || []).slice().sort(function (a, b) {
        return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
      });
      entries.forEach(function (entry) {
        if (entry.type !== 'rest' && entry.id) {
          flatWorkouts.push({ id: entry.id, title: entry.title || 'Workout', type: entry.type });
        }
      });
    });
  }

  // ── Fetch & render ────────────────────────────────────────────────────────
  function fetchAndRender() {
    var loadingEl = document.getElementById('log-loading-indicator');
    if (loadingEl) loadingEl.hidden = false;

    hideListMessages();
    showListSkeleton();

    var today = todayISO();
    var params = new URLSearchParams();

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
        lastWeeks = data.weeks || [];
        buildFlatWorkouts();
        var listEl = document.getElementById('log-list');
        renderList(listEl, lastWeeks);
        updateHeaderStats(data);
        // Re-sync active row highlight if panel is still open
        if (activeDetailWorkoutId) {
          activePosIndex = findPosIndex(activeDetailWorkoutId);
          syncActiveRow();
          updatePositionPill();
        }
      })
      .catch(function (_) {
        renderListError();
      })
      .finally(function () {
        if (loadingEl) loadingEl.hidden = true;
      });
  }

  // ── Log list rendering ────────────────────────────────────────────────────
  function renderList(container, weeks) {
    if (!container) return;
    container.innerHTML = '';

    var hasFilters = filters.type !== 'all' || !!filters.search || !!filters.from || !!filters.to;

    if (!weeks.length) {
      if (!hasFilters) {
        var emptyEl = document.getElementById('log-empty-msg');
        if (emptyEl) emptyEl.style.display = '';
      } else {
        var msg = document.createElement('p');
        msg.className   = 'log-empty';
        msg.textContent = 'No workouts in this range — try widening your date filter.';
        container.appendChild(msg);
      }
      return;
    }

    hideListMessages();
    weeks.forEach(function (week) { container.appendChild(buildWeekGroup(week)); });
  }

  function renderRestDayRow(entry) {
    var row = document.createElement('div');
    row.className = 'rest-day-row';
    row.setAttribute('aria-label', 'Rest day');

    var dateCol = document.createElement('div');
    dateCol.className = 'entry-date';
    var d = new Date((entry.date || '') + 'T00:00:00');
    var dayNumEl = document.createElement('div');
    dayNumEl.className = 'entry-day-num';
    dayNumEl.textContent = isNaN(d.getDate()) ? '' : d.getDate();
    var dayNameEl = document.createElement('div');
    dayNameEl.className = 'entry-day-name';
    dayNameEl.textContent = isNaN(d.getDay()) ? '' : DAY_ABBR[d.getDay()];
    dateCol.appendChild(dayNumEl);
    dateCol.appendChild(dayNameEl);
    row.appendChild(dateCol);

    var iconEl = document.createElement('span');
    iconEl.className = 'rest-moon-icon';
    iconEl.setAttribute('aria-hidden', 'true');
    iconEl.textContent = '🌙';
    row.appendChild(iconEl);

    var info = document.createElement('div');
    info.className = 'rest-metrics';

    var labelParts = [];
    if (entry.sleep_hours != null) labelParts.push('sleep ' + entry.sleep_hours + 'h');
    if (entry.energy   != null)    labelParts.push('energy ' + entry.energy + '/5');
    if (entry.mood     != null)    labelParts.push('mood ' + entry.mood + '/5');
    if (entry.resting_hr != null)  labelParts.push('RHR ' + entry.resting_hr);

    var label = document.createElement('span');
    label.className = 'rest-day-label';
    label.textContent = 'Rest day' + (labelParts.length ? ' \xb7 ' + labelParts.join(', ') : '');
    info.appendChild(label);

    row.appendChild(info);
    return row;
  }

  function weekDisplayLabel(week) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var dow = today.getDay();
    var diff = dow === 0 ? -6 : 1 - dow;
    var thisMon = new Date(today);
    thisMon.setDate(thisMon.getDate() + diff);
    thisMon.setHours(0, 0, 0, 0);
    var lastMon = new Date(thisMon);
    lastMon.setDate(lastMon.getDate() - 7);
    var weekStart = new Date(week.week_start + 'T00:00:00');
    weekStart.setHours(0, 0, 0, 0);
    if (weekStart.getTime() === thisMon.getTime()) return 'THIS WEEK';
    if (weekStart.getTime() === lastMon.getTime()) return 'LAST WEEK';
    return week.label || '';
  }

  function buildWeekGroup(week) {
    var s  = week.summary || {};
    var ws = week.workouts || [];

    var dateRange = '';
    if (week.week_start && week.week_end) {
      dateRange = fmtShortDate(week.week_start) + ' – ' + fmtShortDate(week.week_end);
    }

    var count = s.workout_count || ws.length;
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
    header.className = 'week-header';

    var titleEl = document.createElement('div');
    titleEl.className = 'week-header-title';
    titleEl.textContent = weekDisplayLabel(week);

    var rangeEl = document.createElement('div');
    rangeEl.className = 'week-header-range';
    rangeEl.textContent = dateRange;

    var summaryEl = document.createElement('div');
    summaryEl.className = 'week-header-summary';
    summaryParts.forEach(function (part, i) {
      if (i > 0) {
        var sep = document.createElement('span');
        sep.className = 'summary-sep';
        sep.textContent = '\xb7';
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

    var card = document.createElement('div');
    card.className = 'week-card';

    var entries = (week.entries || []).slice().sort(function (a, b) {
      return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
    });
    entries.forEach(function (entry) {
      card.appendChild(entry.type === 'rest' ? renderRestDayRow(entry) : buildEntryRow(entry));
    });

    groupEl.appendChild(card);
    return groupEl;
  }

  function buildEntryRow(w) {
    var row = document.createElement('div');
    row.className = 'entry-row';
    if (w.id && activeDetailWorkoutId === w.id) {
      row.classList.add('is-active');
    }

    if (w.id) {
      row.setAttribute('tabindex', '0');
      row.dataset.workoutId = w.id;
      var rowRef = row;
      row.addEventListener('click', function () {
        openDetailPanel(w.id, rowRef);
      });
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openDetailPanel(w.id, rowRef);
        }
      });
    }

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

    var typeKey = (w.type || '').toLowerCase();
    var TYPE_LABELS = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
    var badge = document.createElement('span');
    badge.className = 'entry-badge entry-badge--' + (TYPE_LABELS[typeKey] ? typeKey : 'other');
    badge.textContent = TYPE_LABELS[typeKey] || (w.type || '');

    var body = document.createElement('div');
    body.className = 'entry-body';

    var titleEl = document.createElement('div');
    titleEl.className = 'entry-title';
    titleEl.textContent = w.title || 'Workout';
    body.appendChild(titleEl);

    var metaParts = [];
    if (w.duration_seconds) metaParts.push(fmtDurationRow(w.duration_seconds));
    if (typeKey === 'run' && w.average_pace_seconds_per_km) {
      metaParts.push(fmtPace(w.average_pace_seconds_per_km));
    }
    if (w.avg_hr != null) metaParts.push('HR ' + w.avg_hr);
    metaParts = metaParts.filter(Boolean);

    if (metaParts.length) {
      var metaEl = document.createElement('div');
      metaEl.className = 'entry-meta';
      metaEl.textContent = metaParts.join(' · ');
      body.appendChild(metaEl);
    }

    var metricEl = document.createElement('div');
    metricEl.className = 'entry-metric';
    var metricPrimary = document.createElement('div');
    metricPrimary.className = 'entry-metric-primary';
    var metricSecondary = document.createElement('div');
    metricSecondary.className = 'entry-metric-secondary';
    if (typeKey === 'run' && w.distance_km != null) {
      metricPrimary.textContent = (+w.distance_km).toFixed(1) + ' km';
      if (w.duration_seconds) metricSecondary.textContent = fmtDurationRow(w.duration_seconds);
    } else if (w.duration_seconds) {
      var mins = Math.round(w.duration_seconds / 60);
      metricPrimary.textContent = mins + ' min';
    }
    metricEl.appendChild(metricPrimary);
    if (metricSecondary.textContent) metricEl.appendChild(metricSecondary);

    var tssEl = null;
    if (w.tss != null) {
      tssEl = document.createElement('span');
      var tc = w.tss > 80 ? 'tss-high' : w.tss > 50 ? 'tss-mid' : 'tss-low';
      tssEl.className = 'tss-pill ' + tc;
      tssEl.textContent = 'TSS ' + Math.round(w.tss);
    }

    var sourcesWrap = document.createElement('div');
    sourcesWrap.className = 'source-badges-wrap';
    var srcStr = (w.source || 'manual');
    srcStr.split(',').forEach(function (s) {
      s = s.trim().toLowerCase();
      var sbadge = document.createElement('span');
      if (s === 'strava') {
        sbadge.className = 'source-badge source-badge--strava';
        sbadge.textContent = 'St';
      } else if (s === 'stryd') {
        sbadge.className = 'source-badge source-badge--stryd';
        sbadge.textContent = 'S';
      } else {
        sbadge.className = 'source-badge source-badge--manual';
        sbadge.setAttribute('aria-label', 'Manual');
        sbadge.innerHTML = '&#9998;';
      }
      sourcesWrap.appendChild(sbadge);
    });

    row.appendChild(dateCol);
    row.appendChild(badge);
    row.appendChild(body);
    row.appendChild(metricEl);
    if (tssEl) row.appendChild(tssEl);
    row.appendChild(sourcesWrap);

    return row;
  }

  // ── Sync active row highlight after list re-render ───────────────────────
  function syncActiveRow() {
    document.querySelectorAll('.entry-row').forEach(function (r) {
      r.classList.remove('is-active');
    });
    if (!activeDetailWorkoutId) return;
    var row = document.querySelector('.entry-row[data-workout-id="' + activeDetailWorkoutId + '"]');
    if (row) {
      activeRowEl = row;
      row.classList.add('is-active');
    }
  }

  // ── CSV Export ────────────────────────────────────────────────────────────
  function exportCSV() {
    var today    = todayISO();
    var fromDate = filters.from || today;
    var toDate   = filters.to   || today;
    var filename = 'training-log-' + fromDate + '-to-' + toDate + '.csv';

    var rows = ['date,type,title,distance_km,duration_minutes,avg_hr,tss,source'];
    lastWeeks.forEach(function (week) {
      (week.entries || []).forEach(function (entry) {
        if (entry.type === 'rest') return;
        rows.push([
          csvField(entry.date),
          csvField(entry.type),
          csvField(entry.title),
          csvField(entry.distance_km      != null ? entry.distance_km      : ''),
          csvField(entry.duration_seconds != null ? Math.round(entry.duration_seconds / 60 * 10) / 10 : ''),
          csvField(entry.avg_hr          != null ? entry.avg_hr          : ''),
          csvField(entry.tss             != null ? entry.tss             : ''),
          csvField(entry.source)
        ].join(','));
      });
    });

    var csv  = rows.join('\r\n');
    var blob = new Blob([csv], { type: 'text/csv' });
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href     = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Detail panel position helpers ─────────────────────────────────────────
  function findPosIndex(workoutId) {
    for (var i = 0; i < flatWorkouts.length; i++) {
      if (flatWorkouts[i].id === workoutId) return i;
    }
    return -1;
  }

  function updatePositionPill() {
    var pill    = document.getElementById('dp-position-pill');
    var prevBtn = document.getElementById('dp-prev-btn');
    var nextBtn = document.getElementById('dp-next-btn');
    var total   = flatWorkouts.length;

    if (pill) {
      pill.textContent = total > 0 ? (activePosIndex + 1) + ' of ' + total : '';
    }
    if (prevBtn) prevBtn.disabled = activePosIndex <= 0;
    if (nextBtn) nextBtn.disabled = activePosIndex >= total - 1;
  }

  function isDesktop() {
    return window.innerWidth >= 880;
  }

  // ── Detail panel open / close ─────────────────────────────────────────────
  function openDetailPanel(workoutId, triggerEl) {
    if (activeRowEl) activeRowEl.classList.remove('is-active');
    activeRowEl = triggerEl || null;
    if (activeRowEl) activeRowEl.classList.add('is-active');

    activeDetailWorkoutId = workoutId;
    activeTriggerEl       = triggerEl || null;
    activePosIndex        = findPosIndex(workoutId);

    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    var wrapper = document.getElementById('layout-wrapper');

    if (panel) panel.classList.add('is-open');

    if (isDesktop()) {
      if (wrapper) wrapper.classList.add('has-panel');
    } else {
      if (overlay) { overlay.classList.add('is-open'); overlay.removeAttribute('aria-hidden'); }
      document.body.style.overflow = 'hidden';
    }

    updatePositionPill();
    fetchAndRenderDetail(workoutId);
  }

  function closeDetailPanel() {
    if (activeRowEl) { activeRowEl.classList.remove('is-active'); activeRowEl = null; }

    var trigger = activeTriggerEl;
    activeDetailWorkoutId = null;
    activeTriggerEl       = null;
    activePosIndex        = -1;

    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    var wrapper = document.getElementById('layout-wrapper');

    if (panel)   panel.classList.remove('is-open');
    if (overlay) { overlay.classList.remove('is-open'); overlay.setAttribute('aria-hidden', 'true'); }
    if (wrapper) wrapper.classList.remove('has-panel');
    document.body.style.overflow = '';

    if (trigger) trigger.focus();
  }

  // ── Navigate prev / next ──────────────────────────────────────────────────
  function navigateDetail(direction) {
    var newIndex = activePosIndex + direction;
    if (newIndex < 0 || newIndex >= flatWorkouts.length) return;

    var fw = flatWorkouts[newIndex];
    activePosIndex        = newIndex;
    activeDetailWorkoutId = fw.id;

    syncActiveRow();
    updatePositionPill();
    fetchAndRenderDetail(fw.id);
  }

  // ── Fetch and render detail ───────────────────────────────────────────────
  function fetchAndRenderDetail(workoutId) {
    var loadingEl = document.getElementById('dp-loading');
    var errorEl   = document.getElementById('dp-error');
    var contentEl = document.getElementById('dp-content');
    var scrollEl  = document.getElementById('dp-scroll');

    if (loadingEl) loadingEl.style.display = '';
    if (errorEl)   errorEl.style.display   = 'none';
    if (contentEl) contentEl.innerHTML     = '';
    if (scrollEl)  scrollEl.scrollTop      = 0;

    var editBtn   = document.getElementById('dp-edit-btn');
    var stravaBtn = document.getElementById('dp-strava-btn');
    var deleteBtn = document.getElementById('dp-delete-btn');

    if (stravaBtn) stravaBtn.style.display = 'none';
    if (deleteBtn) deleteBtn.style.display = 'none';

    fetch('/api/workouts/' + workoutId)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (workout) {
        var isRun  = workout.workout_type === 'run';
        var isBike = workout.workout_type === 'bike';

        if (editBtn) editBtn.href = '/workout-edit/' + workout.id;

        var isStrava = (workout.source === 'strava') || !!workout.strava_activity_url;
        if (isStrava) {
          if (stravaBtn) {
            stravaBtn.href         = workout.strava_activity_url || '#';
            stravaBtn.style.display = '';
          }
        } else {
          if (deleteBtn) deleteBtn.style.display = '';
        }

        if (isRun || isBike) {
          fetch('/api/workouts/' + workoutId + '/splits')
            .then(function (r) { return r.ok ? r.json() : []; })
            .catch(function () { return []; })
            .then(function (splits) {
              if (loadingEl) loadingEl.style.display = 'none';
              renderDetailContent(workout, splits);
            });
        } else {
          if (loadingEl) loadingEl.style.display = 'none';
          renderDetailContent(workout, []);
        }
      })
      .catch(function (_) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl)   errorEl.style.display   = '';
        var retryBtn = document.getElementById('dp-retry-btn');
        if (retryBtn) {
          retryBtn.onclick = function () { fetchAndRenderDetail(workoutId); };
        }
      });
  }

  // ── Render detail content ─────────────────────────────────────────────────
  function renderDetailContent(workout, splits) {
    var contentEl = document.getElementById('dp-content');
    if (!contentEl) return;

    var typeKey  = (workout.workout_type || '').toLowerCase();
    var isRun    = typeKey === 'run';
    var isBike   = typeKey === 'bike';
    var isCardio = isRun || isBike;
    var exercises = workout.exercises || [];

    // ── Hero block ──────────────────────────────────────────────────────────
    var typeIcons = { run: '🏃', lift: '🏋️', wod: '🔥', bike: '🚴' };
    var typeLabels = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
    var iconChar  = typeIcons[typeKey]  || '💪';
    var typeLabel = typeLabels[typeKey] || (workout.workout_type || 'Workout').toUpperCase();

    var sourceHtml = '';
    var srcStr = (workout.source || 'manual');
    srcStr.split(',').forEach(function (s) {
      s = s.trim().toLowerCase();
      var cls, lbl;
      if (s === 'strava')      { cls = 'dp-src-badge--strava'; lbl = 'St'; }
      else if (s === 'stryd')  { cls = 'dp-src-badge--stryd';  lbl = 'S';  }
      else                     { cls = 'dp-src-badge--manual';  lbl = '✎'; }
      sourceHtml += '<span class="dp-src-badge ' + esc(cls) + '" title="' + esc(s) + '">' + esc(lbl) + '</span>';
    });

    var heroHtml =
      '<div class="dp-hero">' +
        '<div class="dp-hero-typebadge">' +
          '<div class="dp-icon-pill dp-icon-pill--' + esc(typeKey || 'other') + '">' + esc(iconChar) + '</div>' +
          '<span class="dp-type-pill">' + esc(typeLabel) + '</span>' +
        '</div>' +
        '<h1 id="dp-title">' + esc(workout.name || 'Workout') + '</h1>' +
        '<div class="dp-hero-meta">' +
          esc(fmtDate(workout.workout_date)) +
          (sourceHtml ? '<span class="dp-hero-sources">' + sourceHtml + '</span>' : '') +
        '</div>' +
      '</div>';

    // ── Stats grid 2×3 ──────────────────────────────────────────────────────
    var statsHtml = '';
    if (isCardio) {
      // First tile (highlighted): Distance
      var distStr = workout.distance_km != null ? (+workout.distance_km).toFixed(2) + '<span class="dp-stat-unit">km</span>' : '—';
      var durStr  = workout.duration_seconds != null ? esc(fmtDurationDetail(workout.duration_seconds)) : '—';
      var paceStr, paceUnit = '';
      if (workout.duration_seconds && workout.distance_km) {
        if (isBike) {
          paceStr = esc(fmtSpeedKmh(workout.duration_seconds, workout.distance_km));
        } else {
          var secsPerKm = workout.duration_seconds / workout.distance_km;
          var pm = Math.floor(secsPerKm / 60), ps = Math.round(secsPerKm % 60);
          paceStr = esc(pm + ':' + pad(ps)) + '<span class="dp-stat-unit">/km</span>';
        }
      } else {
        paceStr = '—';
      }
      var hrStr   = workout.avg_hr != null ? esc(workout.avg_hr) + '<span class="dp-stat-unit">bpm</span>' : '—';
      var elevStr = workout.elevation_m != null ? esc(workout.elevation_m) + '<span class="dp-stat-unit">m</span>' : '—';
      var tssStr  = workout.tss != null ? esc((+workout.tss).toFixed(0)) : '—';

      statsHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Stats</div>' +
          '<div class="dp-stats-grid">' +
            '<div class="dp-stat highlight"><div class="dp-stat-label">' + (isBike ? 'Distance' : 'Distance') + '</div><div class="dp-stat-value">' + distStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Duration</div><div class="dp-stat-value">' + durStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg ' + (isBike ? 'speed' : 'pace') + '</div><div class="dp-stat-value">' + paceStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg HR</div><div class="dp-stat-value">' + hrStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Elev</div><div class="dp-stat-value">' + elevStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">TSS</div><div class="dp-stat-value">' + tssStr + '</div></div>' +
          '</div>' +
        '</div>';
    } else {
      // Strength / WOD — first tile: Duration
      var durStr2  = workout.duration_seconds != null ? esc(fmtDurationDetail(workout.duration_seconds)) : '—';
      var exCount  = exercises.length;
      var totalReps = exercises.reduce(function (s, ex) {
        return s + (ex.sets || 0) * (ex.reps || 0);
      }, 0);
      var rpeExs  = exercises.filter(function (ex) { return ex.rpe != null; });
      var avgRpe  = rpeExs.length ? (rpeExs.reduce(function (s, ex) { return s + ex.rpe; }, 0) / rpeExs.length).toFixed(1) : null;
      var hrStr2  = workout.avg_hr != null ? esc(workout.avg_hr) + '<span class="dp-stat-unit">bpm</span>' : '—';
      var tssStr2 = workout.tss != null ? esc((+workout.tss).toFixed(0)) : '—';

      statsHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Stats</div>' +
          '<div class="dp-stats-grid">' +
            '<div class="dp-stat highlight"><div class="dp-stat-label">Duration</div><div class="dp-stat-value">' + durStr2 + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Exercises</div><div class="dp-stat-value">' + esc(String(exCount)) + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Total reps</div><div class="dp-stat-value">' + (totalReps > 0 ? esc(String(totalReps)) : '—') + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg RPE</div><div class="dp-stat-value">' + (avgRpe != null ? esc(avgRpe) : '—') + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg HR</div><div class="dp-stat-value">' + hrStr2 + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">TSS</div><div class="dp-stat-value">' + tssStr2 + '</div></div>' +
          '</div>' +
        '</div>';
    }

    // ── Intervals section (RUN with distance_km exercises) ──────────────────
    var intervalsHtml = '';
    if (isRun) {
      var intervalExs = exercises.filter(function (ex) {
        return ex.distance_km != null;
      });
      if (intervalExs.length) {
        var totalRepDist = 0, totalRepDur = 0;
        var hrExs = [], hrSum = 0;
        var rows = '';
        intervalExs.forEach(function (ex, i) {
          var distKm = parseFloat(ex.distance_km);
          var dur    = ex.duration_seconds;
          var hr     = ex.avg_hr;
          totalRepDist += distKm || 0;
          totalRepDur  += dur || 0;
          if (hr != null) { hrExs.push(hr); hrSum += hr; }

          var distFmt = distKm >= 1
            ? (+distKm).toFixed(1) + ' km'
            : Math.round(distKm * 1000) + 'm';
          var paceFmt = (dur && distKm) ? fmtPaceFromSec(dur, distKm) : '—';
          var hrFmt   = hr != null ? hr + ' bpm' : '—';

          rows +=
            '<div class="dp-interval-row">' +
              '<div class="dp-rep-badge">' + esc(String(i + 1)) + '</div>' +
              '<div>' +
                '<div class="dp-interval-name">' + esc(ex.name || 'Rep ' + (i + 1)) + '</div>' +
                '<div class="dp-interval-sub">' + esc(distFmt) + '</div>' +
              '</div>' +
              '<div>' +
                '<div class="dp-interval-pace">' + esc(paceFmt) + '</div>' +
              '</div>' +
              '<div class="dp-interval-hr">' + esc(hrFmt) + '</div>' +
            '</div>';
        });

        var avgRepPace = (totalRepDur && totalRepDist) ? fmtPaceFromSec(totalRepDur, totalRepDist) : '—';
        var avgRepHR   = hrExs.length ? Math.round(hrSum / hrExs.length) + ' bpm' : '—';

        intervalsHtml =
          '<div class="dp-section">' +
            '<div class="dp-section-title">Intervals · ' + esc(String(intervalExs.length)) + '×' + (function () {
              var d0 = parseFloat(intervalExs[0].distance_km);
              return d0 >= 1 ? (+d0).toFixed(1) + 'km' : Math.round(d0 * 1000) + 'm';
            })() + '</div>' +
            '<div class="dp-intervals">' +
              rows +
              '<div class="dp-interval-footer">' +
                '<span>Avg rep pace · avg HR</span>' +
                '<span><strong>' + esc(avgRepPace) + '</strong> · <strong>' + esc(avgRepHR) + '</strong></span>' +
              '</div>' +
            '</div>' +
          '</div>';
      }
    }

    // ── Per-km splits section (RUN/BIKE, only if no interval exercises) ──────
    var splitsHtml = '';
    if ((isRun || isBike) && !intervalsHtml && splits && splits.length) {
      var splitRows = '';
      splits.forEach(function (s) {
        var distKm  = parseFloat(s.distance_km);
        var pace    = (s.duration_seconds && distKm) ? fmtPaceFromSec(s.duration_seconds, distKm) : '—';
        var hrFmt   = s.avg_hr != null ? s.avg_hr + '' : '—';

        splitRows +=
          '<div class="dp-split-row">' +
            '<div class="dp-split-km">Km ' + esc(String(s.split_index)) + '</div>' +
            '<div></div>' +
            '<div class="dp-split-pace">' + esc(pace) + '</div>' +
            '<div class="dp-split-hr">' + esc(hrFmt) + '</div>' +
          '</div>';
      });

      splitsHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Per-km splits</div>' +
          '<div class="dp-splits">' +
            '<div class="dp-split-header">' +
              '<div>Km</div><div></div><div style="text-align:right">Pace</div><div style="text-align:right">HR</div>' +
            '</div>' +
            splitRows +
          '</div>' +
        '</div>';
    }

    // ── Exercises section (LIFT / WOD) ─────────────────────────────────────
    var exercisesHtml = '';
    if (!isCardio && exercises.length) {
      var exRows = '';
      exercises.forEach(function (ex) {
        var sub = '';
        if (ex.sets != null && ex.reps != null) sub = ex.sets + ' × ' + ex.reps;
        else if (ex.sets != null)               sub = ex.sets + ' sets';
        else if (ex.duration_seconds != null)   sub = fmtDurationDetail(ex.duration_seconds);
        else if (ex.duration)                   sub = ex.duration;
        if (ex.weight_kg != null) sub += (sub ? ' · ' : '') + ex.weight_kg + ' kg';

        var rpe = ex.rpe != null ? 'RPE ' + ex.rpe : '';

        exRows +=
          '<div class="dp-exercise-item">' +
            '<div>' +
              '<div class="dp-exercise-name">' + esc(ex.name || '—') + '</div>' +
              (sub ? '<div class="dp-exercise-sub">' + esc(sub) + '</div>' : '') +
            '</div>' +
            (rpe ? '<div class="dp-exercise-rpe">' + esc(rpe) + '</div>' : '<div></div>') +
          '</div>';
      });

      exercisesHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Exercises</div>' +
          '<div class="dp-exercise-list">' + exRows + '</div>' +
        '</div>';
    }

    // ── Notes section ────────────────────────────────────────────────────────
    var notesHtml = '';
    if (workout.remarks) {
      notesHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Notes</div>' +
          '<p class="dp-notes-card">' + esc(workout.remarks) + '</p>' +
        '</div>';
    }

    contentEl.innerHTML = heroHtml + statsHtml + intervalsHtml + splitsHtml + exercisesHtml + notesHtml;
  }

  // ── Delete workout ────────────────────────────────────────────────────────
  function deleteWorkout(workoutId) {
    if (!confirm('Delete this workout? This cannot be undone.')) return;

    fetch('/api/workouts/' + workoutId, { method: 'DELETE' })
      .then(function (res) {
        if (!res.ok && res.status !== 204) throw new Error('HTTP ' + res.status);
        UIStates.showToast('Workout deleted');
        closeDetailPanel();
        fetchAndRender();
      })
      .catch(function () {
        UIStates.showToast('Could not delete workout. Please try again.', true);
      });
  }

  // ── Swipe gesture support (mobile) ───────────────────────────────────────
  function initSwipe() {
    var panel = document.getElementById('dp-scroll');
    if (!panel) return;

    var touchStartX = 0, touchStartY = 0;

    panel.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1) return;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }, { passive: true });

    panel.addEventListener('touchend', function (e) {
      if (isDesktop()) return;
      var dx = e.changedTouches[0].clientX - touchStartX;
      var dy = e.changedTouches[0].clientY - touchStartY;
      if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
      if (dx < 0) navigateDetail(1);   // swipe left → next
      else        navigateDetail(-1);  // swipe right → prev
    }, { passive: true });
  }

  // ── Sync button state ─────────────────────────────────────────────────────
  var _syncPollTimer = null;

  function _syncSetBusy(busy) {
    var stravaBtn = document.getElementById('sync-strava-btn');
    if (stravaBtn) stravaBtn.disabled = busy;
    // Stryd stays disabled regardless; we only manage the aria/visual state for
    // the Strava button. Stryd's disabled attr is set in HTML and never cleared.
  }

  function _syncPollStatus() {
    fetch('/api/sync/status')
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data) { _syncStopStatusPoll(); _syncSetBusy(false); return; }
        if (data.status === 'running') {
          _syncSetBusy(true);
          if (!_syncPollTimer) {
            _syncPollTimer = setInterval(_syncPollStatus, 3000);
          }
        } else {
          _syncStopStatusPoll();
          _syncSetBusy(false);
        }
      })
      .catch(function () { _syncStopStatusPoll(); _syncSetBusy(false); });
  }

  function _syncStopStatusPoll() {
    if (_syncPollTimer) { clearInterval(_syncPollTimer); _syncPollTimer = null; }
  }

  function _onSyncStravaClick() {
    _syncSetBusy(true);
    fetch('/api/strava/sync', { method: 'POST' })
      .then(function (res) {
        if (res.status === 202 || res.status === 409) {
          if (window.syncBarRefresh) window.syncBarRefresh();
          _syncPollStatus();
        } else {
          _syncSetBusy(false);
        }
      })
      .catch(function () { _syncSetBusy(false); });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    readURLParams();
    buildFilterBar();
    fetchAndRender();
    initSwipe();

    _syncPollStatus();

    window.addEventListener('userChanged', function () {
      fetchAndRender();
    });

    var syncStravaBtn = document.getElementById('sync-strava-btn');
    if (syncStravaBtn) syncStravaBtn.addEventListener('click', _onSyncStravaClick);

    var exportBtn = document.getElementById('log-export-btn');
    if (exportBtn) exportBtn.addEventListener('click', exportCSV);

    var closeBtn = document.getElementById('dp-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', closeDetailPanel);

    var prevBtn = document.getElementById('dp-prev-btn');
    if (prevBtn) prevBtn.addEventListener('click', function () { navigateDetail(-1); });

    var nextBtn = document.getElementById('dp-next-btn');
    if (nextBtn) nextBtn.addEventListener('click', function () { navigateDetail(1); });

    var overlay = document.getElementById('detail-overlay');
    if (overlay) overlay.addEventListener('click', closeDetailPanel);

    var deleteBtn = document.getElementById('dp-delete-btn');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', function () {
        if (activeDetailWorkoutId) deleteWorkout(activeDetailWorkoutId);
      });
    }

    var listRetryBtn = document.getElementById('log-retry-btn');
    if (listRetryBtn) listRetryBtn.addEventListener('click', function () {
      fetchAndRender();
    });

    var emptyCta = document.getElementById('log-empty-cta');
    if (emptyCta) emptyCta.addEventListener('click', function () {
      window.location.href = '/training';
    });

    var newBtn = document.getElementById('log-new-btn');
    if (newBtn) newBtn.addEventListener('click', function () {
      window.location.href = '/training';
    });

    document.addEventListener('keydown', function (e) {
      var panel = document.getElementById('detail-panel');
      if (!panel || !panel.classList.contains('is-open')) return;
      if (e.key === 'Escape') closeDetailPanel();
      if (e.key === 'ArrowUp'   || e.key === 'ArrowLeft')  navigateDetail(-1);
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') navigateDetail(1);
    });
  });

  // ── Week strip ────────────────────────────────────────────────────────────
  var DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  var TYPE_COLORS = {
    run:  '#3b82f6',
    lift: '#8b5cf6',
    wod:  '#f97316',
    bike: '#14b8a6',
  };

  var TYPE_ORDER = ['run', 'lift', 'wod', 'bike'];


  function toISODate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function getMondayOf(d) {
    var date = new Date(d);
    date.setHours(0, 0, 0, 0);
    var dow = date.getDay();
    var diff = dow === 0 ? -6 : 1 - dow;
    date.setDate(date.getDate() + diff);
    return date;
  }

  function parseWeekParam() {
    var params = new URLSearchParams(window.location.search);
    var w = params.get('week');
    if (w && /^\d{4}-\d{2}-\d{2}$/.test(w)) {
      var d = new Date(w + 'T00:00:00');
      if (!isNaN(d.getTime())) return getMondayOf(d);
    }
    return getMondayOf(new Date());
  }

  function pushWeekParam(monday) {
    var params = new URLSearchParams(window.location.search);
    params.set('week', toISODate(monday));
    history.pushState({}, '', window.location.pathname + '?' + params);
  }

  function weekContainsToday(monday) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    return today >= monday && today <= sunday;
  }

  function buildWeekLabel(monday) {
    if (weekContainsToday(monday)) return 'This week';
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    var month = monday.toLocaleDateString('en-US', { month: 'short' });
    return month + ' ' + monday.getDate() + ' – ' + sunday.getDate();
  }

  var currentMonday = parseWeekParam();

  async function loadAndRender(monday) {
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);

    var fromStr = toISODate(monday);
    var toStr   = toISODate(sunday);

    var url = '/api/training-log?from=' + fromStr + '&to=' + toStr + '&include_rest=false';

    var dotsByDate = {};
    try {
      var res = await fetch(url);
      if (res.ok) {
        var data = await res.json();
        (data.weeks || []).forEach(function (week) {
          (week.entries || []).forEach(function (entry) {
            var t = (entry.type || '').toLowerCase();
            if (TYPE_COLORS[t]) {
              if (!dotsByDate[entry.date]) dotsByDate[entry.date] = [];
              if (dotsByDate[entry.date].indexOf(t) === -1) dotsByDate[entry.date].push(t);
            }
          });
        });
      }
    } catch (_) {
      // network error — render with empty dots
    }

    render(monday, dotsByDate);
  }

  function render(monday, dotsByDate) {
    var strip = document.getElementById('week-strip');
    if (!strip) return;

    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var todayStr = toISODate(today);

    var pillsHtml = '';
    for (var i = 0; i < 7; i++) {
      var d = new Date(monday);
      d.setDate(d.getDate() + i);
      var dateStr = toISODate(d);
      var isToday = dateStr === todayStr;

      var typesForDay = dotsByDate[dateStr] || [];
      var dotsHtml = TYPE_ORDER
        .filter(function (t) { return typesForDay.indexOf(t) !== -1; })
        .map(function (t) {
          return '<span class="wd-dot" style="background:' + TYPE_COLORS[t] + '"></span>';
        })
        .join('');

      pillsHtml +=
        '<div class="day-pill' + (isToday ? ' today' : '') + '">' +
          '<span class="day-name">' + DAY_NAMES[i] + '</span>' +
          '<span class="day-num">' + d.getDate() + '</span>' +
          '<div class="wd-dots">' + dotsHtml + '</div>' +
        '</div>';
    }

    strip.innerHTML =
      '<div class="ws-nav">' +
        '<button id="week-prev" class="ws-chevron" aria-label="Previous week">&#8249;</button>' +
        '<span id="week-label" class="ws-label">' + buildWeekLabel(monday) + '</span>' +
        '<button id="week-next" class="ws-chevron" aria-label="Next week">&#8250;</button>' +
      '</div>' +
      '<div class="ws-pills">' + pillsHtml + '</div>';

    document.getElementById('week-prev').addEventListener('click', function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() - 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday);
    });

    document.getElementById('week-next').addEventListener('click', function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() + 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadAndRender(currentMonday);
  });

  window.addEventListener('userReady', function () {
    loadAndRender(currentMonday);
  });

  window.addEventListener('userChanged', function () {
    loadAndRender(currentMonday);
  });
}());
