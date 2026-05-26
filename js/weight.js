function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function chartData(entries) {
  const source = entries.length > 0 ? entries : MOCK_WEIGHT_ENTRIES;
  const sorted = source.slice().sort((a, b) => a.recorded_date.localeCompare(b.recorded_date));
  return {
    labels: sorted.map(e => e.recorded_date),
    weights: sorted.map(e => e.weight_kg),
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
    const entries = await res.json();
    renderEntries(entries);
    renderChart(entries);
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
  const userSelect = document.getElementById('user-select');
  const form = document.getElementById('weight-form');
  const weightInput = document.getElementById('weight-input');
  const dateInput = document.getElementById('date-input');
  const errorMsg = document.getElementById('weight-error');

  dateInput.value = todayISO();

  // Load users into selector (AC-5)
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

  // Load entries for initial user (AC-8)
  await loadAndRender();

  // Reload on user change (AC-8)
  userSelect.addEventListener('change', () => loadAndRender());

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
        // AC-7: do not reset form, show specific error
        errorMsg.textContent = 'You already have an entry for this date — delete it first.';
        return;
      }

      if (!res.ok) throw new Error(`Server error ${res.status}`);

      // AC-6: reset form and refresh list + chart
      form.reset();
      dateInput.value = todayISO();
      await loadAndRender();
    } catch (e) {
      showApiError('Failed to save entry: ' + e.message);
    }
  });
});
