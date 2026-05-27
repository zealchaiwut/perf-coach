(() => {
  const PRESETS = ['7d', '30d', '90d'];
  const DEFAULT_PRESET = '30d';

  let _userId = null;

  const presetBtns = document.querySelectorAll('.range-btn[data-range]');
  const customInputs = document.getElementById('custom-range-inputs');
  const fromInput = document.getElementById('range-from');
  const toInput = document.getElementById('range-to');
  const emptyBanner = document.getElementById('trends-empty-banner');

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
    history.replaceState(null, '', `${location.pathname}?${params.toString()}`);
  }

  // ── UI state ─────────────────────────────────────────────────────────────────

  function applyRangeState(state) {
    presetBtns.forEach(btn => {
      const isActive = state.type === 'preset'
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
    if (state.type === 'custom') return { from: state.from || null, to: state.to || null };
    const days = parseInt(state.preset, 10);
    const from = new Date(today);
    from.setDate(today.getDate() - days + 1);
    return { from: toLocalDateStr(from), to: toLocalDateStr(today) };
  }

  // ── Date utilities ────────────────────────────────────────────────────────────

  function toLocalDateStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function buildDateRange(from, to) {
    const dates = [];
    const cur = new Date(from + 'T00:00:00');
    const end = new Date(to + 'T00:00:00');
    while (cur <= end) {
      dates.push(toLocalDateStr(cur));
      cur.setDate(cur.getDate() + 1);
    }
    return dates;
  }

  function formatLabel(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function addOneDay(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    d.setDate(d.getDate() + 1);
    return toLocalDateStr(d);
  }

  // ── Rolling average ───────────────────────────────────────────────────────────

  function compute7DayRollingAvg(scores) {
    return scores.map((_, i) => {
      const window = scores.slice(Math.max(0, i - 6), i + 1).filter(v => v !== null);
      if (window.length === 0) return null;
      return Math.round(window.reduce((a, b) => a + b, 0) / window.length * 10) / 10;
    });
  }

  // ── Summary API ───────────────────────────────────────────────────────────────

  async function fetchSummary(state, userId) {
    let url = '/trends/summary?user_id=' + encodeURIComponent(userId);
    if (state.type === 'custom') {
      if (state.from) url += '&from=' + state.from;
      if (state.to) url += '&to=' + state.to;
    } else {
      url += '&range=' + state.preset;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error('server error');
    return res.json();
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
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: buildTooltipCallbacks(dates, scores, avgForTooltip) },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0, font: { size: 10 } }, grid: { display: false } },
          y: { min: 0, max: 100, ticks: { stepSize: 20, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,0.05)' } },
        },
        animation: { duration: 200 },
      },
    });
  }

  function buildTooltipCallbacks(dates, scores, avgScores) {
    return {
      title(items) { return dates[items[0].dataIndex] || items[0].label; },
      afterBody(items) {
        if (!avgScores) return [];
        const avg = avgScores[items[0].dataIndex];
        return avg === null ? [] : [`7-day avg: ${avg}`];
      },
      label(item) {
        if (item.datasetIndex === 1) return null;
        const v = item.raw;
        if (v === null) return 'Readiness: —';
        const band = v >= 70 ? 'Good' : v >= 40 ? 'Moderate' : 'Low';
        return `Readiness: ${v}  (${band})`;
      },
    };
  }

  function renderReadinessFromSummary(bodyEl, summary) {
    const series = summary.readiness.series;
    const dates = series.map(s => s.date);
    const scores = series.map(s => s.score);
    if (dates.length === 0 || scores.every(v => v === null)) {
      showEmpty(bodyEl);
      emptyBanner.hidden = false;
      return;
    }
    emptyBanner.hidden = true;
    renderReadinessChart(bodyEl, dates, scores, dates.length >= 7);
  }

  // ── HRV / RHR stacked sub-charts ─────────────────────────────────────────────

  let hrvSubChart = null;
  let rhrSubChart = null;

  const baselineBandPlugin = {
    id: 'baselineBand',
    beforeDraw(chart) {
      const cfg = chart.options.plugins.baselineBand;
      if (!cfg || cfg.mean == null || cfg.sd == null) return;
      const { ctx, chartArea, scales } = chart;
      if (!chartArea) return;
      const y = scales.y;
      const top = y.getPixelForValue(cfg.mean + cfg.sd);
      const bottom = y.getPixelForValue(cfg.mean - cfg.sd);
      ctx.save();
      ctx.fillStyle = cfg.color || 'rgba(0,112,243,0.12)';
      ctx.fillRect(chartArea.left, top, chartArea.width, bottom - top);
      ctx.restore();
    },
  };

  function computeStats(values) {
    const valid = values.filter(v => v !== null && v !== undefined);
    if (valid.length === 0) return { mean: null, sd: null };
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    const variance = valid.reduce((a, v) => a + (v - mean) ** 2, 0) / valid.length;
    return {
      mean: Math.round(mean * 10) / 10,
      sd: Math.round(Math.sqrt(variance) * 10) / 10,
    };
  }

  function buildSubChartTooltipCallbacks(series, label, unit, mean, sd) {
    return {
      title(items) { return series[items[0].dataIndex]?.date || items[0].label; },
      label(item) {
        const v = item.raw;
        return v === null ? `${label}: —` : `${label}: ${v} ${unit}`;
      },
      afterBody(items) {
        const v = items[0].raw;
        if (v === null || mean == null) return [];
        const lines = [`Baseline: ${mean} ${unit}`];
        if (sd != null) {
          const raw = (v - mean) / sd;
          const sign = raw >= 0 ? '+' : '';
          lines.push(`Deviation: ${sign}${raw.toFixed(1)} SD`);
        }
        return lines;
      },
    };
  }

  function buildSubChart(ctx, series, label, unit, color, mean, sd, today) {
    const dates = series.map(s => s.date);
    const values = series.map(s => s.value);
    const labels = dates.map(formatLabel);
    const todayIdx = dates.indexOf(today);

    const pointBgColors = values.map((v, i) => {
      if (v === null) return 'transparent';
      if (mean != null && sd != null && Math.abs(v - mean) > sd) return '#ef4444';
      return color;
    });
    const pointRadii = values.map((v, i) => (v === null ? 0 : i === todayIdx ? 7 : 3));
    const pointHoverRadii = values.map((v, i) => (v === null ? 0 : i === todayIdx ? 9 : 5));
    const pointBorderColors = values.map((v, i) =>
      (v !== null && i === todayIdx ? '#1a1a1a' : pointBgColors[i])
    );
    const pointBorderWidths = values.map((_, i) => (i === todayIdx ? 2 : 0));

    return new Chart(ctx, {
      type: 'line',
      plugins: [baselineBandPlugin],
      data: {
        labels,
        datasets: [{
          label,
          data: values,
          borderColor: color,
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: pointRadii,
          pointHoverRadius: pointHoverRadii,
          pointBackgroundColor: pointBgColors,
          pointBorderColor: pointBorderColors,
          pointBorderWidth: pointBorderWidths,
          spanGaps: false,
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: buildSubChartTooltipCallbacks(series, label, unit, mean, sd) },
          baselineBand: {
            mean,
            sd,
            color: color === '#0070f3' ? 'rgba(0,112,243,0.12)' : 'rgba(239,68,68,0.12)',
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 7, maxRotation: 0, font: { size: 9 } }, grid: { display: false } },
          y: { ticks: { font: { size: 9 }, maxTicksLimit: 5 }, grid: { color: 'rgba(0,0,0,0.05)' } },
        },
        animation: { duration: 200 },
      },
    });
  }

  function renderHrvRhrStacked(bodyEl, hrvInfo, rhrInfo, today) {
    const hasHrvData = hrvInfo && hrvInfo.series && hrvInfo.series.some(s => s.value !== null);
    const hasRhrData = rhrInfo && rhrInfo.series && rhrInfo.series.some(s => s.value !== null);

    if (!hasHrvData && !hasRhrData) { showEmpty(bodyEl); return; }

    const approxBadge = '<span class="hrv-rhr-approx">approximate</span>';
    bodyEl.innerHTML = `
      <div class="hrv-rhr-stack">
        <div class="hrv-rhr-sub">
          <div class="hrv-rhr-sub-label">
            HRV (ms)${hrvInfo && hrvInfo.is_approximate ? ' ' + approxBadge : ''}
          </div>
          <div class="hrv-rhr-canvas-wrap">
            ${hasHrvData ? '<canvas id="canvas-hrv"></canvas>' : '<div class="hrv-rhr-sub-empty">No HRV data</div>'}
          </div>
        </div>
        <div class="hrv-rhr-sub hrv-rhr-sub--sep">
          <div class="hrv-rhr-sub-label">
            Resting HR (bpm)${rhrInfo && rhrInfo.is_approximate ? ' ' + approxBadge : ''}
          </div>
          <div class="hrv-rhr-canvas-wrap">
            ${hasRhrData ? '<canvas id="canvas-rhr"></canvas>' : '<div class="hrv-rhr-sub-empty">No RHR data</div>'}
          </div>
        </div>
      </div>`;

    if (hasHrvData) {
      const ctx = bodyEl.querySelector('#canvas-hrv').getContext('2d');
      hrvSubChart = buildSubChart(
        ctx, hrvInfo.series, 'HRV', 'ms', '#0070f3',
        hrvInfo.baseline_mean ?? null, hrvInfo.baseline_sd ?? null, today
      );
    }

    if (hasRhrData) {
      const ctx = bodyEl.querySelector('#canvas-rhr').getContext('2d');
      rhrSubChart = buildSubChart(
        ctx, rhrInfo.series, 'Resting HR', 'bpm', '#ef4444',
        rhrInfo.baseline_mean ?? null, rhrInfo.baseline_sd ?? null, today
      );
    }
  }

  // ── Sleep / Energy / Mood chart ───────────────────────────────────────────────

  let sleepEnergyChart = null;

  function renderSleepEnergyChart(bodyEl, summary) {
    const sleepData = summary.sleep.series.map(s => s.hours);
    const energyData = summary.energy.series.map(s => s.value);
    const moodData = summary.mood.series.map(s => s.value);
    const labels = summary.sleep.series.map(s => formatLabel(s.date));
    const hasData = sleepData.some(v => v !== null) || energyData.some(v => v !== null) || moodData.some(v => v !== null);
    if (!hasData) { showEmpty(bodyEl); return; }
    if (!bodyEl.querySelector('canvas')) {
      bodyEl.innerHTML = '<canvas id="chart-sleep-energy" style="display:block;width:100%;"></canvas>';
    }
    const datasets = [
      {
        label: 'Sleep (h)',
        data: sleepData,
        yAxisID: 'ySleep',
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.08)',
        borderWidth: 2,
        pointRadius: 3,
        spanGaps: false,
        fill: false,
        tension: 0.3,
      },
      {
        label: 'Energy',
        data: energyData,
        yAxisID: 'yScore',
        borderColor: '#f59e0b',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        spanGaps: false,
        fill: false,
        tension: 0.3,
      },
      {
        label: 'Mood',
        data: moodData,
        yAxisID: 'yScore',
        borderColor: '#10b981',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        spanGaps: false,
        fill: false,
        tension: 0.3,
      },
    ];
    if (sleepEnergyChart) {
      sleepEnergyChart.data.labels = labels;
      sleepEnergyChart.data.datasets = datasets;
      sleepEnergyChart.update();
      return;
    }
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    sleepEnergyChart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              title(items) { return summary.sleep.series[items[0].dataIndex].date; },
            },
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 0, font: { size: 10 } }, grid: { display: false } },
          ySleep: {
            type: 'linear', position: 'left', min: 0, max: 12,
            title: { display: true, text: 'Sleep (h)', font: { size: 10 } },
            ticks: { font: { size: 10 }, stepSize: 3 },
            grid: { color: 'rgba(0,0,0,0.05)' },
          },
          yScore: {
            type: 'linear', position: 'right', min: 0, max: 5,
            title: { display: true, text: '1–5', font: { size: 10 } },
            ticks: { font: { size: 10 }, stepSize: 1 },
            grid: { display: false },
          },
        },
        animation: { duration: 200 },
      },
    });
  }

  // ── TSS overlay chart ─────────────────────────────────────────────────────────

  let tssOverlayChart = null;

  function showTSSEmpty(bodyEl, message) {
    bodyEl.innerHTML = `
      <div class="slot-empty">
        <div class="slot-empty-icon">📭</div>
        <div class="slot-empty-text">${message || 'No data for this range'}</div>
      </div>`;
  }

  function renderTSSOverlayChart(bodyEl, dates, tssByDate, readinessByDate) {
    const tssValues = dates.map(d => tssByDate[d] ?? null);
    const nextDayReadiness = dates.map(d => readinessByDate[addOneDay(d)] ?? null);
    const validPairs = dates.filter((_, i) => tssValues[i] !== null && nextDayReadiness[i] !== null).length;
    if (validPairs < 2) {
      if (tssOverlayChart) { tssOverlayChart.destroy(); tssOverlayChart = null; }
      showTSSEmpty(bodyEl, 'Not enough data — log at least 2 days of workouts and next-day readiness to see this chart');
      return;
    }
    if (!bodyEl.querySelector('canvas')) {
      bodyEl.innerHTML = '<canvas id="chart-tss" style="display:block;width:100%;"></canvas>';
    }
    const labels = dates.map(formatLabel);
    const datasets = [
      {
        label: 'Daily TSS',
        data: tssValues,
        type: 'bar',
        yAxisID: 'yTSS',
        backgroundColor: 'rgba(99,102,241,0.55)',
        borderColor: 'rgba(99,102,241,0.85)',
        borderWidth: 1,
        order: 2,
      },
      {
        label: 'Next-day Readiness',
        data: nextDayReadiness,
        type: 'line',
        yAxisID: 'yReadiness',
        borderColor: '#f59e0b',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: '#f59e0b',
        fill: false,
        spanGaps: false,
        tension: 0.3,
        order: 1,
      },
    ];
    if (tssOverlayChart) {
      tssOverlayChart.data.labels = labels;
      tssOverlayChart.data.datasets = datasets;
      tssOverlayChart.update();
      return;
    }
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    tssOverlayChart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              title(items) { return dates[items[0].dataIndex]; },
              label(item) {
                const v = item.raw;
                if (item.datasetIndex === 0) return v === null ? 'TSS: —' : `TSS: ${v}`;
                if (v === null) return 'Next-day readiness: —';
                const band = v >= 70 ? 'Good' : v >= 40 ? 'Moderate' : 'Low';
                return `Next-day readiness: ${v}  (${band})`;
              },
            },
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 10 } }, grid: { display: false } },
          yTSS: {
            type: 'linear', position: 'left', min: 0,
            title: { display: true, text: 'TSS', font: { size: 10 }, color: 'rgba(99,102,241,0.9)' },
            ticks: { font: { size: 10 } },
            grid: { color: 'rgba(0,0,0,0.05)' },
          },
          yReadiness: {
            type: 'linear', position: 'right', min: 0, max: 100,
            title: { display: true, text: 'Readiness', font: { size: 10 }, color: '#f59e0b' },
            ticks: { stepSize: 20, font: { size: 10 } },
            grid: { drawOnChartArea: false },
          },
        },
        animation: { duration: 200 },
      },
    });
  }

  function renderTSSFromSummary(bodyEl, summary) {
    const tssByDate = {};
    summary.tss.series.forEach(s => { if (s.value !== null) tssByDate[s.date] = s.value; });
    const readinessByDate = {};
    summary.readiness.series.forEach(s => { if (s.score !== null) readinessByDate[s.date] = s.score; });
    const dates = summary.tss.series.map(s => s.date);
    renderTSSOverlayChart(bodyEl, dates, tssByDate, readinessByDate);
  }

  // ── Mock fallback helpers ─────────────────────────────────────────────────────

  function filterMockReadiness(from, to) {
    return (typeof MOCK_READINESS !== 'undefined' ? MOCK_READINESS : [])
      .filter(r => r.date >= from && r.date <= to);
  }

  function filterMockTSS(from, to) {
    return (typeof MOCK_TSS !== 'undefined' ? MOCK_TSS : [])
      .filter(r => r.date >= from && r.date <= to);
  }

  function buildTSSByDate(entries) {
    const byDate = {};
    entries.forEach(({ date, tss }) => { byDate[date] = (byDate[date] || 0) + tss; });
    return byDate;
  }

  function renderMockFallback(state) {
    const win = resolveDateWindow(state);
    if (!win.from || !win.to) return;

    const dates = buildDateRange(win.from, win.to);
    const readinessBodyEl = document.getElementById('slot-readiness-body');
    const mockReadiness = filterMockReadiness(win.from, win.to);
    const scoreByDate = Object.fromEntries(mockReadiness.map(r => [r.date, r.readiness_score]));
    const scores = dates.map(d => d in scoreByDate ? scoreByDate[d] : null);
    if (scores.some(v => v !== null)) {
      emptyBanner.hidden = true;
      renderReadinessChart(readinessBodyEl, dates, scores, dates.length >= 7);
    } else {
      showEmpty(readinessBodyEl);
      emptyBanner.hidden = false;
    }

    const hrvRhrBodyEl = document.getElementById('slot-hrv-rhr-body');
    const allHrvRhr = typeof MOCK_HRV_RHR !== 'undefined' ? MOCK_HRV_RHR : [];
    const filteredHrvRhr = allHrvRhr.filter(r => r.date >= win.from && r.date <= win.to);
    if (filteredHrvRhr.length > 0) {
      const { mean: hrvMean, sd: hrvSd } = computeStats(allHrvRhr.map(r => r.hrv));
      const { mean: rhrMean, sd: rhrSd } = computeStats(allHrvRhr.map(r => r.rhr));
      const isApprox = allHrvRhr.length < 30;
      renderHrvRhrStacked(
        hrvRhrBodyEl,
        {
          series: filteredHrvRhr.map(r => ({ date: r.date, value: r.hrv })),
          baseline_mean: hrvMean, baseline_sd: hrvSd, is_approximate: isApprox,
        },
        {
          series: filteredHrvRhr.map(r => ({ date: r.date, value: r.rhr })),
          baseline_mean: rhrMean, baseline_sd: rhrSd, is_approximate: isApprox,
        },
        toLocalDateStr(new Date())
      );
    } else {
      showEmpty(hrvRhrBodyEl);
    }

    showEmpty(document.getElementById('slot-sleep-energy-body'));

    const tssBodyEl = document.getElementById('slot-tss-body');
    const mockWorkouts = filterMockTSS(win.from, win.to);
    const tssByDate = buildTSSByDate(mockWorkouts);
    const mockReadinessByDate = Object.fromEntries(
      (typeof MOCK_READINESS !== 'undefined' ? MOCK_READINESS : []).map(r => [r.date, r.readiness_score])
    );
    renderTSSOverlayChart(tssBodyEl, dates, tssByDate, mockReadinessByDate);
  }

  // ── Main data loader ──────────────────────────────────────────────────────────

  function loadChartData(state) {
    if (!_userId) return;

    const win = resolveDateWindow(state);
    const hasValidWindow = win.from && win.to && win.from <= win.to;

    const readinessBodyEl = document.getElementById('slot-readiness-body');
    const hrvRhrBodyEl = document.getElementById('slot-hrv-rhr-body');
    const sleepEnergyBodyEl = document.getElementById('slot-sleep-energy-body');
    const tssBodyEl = document.getElementById('slot-tss-body');

    showLoading(readinessBodyEl);
    showLoading(hrvRhrBodyEl);
    showLoading(sleepEnergyBodyEl);
    showLoading(tssBodyEl);
    if (tssOverlayChart) { tssOverlayChart.destroy(); tssOverlayChart = null; }
    if (hrvSubChart) { hrvSubChart.destroy(); hrvSubChart = null; }
    if (rhrSubChart) { rhrSubChart.destroy(); rhrSubChart = null; }
    emptyBanner.hidden = true;

    if (!hasValidWindow) {
      showEmpty(readinessBodyEl);
      showEmpty(hrvRhrBodyEl);
      showEmpty(sleepEnergyBodyEl);
      showTSSEmpty(tssBodyEl);
      emptyBanner.hidden = false;
      return;
    }

    fetchSummary(state, _userId)
      .then(summary => {
        renderReadinessFromSummary(readinessBodyEl, summary);
        renderHrvRhrStacked(hrvRhrBodyEl, summary.hrv, summary.rhr, toLocalDateStr(new Date()));
        renderSleepEnergyChart(sleepEnergyBodyEl, summary);
        renderTSSFromSummary(tssBodyEl, summary);
      })
      .catch(() => renderMockFallback(state));
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

  const _initialState = readRangeFromURL();

  window.addEventListener('userReady', e => {
    _userId = e.detail.userId;
    applyRangeState(_initialState);
  });

  window.addEventListener('userChanged', e => {
    _userId = e.detail.userId;
    applyRangeState(readRangeFromURL());
  });
})();
