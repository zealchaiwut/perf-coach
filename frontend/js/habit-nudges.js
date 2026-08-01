// ── Adherence & Nudges Panel ───────────────────────────────────────────────────
// Fetches /api/adherence-nudges and renders slipping-habit nudges in
// #nudges-panel (issue #1602 — the endpoint was fully implemented and tested
// with zero frontend callers). Modeled on habit-insights.js: same panel
// shape, same loading/building/error states, so the two panels read as one
// family rather than two different UI patterns on the same page.

(function () {
  'use strict';

  const contentEl = () => document.getElementById('nudges-body');

  // Delegates to the shared escaper (issue #1603) rather than a local copy.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _renderLoading() {
    const el = contentEl();
    if (!el) return;
    el.innerHTML = '<div class="insights-loading"><span class="insights-spinner"></span> Loading…</div>';
  }

  function _renderError(msg) {
    const el = contentEl();
    if (!el) return;
    el.innerHTML = `<div class="insights-error" role="alert">${esc(msg || 'Could not load nudges.')}</div>`;
  }

  function _renderBuilding(reason) {
    const el = contentEl();
    if (!el) return;
    el.innerHTML =
      '<div class="insights-building">' +
        '<span class="insights-building-icon">📈</span>' +
        '<p class="insights-building-msg">Still building your adherence picture.</p>' +
        '<p class="insights-building-sub">' +
          esc(reason || "Keep logging — nudges appear once there's enough history.") +
        '</p>' +
      '</div>';
  }

  function _renderNudges(data) {
    const el = contentEl();
    if (!el) return;

    const nudges = Array.isArray(data.nudges) ? data.nudges : [];
    const slipping = Array.isArray(data.slipping_habits) ? data.slipping_habits : [];

    if (!nudges.length && !slipping.length) {
      el.innerHTML = '<div class="insights-empty">No slipping habits — adherence looks steady.</div>';
      return;
    }

    const slipRows = slipping.map(h => {
      const drop = typeof h.drop === 'number' ? h.drop.toFixed(0) : '?';
      return (
        '<div class="nudge-slip-row">' +
          '<span class="nudge-slip-name">' + esc(h.name || '') + '</span>' +
          '<span class="nudge-slip-drop">-' + drop + 'pp vs. prior period</span>' +
        '</div>'
      );
    }).join('');

    const nudgeCards = nudges.map(n =>
      '<div class="insight-card"><div class="insight-line">' + esc(n) + '</div></div>'
    ).join('');

    el.innerHTML =
      (slipRows ? '<div class="nudge-slip-list">' + slipRows + '</div>' : '') +
      (nudgeCards ? '<div class="insights-cards" style="margin-top:10px">' + nudgeCards + '</div>' : '');
  }

  async function loadNudges() {
    _renderLoading();

    try {
      const res = await fetch('/api/adherence-nudges');
      if (res.status === 401 || res.status === 403) {
        // Page-level auth redirect (nav.js/user.js) owns this case.
        return;
      }
      if (!res.ok) {
        _renderError(`Error ${res.status}: could not load nudges.`);
        return;
      }
      const data = await res.json();

      if (data.building_state && data.building_state.active) {
        _renderBuilding(data.building_state.reason);
        return;
      }

      _renderNudges(data);
    } catch (err) {
      _renderError('Failed to load nudges: ' + err.message);
    }
  }

  // Expose so habits.js can call after log mutations (mirrors HabitInsights).
  window.HabitNudges = { load: loadNudges };

  // Boot on userReady (same lifecycle as habit-insights.js).
  window.addEventListener('userReady', loadNudges);
  window.addEventListener('userChanged', loadNudges);
})();
