'use strict';

// ── Utilities ──────────────────────────────────────────────────────────────

function todayISO() {
  const d = new Date();
  return isoDateStr(d);
}

function isoDateStr(date) {
  return (
    date.getFullYear() +
    '-' + String(date.getMonth() + 1).padStart(2, '0') +
    '-' + String(date.getDate()).padStart(2, '0')
  );
}

function nowHHMM() {
  const d = new Date();
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function addDays(dateStr, n) {
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return isoDateStr(d);
}

// Compute from-date for each named range
function rangeFromDate(range) {
  const offsets = { '30d': -29, '90d': -89, '6m': -180, '1y': -364, 'all': -364 };
  return addDays(todayISO(), offsets[range] ?? -29);
}

// Format a date string for the x-axis, adapting by range
function fmtDateForRange(dateStr, range) {
  const d = new Date(dateStr + 'T00:00:00');
  if (range === '30d' || range === '90d') {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
}

// Format date for display in entries list
function fmtDisplayDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

// Linear interpolation: weight at atDate between (fromDate, fromWeight) and (toDate, toWeight)
function interpolateWeight(fromDate, fromWeight, toDate, toWeight, atDate) {
  const t0 = new Date(fromDate + 'T00:00:00').getTime();
  const t1 = new Date(toDate + 'T00:00:00').getTime();
  const ta = new Date(atDate + 'T00:00:00').getTime();
  if (t1 === t0) return toWeight;
  if (ta <= t0) return fromWeight;
  if (ta >= t1) return toWeight;
  const frac = (ta - t0) / (t1 - t0);
  return fromWeight + (toWeight - fromWeight) * frac;
}

// ── State ──────────────────────────────────────────────────────────────────

let _userId = null;
let _chartInstance = null;
let _currentRange = '30d';
let _chartData = null;       // last /api/weight-chart response
let _activeTarget = null;    // last /api/weight-targets/active target object
let _recentEntries = [];     // entries for last 14 days

// ── API helpers ────────────────────────────────────────────────────────────

function showPageError(msg) {
  const el = document.getElementById('page-error');
  if (el) el.textContent = msg || '';
}

async function apiFetch(url) {
  const res = await fetch(url);
  if (res.status === 401 || res.status === 403) {
    window.location.href = '/login';
    throw new Error('auth');
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchChartData(range) {
  const from = rangeFromDate(range);
  const to = todayISO();
  return apiFetch(
    `/api/weight-chart?user_id=${encodeURIComponent(_userId)}&from=${from}&to=${to}&include_target=true`
  );
}

async function fetchRecentEntries() {
  const from = addDays(todayISO(), -13);
  const to = todayISO();
  return apiFetch(
    `/api/weight-entries?user_id=${encodeURIComponent(_userId)}&from=${from}&to=${to}`
  );
}

async function fetchAllEntriesSummary() {
  const from = addDays(todayISO(), -364);
  const to = todayISO();
  return apiFetch(
    `/api/weight-entries?user_id=${encodeURIComponent(_userId)}&from=${from}&to=${to}`
  );
}

async function fetchActiveTarget() {
  return apiFetch(`/api/weight-targets/active?user_id=${encodeURIComponent(_userId)}`);
}

// ── Subtitle ─────────────────────────────────────────────────────────────

function renderSubtitle(summary, stats) {
  const el = document.getElementById('page-subtitle');
  if (!el) return;

  const count = summary ? summary.entries_logged : 0;
  const daysRange = summary && summary.first_date && summary.last_date
    ? Math.round((new Date(summary.last_date + 'T00:00:00') - new Date(summary.first_date + 'T00:00:00')) / 86400000) + 1
    : 0;

  let trendStr = '';
  if (stats && stats.delta_7d_kg != null) {
    const d = stats.delta_7d_kg;
    const isFlat = Math.abs(d) < 0.05;
    const arrow = isFlat ? '→' : (d < 0 ? '↓' : '↑');
    trendStr = ` · ${arrow} ${Math.abs(d).toFixed(1)} kg/wk`;
  }

  el.textContent = `${count} entries · ${daysRange} days tracked${trendStr}`;
}

// ── Hero strip ─────────────────────────────────────────────────────────────

function renderHero(stats) {
  const curEl = document.getElementById('current-weight-value');
  if (curEl) {
    curEl.textContent = stats && stats.current_weight_kg != null
      ? `${stats.current_weight_kg.toFixed(1)} kg`
      : '--';
  }

  const avgEl = document.getElementById('avg-7d-value');
  if (avgEl) {
    avgEl.textContent = stats && stats.current_avg_kg != null
      ? `${stats.current_avg_kg.toFixed(1)} kg`
      : '--';
  }

  _renderDeltaPill('delta-week', stats ? stats.delta_7d_kg : null, 'This wk');
  _renderDeltaPill('delta-month', stats ? stats.delta_30d_kg : null, 'This mo');
}

function _renderDeltaPill(id, delta, label) {
  const el = document.getElementById(id);
  if (!el) return;

  if (delta == null) {
    el.textContent = `${label}: --`;
    el.className = 'delta-pill neutral';
    return;
  }

  const isFlat = Math.abs(delta) < 0.05;
  const isLoss = delta < 0;
  const arrow = isFlat ? '→' : (isLoss ? '↓' : '↑');
  el.textContent = `${label}: ${arrow} ${Math.abs(delta).toFixed(1)} kg`;
  el.className = `delta-pill ${isFlat ? 'neutral' : (isLoss ? 'loss' : 'gain')}`;
}

// ── Chart ──────────────────────────────────────────────────────────────────

const CHART_COLORS = {
  actuals:   '#9ca3af',
  trend:     '#2563eb',
  target:    '#16a34a',
  projected: '#60a5fa',
};

function _buildChartDatasets(chartData, range) {
  const actuals = chartData.actuals || [];
  const trend   = chartData.trend   || [];
  const target  = chartData.target  || null;

  // Labels come from the dense trend series (one point per day in range)
  const labels = trend.map(p => p.date);

  // Actuals: map by date; last value per date wins (API sorts by time asc)
  const actualsMap = {};
  actuals.forEach(p => { actualsMap[p.date] = p.weight_kg; });
  const actualsData = labels.map(d => actualsMap[d] != null ? actualsMap[d] : null);

  // Trend: direct mapping, nulls kept for spanGaps
  const trendData = trend.map(p => p.weight_kg);

  const datasets = [
    {
      label: 'Daily weigh-in',
      data: actualsData,
      showLine: false,
      pointBackgroundColor: CHART_COLORS.actuals,
      pointBorderColor: CHART_COLORS.actuals,
      pointRadius: actualsData.map(v => v != null ? 4 : 0),
      pointHoverRadius: 6,
      spanGaps: false,
      order: 1,
    },
    {
      label: '7-day moving avg',
      data: trendData,
      borderColor: CHART_COLORS.trend,
      backgroundColor: 'transparent',
      borderWidth: 2,
      tension: 0.3,
      pointRadius: 0,
      pointHoverRadius: 0,
      spanGaps: false,
      order: 2,
    },
  ];

  // Target: horizontal dashed line at target_weight_kg
  const hasTarget = target && target.target_weight_kg != null;
  if (hasTarget) {
    const tw = target.target_weight_kg;
    datasets.push({
      label: 'Target',
      data: labels.map(() => tw),
      borderColor: CHART_COLORS.target,
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      borderDash: [6, 4],
      pointRadius: 0,
      pointHoverRadius: 0,
      spanGaps: true,
      order: 3,
    });
  } else {
    datasets.push({ label: 'Target', data: [], hidden: true, order: 3 });
  }

  // Projected: dashed line from today → target_date (sparse points from API)
  const hasProjected = hasTarget && Array.isArray(target.projected_path) && target.projected_path.length;
  if (hasProjected) {
    const projMap = {};
    target.projected_path.forEach(p => { projMap[p.date] = p.weight_kg; });
    datasets.push({
      label: 'Projected',
      data: labels.map(d => projMap[d] != null ? projMap[d] : null),
      borderColor: CHART_COLORS.projected,
      backgroundColor: 'transparent',
      borderWidth: 2,
      borderDash: [4, 4],
      pointRadius: 0,
      pointHoverRadius: 0,
      spanGaps: false,
      order: 4,
    });
  } else {
    datasets.push({ label: 'Projected', data: [], hidden: true, order: 4 });
  }

  // Show/hide legend chips for target and projected
  const legendTarget = document.getElementById('legend-target');
  const legendProjected = document.getElementById('legend-projected');
  if (legendTarget) legendTarget.hidden = !hasTarget;
  if (legendProjected) legendProjected.hidden = !hasProjected;

  return { labels, datasets };
}

function _buildYBounds(chartData) {
  const vals = [];
  (chartData.actuals || []).forEach(p => vals.push(p.weight_kg));
  (chartData.trend || []).forEach(p => { if (p.weight_kg != null) vals.push(p.weight_kg); });
  if (chartData.target) {
    vals.push(chartData.target.target_weight_kg);
    (chartData.target.projected_path || []).forEach(p => vals.push(p.weight_kg));
  }
  if (!vals.length) return { min: undefined, max: undefined };

  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = Math.max(1, Math.min(2, (hi - lo) * 0.12));
  return {
    min: Math.floor((lo - pad) / 2) * 2,
    max: Math.ceil((hi + pad) / 2) * 2,
  };
}

function renderChart(chartData, range) {
  _chartData = chartData;
  const { labels, datasets } = _buildChartDatasets(chartData, range);
  const { min: yMin, max: yMax } = _buildYBounds(chartData);

  // X-axis tick callback: show formatted date, thinned by range
  const tickCallback = function (val, idx) {
    const date = labels[idx];
    if (!date) return '';
    const d = new Date(date + 'T00:00:00');

    if (range === '30d') {
      // Every 5th day
      return d.getDate() % 5 === 1 ? fmtDateForRange(date, range) : '';
    }
    if (range === '90d') {
      // 1st of each month
      return d.getDate() === 1 ? fmtDateForRange(date, range) : '';
    }
    // 6m / 1y / all: 1st of each month
    return d.getDate() === 1 ? fmtDateForRange(date, range) : '';
  };

  // hide loading placeholder and reveal canvas on first render
  const loadingEl = document.getElementById('chart-loading');
  const canvasEl = document.getElementById('weight-chart');
  if (loadingEl) loadingEl.hidden = true;
  if (canvasEl) canvasEl.hidden = false;

  if (_chartInstance) {
    _chartInstance.data.labels = labels;
    _chartInstance.data.datasets = datasets;
    _chartInstance.options.scales.y.min = yMin;
    _chartInstance.options.scales.y.max = yMax;
    _chartInstance.options.scales.x.ticks.callback = tickCallback;
    _chartInstance.update();
    return;
  }

  const ctx = document.getElementById('weight-chart').getContext('2d');
  _chartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          filter: (item) => item.parsed.y != null,
          callbacks: {
            title: (items) => {
              const date = labels[items[0]?.dataIndex];
              return date ? fmtDisplayDate(date) : '';
            },
            label: (item) => {
              if (item.parsed.y == null) return null;
              return `${item.dataset.label}: ${item.parsed.y.toFixed(1)} kg`;
            },
          },
        },
      },
      scales: {
        x: {
          type: 'category',
          ticks: {
            callback: tickCallback,
            maxRotation: 0,
            autoSkip: false,
          },
          grid: { display: false },
        },
        y: {
          title: { display: true, text: 'kg' },
          min: yMin,
          max: yMax,
          ticks: {
            stepSize: 2,
          },
        },
      },
    },
  });
}

// ── Progress card ──────────────────────────────────────────────────────────

const STATUS_CLASSES = {
  on_track: 'on-track',
  behind:   'behind',
  ahead:    'ahead',
};

const STATUS_LABELS = {
  on_track: 'On track',
  behind:   'Behind',
  ahead:    'Ahead',
};

function renderProgress(target) {
  const card = document.getElementById('progress-card');
  if (!card) return;

  if (!target) {
    card.hidden = true;
    return;
  }

  card.hidden = false;

  const pct = Math.max(0, Math.min(100, target.progress_pct || 0));

  // Bar fill and marker
  const fill = document.getElementById('progress-bar-fill');
  const marker = document.getElementById('progress-marker');
  if (fill) fill.style.width = `${pct}%`;
  if (marker) marker.style.left = `${pct}%`;

  // Labels
  const startEl = document.getElementById('label-start');
  const currentEl = document.getElementById('label-current');
  const targetEl = document.getElementById('label-target');

  if (startEl) {
    startEl.innerHTML =
      `<strong>${(target.start_weight_kg || 0).toFixed(1)} kg</strong>Start<br>${target.start_date || ''}`;
  }
  if (currentEl) {
    const curW = target.start_weight_kg - (target.kg_to_go || 0) + (pct / 100) *
      Math.abs((target.start_weight_kg || 0) - (target.target_weight_kg || 0));
    // Simpler: current = start - kg_lost; kg_lost = (start - target) * pct/100
    const kgLost = ((target.start_weight_kg || 0) - (target.target_weight_kg || 0)) * pct / 100;
    const currentKg = (target.start_weight_kg || 0) - kgLost;
    currentEl.innerHTML = `<strong>${currentKg.toFixed(1)} kg</strong>Current`;
  }
  if (targetEl) {
    targetEl.innerHTML =
      `<strong>${(target.target_weight_kg || 0).toFixed(1)} kg</strong>Goal<br>${target.target_date || ''}`;
  }

  // Progress pct
  const pctEl = document.getElementById('progress-pct');
  if (pctEl) {
    pctEl.textContent = `${pct.toFixed(0)}`;
    const statusClass = STATUS_CLASSES[target.status_label] || 'neutral';
    pctEl.style.color =
      statusClass === 'on-track' ? '#15803d' :
      statusClass === 'behind'   ? '#b45309' :
      statusClass === 'ahead'    ? '#1d4ed8' : '#374151';
  }

  // kg to go
  const kgEl = document.getElementById('kg-to-go');
  if (kgEl) {
    const kg = target.kg_to_go != null ? target.kg_to_go.toFixed(1) : '--';
    kgEl.textContent = `${kg} kg to go`;
  }

  // Status pill
  const pillEl = document.getElementById('status-pill');
  if (pillEl) {
    const sl = target.status_label || '';
    pillEl.textContent = STATUS_LABELS[sl] || sl;
    pillEl.className = 'status-pill ' + (STATUS_CLASSES[sl] || '');
  }
}

// ── Milestones panel ───────────────────────────────────────────────────────

function renderMilestones(target, stats) {
  const panel = document.getElementById('milestones-panel');
  const list  = document.getElementById('milestones-list');
  if (!panel || !list) return;

  if (!target) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;

  const today = todayISO();
  const currentKg = stats && stats.current_weight_kg != null
    ? stats.current_weight_kg
    : target.start_weight_kg;

  const targetKg   = target.target_weight_kg;
  const targetDate = target.target_date;

  // 4 milestone points: Today, 3 mo (90 days), 6 mo (180 days), Goal
  const milestones = [
    { label: 'Today',  date: today },
    { label: '3 mo',   date: addDays(today, 90) },
    { label: '6 mo',   date: addDays(today, 180) },
    { label: 'Goal',   date: targetDate },
  ];

  list.innerHTML = milestones.map(m => {
    const projWeight = interpolateWeight(today, currentKg, targetDate, targetKg, m.date);
    const displayDate = m.label === 'Goal'
      ? m.date
      : fmtDisplayDate(m.date);
    return `
      <div class="milestone-item">
        <div class="milestone-label">${m.label}</div>
        <div class="milestone-weight">${projWeight.toFixed(1)} kg</div>
        <div class="milestone-date">${displayDate}</div>
      </div>`;
  }).join('');
}

// ── Recent entries (last 14 days) ─────────────────────────────────────────

function _nearestWeight(entries, targetDate) {
  if (!entries.length) return null;
  const sorted = entries.slice().sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  const before = sorted.filter(e => e.entry_date < targetDate);
  if (before.length) return before[before.length - 1].weight_kg;
  const after = sorted.filter(e => e.entry_date > targetDate);
  if (after.length) return after[0].weight_kg;
  return null;
}

function renderRecentEntries(entries, activeTarget) {
  const tbody = document.getElementById('entries-tbody');
  const viewAllLink = document.getElementById('view-all-link');
  if (!tbody) return;

  // Update "View all N →" link count
  if (viewAllLink) {
    viewAllLink.textContent = `View all ${entries.length} →`;
  }

  // Build a map: date → sorted entries (newest time first)
  const byDate = {};
  entries.forEach(e => {
    if (!byDate[e.entry_date]) byDate[e.entry_date] = [];
    byDate[e.entry_date].push(e);
  });
  Object.values(byDate).forEach(arr =>
    arr.sort((a, b) => (b.entry_time || '').localeCompare(a.entry_time || ''))
  );

  // Build 14-day list: today → today-13
  const today = todayISO();
  const days = [];
  for (let i = 0; i < 14; i++) {
    days.push(addDays(today, -i));
  }

  // Compute deltas: compare each entry to the previous logged day (across gaps)
  const allSorted = entries.slice().sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  const prevWeight = {};
  allSorted.forEach((e, idx) => {
    const prev = allSorted.slice(0, idx).filter(x => x.entry_date < e.entry_date).pop();
    prevWeight[e.id] = prev ? e.weight_kg - prev.weight_kg : null;
  });

  // Delta direction: ↓ green when toward target, ↑ red when away from target
  const losingIsGoal = !activeTarget ||
    activeTarget.target_weight_kg == null ||
    activeTarget.start_weight_kg == null ||
    activeTarget.target_weight_kg < activeTarget.start_weight_kg;

  // empty state: if no entries exist at all, show prompt instead of 14 blank rows
  if (!entries.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:24px;color:#9ca3af;font-size:0.9375rem;">
      No weight entries yet — log your first weigh-in above
    </td></tr>`;
    return;
  }

  tbody.innerHTML = days.map(date => {
    const isToday = date === today;
    const rowClass = isToday ? 'entry-row-today' : '';
    const dayEntries = byDate[date];

    if (!dayEntries || !dayEntries.length) {
      // No entry: show faded missing-day-row with ＋ Add chip
      // No entry for this date — render add chip
      return `
        <tr class="${rowClass} missing-day-row" data-date="${date}">
          <td data-label="Date">${fmtDisplayDate(date)}</td>
          <td data-label="Weight" colspan="2">
            <button class="backfill-add-btn" data-date="${date}" data-is-today="${isToday}" type="button"
              aria-label="No entry for ${date} — click to add">＋ Add</button>
          </td>
          <td></td>
        </tr>`;
    }

    // One or more entries on this day
    return dayEntries.map((e, idx) => {
      const delta = prevWeight[e.id];
      let deltaHtml = `<span class="entry-delta neutral">—</span>`;
      if (delta != null) {
        const isFlat = Math.abs(delta) < 0.05;
        const isLoss = delta < 0;
        const isTowardTarget = losingIsGoal ? isLoss : !isLoss;
        const cls = isFlat ? 'neutral' : (isTowardTarget ? 'loss' : 'gain');
        const arrow = isFlat ? '→' : (isLoss ? '↓' : '↑');
        deltaHtml = `<span class="entry-delta ${cls}">${arrow} ${Math.abs(delta).toFixed(1)}</span>`;
      }

      const notesHtml = e.notes
        ? `<div class="entry-notes">${e.notes.replace(/[<>&"]/g, c => ({'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c]))}</div>`
        : '';

      return `
        <tr class="${rowClass}" data-entry-id="${e.id}">
          <td data-label="Date">
            ${idx === 0 ? fmtDisplayDate(date) : ''}
            ${notesHtml}
          </td>
          <td data-label="Weight"><span class="entry-weight">${e.weight_kg.toFixed(1)} kg</span></td>
          <td data-label="Delta">${deltaHtml}</td>
          <td class="entry-actions-wrap">
            <button class="entry-menu-btn" data-entry-id="${e.id}" data-weight="${e.weight_kg}" data-date="${e.entry_date}" type="button"
              aria-label="Actions for entry ${e.id}" aria-expanded="false">⋯</button>
          </td>
        </tr>`;
    }).join('');
  }).join('');

  // Wire backfill ＋ Add chip buttons
  tbody.querySelectorAll('.backfill-add-btn').forEach(btn => {
    const date = btn.dataset.date;
    const isToday = btn.dataset.isToday === 'true';
    btn.addEventListener('click', () => _openMiniStepper(btn, date));
    // Auto-open stepper for today's row if unlogged
    if (isToday) {
      _openMiniStepper(btn, date);
    }
  });

  // Wire entry menu buttons
  tbody.querySelectorAll('.entry-menu-btn').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      _toggleEntryMenu(btn);
    });
  });

  // Close open menus on outside click
  document.addEventListener('click', _closeAllMenus);
}

// ── Entry actions menu ─────────────────────────────────────────────────────

function _closeAllMenus() {
  document.querySelectorAll('.entry-menu').forEach(m => m.remove());
  document.querySelectorAll('.entry-menu-btn').forEach(b => b.setAttribute('aria-expanded', 'false'));
}

function _toggleEntryMenu(btn) {
  const existing = btn.parentElement.querySelector('.entry-menu');
  if (existing) {
    existing.remove();
    btn.setAttribute('aria-expanded', 'false');
    return;
  }
  _closeAllMenus();

  const entryId = btn.dataset.entryId;
  const weight = btn.dataset.weight;
  const entryDate = btn.dataset.date;
  const menu = document.createElement('div');
  menu.className = 'entry-menu';
  menu.innerHTML = `
    <button class="entry-edit" data-id="${entryId}" data-weight="${weight}" data-date="${entryDate}" type="button">Edit</button>
    <button class="menu-delete" data-id="${entryId}" type="button">Delete</button>`;
  btn.parentElement.appendChild(menu);
  btn.setAttribute('aria-expanded', 'true');

  menu.querySelector('.entry-edit').addEventListener('click', (ev) => {
    ev.stopPropagation();
    _closeAllMenus();
    const row = btn.closest('tr');
    openInlineEdit(row, entryId, parseFloat(weight), entryDate);
  });

  menu.querySelector('.menu-delete').addEventListener('click', async (ev) => {
    ev.stopPropagation();
    if (!confirm('Delete this entry?')) return;
    try {
      const res = await fetch(`/api/weight-entries/${encodeURIComponent(entryId)}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      UIStates.showToast('Entry deleted');
      await _reload();
    } catch (e) {
      showPageError('Delete failed: ' + e.message);
    }
  });
}

// ── Inline edit and patch ──────────────────────────────────────────────────

function openInlineEdit(row, entryId, currentWeight, currentDate) {
  if (!row) return;
  row.innerHTML = `
    <td colspan="4">
      <form class="inline-edit-form" novalidate>
        <input type="number" step="0.1" min="20" max="300"
          class="backfill-input" value="${currentWeight.toFixed(1)}" aria-label="Weight in kg">
        <button type="submit" class="inline-save-btn">Save</button>
        <button type="button" class="inline-cancel-btn">Cancel</button>
        <span class="backfill-error" role="alert"></span>
      </form>
    </td>`;

  const form = row.querySelector('form');
  const weightInput = form.querySelector('input');
  const errEl = form.querySelector('.backfill-error');

  weightInput.focus();

  row.addEventListener('keydown', function onEscape(ev) {
    if (ev.key === 'Escape') {
      row.removeEventListener('keydown', onEscape);
      _reload();
    }
  });

  form.querySelector('.inline-cancel-btn').addEventListener('click', () => _reload());

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errEl.textContent = '';
    const val = parseFloat(weightInput.value);
    if (isNaN(val) || val <= 0) {
      errEl.textContent = 'Weight must be a positive number.';
      weightInput.focus();
      return;
    }
    if (val < 20 || val > 300) {
      errEl.textContent = 'Weight must be between 20 and 300 kg.';
      weightInput.focus();
      return;
    }
    try {
      await patchEntry(entryId, { weight_kg: val });
      UIStates.showToast('Entry updated');
      await _reload();
    } catch (e) {
      if (e.message === 'conflict') {
        errEl.textContent = 'Date conflict with another entry.';
      } else {
        showPageError('Save failed: ' + e.message);
      }
    }
  });
}

async function patchEntry(entryId, data) {
  const res = await fetch(`/api/weight-entries/${encodeURIComponent(entryId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (res.status === 409) throw new Error('conflict');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Backfill / mini-stepper ────────────────────────────────────────────────

function _openMiniStepper(btn, date) {
  const td = btn.closest('td');
  if (!td) return;

  const prefill = _nearestWeight(_recentEntries, date) || 70.0;
  const initVal = (Math.round(prefill * 10) / 10).toFixed(1);

  td.innerHTML = `
    <form class="mini-stepper backfill-inline" novalidate>
      <button type="button" class="stepper-btn stepper-dec" aria-label="Decrease">&#x2212;</button>
      <input type="number" step="0.1" min="20" max="300"
        class="stepper-value backfill-input" value="${initVal}" aria-label="Weight in kg">
      <button type="button" class="stepper-btn stepper-inc" aria-label="Increase">+</button>
      <button type="submit" class="stepper-log-btn backfill-save-btn">Log</button>
      <button type="button" class="backfill-cancel-btn" style="font-size:0.8125rem;background:none;border:none;color:#9ca3af;cursor:pointer">&#x2715;</button>
      <span class="stepper-error backfill-error" role="alert"></span>
    </form>`;

  const form = td.querySelector('form');
  const input = td.querySelector('.stepper-value');
  const errEl = td.querySelector('.stepper-error');

  input.focus();
  input.select();

  td.querySelector('.stepper-dec').addEventListener('click', () => {
    const v = parseFloat(input.value) || 0;
    input.value = Math.max(20, v - 0.1).toFixed(1);
  });

  td.querySelector('.stepper-inc').addEventListener('click', () => {
    const v = parseFloat(input.value) || 0;
    input.value = Math.min(300, v + 0.1).toFixed(1);
  });

  td.querySelector('.backfill-cancel-btn').addEventListener('click', () => _reload());

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errEl.textContent = '';
    const raw = parseFloat(input.value);
    if (isNaN(raw) || raw < 20 || raw > 300) {
      errEl.textContent = 'Enter a valid weight (20–300 kg).';
      input.focus();
      return;
    }
    // reject future date: allow today and up to 1 day ahead, reject beyond that
    if (date > addDays(todayISO(), 1)) {
      errEl.textContent = 'Cannot log a weight entry for a future date.';
      return;
    }

    try {
      const res = await fetch('/api/weight-entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: _userId,
          entry_date: date,
          weight_kg: raw,
        }),
      });

      if (res.status === 409) {
        errEl.textContent = 'Entry already exists for this date.';
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      UIStates.showToast('Entry saved');
      await _reload();
    } catch (e) {
      showPageError('Save failed: ' + e.message);
    }
  });
}

// ── Quick-log ──────────────────────────────────────────────────────────────

function _initQuickLog() {
  const form   = document.getElementById('quicklog-form');
  const input  = document.getElementById('quicklog-input');
  const errEl  = document.getElementById('quicklog-error');
  const btn    = form ? form.querySelector('button[type="submit"]') : null;

  if (!form) return;

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (errEl) errEl.textContent = '';
    showPageError('');

    const raw = parseFloat(input.value);
    if (isNaN(raw) || raw < 20 || raw > 300) {
      if (errEl) errEl.textContent = 'Enter a valid weight (20–300 kg).';
      input.focus();
      return;
    }

    if (btn) btn.disabled = true;

    try {
      const res = await fetch('/api/weight-entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: _userId,
          entry_date: todayISO(),
          entry_time: nowHHMM(),
          weight_kg: raw,
        }),
      });

      if (res.status === 409) {
        if (errEl) errEl.textContent = 'Entry already exists for today — backfill or delete it first.';
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      UIStates.showToast('Logged!');
      form.reset();
      await _reload();
    } catch (e) {
      showPageError('Log failed: ' + e.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

// ── Range tabs ─────────────────────────────────────────────────────────────

function _initRangeTabs() {
  document.querySelectorAll('.range-tab').forEach(btn => {
    btn.addEventListener('click', async () => {
      _currentRange = btn.dataset.range;
      document.querySelectorAll('.range-tab').forEach(b => b.classList.toggle('active', b === btn));

      try {
        const data = await fetchChartData(_currentRange);
        renderChart(data, _currentRange);
      } catch (e) {
        showPageError('Chart load failed: ' + e.message);
      }
    });
  });
}

// ── Full reload (after mutations) ─────────────────────────────────────────

async function _reload() {
  try {
    const [chartData, entriesRes, targetRes, summaryRes] = await Promise.all([
      fetchChartData(_currentRange),
      fetchRecentEntries(),
      fetchActiveTarget(),
      fetchAllEntriesSummary(),
    ]);

    _chartData = chartData;
    _recentEntries = entriesRes.entries || [];
    _activeTarget = targetRes.target || null;

    renderSubtitle(summaryRes.summary, chartData.stats);
    renderHero(chartData.stats);
    renderChart(chartData, _currentRange);
    renderProgress(_activeTarget);
    renderMilestones(_activeTarget, chartData.stats);
    renderRecentEntries(_recentEntries, _activeTarget);
  } catch (e) {
    if (e.message !== 'auth') showPageError('Load error: ' + e.message);
  }
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Identify session user
  try {
    const me = await apiFetch('/api/auth/me');
    _userId = me.id;
  } catch (e) {
    if (e.message !== 'auth') showPageError('Could not identify user: ' + e.message);
    return;
  }

  _initQuickLog();
  _initRangeTabs();

  const exportBtn = document.getElementById('export-csv-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      let url;
      if (_currentRange === 'all') {
        url = `/api/exports/weight-entries?user_id=${encodeURIComponent(_userId)}`;
      } else {
        const from = rangeFromDate(_currentRange);
        const to = todayISO();
        url = `/api/exports/weight-entries?user_id=${encodeURIComponent(_userId)}&from=${from}&to=${to}`;
      }
      window.location.href = url;
    });
  }

  await _reload();
});
