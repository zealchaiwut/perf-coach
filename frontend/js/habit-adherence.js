// ── Habit Adherence & Nudges Panel ────────────────────────────────────────────
// Fetches /api/habits/adherence and renders per-habit adherence, trend, and nudge
// copy into #adherence-panel.

(function () {
  'use strict';

  const panelEl  = () => document.getElementById('adherence-panel');
  const bodyEl   = () => document.getElementById('adherence-body');

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _barClass(pct) {
    if (pct >= 80) return 'adherence-bar-fill--high';
    if (pct >= 40) return 'adherence-bar-fill--mid';
    return 'adherence-bar-fill--low';
  }

  function _dayChip(label, type) {
    if (!label) return '';
    const cls = type === 'best'
      ? 'adherence-day-chip adherence-day-chip--best'
      : 'adherence-day-chip adherence-day-chip--worst';
    const prefix = type === 'best' ? '↑' : '↓';
    return `<span class="${cls}">${prefix} ${label}</span>`;
  }

  // ── Render functions ─────────────────────────────────────────────────────────

  function _renderSkeleton() {
    const el = bodyEl();
    if (!el) return;
    el.innerHTML =
      '<div class="adherence-skeleton-row adherence-skeleton"></div>' +
      '<div class="adherence-skeleton-row adherence-skeleton" style="width:85%"></div>';
  }

  function _renderBuilding() {
    const el = bodyEl();
    if (!el) return;
    el.innerHTML =
      '<div class="adherence-building">' +
        '<span class="adherence-building-icon" aria-hidden="true">🌱</span>' +
        '<p class="adherence-building-msg">Keep going — your streak is just getting started.</p>' +
        '<p class="adherence-building-sub">Log a few more days and your adherence picture will come into focus.</p>' +
      '</div>';
  }

  function _renderHabits(habits) {
    const el = bodyEl();
    if (!el) return;

    if (!habits.length) {
      el.innerHTML = '<div class="adherence-building"><p class="adherence-building-msg">No active habits yet.</p></div>';
      return;
    }

    const rows = habits.map(h => {
      const decliningClass = h.trend === 'declining' ? ' adherence-habit-row--declining' : '';
      const pct = typeof h.adherence_percent === 'number' ? h.adherence_percent : 0;
      const pctLabel = `${h.met_count} of ${h.scheduled_count} days`;
      const pctPct   = `${Math.round(pct)}%`;
      const barClass = _barClass(pct);
      const barWidth = Math.min(100, pct);

      const dayChips = [
        _dayChip(h.best_day, 'best'),
        _dayChip(h.worst_day, 'worst'),
      ].filter(Boolean).join('');

      const dayRow = dayChips
        ? `<div class="adherence-day-indicators">${dayChips}</div>`
        : '';

      const nudgeHtml = h.nudge
        ? `<p class="adherence-nudge">${_esc(h.nudge)}</p>`
        : '';

      return `<div class="adherence-habit-row${decliningClass}" role="region" aria-label="${_esc(h.habit_name)}">
  <div class="adherence-row-top">
    <span class="adherence-habit-name">${_esc(h.habit_name)}</span>
    <span class="adherence-pct-badge" title="${pctLabel}">${pctPct}</span>
  </div>
  <div class="adherence-bar-outer" role="progressbar" aria-valuenow="${Math.round(pct)}" aria-valuemin="0" aria-valuemax="100" aria-label="${pctLabel}">
    <div class="adherence-bar-fill ${barClass}" style="width:${barWidth}%"></div>
  </div>
  <div style="font-size:11px;color:var(--text-tertiary);margin-bottom:4px">${_esc(pctLabel)}</div>
  ${dayRow}
  ${nudgeHtml}
</div>`;
    }).join('');

    el.innerHTML = rows;
  }

  function _renderError() {
    // AC11: degrade gracefully — hide the panel, don't show an error banner
    const panel = panelEl();
    if (panel) panel.style.display = 'none';
  }

  // Simple HTML-escape to avoid XSS from server-returned strings
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Fetch & render ───────────────────────────────────────────────────────────

  async function loadAdherence() {
    _renderSkeleton();

    try {
      const res = await fetch('/api/habits/adherence');
      if (!res.ok) {
        _renderError();
        return;
      }
      const data = await res.json();

      if (data.building) {
        _renderBuilding();
        return;
      }

      _renderHabits(data.habits || []);
    } catch (_err) {
      _renderError();
    }
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  // Expose so habits.js can refresh after log mutations
  window.HabitAdherence = { load: loadAdherence };

  window.addEventListener('userReady',   loadAdherence);
  window.addEventListener('userChanged', loadAdherence);
})();
