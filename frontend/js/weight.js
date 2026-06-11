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
  const offsets = { '7d': -6, '30d': -29, '90d': -89, '6m': -180, '1y': -364, 'all': -364 };
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
let _historySummary = null;  // last /api/weight-targets/history-summary response

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

async function fetchTargetHistorySummary() {
  return apiFetch(`/api/weight-targets/history-summary?user_id=${encodeURIComponent(_userId)}`);
}

async function fetchTargetHistory(status) {
  let url = `/api/weight-targets/history?user_id=${encodeURIComponent(_userId)}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;
  return apiFetch(url);
}

// ── Subtitle ─────────────────────────────────────────────────────────────

function renderSubtitle(summary, stats) {
  const el = document.getElementById('page-subtitle');
  if (!el) return;

  const count = summary ? summary.entries_logged : 0;
  const last14Count = _recentEntries.filter(e => e.weight_kg != null).length;

  let trendStr = '';
  if (stats && stats.delta_7d_kg != null) {
    const d = stats.delta_7d_kg;
    const isFlat = Math.abs(d) < 0.05;
    const arrow = isFlat ? '→' : (d < 0 ? '↓' : '↑');
    trendStr = ` · trending ${arrow} ${Math.abs(d).toFixed(1)} kg/wk`;
  }

  el.textContent = `${count} entries · ${last14Count} of last 14 days${trendStr}`;
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
  if (planSubEl) planSubEl.textContent = planTodayKg != null ? `plan says ${planTodayKg.toFixed(1)}` : 'plan --';

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

function _nearestWeight(entries, targetDate) {
  if (!entries.length) return null;
  const sorted = entries.slice().sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  const before = sorted.filter(e => e.entry_date < targetDate);
  if (before.length) return before[before.length - 1].weight_kg;
  const after = sorted.filter(e => e.entry_date > targetDate);
  if (after.length) return after[0].weight_kg;
  return null;
}

function renderRecentEntries(entries, activeTarget, totalEntries) {
  const container = document.getElementById('recent-entries');
  const viewAllLink = document.getElementById('view-all-link');
  if (!container) return;

  // Use total_entries from history-summary for the "View all N" count
  const displayCount = totalEntries != null ? totalEntries : entries.length;
  if (viewAllLink) {
    viewAllLink.textContent = `View all ${displayCount} →`;
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

  function _esc(s) {
    return String(s).replace(/[<>&"]/g, c => ({'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c]));
  }

  // empty state: if no entries exist at all, show prompt instead of 14 blank rows
  if (!entries.length) {
    container.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-tertiary);font-size:13px;">
      No weight entries yet — log your first weigh-in above
    </div>`;
    return;
  }

  container.innerHTML = days.map(date => {
    const isToday = date === today;
    const todayCls = isToday ? 'entry-row-today' : '';
    const dayEntries = byDate[date];
    const d = new Date(date + 'T00:00:00');
    const weekday = d.toLocaleDateString('en-US', { weekday: 'short' });
    const dayStr  = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const dateLabel = `${weekday}, ${dayStr}`;

    if (!dayEntries || !dayEntries.length) {
      return `
        <div class="re-row ${todayCls} missing-day-row" data-date="${date}">
          <div class="re-d">${dateLabel}${isToday ? '<span class="re-d-sub">Today</span>' : ''}</div>
          <div class="re-note">
            <button class="add-chip backfill-add-btn" data-date="${date}" data-is-today="${isToday}" type="button"
              aria-label="No entry for ${date} — click to add">＋ Add</button>
          </div>
          <div class="re-w"></div>
          <div class="re-delta"></div>
          <div class="re-actions"></div>
        </div>`;
    }

    // One or more entries on this day — show the first (most recent) entry
    return dayEntries.map((e, idx) => {
      const delta = prevWeight[e.id];
      let deltaCls = 'neu', deltaArrow = '—', deltaVal = '';
      if (delta != null) {
        const isFlat = Math.abs(delta) < 0.05;
        const isLoss = delta < 0;
        const isTowardTarget = losingIsGoal ? isLoss : !isLoss;
        if (!isFlat) {
          deltaCls = isTowardTarget ? 'dn' : 'up';
          deltaArrow = isLoss ? '↓' : '↑';
          deltaVal = ' ' + Math.abs(delta).toFixed(1);
        }
      }
      const noteText = e.notes ? _esc(e.notes) : '';

      return `
        <div class="re-row ${todayCls}" data-entry-id="${e.id}">
          <div class="re-d">${idx === 0 ? dateLabel : ''}${isToday && idx === 0 ? '<span class="re-d-sub">Today</span>' : ''}</div>
          <div class="re-note">${noteText}</div>
          <div class="re-w">${e.weight_kg.toFixed(1)}<span class="re-u"> kg</span></div>
          <div class="re-delta ${deltaCls}">${deltaArrow}${deltaVal}</div>
          <div class="re-actions">
            <button class="entry-menu-btn" data-entry-id="${e.id}" data-weight="${e.weight_kg}" data-date="${e.entry_date}" type="button"
              aria-label="Actions for entry ${e.id}" aria-expanded="false">⋯</button>
          </div>
        </div>`;
    }).join('');
  }).join('');

  // Wire ＋ Add chip buttons
  container.querySelectorAll('.backfill-add-btn').forEach(btn => {
    const date = btn.dataset.date;
    const isToday = btn.dataset.isToday === 'true';
    btn.addEventListener('click', () => _openMiniStepper(btn, date));
    if (isToday) {
      _openMiniStepper(btn, date);
    }
  });

  // Wire entry menu buttons
  container.querySelectorAll('.entry-menu-btn').forEach(btn => {
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
    const row = btn.closest('.re-row') || btn.closest('tr');
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
  // Works for both div-based re-row and legacy tr-based rows
  const isDiv = row.classList.contains('re-row');
  if (isDiv) {
    row.innerHTML = `
      <div style="grid-column:1/-1;">
        <form class="inline-edit-form" novalidate>
          <input type="number" step="0.1" min="20" max="300"
            class="backfill-input" value="${currentWeight.toFixed(1)}" aria-label="Weight in kg">
          <button type="submit" class="inline-save-btn">Save</button>
          <button type="button" class="inline-cancel-btn">Cancel</button>
          <span class="backfill-error" role="alert"></span>
        </form>
      </div>`;
  } else {
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
  }

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
  const noteCell = btn.closest('.re-note') || btn.closest('td');
  if (!noteCell) return;

  const prefill = _nearestWeight(_recentEntries, date) || 70.0;
  const initVal = (Math.round(prefill * 10) / 10).toFixed(1);

  noteCell.innerHTML = `
    <form class="inline-fill" novalidate>
      <button type="button" class="mini-step stepper-dec" aria-label="Decrease">&#x2212;</button>
      <input type="number" step="0.1" min="20" max="300"
        class="mini-val backfill-input" value="${initVal}" aria-label="Weight in kg">
      <button type="button" class="mini-step stepper-inc" aria-label="Increase">+</button>
      <button type="submit" class="mini-save backfill-save-btn">Log</button>
      <span class="mini-err backfill-error" role="alert"></span>
    </form>`;

  const form = noteCell.querySelector('form');
  const input = noteCell.querySelector('.mini-val');
  const errEl = noteCell.querySelector('.mini-err');

  input.focus();
  input.select();

  noteCell.querySelector('.stepper-dec').addEventListener('click', () => {
    const v = parseFloat(input.value) || 0;
    input.value = Math.max(20, v - 0.1).toFixed(1);
  });

  noteCell.querySelector('.stepper-inc').addEventListener('click', () => {
    const v = parseFloat(input.value) || 0;
    input.value = Math.min(300, v + 0.1).toFixed(1);
  });

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errEl.textContent = '';
    const raw = parseFloat(input.value);
    if (isNaN(raw) || raw < 20 || raw > 300) {
      errEl.textContent = 'Enter a valid weight (20–300 kg).';
      input.focus();
      return;
    }
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

// ── Edit-target slide-in panel ────────────────────────────────────────────

function _openEditPanel() {
  _populateEditPanel(_activeTarget);
  const scrim = document.getElementById('edit-scrim');
  const panel = document.getElementById('edit-panel');
  if (scrim) scrim.hidden = false;
  if (panel) panel.hidden = false;
  const goalWeight = document.getElementById('et-goal-weight');
  if (goalWeight) goalWeight.focus();
}

function _closeEditPanel() {
  const scrim = document.getElementById('edit-scrim');
  const panel = document.getElementById('edit-panel');
  if (scrim) scrim.hidden = true;
  if (panel) panel.hidden = true;
  const errEl = document.getElementById('et-panel-error');
  if (errEl) errEl.textContent = '';
}

function _populateEditPanel(target) {
  const startWEl   = document.getElementById('et-start-weight');
  const startHint  = document.getElementById('et-start-date-hint');
  const goalWInput = document.getElementById('et-goal-weight');
  const goalDInput = document.getElementById('et-goal-date');
  const errEl      = document.getElementById('et-panel-error');

  if (errEl) errEl.textContent = '';

  if (target) {
    if (startWEl)   startWEl.textContent = `${target.start_weight_kg.toFixed(1)} kg`;
    if (startHint)  {
      const d = new Date(target.start_date + 'T00:00:00');
      const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      startHint.textContent = `Captured when the target began · ${dateStr}`;
    }
    if (goalWInput) goalWInput.value = target.target_weight_kg.toFixed(1);
    if (goalDInput) goalDInput.value = target.target_date;
  } else {
    if (startWEl)   startWEl.textContent = '-- kg';
    if (startHint)  startHint.textContent = 'No active target';
    if (goalWInput) goalWInput.value = '';
    if (goalDInput) goalDInput.value = '';
  }

  _updatePreview();
}

function _updatePreview() {
  const goalWInput = document.getElementById('et-goal-weight');
  const goalDInput = document.getElementById('et-goal-date');
  const paceEl     = document.getElementById('et-preview-pace');
  const kgEl       = document.getElementById('et-preview-kg');
  const msEl       = document.getElementById('et-preview-ms');
  const daysHint   = document.getElementById('et-days-hint');

  const goalW = parseFloat(goalWInput ? goalWInput.value : '');
  const goalD = goalDInput ? goalDInput.value : '';
  const today = todayISO();

  // Days from today hint
  if (daysHint && goalD) {
    const d = new Date(goalD + 'T00:00:00');
    const t = new Date(today + 'T00:00:00');
    const days = Math.round((d - t) / 86400000);
    daysHint.textContent = days > 0 ? `${days} days from today` : (days === 0 ? 'today' : 'date is in the past');
  } else if (daysHint) {
    daysHint.textContent = '';
  }

  if (!goalD || isNaN(goalW)) {
    if (paceEl) paceEl.textContent = '--';
    if (kgEl)   kgEl.textContent   = '--';
    if (msEl)   msEl.textContent   = '--';
    return;
  }

  // Get the current weight basis (use _activeTarget plan + gap, or chart stats)
  const currentW = _activeTarget && _activeTarget.plan_today_kg != null && _activeTarget.gap_kg != null
    ? _activeTarget.plan_today_kg + _activeTarget.gap_kg
    : (_chartData && _chartData.stats ? _chartData.stats.current_weight_kg : null);

  if (currentW == null || isNaN(currentW)) {
    if (paceEl) paceEl.textContent = '--';
    if (kgEl)   kgEl.textContent   = '--';
    if (msEl)   msEl.textContent   = '--';
    return;
  }

  const kgToLose = currentW - goalW;
  const daysLeft = Math.round((new Date(goalD + 'T00:00:00') - new Date(today + 'T00:00:00')) / 86400000);

  if (kgEl) {
    kgEl.textContent = kgToLose > 0
      ? `${kgToLose.toFixed(1)} kg to lose`
      : `${Math.abs(kgToLose).toFixed(1)} kg to gain`;
  }

  if (paceEl) {
    if (daysLeft > 0) {
      const weeksLeft = daysLeft / 7;
      const pace = Math.abs(kgToLose) / weeksLeft;
      paceEl.textContent = `${pace.toFixed(2)} kg/wk`;
    } else {
      paceEl.textContent = '--';
    }
  }

  if (msEl) {
    // Milestone months: roughly every 3 months from today to goal date
    const months = Math.round(daysLeft / 30);
    if (months <= 1) {
      msEl.textContent = '< 1 month';
    } else {
      const labels = [];
      const d = new Date(today + 'T00:00:00');
      for (let m = 3; m < months; m += 3) {
        const ms = new Date(d);
        ms.setMonth(ms.getMonth() + m);
        labels.push(ms.toLocaleDateString('en-US', { month: 'short' }) + ' \'' + String(ms.getFullYear()).slice(2));
      }
      msEl.textContent = labels.length ? labels.join(' · ') : (months + ' mo');
    }
  }
}

async function _saveEditPanel() {
  const goalWInput = document.getElementById('et-goal-weight');
  const goalDInput = document.getElementById('et-goal-date');
  const saveBtn    = document.getElementById('et-save-btn');
  const errEl      = document.getElementById('et-panel-error');

  if (errEl) errEl.textContent = '';

  const goalW = parseFloat(goalWInput ? goalWInput.value : '');
  const goalD = goalDInput ? goalDInput.value : '';

  if (isNaN(goalW) || goalW < 20 || goalW > 300) {
    if (errEl) errEl.textContent = 'Goal weight must be between 20 and 300 kg.';
    return;
  }
  if (!goalD) {
    if (errEl) errEl.textContent = 'Please select a goal date.';
    return;
  }
  const today = todayISO();
  if (goalD <= today) {
    if (errEl) errEl.textContent = 'Goal date must be in the future.';
    return;
  }

  if (saveBtn) saveBtn.disabled = true;

  try {
    if (_activeTarget) {
      const res = await fetch(`/api/weight-targets/${encodeURIComponent(_activeTarget.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_weight_kg: goalW, target_date: goalD }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (errEl) errEl.textContent = data.detail || `Save failed (HTTP ${res.status})`;
        return;
      }
    } else {
      // No active target — POST a new one using current weight as start
      const startW = _chartData && _chartData.stats ? _chartData.stats.current_weight_kg : null;
      if (!startW) {
        if (errEl) errEl.textContent = 'Log a weight entry before creating a target.';
        return;
      }
      const res = await fetch('/api/weight-targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: _userId,
          start_weight_kg: startW,
          start_date: today,
          target_weight_kg: goalW,
          target_date: goalD,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (errEl) errEl.textContent = data.detail || `Create failed (HTTP ${res.status})`;
        return;
      }
    }
    UIStates.showToast('Target saved');
    _closeEditPanel();
    await _reload();
  } catch (e) {
    if (errEl) errEl.textContent = 'Network error: ' + e.message;
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function _endTargetFromPanel() {
  if (!_activeTarget) return;
  if (!confirm('End this target? This action cannot be undone.')) return;

  const endBtn = document.getElementById('et-end-btn');
  const errEl  = document.getElementById('et-panel-error');
  if (errEl) errEl.textContent = '';
  if (endBtn) endBtn.disabled = true;

  try {
    const res = await fetch(`/api/weight-targets/${encodeURIComponent(_activeTarget.id)}/end`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'abandoned' }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (errEl) errEl.textContent = data.detail || `End failed (HTTP ${res.status})`;
      return;
    }
    UIStates.showToast('Target ended');
    _closeEditPanel();
    await _reload();
  } catch (e) {
    if (errEl) errEl.textContent = 'Network error: ' + e.message;
  } finally {
    if (endBtn) endBtn.disabled = false;
  }
}

function _initEditPanel() {
  const pillBtn       = document.getElementById('edit-target-pill-btn');
  const headerBtn     = document.getElementById('edit-target-header-btn');
  const closeBtn      = document.getElementById('edit-panel-close');
  const scrim         = document.getElementById('edit-scrim');
  const saveBtn       = document.getElementById('et-save-btn');
  const endBtn        = document.getElementById('et-end-btn');
  const goalWInput    = document.getElementById('et-goal-weight');
  const goalDInput    = document.getElementById('et-goal-date');

  if (pillBtn)    pillBtn.addEventListener('click', _openEditPanel);
  if (headerBtn)  headerBtn.addEventListener('click', _openEditPanel);
  if (closeBtn)   closeBtn.addEventListener('click', _closeEditPanel);
  if (scrim)      scrim.addEventListener('click', _closeEditPanel);
  if (saveBtn)    saveBtn.addEventListener('click', _saveEditPanel);
  if (endBtn)     endBtn.addEventListener('click', _endTargetFromPanel);
  if (goalWInput) goalWInput.addEventListener('input', _updatePreview);
  if (goalDInput) goalDInput.addEventListener('input', _updatePreview);
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
    renderRecentEntries(_recentEntries, _activeTarget, _historySummary ? _historySummary.total_entries : null);
  } catch (e) {
    if (e.message !== 'auth') showPageError('Entries reload failed: ' + e.message);
  }
}

// ── Target History section ─────────────────────────────────────────────────

let _targetHistoryFilter = 'all';
let _targetHistoryRows = [];  // all completed target rows from history-summary

function renderTargetHistory(summary) {
  if (!summary) return;
  _historySummary = summary;
  _targetHistoryRows = summary.targets || [];

  const stats = summary.stats || {};
  const pastAttempts = summary.past_attempts || [];

  // Populate "Your weight journey" stats
  const setEl   = document.getElementById('journey-targets-set');
  const achEl   = document.getElementById('journey-achieved');
  const lostEl  = document.getElementById('journey-total-lost');
  const paceEl  = document.getElementById('journey-avg-pace');
  const achSub  = document.getElementById('journey-achieved-sub');
  const bannerEl = document.getElementById('journey-banner-text');

  if (setEl)  setEl.innerHTML = String(stats.targets_set || 0);
  if (achEl)  achEl.innerHTML = String(stats.targets_achieved || 0);
  if (achSub && stats.success_pct != null) {
    achSub.textContent = stats.success_pct.toFixed(0) + '% success';
    achSub.className = 'js4-s good';
  }
  if (lostEl) {
    lostEl.innerHTML = stats.total_kg_lost != null
      ? `${stats.total_kg_lost.toFixed(1)}<span class="js4-u">kg</span>`
      : `—<span class="js4-u">kg</span>`;
  }
  if (paceEl) {
    paceEl.innerHTML = stats.avg_pace_kg_per_week != null
      ? `${stats.avg_pace_kg_per_week.toFixed(2)}<span class="js4-u">/wk</span>`
      : `—<span class="js4-u">/wk</span>`;
  }

  // Journey banner: current day count vs past attempts
  if (bannerEl) {
    const dayCount = stats.current_day_count;
    if (pastAttempts.length > 0 && dayCount != null) {
      const best = pastAttempts.reduce((a, b) => (a.pace_kg_per_week || 0) > (b.pace_kg_per_week || 0) ? a : b);
      const paceStr = best.pace_kg_per_week != null ? best.pace_kg_per_week.toFixed(2) : '—';
      bannerEl.innerHTML = `Day <strong>${dayCount}</strong> of this target. ` +
        `Your best attempt was <strong>${best.day_count} days</strong> — you lose <strong>${paceStr} kg/wk</strong> when you finish.`;
    } else if (dayCount != null) {
      bannerEl.innerHTML = `Day <strong>${dayCount}</strong> of this target.`;
    } else {
      bannerEl.textContent = 'No active target.';
    }
  }

  _renderPastTargetsTable(_targetHistoryFilter);
}

function _renderPastTargetsTable(filter) {
  const tbody = document.getElementById('past-targets-tbody');
  if (!tbody) return;

  const filtered = filter === 'all'
    ? _targetHistoryRows
    : _targetHistoryRows.filter(t => t.status === filter);

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="th-empty">No ${filter === 'all' ? '' : filter + ' '}targets yet.</td></tr>`;
    return;
  }

  const MONTH_FMT = { month: 'short', year: '2-digit' };
  const DAY_FMT   = { month: 'short', day: 'numeric', year: '2-digit' };

  tbody.innerHTML = filtered.map(t => {
    const statusLabel = { achieved: 'Done', replaced: 'Repl.', abandoned: 'N/A' }[t.status] || t.status;
    const statusIcon  = { achieved: '✓', replaced: '↺', abandoned: '○' }[t.status] || '';
    const badgeCls    = { achieved: 'achieved', replaced: 'replaced', abandoned: 'abandoned' }[t.status] || '';

    const start = t.start_date ? new Date(t.start_date + 'T00:00:00') : null;
    const end   = t.end_date   ? new Date(t.end_date   + 'T00:00:00') : null;
    const startFmt = start ? start.toLocaleDateString('en-US', MONTH_FMT) : '—';
    const endFmt   = end   ? end.toLocaleDateString('en-US', MONTH_FMT)   : '—';
    const days     = t.days != null ? `${t.days}d` : '—';

    const rangeLabel = `${t.start_weight_kg.toFixed(0)} → ${t.target_weight_kg.toFixed(0)}`;
    const meta = `${startFmt}–${endFmt} · ${days}`;

    const result = t.result_weight_kg != null ? t.result_weight_kg.toFixed(1) : '—';

    let deltaHtml = '—';
    if (t.delta_kg != null) {
      const cls   = t.delta_kg < 0 ? 'th-delta-good' : 'th-delta-bad';
      const sign  = t.delta_kg < 0 ? '' : '+';
      deltaHtml = `<span class="${cls}">${sign}${t.delta_kg.toFixed(1)}</span>`;
    }

    return `<tr data-status="${t.status}">
      <td><span class="th-badge ${badgeCls}">${statusIcon} ${statusLabel}</span></td>
      <td><span class="th-nm">${rangeLabel}<span class="th-meta">${meta}</span></span></td>
      <td class="r">${result}</td>
      <td class="r">${deltaHtml}</td>
    </tr>`;
  }).join('');
}

function _initTargetHistoryFilters() {
  const pills = document.querySelectorAll('#target-filter-pills .th-fb');
  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      _targetHistoryFilter = pill.dataset.filter;
      _renderPastTargetsTable(_targetHistoryFilter);
    });
  });

  const exportBtn = document.getElementById('export-targets-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      const status = _targetHistoryFilter === 'all' ? '' : _targetHistoryFilter;
      let url = `/api/exports/weight-targets?user_id=${encodeURIComponent(_userId)}`;
      if (status) url += `&status=${encodeURIComponent(status)}`;
      window.location.href = url;
    });
  }
}

// ── Full reload (after mutations) ─────────────────────────────────────────

async function _reload() {
  try {
    const [chartData, entriesRes, targetRes, summaryRes, histSummary] = await Promise.all([
      fetchChartData(_currentRange),
      fetchRecentEntries(),
      fetchActiveTarget(),
      fetchAllEntriesSummary(),
      fetchTargetHistorySummary(),
    ]);

    _chartData = chartData;
    _recentEntries = entriesRes.entries || [];
    _activeTarget = targetRes.target || null;

    renderSubtitle(summaryRes.summary, chartData.stats);
    renderHeroCardA(chartData, _activeTarget);
    renderCoachStrip(chartData, _activeTarget);
    renderChart(chartData, _currentRange);
    renderProgress(_activeTarget);
    renderMilestones(_activeTarget, chartData.stats);
    renderRecentEntries(_recentEntries, _activeTarget, histSummary ? histSummary.total_entries : null);
    renderTargetHistory(histSummary);
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
  _initEditPanel();
  _initTargetHistoryFilters();

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
