(() => {
  const PRESETS = ['7d', '30d', '90d'];
  const DEFAULT_PRESET = '30d';

  // Readiness thresholds matching the Sprint 8 readiness card
  const READINESS_RED_MAX = 39;
  const READINESS_AMBER_MAX = 69;

  const presetBtns = document.querySelectorAll('.range-btn[data-range]');
  const customInputs = document.getElementById('custom-range-inputs');
  const fromInput = document.getElementById('range-from');
  const toInput = document.getElementById('range-to');
  const emptyBanner = document.getElementById('trends-empty-banner');

  const otherSlots = [
    { id: 'slot-hrv-rhr-body' },
    { id: 'slot-sleep-energy-body' },
    { id: 'slot-tss-body' },
  ];

  // ── URL helpers ──────────────────────────────────────────────────────────────

  function readRangeFromURL() {
    const params = new URLSearchParams(location.search);
    const range = params.get('range');
    const from = params.get('from');
    const to = params.get('to');

    if (from && to) return { type: 'custom', from, to };
    if (range && PRESETS.includes(range)) return { type: 'preset', preset: range };
    return { type: 'preset', preset: DEFAULT_PRESET };
  }

  function writeRangeToURL(state) {
    const params = new URLSearchParams();
    if (state.type === 'custom') {
      if (state.from) params.set('from', state.from);
      if (state.to) params.set('to', state.to);
    } else {
      params.set('range', state.preset);
    }
    const newURL = `${location.pathname}?${params.toString()}`;
    history.replaceState(null, '', newURL);
  }

  // ── UI state ─────────────────────────────────────────────────────────────────

  function applyRangeState(state) {
    presetBtns.forEach(btn => {
      const isActive =
        state.type === 'preset'
          ? btn.dataset.range === state.preset
          : btn.dataset.range === 'custom';
      btn.classList.toggle('active', isActive);
    });

    const isCustom = state.type === 'custom';
    customInputs.hidden = !isCustom;
    if (isCustom) {
      if (state.from) fromInput.value = state.from;
      if (state.to) toInput.value = state.to;
    }

    writeRangeToURL(state);
    loadChartData(state);
  }

  // ── Chart slot helpers ───────────────────────────────────────────────────────

  function showLoading(bodyEl) {
    bodyEl.innerHTML = `
      <div class="slot-loading">
        <div class="skeleton-spinner"></div>
        <div class="skeleton-bar-wrap">
          <div class="skeleton-bar"></div>
          <div class="skeleton-bar"></div>
          <div class="skeleton-bar"></div>
          <div class="skeleton-bar"></div>
        </div>
      </div>`;
  }

  function showEmpty(bodyEl) {
    bodyEl.innerHTML = `
      <div class="slot-empty">
        <div class="slot-empty-icon">📭</div>
        <div class="slot-empty-text">No data for this range</div>
      </div>`;
  }

  function resolveDateWindow(state) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (state.type === 'custom') {
      return { from: state.from || null, to: state.to || null };
    }
    const days = parseInt(state.preset, 10);
    const from = new Date(today);
    from.setDate(today.getDate() - days + 1);
    return {
      from: from.toISOString().slice(0, 10),
      to: today.toISOString().slice(0, 10),
    };
  }

  // ── Date utilities ────────────────────────────────────────────────────────────

  function buildDateRange(from, to) {
    const dates = [];
    const cur = new Date(from + 'T00:00:00');
    const end = new Date(to + 'T00:00:00');
    while (cur <= end) {
      dates.push(cur.toISOString().slice(0, 10));
      cur.setDate(cur.getDate() + 1);
    }
    return dates;
  }

  function formatLabel(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  // ── Rolling average ───────────────────────────────────────────────────────────

  function compute7DayRollingAvg(scores) {
    return scores.map((_, i) => {
      const window = scores.slice(Math.max(0, i - 6), i + 1).filter(v => v !== null);
      if (window.length === 0) return null;
      const avg = window.reduce((a, b) => a + b, 0) / window.length;
      return Math.round(avg * 10) / 10;
    });
  }

  // ── Chart.js color-band plugin ────────────────────────────────────────────────

  const readinessBandPlugin = {
    id: 'readinessBands',
    beforeDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      if (!chartArea) return;
      const y = scales.y;

      const bands = [
        { from: 70, to: 100, color: 'rgba(22, 163, 74, 0.08)' },
        { from: 40, to: 70,  color: 'rgba(217, 119, 6, 0.08)' },
        { from: 0,  to: 40,  color: 'rgba(220, 38, 38, 0.08)' },
      ];

      bands.forEach(({ from, to, color }) => {
        const top    = y.getPixelForValue(to);
        const bottom = y.getPixelForValue(from);
        ctx.save();
        ctx.fillStyle = color;
        ctx.fillRect(chartArea.left, top, chartArea.width, bottom - top);
        ctx.restore();
      });
    },
  };

  // ── Readiness chart ───────────────────────────────────────────────────────────

  let readinessChart = null;

  function renderReadinessChart(bodyEl, dates, scores, showAvg) {
    const labels = dates.map(formatLabel);
    const avgScores = showAvg ? compute7DayRollingAvg(scores) : [];

    // Ensure canvas is present (or reset after empty/loading state)
    if (!bodyEl.querySelector('canvas')) {
      bodyEl.innerHTML = '<canvas id="chart-readiness" style="display:block;width:100%;"></canvas>';
    }

    const datasets = [
      {
        label: 'Readiness',
        data: scores,
        borderColor: '#0070f3',
        backgroundColor: 'rgba(0,112,243,0.12)',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: '#0070f3',
        fill: false,
        spanGaps: false,
        tension: 0.3,
        order: 2,
      },
    ];

    if (showAvg) {
      datasets.push({
        label: '7-day avg',
        data: avgScores,
        borderColor: '#f59e0b',
        backgroundColor: 'transparent',
        borderWidth: 2.5,
        borderDash: [5, 4],
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: false,
        spanGaps: true,
        tension: 0.4,
        order: 1,
      });
    }

    if (readinessChart) {
      readinessChart.data.labels = labels;
      readinessChart.data.datasets = datasets;
      readinessChart.options.plugins.tooltip.callbacks =
        buildTooltipCallbacks(dates, scores, showAvg ? compute7DayRollingAvg(scores) : null);
      readinessChart.update();
      return;
    }

    const avgForTooltip = showAvg ? compute7DayRollingAvg(scores) : null;
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    readinessChart = new Chart(ctx, {
      type: 'line',
      plugins: [readinessBandPlugin],
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'nearest',
          axis: 'x',
          intersect: false,
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: { boxWidth: 12, font: { size: 11 } },
          },
          tooltip: {
            callbacks: buildTooltipCallbacks(dates, scores, avgForTooltip),
          },
        },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              maxRotation: 0,
              font: { size: 10 },
            },
            grid: { display: false },
          },
          y: {
            min: 0,
            max: 100,
            ticks: { stepSize: 20, font: { size: 10 } },
            grid: { color: 'rgba(0,0,0,0.05)' },
          },
        },
        animation: { duration: 200 },
      },
    });
  }

  function buildTooltipCallbacks(dates, scores, avgScores) {
    return {
      title(items) {
        const i = items[0].dataIndex;
        return dates[i] || items[0].label;
      },
      afterBody(items) {
        if (!avgScores) return [];
        const i = items[0].dataIndex;
        const avg = avgScores[i];
        if (avg === null) return [];
        return [`7-day avg: ${avg}`];
      },
      label(item) {
        const v = item.raw;
        if (item.datasetIndex === 1) return null; // avg handled in afterBody
        if (v === null) return 'Readiness: —';
        const band =
          v >= 70 ? 'Good' :
          v >= 40 ? 'Moderate' : 'Low';
        return `Readiness: ${v}  (${band})`;
      },
    };
  }

  // ── Fetch + render ────────────────────────────────────────────────────────────

  async function fetchReadiness(from, to) {
    const res = await fetch(`/api/readiness?from=${from}&to=${to}`);
    if (!res.ok) throw new Error('server error');
    return res.json();
  }

  function filterMockReadiness(from, to) {
    return (typeof MOCK_READINESS !== 'undefined' ? MOCK_READINESS : [])
      .filter(r => r.date >= from && r.date <= to);
  }

  function loadChartData(state) {
    const win = resolveDateWindow(state);
    const hasValidWindow = win.from && win.to && win.from <= win.to;

    const readinessBodyEl = document.getElementById('slot-readiness-body');
    showLoading(readinessBodyEl);
    otherSlots.forEach(({ id }) => showLoading(document.getElementById(id)));
    emptyBanner.hidden = true;

    if (!hasValidWindow) {
      showEmpty(readinessBodyEl);
      otherSlots.forEach(({ id }) => showEmpty(document.getElementById(id)));
      emptyBanner.hidden = false;
      return;
    }

    fetchReadiness(win.from, win.to)
      .then(data => renderReadinessFromData(readinessBodyEl, win, data))
      .catch(() => {
        // Fall back to mock data
        const data = filterMockReadiness(win.from, win.to);
        renderReadinessFromData(readinessBodyEl, win, data);
      });

    // Other slots are out of scope — show empty state after brief delay
    setTimeout(() => {
      otherSlots.forEach(({ id }) => showEmpty(document.getElementById(id)));
    }, 400);
  }

  function renderReadinessFromData(bodyEl, win, data) {
    const dates = buildDateRange(win.from, win.to);

    if (dates.length === 0) {
      showEmpty(bodyEl);
      emptyBanner.hidden = false;
      return;
    }

    // Build score array aligned to the full date range (null for missing days)
    const scoreByDate = Object.fromEntries(
      (data || []).map(r => [r.date, r.readiness_score])
    );
    const scores = dates.map(d =>
      d in scoreByDate ? scoreByDate[d] : null
    );

    const hasAnyData = scores.some(v => v !== null);
    if (!hasAnyData) {
      showEmpty(bodyEl);
      emptyBanner.hidden = false;
      return;
    }

    emptyBanner.hidden = true;
    const showAvg = dates.length >= 7;
    renderReadinessChart(bodyEl, dates, scores, showAvg);
  }

  // ── Event handlers ────────────────────────────────────────────────────────────

  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const range = btn.dataset.range;
      if (range === 'custom') {
        applyRangeState({ type: 'custom', from: fromInput.value, to: toInput.value });
      } else {
        applyRangeState({ type: 'preset', preset: range });
      }
    });
  });

  function onCustomDateChange() {
    if (fromInput.value || toInput.value) {
      applyRangeState({ type: 'custom', from: fromInput.value, to: toInput.value });
    }
  }

  fromInput.addEventListener('change', onCustomDateChange);
  toInput.addEventListener('change', onCustomDateChange);

  // ── Boot ─────────────────────────────────────────────────────────────────────

  applyRangeState(readRangeFromURL());
})();
