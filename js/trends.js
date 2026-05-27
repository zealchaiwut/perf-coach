(() => {
  const PRESETS = ['7d', '30d', '90d'];
  const DEFAULT_PRESET = '30d';

  const presetBtns = document.querySelectorAll('.range-btn[data-range]');
  const customInputs = document.getElementById('custom-range-inputs');
  const fromInput = document.getElementById('range-from');
  const toInput = document.getElementById('range-to');
  const emptyBanner = document.getElementById('trends-empty-banner');

  const slots = [
    { id: 'slot-readiness-body' },
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
    // Update preset buttons
    presetBtns.forEach(btn => {
      const isActive =
        state.type === 'preset'
          ? btn.dataset.range === state.preset
          : btn.dataset.range === 'custom';
      btn.classList.toggle('active', isActive);
    });

    // Show/hide custom inputs
    const isCustom = state.type === 'custom';
    customInputs.hidden = !isCustom;
    if (isCustom) {
      if (state.from) fromInput.value = state.from;
      if (state.to) toInput.value = state.to;
    }

    writeRangeToURL(state);
    loadChartData(state);
  }

  // ── Chart slot state ─────────────────────────────────────────────────────────

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

  // Resolve the date window for the current range state
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

  // Placeholder: sibling issues will replace showEmpty with real chart renders.
  // For now, simulate an async data check and display empty state.
  function loadChartData(state) {
    const window = resolveDateWindow(state);
    const hasValidWindow = window.from && window.to && window.from <= window.to;

    // Show loading spinners in every slot
    slots.forEach(({ id }) => showLoading(document.getElementById(id)));
    emptyBanner.hidden = true;

    if (!hasValidWindow) {
      slots.forEach(({ id }) => showEmpty(document.getElementById(id)));
      emptyBanner.hidden = false;
      return;
    }

    // Simulate async fetch — sibling issues will swap this out for real calls.
    setTimeout(() => {
      // No real data yet; show empty state in each slot
      slots.forEach(({ id }) => showEmpty(document.getElementById(id)));
      emptyBanner.hidden = false;
    }, 600);
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
