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

function chartData(entries) {
  const source = entries.length > 0 ? entries : MOCK_WEIGHT_ENTRIES;
  const sorted = source.slice().sort((a, b) => a.date.localeCompare(b.date));
  return {
    labels: sorted.map(e => e.date),
    weights: sorted.map(e => e.weight),
  };
}

let weightChart = null;

function renderChart(entries) {
  const { labels, weights } = chartData(entries);
  if (weightChart) {
    weightChart.data.labels = labels;
    weightChart.data.datasets[0].data = weights;
    weightChart.update();
    return;
  }
  const ctx = document.getElementById('weight-chart').getContext('2d');
  weightChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Weight (kg)',
        data: weights,
        tension: 0.3,
        fill: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        x: { title: { display: true, text: 'Date' } },
        y: { title: { display: true, text: 'Weight (kg)' } },
      },
    },
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('weight-form');
  const weightInput = document.getElementById('weight-input');
  const dateInput = document.getElementById('date-input');
  const errorMsg = document.getElementById('weight-error');

  dateInput.value = todayISO();

  const entries = loadEntries();
  renderEntries(entries);
  renderChart(entries);

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
    renderChart(entries);
    form.reset();
    dateInput.value = todayISO();
  });
});
