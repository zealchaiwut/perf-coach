// ── Habit Insights Panel ──────────────────────────────────────────────────────
// Fetches /api/habits/insights and renders the panel in #insights-panel.

(function () {
  'use strict';

  const panelEl = () => document.getElementById('insights-panel');
  const contentEl = () => document.getElementById('insights-body');

  function _outcomeLabel(name) {
    return name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  function _renderLoading() {
    const el = contentEl();
    if (!el) return;
    el.innerHTML = '<div class="insights-loading"><span class="insights-spinner"></span> Loading…</div>';
  }

  function _renderError(msg) {
    const el = contentEl();
    if (!el) return;
    el.innerHTML = `<div class="insights-error" role="alert">${msg || 'Could not load insights.'}</div>`;
  }

  function _renderBuilding(reason) {
    const el = contentEl();
    if (!el) return;
    el.innerHTML =
      '<div class="insights-building">' +
        '<span class="insights-building-icon">📊</span>' +
        '<p class="insights-building-msg">Still learning your patterns.</p>' +
        '<p class="insights-building-sub">Keep logging — insights appear once there\'s enough data to detect a reliable association.</p>' +
      '</div>';
  }

  function _strengthLabel(r) {
    const abs = Math.abs(r);
    if (abs >= 0.5) return 'strong';
    if (abs >= 0.3) return 'moderate';
    return 'weak';
  }

  function _renderCards(insights) {
    const el = contentEl();
    if (!el) return;

    if (!insights.length) {
      el.innerHTML = '<div class="insights-empty">No confident associations found yet.</div>';
      return;
    }

    const cards = insights.map(insight => {
      const r = typeof insight.coefficient === 'number' ? insight.coefficient : 0;
      const pct = Math.min(100, Math.round(Math.abs(r) * 100));
      const direction = r >= 0 ? 'positive' : 'negative';
      const strength = _strengthLabel(r);
      const outcome = _outcomeLabel(insight.outcome_name || '');
      const line = insight.line || `Logging '${insight.habit_name}' is associated with ${outcome}.`;

      return `<div class="insight-card">
  <div class="insight-line">${line}</div>
  <div class="insight-indicator">
    <div class="insight-bar-outer" title="r = ${r.toFixed(2)}">
      <div class="insight-bar-fill insight-bar-${direction}" style="width:${pct}%"></div>
    </div>
    <span class="insight-coeff insight-coeff-${strength}">r = ${r.toFixed(2)}</span>
  </div>
</div>`;
    }).join('');

    el.innerHTML = cards;
  }

  async function loadInsights() {
    _renderLoading();

    try {
      const res = await fetch('/api/habits/insights');
      if (!res.ok) {
        _renderError(`Error ${res.status}: could not load insights.`);
        return;
      }
      const data = await res.json();

      if (data.building) {
        _renderBuilding(data.reason);
        return;
      }

      _renderCards(data.insights || []);
    } catch (err) {
      const el = contentEl();
      if (el) {
        el.innerHTML = `<div class="insights-error" role="alert">Failed to load insights: ${err.message}</div>`;
      }
    }
  }

  // Expose so habits.js can call after log mutations
  window.HabitInsights = { load: loadInsights };

  // Boot on userReady (same lifecycle as habits.js)
  window.addEventListener('userReady', loadInsights);
  window.addEventListener('userChanged', loadInsights);
})();
