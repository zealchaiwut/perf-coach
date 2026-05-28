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

    // Search input
    var searchWrap = document.createElement('div');
    searchWrap.className = 'fb-search-wrap';
    var searchInput = document.createElement('input');
    searchInput.type        = 'text';
    searchInput.id          = 'log-search';
    searchInput.placeholder = 'Search workouts';
    searchInput.value       = filters.search;
    searchWrap.appendChild(searchInput);
    bar.appendChild(searchWrap);

    // Type chips
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

    // Date-range chip + panel
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

    // Loading indicator
    var loadingEl = document.createElement('span');
    loadingEl.id        = 'log-loading-indicator';
    loadingEl.className = 'log-loading-indicator';
    loadingEl.hidden    = true;
    loadingEl.setAttribute('role', 'status');
    loadingEl.setAttribute('aria-live', 'polite');
    loadingEl.textContent = 'Loading…';
    bar.appendChild(loadingEl);

    // ── Events ────────────────────────────────────────────────────────────

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

    // DR chip toggle
    drChip.addEventListener('click', function (e) {
      e.stopPropagation();
      var nowOpen = drPanel.hidden;
      drPanel.hidden = !nowOpen;
      drChip.setAttribute('aria-expanded', String(nowOpen));
    });

    // Apply date range
    applyBtn.addEventListener('click', function () {
      filters.from = fromInput.value;
      filters.to   = toInput.value;
      drPanel.hidden = true;
      drChip.setAttribute('aria-expanded', 'false');
      drChip.textContent = drLabel() + ' ▾';
      writeURLParams();
      fetchAndRender();
    });

    // Close DR panel on outside click
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
        if (listEl) listEl.innerHTML = '<p class="log-empty">Failed to load workouts.</p>';
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
    if (!weeks.length) {
      var msg = document.createElement('p');
      msg.className   = 'log-empty';
      msg.textContent = 'No workouts in this range.';
      container.appendChild(msg);
      return;
    }
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
    if (s.total_distance_km > 0) parts.push((+s.total_distance_km).toFixed(1) + ' km');
    if (s.total_time_minutes > 0) parts.push(fmtDuration(s.total_time_minutes * 60));
    if (s.total_tss > 0) parts.push('TSS ' + (+s.total_tss).toFixed(0));

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
      dl.textContent = DAY_ABBR[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
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

    var meta = [];
    if (w.duration_seconds) meta.push(fmtDuration(w.duration_seconds));
    if ((w.type === 'run' || w.type === 'bike') && w.distance_km)
      meta.push((+w.distance_km).toFixed(1) + ' km');
    if ((w.type === 'run' || w.type === 'bike') && w.average_pace_seconds_per_km)
      meta.push(fmtPace(w.average_pace_seconds_per_km));
    if (w.avg_hr) meta.push('HR ' + w.avg_hr);

    var tssHtml = '';
    if (w.tss != null) {
      var tc = w.tss > 80 ? 'tss-high' : w.tss > 50 ? 'tss-mid' : 'tss-low';
      tssHtml = '<span class="tss-pill ' + tc + '">TSS ' + (+w.tss).toFixed(0) + '</span>';
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
