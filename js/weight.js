function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function isoDateStr(date) {
  return date.toISOString().slice(0, 10);
}

// Returns ISO week Monday date string for a given YYYY-MM-DD string
function weekMondayStr(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  const day = d.getDay(); // 0=Sun, 1=Mon...6=Sat
  const offset = day === 0 ? -6 : 1 - day;
  const monday = new Date(d);
  monday.setDate(d.getDate() + offset);
  return isoDateStr(monday);
}

function fmtShortDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function renderSummaryCards(entries) {
  const today = todayISO();

  // === Card 1: This week avg ===
  const thisMonday = weekMondayStr(today);
  const thisSundayDate = new Date(thisMonday + 'T00:00:00');
  thisSundayDate.setDate(thisSundayDate.getDate() + 6);
  const thisSunday = isoDateStr(thisSundayDate);

  const prevMondayDate = new Date(thisMonday + 'T00:00:00');
  prevMondayDate.setDate(prevMondayDate.getDate() - 7);
  const prevMonday = isoDateStr(prevMondayDate);
  const prevSundayDate = new Date(prevMondayDate);
  prevSundayDate.setDate(prevMondayDate.getDate() + 6);
  const prevSunday = isoDateStr(prevSundayDate);

  const thisWeekEntries = entries.filter(e => e.recorded_date >= thisMonday && e.recorded_date <= thisSunday);
  const prevWeekEntries = entries.filter(e => e.recorded_date >= prevMonday && e.recorded_date <= prevSunday);

  const avgVal = document.getElementById('card-week-avg-value');
  const avgMeta = document.getElementById('card-week-avg-meta');
  const avgSub = document.getElementById('card-week-avg-sub');

  if (thisWeekEntries.length < 2) {
    avgVal.innerHTML = '<span class="card-need-data">Need more data</span>';
    avgMeta.textContent = '';
    avgSub.textContent = '';
  } else {
    const thisAvg = thisWeekEntries.reduce((s, e) => s + e.weight_kg, 0) / thisWeekEntries.length;
    avgVal.textContent = thisAvg.toFixed(1) + ' kg';
    if (prevWeekEntries.length >= 1) {
      const prevAvg = prevWeekEntries.reduce((s, e) => s + e.weight_kg, 0) / prevWeekEntries.length;
      const diff = thisAvg - prevAvg;
      const isLoss = diff < 0;
      const color = isLoss ? 'var(--color-text-success)' : 'var(--color-text-danger)';
      const arrow = isLoss ? '↓' : '↑';
      avgMeta.innerHTML = `<span style="color:${color}">${arrow} ${Math.abs(diff).toFixed(1)} kg</span>`;
      avgSub.textContent = `last week: ${prevAvg.toFixed(1)} kg`;
    } else {
      avgMeta.textContent = '';
      avgSub.textContent = 'No previous week data';
    }
  }

  // === Card 2: 30-day trend ===
  const thirtyAgoDate = new Date(today + 'T00:00:00');
  thirtyAgoDate.setDate(thirtyAgoDate.getDate() - 29);
  const thirtyAgo = isoDateStr(thirtyAgoDate);

  const window30 = entries
    .filter(e => e.recorded_date >= thirtyAgo && e.recorded_date <= today)
    .sort((a, b) => a.recorded_date.localeCompare(b.recorded_date));

  const trendVal = document.getElementById('card-trend-value');
  const trendMeta = document.getElementById('card-trend-meta');
  const trendSub = document.getElementById('card-trend-sub');

  const uniqueDays30 = new Set(window30.map(e => e.recorded_date)).size;
  if (uniqueDays30 < 14) {
    trendVal.innerHTML = '<span class="card-need-data">Need more data</span>';
    trendMeta.textContent = '';
    trendSub.textContent = '';
  } else {
    const first = window30[0];
    const last = window30[window30.length - 1];
    const change = last.weight_kg - first.weight_kg;
    const isLoss = change < 0;
    const color = isLoss ? 'var(--color-text-success)' : 'var(--color-text-danger)';
    const arrow = isLoss ? '↘' : '↗';
    trendVal.innerHTML = `<span style="color:${color}">${arrow} ${Math.abs(change).toFixed(1)} kg</span>`;
    trendMeta.textContent = `${first.weight_kg} → ${last.weight_kg} kg`;
    trendSub.textContent = `${fmtShortDate(first.recorded_date)} – ${fmtShortDate(last.recorded_date)}`;
  }

  // === Card 3: Days logged ===
  const loggedDays = new Set(
    entries
      .filter(e => e.recorded_date >= thisMonday && e.recorded_date <= thisSunday)
      .map(e => e.recorded_date)
  );

  const daysVal = document.getElementById('card-days-value');
  const daysDots = document.getElementById('card-days-dots');
  const daysSub = document.getElementById('card-days-sub');

  daysVal.textContent = `${loggedDays.size} / 7`;

  const CHECK_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  const monday = new Date(thisMonday + 'T00:00:00');
  const dots = [];
  for (let i = 0; i < 7; i++) {
    const dayDate = new Date(monday);
    dayDate.setDate(monday.getDate() + i);
    const dayStr = isoDateStr(dayDate);
    const logged = loggedDays.has(dayStr);
    const isToday = dayStr === today;
    const isPast = dayStr < today;
    let cls, inner;
    if (logged) {
      cls = 'day-dot logged';
      inner = CHECK_SVG;
    } else if (isToday) {
      cls = 'day-dot today-pending';
      inner = '';
    } else if (isPast) {
      cls = 'day-dot missed';
      inner = '';
    } else {
      cls = 'day-dot missed';
      inner = '';
    }
    dots.push(`<span class="${cls}" title="${dayStr}">${inner}</span>`);
  }
  daysDots.innerHTML = dots.join('');

  daysSub.textContent = loggedDays.has(today) ? 'Mon – Sun' : 'Mon – Sun · today not logged';
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
    renderSummaryCards(entries);
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
