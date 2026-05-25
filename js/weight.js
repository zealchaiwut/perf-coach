// MOCK — all state in localStorage, no backend
const STORAGE_KEY = 'perf-coach.weight-entries';

function loadEntries() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveEntries(entries) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

function renderEntries(entries) {
  const list = document.getElementById('entry-list');
  if (entries.length === 0) {
    list.innerHTML = '<li class="empty">No entries yet.</li>';
    return;
  }
  list.innerHTML = entries
    .slice()
    .sort((a, b) => b.date.localeCompare(a.date))
    .map(e => `<li><span class="entry-date">${e.date}</span><span class="entry-weight">${e.weight} kg</span></li>`)
    .join('');
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('weight-form');
  const weightInput = document.getElementById('weight-input');
  const dateInput = document.getElementById('date-input');
  const errorMsg = document.getElementById('weight-error');

  dateInput.value = todayISO();
  renderEntries(loadEntries());

  form.addEventListener('submit', e => {
    e.preventDefault();
    const raw = weightInput.value.trim();

    if (raw === '' || isNaN(Number(raw)) || Number(raw) <= 0) {
      errorMsg.textContent = 'Please enter a valid weight in kg.';
      weightInput.focus();
      return;
    }

    errorMsg.textContent = '';
    const entry = { weight: Number(raw), date: dateInput.value || todayISO() };
    const entries = loadEntries();
    entries.push(entry);
    saveEntries(entries);
    renderEntries(entries);
    form.reset();
    dateInput.value = todayISO();
  });
});
