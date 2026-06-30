(() => {
  const PRESETS = ['7d', '30d', '90d'];
  const DEFAULT_PRESET = '30d';

  let _userId = null;

  const presetBtns = document.querySelectorAll('.range-btn[data-range]');
  const customInputs = document.getElementById('custom-range-inputs');
  const fromInput = document.getElementById('range-from');
  const toInput = document.getElementById('range-to');
  const confirmBtn = document.getElementById('range-confirm');
  const rangeCancelBtn = document.getElementById('range-cancel');
  const emptyBanner = document.getElementById('trends-empty-banner');

  // Track the last non-custom state so Cancel can revert to it
  let _lastPresetState = { type: 'preset', preset: DEFAULT_PRESET };

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

  let _confirmedState = null;

  function setActiveChip(state) {
    presetBtns.forEach(btn => {
      const isActive = state.type === 'preset'
        ? btn.dataset.range === state.preset
        : btn.dataset.range === 'custom';
      btn.classList.toggle('active', isActive);
    });
  }

  function openCustomPicker() {
    if (_confirmedState?.type === 'custom') {
      if (_confirmedState.from) fromInput.value = _confirmedState.from;
      if (_confirmedState.to) toInput.value = _confirmedState.to;
    }
    presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.range === 'custom'));
    customInputs.hidden = false;
    fromInput.focus();
  }

  function closeCustomPicker() {
    customInputs.hidden = true;
    const errEl = document.getElementById('custom-range-error');
    if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
  }

  function commitState(state) {
    _confirmedState = state;
    setActiveChip(state);
    closeCustomPicker();
    writeRangeToURL(state);
    loadChartData(state);
  }

  function applyRangeState(state) {
    _confirmedState = state;
    setActiveChip(state);
    const isCustom = state.type === 'custom';
    if (isCustom) {
      if (state.from) fromInput.value = state.from;
      if (state.to) toInput.value = state.to;
      customInputs.hidden = false;
    } else {
      customInputs.hidden = true;
    }
    if (state.type === 'preset') {
      _lastPresetState = state;
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
      if (i < 6) return null;
      const window = scores.slice(i - 6, i + 1).filter(v => v !== null);
      if (window.length === 0) return null;
      return Math.round(window.reduce((a, b) => a + b, 0) / window.length * 10) / 10;
    });
  }

  // ── Summary API ───────────────────────────────────────────────────────────────

  async function fetchSummary(state) {
    const params = new URLSearchParams();
    if (state.type === 'custom') {
      if (state.from) params.set('from', state.from);
      if (state.to) params.set('to', state.to);
    } else {
      params.set('range', state.preset);
    }
    const res = await fetch('/trends/summary?' + params.toString());
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
        interaction: { mode: 'index', axis: 'x', intersect: false },
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
      title(items) {
        const idx = items[0].dataIndex;
        return dates[idx] || items[0].label;
      },
      afterBody(items) {
        const idx = items[0].dataIndex;
        const lines = [];
        if (avgScores) {
          const avg = avgScores[idx];
          if (avg !== null) lines.push(`7-day avg: ${avg}`);
        }
        if (scores[idx] === null) lines.push('Missing data');
        return lines;
      },
      label(item) {
        if (item.datasetIndex === 1) return null;
        const idx = item.dataIndex;
        const v = scores[idx];
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
      const baseline_mean = cfg.mean;
      const baseline_sd = cfg.sd;
      const top = y.getPixelForValue(baseline_mean + baseline_sd);
      const bottom = y.getPixelForValue(baseline_mean - baseline_sd);
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

  function renderHrvChart(bodyEl, info, today) {
    if (!info || !info.series || !info.series.some(s => s.value !== null)) {
      showEmpty(bodyEl); return;
    }
    const baseline_mean = info.baseline_mean ?? null;
    const baseline_sd = info.baseline_sd ?? null;
    const labelEl = document.getElementById('hrv-sub-label');
    if (labelEl && info.is_approximate) {
      labelEl.innerHTML = 'HRV (ms) <span class="hrv-rhr-approx">approximate</span>';
    }
    bodyEl.innerHTML = '<canvas></canvas>';
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    hrvSubChart = buildSubChart(ctx, info.series, 'HRV', 'ms', '#0070f3', baseline_mean, baseline_sd, today);
  }

  function renderRhrChart(bodyEl, info, today) {
    if (!info || !info.series || !info.series.some(s => s.value !== null)) {
      showEmpty(bodyEl); return;
    }
    const baseline_mean = info.baseline_mean ?? null;
    const baseline_sd = info.baseline_sd ?? null;
    const labelEl = document.getElementById('rhr-sub-label');
    if (labelEl && info.is_approximate) {
      labelEl.innerHTML = 'Resting HR (bpm) <span class="hrv-rhr-approx">approximate</span>';
    }
    bodyEl.innerHTML = '<canvas></canvas>';
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    rhrSubChart = buildSubChart(ctx, info.series, 'Resting HR', 'bpm', '#ef4444', baseline_mean, baseline_sd, today);
  }

  // ── Sleep / Energy / Mood chart ───────────────────────────────────────────────

  let semChart = null;
  let _semEnergyVisible = true;
  let _semMoodVisible = true;
  let _semWeeklyAvgVisible = false;

  // Custom plugin: draws a weekly-average sleep-quality label above each week's bars
  const weeklyAvgPlugin = {
    id: 'weeklyAvgAnnotations',
    afterDatasetsDraw(chart) {
      const cfg = chart.options.plugins.weeklyAvgAnnotations;
      if (!cfg?.enabled) return;
      const { ctx, chartArea, scales } = chart;
      if (!chartArea) return;
      const { dates, sleepData } = cfg;

      const weekMap = new Map();
      dates.forEach((date, i) => {
        const d = new Date(date + 'T00:00:00');
        const dow = d.getDay();
        const monday = new Date(d);
        monday.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
        const key = toLocalDateStr(monday);
        if (!weekMap.has(key)) weekMap.set(key, { indices: [], values: [] });
        const wk = weekMap.get(key);
        wk.indices.push(i);
        if (sleepData[i] !== null) wk.values.push(sleepData[i]);
      });

      ctx.save();
      ctx.font = 'bold 9px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = 'rgba(99,102,241,0.85)';
      weekMap.forEach(wk => {
        if (wk.values.length === 0) return;
        const avg = wk.values.reduce((a, b) => a + b, 0) / wk.values.length;
        const midIdx = wk.indices[Math.floor(wk.indices.length / 2)];
        ctx.fillText(`avg ${avg.toFixed(1)}`, scales.x.getPixelForValue(midIdx), chartArea.top + 10);
      });
      ctx.restore();
    },
  };

  function renderSEMChart(bodyEl, sleepSeries, energySeries, moodSeries) {
    const dateSet = new Set([
      ...sleepSeries.map(s => s.date),
      ...energySeries.map(s => s.date),
      ...moodSeries.map(s => s.date),
    ]);
    const dates = [...dateSet].sort();

    const sleepByDate  = Object.fromEntries(sleepSeries.map(s => [s.date, s.quality ?? null]));
    const energyByDate = Object.fromEntries(energySeries.map(s => [s.date, s.value  ?? null]));
    const moodByDate   = Object.fromEntries(moodSeries.map(s => [s.date, s.value    ?? null]));

    const sleepData  = dates.map(d => sleepByDate[d]  ?? null);
    const energyData = dates.map(d => energyByDate[d] ?? null);
    const moodData   = dates.map(d => moodByDate[d]   ?? null);

    const hasAnySleep  = sleepData.some(v => v !== null);
    const hasAnyEnergy = energyData.some(v => v !== null);
    const hasAnyMood   = moodData.some(v => v !== null);

    if (!hasAnySleep && !hasAnyEnergy && !hasAnyMood) { showEmpty(bodyEl); return; }

    const energyBtn  = document.getElementById('btn-toggle-energy');
    const moodBtn    = document.getElementById('btn-toggle-mood');
    const semToggles = document.getElementById('sem-toggles');
    if (energyBtn)  energyBtn.hidden  = !hasAnyEnergy;
    if (moodBtn)    moodBtn.hidden    = !hasAnyMood;
    if (semToggles) semToggles.hidden = !hasAnyEnergy && !hasAnyMood;

    const labels = dates.map(formatLabel);
    const datasets = [];

    if (hasAnySleep) {
      datasets.push({
        label: 'Sleep quality',
        data: sleepData,
        type: 'bar',
        yAxisID: 'yScore',
        backgroundColor: 'rgba(99,102,241,0.55)',
        borderColor: 'rgba(99,102,241,0.8)',
        borderWidth: 1,
        order: 3,
      });
    }

    if (hasAnyEnergy) {
      datasets.push({
        label: 'Energy',
        data: energyData,
        type: 'line',
        yAxisID: 'yScore',
        borderColor: '#f59e0b',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: '#f59e0b',
        spanGaps: false,
        fill: false,
        tension: 0.3,
        order: 1,
        hidden: !_semEnergyVisible,
      });
    }

    if (hasAnyMood) {
      datasets.push({
        label: 'Mood',
        data: moodData,
        type: 'line',
        yAxisID: 'yScore',
        borderColor: '#10b981',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: '#10b981',
        spanGaps: false,
        fill: false,
        tension: 0.3,
        order: 2,
        hidden: !_semMoodVisible,
      });
    }

    bodyEl.innerHTML = '<canvas id="chart-sem"></canvas>';
    const ctx = bodyEl.querySelector('canvas').getContext('2d');
    semChart = new Chart(ctx, {
      type: 'bar',
      plugins: [weeklyAvgPlugin],
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            filter: item => item.raw !== null && item.raw !== undefined,
            callbacks: {
              title(items) { return dates[items[0].dataIndex]; },
              label(item) {
                const v = item.raw;
                if (v === null || v === undefined) return null;
                return `${item.dataset.label}: ${v}/5`;
              },
            },
          },
          weeklyAvgAnnotations: { enabled: _semWeeklyAvgVisible, dates, sleepData },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 10 } }, grid: { display: false } },
          yScore: {
            type: 'linear', position: 'left', min: 0, max: 5,
            title: { display: true, text: '1–5', font: { size: 10 } },
            ticks: { font: { size: 10 }, stepSize: 1 },
            grid: { color: 'rgba(0,0,0,0.05)' },
          },
        },
        animation: { duration: 200 },
      },
    });
  }

  function renderSEMFromSummary(bodyEl, summary) {
    renderSEMChart(
      bodyEl,
      summary.sleep?.series  || [],
      summary.energy?.series || [],
      summary.mood?.series   || [],
    );
  }

  function updateSEMVisibility() {
    const energyBtn = document.getElementById('btn-toggle-energy');
    const moodBtn   = document.getElementById('btn-toggle-mood');
    const weeklyBtn = document.getElementById('btn-toggle-weekly-avg');
    if (energyBtn) energyBtn.classList.toggle('active', _semEnergyVisible);
    if (moodBtn)   moodBtn.classList.toggle('active', _semMoodVisible);
    if (weeklyBtn) weeklyBtn.classList.toggle('active', _semWeeklyAvgVisible);

    if (!semChart) return;
    semChart.data.datasets.forEach(ds => {
      if (ds.label === 'Energy') ds.hidden = !_semEnergyVisible;
      if (ds.label === 'Mood')   ds.hidden = !_semMoodVisible;
    });
    if (semChart.options.plugins.weeklyAvgAnnotations) {
      semChart.options.plugins.weeklyAvgAnnotations.enabled = _semWeeklyAvgVisible;
    }
    semChart.update();
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

  function _buildTSSTooltipCallbacks(datesRef) {
    return {
      title(items) { return datesRef[items[0].dataIndex]; },
      label(item) {
        const v = item.raw;
        if (item.datasetIndex === 0) return v === null ? 'TSS: —' : `TSS: ${v}`;
        if (v === null) return 'Next-day readiness: —';
        const band = v >= 70 ? 'Good' : v >= 40 ? 'Moderate' : 'Low';
        return `Next-day readiness: ${v}  (${band})`;
      },
      afterBody() {
        return ['Readiness shown is for the day after this TSS value'];
      },
    };
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
        pointHoverRadius: 6,
        pointBackgroundColor: '#f59e0b',
        hitRadius: 22,
        fill: false,
        spanGaps: false,
        tension: 0.3,
        order: 1,
      },
    ];
    if (tssOverlayChart) {
      tssOverlayChart.data.labels = labels;
      tssOverlayChart.data.datasets = datasets;
      // Refresh tooltip callbacks so the title() closure references the new dates array
      tssOverlayChart.options.plugins.tooltip.callbacks = _buildTSSTooltipCallbacks(dates);
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
          legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 12 } } },
          tooltip: {
            callbacks: _buildTSSTooltipCallbacks(dates),
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 12 } }, grid: { display: false } },
          yTSS: {
            type: 'linear', position: 'left', min: 0,
            title: { display: true, text: 'TSS', font: { size: 12 }, color: 'rgba(99,102,241,0.9)' },
            ticks: { font: { size: 12 } },
            grid: { color: 'rgba(0,0,0,0.05)' },
          },
          yReadiness: {
            type: 'linear', position: 'right', min: 0, max: 100,
            title: { display: true, text: 'Readiness', font: { size: 12 }, color: '#f59e0b' },
            ticks: { stepSize: 20, font: { size: 12 } },
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

    const hrvBodyEl = document.getElementById('slot-hrv-body');
    const rhrBodyEl = document.getElementById('slot-rhr-body');
    const allHrvRhr = typeof MOCK_HRV_RHR !== 'undefined' ? MOCK_HRV_RHR : [];
    const filteredHrvRhr = allHrvRhr.filter(r => r.date >= win.from && r.date <= win.to);
    const today = toLocalDateStr(new Date());
    if (filteredHrvRhr.length > 0) {
      const { mean: hrvMean, sd: hrvSd } = computeStats(allHrvRhr.map(r => r.hrv));
      const { mean: rhrMean, sd: rhrSd } = computeStats(allHrvRhr.map(r => r.rhr));
      const isApprox = allHrvRhr.length < 30;
      renderHrvChart(hrvBodyEl,
        { series: filteredHrvRhr.map(r => ({ date: r.date, value: r.hrv })),
          baseline_mean: hrvMean, baseline_sd: hrvSd, is_approximate: isApprox },
        today);
      renderRhrChart(rhrBodyEl,
        { series: filteredHrvRhr.map(r => ({ date: r.date, value: r.rhr })),
          baseline_mean: rhrMean, baseline_sd: rhrSd, is_approximate: isApprox },
        today);
    } else {
      showEmpty(hrvBodyEl);
      showEmpty(rhrBodyEl);
    }

    const semBodyEl = document.getElementById('slot-sem-body');
    const mockFallbackSummary = typeof mockGetTrendsSummary === 'function'
      ? mockGetTrendsSummary({ range: state.type === 'preset' ? state.preset : '30d' })
      : null;
    if (mockFallbackSummary) {
      const filteredSleep  = (mockFallbackSummary.sleep?.series  || []).filter(s => s.date >= win.from && s.date <= win.to);
      const filteredEnergy = (mockFallbackSummary.energy?.series || []).filter(s => s.date >= win.from && s.date <= win.to);
      const filteredMood   = (mockFallbackSummary.mood?.series   || []).filter(s => s.date >= win.from && s.date <= win.to);
      if (filteredSleep.length > 0 || filteredEnergy.length > 0 || filteredMood.length > 0) {
        if (semChart) { semChart.destroy(); semChart = null; }
        renderSEMChart(semBodyEl, filteredSleep, filteredEnergy, filteredMood);
      } else {
        showEmpty(semBodyEl);
      }
    } else {
      showEmpty(semBodyEl);
    }

    const tssBodyEl = document.getElementById('slot-tss-body');
    const mockWorkouts = filterMockTSS(win.from, win.to);
    const tssByDate = buildTSSByDate(mockWorkouts);
    const mockReadinessByDate = Object.fromEntries(
      (typeof MOCK_READINESS !== 'undefined' ? MOCK_READINESS : []).map(r => [r.date, r.readiness_score])
    );
    renderTSSOverlayChart(tssBodyEl, dates, tssByDate, mockReadinessByDate);
  }

  // ── Intensity distribution stacked bar chart ─────────────────────────────────

  let intensityChart = null;

  // Design-system colours: low=green (#16a34a), moderate=amber (#d97706), high=red (#dc2626)
  const INTENSITY_COLOURS = {
    low:      { bg: 'rgba(22, 163, 74, 0.80)',  border: '#16a34a' },
    moderate: { bg: 'rgba(217, 119, 6, 0.80)',  border: '#d97706' },
    high:     { bg: 'rgba(220, 38, 38, 0.80)',  border: '#dc2626' },
  };

  function renderIntensityChart(bodyEl, data) {
    if (!bodyEl) return;

    var sessions = (data && data.sessions) || [];
    var rollingWindow = (data && data.rolling_window) || {};

    // Show empty state when no sessions have band data
    var hasBandData = sessions.some(function (s) { return s.low_pct !== null; });
    var hasRollingData = rollingWindow.low_pct !== null;
    if (!hasBandData && !hasRollingData) {
      showEmpty(bodyEl);
      return;
    }

    bodyEl.innerHTML = '<canvas id="chart-intensity" style="display:block;width:100%;"></canvas>';
    var canvas = document.getElementById('chart-intensity');
    if (!canvas || typeof Chart === 'undefined') return;

    // Build labels: one per session + separator + rolling window label
    var labels = sessions.map(function (s) { return formatLabel(s.date); });
    var sessionCount = sessions.length;
    labels.push('');           // visual gap
    labels.push('28-day avg'); // rolling window bar

    function buildDataset(band, label) {
      var vals = sessions.map(function (s) { return s[band + '_pct'] || 0; });
      vals.push(0); // gap bar
      vals.push(rollingWindow[band + '_pct'] || 0);
      return {
        label: label,
        data: vals,
        backgroundColor: INTENSITY_COLOURS[band].bg,
        borderColor: INTENSITY_COLOURS[band].border,
        borderWidth: 1,
        borderRadius: 2,
        maxBarThickness: 40,
        stack: 'intensity',
      };
    }

    var datasets = [
      buildDataset('low',      'Low'),
      buildDataset('moderate', 'Moderate'),
      buildDataset('high',     'High'),
    ];

    if (intensityChart) { intensityChart.destroy(); intensityChart = null; }
    intensityChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 3,
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: { boxWidth: 12, font: { size: 12 }, color: '#6b7280' },
          },
          tooltip: {
            backgroundColor: '#1f2937',
            titleColor: '#fff',
            bodyColor: '#fff',
            cornerRadius: 4,
            padding: 8,
            callbacks: {
              title: function (items) {
                var idx = items[0].dataIndex;
                if (idx === sessionCount) return '';       // gap
                if (idx === sessionCount + 1) return '28-day rolling window';
                var s = sessions[idx];
                return s ? (s.name + ' · ' + s.date) : '';
              },
              label: function (item) {
                var val = item.raw;
                if (val === 0) return null;
                return item.dataset.label + ': ' + val.toFixed(1) + '%';
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#6b7280',
              font: { size: 11 },
              maxRotation: 45,
              callback: function (value, index) {
                // Hide the gap-bar label
                return index === sessionCount ? '' : this.getLabelForValue(index);
              },
            },
          },
          y: {
            stacked: true,
            min: 0,
            max: 100,
            grid: { color: 'rgba(0,0,0,0.06)' },
            ticks: { color: '#6b7280', font: { size: 11 }, callback: function (v) { return v + '%'; } },
            title: { display: true, text: 'Time in zone (%)', color: '#6b7280', font: { size: 12 } },
          },
        },
      },
    });
  }

  function loadIntensityChart(win) {
    var bodyEl = document.getElementById('slot-intensity-body');
    if (!bodyEl) return;
    showLoading(bodyEl);
    if (intensityChart) { intensityChart.destroy(); intensityChart = null; }
    if (!win.from || !win.to) { showEmpty(bodyEl); return; }

    fetch('/api/workouts/intensity-distribution?from=' + win.from + '&to=' + win.to)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) { renderIntensityChart(bodyEl, data); })
      .catch(function () {
        bodyEl.innerHTML = '<div class="slot-empty"><div class="slot-empty-text">Could not load intensity data</div></div>';
      });
  }

  // ── Main data loader ──────────────────────────────────────────────────────────

  function loadChartData(state) {
    if (!_userId) return;

    const win = resolveDateWindow(state);
    const hasValidWindow = win.from && win.to && win.from <= win.to;

    const readinessBodyEl = document.getElementById('slot-readiness-body');
    const hrvBodyEl = document.getElementById('slot-hrv-body');
    const rhrBodyEl = document.getElementById('slot-rhr-body');
    const semBodyEl = document.getElementById('slot-sem-body');
    const tssBodyEl = document.getElementById('slot-tss-body');

    showLoading(readinessBodyEl);
    showLoading(hrvBodyEl);
    showLoading(rhrBodyEl);
    showLoading(semBodyEl);
    showLoading(tssBodyEl);
    if (tssOverlayChart) { tssOverlayChart.destroy(); tssOverlayChart = null; }
    if (semChart) { semChart.destroy(); semChart = null; }
    if (hrvSubChart) { hrvSubChart.destroy(); hrvSubChart = null; }
    if (rhrSubChart) { rhrSubChart.destroy(); rhrSubChart = null; }
    emptyBanner.hidden = true;

    if (!hasValidWindow) {
      showEmpty(readinessBodyEl);
      showEmpty(hrvBodyEl);
      showEmpty(rhrBodyEl);
      showEmpty(semBodyEl);
      showTSSEmpty(tssBodyEl);
      showEmpty(document.getElementById('slot-intensity-body'));
      emptyBanner.hidden = false;
      return;
    }

    loadIntensityChart(win);

    fetchSummary(state)
      .then(summary => {
        const today = toLocalDateStr(new Date());
        renderReadinessFromSummary(readinessBodyEl, summary);
        renderHrvChart(hrvBodyEl, summary.hrv, today);
        renderRhrChart(rhrBodyEl, summary.rhr, today);
        renderSEMFromSummary(semBodyEl, summary);
        renderTSSFromSummary(tssBodyEl, summary);
      })
      .catch(() => renderMockFallback(state));
  }

  // ── Event handlers ────────────────────────────────────────────────────────────

  const applyBtn  = document.getElementById('custom-apply');
  const cancelBtn = document.getElementById('custom-cancel');
  const rangeErr  = document.getElementById('custom-range-error');

  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const range = btn.dataset.range;
      if (range === 'custom') {
        openCustomPicker();
      } else {
        commitState({ type: 'preset', preset: range });
      }
    });
  });

  applyBtn?.addEventListener('click', () => {
    const from = fromInput.value;
    const to   = toInput.value;
    if (!from || !to) {
      rangeErr.textContent = 'Please select both a From and To date.';
      rangeErr.hidden = false;
      return;
    }
    if (from > to) {
      rangeErr.textContent = '"From" must not be after "To".';
      rangeErr.hidden = false;
      return;
    }
    rangeErr.textContent = '';
    rangeErr.hidden = true;
    commitState({ type: 'custom', from, to });
  });

  cancelBtn?.addEventListener('click', () => {
    closeCustomPicker();
    if (_confirmedState) setActiveChip(_confirmedState);
  });

  // ── SEM toggle handlers ───────────────────────────────────────────────────────

  document.getElementById('btn-toggle-energy')?.addEventListener('click', () => {
    _semEnergyVisible = !_semEnergyVisible;
    updateSEMVisibility();
  });

  document.getElementById('btn-toggle-mood')?.addEventListener('click', () => {
    _semMoodVisible = !_semMoodVisible;
    updateSEMVisibility();
  });

  document.getElementById('btn-toggle-weekly-avg')?.addEventListener('click', () => {
    _semWeeklyAvgVisible = !_semWeeklyAvgVisible;
    updateSEMVisibility();
  });

  // ── Boot ─────────────────────────────────────────────────────────────────────

  const _initialState = readRangeFromURL();
  // Seed _lastPresetState from the URL so Cancel works correctly on page load
  if (_initialState.type === 'preset') {
    _lastPresetState = _initialState;
  }

  window.addEventListener('userReady', e => {
    _userId = e.detail.userId;
    applyRangeState(_initialState);
  });

  window.addEventListener('userChanged', e => {
    _userId = e.detail.userId;
    applyRangeState(readRangeFromURL());
  });
})();
