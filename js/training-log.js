(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var filters               = { type: 'all', search: '', from: '', to: '' };
  var lastWeeks             = [];
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

  // ── URL sync ──────────────────────────────────────────────────────────────
  function readURLParams() {
    var p = new URLSearchParams(window.location.search);
    filters.type   = p.get('type')   || 'all';
    filters.search = p.get('search') || '';
    filters.from   = p.get('from')   || '';
    filters.to     = p.get('to')     || '';
  }

  // Preserves the ?week param when updating filter params.
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

    // Visual divider between type chips and date-range chip
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

    // Search — 300 ms debounce
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

  // ── Fetch & render ────────────────────────────────────────────────────────
  function fetchAndRender() {
    var loadingEl = document.getElementById('log-loading-indicator');
    if (loadingEl) loadingEl.hidden = false;

    hideListMessages();
    showListSkeleton();

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
        lastWeeks = data.weeks || [];
        var listEl = document.getElementById('log-list');
        renderList(listEl, lastWeeks);
        updateHeaderStats(data);
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

    if (w.id) {
      row.setAttribute('tabindex', '0');
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

    // Source badges — supports comma-separated multi-source strings
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

  // ── Detail panel ──────────────────────────────────────────────────────────
  function openDetailPanel(workoutId, triggerEl) {
    if (activeRowEl) activeRowEl.classList.remove('is-active');
    activeRowEl = triggerEl || null;
    if (activeRowEl) activeRowEl.classList.add('is-active');

    activeDetailWorkoutId = workoutId;
    activeTriggerEl = triggerEl || null;
    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    if (overlay) { overlay.classList.add('is-open'); overlay.removeAttribute('aria-hidden'); }
    if (panel)   panel.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    fetchAndRenderDetail(workoutId);
  }

  function closeDetailPanel() {
    if (activeRowEl) { activeRowEl.classList.remove('is-active'); activeRowEl = null; }

    var trigger = activeTriggerEl;
    activeDetailWorkoutId = null;
    activeTriggerEl = null;
    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    if (overlay) { overlay.classList.remove('is-open'); overlay.setAttribute('aria-hidden', 'true'); }
    if (panel)   panel.classList.remove('is-open');
    document.body.style.overflow = '';
    if (trigger) trigger.focus();
  }

  function fetchAndRenderDetail(workoutId) {
    var loadingEl    = document.getElementById('detail-panel-loading');
    var errorEl      = document.getElementById('detail-panel-error');
    var contentEl    = document.getElementById('detail-panel-content');
    var titleEl      = document.getElementById('detail-panel-title-text');
    var dateEl       = document.getElementById('detail-panel-date');
    var sourcePillEl = document.getElementById('detail-panel-source-pill');
    var editBtn      = document.getElementById('detail-edit-btn');
    var stravaBtn    = document.getElementById('detail-strava-btn');

    if (loadingEl)    loadingEl.style.display = '';
    if (errorEl)      errorEl.style.display   = 'none';
    if (contentEl)    contentEl.innerHTML      = '';
    if (stravaBtn)    stravaBtn.style.display  = 'none';
    if (titleEl)      titleEl.textContent      = 'Workout';
    if (dateEl)       dateEl.textContent        = '';
    if (sourcePillEl) sourcePillEl.hidden       = true;

    fetch('/api/workouts/' + workoutId)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (workout) {
        if (loadingEl) loadingEl.style.display = 'none';

        if (titleEl && workout.name) titleEl.textContent = workout.name;

        if (dateEl && workout.workout_date) {
          dateEl.textContent = fmtDate(workout.workout_date);
        }

        if (sourcePillEl) {
          var srcLabel = workout.source === 'strava' ? 'Strava' : 'Manual';
          sourcePillEl.textContent = srcLabel;
          sourcePillEl.className = 'detail-source-pill detail-source-pill--' +
            (workout.source === 'strava' ? 'strava' : 'manual');
          sourcePillEl.hidden = false;
        }

        renderDetailContent(workout);

        if (editBtn)  editBtn.href = '/workout-edit/' + workout.id;
        if (stravaBtn && workout.strava_activity_url) {
          stravaBtn.href          = workout.strava_activity_url;
          stravaBtn.style.display = '';
        }
      })
      .catch(function (_) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl)   errorEl.style.display   = '';
        var retryBtn = document.getElementById('detail-retry-btn');
        if (retryBtn) {
          retryBtn.onclick = function () {
            fetchAndRenderDetail(workoutId);
          };
        }
      });
  }

  function renderDetailContent(workout) {
    var contentEl = document.getElementById('detail-panel-content');
    if (!contentEl) return;

    var em = '—';

    var hasDist = workout.distance_km != null;
    var hasDur  = workout.duration_seconds != null;
    var isRun   = workout.workout_type === 'run';
    var isBike  = workout.workout_type === 'bike';
    var showPaceSpeed = (isRun || isBike) && hasDist && hasDur;

    var distStr = hasDist ? (+workout.distance_km).toFixed(2) + ' km' : em;
    var durStr  = fmtDurationDetail(workout.duration_seconds);
    var paceStr = showPaceSpeed
      ? (isBike
          ? fmtSpeedKmh(workout.duration_seconds, workout.distance_km)
          : fmtPaceFromSec(workout.duration_seconds, workout.distance_km))
      : em;
    var hrStr   = workout.avg_hr != null ? workout.avg_hr + ' bpm' : em;
    var elevStr = workout.elevation_m != null ? workout.elevation_m + ' m' : em;
    var tssStr  = workout.tss != null ? (+workout.tss).toFixed(0) : em;

    var stats = [
      ['Distance',  distStr],
      ['Duration',  durStr],
      ['Avg Pace',  paceStr],
      ['Avg HR',    hrStr],
      ['Elevation', elevStr],
      ['TSS',       tssStr],
    ];

    var html = '<div class="detail-stats">';
    stats.forEach(function (s) {
      html +=
        '<div class="detail-stat">' +
          '<span class="detail-stat-label">' + esc(s[0]) + '</span>' +
          '<span class="detail-stat-value">' + esc(String(s[1])) + '</span>' +
        '</div>';
    });
    html += '</div>';

    var exercises = workout.exercises || [];
    if (exercises.length) {
      html += '<p class="detail-section-title">Exercises</p>';
      html += '<div class="exercises-section">';
      exercises.forEach(function (ex) {
        var parts = [];
        if (ex.sets != null && ex.reps != null) parts.push(ex.sets + ' \xd7 ' + ex.reps);
        else if (ex.sets != null)               parts.push(ex.sets + ' sets');
        if (ex.weight_kg != null) parts.push(ex.weight_kg + ' kg');
        if (ex.rpe != null)       parts.push('RPE ' + ex.rpe);
        html +=
          '<div class="exercise-item">' +
            '<span class="exercise-name">' + esc(ex.name || '') + '</span>' +
            (parts.length
              ? '<span class="exercise-meta">' + esc(parts.join(' · ')) + '</span>'
              : '') +
          '</div>';
      });
      html += '</div>';
    }

    if (workout.remarks) {
      html +=
        '<p class="detail-section-title">Notes</p>' +
        '<p class="detail-notes-body">' + esc(workout.remarks) + '</p>';
    }

    contentEl.innerHTML = html;
  }

  // ── More dropdown toggle ──────────────────────────────────────────────────
  function initMoreDropdown() {
    var moreBtn      = document.getElementById('top-nav-more-btn');
    var moreDropdown = document.getElementById('top-nav-dropdown');
    if (!moreBtn || !moreDropdown) return;

    moreBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var isOpen = !moreDropdown.hidden;
      moreDropdown.hidden = isOpen;
      moreBtn.setAttribute('aria-expanded', String(!isOpen));
    });

    document.addEventListener('click', function (e) {
      if (!moreDropdown.hidden && !moreDropdown.contains(e.target) && e.target !== moreBtn) {
        moreDropdown.hidden = true;
        moreBtn.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !moreDropdown.hidden) {
        moreDropdown.hidden = true;
        moreBtn.setAttribute('aria-expanded', 'false');
        moreBtn.focus();
      }
    });
  }

  // ── Avatar initial ────────────────────────────────────────────────────────
  function updateAvatarInitial() {
    var avatarEl  = document.getElementById('header-avatar');
    if (!avatarEl) return;
    var selectEl  = document.getElementById('user-selector-select');
    if (!selectEl || selectEl.selectedIndex < 0) return;
    var opt = selectEl.options[selectEl.selectedIndex];
    if (!opt || opt.value === '__add__') return;
    avatarEl.textContent = opt.textContent.trim().charAt(0).toUpperCase() || 'U';
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    readURLParams();
    buildFilterBar();
    fetchAndRender();
    initMoreDropdown();

    window.addEventListener('userChanged', function () {
      fetchAndRender();
      updateAvatarInitial();
    });

    var exportBtn = document.getElementById('log-export-btn');
    if (exportBtn) exportBtn.addEventListener('click', exportCSV);

    // log-new-btn is disabled — no click handler needed

    var closeBtn = document.getElementById('detail-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', closeDetailPanel);

    var overlay = document.getElementById('detail-overlay');
    if (overlay) overlay.addEventListener('click', closeDetailPanel);

    var listRetryBtn = document.getElementById('log-retry-btn');
    if (listRetryBtn) listRetryBtn.addEventListener('click', function () {
      fetchAndRender();
    });

    var emptyCta = document.getElementById('log-empty-cta');
    if (emptyCta) emptyCta.addEventListener('click', function () {
      window.location.href = 'training.html';
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDetailPanel();
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

  var USER_KEY = 'perf-coach.current-user-id';

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

  // Preserves all current URL params when updating ?week.
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

  function getCurrentUserId() {
    return localStorage.getItem(USER_KEY) || null;
  }

  var currentMonday = parseWeekParam();
  var currentUserId = null;

  async function loadAndRender(monday, userId) {
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);

    var fromStr = toISODate(monday);
    var toStr   = toISODate(sunday);

    var url = '/api/training-log?from=' + fromStr + '&to=' + toStr + '&include_rest=false';
    if (userId) url += '&user_id=' + encodeURIComponent(userId);

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
      loadAndRender(currentMonday, currentUserId);
    });

    document.getElementById('week-next').addEventListener('click', function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() + 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday, currentUserId);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    currentUserId = getCurrentUserId();
    loadAndRender(currentMonday, currentUserId);
  });

  window.addEventListener('userReady', function (e) {
    var newId = (e.detail && e.detail.userId) ? e.detail.userId : null;
    if (newId !== currentUserId) {
      currentUserId = newId;
      loadAndRender(currentMonday, currentUserId);
    }
    updateAvatarInitial();
  });

  window.addEventListener('userChanged', function (e) {
    currentUserId = (e.detail && e.detail.userId) ? e.detail.userId : getCurrentUserId();
    loadAndRender(currentMonday, currentUserId);
  });
}());
