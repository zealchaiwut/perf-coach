function getLocalDateString() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function getLocalTimeString() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return `${hh}:${min} (${tz})`;
}

function scheduleMidnightRefresh() {
  const now = new Date();
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const msUntilMidnight = tomorrow - now;
  const timer = setTimeout(() => {
    if (currentUserId) loadAndRender(currentUserId);
  }, msUntilMidnight);
  window.addEventListener('pagehide', () => clearTimeout(timer), { once: true });
}

let currentUserId = null;
let todayLogs = [];
let lastFetchedDate = null;
let lastFetchedAt = null;

function showError(msg) {
  const el = document.getElementById('api-error');
  if (el) el.textContent = msg;
}

function clearError() { showError(''); }

async function loadAndRender(userId) {
  currentUserId = userId;
  const today = getLocalDateString();
  clearError();
  try {
    const [habitsRes, logsRes] = await Promise.all([
      fetch('/api/habits'),
      fetch(`/api/habits/logs?from=${today}&to=${today}`),
    ]);
    if (!habitsRes.ok) throw new Error(`Server error ${habitsRes.status}`);
    if (!logsRes.ok) throw new Error(`Server error ${logsRes.status}`);
    const habits = await habitsRes.json();
    todayLogs = await logsRes.json();
    lastFetchedDate = today;
    lastFetchedAt = Date.now();
    render(habits);
    fetchAllStats(habits, userId);
    updateRefreshTimestamp();
  } catch (e) {
    showError('Unable to load habits: ' + e.message);
  }
}

function updateRefreshTimestamp() {
  const el = document.getElementById('habits-last-refreshed');
  if (el) el.textContent = `Last refreshed: ${getLocalTimeString()}`;
}

function checkDayRollover() {
  if (!currentUserId) return;
  const today = getLocalDateString();
  const staleFetch = lastFetchedAt && (Date.now() - lastFetchedAt) > 5 * 60 * 1000;
  if (today !== lastFetchedDate || staleFetch) {
    loadAndRender(currentUserId);
  }
}

function streakIcon(streak) {
  if (streak >= 100) return '🔥🔥🔥';
  if (streak >= 30) return '🔥🔥';
  if (streak >= 7) return '🔥';
  return '🔥';
}

function renderStreakEl(el, data) {
  if (!data || data.streak === 0) {
    if (data && data.days_completed === 0) {
      el.textContent = 'No streak yet';
      el.className = 'habit-streak streak-none';
    } else {
      el.textContent = '—';
      el.className = 'habit-streak streak-zero';
    }
    return;
  }
  el.textContent = `${streakIcon(data.streak)} ${data.streak}`;
  el.className = 'habit-streak';
}

function renderRateEl(el, data) {
  if (!data || data.days_completed === 0) {
    el.textContent = '—';
    el.className = 'habit-rate rate-grey';
    return;
  }
  const pct = Math.round(data.completion_rate * 100);
  el.textContent = `${pct}% (${data.days_completed}/${data.days_total})`;
  if (pct >= 80) {
    el.className = 'habit-rate rate-green';
  } else if (pct >= 50) {
    el.className = 'habit-rate rate-yellow';
  } else {
    el.className = 'habit-rate rate-grey';
  }
}

async function fetchStats(habitId, userId) {
  try {
    const res = await fetch(
      `/api/habits/stats?habit_id=${encodeURIComponent(habitId)}&days=30`
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function fetchAllStats(habits, userId) {
  await Promise.all(habits.map(async habit => {
    const data = await fetchStats(habit.id, userId);
    const row = document.getElementById(`habit-row-${habit.id}`);
    if (!row) return;
    renderStreakEl(row.querySelector('.habit-streak'), data);
    renderRateEl(row.querySelector('.habit-rate'), data);
  }));
}

async function refreshStatsForHabit(habitId) {
  const data = await fetchStats(habitId, currentUserId);
  const row = document.getElementById(`habit-row-${habitId}`);
  if (!row) return;
  renderStreakEl(row.querySelector('.habit-streak'), data);
  renderRateEl(row.querySelector('.habit-rate'), data);
}

function render(habits) {
  const list = document.getElementById('habit-list');
  list.innerHTML = '';

  if (habits.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'habit-empty';
    const text = document.createTextNode('No habits yet. ');
    const btn = document.createElement('button');
    btn.className = 'link-btn';
    btn.textContent = '+ Add habit';
    btn.addEventListener('click', openModal);
    empty.appendChild(text);
    empty.appendChild(btn);
    list.appendChild(empty);
    return;
  }

  habits.forEach(habit => {
    const log = todayLogs.find(l => l.habit_id === habit.id);
    const done = !!log;

    const li = document.createElement('li');
    li.className = 'habit-row' + (done ? ' habit-done' : '');
    li.id = `habit-row-${habit.id}`;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = done;
    checkbox.setAttribute('aria-label', 'Mark ' + habit.name + ' as done');
    checkbox.addEventListener('change', () => toggleLog(habit.id, log ? log.id : null, checkbox));

    const name = document.createElement('span');
    name.className = 'habit-name';
    name.textContent = habit.name;

    const streak = document.createElement('span');
    streak.className = 'habit-streak streak-loading';
    streak.textContent = '…';

    const rate = document.createElement('span');
    rate.className = 'habit-rate rate-loading';
    rate.textContent = '…';

    const del = document.createElement('button');
    del.className = 'habit-delete';
    del.textContent = 'Delete';
    del.setAttribute('aria-label', 'Delete ' + habit.name);
    del.addEventListener('click', () => deleteHabit(habit.id));

    li.appendChild(checkbox);
    li.appendChild(name);
    li.appendChild(streak);
    li.appendChild(rate);
    li.appendChild(del);
    list.appendChild(li);
  });
}

async function toggleLog(habitId, logId, checkbox) {
  const today = getLocalDateString();
  clearError();
  if (checkbox.checked) {
    try {
      const res = await fetch('/api/habits/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ habit_id: habitId, logged_date: today }),
      });
      if (!res.ok && res.status !== 409) throw new Error(`Server error ${res.status}`);
    } catch (e) {
      showError('Failed to log habit: ' + e.message);
      checkbox.checked = false;
      return;
    }
  } else {
    if (!logId) return;
    try {
      const res = await fetch(`/api/habits/logs/${encodeURIComponent(logId)}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    } catch (e) {
      showError('Failed to remove log: ' + e.message);
      checkbox.checked = true;
      return;
    }
  }
  try {
    const logsRes = await fetch(
      `/api/habits/logs?from=${today}&to=${today}`
    );
    if (logsRes.ok) todayLogs = await logsRes.json();
  } catch { /* keep stale logs */ }

  const row = document.getElementById(`habit-row-${habitId}`);
  if (row) {
    const newLog = todayLogs.find(l => l.habit_id === habitId);
    if (newLog) {
      row.classList.add('habit-done');
      checkbox.checked = true;
    } else {
      row.classList.remove('habit-done');
      checkbox.checked = false;
    }
  }
  refreshStatsForHabit(habitId);
}

async function deleteHabit(habitId) {
  clearError();
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    await loadAndRender(currentUserId);
  } catch (e) {
    showError('Failed to delete habit: ' + e.message);
  }
}

function openModal() {
  document.getElementById('habit-modal').style.display = 'flex';
  document.getElementById('modal-habit-name').value = '';
  document.getElementById('modal-error').textContent = '';
  document.getElementById('modal-habit-name').focus();
}

function closeModal() {
  document.getElementById('habit-modal').style.display = 'none';
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-habit-btn').addEventListener('click', openModal);
  document.getElementById('modal-cancel').addEventListener('click', closeModal);

  document.getElementById('habit-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('habit-modal')) closeModal();
  });

  document.getElementById('modal-form').addEventListener('submit', async e => {
    e.preventDefault();
    const input = document.getElementById('modal-habit-name');
    const errorEl = document.getElementById('modal-error');
    const name = input.value.trim();
    if (!name) {
      errorEl.textContent = 'Habit name cannot be empty.';
      input.focus();
      return;
    }
    errorEl.textContent = '';
    try {
      const res = await fetch('/api/habits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      closeModal();
      await loadAndRender(currentUserId);
    } catch (e) {
      errorEl.textContent = 'Failed to add habit: ' + e.message;
    }
  });
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') checkDayRollover();
});

window.addEventListener('userReady', e => {
  loadAndRender(e.detail.userId);
  scheduleMidnightRefresh();
});
window.addEventListener('userChanged', e => loadAndRender(e.detail.userId));
