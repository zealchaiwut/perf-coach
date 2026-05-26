const TODAY = new Date().toISOString().slice(0, 10);

let currentUserId = null;
let todayLogs = [];

function showError(msg) {
  const el = document.getElementById('api-error');
  if (el) el.textContent = msg;
}

function clearError() { showError(''); }

async function loadAndRender(userId) {
  currentUserId = userId;
  clearError();
  try {
    const [habitsRes, logsRes] = await Promise.all([
      fetch(`/api/habits?user_id=${encodeURIComponent(userId)}`),
      fetch(`/api/habits/logs?user_id=${encodeURIComponent(userId)}&from=${TODAY}&to=${TODAY}`),
    ]);
    if (!habitsRes.ok) throw new Error(`Server error ${habitsRes.status}`);
    if (!logsRes.ok) throw new Error(`Server error ${logsRes.status}`);
    const habits = await habitsRes.json();
    todayLogs = await logsRes.json();
    render(habits);
  } catch (e) {
    showError('Unable to load habits: ' + e.message);
  }
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

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = done;
    checkbox.setAttribute('aria-label', 'Mark ' + habit.name + ' as done');
    checkbox.addEventListener('change', () => toggleLog(habit.id, log ? log.id : null, checkbox));

    const name = document.createElement('span');
    name.className = 'habit-name';
    name.textContent = habit.name;

    const del = document.createElement('button');
    del.className = 'habit-delete';
    del.textContent = 'Delete';
    del.setAttribute('aria-label', 'Delete ' + habit.name);
    del.addEventListener('click', () => deleteHabit(habit.id));

    li.appendChild(checkbox);
    li.appendChild(name);
    li.appendChild(del);
    list.appendChild(li);
  });
}

async function toggleLog(habitId, logId, checkbox) {
  clearError();
  if (checkbox.checked) {
    try {
      const res = await fetch('/api/habits/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ habit_id: habitId, user_id: currentUserId, logged_date: TODAY }),
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
  await loadAndRender(currentUserId);
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
        body: JSON.stringify({ user_id: currentUserId, name }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      closeModal();
      await loadAndRender(currentUserId);
    } catch (e) {
      errorEl.textContent = 'Failed to add habit: ' + e.message;
    }
  });
});

window.addEventListener('userReady', e => loadAndRender(e.detail.userId));
window.addEventListener('userChanged', e => loadAndRender(e.detail.userId));
