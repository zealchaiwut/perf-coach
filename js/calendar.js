(function () {
  const MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  let state = readMonthFromURL();
  let currentUserId = null;
  let calData = emptyData();
  let loadSeq = 0;

  function emptyData() {
    return { weights: {}, habits: [], habitLogs: {}, workouts: {} };
  }

  function readMonthFromURL() {
    const params = new URLSearchParams(location.search);
    const raw = params.get('month');
    if (raw && /^\d{4}-\d{2}$/.test(raw)) {
      const [y, m] = raw.split('-').map(Number);
      if (m >= 1 && m <= 12) return { year: y, month: m - 1 };
    }
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  }

  function writeMonthToURL(year, month) {
    const tag = `${year}-${String(month + 1).padStart(2, '0')}`;
    const url = new URL(location.href);
    url.searchParams.set('month', tag);
    history.pushState({ month: tag }, '', url);
  }

  function toLocalDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function monthRange(year, month) {
    const mm = String(month + 1).padStart(2, '0');
    const from = `${year}-${mm}-01`;
    const to = `${year}-${mm}-${String(new Date(year, month + 1, 0).getDate()).padStart(2, '0')}`;
    return { from, to };
  }

  async function fetchCalendarData(userId, year, month) {
    const { from, to } = monthRange(year, month);
    const enc = s => encodeURIComponent(s);
    try {
      const [wR, hR, lR, tR] = await Promise.all([
        fetch(`/api/weight?user_id=${enc(userId)}`),
        fetch(`/api/habits?user_id=${enc(userId)}`),
        fetch(`/api/habits/logs?user_id=${enc(userId)}&from=${from}&to=${to}`),
        fetch(`/api/workouts?user_id=${enc(userId)}&from=${from}&to=${to}`),
      ]);
      const [weights, habits, logs, workouts] = await Promise.all([
        wR.ok ? wR.json() : [],
        hR.ok ? hR.json() : [],
        lR.ok ? lR.json() : [],
        tR.ok ? tR.json() : [],
      ]);

      const weightMap = {};
      for (const w of weights) {
        if (w.recorded_date >= from && w.recorded_date <= to) {
          weightMap[w.recorded_date] = w.weight_kg;
        }
      }

      const logMap = {};
      for (const l of logs) {
        if (!logMap[l.logged_date]) logMap[l.logged_date] = new Set();
        logMap[l.logged_date].add(l.habit_id);
      }

      const workoutMap = {};
      for (const w of workouts) {
        if (!workoutMap[w.workout_date]) workoutMap[w.workout_date] = [];
        workoutMap[w.workout_date].push(w);
      }

      calData = { weights: weightMap, habits, habitLogs: logMap, workouts: workoutMap };
    } catch {
      // calData stays as emptyData() set by caller; cells remain empty
    }
  }

  function trainingIconClass(type) {
    const t = (type || '').toLowerCase();
    if (/run|swim|cycl|cardio|hiit|aerob|walk|jog/.test(t)) return 'ti-run';
    if (/strength|weight|power|lift|resist/.test(t)) return 'ti-barbell';
    if (/yoga|stretch|flex|mobil|pilat/.test(t)) return 'ti-yoga';
    return 'ti-activity';
  }

  function populateCell(cell, date, inMonth) {
    const todayStr = toLocalDateStr(new Date());
    const dateStr = toLocalDateStr(date);
    const isToday = dateStr === todayStr;
    const isPast = dateStr < todayStr;

    // Top row: day number + optional weight value
    const top = document.createElement('div');
    top.className = 'cal-cell-top';

    const num = document.createElement('span');
    num.className = 'cal-day-num';
    num.textContent = date.getDate();
    top.appendChild(num);

    if (inMonth && calData.weights[dateStr] !== undefined) {
      const wt = document.createElement('span');
      wt.className = 'cal-weight-val';
      wt.textContent = `${parseFloat(calData.weights[dateStr]).toFixed(1)}kg`;
      top.appendChild(wt);
    }

    cell.appendChild(top);

    if (!inMonth) return;

    // Middle row: one dot per habit
    if (calData.habits.length > 0) {
      const row = document.createElement('div');
      row.className = 'cal-habits-row';
      const doneIds = calData.habitLogs[dateStr] || new Set();

      for (const h of calData.habits) {
        const dot = document.createElement('span');
        dot.className = 'cal-habit-dot';
        dot.title = h.name;

        if (doneIds.has(h.id)) {
          dot.classList.add('done');
        } else if (isToday) {
          dot.classList.add('today-pending');
        } else if (isPast) {
          dot.classList.add('missed');
        } else {
          dot.classList.add('future');
        }

        row.appendChild(dot);
      }
      cell.appendChild(row);
    }

    // Bottom row: training icon + exercise count
    const dayWorkouts = calData.workouts[dateStr];
    if (dayWorkouts && dayWorkouts.length > 0) {
      const row = document.createElement('div');
      row.className = 'cal-training-row';

      const w = dayWorkouts[0];
      const icon = document.createElement('i');
      icon.className = `ti ${trainingIconClass(w.workout_type)} cal-training-icon`;
      row.appendChild(icon);

      if (w.exercise_count > 0) {
        const count = document.createElement('span');
        count.className = 'cal-training-dur';
        count.textContent = `${w.exercise_count}ex`;
        row.appendChild(count);
      }

      cell.appendChild(row);
    }

    cell.style.cursor = 'pointer';
  }

  function render() {
    const { year, month } = state;
    const today = new Date();
    const showWeight = document.getElementById('filter-weight').checked;
    const showHabits = document.getElementById('filter-habits').checked;
    const showTraining = document.getElementById('filter-training').checked;

    document.getElementById('month-label').textContent = `${MONTH_NAMES[month]} ${year}`;

    // ISO Monday-first: Mon=0 … Sun=6
    const firstDow = new Date(year, month, 1).getDay(); // 0=Sun
    const offset = (firstDow + 6) % 7;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const totalSlots = Math.ceil((offset + daysInMonth) / 7) * 7;

    const grid = document.getElementById('cal-grid-cells');
    grid.innerHTML = '';

    for (let i = 0; i < totalSlots; i++) {
      const dayNum = i - offset + 1;
      const date = new Date(year, month, dayNum);
      const inMonth = dayNum >= 1 && dayNum <= daysInMonth;
      const isToday =
        date.getFullYear() === today.getFullYear() &&
        date.getMonth() === today.getMonth() &&
        date.getDate() === today.getDate();

      const cell = document.createElement('div');
      cell.className = 'cal-cell';
      if (!inMonth) cell.classList.add('out-of-month');
      if (isToday) cell.classList.add('today');

      populateCell(cell, date, inMonth);

      // Apply current filter visibility
      const wtEl = cell.querySelector('.cal-weight-val');
      const hRow = cell.querySelector('.cal-habits-row');
      const tRow = cell.querySelector('.cal-training-row');
      if (wtEl) wtEl.hidden = !showWeight;
      if (hRow) hRow.hidden = !showHabits;
      if (tRow) tRow.hidden = !showTraining;

      grid.appendChild(cell);
    }
  }

  function applyFilters() {
    const showWeight = document.getElementById('filter-weight').checked;
    const showHabits = document.getElementById('filter-habits').checked;
    const showTraining = document.getElementById('filter-training').checked;
    document.querySelectorAll('.cal-weight-val').forEach(el => { el.hidden = !showWeight; });
    document.querySelectorAll('.cal-habits-row').forEach(el => { el.hidden = !showHabits; });
    document.querySelectorAll('.cal-training-row').forEach(el => { el.hidden = !showTraining; });
  }

  // Fetch data for current state, then re-render. Uses loadSeq to discard stale results.
  async function loadData() {
    const seq = ++loadSeq;
    if (!currentUserId) return;
    await fetchCalendarData(currentUserId, state.year, state.month);
    if (seq !== loadSeq) return;
    render();
  }

  // Fade out → run action (updates state + clears data) → render empty → fade in → fetch + render with data
  function withFade(action) {
    const grid = document.getElementById('cal-grid-cells');
    grid.classList.add('fading');
    setTimeout(() => {
      action();
      render();
      grid.classList.remove('fading');
      loadData();
    }, 75);
  }

  function navigate(delta) {
    withFade(() => {
      let { year, month } = state;
      month += delta;
      if (month > 11) { year++; month = 0; }
      if (month < 0) { year--; month = 11; }
      state = { year, month };
      writeMonthToURL(year, month);
      calData = emptyData();
    });
  }

  function goToToday() {
    withFade(() => {
      const now = new Date();
      state = { year: now.getFullYear(), month: now.getMonth() };
      writeMonthToURL(state.year, state.month);
      calData = emptyData();
    });
  }

  document.getElementById('prev-btn').addEventListener('click', () => navigate(-1));
  document.getElementById('next-btn').addEventListener('click', () => navigate(1));
  document.getElementById('today-btn').addEventListener('click', goToToday);

  document.getElementById('filter-weight').addEventListener('change', applyFilters);
  document.getElementById('filter-habits').addEventListener('change', applyFilters);
  document.getElementById('filter-training').addEventListener('change', applyFilters);

  window.addEventListener('popstate', () => {
    state = readMonthFromURL();
    calData = emptyData();
    render();
    loadData();
  });

  // Keyboard shortcuts: ←/→ navigate, Home = today, Esc = close modal
  document.addEventListener('keydown', (e) => {
    const tag = (document.activeElement && document.activeElement.tagName.toLowerCase()) || '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      navigate(-1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      navigate(1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      goToToday();
    } else if (e.key === 'Escape') {
      const overlay = document.querySelector('.modal-overlay');
      if (overlay) overlay.remove();
    }
  });

  window.addEventListener('userReady', e => {
    currentUserId = e.detail.userId;
    loadData();
  });

  window.addEventListener('userChanged', e => {
    currentUserId = e.detail.userId;
    calData = emptyData();
    render();
    loadData();
  });

  render();
})();
