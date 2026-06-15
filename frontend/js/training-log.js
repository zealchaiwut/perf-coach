(function () {
  'use strict';

  // Shared format helpers (issue #531) — single home for type normalization,
  // pace/duration formatting, and segment definitions. training-log.html loads
  // lib/training-format.js before this script.
  var TF = window.TrainingFormat;

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

  // issue #531: empty for falsy/non-positive, else the shared h:mm:ss/m:ss form.
  function fmtDurationRow(secs) {
    if (!secs || secs <= 0) return '';
    return TF.formatDuration(secs);
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

  // issue #531: render an already-computed seconds-per-km via the shared
  // pace formatter; '' keeps the prior empty-input behavior.
  function fmtPace(secsPerKm) {
    var core = TF.formatPace(secsPerKm, 1);
    return core ? core + ' /km' : '';
  }

  function fmtShortDate(isoStr) {
    var d = new Date(isoStr + 'T00:00:00');
    return d.getDate() + ' ' + MONTHS[d.getMonth()];
  }

  // issue #531: shared h:mm:ss/m:ss formatter; '—' for missing values.
  function fmtDurationDetail(secs) {
    return secs == null ? '—' : TF.formatDuration(secs);
  }

  // issue #531: compute seconds-per-km here (the #118 contract), then render
  // the m:ss part via the shared pace formatter; '—' when inputs are missing.
  function fmtPaceFromSec(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var secsPerKm = durSeconds / distKm;
    var core = TF.formatPace(secsPerKm, 1);
    return core ? core + ' /km' : '—';
  }

  function fmtSpeedKmh(durSeconds, distKm) {
    if (!durSeconds || !distKm || distKm === 0) return '—';
    var speed = distKm / (durSeconds / 3600);
    return speed.toFixed(1) + ' km/h';
  }

  // Map free-text workout_type values onto canonical keys (issue #531: the
  // shared normalizer, so the log and the editor detect runs identically).
  var normalizeTypeKey = TF.normalizeType;

  // Segment label → intensity key (timeline colors + segment dots), derived
  // from the shared segment definitions (issue #531).
  var RUN_SEGMENT_INTENSITY = TF.segmentIntensityByLabel;
  var RUN_SEGMENT_LABELS = RUN_SEGMENT_INTENSITY; // truthy lookup by label

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
    searchInput.setAttribute('aria-label', 'Search workouts');
    searchInput.setAttribute('type', 'search');
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
    params.set('include_rest', 'true');
    // issue #528: pull CTL/ATL/TSB on the SAME request as the list so the
    // readiness widget is fed from one computation (no duplicate load_context).
    params.set('include_load_context', 'true');

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
        // issue #528: re-render training-load surfaces on every fetch, so a
        // date-range change updates them without a full page reload (AC4).
        renderLoadWidget(data.load_context);
        renderVolumeChart();
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

  // ── Training-load surfaces (issue #528) ─────────────────────────────────────
  var volumeChart = null;

  function fmtLoadNum(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return String(Math.round(v * 10) / 10);
  }

  // Readiness widget: current CTL / ATL / TSB + plain-language interpretation.
  function renderLoadWidget(lc) {
    var el = document.getElementById('load-widget');
    if (!el) return;

    var ctl, atl, tsb, interp, cls;
    if (lc && typeof lc.ctl === 'number') {
      ctl = lc.ctl; atl = lc.atl; tsb = lc.tsb;
      interp = lc.interpretation || '—';
      cls = tsb >= 5 ? 'fresh' : (tsb <= -15 ? 'fatigued' : 'neutral');
    } else {
      // AC7 zero/empty state — brand-new athlete or < 7 days of history.
      ctl = 0; atl = 0; tsb = 0;
      interp = 'Not enough data';
      cls = 'empty';
    }

    function stat(val, label, sub) {
      return '<div class="lw-stat">' +
               '<div class="lw-stat-val">' + esc(fmtLoadNum(val)) + '</div>' +
               '<div class="lw-stat-label">' + label + '</div>' +
               '<div class="lw-stat-sub">' + sub + '</div>' +
             '</div>';
    }

    el.innerHTML =
      '<div class="lw-head">' +
        '<span class="lw-title">Readiness</span>' +
        '<span class="lw-interp lw-interp--' + cls + '">' + esc(interp) + '</span>' +
      '</div>' +
      '<div class="lw-stats">' +
        stat(ctl, 'CTL', 'Fitness') +
        stat(atl, 'ATL', 'Fatigue') +
        stat(tsb, 'TSB', 'Freshness') +
      '</div>';
    el.hidden = false;
  }

  function volumeWeekLabel(monday) {
    return monday.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  // Weekly volume chart: >= 8 weeks of distance (km) or TSS, auto-selected.
  function renderVolumeChart() {
    var card   = document.getElementById('volume-chart-card');
    var canvas = document.getElementById('volume-chart');
    var unitEl = document.getElementById('volume-chart-unit');
    // Guard: no-op when the surfaces or Chart.js are absent (other pages).
    if (!card || !canvas || typeof Chart === 'undefined') return;

    var toISO     = filters.to || todayISO();
    var toMonday  = getMondayOf(new Date(toISO + 'T00:00:00'));
    // Minimum window: 8 week-buckets ending at the selected week.
    var minStart  = new Date(toMonday);
    minStart.setDate(minStart.getDate() - 7 * 7);

    var startMonday = minStart;
    if (filters.from) {
      var fm = getMondayOf(new Date(filters.from + 'T00:00:00'));
      if (fm < minStart) startMonday = fm;
    }

    var fromStr = toISODate(startMonday);
    // Separate fetch WITHOUT include_load_context so load_context stays a
    // single computation on the main list request (AC5).
    fetch('/api/training-log?from=' + fromStr + '&to=' + toISO + '&include_rest=false')
      .then(function (res) { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); })
      .then(function (data) {
        var weeks = data.weeks || [];
        var byStart = {};
        weeks.forEach(function (w) { byStart[w.week_start] = w.summary || {}; });

        var labels = [], distVals = [], tssVals = [];
        var cur = new Date(startMonday);
        while (cur <= toMonday) {
          var s = byStart[toISODate(cur)] || {};
          labels.push(volumeWeekLabel(cur));
          // zero-fill empty/zero-activity weeks so they render as a zero bar (AC7)
          distVals.push(Math.round((s.total_distance_km || 0) * 10) / 10);
          tssVals.push(Math.round(s.total_tss || 0));
          cur.setDate(cur.getDate() + 7);
        }

        // Auto-select metric: distance when any distance present, else TSS.
        var hasDist = distVals.some(function (v) { return v > 0; });
        var hasTss  = tssVals.some(function (v) { return v > 0; });
        var useDist = hasDist || !hasTss;
        var values  = useDist ? distVals : tssVals;
        var unit    = useDist ? 'km' : 'TSS';
        var color   = useDist ? '#3b82f6' : '#f59e0b';

        if (unitEl) unitEl.textContent = unit;

        if (volumeChart) { volumeChart.destroy(); volumeChart = null; }
        volumeChart = new Chart(canvas.getContext('2d'), {
          type: 'bar',
          data: {
            labels: labels,
            datasets: [{
              label: unit,
              data: values,
              backgroundColor: color,
              borderRadius: 3,
              maxBarThickness: 36,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: function (ctx) { return ctx.parsed.y + ' ' + unit; },
                },
              },
            },
            scales: {
              x: {
                grid: { display: false },
                ticks: { font: { size: 10 }, color: '#69748c' },
                title: { display: true, text: 'Week', color: '#69748c', font: { size: 10 } },
              },
              y: {
                beginAtZero: true,
                ticks: { font: { size: 10 }, color: '#69748c' },
                title: { display: true, text: unit, color: '#69748c', font: { size: 10 } },
              },
            },
          },
        });
        card.hidden = false;
      })
      .catch(function () { /* leave prior chart / hidden card untouched */ });
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

    var titleEl = document.createElement('h2');
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

  // issue #530: a workout is Strava-sourced if its `source` is 'strava' OR it
  // carries a Strava activity URL (some imports leave `source` unset). Shared by
  // the list and detail views so both attribute the source identically.
  function isStravaWorkout(workout) {
    if (!workout) return false;
    return workout.source === 'strava' || !!workout.strava_activity_url;
  }

  function buildEntryRow(w) {
    var row = document.createElement('div');
    row.className = 'entry-row';
    if (w.id && activeDetailWorkoutId === w.id) {
      row.classList.add('is-active');
    }

    if (w.id) {
      row.setAttribute('tabindex', '0');
      row.setAttribute('role', 'button');
      // Accessible name: type, title, date, and primary metric.
      var ariaBits = [];
      var tk = normalizeTypeKey(w.type);
      ariaBits.push(({ run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' })[tk] || (w.type || 'Workout'));
      ariaBits.push(w.title || 'Workout');
      if (w.date) ariaBits.push(fmtDate(w.date));
      if (tk === 'run' && w.distance_km != null) ariaBits.push((+w.distance_km).toFixed(1) + ' kilometers');
      else if (w.duration_seconds) ariaBits.push(Math.round(w.duration_seconds / 60) + ' minutes');
      row.setAttribute('aria-label', ariaBits.join(', ') + '. Open details');
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

    var typeKey = normalizeTypeKey(w.type);
    var TYPE_LABELS = { run: 'Run', lift: 'Lift', wod: 'WOD', bike: 'Bike' };
    var typeSlug = TYPE_LABELS[typeKey] ? typeKey : 'other';
    row.classList.add('entry-row--' + typeSlug);
    var badge = document.createElement('span');
    badge.className = 'entry-type entry-type--' + typeSlug;
    var dot = document.createElement('span');
    dot.className = 'entry-type-dot';
    badge.appendChild(dot);
    var typeLbl = document.createElement('span');
    typeLbl.className = 'entry-type-label';
    typeLbl.textContent = (TYPE_LABELS[typeKey] || w.type || '').toUpperCase();
    badge.appendChild(typeLbl);

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
    var isStrava = isStravaWorkout(w);
    var isStryd = !!w.is_stryd_synced;
    if (isStrava) {
      var sbadge = document.createElement('span');
      sbadge.className = 'source-badge source-badge--strava';
      sbadge.textContent = 'St';
      sourcesWrap.appendChild(sbadge);
    }
    if (isStryd) {
      var sbadgeStryd = document.createElement('span');
      sbadgeStryd.className = 'source-badge source-badge--stryd';
      sbadgeStryd.textContent = 'S';
      sourcesWrap.appendChild(sbadgeStryd);
    }
    if (!isStrava && !isStryd) {
      var sbadgeM = document.createElement('span');
      sbadgeM.className = 'source-badge source-badge--manual';
      sbadgeM.setAttribute('aria-label', 'Manual');
      sbadgeM.innerHTML = '&#9998;';
      sourcesWrap.appendChild(sbadgeM);
    }

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
        var _tk    = normalizeTypeKey(workout.workout_type);
        var isRun  = _tk === 'run';
        var isBike = _tk === 'bike';

        var returnUrl = '/log?week=' + toISODate(currentMonday);
        if (editBtn) editBtn.href = '/training?edit=' + workout.id + '&return=' + encodeURIComponent(returnUrl);

        var isStrava = isStravaWorkout(workout);
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

    var typeKey  = normalizeTypeKey(workout.workout_type);
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
    var dpIsStrava = isStravaWorkout(workout);
    var dpIsStryd  = !!workout.is_stryd_synced;
    if (dpIsStrava) {
      sourceHtml += '<span class="dp-src-badge dp-src-badge--strava" title="strava">St</span>';
    }
    if (dpIsStryd) {
      sourceHtml += '<span class="dp-src-badge dp-src-badge--stryd" title="stryd">S</span>';
    }
    if (!dpIsStrava && !dpIsStryd) {
      sourceHtml += '<span class="dp-src-badge dp-src-badge--manual" title="manual">&#10002;</span>';
    }

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

    // ── Stats ─────────────────────────────────────────────────────────────────
    var statsHtml = '';
    if (isRun) {
      var hasDist = workout.distance_km != null;
      var hasPace = !!(workout.duration_seconds && workout.distance_km);
      var distVal = hasDist ? parseFloat((+workout.distance_km).toFixed(2)) : null;
      var paceVal = null;
      if (hasPace) {
        var spk = workout.duration_seconds / workout.distance_km;
        paceVal = Math.floor(spk / 60) + ':' + pad(Math.round(spk % 60));
      }
      var m1, m2;
      if (hasDist) {
        m1 = { v: distVal, u: 'km', l: 'Distance' };
        m2 = hasPace
          ? { v: paceVal, u: '/km', l: 'Avg pace' }
          : { v: workout.duration_seconds != null ? fmtDurationDetail(workout.duration_seconds) : '\u2014', u: '', l: 'Duration' };
      } else {
        m1 = { v: workout.duration_seconds != null ? fmtDurationDetail(workout.duration_seconds) : '\u2014', u: '', l: 'Duration' };
        m2 = { v: workout.avg_hr != null ? workout.avg_hr : '\u2014', u: workout.avg_hr != null ? 'bpm' : '', l: 'Avg HR' };
      }
      function heroMetric(m) {
        return '<div class="dp-hm">' +
          '<div class="dp-hm-val">' + esc(String(m.v)) + (m.u ? '<span class="dp-hm-unit">' + m.u + '</span>' : '') + '</div>' +
          '<div class="dp-hm-label">' + esc(m.l) + '</div>' +
        '</div>';
      }
      var stripItems = [];
      if (hasDist && workout.duration_seconds != null) stripItems.push(['Duration', fmtDurationDetail(workout.duration_seconds)]);
      if (workout.avg_hr != null && !(m1.l === 'Avg HR' || m2.l === 'Avg HR')) stripItems.push(['HR', workout.avg_hr + ' bpm']);
      if (workout.elevation_m != null) stripItems.push(['Elev', workout.elevation_m + ' m']);
      if (workout.tss != null) stripItems.push(['TSS', (+workout.tss).toFixed(0)]);
      var stripHtml = stripItems.map(function (it) {
        return '<span class="dp-strip-item"><span class="dp-strip-k">' + esc(it[0]) + '</span> ' + esc(String(it[1])) + '</span>';
      }).join('');
      statsHtml =
        '<div class="dp-section">' +
          '<div class="dp-hero-metrics">' + heroMetric(m1) + heroMetric(m2) + '</div>' +
          (stripHtml ? '<div class="dp-stat-strip">' + stripHtml + '</div>' : '') +
        '</div>';
    } else if (isBike) {
      var distStr = workout.distance_km != null ? (+workout.distance_km).toFixed(2) + '<span class="dp-stat-unit">km</span>' : '\u2014';
      var durStr  = workout.duration_seconds != null ? esc(fmtDurationDetail(workout.duration_seconds)) : '\u2014';
      var spdStr  = (workout.duration_seconds && workout.distance_km) ? esc(fmtSpeedKmh(workout.duration_seconds, workout.distance_km)) : '\u2014';
      var hrStr   = workout.avg_hr != null ? esc(workout.avg_hr) + '<span class="dp-stat-unit">bpm</span>' : '\u2014';
      var elevStr = workout.elevation_m != null ? esc(workout.elevation_m) + '<span class="dp-stat-unit">m</span>' : '\u2014';
      var tssStr  = workout.tss != null ? esc((+workout.tss).toFixed(0)) : '\u2014';
      statsHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Stats</div>' +
          '<div class="dp-stats-grid">' +
            '<div class="dp-stat"><div class="dp-stat-label">Distance</div><div class="dp-stat-value">' + distStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Duration</div><div class="dp-stat-value">' + durStr + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg speed</div><div class="dp-stat-value">' + spdStr + '</div></div>' +
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
            '<div class="dp-stat"><div class="dp-stat-label">Duration</div><div class="dp-stat-value">' + durStr2 + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Exercises</div><div class="dp-stat-value">' + esc(String(exCount)) + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Total reps</div><div class="dp-stat-value">' + (totalReps > 0 ? esc(String(totalReps)) : '—') + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg RPE</div><div class="dp-stat-value">' + (avgRpe != null ? esc(avgRpe) : '—') + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">Avg HR</div><div class="dp-stat-value">' + hrStr2 + '</div></div>' +
            '<div class="dp-stat"><div class="dp-stat-label">TSS</div><div class="dp-stat-value">' + tssStr2 + '</div></div>' +
          '</div>' +
        '</div>';
    }

    // ── Segments section (structured runs from the run builder) ─────────────
    var segmentsHtml = '';
    var segExs = exercises.filter(function (ex) {
      return RUN_SEGMENT_LABELS[(ex.name || '').toLowerCase()];
    });
    var isStructuredRun = isRun && segExs.length > 0 && segExs.length === exercises.length;
    if (isStructuredRun) {
      var segData = exercises.map(function (ex) {
        var sets   = ex.sets != null ? ex.sets : null;
        var repKm  = ex.distance_km != null ? parseFloat(ex.distance_km) : null;
        var repSec = ex.duration_seconds != null ? ex.duration_seconds : null;
        var mult   = sets && sets > 0 ? sets : 1;
        return {
          name: ex.name,
          intensity: RUN_SEGMENT_INTENSITY[(ex.name || '').toLowerCase()] || 'easy',
          sets: sets, repKm: repKm, repSec: repSec, mult: mult, hr: ex.avg_hr,
          totKm: repKm != null ? repKm * mult : null,
          totSec: repSec != null ? repSec * mult : null,
        };
      });

      var allTime = segData.every(function (s) { return s.totSec > 0; });
      var allDist = segData.every(function (s) { return s.totKm > 0; });
      var axis = allTime ? 'time' : (allDist ? 'dist' : 'equal');
      var axisTotal = segData.reduce(function (a, s) {
        return a + (axis === 'time' ? (s.totSec || 0) : axis === 'dist' ? (s.totKm || 0) : 1);
      }, 0) || 1;

      var tlBlocks = '';
      segData.forEach(function (s) {
        var mag = axis === 'time' ? (s.totSec || 0) : axis === 'dist' ? (s.totKm || 0) : 1;
        var pct = Math.max(mag / axisTotal, 0.02);
        var detail = axis === 'time'
          ? fmtDurationDetail(Math.round(s.totSec || 0))
          : (s.totKm != null ? parseFloat(s.totKm.toFixed(2)) + ' km' : '');
        tlBlocks +=
          '<div class="dp-tl-seg dp-tl-seg--' + s.intensity + '" ' +
            'style="flex:' + (pct * 1000).toFixed(0) + ' 1 0;" ' +
            'title="' + esc(s.name + (detail ? ' \u00b7 ' + detail : '')) + '">' +
            '<span class="dp-tl-label">' + esc(s.name) + '</span>' +
          '</div>';
      });
      var timelineHtml =
        '<div class="dp-timeline" role="img" aria-label="Session intensity by segment">' + tlBlocks + '</div>';

      var sgRows = '';
      var sgKm = 0, sgSec = 0, sgHrs = [], sgHrSum = 0;
      segData.forEach(function (s) {
        if (s.totKm) sgKm += s.totKm;
        if (s.totSec) sgSec += s.totSec;
        if (s.hr != null) { sgHrs.push(s.hr); sgHrSum += s.hr; }
        var distFmt = s.repKm != null
          ? (s.repKm >= 1 ? (+s.repKm).toFixed(1) + ' km' : Math.round(s.repKm * 1000) + 'm')
          : null;
        var timeFmt = s.repSec != null ? fmtDurationDetail(s.repSec) : null;
        var qty = s.sets != null
          ? s.sets + ' \u00d7 ' + (distFmt || timeFmt || '\u2014')
          : ([distFmt, timeFmt].filter(Boolean).join(' \u00b7 ') || '\u2014');
        var paceFmt = (s.repSec && s.repKm) ? fmtPaceFromSec(s.repSec, s.repKm) : '\u2014';
        var hrFmt   = s.hr != null ? s.hr + ' bpm' : '\u2014';
        sgRows +=
          '<div class="dp-interval-row">' +
            '<div class="dp-seg-dot dp-seg-dot--' + s.intensity + '" title="' + esc(s.name) + '"></div>' +
            '<div>' +
              '<div class="dp-interval-name">' + esc(s.name) + '</div>' +
              '<div class="dp-interval-sub">' + esc(qty) + '</div>' +
            '</div>' +
            '<div><div class="dp-interval-pace">' + esc(paceFmt) + '</div></div>' +
            '<div class="dp-interval-hr">' + esc(hrFmt) + '</div>' +
          '</div>';
      });

      var sgPace = (sgSec && sgKm) ? fmtPaceFromSec(sgSec, sgKm) : null;
      var sgHr = sgHrs.length ? Math.round(sgHrSum / sgHrs.length) + ' bpm' : null;
      var footRight = [sgPace, sgHr].filter(Boolean).join(' \u00b7 ') || '\u2014';

      segmentsHtml =
        '<div class="dp-section">' +
          '<div class="dp-section-title">Session</div>' +
          timelineHtml +
          '<div class="dp-intervals" style="margin-top:12px;">' +
            sgRows +
            '<div class="dp-interval-footer">' +
              '<span>Avg pace \u00b7 avg HR</span>' +
              '<span><strong>' + footRight + '</strong></span>' +
            '</div>' +
          '</div>' +
        '</div>';
    }

    // ── Intervals section (legacy runs with distance_km exercises) ──────────
    var intervalsHtml = '';
    if (isRun && !isStructuredRun) {
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
    if ((isRun || isBike) && !intervalsHtml && !segmentsHtml && splits && splits.length) {
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

    contentEl.innerHTML = heroHtml + statsHtml + segmentsHtml + intervalsHtml + splitsHtml + exercisesHtml + notesHtml;
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

  // ── Quick-add workout modal (issue #522) ────────────────────────────────────
  // A lightweight modal on /log that posts to the existing POST /api/workouts
  // endpoint and re-renders the list in place — no navigation to /training for
  // the common case. The full form stays reachable via "Open full form".
  var QA_FIELD_IDS = ['qa-date', 'qa-type', 'qa-name', 'qa-duration', 'qa-distance', 'qa-tss'];

  function qaEl(id) { return document.getElementById(id); }

  function clearQuickAddErrors() {
    QA_FIELD_IDS.forEach(function (id) {
      var input = qaEl(id);
      if (input) input.classList.remove('is-error');
      var err = qaEl(id + '-error');
      if (err) { err.textContent = ''; err.classList.remove('is-visible'); }
    });
    var formErr = qaEl('qa-form-error');
    if (formErr) { formErr.textContent = ''; formErr.classList.remove('is-visible'); }
  }

  function setQuickAddError(fieldId, message) {
    var input = qaEl(fieldId);
    if (input) input.classList.add('is-error');
    var err = qaEl(fieldId + '-error');
    if (err) { err.textContent = message; err.classList.add('is-visible'); }
  }

  // issue #525: pre-select the Type field with the user's most recently logged
  // workout type so they don't re-pick their usual type on every quick log. The
  // default comes from the server (the user's own workout history via
  // /api/workouts/recent-type), so it is persisted per user — not per browser
  // session — and never leaks across users. With no history the request returns
  // null and the select keeps its built-in default. The raw stored type is run
  // through the shared normalizer so values like "Running"/"Strength" map onto
  // the canonical option keys (run/lift/wod/bike). Only the select's value is
  // set — no marker/indicator — so a pre-selected type looks identical to a
  // manual one, and the user can freely override it before submitting.
  function prefillDefaultWorkoutType() {
    var typeSel = qaEl('qa-type');
    if (!typeSel) return;
    fetch('/api/workouts/recent-type')
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !data.workout_type) return;
        // Bail if the user already touched the field while the request was in
        // flight, so we never clobber an in-progress manual selection.
        if (typeSel.value) return;
        var key = normalizeTypeKey(data.workout_type);
        var hasOption = Array.prototype.some.call(typeSel.options, function (o) {
          return o.value === key;
        });
        if (hasOption) typeSel.value = key;
      })
      .catch(function () { /* non-fatal: keep the built-in default */ });
  }

  function openQuickAdd() {
    var modal = qaEl('quick-add-modal');
    if (!modal) return;
    clearQuickAddErrors();
    var form = qaEl('qa-form');
    if (form) form.reset();
    // Default the date to today for the common "log today's workout" case.
    var dateInput = qaEl('qa-date');
    if (dateInput && !dateInput.value) dateInput.value = todayISO();
    // Default the Type to the user's most recently logged type (issue #525).
    prefillDefaultWorkoutType();
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    var nameInput = qaEl('qa-name');
    if (nameInput) nameInput.focus();
  }

  function closeQuickAdd() {
    var modal = qaEl('quick-add-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function quickAddIsOpen() {
    var modal = qaEl('quick-add-modal');
    return !!(modal && modal.classList.contains('is-open'));
  }

  // Validate required fields (date, type, name) and numeric ranges. Returns true
  // when the form is safe to submit; otherwise paints inline errors and returns
  // false so the caller can short-circuit before the POST.
  function validateQuickAdd() {
    clearQuickAddErrors();
    var valid = true;

    var dateVal = (qaEl('qa-date').value || '').trim();
    if (!dateVal) {
      setQuickAddError('qa-date', 'Date is required.');
      valid = false;
    } else if (dateVal > todayISO()) {
      setQuickAddError('qa-date', 'Date cannot be in the future.');
      valid = false;
    }

    var typeVal = (qaEl('qa-type').value || '').trim();
    if (!typeVal) {
      setQuickAddError('qa-type', 'Type is required.');
      valid = false;
    }

    var nameVal = (qaEl('qa-name').value || '').trim();
    if (!nameVal) {
      setQuickAddError('qa-name', 'Name is required.');
      valid = false;
    }

    var durationVal = (qaEl('qa-duration').value || '').trim();
    if (durationVal !== '' && Number(durationVal) < 0) {
      setQuickAddError('qa-duration', 'Duration cannot be negative.');
      valid = false;
    }

    var distanceVal = (qaEl('qa-distance').value || '').trim();
    if (distanceVal !== '' && Number(distanceVal) < 0) {
      setQuickAddError('qa-distance', 'Distance cannot be negative.');
      valid = false;
    }

    var tssVal = (qaEl('qa-tss').value || '').trim();
    if (tssVal !== '' && Number(tssVal) < 0) {
      setQuickAddError('qa-tss', 'TSS cannot be negative.');
      valid = false;
    }

    return valid;
  }

  function submitQuickAdd() {
    if (!validateQuickAdd()) return;

    var durationVal = (qaEl('qa-duration').value || '').trim();
    var distanceVal = (qaEl('qa-distance').value || '').trim();
    var tssVal = (qaEl('qa-tss').value || '').trim();

    var payload = {
      workout_date: (qaEl('qa-date').value || '').trim(),
      workout_type: (qaEl('qa-type').value || '').trim(),
      name: (qaEl('qa-name').value || '').trim(),
      duration_seconds: durationVal !== '' ? Math.round(Number(durationVal) * 60) : null,
      distance_km: distanceVal !== '' ? Number(distanceVal) : null,
      tss: tssVal !== '' ? Number(tssVal) : null,
      exercises: [],
    };

    var saveBtn = qaEl('qa-save-btn');
    if (saveBtn) saveBtn.disabled = true;

    fetch('/api/workouts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          var formErr = qaEl('qa-form-error');
          var detail = (result.data && result.data.detail) || 'Save failed. Please try again.';
          if (formErr) { formErr.textContent = detail; formErr.classList.add('is-visible'); }
          return;
        }
        closeQuickAdd();
        UIStates.showToast('Workout saved');
        // Re-render the list in place so the new entry lands at the correct
        // position without a full page reload (AC3).
        fetchAndRender();
      })
      .catch(function () {
        var formErr = qaEl('qa-form-error');
        if (formErr) { formErr.textContent = 'Save failed. Please try again.'; formErr.classList.add('is-visible'); }
      })
      .finally(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  function wireQuickAdd() {
    var newBtn = qaEl('log-new-btn');
    if (newBtn) newBtn.addEventListener('click', function () { openQuickAdd(); });

    var emptyCta = qaEl('log-empty-cta');
    if (emptyCta) emptyCta.addEventListener('click', function () { openQuickAdd(); });

    var closeBtn = qaEl('qa-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', function () { closeQuickAdd(); });

    var backdrop = qaEl('qa-backdrop');
    if (backdrop) backdrop.addEventListener('click', function () { closeQuickAdd(); });

    var form = qaEl('qa-form');
    if (form) form.addEventListener('submit', function (e) {
      e.preventDefault();
      submitQuickAdd();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && quickAddIsOpen()) closeQuickAdd();
    });
  }

  // ── Repeat last workout (issue #524) ──────────────────────────────────────
  // The /log page surfaces the action; the prefill itself reuses the existing
  // repeatLastWorkout entry point on the form page (out of scope to duplicate).
  function repeatLastEntryPoint() {
    window.location.href = '/training?repeat=1';
  }

  // Enable the button only when a previous workout exists; otherwise disable it
  // with an explanatory empty-state title (AC6). Checks a long window so a user
  // with history but an empty current week still sees it enabled.
  function refreshRepeatAvailability() {
    var btn = document.getElementById('log-repeat-last-btn');
    if (!btn) return;
    var to = todayISO();
    var from = addDays(to, -1095); // ~3 years, matches the form-side repeat window
    fetch('/api/workouts?from=' + from + '&to=' + to)
      .then(function (res) { return res.ok ? res.json() : []; })
      .then(function (workouts) {
        var has = Array.isArray(workouts) && workouts.length > 0;
        btn.disabled = !has;
        btn.title = has
          ? 'Repeat your most recent workout'
          : 'No previous workout to repeat';
      })
      .catch(function () { /* leave the button disabled on error */ });
  }

  // ── Duplicate to date (issue #524) ────────────────────────────────────────
  function openDuplicateModal() {
    if (!activeDetailWorkoutId) return;
    var modal = document.getElementById('dup-modal');
    var input = document.getElementById('dup-date-input');
    var err   = document.getElementById('dup-date-error');
    if (err) err.textContent = '';
    if (input) {
      input.max   = todayISO();   // no future dates (mirrors the backend rule)
      input.value = todayISO();
    }
    if (modal) {
      modal.classList.add('is-open');
      modal.setAttribute('aria-hidden', 'false');
    }
    if (input) input.focus();
  }

  function closeDuplicateModal() {
    var modal = document.getElementById('dup-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function dupModalIsOpen() {
    var modal = document.getElementById('dup-modal');
    return !!(modal && modal.classList.contains('is-open'));
  }

  function confirmDuplicate() {
    var input = document.getElementById('dup-date-input');
    var err   = document.getElementById('dup-date-error');
    var btn   = document.getElementById('dup-confirm-btn');
    if (!activeDetailWorkoutId || !input) return;
    var date = input.value;
    if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      if (err) err.textContent = 'Pick a valid date.';
      return;
    }
    if (date > todayISO()) {
      if (err) err.textContent = 'Date cannot be in the future.';
      return;
    }
    if (btn) btn.disabled = true;
    fetch('/api/workouts/' + activeDetailWorkoutId + '/duplicate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workout_date: date }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function () {
        closeDuplicateModal();
        closeDetailPanel();
        UIStates.showToast('Workout duplicated');
        fetchAndRender();
        refreshRepeatAvailability();
      })
      .catch(function () {
        if (err) err.textContent = 'Could not duplicate. Please try again.';
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    readURLParams();
    buildFilterBar();
    fetchAndRender();
    initSwipe();
    refreshRepeatAvailability();

    _syncPollStatus();

    window.addEventListener('userChanged', function () {
      fetchAndRender();
      refreshRepeatAvailability();
    });

    var repeatBtn = document.getElementById('log-repeat-last-btn');
    if (repeatBtn) repeatBtn.addEventListener('click', function () {
      if (!repeatBtn.disabled) repeatLastEntryPoint();
    });

    var dupBtn = document.getElementById('dp-duplicate-btn');
    if (dupBtn) dupBtn.addEventListener('click', openDuplicateModal);

    var dupCloseBtn  = document.getElementById('dup-close-btn');
    if (dupCloseBtn) dupCloseBtn.addEventListener('click', closeDuplicateModal);
    var dupCancelBtn = document.getElementById('dup-cancel-btn');
    if (dupCancelBtn) dupCancelBtn.addEventListener('click', closeDuplicateModal);
    var dupBackdrop  = document.getElementById('dup-backdrop');
    if (dupBackdrop) dupBackdrop.addEventListener('click', closeDuplicateModal);
    var dupForm = document.getElementById('dup-form');
    if (dupForm) dupForm.addEventListener('submit', function (e) {
      e.preventDefault();
      confirmDuplicate();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && dupModalIsOpen()) closeDuplicateModal();
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

    // Quick-add modal triggers ("Log workout" + empty-state CTA), close/backdrop/
    // Esc dismissal, and form submission (issue #522).
    wireQuickAdd();

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
    var isCurrentWeek = weekContainsToday(monday);

    // A pill is "selected" only when the list filter is pinned to exactly that
    // single day (filters.from === filters.to === the pill's date). issue #523
    var isDayFilter = !!filters.from && filters.from === filters.to;

    var pillsHtml = '';
    for (var i = 0; i < 7; i++) {
      var d = new Date(monday);
      d.setDate(d.getDate() + i);
      var dateStr = toISODate(d);
      var isToday = dateStr === todayStr;
      var isSelected = isDayFilter && filters.from === dateStr;

      var typesForDay = dotsByDate[dateStr] || [];
      var dotsHtml = TYPE_ORDER
        .filter(function (t) { return typesForDay.indexOf(t) !== -1; })
        .map(function (t) {
          return '<span class="wd-dot" style="background:' + TYPE_COLORS[t] + '"></span>';
        })
        .join('');

      // Full, human-readable date for screen readers, e.g. "Monday, June 9".
      var ariaLabel = d.toLocaleDateString('en-US', {
        weekday: 'long', month: 'long', day: 'numeric'
      });

      pillsHtml +=
        '<button type="button" class="day-pill' +
            (isToday ? ' today' : '') + (isSelected ? ' is-selected' : '') + '"' +
          ' data-date="' + dateStr + '"' +
          ' aria-pressed="' + (isSelected ? 'true' : 'false') + '"' +
          ' aria-label="' + esc(ariaLabel) + '">' +
          '<span class="day-name">' + DAY_NAMES[i] + '</span>' +
          '<span class="day-num">' + d.getDate() + '</span>' +
          '<div class="wd-dots">' + dotsHtml + '</div>' +
        '</button>';
    }

    strip.innerHTML =
      '<div class="ws-nav">' +
        '<button id="week-prev" class="ws-chevron" aria-label="Previous week">&#8249;</button>' +
        '<span id="week-label" class="ws-label">' + buildWeekLabel(monday) + '</span>' +
        '<button id="week-today" class="ws-today-btn"' + (isCurrentWeek ? ' disabled' : '') + '>Today</button>' +
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

    document.getElementById('week-today').addEventListener('click', function () {
      currentMonday = getMondayOf(new Date());
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday);
    });

    // issue #523: wire each (native, keyboard-operable) day pill to the
    // selection handler. Real <button>s already fire click on Enter & Space,
    // so no extra keydown handling is needed.
    var pillEls = strip.querySelectorAll('.day-pill');
    Array.prototype.forEach.call(pillEls, function (pill) {
      pill.addEventListener('click', function () {
        selectDay(pill.getAttribute('data-date'));
      });
    });

    // issue #523: on load (and re-render) bring the selected pill — or today's
    // pill on the current week — into view regardless of viewport width.
    var focusDate = (isDayFilter && filters.from) ? filters.from
                  : (isCurrentWeek ? todayStr : null);
    if (focusDate) {
      var target = strip.querySelector('.day-pill[data-date="' + focusDate + '"]');
      if (target) scrollPillIntoView(target);
    }
  }

  // Centre a pill within the horizontally-scrolling strip without disturbing
  // vertical page scroll. issue #523 (AC3 — works on all screen widths).
  function scrollPillIntoView(pill) {
    var container = pill.parentElement; // .ws-pills
    if (!container) return;
    var offset = pill.offsetLeft - (container.clientWidth - pill.clientWidth) / 2;
    container.scrollLeft = Math.max(0, offset);
  }

  // issue #523: tapping a day pill filters the log list to that single date.
  // Tapping the already-selected pill clears the filter (back to full list).
  function selectDay(dateStr) {
    if (!dateStr) return;
    var alreadySelected = !!filters.from && filters.from === filters.to
                          && filters.from === dateStr;
    if (alreadySelected) {
      filters.from = '';
      filters.to = '';
    } else {
      filters.from = dateStr;
      filters.to = dateStr;
    }
    writeURLParams();
    syncDateRangeChip();
    fetchAndRender();          // re-render the log list in place
    loadAndRender(currentMonday); // re-render the strip to update selection
  }

  // Keep the date-range chip / inputs in sync when a pill drives the filter.
  function syncDateRangeChip() {
    var chip = document.getElementById('dr-chip');
    if (chip) chip.textContent = drLabel() + ' ▾';
    var fromInput = document.getElementById('dr-from');
    if (fromInput) fromInput.value = filters.from;
    var toInput = document.getElementById('dr-to');
    if (toInput) toInput.value = filters.to;
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
