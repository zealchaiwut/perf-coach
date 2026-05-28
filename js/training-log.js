(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var filters              = { type: 'all', search: '', from: '', to: '' };
  var lastWeeks            = [];
  var activeDetailWorkoutId = null;

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
      row.addEventListener('click', function () {
        openDetailPanel(w.id);
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

  // ── Detail panel ──────────────────────────────────────────────────────────
  function openDetailPanel(workoutId) {
    activeDetailWorkoutId = workoutId;
    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    if (overlay) { overlay.classList.add('is-open'); overlay.removeAttribute('aria-hidden'); }
    if (panel)   panel.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    fetchAndRenderDetail(workoutId);
  }

  function closeDetailPanel() {
    activeDetailWorkoutId = null;
    var overlay = document.getElementById('detail-overlay');
    var panel   = document.getElementById('detail-panel');
    if (overlay) { overlay.classList.remove('is-open'); overlay.setAttribute('aria-hidden', 'true'); }
    if (panel)   panel.classList.remove('is-open');
    document.body.style.overflow = '';
  }

  function fetchAndRenderDetail(workoutId) {
    var loadingEl = document.getElementById('detail-panel-loading');
    var errorEl   = document.getElementById('detail-panel-error');
    var contentEl = document.getElementById('detail-panel-content');
    var titleEl   = document.getElementById('detail-panel-title-text');
    var editBtn   = document.getElementById('detail-edit-btn');
    var stravaBtn = document.getElementById('detail-strava-btn');

    if (loadingEl) loadingEl.style.display = '';
    if (errorEl)   errorEl.style.display   = 'none';
    if (contentEl) contentEl.innerHTML     = '';
    if (stravaBtn) stravaBtn.style.display = 'none';
    if (titleEl)   titleEl.textContent     = 'Workout';

    fetch('/api/workouts/' + workoutId)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (workout) {
        if (loadingEl) loadingEl.style.display = 'none';
        renderDetailContent(workout);
        if (titleEl && workout.name) titleEl.textContent = workout.name;
        if (editBtn)  editBtn.href = '/workout-edit/' + workout.id;
        if (stravaBtn && workout.strava_activity_url) {
          stravaBtn.href         = workout.strava_activity_url;
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

    var meta = [];
    if (workout.workout_date) meta.push(workout.workout_date);
    if (workout.workout_type) {
      meta.push(workout.workout_type.charAt(0).toUpperCase() + workout.workout_type.slice(1));
    }

    var stats = [];
    if (workout.duration_seconds) stats.push(['Duration', fmtDuration(workout.duration_seconds)]);
    if (workout.distance_km)      stats.push(['Distance', (+workout.distance_km).toFixed(1) + ' km']);
    if (workout.avg_hr)           stats.push(['Avg HR', workout.avg_hr + ' bpm']);
    if (workout.max_hr)           stats.push(['Max HR', workout.max_hr + ' bpm']);
    if (workout.elevation_m)      stats.push(['Elevation', workout.elevation_m + ' m']);
    if (workout.tss != null)      stats.push(['TSS', (+workout.tss).toFixed(0)]);

    var html = '';

    if (meta.length) {
      html += '<p class="detail-meta">' + esc(meta.join(' · ')) + '</p>';
    }

    if (stats.length) {
      html += '<div class="detail-stats">';
      stats.forEach(function (s) {
        html +=
          '<div class="detail-stat">' +
            '<span class="detail-stat-label">' + esc(s[0]) + '</span>' +
            '<span class="detail-stat-value">' + esc(String(s[1])) + '</span>' +
          '</div>';
      });
      html += '</div>';
    }

    if (workout.remarks) {
      html +=
        '<p class="detail-section-title">Notes</p>' +
        '<p class="detail-notes-body">' + esc(workout.remarks) + '</p>';
    }

    if (workout.exercises && workout.exercises.length) {
      html += '<p class="detail-section-title">Exercises (' + workout.exercises.length + ')</p>';
      workout.exercises.forEach(function (ex) {
        html += '<div class="detail-exercise-item">' + esc(ex.name || '') + '</div>';
      });
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
    if (exportBtn) exportBtn.addEventListener('click', function () {
      alert('Export coming soon.');
    });

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
