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

function fmtDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function fmtDateShort(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function addDays(dateStr, n) {
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return isoDateStr(d);
}

function advanceMonths(dateStr, months) {
  const d = new Date(dateStr + 'T00:00:00');
  d.setMonth(d.getMonth() + months);
  return isoDateStr(d);
}

function monthsDiff(fromStr, toStr) {
  const a = new Date(fromStr + 'T00:00:00');
  const b = new Date(toStr + 'T00:00:00');
  return (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth());
}

function daysDiff(fromStr, toStr) {
  const a = new Date(fromStr + 'T00:00:00');
  const b = new Date(toStr + 'T00:00:00');
  return Math.round((b - a) / 86400000);
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function interpolateWeight(startKg, targetKg, totalDays, daysIn) {
  if (totalDays <= 0) return startKg;
  const frac = Math.min(Math.max(daysIn / totalDays, 0), 1);
  return startKg + (targetKg - startKg) * frac;
}

// ── State ──────────────────────────────────────────────────────────────────

let _userId = null;
let _activeTarget = null;
let _historyTargets = [];
let _activeFilter = 'all';

// ── API helpers ────────────────────────────────────────────────────────────

function showPageError(msg) {
  const el = document.getElementById('page-error');
  if (el) el.textContent = msg || '';
}

async function apiFetch(url, opts) {
  const res = await fetch(url, opts);
  if (res.status === 401 || res.status === 403) {
    window.location.href = '/login';
    return null;
  }
  return res;
}

// ── Init ───────────────────────────────────────────────────────────────────

async function init() {
  try {
    const meRes = await apiFetch('/api/auth/me');
    if (!meRes) return;
    if (!meRes.ok) { window.location.href = '/login'; return; }
    const me = await meRes.json();
    _userId = me.id;
  } catch (e) {
    showPageError('Failed to authenticate. Please refresh.');
    return;
  }

  await Promise.all([loadActiveTarget(), loadHistory()]);
  renderPage();
}

async function loadActiveTarget() {
  try {
    const res = await apiFetch(`/api/weight-targets/active?user_id=${encodeURIComponent(_userId)}`);
    if (!res || !res.ok) return;
    const data = await res.json();
    _activeTarget = data.target || null;
  } catch (e) {
    _activeTarget = null;
  }
}

async function loadHistory() {
  try {
    const res = await apiFetch(`/api/weight-targets/history?user_id=${encodeURIComponent(_userId)}`);
    if (!res || !res.ok) return;
    const data = await res.json();
    _historyTargets = data.targets || [];
  } catch (e) {
    _historyTargets = [];
  }
}

async function loadLatestWeightEntry() {
  try {
    const res = await apiFetch(`/api/weight-entries?user_id=${encodeURIComponent(_userId)}`);
    if (!res || !res.ok) return null;
    const data = await res.json();
    const entries = data.entries || data;
    if (Array.isArray(entries) && entries.length > 0) {
      return entries[entries.length - 1];
    }
    return null;
  } catch (e) {
    return null;
  }
}

// ── Render ─────────────────────────────────────────────────────────────────

function renderPage() {
  renderHeader();

  if (_activeTarget) {
    renderActiveCard(_activeTarget);
    renderMilestoneStrip(_activeTarget);
  } else {
    // empty state: no active target — show the "Set new target" form as graceful fallback
    renderNewTargetForm();
    hideMilestoneStrip();
  }

  renderStats();
  renderHistoryTable();
  bindFilterPills();
}

function renderHeader() {
  const btn = document.getElementById('set-target-btn');
  if (!btn) return;
  if (_activeTarget) {
    btn.disabled = true;
    btn.title = 'End or replace the current target first';
  } else {
    btn.disabled = false;
    btn.title = '';
    btn.addEventListener('click', () => {
      const form = document.getElementById('new-target-form-card');
      if (form) form.scrollIntoView({ behavior: 'smooth' });
      const firstInput = document.getElementById('form-start-weight');
      if (firstInput) firstInput.focus();
    });
  }
}

function renderActiveCard(t) {
  // null-safe guard: t is guaranteed non-null by renderPage's if (_activeTarget) check
  const activeCard = document.getElementById('active-card');
  const formCard = document.getElementById('new-target-form-card');
  if (activeCard) activeCard.hidden = false;
  if (formCard) formCard.hidden = true;

  // Title
  const title = document.getElementById('active-card-title');
  if (title) title.textContent = `${t.start_weight_kg} → ${t.target_weight_kg} kg`;

  // Weight range display
  const rangeDisplay = document.getElementById('weight-range-display');
  if (rangeDisplay) rangeDisplay.textContent = `${t.start_weight_kg} → ${t.target_weight_kg} kg`;

  // Dates row
  const datesRow = document.getElementById('weight-dates-row');
  if (datesRow) datesRow.textContent = `${fmtDate(t.start_date)} → ${fmtDate(t.target_date)}`;

  // "in N months" subtitle
  const months = monthsDiff(t.start_date, t.target_date);
  const monthsSub = document.getElementById('weight-months-sub');
  if (monthsSub) monthsSub.textContent = months > 0 ? `in ${months} month${months !== 1 ? 's' : ''}` : '';

  // 3-up pace stats
  const kgToGo = t.kg_to_go != null ? round2(t.kg_to_go) : null;
  const requiredPace = t.required_pace_kg_per_week;
  const currentPace = t.current_pace_kg_per_week;

  const remainingEl = document.getElementById('remaining-kg');
  if (remainingEl) remainingEl.textContent = kgToGo != null ? `${kgToGo} kg` : '--';

  const requiredEl = document.getElementById('required-pace');
  if (requiredEl) requiredEl.textContent = requiredPace != null ? `${round2(requiredPace)}` : '--';

  const currentPaceVal = document.getElementById('current-pace-value');
  const currentPaceArrow = document.getElementById('current-pace-arrow');
  if (currentPaceVal) currentPaceVal.textContent = currentPace != null ? `${round2(currentPace)}` : '--';
  if (currentPaceArrow && currentPace != null && requiredPace != null) {
    if (currentPace >= requiredPace) {
      currentPaceArrow.textContent = '↑';
      currentPaceArrow.className = 'pace-arrow green';
    } else {
      currentPaceArrow.textContent = '↓';
      currentPaceArrow.className = 'pace-arrow amber';
    }
  }

  // Progress mini-card
  const pct = t.progress_pct != null ? Math.round(t.progress_pct) : 0;
  const pctEl = document.getElementById('progress-pct-large');
  if (pctEl) pctEl.textContent = `${pct}%`;

  const totalKg = Math.abs(t.start_weight_kg - t.target_weight_kg);
  const kgLost = round2(totalKg - (kgToGo != null ? kgToGo : totalKg));
  const kgLostEl = document.getElementById('kg-lost-label');
  if (kgLostEl) kgLostEl.textContent = `${kgLost} of ${round2(totalKg)} kg lost`;

  const statusPill = document.getElementById('status-pill');
  if (statusPill && t.status_label) {
    const labelMap = {
      on_track: ['On track', 'on-track'],
      ahead:    ['Ahead',    'ahead'],
      behind:   ['Behind',   'behind'],
      at_risk:  ['At risk',  'at-risk'],
      complete: ['Complete', 'complete'],
    };
    const [text, cls] = labelMap[t.status_label] || [t.status_label, 'on-track'];
    statusPill.textContent = text;
    statusPill.className = `status-pill ${cls}`;
  }

  // Projected mini-card
  const projectedDate = document.getElementById('projected-date');
  const projPaceLabel = document.getElementById('projected-pace-label');
  const daysDeltaEl = document.getElementById('days-delta');

  if (t.projected_end_date) {
    if (projectedDate) projectedDate.textContent = fmtDate(t.projected_end_date);
    if (projPaceLabel && currentPace != null) {
      projPaceLabel.textContent = `At ${round2(currentPace)} kg/wk`;
    }
    if (daysDeltaEl) {
      const delta = daysDiff(t.target_date, t.projected_end_date);
      if (delta < 0) {
        daysDeltaEl.textContent = `${Math.abs(delta)}d ahead`;
        daysDeltaEl.className = 'days-delta ahead';
      } else if (delta > 0) {
        daysDeltaEl.textContent = `${delta}d behind`;
        daysDeltaEl.className = 'days-delta behind';
      } else {
        daysDeltaEl.textContent = 'On target';
        daysDeltaEl.className = 'days-delta';
      }
    }
  } else {
    if (projectedDate) projectedDate.textContent = '--';
    if (projPaceLabel) projPaceLabel.textContent = '';
    if (daysDeltaEl) daysDeltaEl.textContent = '';
  }

  // Bind edit / end buttons
  const editBtn = document.getElementById('edit-target-btn');
  if (editBtn) editBtn.onclick = () => openEditModal(t);

  const endBtn = document.getElementById('end-target-btn');
  if (endBtn) endBtn.onclick = () => openEndModal(t);
}

function renderNewTargetForm() {
  const activeCard = document.getElementById('active-card');
  const formCard = document.getElementById('new-target-form-card');
  if (activeCard) activeCard.hidden = true;
  if (formCard) formCard.hidden = false;

  // Pre-fill start date with today
  const startDateInput = document.getElementById('form-start-date');
  if (startDateInput) startDateInput.value = todayISO();

  // Pre-fill start weight from latest weight entry
  loadLatestWeightEntry().then(entry => {
    const startWeightInput = document.getElementById('form-start-weight');
    if (startWeightInput && entry && entry.weight_kg != null) {
      startWeightInput.value = entry.weight_kg;
    }
  });

  // Bind submit
  const form = document.getElementById('new-target-form');
  if (form && !form._bound) {
    form._bound = true;
    form.addEventListener('submit', handleNewTargetSubmit);
  }
}

async function handleNewTargetSubmit(e) {
  e.preventDefault();
  const errEl = document.getElementById('new-target-form-error');
  if (errEl) errEl.hidden = true;

  const startWeight = parseFloat(document.getElementById('form-start-weight').value);
  const startDate = document.getElementById('form-start-date').value;
  const targetWeight = parseFloat(document.getElementById('form-target-weight').value);
  const targetDate = document.getElementById('form-target-date').value;
  const notes = document.getElementById('form-notes').value.trim() || null;

  if (!startWeight || !startDate || !targetWeight || !targetDate) {
    if (errEl) { errEl.textContent = 'Please fill in all required fields.'; errEl.hidden = false; }
    return;
  }

  const submitBtn = e.target.querySelector('[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const res = await apiFetch('/api/weight-targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: _userId,
        start_weight_kg: startWeight,
        start_date: startDate,
        target_weight_kg: targetWeight,
        target_date: targetDate,
        notes,
      }),
    });
    if (!res) return;
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (errEl) {
        errEl.textContent = data.message || data.detail || 'Failed to create target.';
        errEl.hidden = false;
      }
      return;
    }
    // Reload page state
    await Promise.all([loadActiveTarget(), loadHistory()]);
    renderPage();
  } catch (err) {
    if (errEl) { errEl.textContent = 'Network error. Please try again.'; errEl.hidden = false; }
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

// ── Milestone Strip (Section C) ────────────────────────────────────────────

function renderMilestoneStrip(t) {
  const strip = document.getElementById('milestone-strip');
  if (!strip) return;
  strip.hidden = false;

  const rail = document.getElementById('milestone-rail');
  if (!rail) return;

  const startDate = t.start_date;
  const targetDate = t.target_date;
  const startKg = t.start_weight_kg;
  const goalKg = t.target_weight_kg;
  const today = todayISO();
  const totalDays = daysDiff(startDate, targetDate);

  const date3mo = advanceMonths(startDate, 3);
  const date6mo = advanceMonths(startDate, 6);

  const weight3mo = round2(interpolateWeight(startKg, goalKg, totalDays, daysDiff(startDate, date3mo)));
  const weight6mo = round2(interpolateWeight(startKg, goalKg, totalDays, daysDiff(startDate, date6mo)));
  const currentKg = t.start_weight_kg - (t.kg_to_go != null ? (totalDays !== 0 ? t.start_weight_kg - t.target_weight_kg - t.kg_to_go : 0) : 0);

  const points = [
    { label: 'Start',   marker: 'done',    date: startDate, kg: startKg },
    { label: 'Current', marker: 'current', date: today,     kg: null },
    { label: '3mo',     marker: '',        date: date3mo,   kg: weight3mo },
    { label: '6mo',     marker: '',        date: date6mo,   kg: weight6mo },
    { label: 'Goal',    marker: 'goal',    date: targetDate, kg: goalKg },
  ];

  const pct = t.progress_pct != null ? Math.min(Math.max(t.progress_pct, 0), 100) : 0;

  // Remove old point elements (preserve track)
  const track = document.getElementById('milestone-track');
  while (rail.firstChild) rail.removeChild(rail.firstChild);
  if (track) {
    rail.appendChild(track);
    const fill = document.getElementById('milestone-track-fill');
    if (fill) fill.style.width = `${pct}%`;
  }

  points.forEach(p => {
    const pt = document.createElement('div');
    pt.className = 'milestone-point';

    const marker = document.createElement('div');
    marker.className = 'milestone-marker' + (p.marker ? ` ${p.marker}` : '');
    pt.appendChild(marker);

    const label = document.createElement('div');
    label.className = 'milestone-label';
    label.textContent = p.label;
    pt.appendChild(label);

    const dateEl = document.createElement('div');
    dateEl.className = 'milestone-date';
    dateEl.textContent = fmtDateShort(p.date);
    pt.appendChild(dateEl);

    const kgEl = document.createElement('div');
    kgEl.className = 'milestone-weight';
    kgEl.textContent = p.kg != null ? `${p.kg} kg` : '--';
    pt.appendChild(kgEl);

    rail.appendChild(pt);
  });
}

function hideMilestoneStrip() {
  const strip = document.getElementById('milestone-strip');
  if (strip) strip.hidden = true;
}

// ── Stats Summary (Section D) ──────────────────────────────────────────────

function renderStats() {
  const history = _historyTargets;
  const totalSet = history.length;
  const achieved = history.filter(t => t.status === 'achieved');
  const achievedCount = achieved.length;
  const successPct = totalSet > 0 ? Math.round(achievedCount / totalSet * 100) : 0;

  const totalLost = achieved.reduce((sum, t) => {
    if (t.end_weight_kg != null) {
      return sum + Math.max(0, t.start_weight_kg - t.end_weight_kg);
    }
    return sum;
  }, 0);

  let avgPace = null;
  if (achievedCount > 0) {
    const totalPace = achieved.reduce((sum, t) => {
      if (t.duration_days && t.duration_days > 0) {
        const kg = t.start_weight_kg - (t.end_weight_kg || t.start_weight_kg);
        return sum + (kg / t.duration_days * 7);
      }
      return sum;
    }, 0);
    avgPace = round2(totalPace / achievedCount);
  }

  setText('stat-targets-set', totalSet > 0 ? String(totalSet) : '0');
  setText('stat-targets-achieved', achievedCount > 0 ? String(achievedCount) : '0');

  const successEl = document.getElementById('success-rate');
  if (successEl) successEl.textContent = totalSet > 0 ? `${successPct}% success rate` : '';

  setText('stat-total-lost', totalLost > 0 ? `${round2(totalLost)} kg` : '0 kg');
  setText('stat-avg-pace', avgPace != null ? `${avgPace}` : '--');
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── History Table (Section E) ──────────────────────────────────────────────

function renderHistoryTable() {
  const tbody = document.getElementById('history-tbody');
  const empty = document.getElementById('history-empty');
  if (!tbody) return;

  tbody.innerHTML = '';

  const visible = _activeFilter === 'all'
    ? _historyTargets
    : _historyTargets.filter(t => t.status === _activeFilter);

  if (visible.length === 0) {
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;

  visible.forEach(t => {
    const row = document.createElement('tr');
    row.dataset.status = t.status;

    // Status badge
    const badgeMap = {
      achieved: ['Done',      'badge badge-done'],
      replaced: ['Replaced',  'badge badge-replaced'],
      abandoned: ['Abandoned', 'badge badge-abandoned'],
    };
    const [badgeText, badgeCls] = badgeMap[t.status] || [t.status, 'badge'];

    // Name: "X → Y kg (date range)"
    const name = `${t.start_weight_kg} → ${t.target_weight_kg} kg`;
    const dateRange = `${fmtDateShort(t.start_date)} – ${t.ended_at ? fmtDateShort(t.ended_at.split('T')[0]) : ''}`;

    // Pace from duration
    let pace = '--';
    if (t.duration_days && t.duration_days > 0 && t.end_weight_kg != null) {
      const kgMoved = t.start_weight_kg - t.end_weight_kg;
      pace = `${round2(kgMoved / t.duration_days * 7)}`;
    }

    // Result weight
    const resultWeight = t.end_weight_kg != null ? `${t.end_weight_kg} kg` : '--';

    // Delta from start
    let deltaText = '--';
    let deltaCls = 'delta-neutral';
    if (t.end_weight_kg != null) {
      const delta = round2(t.start_weight_kg - t.end_weight_kg);
      if (delta > 0) {
        deltaText = `−${delta} kg`;
        deltaCls = (t.status === 'achieved' || t.status === 'replaced') ? 'delta-positive' : 'delta-amber';
      } else if (delta < 0) {
        deltaText = `+${Math.abs(delta)} kg`;
        deltaCls = 'delta-amber';
      } else {
        deltaText = '0 kg';
      }
    }

    const duration = t.duration_days != null ? `${t.duration_days}d` : '--';

    // Actions cell — edit only for this row's status (history rows are non-active, so minimal)
    const actionsHtml = `<button class="actions-btn" data-id="${t.id}" type="button">•••</button>`;

    row.innerHTML = `
      <td data-label="Status"><span class="${badgeCls}">${badgeText}</span></td>
      <td data-label="Name">
        <div style="font-weight:500">${name}</div>
        <div style="font-size:0.75rem;color:#9ca3af">${dateRange}</div>
      </td>
      <td data-label="Pace kg/wk">${pace}</td>
      <td data-label="Result weight">${resultWeight}</td>
      <td data-label="Delta"><span class="${deltaCls}">${deltaText}</span></td>
      <td data-label="Duration days">${duration}</td>
      <td data-label="Actions">${actionsHtml}</td>
    `;
    tbody.appendChild(row);
  });
}

function bindFilterPills() {
  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      _activeFilter = pill.dataset.filter || 'all';
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      renderHistoryTable();
    });
  });

  const exportTargetsBtn = document.getElementById('export-targets-btn');
  if (exportTargetsBtn) {
    exportTargetsBtn.addEventListener('click', () => {
      let url = `/api/exports/weight-targets?user_id=${encodeURIComponent(_userId)}`;
      if (_activeFilter !== 'all') {
        url += `&status=${encodeURIComponent(_activeFilter)}`;
      }
      window.location.href = url;
    });
  }
}

// ── Edit Modal ─────────────────────────────────────────────────────────────

function openEditModal(t) {
  const modal = document.getElementById('edit-modal');
  if (!modal) return;

  const targetWeightInput = document.getElementById('edit-target-weight');
  const targetDateInput = document.getElementById('edit-target-date');
  const notesInput = document.getElementById('edit-notes');
  const errEl = document.getElementById('edit-modal-error');

  if (targetWeightInput) targetWeightInput.value = t.target_weight_kg;
  if (targetDateInput) targetDateInput.value = t.target_date;
  if (notesInput) notesInput.value = t.notes || '';
  if (errEl) errEl.hidden = true;

  modal.hidden = false;

  const cancelBtn = document.getElementById('edit-cancel-btn');
  if (cancelBtn) cancelBtn.onclick = () => { modal.hidden = true; };

  const form = document.getElementById('edit-form');
  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (errEl) errEl.hidden = true;

      const targetWeight = parseFloat(targetWeightInput.value);
      const targetDate = targetDateInput.value;
      const notes = notesInput.value.trim() || null;

      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await apiFetch(`/api/weight-targets/${t.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_weight_kg: targetWeight, target_date: targetDate, notes }),
        });
        if (!res) return;
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          if (errEl) { errEl.textContent = data.detail || 'Failed to save changes.'; errEl.hidden = false; }
          return;
        }
        modal.hidden = true;
        await loadActiveTarget();
        renderActiveCard(_activeTarget);
        renderMilestoneStrip(_activeTarget);
      } catch (err) {
        if (errEl) { errEl.textContent = 'Network error. Please try again.'; errEl.hidden = false; }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    };
  }
}

// ── End Modal ──────────────────────────────────────────────────────────────

async function openEndModal(t) {
  const modal = document.getElementById('end-modal');
  if (!modal) return;

  const weightDisplay = document.getElementById('end-weight-display');
  const weightValue = document.getElementById('end-weight-value');
  const noWeightMsg = document.getElementById('end-no-weight-msg');
  const achievedBtn = document.getElementById('end-achieved-btn');
  const abandonedBtn = document.getElementById('end-abandoned-btn');
  const errEl = document.getElementById('end-modal-error');

  if (errEl) errEl.hidden = true;
  modal.hidden = false;

  // Reset to disabled state while checking
  if (achievedBtn) achievedBtn.disabled = true;
  if (abandonedBtn) abandonedBtn.disabled = true;
  if (weightDisplay) weightDisplay.hidden = true;
  if (noWeightMsg) noWeightMsg.hidden = true;

  // Check for recent weight entry (within 7 days)
  const cutoffDate = addDays(todayISO(), -7);
  let recentEntry = null;
  try {
    const res = await apiFetch(`/api/weight-entries?user_id=${encodeURIComponent(_userId)}`);
    if (res && res.ok) {
      const data = await res.json();
      const entries = data.entries || data;
      if (Array.isArray(entries)) {
        recentEntry = entries
          .filter(e => e.entry_date >= cutoffDate)
          .sort((a, b) => b.entry_date.localeCompare(a.entry_date))[0] || null;
      }
    }
  } catch (e) {
    recentEntry = null;
  }

  if (recentEntry) {
    if (weightDisplay) weightDisplay.hidden = false;
    if (weightValue) weightValue.textContent = `${recentEntry.weight_kg} kg`;
    if (noWeightMsg) noWeightMsg.hidden = true;
    if (achievedBtn) achievedBtn.disabled = false;
    if (abandonedBtn) abandonedBtn.disabled = false;
  } else {
    if (weightDisplay) weightDisplay.hidden = true;
    if (noWeightMsg) noWeightMsg.hidden = false;
    if (achievedBtn) achievedBtn.disabled = true;
    if (abandonedBtn) abandonedBtn.disabled = true;
  }

  const cancelBtn = document.getElementById('end-cancel-btn');
  if (cancelBtn) cancelBtn.onclick = () => { modal.hidden = true; };

  async function endTarget(status) {
    if (achievedBtn) achievedBtn.disabled = true;
    if (abandonedBtn) abandonedBtn.disabled = true;
    try {
      const res = await apiFetch(`/api/weight-targets/${t.id}/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (!res) return;
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (errEl) { errEl.textContent = data.detail || 'Failed to end target.'; errEl.hidden = false; }
        if (recentEntry && achievedBtn) achievedBtn.disabled = false;
        if (recentEntry && abandonedBtn) abandonedBtn.disabled = false;
        return;
      }
      modal.hidden = true;
      _activeTarget = null;
      await Promise.all([loadActiveTarget(), loadHistory()]);
      renderPage();
    } catch (err) {
      if (errEl) { errEl.textContent = 'Network error. Please try again.'; errEl.hidden = false; }
      if (recentEntry && achievedBtn) achievedBtn.disabled = false;
      if (recentEntry && abandonedBtn) abandonedBtn.disabled = false;
    }
  }

  if (achievedBtn) achievedBtn.onclick = () => endTarget('achieved');
  if (abandonedBtn) abandonedBtn.onclick = () => endTarget('abandoned');
}

// ── Bootstrap ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
