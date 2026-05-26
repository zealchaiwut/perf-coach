(function () {
  const MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  let state = readMonthFromURL();

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

  function render() {
    const { year, month } = state;
    const today = new Date();

    document.getElementById('month-label').textContent =
      `${MONTH_NAMES[month]} ${year}`;

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

      const num = document.createElement('span');
      num.className = 'cal-day-num';
      num.textContent = date.getDate();
      cell.appendChild(num);

      grid.appendChild(cell);
    }
  }

  function navigate(delta) {
    let { year, month } = state;
    month += delta;
    if (month > 11) { year++; month = 0; }
    if (month < 0) { year--; month = 11; }
    state = { year, month };
    writeMonthToURL(year, month);
    render();
  }

  document.getElementById('prev-btn').addEventListener('click', () => navigate(-1));
  document.getElementById('next-btn').addEventListener('click', () => navigate(1));
  document.getElementById('today-btn').addEventListener('click', () => {
    const now = new Date();
    state = { year: now.getFullYear(), month: now.getMonth() };
    writeMonthToURL(state.year, state.month);
    render();
  });

  window.addEventListener('popstate', () => {
    state = readMonthFromURL();
    render();
  });

  render();
})();
