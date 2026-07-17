// ── Constants ─────────────────────────────────────────────────────────────────

const ICONS = [
  // Fitness
  'ti-run', 'ti-barbell', 'ti-walk', 'ti-bike', 'ti-shoe',
  'ti-swimming', 'ti-yoga', 'ti-dumbbell', 'ti-stretching',
  // Energy & Vitality
  'ti-flame', 'ti-sun', 'ti-moon', 'ti-heart',
  // Mindfulness
  'ti-meditation', 'ti-brain', 'ti-mood-smile',
  // Nutrition & Hydration
  'ti-droplet', 'ti-apple', 'ti-coffee', 'ti-salad',
  // Rest & Recovery
  'ti-bed', 'ti-bath',
  // Learning
  'ti-book', 'ti-pencil', 'ti-school', 'ti-notebook',
  // Productivity
  'ti-clipboard', 'ti-clock', 'ti-calendar', 'ti-target', 'ti-check',
  // Social
  'ti-users', 'ti-message',
  // Health
  'ti-stethoscope',
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

// Week-view state
let weekData = null;        // last response from GET /api/habits/week
let currentWeekStart = null; // ISO date string; null = use server default (current week)

// Debounce handle for hero + grid-totals refresh after cell mutations
let _gridRefreshTimer = null;

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

function formatWeekRange(weekStart, weekEnd) {
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const [, sm, sd] = weekStart.split('-').map(Number);
  const [, em, ed] = weekEnd.split('-').map(Number);
  if (sm === em) return `${MONTHS[sm-1]} ${sd}–${ed}`;
  return `${MONTHS[sm-1]} ${sd}–${MONTHS[em-1]} ${ed}`;
}

// ── Polar-to-cartesian helpers — shared wheel math lives in wheel-helpers.js ──

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

// ── Today quick-log surface ───────────────────────────────────────────────────
// Fetches /api/habits/summary and renders a per-habit row with type-specific
// quick-log controls. Controls POST to /api/habits/{id}/log (upsert semantics)
// and refresh only the specific row's streak from /api/habits/summary.

async function _logHabitToday(habitId, value) {
  const today = bangkokTodayStr();
  const body = { log_date: today };
  if (value !== undefined && value !== null) body.value = value;

  const res = await fetch(`/api/habits/${habitId}/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || errData.message || `Error ${res.status}`);
  }

  await _refreshHabitStreak(habitId);
}

// ── Miss detection helper ─────────────────────────────────────────────────────
// For daily (7×/week) habits: true when there were missed days earlier this week
// before today. Uses Bangkok time so the weekday is accurate.
function _hasMissThisWeek(habit, weekDone) {
  if (habit.tracking_type !== 'daily_checkmark') return false;
  const wt = habit.weekly_target != null ? parseFloat(habit.weekly_target) : 7;
  if (wt < 7) return false;
  const bkkDate = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  const dow = new Date(bkkDate + 'T00:00:00').getDay(); // 0=Sun..6=Sat
  const daysBeforeToday = dow === 0 ? 6 : dow - 1;     // Mon=0...Sat=5, Sun=6
  return daysBeforeToday > 0 && weekDone < daysBeforeToday;
}

// ── Milestone moment display ──────────────────────────────────────────────────
// Shows a full-width coaching banner that auto-dismisses after 6 s.
function _showMilestoneMoment(coaching) {
  const existing = document.getElementById('habit-milestone-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'habit-milestone-banner';
  banner.className = 'habit-milestone-banner';
  banner.setAttribute('role', 'status');
  banner.setAttribute('aria-live', 'polite');

  const msgEl = document.createElement('p');
  msgEl.className = 'habit-milestone-msg';
  msgEl.textContent = coaching.message;
  banner.appendChild(msgEl);

  if (coaching.showIdentity && window.HabitVoice) {
    const idEl = document.createElement('p');
    idEl.className = 'habit-milestone-identity';
    idEl.textContent = HabitVoice.identityLine(coaching._habitName || '');
    banner.appendChild(idEl);
  }

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'habit-milestone-close';
  closeBtn.setAttribute('aria-label', 'Dismiss');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => banner.remove());
  banner.appendChild(closeBtn);

  const card = document.getElementById('today-quick-log-card');
  if (card) {
    card.insertAdjacentElement('afterend', banner);
  } else {
    document.body.appendChild(banner);
  }

  setTimeout(() => { if (banner.parentNode) banner.remove(); }, 6000);
}

// ── Streak feedback after log ─────────────────────────────────────────────────
// Fetches refreshed summary and renders coaching copy on the habit row.
async function _refreshHabitStreak(habitId) {
  const res = await fetch('/api/habits/summary');
  if (!res.ok) return;
  const data = await res.json();
  const habit = (data.habits || []).find(h => h.id === habitId);
  if (!habit) return;

  const weekDone = habit.week_done != null ? habit.week_done : 0;
  const weekTarget = habit.weekly_target != null ? Math.floor(parseFloat(habit.weekly_target)) : 7;
  const totalLogs = habit.total_logs || 0;
  const currentStreak = habit.current_streak || 0;
  const isMiss = _hasMissThisWeek(habit, weekDone);

  // Route all copy through the shared voice module (AC7)
  const V = window.HabitVoice;
  if (!V) return;
  const coaching = V.compose(habit, weekDone, weekTarget, totalLogs, isMiss, currentStreak);
  coaching._habitName = habit.name;

  // Update row meta with coaching copy
  const row = document.querySelector(`[data-habit-id="${habitId}"]`);
  if (row) {
    const metaEl = row.querySelector('.today-habit-meta');
    if (metaEl) {
      const oldBadge = metaEl.querySelector('.streak-badge, .coaching-copy');
      const coachEl = document.createElement('span');
      coachEl.className = `coaching-copy coaching-copy--${coaching.framing}`;
      coachEl.textContent = coaching.message;
      if (oldBadge) {
        oldBadge.replaceWith(coachEl);
      } else {
        metaEl.appendChild(coachEl);
      }
    }
  }

  // Milestone moment surface (AC4, AC5)
  if (coaching.framing === 'milestone') {
    _showMilestoneMoment(coaching);
  }
}

function _showRowError(row, msg) {
  let errEl = row.querySelector('.today-row-error');
  if (!errEl) {
    errEl = document.createElement('p');
    errEl.className = 'today-row-error';
    errEl.setAttribute('role', 'alert');
    row.appendChild(errEl);
  }
  errEl.textContent = msg;
  setTimeout(() => { if (errEl.parentNode) errEl.textContent = ''; }, 4000);
}

function renderTodayCard(habits) {
  const card = document.getElementById('today-quick-log-card');
  const list = document.getElementById('today-habits-list');
  const emptyEl = document.getElementById('today-empty-state');
  const dateLabel = document.getElementById('today-date-label');
  if (!card || !list) return;

  // Show date label
  if (dateLabel) {
    const today = bangkokToday();
    const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    dateLabel.textContent = `${DAYS[today.getDay()]}, ${MONTHS[today.getMonth()]} ${today.getDate()}`;
  }

  card.style.display = '';

  if (!habits || habits.length === 0) {
    list.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }

  if (emptyEl) emptyEl.style.display = 'none';

  list.innerHTML = '';
  habits.forEach(habit => {
    const row = document.createElement('div');
    row.className = 'today-habit-row';
    row.dataset.habitId = habit.id;
    row.dataset.trackingType = habit.tracking_type;

    const iconHTML = habitIconHTML(habit.icon, habit.color, 28);

    // Coaching copy for initial render — route through voice module (AC7)
    const V = window.HabitVoice;
    const weekDone = habit.week_done != null ? habit.week_done : 0;
    const weekTarget = habit.weekly_target != null ? Math.floor(parseFloat(habit.weekly_target)) : 7;
    const totalLogs = habit.total_logs || 0;
    const currentStreak = habit.current_streak || 0;
    const isMiss = _hasMissThisWeek(habit, weekDone);

    let streakBadgeHTML = '';
    if (V) {
      const coaching = V.compose(habit, weekDone, weekTarget, totalLogs, isMiss, currentStreak);
      streakBadgeHTML = `<span class="coaching-copy coaching-copy--${esc(coaching.framing)}">${esc(coaching.message)}</span>`;
    } else {
      // Fallback: raw streak badge when voice module not loaded
      const streak = currentStreak;
      streakBadgeHTML = streak >= 3
        ? `<span class="streak-badge">🔥 ${streak} day${streak !== 1 ? 's' : ''}</span>`
        : streak > 0
          ? `<span class="streak-badge">${streak} day${streak !== 1 ? 's' : ''}</span>`
          : '';
    }

    // Target label
    const targetStr = habit.weekly_target != null
      ? `target: ${habit.weekly_target}${habit.unit ? ' ' + habit.unit : ''}/wk`
      : '';

    // Type-specific control HTML
    let controlHTML = '';
    if (habit.tracking_type === 'daily_checkmark') {
      controlHTML = `<button type="button" class="today-toggle-btn" aria-label="Mark ${esc(habit.name)} done"><i class="ti ti-check" aria-hidden="true"></i></button>`;
    } else if (habit.tracking_type === 'weekly_count') {
      controlHTML = `<div class="today-stepper" aria-label="${esc(habit.name)} count">
        <button type="button" class="stepper-dec" aria-label="Decrease">−</button>
        <span class="stepper-val">0</span>
        <button type="button" class="stepper-inc" aria-label="Increase">+</button>
      </div>`;
    } else {
      // weekly_minutes, weekly_quantity — duration/quantity entry
      const unitHint = habit.unit ? ` placeholder="${esc(habit.unit)}"` : '';
      controlHTML = `<input type="number" class="today-duration-input" min="0" step="1"${unitHint} aria-label="${esc(habit.name)} value">`;
    }

    row.innerHTML = `
      <div style="flex-shrink:0">${iconHTML}</div>
      <div class="today-habit-info">
        <div class="today-habit-name">${esc(habit.name)}</div>
        <div class="today-habit-meta">
          ${targetStr ? `<span class="today-target">${esc(targetStr)}</span>` : ''}
          ${streakBadgeHTML}
        </div>
      </div>
      <div class="today-habit-control">${controlHTML}</div>`;

    list.appendChild(row);
  });

  // Attach interactive handlers — POST to upsert-log endpoint then refresh streak
  list.querySelectorAll('.today-toggle-btn').forEach(btn => {
    const row = btn.closest('.today-habit-row');
    const habitId = row && row.dataset.habitId;
    btn.addEventListener('click', async () => {
      btn.classList.toggle('toggled');
      btn.disabled = true;
      try {
        await _logHabitToday(habitId, 1);
        if (btn.classList.contains('toggled')) {
          _pendingCheckCelebrate = true;
          scheduleHeroRefresh();
        }
      } catch (e) {
        btn.classList.toggle('toggled'); // revert
        if (row) _showRowError(row, e.message || 'Failed to log habit');
      } finally {
        btn.disabled = false;
      }
    });
  });

  list.querySelectorAll('.today-stepper').forEach(stepper => {
    const row = stepper.closest('.today-habit-row');
    const habitId = row && row.dataset.habitId;
    const dec = stepper.querySelector('.stepper-dec');
    const inc = stepper.querySelector('.stepper-inc');
    const val = stepper.querySelector('.stepper-val');
    let count = 0;

    if (dec) dec.addEventListener('click', async () => {
      if (count <= 0) return;
      count--;
      val.textContent = count;
      dec.disabled = true;
      try {
        await _logHabitToday(habitId, count);
      } catch (e) {
        count++;
        val.textContent = count;
        if (row) _showRowError(row, e.message || 'Failed to log habit');
      } finally {
        dec.disabled = false;
      }
    });

    if (inc) inc.addEventListener('click', async () => {
      count++;
      val.textContent = count;
      inc.disabled = true;
      try {
        await _logHabitToday(habitId, count);
      } catch (e) {
        count--;
        val.textContent = count;
        if (row) _showRowError(row, e.message || 'Failed to log habit');
      } finally {
        inc.disabled = false;
      }
    });
  });

  list.querySelectorAll('.today-duration-input').forEach(input => {
    const row = input.closest('.today-habit-row');
    const habitId = row && row.dataset.habitId;
    let lastValue = '';
    input.addEventListener('change', async () => {
      const v = parseFloat(input.value);
      if (isNaN(v) || v <= 0) return;
      const prev = lastValue;
      lastValue = input.value;
      input.disabled = true;
      try {
        await _logHabitToday(habitId, v);
      } catch (e) {
        input.value = prev;
        lastValue = prev;
        if (row) _showRowError(row, e.message || 'Failed to log habit');
      } finally {
        input.disabled = false;
      }
    });
  });
}

// ── Load & Render (main entry) ────────────────────────────────────────────────

async function loadAndRender() {
  clearError();

  const todayStr = bangkokTodayStr();
  const dates = weekDates();
  const weekFrom = dates[0];
  const weekTo = dates[6];

  try {
    const weekUrl = currentWeekStart
      ? `/api/habits/week?week_start=${currentWeekStart}`
      : '/api/habits/week';

    const [weekRes, activeRes, archivedRes, logsRes] = await Promise.all([
      fetch(weekUrl),
      fetch('/api/habits'),
      fetch('/api/habits?include_archived=true'),
      fetch(`/api/habits/logs?from=${weekFrom}&to=${weekTo}`),
    ]);

    if (!weekRes.ok) throw new Error(`Server error ${weekRes.status}`);
    if (!activeRes.ok) throw new Error(`Server error ${activeRes.status}`);
    if (!archivedRes.ok) throw new Error(`Server error ${archivedRes.status}`);

    weekData = await weekRes.json();
    currentWeekStart = weekData.week_start;

    activeHabits = await activeRes.json();
    const allHabits = await archivedRes.json();
    archivedHabits = allHabits.filter(h => h.is_archived);
    const logs = logsRes.ok ? await logsRes.json() : [];

    // ── Page header (always updated) ──
    renderPageHeader();

    // ── Starter or dashboard ──
    if (activeHabits.length === 0 && archivedHabits.length === 0) {
      renderEmptyState();
      return;
    }

    document.getElementById('starter-section').style.display = 'none';
    document.getElementById('hero-row').style.display = '';
    document.getElementById('habits-day-grid-card').style.display = '';
    document.getElementById('weekly-habits-card').style.display = '';

    // ── Hero cards ──
    renderHeroWheel();
    renderHeroStats();

    // Build log set (habit_id|date → log_id) for current-week done cell log IDs
    const logSet = {};
    logs.forEach(l => {
      if (dates.includes(l.logged_date)) {
        logSet[l.habit_id + '|' + l.logged_date] = l.id;
      }
    });

    // ── Daily grid (uses weekData.daily_habits for 4-state cells) ──
    renderDailyGrid(logSet);
    renderWeeklyHabits(weekData.weekly_habits || [], weekData, activeHabits);
    renderArchivedList();
    initHabitCal();

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
  const cal = document.getElementById('habits-history-cal');
  if (cal) cal.style.display = 'none';
  const detail = document.getElementById('habits-cal-detail');
  if (detail) detail.style.display = 'none';

  renderStarterGrid();
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

// ── Page header ───────────────────────────────────────────────────────────────

function renderPageHeader() {
  const subtitleEl = document.getElementById('habits-subtitle');
  const navLabel = document.getElementById('week-nav-label');
  const nextBtn = document.getElementById('week-next-btn');
  const backWrap = document.getElementById('back-current-wrap');

  const isEmpty = (activeHabits.length === 0 && archivedHabits.length === 0);

  if (isEmpty) {
    if (subtitleEl) subtitleEl.textContent = 'No habits yet — add one to start tracking';
    if (navLabel) navLabel.textContent = weekData ? formatWeekRange(weekData.week_start, weekData.week_end) : '—';
    if (nextBtn) nextBtn.disabled = weekData ? weekData.is_current_week : true;
    if (backWrap) backWrap.style.display = 'none';
    return;
  }

  if (!weekData) return;

  const range = formatWeekRange(weekData.week_start, weekData.week_end);
  if (navLabel) navLabel.textContent = range;
  if (nextBtn) nextBtn.disabled = weekData.is_current_week;
  if (backWrap) backWrap.style.display = weekData.is_current_week ? 'none' : '';

  if (!subtitleEl) return;

  if (!weekData.is_current_week) {
    subtitleEl.textContent = `Week of ${range}`;
    return;
  }

  // Current week: "Week of Jun 9–15 · day N of 7 · X of Y daily checks so far"
  const today = bangkokTodayStr();
  const totals = weekData.week_totals;
  const N = totals.elapsed_days;
  const doneElapsed = (weekData.day_scores || [])
    .filter(ds => ds.date <= today)
    .reduce((acc, ds) => acc + ds.done, 0);
  const possibleElapsed = totals.daily_habits_count * N;
  subtitleEl.textContent = `Week of ${range} · day ${N} of 7 · ${doneElapsed} of ${possibleElapsed} daily checks so far`;
}

// ── Hero wheel (Card A) — 7 solid wedges + center hub ───────────────────────

// Today's done/of/remaining from the current-week day scores.
function _todayScore() {
  const today = bangkokTodayStr();
  const ds = (weekData && weekData.day_scores || []).find(d => d.date === today);
  const done = ds ? ds.done : 0;
  const of = ds ? ds.of : 0;
  return { done, of, remaining: Math.max(0, of - done) };
}

// Mon..Sun index (0..6) of today within the wheel, or -1.
function _todayWheelIndex() {
  const today = bangkokTodayStr();
  return (weekData && weekData.day_scores || []).findIndex(d => d.date === today);
}

// All-streak: every daily habit scheduled today is on an active streak (>=1).
// Returns the binding (minimum) streak length, or 0 when not all are on streak.
function _allStreakLength() {
  const daily = (weekData && weekData.daily_habits) || [];
  const per = (weekData && weekData.streaks && weekData.streaks.per_habit) || {};
  if (!daily.length) return 0;
  let min = Infinity;
  for (const h of daily) {
    const s = per[h.id] || 0;
    if (s < 1) return 0;
    if (s < min) min = s;
  }
  return min === Infinity ? 0 : min;
}

function renderHeroWheel() {
  const svg = document.getElementById('week-wheel-svg');
  const centerEl = document.getElementById('wheel-center');
  const checksEl = document.getElementById('wheel-checks-line');
  if (!svg || !weekData) return;

  const wheel = weekData.wheel || [];
  const totals = weekData.week_totals;
  const FX = window.HabitWheelFx;
  const WH = window.WheelHelpers;

  if (FX && FX.renderThemedWheel) {
    FX.renderThemedWheel(svg, wheel);
  } else if (WH && WH.renderWheelDom) {
    WH.renderWheelDom(svg, wheel);
  }

  // Center: "N more today" countdown when focused on the current week;
  // the weekly percent for a past-week summary view.
  if (FX && FX.renderCenter && centerEl) {
    if (weekData.is_current_week) {
      FX.renderCenter(centerEl, { mode: 'countdown', remaining: _todayScore().remaining });
    } else {
      FX.renderCenter(centerEl, { mode: 'weekly', pct: totals.pct_full_week });
    }
  }

  // All-streak fire: lit only when today's habits are all done AND all on streak.
  if (FX && FX.setFire) {
    const streakLen = _allStreakLength();
    const lit = weekData.is_current_week && _todayScore().remaining === 0 && streakLen >= 1;
    FX.setFire(lit, {
      card: document.getElementById('wheel-card'),
      fire: document.getElementById('wheel-fire'),
      badge: document.getElementById('wheel-fire-badge'),
      streakLen: streakLen,
    });
  }

  // Checks line (right of wheel)
  if (checksEl) {
    const today = bangkokTodayStr();
    const doneElapsed = (weekData.day_scores || [])
      .filter(ds => ds.date <= today)
      .reduce((acc, ds) => acc + ds.done, 0);
    const possibleElapsed = totals.daily_habits_count * totals.elapsed_days;

    if (weekData.is_current_week) {
      checksEl.textContent = `${doneElapsed} / ${possibleElapsed} possible checks (Mon–today)`;
    } else {
      const doneFull = totals.daily_done;
      const possibleFull = totals.daily_habits_count * 7;
      checksEl.textContent = `${doneFull} / ${possibleFull} checks`;
    }
  }
}

// ── Hero stats (Card B) ───────────────────────────────────────────────────────

function renderHeroStats() {
  if (!weekData) return;

  const todayLabelEl  = document.getElementById('stat-today-label');
  const todayValEl    = document.getElementById('stat-today-val');
  const todaySubEl    = document.getElementById('stat-today-sub');
  const streakTile    = document.getElementById('stat-streak-tile');
  const streakValEl   = document.getElementById('stat-streak-val');
  const streakSubEl   = document.getElementById('stat-streak-sub');
  const lastWeekValEl = document.getElementById('stat-lastweek-val');
  const lastWeekSubEl = document.getElementById('stat-lastweek-sub');

  const today   = bangkokTodayStr();
  const totals  = weekData.week_totals;
  const streaks = weekData.streaks || {};
  const lastWeek = weekData.last_week;

  // ── Today tile ──
  if (weekData.is_current_week) {
    const todayScore = (weekData.day_scores || []).find(ds => ds.date === today) || { done: 0, of: 0 };
    if (todayLabelEl) todayLabelEl.textContent = 'Today';
    if (todayValEl) todayValEl.textContent = `${todayScore.done} / ${todayScore.of}`;
    if (todaySubEl) {
      const left = Math.max(0, todayScore.of - todayScore.done);
      todaySubEl.textContent = left === 0
        ? 'all done!'
        : `${left} habit${left !== 1 ? 's' : ''} left to check`;
    }
  } else {
    // Past-week: show week result
    if (todayLabelEl) todayLabelEl.textContent = 'Week result';
    if (todayValEl) todayValEl.textContent = `${Math.round(totals.pct_full_week)}%`;
    if (todaySubEl) todaySubEl.textContent = '';
  }

  // ── Best streak tile (hide gracefully when null) ──
  const best = streaks.best;
  if (streakTile) {
    if (best && best.length > 0) {
      streakTile.style.display = '';
      if (streakValEl) streakValEl.textContent = `${best.length} day${best.length !== 1 ? 's' : ''}`;
      if (streakSubEl) streakSubEl.textContent = best.habit_name || '—';
    } else {
      streakTile.style.display = 'none';
    }
  }

  // ── Last week tile ──
  if (lastWeek) {
    if (lastWeekValEl) lastWeekValEl.textContent = `${Math.round(lastWeek.pct)}%`;
    if (lastWeekSubEl) {
      lastWeekSubEl.innerHTML = `<span class="stat-sub-green">${lastWeek.done} / ${lastWeek.possible} checks ✓</span>`;
    }
  } else {
    if (lastWeekValEl) lastWeekValEl.textContent = '—';
    if (lastWeekSubEl) lastWeekSubEl.textContent = 'no data';
  }
}

// ── Daily grid ────────────────────────────────────────────────────────────────

function _formatTarget(target) {
  if (target == null) return '?';
  return Number.isInteger(target) ? String(target) : target.toFixed(1);
}

function _setCellState(btn, state, logId) {
  btn.dataset.state = state;
  if (logId !== undefined) btn.dataset.logId = logId || '';
  btn.className = 'day-cell-btn';
  if (state === 'done') {
    btn.classList.add('done');
    btn.innerHTML = '<i class="ti ti-check" aria-hidden="true"></i>';
    btn.tabIndex = 0;
  } else if (state === 'today-pending') {
    btn.classList.add('today-pending');
    btn.innerHTML = '<i class="ti ti-plus" aria-hidden="true"></i>';
    btn.tabIndex = 0;
  } else if (state === 'missed') {
    btn.classList.add('missed');
    btn.innerHTML = '';
    btn.tabIndex = weekData && weekData.is_current_week ? 0 : -1;
  } else {
    btn.classList.add('future');
    btn.innerHTML = '';
    btn.tabIndex = -1;
  }
}

function _buildHabitRow(habit, weekDatesArr, streaksPerHabit, todayStr, logSet) {
  const iconHTML = habitIconHTML(habit.icon, habit.color, 28);
  const target = habit.total ? habit.total.target : 7;
  const done = habit.total ? habit.total.done : 0;
  const pct = target > 0 ? Math.min(100, Math.round(done / target * 100)) : 0;
  const barWidth = target > 0 ? Math.min(100, done / target * 100).toFixed(1) : '0.0';

  const streak = streaksPerHabit[habit.id] || 0;
  const streakBadge = streak >= 3
    ? `<span class="streak-badge">🔥 ${streak}-day streak</span>`
    : '';

  const metaTarget = _formatTarget(target);

  let row = `<tr class="habit-row" data-habit-id="${esc(String(habit.id))}">`;
  row += `<td class="habit-name-cell">
      <div class="habit-name-inner">
        ${iconHTML}
        <div>
          <div class="habit-name-text" data-detail-trigger tabindex="0" role="button" aria-label="View details for ${esc(habit.name)}" title="View habit details">${esc(habit.name)}</div>
          <div class="habit-meta-line">
            <span class="habit-type-chip">daily · target ${esc(metaTarget)}/wk</span>
            ${streakBadge}
          </div>
        </div>
      </div>
    </td>`;

  for (let i = 0; i < 7; i++) {
    const day = habit.days[i] || { date: weekDatesArr[i] || '', state: 'future' };
    const dateStr = day.date;
    const stateRaw = day.state;
    const cssState = stateRaw === 'today_pending' ? 'today-pending' : stateRaw;
    const logKey = habit.id + '|' + dateStr;
    const logId = logSet[logKey] || '';

    const isInert = cssState === 'future' || !(weekData && weekData.is_current_week);
    const tIdx = isInert && cssState !== 'done' ? -1 : 0;

    let cellInner = '';
    if (cssState === 'done') {
      cellInner = '<i class="ti ti-check" aria-hidden="true"></i>';
    } else if (cssState === 'today-pending') {
      cellInner = '<i class="ti ti-plus" aria-hidden="true"></i>';
    }

    const ariaLabel = `${habit.name} ${DAY_LABELS_FULL[i]}: ${stateRaw.replace('_', ' ')}`;
    row += `<td><button
        class="day-cell-btn ${esc(cssState)}"
        type="button"
        aria-label="${esc(ariaLabel)}"
        data-habit-id="${esc(String(habit.id))}"
        data-date="${esc(dateStr)}"
        data-state="${esc(cssState)}"
        data-log-id="${esc(logId)}"
        tabindex="${tIdx}"
      >${cellInner}</button></td>`;
  }

  row += `<td class="day-total-cell" id="total-cell-${esc(String(habit.id))}">
      <span class="day-total-val">${esc(String(done))}/${esc(_formatTarget(target))}</span>
      <div class="day-total-bar-outer"><div class="day-total-bar-inner" style="width:${barWidth}%"></div></div>
      <span class="day-total-pct">${pct}%</span>
    </td>`;

  row += `<td class="habit-actions-cell">
      <div class="habit-day-actions">
        <button type="button" class="day-actions-toggle" aria-label="Habit actions for ${esc(habit.name)}">⋯</button>
        <div class="day-actions-menu" id="day-menu-${esc(String(habit.id))}"></div>
      </div>
    </td>`;

  row += '</tr>';
  return row;
}

function renderDailyGrid(logSet) {
  const container = document.getElementById('day-grid-content');
  if (!container) return;

  const dailyHabits = (weekData && weekData.daily_habits) || [];
  const dayScores = (weekData && weekData.day_scores) || [];
  const streaksPerHabit = (weekData && weekData.streaks && weekData.streaks.per_habit) || {};
  const todayStr = bangkokTodayStr();

  if (dailyHabits.length === 0) {
    container.innerHTML = '<div class="day-grid-empty">No daily habits yet.</div>';
    // Hide section containers
    const ts = document.getElementById('day-grid-training-section');
    const gs = document.getElementById('day-grid-general-section');
    if (ts) ts.style.display = 'none';
    if (gs) gs.style.display = 'none';
    return;
  }

  // Compute day dates from weekData
  const weekDatesArr = (weekData && weekData.day_scores)
    ? weekData.day_scores.map(ds => ds.date)
    : [];

  const trainingHabits = dailyHabits.filter(h => h.section === 'training');
  const generalHabits = dailyHabits.filter(h => h.section !== 'training');

  const theadHTML = (() => {
    let h = '<thead><tr>';
    h += '<th class="habit-name-hdr" scope="col">Habit</th>';
    for (let i = 0; i < 7; i++) {
      const dateStr = weekDatesArr[i] || '';
      const isToday = dateStr === todayStr;
      const todayCls = isToday ? ' day-hdr-today' : '';
      h += `<th class="${todayCls}" scope="col"><span class="day-hdr-full">${DAY_LABELS_FULL[i]}</span></th>`;
    }
    h += '<th class="day-total-hdr" scope="col">Total</th>';
    h += '<th class="habit-actions-hdr" scope="col"><span class="u-sr-only">Actions</span></th>';
    h += '</tr></thead>';
    return h;
  })();

  function _buildSectionTable(habits) {
    let h = `<table class="day-grid-table" role="grid">${theadHTML}<tbody>`;
    habits.forEach(habit => { h += _buildHabitRow(habit, weekDatesArr, streaksPerHabit, todayStr, logSet); });
    h += '</tbody></table>';
    return h;
  }

  // Show or hide section containers
  const trainingSection = document.getElementById('day-grid-training-section');
  const generalSection = document.getElementById('day-grid-general-section');
  const trainingContent = document.getElementById('day-grid-training-content');
  const generalContent = document.getElementById('day-grid-general-content');

  if (trainingHabits.length > 0) {
    if (trainingContent) trainingContent.innerHTML = _buildSectionTable(trainingHabits);
    if (trainingSection) trainingSection.style.display = '';
  } else {
    if (trainingSection) trainingSection.style.display = 'none';
  }

  if (generalHabits.length > 0) {
    if (generalContent) generalContent.innerHTML = _buildSectionTable(generalHabits);
    if (generalSection) generalSection.style.display = '';
  } else {
    if (generalSection) generalSection.style.display = 'none';
  }

  // Day Score row in the legacy container
  const totalDone = weekData ? weekData.week_totals.daily_done : 0;
  const totalPossible = weekData ? weekData.week_totals.daily_habits_count * 7 : 0;
  const weekPct = weekData ? Math.round(weekData.week_totals.pct_full_week) : 0;
  const weekBarW = weekData ? Math.min(100, weekData.week_totals.pct_full_week).toFixed(1) : '0.0';

  let scoreHTML = `<table class="day-grid-table day-score-only" role="presentation"><tbody>`;
  scoreHTML += '<tr class="day-score-row" id="day-score-row">';
  scoreHTML += '<td class="day-score-label">Day Score</td>';
  for (let i = 0; i < 7; i++) {
    const ds = dayScores[i] || { date: '', done: 0, of: 0 };
    const dateStr = ds.date;
    const isFuture = dateStr > todayStr;
    const isToday = dateStr === todayStr;
    let valCls = '';
    let valTxt = '';
    if (isFuture) {
      valCls = 'day-score-dash';
      valTxt = '—';
    } else {
      if (ds.of > 0 && ds.done === ds.of) valCls = 'day-score-full';
      else if (isToday) valCls = 'day-score-today';
      valTxt = `${ds.done}/${ds.of}`;
    }
    scoreHTML += `<td class="day-score-cell" data-date="${esc(dateStr)}">
      <span class="day-score-val ${valCls}">${esc(valTxt)}</span>
    </td>`;
  }
  scoreHTML += `<td class="day-total-cell" id="day-score-total-cell">
    <span class="day-total-val">${esc(String(totalDone))}/${esc(String(totalPossible))}</span>
    <div class="day-total-bar-outer"><div class="day-total-bar-inner" style="width:${weekBarW}%"></div></div>
    <span class="day-total-pct">${weekPct}% of week</span>
  </td>`;
  scoreHTML += '<td></td></tr></tbody></table>';
  container.innerHTML = scoreHTML;
  container.style.display = '';

  // Build action menus and attach handlers for all daily habits
  dailyHabits.forEach(habit => {
    const fullHabit = activeHabits.find(h => String(h.id) === String(habit.id)) || habit;
    const menu = document.getElementById(`day-menu-${habit.id}`);
    if (menu) {
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.textContent = 'Edit';
      editBtn.addEventListener('click', () => { closeAllMenus(); openHabitForm(fullHabit); });
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

      const toggle = menu.previousElementSibling;
      if (toggle) {
        toggle.addEventListener('click', e => {
          e.stopPropagation();
          closeAllMenus();
          menu.classList.toggle('open');
        });
      }
    }
  });

  // Attach click and keyboard handlers on actionable cells across all section containers
  const gridRoot = document.getElementById('habits-day-grid-card') || container.parentElement;
  (gridRoot || container).querySelectorAll('.day-cell-btn').forEach(btn => {
    const state = btn.dataset.state;
    const isInert = state === 'future' ||
      !(weekData && weekData.is_current_week) && state !== 'done';

    if (!isInert) {
      btn.addEventListener('click', () => handleGridCellAction(btn));
      btn.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handleGridCellAction(btn);
        }
      });
    }
  });

  _wireDetailTriggers();
}

// Update just the totals portion of the grid after a mutation (without rebuilding everything)
function refreshGridTotals() {
  if (!weekData) return;
  const dailyHabits = weekData.daily_habits || [];
  const dayScores = weekData.day_scores || [];
  const todayStr = bangkokTodayStr();

  // Per-habit total cells
  dailyHabits.forEach(habit => {
    const totalCell = document.getElementById(`total-cell-${habit.id}`);
    if (!totalCell) return;
    const done = habit.total ? habit.total.done : 0;
    const target = habit.total ? habit.total.target : 7;
    const pct = target > 0 ? Math.min(100, Math.round(done / target * 100)) : 0;
    const barWidth = target > 0 ? Math.min(100, done / target * 100).toFixed(1) : '0.0';
    totalCell.innerHTML = `
      <span class="day-total-val">${done}/${_formatTarget(target)}</span>
      <div class="day-total-bar-outer"><div class="day-total-bar-inner" style="width:${barWidth}%"></div></div>
      <span class="day-total-pct">${pct}%</span>
    `;
  });

  // Day score cells
  const scoreRow = document.getElementById('day-score-row');
  if (scoreRow) {
    dayScores.forEach(ds => {
      const cell = scoreRow.querySelector(`[data-date="${ds.date}"]`);
      if (!cell) return;
      const isFuture = ds.date > todayStr;
      const isToday = ds.date === todayStr;
      let valCls = '';
      let valTxt = '';
      if (isFuture) {
        valCls = 'day-score-dash';
        valTxt = '—';
      } else {
        if (ds.of > 0 && ds.done === ds.of) valCls = 'day-score-full';
        else if (isToday) valCls = 'day-score-today';
        valTxt = `${ds.done}/${ds.of}`;
      }
      cell.innerHTML = `<span class="day-score-val ${valCls}">${valTxt}</span>`;
    });

    // Grand total
    const totalCell = document.getElementById('day-score-total-cell');
    if (totalCell) {
      const totals = weekData.week_totals;
      const done = totals.daily_done;
      const possible = totals.daily_habits_count * 7;
      const pct = Math.round(totals.pct_full_week);
      const barW = Math.min(100, totals.pct_full_week).toFixed(1);
      totalCell.innerHTML = `
        <span class="day-total-val">${done}/${possible}</span>
        <div class="day-total-bar-outer"><div class="day-total-bar-inner" style="width:${barW}%"></div></div>
        <span class="day-total-pct">${pct}% of week</span>
      `;
    }
  }
}

// Set when a today check-in just landed; consumed after the next hero render
// to play the wheel celebration (pop + burst + confetti + center tick).
let _pendingCheckCelebrate = false;

function celebrateTodayCheckin() {
  const FX = window.HabitWheelFx;
  if (!FX || !FX.playCheckIn) return;
  const idx = _todayWheelIndex();
  if (idx < 0) return;
  FX.playCheckIn({
    svg: document.getElementById('week-wheel-svg'),
    center: document.getElementById('wheel-center'),
    fx: document.getElementById('wheel-fx'),
    segIndex: idx,
  });
}

// Debounced 300 ms refetch of /api/habits/week → refresh hero + grid totals
function scheduleHeroRefresh() {
  if (_gridRefreshTimer) clearTimeout(_gridRefreshTimer);
  _gridRefreshTimer = setTimeout(async () => {
    const weekUrl = currentWeekStart
      ? `/api/habits/week?week_start=${currentWeekStart}`
      : '/api/habits/week';
    try {
      const res = await fetch(weekUrl);
      if (!res.ok) return;
      weekData = await res.json();
      renderPageHeader();
      renderHeroWheel();
      renderHeroStats();
      refreshGridTotals();
      if (_pendingCheckCelebrate) {
        _pendingCheckCelebrate = false;
        celebrateTodayCheckin();
      }
      if (window.HabitInsights) window.HabitInsights.load();
    } catch (_e) {
      // non-critical: hero will refresh on next full load
    }
  }, 300);
}

async function handleGridCellAction(btn) {
  const habitId = btn.dataset.habitId;
  const dateStr = btn.dataset.date;
  const state = btn.dataset.state;  // 'done', 'today-pending', 'missed'

  // Guard: only mutate in current week, never future cells
  if (!weekData || !weekData.is_current_week) return;
  if (state === 'future') return;

  const prevState = state;
  const prevLogId = btn.dataset.logId || '';

  // Optimistic update
  const todayStr = bangkokTodayStr();
  if (state === 'done') {
    const revertState = dateStr === todayStr ? 'today-pending' : 'missed';
    _setCellState(btn, revertState, '');
  } else {
    _setCellState(btn, 'done');
  }

  btn.disabled = true;

  try {
    if (prevState === 'done') {
      if (!prevLogId) { btn.disabled = false; return; }
      const res = await fetch(`/api/habits/logs/${encodeURIComponent(prevLogId)}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 404) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
    } else {
      const res = await fetch('/api/habits/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ habit_id: habitId, logged_date: dateStr }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      btn.dataset.logId = data.id || '';
    }

    // Celebrate only when a today cell was just checked ON (not unchecked).
    if (prevState !== 'done' && dateStr === todayStr) _pendingCheckCelebrate = true;

    scheduleHeroRefresh();

  } catch (e) {
    // Rollback to previous state
    _setCellState(btn, prevState, prevLogId);
    if (typeof UIStates !== 'undefined') UIStates.showToast(e.message || 'Failed to update', true);
  }

  btn.disabled = false;
}

// ── Weekly habits card ────────────────────────────────────────────────────────

const _AUTO_FILL_DESCRIPTIONS = {
  'workout.zone2_minutes':          'synced with zone-2 minutes on your runs',
  'workout.run_count':              'synced with run workouts',
  'workout.lift_count':             'synced with strength workouts',
  'workout.total_duration_minutes': 'synced with total workout duration',
  'workout.distance_km':            'synced with workout distances',
};

const _WEEK_DAY_SHORTS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function _formatBreakdown(dailyBreakdown, weekStart) {
  if (!dailyBreakdown || dailyBreakdown.length === 0) return '';
  const [wy, wm, wd] = weekStart.split('-').map(Number);
  const monDate = new Date(wy, wm - 1, wd);
  return dailyBreakdown
    .map(entry => {
      const d = new Date(entry.date + 'T00:00:00');
      const dow = (d.getDay() + 6) % 7; // 0=Mon
      const dayName = _WEEK_DAY_SHORTS[dow] || entry.date;
      const v = entry.value;
      const vStr = Number.isInteger(v) ? String(v) : v.toFixed(1);
      return `${dayName} ${vStr}`;
    })
    .join(' · ');
}

function _fmtVal(v) {
  if (v == null) return '—';
  return Number.isInteger(v) ? String(v) : Number(v).toFixed(1);
}

function _renderSegmentedBar(current, target, isComplete) {
  const segCount = Math.max(1, Math.round(target));
  const filled = Math.min(segCount, Math.round(current));
  const over = Math.max(0, Math.round(current) - segCount);
  const completeCls = isComplete ? ' complete' : '';

  let segsHTML = '';
  for (let i = 0; i < segCount; i++) {
    const isFilled = i < filled;
    segsHTML += `<div class="week-seg${isFilled ? ' filled' + completeCls : ''}"></div>`;
  }
  const overHTML = over > 0 ? `<span class="week-overflow-label">+${over} over</span>` : '';
  return `<div class="week-seg-bar">${segsHTML}${overHTML}</div>`;
}

function _renderSmoothBar(pct, isComplete) {
  const w = Math.min(100, pct).toFixed(1);
  const completeCls = isComplete ? ' complete' : '';
  return `<div class="week-smooth-bar-outer">
    <div class="week-smooth-bar-fill${completeCls}" style="width:${w}%"></div>
    <div class="week-smooth-bar-endmark"></div>
  </div>`;
}

function renderWeeklyHabits(weeklyHabits, wkData, fullHabitsList) {
  const container = document.getElementById('weekly-habits-content');
  if (!container) return;

  const isCurrentWeek = wkData && wkData.is_current_week;
  const elapsedDays = (wkData && wkData.week_totals && wkData.week_totals.elapsed_days) || 0;
  const weekStart = (wkData && wkData.week_start) || '';

  if (!weeklyHabits || weeklyHabits.length === 0) {
    container.innerHTML = `
      <div class="weekly-habits-empty">
        <p>Track weekly goals like Zone 2 minutes — they can sync automatically from your workouts</p>
        <button type="button" class="weekly-empty-new-btn" id="weekly-empty-new-btn">＋ New habit</button>
      </div>`;
    const emptyBtn = container.querySelector('#weekly-empty-new-btn');
    if (emptyBtn) {
      emptyBtn.addEventListener('click', () => {
        openHabitForm();
        const sel = document.getElementById('habit-form-habit-type');
        if (sel) { sel.value = 'duration'; _sfUpdateVisibility(); }
      });
    }
    return;
  }

  container.innerHTML = '';

  weeklyHabits.forEach(habit => {
    const current = habit.current_value != null ? habit.current_value : 0;
    const target = habit.target;
    const pct = Math.min(100, habit.pct != null ? habit.pct : 0);
    const isComplete = !!habit.is_complete;
    const unit = habit.unit || '';
    const isAutoFill = !!habit.auto_fill_source;
    const trackingType = habit.tracking_type;

    // Value string
    const valStr = target != null
      ? `${_fmtVal(current)} / ${_fmtVal(target)}${unit ? ' ' + unit : ''}`
      : '—';

    // Progress bar HTML
    const barHTML = trackingType === 'weekly_count'
      ? _renderSegmentedBar(current, target || 1, isComplete)
      : _renderSmoothBar(pct, isComplete);

    // Daily breakdown label
    const breakdownStr = _formatBreakdown(habit.daily_breakdown, weekStart);

    // Pace sub-line
    let paceHTML = '';
    if (target != null && target > 0) {
      const onPace = elapsedDays === 0 || (current / target) >= (elapsedDays / 7);
      if (onPace) {
        paceHTML = `<div class="week-pace-line"><span class="week-pace-on">on pace</span></div>`;
      } else {
        const remaining = habit.remaining != null ? habit.remaining : Math.max(0, target - current);
        const remStr = _fmtVal(remaining);
        const unitStr = unit ? ` ${unit}` : '';
        paceHTML = `<div class="week-pace-line"><span class="week-pace-behind">${esc(remStr)}${esc(unitStr)} to go</span></div>`;
      }
    }

    // Meta badge (auto vs manual)
    let metaHTML = '';
    if (isAutoFill) {
      const srcDesc = _AUTO_FILL_DESCRIPTIONS[habit.auto_fill_source] || habit.auto_fill_source;
      metaHTML = `
        <span class="week-auto-badge" title="Updates automatically from your workouts">↻ auto · workouts</span>
        <span class="week-auto-source">${esc(srcDesc)}</span>`;
    } else {
      const logChip = isCurrentWeek
        ? `<button type="button" class="week-log-chip" data-habit-id="${esc(String(habit.id))}" data-tracking-type="${esc(trackingType)}" data-unit="${esc(unit)}">＋ log</button>`
        : '';
      metaHTML = `<span class="week-manual-badge">manual</span>${logChip}`;
    }

    const iconHTML = habitIconHTML(habit.icon, habit.color, 30);

    const row = document.createElement('div');
    row.className = 'week-habit-row';
    row.id = `habit-week-row-${habit.id}`;

    row.innerHTML = `
      <div class="week-habit-left">
        ${iconHTML}
        <div class="week-habit-info">
          <div class="week-habit-name" data-detail-trigger tabindex="0" role="button" aria-label="View details for ${esc(habit.name)}" title="View habit details">${esc(habit.name)}</div>
          <div class="week-habit-meta">${metaHTML}</div>
        </div>
      </div>
      <div class="week-habit-progress">
        ${barHTML}
        <div class="week-bar-labels">
          <span class="week-breakdown-label">${esc(breakdownStr)}</span>
          ${target != null ? `<span class="week-target-label">target ${esc(_fmtVal(target))}</span>` : ''}
        </div>
      </div>
      <div class="week-habit-right">
        <span class="week-habit-val-main" id="week-val-${esc(String(habit.id))}">${esc(valStr)}</span>
        ${paceHTML}
        <div class="week-habit-actions">
          <button type="button" class="week-actions-toggle" aria-label="Habit actions for ${esc(habit.name)}">⋯</button>
          <div class="week-actions-menu" id="week-menu-${esc(String(habit.id))}"></div>
        </div>
      </div>`;

    // Build action menu
    const menu = row.querySelector('.week-actions-menu');
    const fullHabit = (fullHabitsList || []).find(h => String(h.id) === String(habit.id)) || habit;

    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => { closeAllMenus(); openEditModal(fullHabit); });
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

  // Attach log chip handlers
  if (isCurrentWeek) {
    container.querySelectorAll('.week-log-chip').forEach(chip => {
      chip.addEventListener('click', e => {
        e.stopPropagation();
        openLogPopover(chip);
      });
    });
  }

  _wireDetailTriggers();
}

// ── Log popover ───────────────────────────────────────────────────────────────

let _activePopover = null;

function closeLogPopover() {
  if (_activePopover) {
    _activePopover.remove();
    _activePopover = null;
  }
}

function openLogPopover(chip) {
  closeLogPopover();

  const habitId = chip.dataset.habitId;
  const trackingType = chip.dataset.trackingType;
  const unit = chip.dataset.unit || '';

  const popover = document.createElement('div');
  popover.className = 'week-log-popover';
  _activePopover = popover;

  const isMinutes = trackingType === 'weekly_minutes';

  const quickChipsHTML = isMinutes
    ? `<div class="week-quick-chips">
        <button type="button" class="week-quick-chip" data-add="5">+5</button>
        <button type="button" class="week-quick-chip" data-add="10">+10</button>
        <button type="button" class="week-quick-chip" data-add="15">+15</button>
      </div>`
    : '';

  popover.innerHTML = `
    <div class="week-popover-title">Log${unit ? ' ' + unit : ''}</div>
    <input class="week-popover-input" type="number" min="0.1" step="any" placeholder="Amount…">
    ${quickChipsHTML}
    <button type="button" class="week-popover-submit">Add</button>
    <div class="week-popover-error"></div>`;

  const input = popover.querySelector('.week-popover-input');
  const submitBtn = popover.querySelector('.week-popover-submit');
  const errorEl = popover.querySelector('.week-popover-error');

  // Quick chips accumulate into the input
  if (isMinutes) {
    popover.querySelectorAll('.week-quick-chip').forEach(qc => {
      qc.addEventListener('click', () => {
        const current = parseFloat(input.value) || 0;
        input.value = current + parseInt(qc.dataset.add, 10);
      });
    });
  }

  submitBtn.addEventListener('click', async () => {
    const value = parseFloat(input.value);
    if (!value || value <= 0) {
      errorEl.textContent = 'Enter a value greater than 0';
      return;
    }
    submitBtn.disabled = true;
    errorEl.textContent = '';
    try {
      const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value, mode: 'add' }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errorEl.textContent = (body.detail && body.detail.error_code) || body.detail || `Error ${res.status}`;
        submitBtn.disabled = false;
        return;
      }
      const data = await res.json();
      closeLogPopover();

      // Update value display from week_current_value without full refetch
      const weekCurrentValue = data.week_current_value;
      if (weekCurrentValue != null) {
        const valEl = document.getElementById(`week-val-${habitId}`);
        if (valEl) {
          const wh = (weekData && weekData.weekly_habits || []).find(h => h.id === habitId);
          const tgt = wh ? wh.target : null;
          const unit2 = wh ? (wh.unit || '') : '';
          const newValStr = tgt != null
            ? `${_fmtVal(weekCurrentValue)} / ${_fmtVal(tgt)}${unit2 ? ' ' + unit2 : ''}`
            : _fmtVal(weekCurrentValue);
          valEl.textContent = newValStr;
        }

        // Update progress bar visually
        const row = document.getElementById(`habit-week-row-${habitId}`);
        if (row) {
          const wh = (weekData && weekData.weekly_habits || []).find(h => h.id === habitId);
          if (wh && wh.target != null) {
            wh.current_value = weekCurrentValue;
            wh.pct = Math.min(100, (weekCurrentValue / wh.target) * 100);
            wh.is_complete = weekCurrentValue >= wh.target;
            wh.remaining = Math.max(0, wh.target - weekCurrentValue);

            const progDiv = row.querySelector('.week-habit-progress');
            if (progDiv) {
              const newBarHTML = wh.tracking_type === 'weekly_count'
                ? _renderSegmentedBar(weekCurrentValue, wh.target, wh.is_complete)
                : _renderSmoothBar(wh.pct, wh.is_complete);
              const existing = progDiv.querySelector('.week-seg-bar, .week-smooth-bar-outer');
              if (existing) existing.outerHTML = newBarHTML;
            }
          }
        }
      }
    } catch (err) {
      errorEl.textContent = err.message || 'Failed to log';
      submitBtn.disabled = false;
    }
  });

  // Position popover relative to chip
  const chipRect = chip.getBoundingClientRect();
  popover.style.position = 'fixed';
  popover.style.top = (chipRect.bottom + 6) + 'px';
  popover.style.left = Math.max(8, chipRect.left) + 'px';

  document.body.appendChild(popover);
  input.focus();

  // Close on outside click
  setTimeout(() => {
    document.addEventListener('click', _closePopoverOnOutside, { once: false, capture: true });
  }, 0);
}

function _closePopoverOnOutside(e) {
  if (_activePopover && !_activePopover.contains(e.target) && !e.target.classList.contains('week-log-chip')) {
    closeLogPopover();
    document.removeEventListener('click', _closePopoverOnOutside, true);
  }
}

function closeAllMenus() {
  document.querySelectorAll('.week-actions-menu.open, .day-actions-menu.open, .actions-menu.open').forEach(m => m.classList.remove('open'));
  closeLogPopover();
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

    const iconHTML = habitIconHTML(habit.icon, habit.color, 28);
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

function openEditModal(habit) {
  editingHabitId = habit.id;
  selectedIcon = habit.icon || ICONS[0];
  selectedColor = habit.color || COLORS[0];

  document.getElementById('modal-title').textContent = 'Edit habit';
  document.getElementById('modal-submit').textContent = 'Save changes';
  document.getElementById('modal-name').value = habit.name || '';
  document.getElementById('modal-description').value = habit.description || '';
  document.getElementById('modal-tracking-type').value = habit.tracking_type || 'daily_checkmark';
  document.getElementById('modal-tracking-type').disabled = true;
  document.getElementById('modal-tracking-type-hint').style.display = '';
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
  document.getElementById('modal-tracking-type').disabled = false;
  editingHabitId = null;
}

// ── Form submit ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-habit-btn').addEventListener('click', () => openHabitForm());
  document.getElementById('modal-cancel').addEventListener('click', closeModal);

  // ── Week navigation ──
  const prevBtn = document.getElementById('week-prev-btn');
  const nextBtn = document.getElementById('week-next-btn');
  const backBtn = document.getElementById('back-current-btn');

  if (prevBtn) {
    prevBtn.addEventListener('click', async () => {
      if (!currentWeekStart) return;
      const [y, m, d] = currentWeekStart.split('-').map(Number);
      const prevMon = new Date(y, m - 1, d - 7);
      currentWeekStart = isoDate(prevMon);
      await loadAndRender();
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', async () => {
      if (!currentWeekStart || (weekData && weekData.is_current_week)) return;
      const [y, m, d] = currentWeekStart.split('-').map(Number);
      const nextMon = new Date(y, m - 1, d + 7);
      currentWeekStart = isoDate(nextMon);
      await loadAndRender();
    });
  }

  if (backBtn) {
    backBtn.addEventListener('click', async () => {
      currentWeekStart = null;
      await loadAndRender();
    });
  }

  document.getElementById('habit-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('habit-modal')) closeModal();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeModal(); closeHabitForm(); }
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

    // tracking_type is immutable after creation — backend rejects it in PATCH
    if (editingHabitId) delete payload.tracking_type;

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

// ── Habit slide-over form (issue #832) ───────────────────────────────────────

let _sfEditingHabitId = null;

function openHabitForm(habit) {
  _sfEditingHabitId = habit ? habit.id : null;

  const titleEl = document.getElementById('habit-form-title');
  const submitEl = document.getElementById('habit-form-submit');
  const archiveEl = document.getElementById('habit-form-archive');

  if (titleEl) titleEl.textContent = habit ? 'Edit Habit' : 'New Habit';
  if (submitEl) submitEl.textContent = habit ? 'Save Changes' : 'Save Habit';
  if (archiveEl) archiveEl.style.display = habit ? '' : 'none';

  const errorIds = [
    'habit-form-name-error',
    'habit-form-target-value-error',
    'habit-form-schedule-target-error',
    'habit-form-error',
  ];
  errorIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.remove('is-visible'); }
  });

  if (habit) {
    const fields = _sfApiToForm(habit);
    document.getElementById('habit-form-name').value = habit.name || '';
    document.getElementById('habit-form-habit-type').value = fields.habitType;
    document.getElementById('habit-form-target-value').value = fields.targetValue != null ? fields.targetValue : '';
    document.getElementById('habit-form-unit').value = habit.unit || '';
    document.getElementById('habit-form-schedule-type').value = fields.scheduleType;
    document.getElementById('habit-form-schedule-target').value = fields.scheduleTarget != null ? fields.scheduleTarget : '';
    const secEl = document.getElementById('habit-form-section');
    if (secEl) secEl.value = habit.section || 'general';
  } else {
    document.getElementById('habit-form-name').value = '';
    document.getElementById('habit-form-habit-type').value = 'binary';
    document.getElementById('habit-form-target-value').value = '';
    document.getElementById('habit-form-unit').value = '';
    document.getElementById('habit-form-schedule-type').value = 'daily';
    document.getElementById('habit-form-schedule-target').value = '';
    const secEl = document.getElementById('habit-form-section');
    if (secEl) secEl.value = 'general';
  }

  _sfUpdateVisibility();

  const overlay = document.getElementById('habit-slideover');
  if (overlay) overlay.classList.add('is-open');
  const nameEl = document.getElementById('habit-form-name');
  if (nameEl) nameEl.focus();
}

function closeHabitForm() {
  const overlay = document.getElementById('habit-slideover');
  if (overlay) overlay.classList.remove('is-open');
  _sfEditingHabitId = null;
}

function _sfUpdateVisibility() {
  const habitType = (document.getElementById('habit-form-habit-type') || {}).value;
  const scheduleType = (document.getElementById('habit-form-schedule-type') || {}).value;

  const targetRow = document.getElementById('habit-form-target-row');
  const scheduleTargetRow = document.getElementById('habit-form-schedule-target-row');

  const showTarget = habitType === 'count' || habitType === 'duration';
  if (targetRow) {
    targetRow.style.display = showTarget ? '' : 'none';
    if (!showTarget) {
      document.getElementById('habit-form-target-value').value = '';
      document.getElementById('habit-form-unit').value = '';
    }
  }

  const showScheduleTarget = scheduleType === 'times_per_week';
  if (scheduleTargetRow) {
    scheduleTargetRow.style.display = showScheduleTarget ? '' : 'none';
    if (!showScheduleTarget) {
      document.getElementById('habit-form-schedule-target').value = '';
    }
  }
}

function _sfApiToForm(habit) {
  let habitType = 'binary';
  let scheduleType = 'daily';
  let targetValue = null;
  let scheduleTarget = null;

  switch (habit.tracking_type) {
    case 'daily_checkmark':
      habitType = 'binary'; scheduleType = 'daily';
      break;
    case 'weekly_count':
      habitType = 'count'; scheduleType = 'weekly';
      targetValue = habit.weekly_target;
      break;
    case 'weekly_minutes':
      habitType = 'duration'; scheduleType = 'weekly';
      targetValue = habit.weekly_target;
      break;
    case 'weekly_quantity':
      habitType = 'count'; scheduleType = 'weekly';
      targetValue = habit.weekly_target;
      break;
    default:
      habitType = 'binary'; scheduleType = 'daily';
  }

  return { habitType, scheduleType, targetValue, scheduleTarget };
}

function _sfFormToApiPayload(habitType, scheduleType, targetValue, scheduleTarget, name, unit, section) {
  let tracking_type;
  let weekly_target = null;

  if (habitType === 'binary') {
    if (scheduleType === 'daily') {
      tracking_type = 'daily_checkmark';
    } else if (scheduleType === 'weekly') {
      tracking_type = 'weekly_count';
      weekly_target = 7;
    } else {
      tracking_type = 'weekly_count';
      weekly_target = scheduleTarget;
    }
  } else if (habitType === 'count') {
    tracking_type = 'weekly_count';
    weekly_target = scheduleType === 'times_per_week' ? scheduleTarget : targetValue;
  } else {
    tracking_type = 'weekly_minutes';
    weekly_target = scheduleType === 'times_per_week' ? scheduleTarget : targetValue;
  }

  return {
    name,
    tracking_type,
    weekly_target,
    unit: habitType !== 'binary' ? (unit || null) : null,
    section: section || 'general',
  };
}

document.addEventListener('DOMContentLoaded', () => {
  const habitTypeEl = document.getElementById('habit-form-habit-type');
  const schedTypeEl = document.getElementById('habit-form-schedule-type');
  if (habitTypeEl) habitTypeEl.addEventListener('change', _sfUpdateVisibility);
  if (schedTypeEl) schedTypeEl.addEventListener('change', _sfUpdateVisibility);

  const cancelBtn = document.getElementById('habit-form-cancel');
  if (cancelBtn) cancelBtn.addEventListener('click', closeHabitForm);

  const closeBtn = document.getElementById('habit-slideover-close-btn');
  if (closeBtn) closeBtn.addEventListener('click', closeHabitForm);

  const backdrop = document.getElementById('habit-slideover-backdrop');
  if (backdrop) backdrop.addEventListener('click', closeHabitForm);

  const archiveBtn = document.getElementById('habit-form-archive');
  if (archiveBtn) {
    archiveBtn.addEventListener('click', async () => {
      if (!_sfEditingHabitId) return;
      if (!confirm('Archive this habit? Its log history will be preserved.')) return;
      const errorEl = document.getElementById('habit-form-error');
      try {
        const res = await fetch(`/api/habits/${encodeURIComponent(_sfEditingHabitId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_archived: true }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          if (errorEl) { errorEl.textContent = body.detail || `Server error ${res.status}`; errorEl.classList.add('is-visible'); }
          return;
        }
        closeHabitForm();
        if (typeof UIStates !== 'undefined') UIStates.showToast('Habit archived');
        await loadAndRender();
      } catch (err) {
        if (errorEl) { errorEl.textContent = 'Failed to archive: ' + err.message; errorEl.classList.add('is-visible'); }
      }
    });
  }

  const habitForm = document.getElementById('habit-form');
  if (habitForm) {
    habitForm.addEventListener('submit', async e => {
      e.preventDefault();

      const errorIds = ['habit-form-name-error', 'habit-form-target-value-error', 'habit-form-schedule-target-error', 'habit-form-error'];
      errorIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = ''; el.classList.remove('is-visible'); }
      });

      let valid = true;
      let firstInvalid = null;

      const name = document.getElementById('habit-form-name').value.trim();
      if (!name) {
        const err = document.getElementById('habit-form-name-error');
        if (err) { err.textContent = 'Name is required.'; err.classList.add('is-visible'); }
        firstInvalid = firstInvalid || document.getElementById('habit-form-name');
        valid = false;
      }

      const habitType = document.getElementById('habit-form-habit-type').value;
      const scheduleType = document.getElementById('habit-form-schedule-type').value;

      let targetValue = null;
      if (habitType === 'count' || habitType === 'duration') {
        const tvEl = document.getElementById('habit-form-target-value');
        const val = parseFloat(tvEl.value);
        if (!tvEl.value || isNaN(val) || val <= 0) {
          const err = document.getElementById('habit-form-target-value-error');
          if (err) { err.textContent = 'Target value must be a positive number.'; err.classList.add('is-visible'); }
          firstInvalid = firstInvalid || tvEl;
          valid = false;
        } else {
          targetValue = val;
        }
      }

      let scheduleTarget = null;
      if (scheduleType === 'times_per_week') {
        const stEl = document.getElementById('habit-form-schedule-target');
        const val = parseInt(stEl.value, 10);
        if (!stEl.value || isNaN(val) || val <= 0) {
          const err = document.getElementById('habit-form-schedule-target-error');
          if (err) { err.textContent = 'Times per week must be a positive integer.'; err.classList.add('is-visible'); }
          firstInvalid = firstInvalid || stEl;
          valid = false;
        } else {
          scheduleTarget = val;
        }
      }

      if (!valid) {
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      const unit = document.getElementById('habit-form-unit').value.trim() || null;
      const sectionEl = document.getElementById('habit-form-section');
      const section = sectionEl ? sectionEl.value : 'general';
      const payload = _sfFormToApiPayload(habitType, scheduleType, targetValue, scheduleTarget, name, unit, section);

      // tracking_type is immutable after creation — backend rejects it in PATCH
      if (_sfEditingHabitId) delete payload.tracking_type;

      const genErrorEl = document.getElementById('habit-form-error');
      try {
        let res;
        if (_sfEditingHabitId) {
          res = await fetch(`/api/habits/${encodeURIComponent(_sfEditingHabitId)}`, {
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
          if (genErrorEl) { genErrorEl.textContent = body.detail || `Server error ${res.status}`; genErrorEl.classList.add('is-visible'); }
          return;
        }
        closeHabitForm();
        if (typeof UIStates !== 'undefined') UIStates.showToast(_sfEditingHabitId ? 'Habit updated' : 'Habit added');
        await loadAndRender();
      } catch (err) {
        if (genErrorEl) { genErrorEl.textContent = 'Failed to save: ' + err.message; genErrorEl.classList.add('is-visible'); }
      }
    });
  }
});

// ── History Calendar (issue #829 + #830) ──────────────────────────────────────

let hcalMonth = null;          // Date at 1st of displayed month (null = current)
let hcalWeekStart = null;      // Date of Monday of displayed week (null = current)
let hcalSelectedDate = null;   // ISO string of the selected day (persistent)
let hcalLogsByDate = {};       // { dateStr: Set(habitId) }
let hcalFetchedRange = null;   // 'from|to' key for the last fetch
let _hcalInitialized = false;
let hcalFilterHabitId = null;  // null = All Habits; number = specific habit ID (issue #830)

const HCAL_MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
];
const HCAL_WEEKDAY_ABBR = ['Mo','Tu','We','Th','Fr','Sa','Su'];
const HCAL_DAY_ABBR = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

function _hcalPad(n) { return String(n).padStart(2, '0'); }

function _hcalISO(d) {
  return d.getFullYear() + '-' + _hcalPad(d.getMonth() + 1) + '-' + _hcalPad(d.getDate());
}

// Compute met/partial/not-met/no-data for one calendar day (AC4).
// Reuses the same per-day log-presence logic as the Habits summary endpoint:
//   - applicable = active habits whose created_at date ≤ dateStr
//   - met     → all applicable habits have a log entry for dateStr
//   - partial → at least one (but not all) applicable habits have a log
//   - not-met → zero applicable habits have logs (but some apply)
//   - no-data → future date OR no habits existed yet on that date
function computeDayStatus(dateStr, habits, logsByDate) {
  const todayStr = bangkokTodayStr();
  if (dateStr > todayStr) return 'no-data';

  const applicable = (habits || []).filter(h => {
    if (h.is_archived) return false;
    if (!h.created_at) return true;
    return h.created_at.slice(0, 10) <= dateStr;
  });
  if (applicable.length === 0) return 'no-data';

  const logsOnDate = logsByDate[dateStr] || new Set();
  const loggedCount = applicable.filter(h => logsOnDate.has(h.id)).length;

  if (loggedCount === applicable.length) return 'met';
  if (loggedCount > 0) return 'partial';
  return 'not-met';
}

function _hcalStatusLabel(status) {
  if (status === 'met') return 'met';
  if (status === 'partial') return 'partial';
  if (status === 'not-met') return 'not met';
  return 'no data';
}

// Compute status for All Habits mode — returns {status, done, total} (issue #830, AC3).
function computeAllHabitsDaySummary(dateStr, habits, logsByDate) {
  const todayStr = bangkokTodayStr();
  if (dateStr > todayStr) return { status: 'no-data', done: 0, total: 0 };

  const applicable = (habits || []).filter(h => {
    if (h.is_archived) return false;
    if (!h.created_at) return true;
    return h.created_at.slice(0, 10) <= dateStr;
  });
  if (applicable.length === 0) return { status: 'no-data', done: 0, total: 0 };

  const logsOnDate = logsByDate[dateStr] || new Set();
  const done = applicable.filter(h => logsOnDate.has(h.id)).length;
  const total = applicable.length;
  const status = done === total ? 'met' : done > 0 ? 'partial' : 'not-met';
  return { status, done, total };
}

// Compute status for a single habit on a given day (issue #830, AC4, AC8).
// Returns 'no-data' when the habit was created after dateStr (AC8).
function computeSingleHabitDayStatus(dateStr, habit, logsByDate) {
  const todayStr = bangkokTodayStr();
  if (dateStr > todayStr) return 'no-data';
  if (habit.is_archived) return 'no-data';
  if (habit.created_at && habit.created_at.slice(0, 10) > dateStr) return 'no-data';
  const logsOnDate = logsByDate[dateStr] || new Set();
  return logsOnDate.has(habit.id) ? 'met' : 'not-met';
}

// Render the filter control for the history calendar (issue #830, AC1/AC2/AC9/AC10).
function renderHcalFilter() {
  const el = document.getElementById('hcal-filter');
  if (!el) return;

  let html = '<button type="button" class="hcal-filter-btn' +
    (hcalFilterHabitId === null ? ' hcal-filter-btn--active' : '') + '"' +
    ' data-habit-id=""' +
    ' aria-pressed="' + (hcalFilterHabitId === null ? 'true' : 'false') + '">' +
    'All Habits</button>';

  (activeHabits || []).forEach(h => {
    const active = hcalFilterHabitId === h.id;
    html += '<button type="button" class="hcal-filter-btn' +
      (active ? ' hcal-filter-btn--active' : '') + '"' +
      ' data-habit-id="' + esc(String(h.id)) + '"' +
      ' aria-pressed="' + (active ? 'true' : 'false') + '">' +
      esc(h.name) + '</button>';
  });

  el.innerHTML = html;

  const buttons = Array.from(el.querySelectorAll('.hcal-filter-btn'));

  buttons.forEach((btn, i) => {
    btn.addEventListener('click', async () => {
      const idAttr = btn.dataset.habitId;
      hcalFilterHabitId = idAttr === '' ? null : Number(idAttr);
      renderHcalFilter();
      renderHabitMonthCal();
      renderHabitWeekStrip();
      if (hcalSelectedDate) await _renderHcalDetail(hcalSelectedDate);
    });

    // Arrow key navigation within the filter group (AC10)
    btn.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        const next = buttons[(i + 1) % buttons.length];
        if (next) next.focus();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const prev = buttons[(i - 1 + buttons.length) % buttons.length];
        if (prev) prev.focus();
      }
    });
  });
}

async function _fetchCalendarRange(from, to) {
  const key = from + '|' + to;
  if (hcalFetchedRange === key) return;
  try {
    const res = await fetch(`/api/habits/logs?from=${from}&to=${to}`);
    if (!res.ok) return;
    const logs = await res.json();
    hcalLogsByDate = {};
    (logs || []).forEach(l => {
      const d = l.logged_date;
      if (!hcalLogsByDate[d]) hcalLogsByDate[d] = new Set();
      hcalLogsByDate[d].add(l.habit_id);
    });
    hcalFetchedRange = key;
  } catch (_) { /* silently ignore */ }
}

function renderHabitMonthCal() {
  const el = document.getElementById('habits-month-cal');
  if (!el) return;

  const now = new Date();
  if (!hcalMonth) hcalMonth = new Date(now.getFullYear(), now.getMonth(), 1);

  const year = hcalMonth.getFullYear();
  const month = hcalMonth.getMonth();
  const today = bangkokToday();
  const todayStr = _hcalISO(today);
  const lastDayNum = new Date(year, month + 1, 0).getDate();
  const firstDow = new Date(year, month, 1).getDay();
  const startOffset = (firstDow + 6) % 7;
  const rows = Math.ceil((startOffset + lastDayNum) / 7);
  const isCurrentMonth = year === now.getFullYear() && month === now.getMonth();

  let html =
    '<div class="hcal-nav">' +
      '<button type="button" id="hcal-month-prev" class="hcal-nav-btn" aria-label="Previous month">&#8249;</button>' +
      '<span class="hcal-month-label">' + HCAL_MONTH_NAMES[month] + ' ' + year + '</span>' +
      '<button type="button" id="hcal-today-btn" class="hcal-nav-btn hcal-nav-btn--today"' +
        (isCurrentMonth ? ' disabled' : '') + '>Today</button>' +
      '<button type="button" id="hcal-month-next" class="hcal-nav-btn" aria-label="Next month"' +
        (isCurrentMonth ? ' disabled' : '') + '>&#8250;</button>' +
    '</div>' +
    '<div class="hcal-grid" role="grid" aria-label="' + HCAL_MONTH_NAMES[month] + ' ' + year + '">';

  HCAL_WEEKDAY_ABBR.forEach(abbr => {
    html += '<div class="hcal-weekday" role="columnheader">' + esc(abbr) + '</div>';
  });

  let dayNum = 1;
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < 7; col++) {
      const cellIdx = row * 7 + col;
      if (cellIdx < startOffset || dayNum > lastDayNum) {
        html += '<div class="hcal-cell hcal-cell--no-data" aria-hidden="true"></div>';
      } else {
        const dStr = year + '-' + _hcalPad(month + 1) + '-' + _hcalPad(dayNum);
        let status, countOverlay = '';
        if (hcalFilterHabitId === null) {
          const summary = computeAllHabitsDaySummary(dStr, activeHabits, hcalLogsByDate);
          status = summary.status;
          if (status !== 'no-data') {
            countOverlay = '<span class="hcal-day-count">' + summary.done + '/' + summary.total + '</span>';
          }
        } else {
          const habit = activeHabits.find(h => h.id === hcalFilterHabitId);
          status = habit ? computeSingleHabitDayStatus(dStr, habit, hcalLogsByDate) : 'no-data';
        }
        const isToday = dStr === todayStr;
        const isSel = dStr === hcalSelectedDate;
        const isNoData = status === 'no-data';

        let cls = 'hcal-cell';
        if (isNoData) cls += ' hcal-cell--no-data';
        else if (status === 'met') cls += ' hcal-cell--met';
        else if (status === 'partial') cls += ' hcal-cell--partial';
        else cls += ' hcal-cell--not-met';
        if (isToday && !isNoData) cls += ' hcal-cell--today';
        if (isSel) cls += ' is-selected';

        const dateObj = new Date(year, month, dayNum);
        const fullDate = dateObj.toLocaleDateString('en-US', { month: 'long', day: 'numeric' });
        const ariaLabel = fullDate + ', ' + _hcalStatusLabel(status);

        html +=
          '<button type="button" class="' + cls + '"' +
          ' data-date="' + dStr + '"' +
          ' tabindex="' + (isNoData ? '-1' : '0') + '"' +
          ' aria-label="' + esc(ariaLabel) + '"' +
          ' aria-pressed="' + (isSel ? 'true' : 'false') + '"' +
          ' role="gridcell">' +
          '<span class="hcal-day-num">' + dayNum + '</span>' +
          countOverlay +
          '</button>';
        dayNum++;
      }
    }
  }

  html += '</div>';
  el.innerHTML = html;

  const prevBtn = document.getElementById('hcal-month-prev');
  const nextBtn = document.getElementById('hcal-month-next');
  const todayBtn = document.getElementById('hcal-today-btn');

  if (prevBtn) prevBtn.addEventListener('click', async () => {
    hcalMonth = new Date(year, month - 1, 1);
    await _refreshHabitCal();
  });
  if (nextBtn) nextBtn.addEventListener('click', async () => {
    hcalMonth = new Date(year, month + 1, 1);
    await _refreshHabitCal();
  });
  if (todayBtn) todayBtn.addEventListener('click', async () => {
    const t = new Date();
    hcalMonth = new Date(t.getFullYear(), t.getMonth(), 1);
    await _refreshHabitCal();
  });

  const grid = el.querySelector('.hcal-grid');
  if (grid) {
    grid.addEventListener('click', e => {
      const cell = e.target.closest('.hcal-cell:not(.hcal-cell--no-data)');
      if (!cell) return;
      const date = cell.getAttribute('data-date');
      if (date) _hcalSelectDate(date);
    });

    grid.addEventListener('keydown', e => {
      const cell = e.target.closest('.hcal-cell:not(.hcal-cell--no-data)');
      if (!cell) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const date = cell.getAttribute('data-date');
        if (date) _hcalSelectDate(date);
        return;
      }
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const cells = Array.from(grid.querySelectorAll('.hcal-cell:not(.hcal-cell--no-data)'));
      const idx = cells.indexOf(cell);
      const delta = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 7, ArrowUp: -7 }[e.key];
      const newIdx = idx + delta;
      if (newIdx >= 0 && newIdx < cells.length) cells[newIdx].focus();
    });
  }
}

function renderHabitWeekStrip() {
  const el = document.getElementById('habits-week-strip');
  if (!el) return;

  const today = bangkokToday();
  const todayStr = _hcalISO(today);

  if (!hcalWeekStart) {
    const dow = today.getDay();
    const diff = dow === 0 ? -6 : 1 - dow;
    hcalWeekStart = new Date(today.getFullYear(), today.getMonth(), today.getDate() + diff);
  }

  const weekDays = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(hcalWeekStart.getFullYear(), hcalWeekStart.getMonth(), hcalWeekStart.getDate() + i);
    weekDays.push(d);
  }

  const MONTHS_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const fromDate = weekDays[0];
  const toDate = weekDays[6];
  const label = fromDate.getMonth() === toDate.getMonth()
    ? MONTHS_SHORT[fromDate.getMonth()] + ' ' + fromDate.getDate() + '–' + toDate.getDate()
    : MONTHS_SHORT[fromDate.getMonth()] + ' ' + fromDate.getDate() + ' – ' + MONTHS_SHORT[toDate.getMonth()] + ' ' + toDate.getDate();

  const weekEndStr = _hcalISO(weekDays[6]);
  const isCurrentWeek = _hcalISO(hcalWeekStart) <= todayStr && weekEndStr >= todayStr;

  let html =
    '<div class="hcal-nav">' +
      '<button type="button" id="hcal-strip-prev" class="hcal-nav-btn" aria-label="Previous week">&#8249;</button>' +
      '<span class="hcal-week-label">' + esc(label) + '</span>' +
      '<button type="button" id="hcal-strip-next" class="hcal-nav-btn" aria-label="Next week"' +
        (isCurrentWeek ? ' disabled' : '') + '>&#8250;</button>' +
    '</div>' +
    '<div class="hcal-strip" role="grid" aria-label="' + esc('Week of ' + label) + '">';

  weekDays.forEach(d => {
    const dStr = _hcalISO(d);
    let status, countOverlay = '';
    if (hcalFilterHabitId === null) {
      const summary = computeAllHabitsDaySummary(dStr, activeHabits, hcalLogsByDate);
      status = summary.status;
      if (status !== 'no-data') {
        countOverlay = '<span class="hcal-day-count">' + summary.done + '/' + summary.total + '</span>';
      }
    } else {
      const habit = activeHabits.find(h => h.id === hcalFilterHabitId);
      status = habit ? computeSingleHabitDayStatus(dStr, habit, hcalLogsByDate) : 'no-data';
    }
    const isNoData = status === 'no-data';
    const isToday = dStr === todayStr;
    const isSel = dStr === hcalSelectedDate;

    let cls = 'hcal-strip-cell';
    if (isNoData) cls += ' hcal-strip-cell--no-data hcal-cell--no-data';
    else if (status === 'met') cls += ' hcal-cell--met';
    else if (status === 'partial') cls += ' hcal-cell--partial';
    else cls += ' hcal-cell--not-met';
    if (isToday && !isNoData) cls += ' hcal-cell--today';
    if (isSel) cls += ' is-selected';

    const ariaLabel = d.toLocaleDateString('en-US', { month: 'long', day: 'numeric' }) + ', ' + _hcalStatusLabel(status);

    html +=
      '<button type="button" class="' + cls + '"' +
      ' data-date="' + dStr + '"' +
      ' tabindex="' + (isNoData ? '-1' : '0') + '"' +
      ' aria-label="' + esc(ariaLabel) + '"' +
      ' aria-pressed="' + (isSel ? 'true' : 'false') + '"' +
      ' role="gridcell">' +
      '<span class="hcal-strip-day-name">' + HCAL_DAY_ABBR[d.getDay()].slice(0, 1) + '</span>' +
      '<span class="hcal-strip-day-num">' + d.getDate() + '</span>' +
      countOverlay +
      '</button>';
  });

  html += '</div>';
  el.innerHTML = html;

  const prevBtn = document.getElementById('hcal-strip-prev');
  const nextBtn = document.getElementById('hcal-strip-next');

  if (prevBtn) prevBtn.addEventListener('click', async () => {
    hcalWeekStart = new Date(hcalWeekStart.getFullYear(), hcalWeekStart.getMonth(), hcalWeekStart.getDate() - 7);
    await _refreshHabitCal();
  });
  if (nextBtn) nextBtn.addEventListener('click', async () => {
    hcalWeekStart = new Date(hcalWeekStart.getFullYear(), hcalWeekStart.getMonth(), hcalWeekStart.getDate() + 7);
    await _refreshHabitCal();
  });

  const strip = el.querySelector('.hcal-strip');
  if (strip) {
    strip.addEventListener('click', e => {
      const cell = e.target.closest('.hcal-strip-cell:not(.hcal-strip-cell--no-data)');
      if (!cell) return;
      const date = cell.getAttribute('data-date');
      if (date) _hcalSelectDate(date);
    });

    strip.addEventListener('keydown', e => {
      const cell = e.target.closest('.hcal-strip-cell:not(.hcal-strip-cell--no-data)');
      if (!cell) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const date = cell.getAttribute('data-date');
        if (date) _hcalSelectDate(date);
        return;
      }
      if (!['ArrowLeft','ArrowRight'].includes(e.key)) return;
      e.preventDefault();
      const cells = Array.from(strip.querySelectorAll('.hcal-strip-cell:not(.hcal-strip-cell--no-data)'));
      const idx = cells.indexOf(cell);
      const delta = e.key === 'ArrowRight' ? 1 : -1;
      const newIdx = idx + delta;
      if (newIdx >= 0 && newIdx < cells.length) cells[newIdx].focus();
    });
  }
}

// Persistent highlight on click — sets is-selected on the clicked cell and
// reveals log entries without hiding other cells (AC6, AC7).
function _hcalSelectDate(dateStr) {
  hcalSelectedDate = dateStr;

  // Update month cal: toggle is-selected on all cells, never hide siblings (AC7)
  const monthEl = document.getElementById('habits-month-cal');
  if (monthEl) {
    monthEl.querySelectorAll('[data-date]').forEach(c => {
      const sel = c.getAttribute('data-date') === dateStr;
      c.classList.toggle('is-selected', sel);
      c.setAttribute('aria-pressed', sel ? 'true' : 'false');
    });
  }

  // Update week strip
  const stripEl = document.getElementById('habits-week-strip');
  if (stripEl) {
    stripEl.querySelectorAll('[data-date]').forEach(c => {
      const sel = c.getAttribute('data-date') === dateStr;
      c.classList.toggle('is-selected', sel);
      c.setAttribute('aria-pressed', sel ? 'true' : 'false');
    });
  }

  _renderHcalDetail(dateStr);
}

async function _renderHcalDetail(dateStr) {
  const detail = document.getElementById('habits-cal-detail');
  const content = document.getElementById('habits-cal-detail-content');
  if (!detail || !content) return;

  // Compute status respecting the current filter (issue #830, AC6)
  let status;
  if (hcalFilterHabitId === null) {
    status = computeDayStatus(dateStr, activeHabits, hcalLogsByDate);
  } else {
    const habit = activeHabits.find(h => h.id === hcalFilterHabitId);
    status = habit ? computeSingleHabitDayStatus(dateStr, habit, hcalLogsByDate) : 'no-data';
  }

  const dateObj = new Date(dateStr + 'T00:00:00');
  const MONTHS_D = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const DAYS_D = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const dateLabel = DAYS_D[dateObj.getDay()] + ', ' + MONTHS_D[dateObj.getMonth()] + ' ' + dateObj.getDate();

  const badgeClass = status === 'met' ? 'hcal-detail-status-badge--met'
    : status === 'partial' ? 'hcal-detail-status-badge--partial'
    : 'hcal-detail-status-badge--not-met';
  const badgeText = status === 'met' ? 'Met' : status === 'partial' ? 'Partial' : 'Not met';

  content.innerHTML = '<div class="hcal-detail-hdr">' +
    '<span class="hcal-detail-date">' + esc(dateLabel) + '</span>' +
    (status !== 'no-data'
      ? '<span class="hcal-detail-status-badge ' + esc(badgeClass) + '">' + esc(badgeText) + '</span>'
      : '') +
    '</div><div class="hcal-log-empty">Loading…</div>';

  detail.style.display = '';
  detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  // Fetch logs for this specific date
  let dayLogs = [];
  try {
    const res = await fetch(`/api/habits/logs?from=${dateStr}&to=${dateStr}`);
    if (res.ok) dayLogs = await res.json();
  } catch (_) { /* ignore */ }

  // Filter logs by the selected habit if in single-habit mode (issue #830, AC6)
  if (hcalFilterHabitId !== null) {
    dayLogs = dayLogs.filter(l => l.habit_id === hcalFilterHabitId);
  }

  const habitMap = {};
  activeHabits.forEach(h => { habitMap[h.id] = h; });

  let logsHtml = '';
  if (dayLogs.length > 0) {
    dayLogs.forEach(log => {
      const habit = habitMap[log.habit_id];
      const iconHTML = habit ? habitIconHTML(habit.icon, habit.color, 22) : '';
      const name = habit ? esc(habit.name) : 'Unknown habit';
      logsHtml += '<div class="hcal-log-entry">' + iconHTML + '<span>' + name + '</span></div>';
    });
  } else {
    logsHtml = '<div class="hcal-log-empty">No logs for this day</div>';
  }

  content.innerHTML = '<div class="hcal-detail-hdr">' +
    '<span class="hcal-detail-date">' + esc(dateLabel) + '</span>' +
    (status !== 'no-data'
      ? '<span class="hcal-detail-status-badge ' + esc(badgeClass) + '">' + esc(badgeText) + '</span>'
      : '') +
    '</div>' + logsHtml;
}

async function _refreshHabitCal() {
  // Invalidate cached range so the next fetch is fresh
  hcalFetchedRange = null;

  const year = hcalMonth ? hcalMonth.getFullYear() : new Date().getFullYear();
  const month = hcalMonth ? hcalMonth.getMonth() : new Date().getMonth();
  const lastDay = new Date(year, month + 1, 0).getDate();
  const from = year + '-' + _hcalPad(month + 1) + '-01';
  const to = year + '-' + _hcalPad(month + 1) + '-' + _hcalPad(lastDay);

  await _fetchCalendarRange(from, to);
  renderHcalFilter();
  renderHabitMonthCal();
  renderHabitWeekStrip();
}

async function initHabitCal() {
  const calSection = document.getElementById('habits-history-cal');
  if (!calSection) return;

  if (!_hcalInitialized) {
    const now = new Date();
    hcalMonth = new Date(now.getFullYear(), now.getMonth(), 1);

    const today = bangkokToday();
    const dow = today.getDay();
    const diff = dow === 0 ? -6 : 1 - dow;
    hcalWeekStart = new Date(today.getFullYear(), today.getMonth(), today.getDate() + diff);
    _hcalInitialized = true;
  }

  const year = hcalMonth.getFullYear();
  const month = hcalMonth.getMonth();
  const lastDay = new Date(year, month + 1, 0).getDate();
  const from = year + '-' + _hcalPad(month + 1) + '-01';
  const to = year + '-' + _hcalPad(month + 1) + '-' + _hcalPad(lastDay);

  await _fetchCalendarRange(from, to);
  calSection.style.display = '';
  renderHcalFilter();
  renderHabitMonthCal();
  renderHabitWeekStrip();
}

// ── Habit detail panel (issue #831) ──────────────────────────────────────────

let _detailHabitId = null;

function closeHabitDetail() {
  const panel = document.getElementById('habit-detail-panel');
  if (panel) panel.style.display = 'none';
  _detailHabitId = null;
}

async function openHabitDetail(habitId, habitObj) {
  const panel = document.getElementById('habit-detail-panel');
  if (!panel) return;

  _detailHabitId = habitId;

  // Show panel with loading state
  panel.style.display = '';
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const loadingEl = document.getElementById('detail-loading');
  const contentEl = document.getElementById('detail-content');
  const nameEl = document.getElementById('detail-panel-habit-name');
  const iconEl = document.getElementById('detail-panel-icon');

  if (loadingEl) loadingEl.style.display = '';
  if (contentEl) contentEl.style.display = 'none';

  // Show habit name and icon immediately from local data
  if (habitObj) {
    if (nameEl) nameEl.textContent = habitObj.name || '—';
    if (iconEl) iconEl.innerHTML = habitIconHTML(habitObj.icon, habitObj.color, 28);
  }

  try {
    const today = bangkokTodayStr();
    const ninetyDaysAgo = isoDate(new Date(bangkokToday().getTime() - 90 * 86400000));

    const [summaryRes, logsRes] = await Promise.all([
      fetch(`/api/habits/${habitId}/summary`),
      fetch(`/api/habits/logs?habit_id=${habitId}&from=${ninetyDaysAgo}&to=${today}`),
    ]);

    // Abort if user opened a different panel while fetching
    if (_detailHabitId !== habitId) return;

    if (!summaryRes.ok) throw new Error(`Summary fetch failed (${summaryRes.status})`);
    const summary = await summaryRes.json();

    let logs = [];
    if (logsRes.ok) logs = await logsRes.json();

    renderHabitDetail(summary, logs);
  } catch (e) {
    if (_detailHabitId !== habitId) return;
    if (loadingEl) loadingEl.textContent = 'Failed to load habit details.';
  }
}

function renderHabitDetail(summary, logs) {
  const loadingEl = document.getElementById('detail-loading');
  const contentEl = document.getElementById('detail-content');
  const nameEl = document.getElementById('detail-panel-habit-name');
  const iconEl = document.getElementById('detail-panel-icon');

  if (!contentEl) return;

  const habit = summary.habit || {};
  if (nameEl) nameEl.textContent = habit.name || '—';
  if (iconEl) iconEl.innerHTML = habitIconHTML(habit.icon, habit.color, 28);

  // Stats
  const streakEl = document.getElementById('detail-current-streak');
  const longestEl = document.getElementById('detail-longest-streak');
  const consistencyEl = document.getElementById('detail-consistency');
  const consistencySubEl = document.getElementById('detail-consistency-sub');

  if (streakEl) streakEl.textContent = summary.current_streak ?? 0;
  if (longestEl) longestEl.textContent = summary.longest_streak ?? 0;
  if (consistencyEl) consistencyEl.textContent = (summary.consistency_pct ?? 0) + '%';
  if (consistencySubEl) {
    const checked = summary.days_checked ?? 0;
    const total = summary.days_total ?? 30;
    consistencySubEl.textContent = `${checked}/${total} days`;
  }

  // Log history
  const historyList = document.getElementById('detail-history-list');
  const historyEmpty = document.getElementById('detail-history-empty');
  if (historyList) {
    historyList.innerHTML = '';
    if (!logs || logs.length === 0) {
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'detail-history-empty';
      emptyDiv.textContent = 'No log entries yet — start logging to track your progress!';
      historyList.appendChild(emptyDiv);
    } else {
      logs.forEach(log => {
        const entry = document.createElement('div');
        entry.className = 'detail-history-entry';
        const dateSpan = document.createElement('span');
        dateSpan.className = 'detail-history-date';
        dateSpan.textContent = log.logged_date || log.log_date || '—';
        entry.appendChild(dateSpan);
        if (log.value != null && log.value !== 1) {
          const valSpan = document.createElement('span');
          valSpan.className = 'detail-history-val';
          valSpan.textContent = log.value;
          entry.appendChild(valSpan);
        }
        if (log.notes) {
          const noteSpan = document.createElement('span');
          noteSpan.className = 'detail-history-note';
          noteSpan.textContent = log.notes;
          entry.appendChild(noteSpan);
        }
        historyList.appendChild(entry);
      });
    }
  }

  // Show content
  if (loadingEl) loadingEl.style.display = 'none';
  contentEl.style.display = '';

  // Edit/Archive buttons — reuse the same edit/archive flows the day-grid and
  // weekly-list "⋯" menus already use, so the detail panel isn't a dead end.
  const editBtn = document.getElementById('detail-edit-btn');
  const archiveBtn = document.getElementById('detail-archive-btn');
  if (editBtn) {
    editBtn.onclick = (e) => {
      e.preventDefault();
      closeHabitDetail();
      openHabitForm(habit);
    };
  }
  if (archiveBtn) {
    archiveBtn.onclick = (e) => {
      e.preventDefault();
      if (habit.id && confirm(`Archive "${habit.name}"? You can unarchive it later.`)) {
        closeHabitDetail();
        archiveHabit(habit.id);
      }
    };
  }
}

function _wireDetailTriggerKeydown(el) {
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      el.click();
    }
  });
}

function _wireDetailTriggers() {
  // Wire habit-name clicks (and Enter/Space for keyboard users) in daily grid
  document.querySelectorAll('.habit-name-text[data-detail-trigger]').forEach(el => {
    el.addEventListener('click', () => {
      const row = el.closest('[data-habit-id]');
      const hid = row && row.dataset.habitId;
      if (!hid) return;
      const habit = activeHabits.find(h => String(h.id) === hid) ||
                    archivedHabits.find(h => String(h.id) === hid);
      openHabitDetail(hid, habit || null);
    });
    _wireDetailTriggerKeydown(el);
  });
  // Wire habit-name clicks (and Enter/Space for keyboard users) in weekly habits list
  document.querySelectorAll('.week-habit-name[data-detail-trigger]').forEach(el => {
    el.addEventListener('click', () => {
      const row = el.closest('[id^="habit-week-row-"]');
      const hid = row && row.id.replace('habit-week-row-', '');
      if (!hid) return;
      const habit = activeHabits.find(h => String(h.id) === hid) ||
                    archivedHabits.find(h => String(h.id) === hid);
      openHabitDetail(hid, habit || null);
    });
    _wireDetailTriggerKeydown(el);
  });
}

// Close panel button
document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('detail-panel-close');
  if (closeBtn) closeBtn.addEventListener('click', closeHabitDetail);
});

// ── Habit Insights ────────────────────────────────────────────────────────────

async function loadInsights() {
  const el = document.getElementById('insights-body');
  if (!el) return;
  el.innerHTML = '<div class="insights-loading"><span class="insights-spinner"></span> Loading…</div>';
  try {
    const res = await fetch('/api/habits/insights');
    if (!res.ok) {
      el.innerHTML = `<div class="insights-error" role="alert">Error ${res.status}: could not load insights.</div>`;
      return;
    }
    const data = await res.json();
    if (data.status === 'not_enough_data') {
      el.innerHTML =
        '<div class="insights-building">' +
          '<p class="insights-building-msg">Still learning your patterns.</p>' +
          '<p class="insights-building-sub">Keep logging — insights appear once there\'s enough data to detect a reliable association.</p>' +
        '</div>';
      return;
    }
    const cards = (data.insights || []).map(ins => {
      const r = typeof ins.coefficient === 'number' ? ins.coefficient : 0;
      const pct = Math.min(100, Math.round(Math.abs(r) * 100));
      const dir = r >= 0 ? 'positive' : 'negative';
      return `<div class="insight-card">
  <div class="insight-line">${ins.summary || ''}</div>
  <div class="insight-indicator">
    <div class="insight-bar-outer" title="r = ${r.toFixed(2)}">
      <div class="insight-bar-fill insight-bar-${dir}" style="width:${pct}%"></div>
    </div>
    <span class="insight-coeff">r = ${r.toFixed(2)}</span>
  </div>
</div>`;
    });
    el.innerHTML = cards.join('') || '<div class="insights-empty">No confident associations found yet.</div>';
  } catch (err) {
    if (el) el.innerHTML = `<div class="insights-error" role="alert">Failed to load insights: ${err.message}</div>`;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

window.addEventListener('userReady', () => {
  loadAndRender();
  loadInsights();
});

window.addEventListener('userChanged', () => {
  loadAndRender();
  loadInsights();
});
