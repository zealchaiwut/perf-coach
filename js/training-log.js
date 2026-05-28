(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var filters               = { type: 'all', search: '', from: '', to: '' };
  var lastWeeks             = [];
  var activeDetailWorkoutId = null;
  var activeTriggerEl       = null;

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
    return m + ':' + pad(s) + '/km';
  }

  // Detail panel duration: h:mm:ss or m:ss; null → em-dash
  function fmtDurationDetail(secs) {
    if (secs == null) return '—';
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  // Run pace: returns "M:SS /km"; null/zero inputs → em-dash
  function fmtPaceFromSec(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var secsPerKm = durSeconds / distKm;
    var pm = Math.floor(secsPerKm / 60);
    var ps = Math.round(secsPerKm % 60);
    return pm + ':' + pad(ps) + ' /km';
  }

  // Bike speed: returns "X.X km/h"; null/zero inputs → em-dash
  function fmtSpeedKmh(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var speed = distKm / (durSeconds / 3600);
    return speed.toFixed(1) + ' km/h';
  }

  // Format ISO date string as "Tue, May 28"
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
      })
      .catch(function (_) {
        renderListError();
      })
      .finally(function () {
        if (loadingEl) loadingEl.hidden = true;
      });
  }

  // ── Log list rendering ────────────────────────────────────────────────────
  var ENTRY_LABELS = { run:'Run', lift:'Lift', wod:'WOD', bike:'Bike', rest:'Rest' };

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
        msg.textContent = 'No workouts in this range.';
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

    var badge = document.createElement('span');
    badge.className = 'rest-badge';
    badge.textContent = 'Rest';
    row.appendChild(badge);

    var info = document.createElement('div');
    info.className = 'rest-metrics';

    var labelParts = [];
    if (entry.sleep_hours != null) labelParts.push('sleep ' + entry.sleep_hours + 'h');
    if (entry.energy != null) labelParts.push('energy ' + entry.energy);
    if (entry.mood != null) labelParts.push('mood ' + entry.mood);
    if (entry.resting_hr != null) labelParts.push('RHR ' + entry.resting_hr);

    var label = document.createElement('span');
    label.className = 'rest-day-label';
    label.textContent = 'Rest day' + (labelParts.length ? ' - ' + labelParts.join(', ') : '');
    info.appendChild(label);

    var m = entry.metrics || {};
    if (m.hrv != null) {
      var hrvEl = document.createElement('span');
      hrvEl.className = 'rest-metric-item';
      hrvEl.textContent = 'HRV ' + m.hrv;
      info.appendChild(hrvEl);
    }

    if (m.notes) {
      var noteText = String(m.notes);
      var notesEl = document.createElement('span');
      notesEl.className = 'rest-notes';
      notesEl.textContent = noteText.length > 80 ? noteText.slice(0, 80) + '…' : noteText;
      info.appendChild(notesEl);
    }

    row.appendChild(info);
    return row;
  }

  function buildWeekGroup(week) {
    var s  = week.summary || {};
    var ws = week.workouts || [];
    var parts = [ws.length + ' workout' + (ws.length !== 1 ? 's' : '')];
    if (s.total_distance_km > 0) parts.push((+s.total_distance_km).toFixed(1) + ' km');
    if (s.total_time_minutes > 0) parts.push(fmtDuration(s.total_time_minutes * 60));
    if (s.total_tss > 0) parts.push('TSS ' + (+s.total_tss).toFixed(0));

    var groupEl = document.createElement('div');
    groupEl.className = 'week-group';

    var header = document.createElement('div');
    header.className = 'week-group-header';
    header.innerHTML =
      '<div class="week-group-title">' + esc(week.label) + '</div>' +
      '<div class="week-group-summary">' +
        parts.map(esc).join('<span class="summary-sep">·</span>') +
      '</div>';
    groupEl.appendChild(header);

    var dayMap = {};
    (week.entries || []).forEach(function (e) {
      if (!dayMap[e.date]) dayMap[e.date] = [];
      dayMap[e.date].push(e);
    });

    Object.keys(dayMap).sort().reverse().forEach(function (dateStr) {
      var sec = document.createElement('div');
      sec.className = 'day-section';
      sec.id        = 'day-' + dateStr;

      var dl = document.createElement('div');
      dl.className = 'day-label';
      var d = new Date(dateStr + 'T00:00:00');
      dl.textContent = DAY_ABBR[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
      sec.appendChild(dl);

      dayMap[dateStr].forEach(function (entry) {
        sec.appendChild(entry.type === 'rest' ? renderRestDayRow(entry) : buildEntryRow(entry));
      });
      groupEl.appendChild(sec);
    });

    return groupEl;
  }

  function buildEntryRow(w) {
    var row = document.createElement('div');
    row.className = 'entry-row entry-row--' + esc(w.type || 'other');

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

    var meta = [];
    if (w.duration_seconds) meta.push(fmtDuration(w.duration_seconds));
    if ((w.type === 'run' || w.type === 'bike') && w.distance_km)
      meta.push((+w.distance_km).toFixed(1) + ' km');
    if ((w.type === 'run' || w.type === 'bike') && w.average_pace_seconds_per_km)
      meta.push(fmtPace(w.average_pace_seconds_per_km));
    if (w.avg_hr) meta.push('HR ' + w.avg_hr);

    var tssHtml = '';
    if (w.tss != null) {
      var tc = w.tss > 80 ? 'tss-high' : w.tss > 50 ? 'tss-mid' : 'tss-low';
      tssHtml = '<span class="tss-pill ' + tc + '">TSS ' + (+w.tss).toFixed(0) + '</span>';
    }

    var typeLabel = ENTRY_LABELS[w.type] || esc(w.type || '');
    row.innerHTML =
      '<span class="entry-badge entry-badge--' + esc(w.type || 'other') + '">' + esc(typeLabel) + '</span>' +
      '<div class="entry-body">' +
        '<div class="entry-title">' + esc(w.title || 'Workout') + '</div>' +
        (meta.length ? '<div class="entry-meta">' + esc(meta.join(' · ')) + '</div>' : '') +
      '</div>' +
      tssHtml;

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
          csvField(entry.distance_km    != null ? entry.distance_km    : ''),
          csvField(entry.duration_minutes != null ? entry.duration_minutes : ''),
          csvField(entry.avg_hr         != null ? entry.avg_hr         : ''),
          csvField(entry.tss            != null ? entry.tss            : ''),
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

    // Pace/speed guard variables
    var hasDist = workout.distance_km != null;
    var hasDur  = workout.duration_seconds != null;
    var isRun   = workout.workout_type === 'run';
    var isBike  = workout.workout_type === 'bike';
    var showPaceSpeed = (isRun || isBike) && hasDist && hasDur;

    // Fixed 2×3 stat grid (2 cols, 3 rows)
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
      ['Distance', distStr],
      ['Duration', durStr],
      ['Avg Pace', paceStr],
      ['Avg HR',   hrStr],
      ['Elevation', elevStr],
      ['TSS',      tssStr],
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

    // Exercises section — only when non-empty
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

    // Notes section — only when non-empty
    if (workout.remarks) {
      html +=
        '<p class="detail-section-title">Notes</p>' +
        '<p class="detail-notes-body">' + esc(workout.remarks) + '</p>';
    }

    contentEl.innerHTML = html;
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
    if (exportBtn) exportBtn.addEventListener('click', exportCSV);

    var newBtn = document.getElementById('log-new-btn');
    if (newBtn) newBtn.addEventListener('click', function () {
      window.location.href = 'training.html';
    });

    // Detail panel close
    var closeBtn = document.getElementById('detail-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', closeDetailPanel);

    var overlay = document.getElementById('detail-overlay');
    if (overlay) overlay.addEventListener('click', closeDetailPanel);

    // List retry
    var listRetryBtn = document.getElementById('log-retry-btn');
    if (listRetryBtn) listRetryBtn.addEventListener('click', function () {
      fetchAndRender();
    });

    // Empty state CTA
    var emptyCta = document.getElementById('log-empty-cta');
    if (emptyCta) emptyCta.addEventListener('click', function () {
      window.location.href = 'training.html';
    });

    // Escape key closes detail panel
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDetailPanel();
    });
  });

}());
