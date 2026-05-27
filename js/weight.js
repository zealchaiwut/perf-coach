function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const MA_COLOR = '#16a34a';
const DAILY_COLOR = '#9ca3af';

function isoDateStr(date) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
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
  const cutoffStr = isoDateStr(cutoff);
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
      const key = isoDateStr(check);
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
    renderSummaryCards(allEntries);
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
