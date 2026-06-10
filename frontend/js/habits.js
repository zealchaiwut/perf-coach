// ── Constants ─────────────────────────────────────────────────────────────────

const ICONS = [
  'ti-run', 'ti-barbell', 'ti-droplet', 'ti-book',
  'ti-bed', 'ti-flame', 'ti-walk', 'ti-bike',
  'ti-meditation', 'ti-shoe', 'ti-clipboard',
];

const COLORS = [
  '#3b82f6', // blue
  '#8b5cf6', // purple
  '#10b981', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
];

const TRACKING_TYPE_LABELS = {
  daily_checkmark: 'Daily checkmark',
  weekly_count: 'Weekly count',
  weekly_minutes: 'Weekly minutes',
  weekly_quantity: 'Weekly quantity',
};

const DAY_LABELS_FULL = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAY_LABELS_SHORT = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

const WHEEL_CIRCUMFERENCE = 289.03; // 2 * π * r=46

const STARTER_HABITS = [
  {
    name: 'Zone 2 cardio',
    tracking_type: 'weekly_minutes',
    weekly_target: 210,
    unit: 'min',
    auto_fill_source: 'workout.zone2_minutes',
    icon: 'ti-run',
    color: '#3b82f6',
    description: 'Low-intensity aerobic training in Zone 2 heart rate',
  },
  {
    name: 'Running sessions',
    tracking_type: 'weekly_count',
    weekly_target: 3,
    unit: 'sessions',
    auto_fill_source: 'workout.run_count',
    icon: 'ti-shoe',
    color: '#3b82f6',
    description: 'Weekly run sessions',
  },
  {
    name: 'Strength sessions',
    tracking_type: 'weekly_count',
    weekly_target: 2,
    unit: 'sessions',
    auto_fill_source: 'workout.lift_count',
    icon: 'ti-barbell',
    color: '#8b5cf6',
    description: 'Weekly strength/lifting sessions',
  },
  {
    name: 'Daily metrics logged',
    tracking_type: 'daily_checkmark',
    weekly_target: 7,
    unit: 'days',
    auto_fill_source: null,
    icon: 'ti-clipboard',
    color: '#10b981',
    description: 'Log HRV, RHR, sleep, mood, and energy daily',
  },
];

// ── State ─────────────────────────────────────────────────────────────────────

let activeHabits = [];
let archivedHabits = [];
let editingHabitId = null;
let selectedIcon = ICONS[0];
let selectedColor = COLORS[0];

// ── Date helpers ──────────────────────────────────────────────────────────────

function isoDate(d) {
  return d.getFullYear() + '-' +
    String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

function bangkokToday() {
  const bk = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  const [y, m, d] = bk.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function bangkokTodayStr() {
  return isoDate(bangkokToday());
}

function isoWeekMonday(date) {
  const d = new Date(date);
  const dow = d.getDay();
  const diff = dow === 0 ? -6 : 1 - dow;
  d.setDate(d.getDate() + diff);
  return d;
}

function weekDates() {
  const today = bangkokToday();
  const monday = isoWeekMonday(today);
  const dates = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    dates.push(isoDate(d));
  }
  return dates;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function showError(msg) {
  const el = document.getElementById('api-error');
  if (el) el.textContent = msg;
}

function clearError() { showError(''); }

function iconLabel(code) {
  return code ? code.replace('ti-', '').replace(/-/g, ' ') : '?';
}

function habitIconHTML(icon, color, size) {
  const bg = color || '#9ca3af';
  const s = size || 26;
  if (icon) {
    return `<span class="habit-icon-chip" style="background:${bg};width:${s}px;height:${s}px;font-size:${Math.round(s*0.5)}px"><i class="ti ${icon}" aria-hidden="true"></i></span>`;
  }
  // Fallback ? when icon data is missing
  return `<span class="habit-icon-chip" style="background:${bg};width:${s}px;height:${s}px;font-size:${Math.round(s*0.45)}px;font-weight:700">?</span>`;
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Load & Render (main entry) ────────────────────────────────────────────────

async function loadAndRender() {
  clearError();

  const todayStr = bangkokTodayStr();
  const dates = weekDates();
  const weekFrom = dates[0];
  const weekTo = dates[6];

  try {
    const [activeRes, archivedRes, logsRes, statsRes] = await Promise.all([
      fetch('/api/habits'),
      fetch('/api/habits?include_archived=true'),
      fetch(`/api/habits/logs?from=${weekFrom}&to=${weekTo}`),
      fetch('/api/habits/stats?days=30'),
    ]);

    if (!activeRes.ok) throw new Error(`Server error ${activeRes.status}`);
    if (!archivedRes.ok) throw new Error(`Server error ${archivedRes.status}`);

    activeHabits = await activeRes.json();
    const allHabits = await archivedRes.json();
    archivedHabits = allHabits.filter(h => h.is_archived);
    const logs = logsRes.ok ? await logsRes.json() : [];
    const stats = statsRes.ok ? await statsRes.json() : [];

    // Fetch per-habit progress for weekly habits card
    const progressMap = {};
    if (activeHabits.length > 0) {
      const progressResults = await Promise.all(
        activeHabits.map(h =>
          fetch(`/api/habits/${encodeURIComponent(h.id)}/progress?week_start=${weekFrom}`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null)
        )
      );
      activeHabits.forEach((h, i) => {
        if (progressResults[i]) progressMap[h.id] = progressResults[i];
      });
    }

    // ── Subtitle ──
    const subtitleEl = document.getElementById('habits-subtitle');
    if (subtitleEl) {
      if (activeHabits.length === 0) {
        subtitleEl.textContent = 'No habits yet — add one to start tracking';
      } else {
        subtitleEl.textContent = `${activeHabits.length} habit${activeHabits.length !== 1 ? 's' : ''} · this week`;
      }
    }

    // ── Starter or dashboard ──
    if (activeHabits.length === 0 && archivedHabits.length === 0) {
      renderEmptyState();
      return;
    }

    document.getElementById('starter-section').style.display = 'none';
    document.getElementById('hero-row').style.display = '';
    document.getElementById('habits-day-grid-card').style.display = '';
    document.getElementById('weekly-habits-card').style.display = '';

    // ── Dashboard cards ──
    renderWheel(activeHabits, logs, dates, todayStr);
    renderStatsCard(activeHabits, stats);
    renderDailyGrid(activeHabits, logs, dates, todayStr);
    renderWeeklyHabits(activeHabits, progressMap);
    renderArchivedList();

  } catch (e) {
    showError('Unable to load habits: ' + e.message);
  }
}

// ── Empty state ───────────────────────────────────────────────────────────────

function renderEmptyState() {
  document.getElementById('starter-section').style.display = '';
  document.getElementById('hero-row').style.display = 'none';
  document.getElementById('habits-day-grid-card').style.display = 'none';
  document.getElementById('weekly-habits-card').style.display = 'none';

  renderStarterGrid();
  renderWheelEmpty();
}

function renderStarterGrid() {
  const grid = document.getElementById('starter-grid');
  if (!grid) return;
  grid.innerHTML = '';
  STARTER_HABITS.forEach(s => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'starter-btn';

    const iconEl = document.createElement('span');
    iconEl.className = 'starter-icon';
    iconEl.style.background = s.color;
    if (s.icon) {
      iconEl.innerHTML = `<i class="ti ${s.icon}" aria-hidden="true"></i>`;
    } else {
      iconEl.textContent = '?';
    }

    const labelEl = document.createElement('span');
    labelEl.textContent = s.name;

    btn.appendChild(iconEl);
    btn.appendChild(labelEl);
    btn.addEventListener('click', () => createStarterHabit(s));
    grid.appendChild(btn);
  });
}

async function createStarterHabit(starter) {
  try {
    const res = await fetch('/api/habits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(starter),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit added');
    await loadAndRender();
  } catch (e) {
    showError('Failed to add habit: ' + e.message);
  }
}

// ── Wheel ─────────────────────────────────────────────────────────────────────

function renderWheelEmpty() {
  const arc = document.getElementById('wheel-arc');
  const pctEl = document.getElementById('wheel-pct');
  const labelEl = document.getElementById('wheel-label');
  if (!arc) return;
  arc.classList.add('wheel-empty');
  arc.style.strokeDashoffset = '0';
  if (pctEl) {
    pctEl.style.fontSize = '13px';
    pctEl.style.color = 'var(--text-tertiary)';
    pctEl.textContent = 'Add habits to start tracking';
  }
  if (labelEl) labelEl.textContent = '';
}

function renderWheel(habits, logs, dates, todayStr) {
  const arc = document.getElementById('wheel-arc');
  const pctEl = document.getElementById('wheel-pct');
  const labelEl = document.getElementById('wheel-label');
  if (!arc) return;

  arc.classList.remove('wheel-empty');
  arc.style.stroke = '';

  const total = habits.length * 7;
  if (total === 0) { renderWheelEmpty(); return; }

  // Count distinct (habit_id, date) pairs this week up to today
  const seen = new Set();
  logs.forEach(l => {
    if (l.logged_date >= dates[0] && l.logged_date <= todayStr) {
      seen.add(l.habit_id + '|' + l.logged_date);
    }
  });
  const daysElapsed = dates.filter(d => d <= todayStr).length;
  const possibleSoFar = habits.length * Math.max(1, daysElapsed);
  const completed = seen.size;
  const pct = Math.round(Math.min(100, (completed / possibleSoFar) * 100));

  const offset = WHEEL_CIRCUMFERENCE * (1 - pct / 100);
  arc.style.strokeDashoffset = offset;

  if (pctEl) {
    pctEl.style.fontSize = '';
    pctEl.style.color = '';
    pctEl.textContent = pct + '%';
  }
  if (labelEl) labelEl.textContent = 'this week';
}

// ── Stats card ────────────────────────────────────────────────────────────────

function renderStatsCard(habits, stats) {
  const streakEl = document.getElementById('stat-streak');
  const rateEl = document.getElementById('stat-rate');
  const countEl = document.getElementById('stat-count');

  if (countEl) countEl.textContent = String(habits.length);

  let bestStreak = 0;
  let avgRate = 0;
  if (Array.isArray(stats) && stats.length > 0) {
    stats.forEach(s => {
      if (s.streak > bestStreak) bestStreak = s.streak;
    });
    const totalRate = stats.reduce((acc, s) => acc + (s.completion_rate || 0), 0);
    avgRate = Math.round((totalRate / stats.length) * 100);
  }

  if (streakEl) streakEl.textContent = bestStreak + (bestStreak === 1 ? ' day' : ' days');
  if (rateEl) rateEl.textContent = avgRate + '%';
}

// ── Daily grid ────────────────────────────────────────────────────────────────

function renderDailyGrid(habits, logs, dates, todayStr) {
  const container = document.getElementById('day-grid-content');
  const weekEl = document.getElementById('day-grid-week');
  if (!container) return;

  if (weekEl) {
    const from = dates[0].slice(5).replace('-', '/');
    const to = dates[6].slice(5).replace('-', '/');
    weekEl.textContent = from + ' – ' + to;
  }

  if (habits.length === 0) {
    container.innerHTML = '<div class="day-grid-empty">No habits yet.</div>';
    return;
  }

  // Build log set: habit_id + date → log_id
  const logSet = {};
  logs.forEach(l => {
    if (dates.includes(l.logged_date)) {
      logSet[l.habit_id + '|' + l.logged_date] = l.id;
    }
  });

  let html = '<table class="day-grid-table" role="grid">';
  html += '<thead><tr>';
  html += '<th class="habit-name-hdr">Habit</th>';
  for (let i = 0; i < 7; i++) {
    html += `<th><span class="day-hdr-full">${DAY_LABELS_FULL[i]}</span><span class="day-hdr-short">${DAY_LABELS_SHORT[i]}</span></th>`;
  }
  html += '</tr></thead><tbody>';

  habits.forEach(habit => {
    const iconHTML = habitIconHTML(habit.icon, habit.color, 24);
    const trackingLabel = TRACKING_TYPE_LABELS[habit.tracking_type] || habit.tracking_type;
    const autofillText = habit.auto_fill_source ? 'auto' : '';
    const autofillBadge = autofillText
      ? `<span class="habit-autofill-badge" title="Auto-filled from workouts. Visit <a href='/log'>workouts</a>">${autofillText}</span>`
      : '';

    html += `<tr data-habit-id="${esc(String(habit.id))}">`;
    html += `<td class="habit-name-cell">
      <div class="habit-name-inner">
        ${iconHTML}
        <div>
          <div class="habit-name-text">${esc(habit.name)}</div>
          <div class="habit-meta-line">
            <span class="habit-type-chip">${esc(trackingLabel)}</span>
            ${autofillBadge}
          </div>
        </div>
      </div>
    </td>`;

    for (let i = 0; i < 7; i++) {
      const dateStr = dates[i];
      const isFuture = dateStr > todayStr;
      const isToday = dateStr === todayStr;
      const logKey = habit.id + '|' + dateStr;
      const logId = logSet[logKey];
      const isDone = !!logId;

      let cls = 'day-cell-btn';
      if (isDone) cls += ' done';
      if (isToday) cls += ' today';
      if (isFuture) cls += ' future';

      const ariaLabel = `${habit.name} ${DAY_LABELS_FULL[i]} ${isDone ? 'done' : 'not done'}`;
      html += `<td><button
        class="${cls}"
        type="button"
        aria-label="${esc(ariaLabel)}"
        data-habit-id="${esc(String(habit.id))}"
        data-date="${dateStr}"
        data-log-id="${isDone ? esc(logId) : ''}"
      >${isDone ? '<i class="ti ti-check" aria-hidden="true"></i>' : ''}</button></td>`;
    }

    html += '</tr>';
  });

  html += '</tbody></table>';
  container.innerHTML = html;

  // Attach click listeners for daily grid toggles
  container.querySelectorAll('.day-cell-btn:not(.future)').forEach(btn => {
    btn.addEventListener('click', () => handleDayCellToggle(btn));
  });
}

async function handleDayCellToggle(btn) {
  const habitId = btn.dataset.habitId;
  const dateStr = btn.dataset.date;
  const logId = btn.dataset.logId;
  const isDone = btn.classList.contains('done');

  btn.disabled = true;

  try {
    if (isDone) {
      // Unlog
      if (!logId) { btn.disabled = false; return; }
      const res = await fetch(`/api/habits/logs/${encodeURIComponent(logId)}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
      btn.classList.remove('done');
      btn.innerHTML = '';
      btn.dataset.logId = '';
    } else {
      // Log
      const res = await fetch('/api/habits/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ habit_id: habitId, logged_date: dateStr }),
      });
      if (!res.ok && res.status !== 409) throw new Error(`Server error ${res.status}`);
      if (res.ok) {
        const data = await res.json();
        btn.classList.add('done');
        btn.innerHTML = '<i class="ti ti-check" aria-hidden="true"></i>';
        btn.dataset.logId = data.id || '';
      }
    }

    // Re-render wheel with updated logs (lightweight)
    const dates = weekDates();
    const logsRes = await fetch(`/api/habits/logs?from=${dates[0]}&to=${dates[6]}`);
    if (logsRes.ok) {
      const logs = await logsRes.json();
      renderWheel(activeHabits, logs, dates, bangkokTodayStr());
    }
  } catch (e) {
    showError('Failed to update log: ' + e.message);
  }

  btn.disabled = false;
}

// ── Weekly habits card ────────────────────────────────────────────────────────

function renderWeeklyHabits(habits, progressMap) {
  const container = document.getElementById('weekly-habits-content');
  if (!container) return;

  if (habits.length === 0) {
    container.innerHTML = '<div class="weekly-habits-empty">No habits yet.</div>';
    return;
  }

  container.innerHTML = '';

  habits.forEach(habit => {
    const prog = progressMap[habit.id] || {};
    const current = prog.current_value != null ? prog.current_value : 0;
    const target = prog.target;
    const pct = Math.min(100, prog.percentage != null ? prog.percentage : 0);
    const isComplete = !!prog.is_complete;
    const unit = habit.unit ? ' ' + habit.unit : '';

    const valStr = target != null
      ? (Number.isInteger(current) ? current : current.toFixed(1)) + ' / ' + target + unit
      : '—';

    const trackingLabel = TRACKING_TYPE_LABELS[habit.tracking_type] || habit.tracking_type;

    const row = document.createElement('div');
    row.className = 'week-habit-row';
    row.id = `habit-week-row-${habit.id}`;

    const iconHTML = habitIconHTML(habit.icon, habit.color, 30);

    row.innerHTML = `
      ${iconHTML}
      <div class="week-habit-info">
        <div class="week-habit-name-row">
          <span class="week-habit-name">${esc(habit.name)}</span>
          <span class="week-habit-val">${esc(valStr)}</span>
        </div>
        <div class="week-habit-bar-outer">
          <div class="week-habit-bar-inner${isComplete ? ' complete' : ''}" style="width:${pct.toFixed(1)}%"></div>
        </div>
      </div>
      <span class="week-habit-chip ${isComplete ? 'complete' : 'incomplete'}">${isComplete ? '✓ Done' : Math.round(pct) + '%'}</span>
      <div class="week-habit-actions">
        <button type="button" class="week-actions-toggle" aria-label="Habit actions for ${esc(habit.name)}">⋯</button>
        <div class="week-actions-menu" id="week-menu-${esc(String(habit.id))}"></div>
      </div>
    `;

    // Build action menu
    const menu = row.querySelector('.week-actions-menu');
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => { closeAllMenus(); openEditModal(habit); });
    menu.appendChild(editBtn);

    const archiveBtn = document.createElement('button');
    archiveBtn.type = 'button';
    archiveBtn.textContent = 'Archive';
    archiveBtn.addEventListener('click', () => { closeAllMenus(); archiveHabit(habit.id); });
    menu.appendChild(archiveBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'danger';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', () => {
      closeAllMenus();
      if (confirm(`Delete "${habit.name}"? This cannot be undone.`)) {
        deleteHabit(habit.id);
      }
    });
    menu.appendChild(deleteBtn);

    const toggle = row.querySelector('.week-actions-toggle');
    toggle.addEventListener('click', e => {
      e.stopPropagation();
      closeAllMenus();
      menu.classList.toggle('open');
    });

    container.appendChild(row);
  });
}

function closeAllMenus() {
  document.querySelectorAll('.week-actions-menu.open, .actions-menu.open').forEach(m => m.classList.remove('open'));
}

document.addEventListener('click', closeAllMenus);

// ── Archived list ─────────────────────────────────────────────────────────────

function renderArchivedList() {
  const section = document.getElementById('archived-section');
  const list = document.getElementById('archived-list');
  const countEl = document.getElementById('archived-count');

  if (!section || !list) return;

  if (archivedHabits.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  if (countEl) countEl.textContent = ` (${archivedHabits.length})`;
  list.innerHTML = '';

  archivedHabits.forEach(habit => {
    const li = document.createElement('li');
    li.className = 'archived-habit-row';

    const iconHTML = habitIconHTML(habit.icon, habit.color, 22);
    const nameEl = document.createElement('span');
    nameEl.className = 'archived-habit-name';
    nameEl.innerHTML = iconHTML + ' ' + esc(habit.name);

    const unarchiveBtn = document.createElement('button');
    unarchiveBtn.type = 'button';
    unarchiveBtn.className = 'archived-btn';
    unarchiveBtn.textContent = 'Restore';
    unarchiveBtn.addEventListener('click', () => unarchiveHabit(habit.id));

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'archived-delete-btn';
    deleteBtn.title = 'Delete permanently';
    deleteBtn.textContent = '×';
    deleteBtn.addEventListener('click', () => {
      if (confirm(`Delete "${habit.name}" permanently?`)) deleteHabit(habit.id);
    });

    li.appendChild(nameEl);
    li.appendChild(unarchiveBtn);
    li.appendChild(deleteBtn);
    list.appendChild(li);
  });
}

// ── Archive / Unarchive / Delete ──────────────────────────────────────────────

async function archiveHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit archived');
    await loadAndRender();
  } catch (e) {
    showError('Failed to archive habit: ' + e.message);
  }
}

async function unarchiveHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_archived: false }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit restored');
    await loadAndRender();
  } catch (e) {
    showError('Failed to restore habit: ' + e.message);
  }
}

async function deleteHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}?hard=true`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit deleted');
    await loadAndRender();
  } catch (e) {
    showError('Failed to delete habit: ' + e.message);
  }
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function buildIconPicker() {
  const container = document.getElementById('icon-picker');
  container.innerHTML = '';
  ICONS.forEach(icon => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-option' + (icon === selectedIcon ? ' selected' : '');
    btn.innerHTML = `<i class="ti ${icon}" aria-hidden="true"></i>`;
    btn.title = iconLabel(icon);
    btn.dataset.icon = icon;
    btn.addEventListener('click', () => {
      selectedIcon = icon;
      container.querySelectorAll('.icon-option').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
    container.appendChild(btn);
  });
}

function buildColorPicker() {
  const container = document.getElementById('color-picker');
  container.innerHTML = '';
  COLORS.forEach(color => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'color-swatch' + (color === selectedColor ? ' selected' : '');
    btn.style.background = color;
    btn.title = color;
    btn.dataset.color = color;
    btn.setAttribute('aria-label', `Color ${color}`);
    btn.addEventListener('click', () => {
      selectedColor = color;
      container.querySelectorAll('.color-swatch').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
    container.appendChild(btn);
  });
}

function openNewModal() {
  editingHabitId = null;
  selectedIcon = ICONS[0];
  selectedColor = COLORS[0];

  document.getElementById('modal-title').textContent = 'New habit';
  document.getElementById('modal-submit').textContent = 'Add habit';
  document.getElementById('modal-name').value = '';
  document.getElementById('modal-description').value = '';
  document.getElementById('modal-tracking-type').value = 'daily_checkmark';
  document.getElementById('modal-weekly-target').value = '';
  document.getElementById('modal-unit').value = '';
  document.getElementById('modal-auto-fill').value = '';
  document.getElementById('modal-error').textContent = '';

  buildIconPicker();
  buildColorPicker();

  document.getElementById('habit-modal').classList.add('open');
  document.getElementById('modal-name').focus();
}

function openEditModal(habit) {
  editingHabitId = habit.id;
  selectedIcon = habit.icon || ICONS[0];
  selectedColor = habit.color || COLORS[0];

  document.getElementById('modal-title').textContent = 'Edit habit';
  document.getElementById('modal-submit').textContent = 'Save changes';
  document.getElementById('modal-name').value = habit.name || '';
  document.getElementById('modal-description').value = habit.description || '';
  document.getElementById('modal-tracking-type').value = habit.tracking_type || 'daily_checkmark';
  document.getElementById('modal-weekly-target').value = habit.weekly_target != null ? habit.weekly_target : '';
  document.getElementById('modal-unit').value = habit.unit || '';
  document.getElementById('modal-auto-fill').value = habit.auto_fill_source || '';
  document.getElementById('modal-error').textContent = '';

  buildIconPicker();
  buildColorPicker();

  document.getElementById('habit-modal').classList.add('open');
  document.getElementById('modal-name').focus();
}

function closeModal() {
  document.getElementById('habit-modal').classList.remove('open');
  editingHabitId = null;
}

// ── Form submit ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-habit-btn').addEventListener('click', openNewModal);
  document.getElementById('modal-cancel').addEventListener('click', closeModal);

  document.getElementById('habit-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('habit-modal')) closeModal();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  const archivedToggle = document.getElementById('archived-toggle');
  if (archivedToggle) {
    archivedToggle.addEventListener('click', () => {
      const list = document.getElementById('archived-list');
      const isOpen = archivedToggle.classList.contains('open');
      archivedToggle.classList.toggle('open', !isOpen);
      if (list) list.style.display = isOpen ? 'none' : '';
    });
  }

  document.getElementById('modal-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errorEl = document.getElementById('modal-error');
    errorEl.textContent = '';

    const name = document.getElementById('modal-name').value.trim();
    if (!name) {
      errorEl.textContent = 'Name is required.';
      document.getElementById('modal-name').focus();
      return;
    }

    const payload = {
      name,
      description: document.getElementById('modal-description').value.trim() || null,
      tracking_type: document.getElementById('modal-tracking-type').value,
      weekly_target: document.getElementById('modal-weekly-target').value
        ? parseFloat(document.getElementById('modal-weekly-target').value)
        : null,
      unit: document.getElementById('modal-unit').value.trim() || null,
      auto_fill_source: document.getElementById('modal-auto-fill').value || null,
      icon: selectedIcon || null,
      color: selectedColor || null,
    };

    try {
      let res;
      if (editingHabitId) {
        res = await fetch(`/api/habits/${encodeURIComponent(editingHabitId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/habits', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errorEl.textContent = body.detail || `Server error ${res.status}`;
        return;
      }
      closeModal();
      if (typeof UIStates !== 'undefined') UIStates.showToast(editingHabitId ? 'Habit updated' : 'Habit added');
      await loadAndRender();
    } catch (err) {
      errorEl.textContent = 'Failed to save: ' + err.message;
    }
  });
});

// ── Boot ──────────────────────────────────────────────────────────────────────

window.addEventListener('userReady', () => {
  loadAndRender();
});

window.addEventListener('userChanged', () => {
  loadAndRender();
});
