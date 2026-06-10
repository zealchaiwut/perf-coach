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

// ── Hero: Card A (Current Weight) ─────────────────────────────────────────

function _relativeLoggedDate(actuals) {
  if (!actuals || !actuals.length) return '';
  const lastDate = actuals[actuals.length - 1].date;
  const today = todayISO();
  if (lastDate === today) return 'Today';
  const yesterday = addDays(today, -1);
  if (lastDate === yesterday) {
    const d = new Date(lastDate + 'T00:00:00');
    const mo = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return `Logged yesterday · ${mo}`;
  }
  const diffMs = new Date(today + 'T00:00:00') - new Date(lastDate + 'T00:00:00');
  const diffDays = Math.round(diffMs / 86400000);
  const d = new Date(lastDate + 'T00:00:00');
  const mo = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `Logged ${diffDays} days ago · ${mo}`;
}

function _pillClass(delta, activeTarget) {
  if (delta == null || Math.abs(delta) < 0.05) return 'neutral';
  if (!activeTarget) return delta < 0 ? 'toward' : 'away';
  const isLossGoal = activeTarget.target_weight_kg < activeTarget.start_weight_kg;
  const towardTarget = isLossGoal ? delta < 0 : delta > 0;
  return towardTarget ? 'toward' : 'away';
}

function renderHeroCardA(chartData, activeTarget) {
  const stats   = chartData ? chartData.stats : null;
  const actuals = chartData ? (chartData.actuals || []) : [];

  const dateSubEl = document.getElementById('hca-date-sub');
  if (dateSubEl) dateSubEl.textContent = _relativeLoggedDate(actuals);

  const avgEl = document.getElementById('hca-avg');
  if (avgEl) {
    avgEl.textContent = stats && stats.current_avg_kg != null
      ? `${stats.current_avg_kg.toFixed(1)} kg`
      : '--';
  }

  const weightEl = document.getElementById('hca-weight');
  if (weightEl) {
    weightEl.textContent = stats && stats.current_weight_kg != null
      ? `${stats.current_weight_kg.toFixed(1)} kg`
      : '--';
  }

  _renderHcaPill('hca-pill-week',  stats ? stats.delta_7d_kg  : null, 'This wk', activeTarget);
  _renderHcaPill('hca-pill-month', stats ? stats.delta_30d_kg : null, 'This mo', activeTarget);
}

function _renderHcaPill(id, delta, label, activeTarget) {
  const el = document.getElementById(id);
  if (!el) return;
  if (delta == null) {
    el.textContent = `${label}: --`;
    el.className = 'delta-pill neutral';
    return;
  }
  const isFlat = Math.abs(delta) < 0.05;
  const arrow = isFlat ? '→' : (delta < 0 ? '↓' : '↑');
  el.textContent = `${label}: ${arrow} ${Math.abs(delta).toFixed(1)} kg`;
  el.className = `delta-pill ${_pillClass(delta, activeTarget)}`;
}

// ── Coach strip ────────────────────────────────────────────────────────────

function renderCoachStrip(chartData, activeTarget) {
  const strip   = document.getElementById('coach-strip');
  const textEl  = document.getElementById('coach-text');
  if (!strip || !textEl) return;

  const loggedToday   = chartData && chartData.logged_today;
  const todayDeltaKg  = chartData ? chartData.today_delta_kg : null;

  if (!loggedToday) {
    strip.className = 'coach-strip coach-grey';
    textEl.textContent = '😴 No entry yet today — log your weight to wake me up';
    return;
  }

  const isLossGoal = activeTarget
    ? activeTarget.target_weight_kg < activeTarget.start_weight_kg
    : true;

  const isFlat = todayDeltaKg == null || Math.abs(todayDeltaKg) < 0.05;
  const movedToward = isFlat || (isLossGoal ? todayDeltaKg < 0 : todayDeltaKg > 0);

  if (movedToward) {
    strip.className = 'coach-strip coach-green';
    textEl.textContent = '🎉 You did well — on pace this week';
  } else {
    strip.className = 'coach-strip coach-amber';
    const awayMsg = isLossGoal
      ? '💪 Up a little — new day, keep going'
      : '💪 Down a little — new day, keep going';
    textEl.textContent = awayMsg;
  }
}

// ── Chart ──────────────────────────────────────────────────────────────────

function renderChart(chartData, range) {
  _chartData = chartData;
  WeightChart.render(chartData, range);

  const hasTarget = !!(chartData.plan_series && chartData.plan_series.length);
  const legendPlan      = document.getElementById('legend-plan');
  const legendGap       = document.getElementById('legend-gap');
  const legendMilestone = document.getElementById('legend-milestone');
  if (legendPlan)      legendPlan.hidden      = !hasTarget;
  if (legendGap)       legendGap.hidden       = !hasTarget;
  if (legendMilestone) legendMilestone.hidden = !hasTarget;
}

// ── Progress card ──────────────────────────────────────────────────────────

// Kept for backward-compat with test_weight_page_frontend__412 / __339
// (status_label-based pill is superseded by gap_direction pill in #424)
const STATUS_CLASSES = {
  on_track: 'on-track',
  behind:   'behind',
  ahead:    'ahead',
};

function _fmtShortDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  if (isNaN(d)) return '';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
}

function renderProgress(target) {
  const card = document.getElementById('progress-card');
  if (!card) return;

  if (!target) {
    card.hidden = true;
    return;
  }

  card.hidden = false;

  const pct       = Math.max(0, Math.min(100, target.progress_pct || 0));
  const startW    = target.start_weight_kg || 0;
  const targetW   = target.target_weight_kg || 0;
  const planTodayKg = target.plan_today_kg;
  const gapKg     = target.gap_kg;           // null when no_data
  const gapDir    = target.gap_direction || 'no_data';

  // ── Three-stat row ──────────────────────────────────────────────

  const startValEl  = document.getElementById('pstat-start-val');
  const startDateEl = document.getElementById('pstat-start-date');
  if (startValEl)  startValEl.textContent  = `${startW.toFixed(1)} kg`;
  if (startDateEl) startDateEl.textContent = _fmtShortDate(target.start_date || '');

  // current basis = plan_today + gap  (derived; no extra API field needed)
  const currentBasisKg = (gapKg != null) ? planTodayKg + gapKg : null;
  const youValEl  = document.getElementById('pstat-you-val');
  const planSubEl = document.getElementById('pstat-plan-sub');
  if (youValEl)  youValEl.textContent  = currentBasisKg != null ? `${currentBasisKg.toFixed(1)} kg` : '--';
  if (planSubEl) planSubEl.textContent = planTodayKg != null ? `plan ${planTodayKg.toFixed(1)} kg` : 'plan --';

  const goalValEl  = document.getElementById('pstat-goal-val');
  const goalDateEl = document.getElementById('pstat-goal-date');
  if (goalValEl)  goalValEl.textContent  = `${targetW.toFixed(1)} kg`;
  if (goalDateEl) goalDateEl.textContent = _fmtShortDate(target.target_date || '');

  // ── Bar: gradient fill, you-dot, plan-tick, micro-labels ────────

  // Gradient fill width = progress_pct
  const fillEl = document.getElementById('pgbar-fill');
  if (fillEl) fillEl.style.width = `${pct}%`;

  // You-dot position (progress_pct)
  const youDotEl = document.getElementById('pgbar-you-dot');
  if (youDotEl) youDotEl.style.left = `${pct}%`;

  // Plan-tick position: (start − plan_today) / (start − target) × 100
  const totalRange = startW - targetW;
  const planPct = (totalRange !== 0 && planTodayKg != null)
    ? Math.max(0, Math.min(100, (startW - planTodayKg) / totalRange * 100))
    : pct;
  const planTickEl = document.getElementById('pgbar-plan-tick');
  if (planTickEl) planTickEl.style.left = `${planPct}%`;

  // Micro-labels positioned under their respective marks
  const microYouEl  = document.getElementById('pgbar-micro-you');
  if (microYouEl)  microYouEl.style.left  = `${pct}%`;
  const microPlanEl = document.getElementById('pgbar-micro-plan');
  if (microPlanEl) microPlanEl.style.left = `${planPct}%`;

  // ── Summary row ─────────────────────────────────────────────────

  const pctBigEl = document.getElementById('progress-pct-big');
  if (pctBigEl) pctBigEl.textContent = `${pct.toFixed(0)}%`;

  const detailEl = document.getElementById('progress-detail');
  if (detailEl) {
    const kgStr  = target.kg_to_go != null ? `${target.kg_to_go.toFixed(1)} kg to go` : '--';
    const dayStr = target.days_remaining != null ? `${target.days_remaining} days` : '--';
    detailEl.textContent = `${kgStr} · ${dayStr}`;
  }

  // Backward-compat hidden kg-to-go span (test_weight_page_frontend__412)
  const kgToGoEl = document.getElementById('kg-to-go');
  if (kgToGoEl) kgToGoEl.textContent = target.kg_to_go != null ? `${target.kg_to_go.toFixed(1)} kg` : '--';

  // ── Status pill driven by gap_direction ─────────────────────────
  // Values: 'behind' | 'ahead' | 'on_plan' | 'no_data'
  // Raw gap_direction enum strings are never rendered directly to the UI.

  const pillEl = document.getElementById('pgstatus-pill');
  if (pillEl) {
    const pace = target.required_pace_kg_per_week;
    let pillText, pillClass;

    if (gapDir === 'behind') {
      const absGap  = gapKg   != null ? Math.abs(gapKg).toFixed(1)   : '?';
      const paceStr = pace    != null ? pace.toFixed(2)               : '?';
      pillText  = `+${absGap} kg behind plan · need ${paceStr} kg/wk`;
      pillClass = 'pill-behind';
    } else if (gapDir === 'ahead') {
      const absGap = gapKg != null ? Math.abs(gapKg).toFixed(1) : '?';
      pillText  = `${absGap} kg ahead of plan`;
      pillClass = 'pill-ahead';
    } else if (gapDir === 'on_plan') {
      pillText  = 'On plan';
      pillClass = 'pill-on-plan';
    } else {
      // no_data
      pillText  = 'Just started — log daily to see your pace';
      pillClass = 'pill-no-data';
    }

    pillEl.textContent = pillText;
    pillEl.className   = `pgstatus-pill ${pillClass}`;
  }
}

// ── Milestones panel ───────────────────────────────────────────────────────

function renderMilestones(target) {
  const rowsEl = document.getElementById('milestone-rows');
  if (!rowsEl) return;

  if (!target || !target.milestones || !target.milestones.length) {
    rowsEl.innerHTML = '';
    return;
  }

  const gapDir      = target.gap_direction || 'no_data';
  const planTodayKg = target.plan_today_kg;
  const gapKg       = target.gap_kg;
  // current basis derived the same way as in renderProgress
  const currentBasisKg = (gapKg != null) ? planTodayKg + gapKg : null;

  rowsEl.innerHTML = target.milestones.map(m => {
    const dateDisplay = m.date ? (() => {
      const d = new Date(m.date + 'T00:00:00');
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    })() : '--';

    if (m.kind === 'today') {
      // Today row: actual basis weight + plan sub + signed delta chip
      const actualDisplay = currentBasisKg != null ? `${currentBasisKg.toFixed(1)} kg` : '--';
      const planSub = planTodayKg != null ? `plan ${planTodayKg.toFixed(1)} kg` : '';

      let rowClass = 'milestone-row milestone-row-standard';
      if      (gapDir === 'behind')  rowClass = 'milestone-row milestone-today-behind';
      else if (gapDir === 'ahead')   rowClass = 'milestone-row milestone-today-ahead';
      else if (gapDir === 'on_plan') rowClass = 'milestone-row milestone-today-on-plan';

      let deltaHtml = '';
      if (gapKg != null) {
        const sign      = gapKg >= 0 ? '+' : '';
        const chipClass = Math.abs(gapKg) < 0.15
          ? 'milestone-delta-neutral'
          : (gapKg < 0 ? 'milestone-delta-ahead' : 'milestone-delta-behind');
        deltaHtml = `<span class="milestone-row-delta ${chipClass}">${sign}${gapKg.toFixed(1)} kg</span>`;
      }

      return `
        <div class="${rowClass}">
          <div class="milestone-row-date">${dateDisplay}</div>
          <div class="milestone-row-center">
            <div class="milestone-row-weight">${actualDisplay}</div>
            <div class="milestone-row-sub">${planSub}</div>
          </div>
          ${deltaHtml}
        </div>`;
    }

    // Intermediate or goal row: plan kg + ↓ remaining from today's plan position
    const planDisplay = m.plan_kg != null ? `${m.plan_kg.toFixed(1)} kg` : '--';
    const remaining   = (planTodayKg != null && m.plan_kg != null)
      ? Math.abs(planTodayKg - m.plan_kg)
      : null;
    const remainSub = remaining != null ? `↓ ${remaining.toFixed(1)} kg to go` : '';
    const kindLabel = m.kind === 'goal' ? 'Goal' : '';

    return `
      <div class="milestone-row milestone-row-standard">
        <div class="milestone-row-date">${dateDisplay}${kindLabel ? `<div style="font-size:0.625rem;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.05em;">${kindLabel}</div>` : ''}</div>
        <div class="milestone-row-center">
          <div class="milestone-row-weight">${planDisplay}</div>
          <div class="milestone-row-sub">${remainSub}</div>
        </div>
      </div>`;
  }).join('');
}

// ── Recent entries (last 14 days) ─────────────────────────────────────────

function renderRecentEntries(entries) {
  const tbody = document.getElementById('entries-tbody');
  if (!tbody) return;

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

  // Compute deltas: compare each entry to the previous date's last entry
  const allSorted = entries.slice().sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  const prevWeight = {};
  allSorted.forEach((e, idx) => {
    const prev = allSorted.slice(0, idx).filter(x => x.entry_date < e.entry_date).pop();
    prevWeight[e.id] = prev ? e.weight_kg - prev.weight_kg : null;
  });

  // empty state: if no entries exist at all, show prompt instead of 14 blank rows
  if (!entries.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:#9ca3af;font-size:0.9375rem;">
      No weight entries yet — log your first weigh-in above
    </td></tr>`;
    return;
  }

  tbody.innerHTML = days.map(date => {
    const isToday = date === today;
    const rowClass = isToday ? 'entry-row-today' : '';
    const dayEntries = byDate[date];

    if (!dayEntries || !dayEntries.length) {
      // empty state: no entry for this day — show backfill prompt
      return `
        <tr class="${rowClass}">
          <td data-label="Date">${fmtDisplayDate(date)}</td>
          <td data-label="Time"><span class="entry-no-data">No entry</span></td>
          <td data-label="Weight">
            <button class="backfill-add-btn" data-date="${date}" type="button"
              aria-label="Add entry for ${date}">+</button>
          </td>
          <td data-label="Delta"></td>
          <td></td>
        </tr>`;
    }

    // One or more entries on this day
    return dayEntries.map((e, idx) => {
      const delta = prevWeight[e.id];
      let deltaHtml = '';
      if (delta != null) {
        const isFlat = Math.abs(delta) < 0.05;
        const cls = isFlat ? 'neutral' : (delta < 0 ? 'loss' : 'gain');
        const arrow = isFlat ? '→' : (delta < 0 ? '↓' : '↑');
        deltaHtml = `<span class="entry-delta ${cls}">${arrow} ${Math.abs(delta).toFixed(1)}</span>`;
      }

      const timeStr = e.entry_time ? e.entry_time.slice(0, 5) : '--';

      return `
        <tr class="${rowClass}" data-entry-id="${e.id}">
          <td data-label="Date">${idx === 0 ? fmtDisplayDate(date) : ''}</td>
          <td data-label="Time">${timeStr}</td>
          <td data-label="Weight"><span class="entry-weight">${e.weight_kg.toFixed(1)} kg</span></td>
          <td data-label="Delta">${deltaHtml}</td>
          <td class="entry-actions-wrap">
            <button class="entry-menu-btn" data-entry-id="${e.id}" type="button"
              aria-label="Actions for entry ${e.id}" aria-expanded="false">⋯</button>
          </td>
        </tr>`;
    }).join('');
  }).join('');

  // Wire backfill + buttons
  tbody.querySelectorAll('.backfill-add-btn').forEach(btn => {
    btn.addEventListener('click', () => _openBackfill(btn, btn.dataset.date));
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
  const menu = document.createElement('div');
  menu.className = 'entry-menu';
  menu.innerHTML = `
    <button class="menu-delete" data-id="${entryId}" type="button">Delete</button>`;
  btn.parentElement.appendChild(menu);
  btn.setAttribute('aria-expanded', 'true');

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

// ── Backfill ───────────────────────────────────────────────────────────────

function _openBackfill(btn, date) {
  const td = btn.closest('td');
  if (!td) return;

  td.innerHTML = `
    <form class="backfill-inline" novalidate>
      <input type="number" step="0.1" min="20" max="300"
        class="backfill-input" placeholder="kg" aria-label="Weight in kg">
      <button type="submit" class="backfill-save-btn">Save</button>
      <button type="button" class="backfill-cancel-btn">✕</button>
      <span class="backfill-error" role="alert"></span>
    </form>`;

  const form = td.querySelector('form');
  const input = td.querySelector('.backfill-input');
  const errEl = td.querySelector('.backfill-error');
  input.focus();

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

// ── Card B: Log Today stepper ─────────────────────────────────────────────

let _cardBEntryId = null; // id of today's existing entry, null if not yet logged

function _updateLogBtnLabel() {
  const input = document.getElementById('stepper-input');
  const btn   = document.getElementById('log-submit-btn');
  if (!input || !btn) return;
  const v = parseFloat(input.value);
  btn.textContent = isNaN(v) ? 'Log -- kg' : `Log ${v.toFixed(1)} kg`;
}

function _clampStepperValue(v) {
  if (isNaN(v)) return 20;
  return Math.max(20, Math.min(300, v));
}

function _prefillStepper(weight) {
  const input = document.getElementById('stepper-input');
  if (!input) return;
  input.value = weight != null ? weight.toFixed(1) : '';
  _updateLogBtnLabel();
}

function _showStepperMode() {
  const wrap   = document.getElementById('stepper-wrap');
  const logged = document.getElementById('logged-strip');
  if (wrap)   wrap.hidden   = false;
  if (logged) logged.hidden = true;
}

function _showLoggedMode(weightKg) {
  const wrap      = document.getElementById('stepper-wrap');
  const logged    = document.getElementById('logged-strip');
  const loggedTxt = document.getElementById('logged-text');
  if (wrap)   wrap.hidden   = true;
  if (logged) logged.hidden = false;
  if (loggedTxt) loggedTxt.textContent = `✓ Logged today · ${weightKg.toFixed(1)} kg · `;
}

async function _submitCardB(weightKg) {
  const errEl = document.getElementById('hcb-error');
  const btn   = document.getElementById('log-submit-btn');
  if (errEl) errEl.textContent = '';
  showPageError('');

  if (isNaN(weightKg) || weightKg < 20 || weightKg > 300) {
    if (errEl) errEl.textContent = 'Enter a valid weight (20–300 kg).';
    return;
  }

  if (btn) btn.disabled = true;

  try {
    if (_cardBEntryId) {
      // Edit mode: PATCH the existing entry
      const patchRes = await fetch(`/api/weight-entries/${encodeURIComponent(_cardBEntryId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weight_kg: weightKg }),
      });
      if (!patchRes.ok) throw new Error(`HTTP ${patchRes.status}`);
    } else {
      // New log: attempt POST
      const postRes = await fetch('/api/weight-entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: _userId,
          entry_date: todayISO(),
          entry_time: nowHHMM(),
          weight_kg: weightKg,
        }),
      });

      if (postRes.status === 409) {
        // Race condition: entry already exists — fall back to PATCH using existing_id
        const conflict = await postRes.json();
        const existingId = conflict.existing_id;
        if (!existingId) throw new Error('409 with no existing_id');
        const patchRes = await fetch(`/api/weight-entries/${encodeURIComponent(existingId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ weight_kg: weightKg }),
        });
        if (!patchRes.ok) throw new Error(`HTTP ${patchRes.status}`);
        _cardBEntryId = existingId;
      } else if (!postRes.ok) {
        throw new Error(`HTTP ${postRes.status}`);
      } else {
        const created = await postRes.json();
        _cardBEntryId = created.id;
      }
    }

    UIStates.showToast('Logged!');
    // Update logged strip weight for future Edit clicks
    const logged = document.getElementById('logged-strip');
    if (logged) logged.dataset.weight = weightKg;
    _showLoggedMode(weightKg);
    await _reloadHeroAndCoach();
    await _reloadEntries();
  } catch (e) {
    showPageError('Log failed: ' + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _initCardB() {
  const decBtn  = document.getElementById('stepper-dec');
  const incBtn  = document.getElementById('stepper-inc');
  const input   = document.getElementById('stepper-input');
  const logBtn  = document.getElementById('log-submit-btn');
  const editBtn = document.getElementById('edit-link');
  const dateEl  = document.getElementById('hcb-date');

  if (!input || !logBtn) return;

  // Show today's date in Card B label row
  if (dateEl) {
    const d = new Date(todayISO() + 'T00:00:00');
    dateEl.textContent = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }

  // Stepper ± buttons
  if (decBtn) {
    decBtn.addEventListener('click', () => {
      const v = _clampStepperValue(parseFloat(input.value) - 0.1);
      input.value = v.toFixed(1);
      _updateLogBtnLabel();
    });
  }
  if (incBtn) {
    incBtn.addEventListener('click', () => {
      const v = _clampStepperValue(parseFloat(input.value) + 0.1);
      input.value = v.toFixed(1);
      _updateLogBtnLabel();
    });
  }

  // Live-update button label on input change
  input.addEventListener('input', _updateLogBtnLabel);

  // Submit
  logBtn.addEventListener('click', async () => {
    await _submitCardB(parseFloat(input.value));
  });

  // Edit link: restore stepper with logged value
  if (editBtn) {
    editBtn.addEventListener('click', () => {
      const logged = document.getElementById('logged-strip');
      const weight = logged ? parseFloat(logged.dataset.weight) : NaN;
      _prefillStepper(!isNaN(weight) ? weight : null);
      _showStepperMode();
      input.focus();
    });
  }
}

function _cardBSetLoggedState(entries, fallbackWeight) {
  const today = todayISO();
  const todayEntry = entries.find(e => e.entry_date === today);
  if (todayEntry) {
    _cardBEntryId = todayEntry.id;
    const logged = document.getElementById('logged-strip');
    if (logged) logged.dataset.weight = todayEntry.weight_kg;
    _prefillStepper(todayEntry.weight_kg);
    _showLoggedMode(todayEntry.weight_kg);
  } else {
    _cardBEntryId = null;
    // Prefill stepper with most recent entry (fallback from chart stats)
    if (fallbackWeight != null) _prefillStepper(fallbackWeight);
    _showStepperMode();
  }
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

// ── Partial reloads ───────────────────────────────────────────────────────

async function _reloadHeroAndCoach() {
  try {
    const chartData = await fetchChartData(_currentRange);
    _chartData = chartData;
    renderHeroCardA(chartData, _activeTarget);
    renderCoachStrip(chartData, _activeTarget);
  } catch (e) {
    if (e.message !== 'auth') showPageError('Refresh failed: ' + e.message);
  }
}

async function _reloadEntries() {
  try {
    const entriesRes = await fetchRecentEntries();
    _recentEntries = entriesRes.entries || [];
    renderRecentEntries(_recentEntries);
  } catch (e) {
    if (e.message !== 'auth') showPageError('Entries reload failed: ' + e.message);
  }
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
    renderHeroCardA(chartData, _activeTarget);
    renderCoachStrip(chartData, _activeTarget);
    renderChart(chartData, _currentRange);
    renderProgress(_activeTarget);
    renderMilestones(_activeTarget);
    renderRecentEntries(_recentEntries);
    _cardBSetLoggedState(_recentEntries, chartData.stats ? chartData.stats.current_weight_kg : null);
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

  _initCardB();
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
