function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

const MA_COLOR = '#16a34a';
const DAILY_COLOR = '#9ca3af';

let allEntries = [];
let currentRange = '30d';
let showAvg = true;
let weightChart = null;

function readUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const r = params.get('range');
  if (['7d', '30d', '90d', 'all'].includes(r)) currentRange = r;
  if (params.get('avg') === 'false') showAvg = false;
}

function updateUrl() {
  const params = new URLSearchParams(window.location.search);
  params.set('range', currentRange);
  params.set('avg', showAvg ? 'true' : 'false');
  history.replaceState(null, '', '?' + params.toString());
}

function syncRangeButtons() {
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.range === currentRange);
  });
}

function syncAvgCheckbox() {
  const cb = document.getElementById('avg-toggle');
  if (cb) cb.checked = showAvg;
}

function filterByRange(entries, range) {
  if (range === 'all') return entries;
  const days = { '7d': 7, '30d': 30, '90d': 90 }[range];
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - (days - 1));
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return entries.filter(e => e.recorded_date >= cutoffStr);
}

function computeMovingAverage(visibleSorted, allSorted) {
  const dateToWeight = {};
  for (const e of allSorted) dateToWeight[e.recorded_date] = e.weight_kg;

  return visibleSorted.map(entry => {
    const base = new Date(entry.recorded_date + 'T00:00:00');
    const windowWeights = [];
    for (let d = 6; d >= 0; d--) {
      const check = new Date(base);
      check.setDate(check.getDate() - d);
      const key = check.toISOString().slice(0, 10);
      if (dateToWeight[key] !== undefined) windowWeights.push(dateToWeight[key]);
    }
    if (windowWeights.length < 3) return null;
    const avg = windowWeights.reduce((a, b) => a + b, 0) / windowWeights.length;
    return Math.round(avg * 100) / 100;
  });
}

function renderChart(entries) {
  const source = entries.length > 0 ? entries : MOCK_WEIGHT_ENTRIES;
  const allSorted = source.slice().sort((a, b) => a.recorded_date.localeCompare(b.recorded_date));
  const visibleSorted = filterByRange(allSorted, currentRange);

  const labels = visibleSorted.map(e => e.recorded_date);
  const weights = visibleSorted.map(e => e.weight_kg);

  const pointRadii = weights.map((_, i) => i === weights.length - 1 ? 7 : 3);
  const pointHoverRadii = weights.map((_, i) => i === weights.length - 1 ? 9 : 5);

  const maValues = computeMovingAverage(visibleSorted, allSorted);
  const effectiveShowAvg = showAvg && visibleSorted.length >= 7;

  const allValues = [...weights, ...maValues.filter(v => v !== null)];
  const padding = 0.5;
  const minY = allValues.length ? Math.min(...allValues) - padding : undefined;
  const maxY = allValues.length ? Math.max(...allValues) + padding : undefined;

  if (weightChart) {
    weightChart.data.labels = labels;
    weightChart.data.datasets[0].data = weights;
    weightChart.data.datasets[0].pointRadius = pointRadii;
    weightChart.data.datasets[0].pointHoverRadius = pointHoverRadii;
    weightChart.data.datasets[1].data = maValues;
    weightChart.data.datasets[1].hidden = !effectiveShowAvg;
    if (minY !== undefined) weightChart.options.scales.y.min = minY;
    if (maxY !== undefined) weightChart.options.scales.y.max = maxY;
    weightChart.update();
    return;
  }

  const ctx = document.getElementById('weight-chart').getContext('2d');
  weightChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Daily',
          data: weights,
          showLine: false,
          pointRadius: pointRadii,
          pointHoverRadius: pointHoverRadii,
          pointBackgroundColor: DAILY_COLOR,
          pointBorderColor: DAILY_COLOR,
          borderColor: DAILY_COLOR,
        },
        {
          label: '7-day average',
          data: maValues,
          borderColor: MA_COLOR,
          backgroundColor: 'transparent',
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 0,
          hidden: !effectiveShowAvg,
          spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        x: { title: { display: true, text: 'Date' } },
        y: {
          title: { display: true, text: 'Weight (kg)' },
          min: minY,
          max: maxY,
        },
      },
    },
  });
}

function renderEntries(entries) {
  const list = document.getElementById('entry-list');
  if (entries.length === 0) {
    list.innerHTML = '<li class="empty">No entries yet.</li>';
    return;
  }
  list.innerHTML = entries
    .slice()
    .sort((a, b) => b.recorded_date.localeCompare(a.recorded_date))
    .map(e => `
      <li>
        <span class="entry-date">${e.recorded_date}</span>
        <span class="entry-weight">${e.weight_kg} kg</span>
        <button class="entry-delete" data-id="${e.id}" type="button">Delete</button>
      </li>`)
    .join('');

  list.querySelectorAll('.entry-delete').forEach(btn => {
    btn.addEventListener('click', () => deleteEntry(btn.dataset.id));
  });
}

function showApiError(msg) {
  const el = document.getElementById('api-error');
  if (el) el.textContent = msg;
}

function clearApiError() {
  showApiError('');
}

async function loadAndRender() {
  const userId = document.getElementById('user-select').value;
  if (!userId) return;
  clearApiError();
  try {
    const res = await fetch(`/api/weight?user_id=${encodeURIComponent(userId)}`);
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    allEntries = await res.json();
    renderEntries(allEntries);
    renderChart(allEntries);
  } catch (e) {
    showApiError('Unable to load data: ' + e.message);
  }
}

async function deleteEntry(entryId) {
  clearApiError();
  try {
    const res = await fetch(`/api/weight/${encodeURIComponent(entryId)}`, { method: 'DELETE' });
    if (res.status === 404) throw new Error('Entry not found');
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    await loadAndRender();
  } catch (e) {
    showApiError('Delete failed: ' + e.message);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  readUrlParams();

  const userSelect = document.getElementById('user-select');
  const form = document.getElementById('weight-form');
  const weightInput = document.getElementById('weight-input');
  const dateInput = document.getElementById('date-input');
  const errorMsg = document.getElementById('weight-error');

  dateInput.value = todayISO();

  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentRange = btn.dataset.range;
      updateUrl();
      syncRangeButtons();
      renderChart(allEntries);
    });
  });
  syncRangeButtons();

  const avgToggle = document.getElementById('avg-toggle');
  avgToggle.addEventListener('change', () => {
    showAvg = avgToggle.checked;
    updateUrl();
    renderChart(allEntries);
  });
  syncAvgCheckbox();

  // Load users into selector
  try {
    const res = await fetch('/api/users');
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const users = await res.json();
    userSelect.innerHTML = users
      .map(u => `<option value="${u.id}">${u.name}</option>`)
      .join('');
  } catch (e) {
    userSelect.innerHTML = '<option value="">Failed to load users</option>';
    showApiError('Unable to load users: ' + e.message);
    return;
  }

  const addUserOpt = document.createElement('option');
  addUserOpt.value = '__add__';
  addUserOpt.textContent = '+ Add user...';
  userSelect.appendChild(addUserOpt);

  let prevUserId = userSelect.value;

  await loadAndRender();

  userSelect.addEventListener('change', () => {
    if (userSelect.value === '__add__') {
      userSelect.value = prevUserId;
      if (typeof window.buildAddUserModal === 'function') {
        window.buildAddUserModal(function (newUser) {
          fetch('/api/users')
            .then(r => r.json())
            .then(freshUsers => {
              userSelect.innerHTML = freshUsers
                .map(u => `<option value="${u.id}"${u.id === newUser.id ? ' selected' : ''}>${u.name}</option>`)
                .join('') + '<option value="__add__">+ Add user...</option>';
              prevUserId = newUser.id;
              loadAndRender();
            })
            .catch(() => {});
        });
      }
      return;
    }
    prevUserId = userSelect.value;
    loadAndRender();
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    errorMsg.textContent = '';
    clearApiError();

    const raw = weightInput.value.trim();
    if (raw === '' || isNaN(Number(raw)) || Number(raw) <= 0) {
      errorMsg.textContent = 'Please enter a valid weight in kg.';
      weightInput.focus();
      return;
    }

    const userId = userSelect.value;
    if (!userId) {
      errorMsg.textContent = 'Please select a user.';
      return;
    }

    try {
      const res = await fetch(`/api/weight?user_id=${encodeURIComponent(userId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          weight_kg: Number(raw),
          recorded_date: dateInput.value || todayISO(),
        }),
      });

      if (res.status === 409) {
        errorMsg.textContent = 'You already have an entry for this date — delete it first.';
        return;
      }

      if (!res.ok) throw new Error(`Server error ${res.status}`);

      form.reset();
      dateInput.value = todayISO();
      await loadAndRender();
    } catch (e) {
      showApiError('Failed to save entry: ' + e.message);
    }
  });
});
