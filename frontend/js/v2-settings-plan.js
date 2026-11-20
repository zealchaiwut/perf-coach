(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };
  var state = {};

  function bodyFromForm() {
    var ramp = parseFloat(document.getElementById('ps-ramp').value, 10) / 100;
    var taperRaw = document.getElementById('ps-taper').value.split(',').map(function (x) { return parseFloat(x.trim(), 10); })
      .filter(function (x) { return !isNaN(x); });
    var rest = [];
    document.querySelectorAll('[data-rest-day]').forEach(function (cb) {
      if (cb.checked) rest.push(parseInt(cb.getAttribute('data-rest-day'), 10));
    });
    var peak = document.getElementById('ps-peak-tss').value.trim();
  return {
      ramp_pct: ramp,
      build_weeks: parseInt(document.getElementById('ps-build').value, 10),
      peak_hold_weeks: parseInt(document.getElementById('ps-peak-weeks').value, 10),
      peak_tss: peak === '' ? null : parseFloat(peak, 10),
      taper_factors: taperRaw,
      race_week_factor: parseFloat(document.getElementById('ps-race-factor').value, 10),
      recover_weeks: parseInt(document.getElementById('ps-recover').value, 10),
      rebuild_weeks: parseInt(document.getElementById('ps-rebuild').value, 10),
      a_race_id: document.getElementById('ps-race').value || null,
      block_start: document.getElementById('ps-block-start').value || null,
      max_consecutive_days: parseInt(document.getElementById('ps-max-consec').value, 10),
      rest_days: rest,
    };
  }

  function renderPreview(data) {
    var host = document.getElementById('v2-plan-settings-preview');
    if (!host) return;
    if (!data.allowed) {
      host.hidden = false;
      var err = data.layout_error || {};
      host.innerHTML = '<p class="rv-warn" style="color:#b91c1c">' + esc(err.message || 'Settings blocked') + '</p>';
      return;
    }
    var rows = (data.weeks || []).filter(function (w) { return w.changes; });
    if (!rows.length) {
      host.hidden = false;
      host.innerHTML = '<p class="rv-subtitle">No future weeks change with these values.</p>';
      return;
    }
    var html = ['<h2 class="rv-label">Preview</h2><table class="rv-subtitle"><thead><tr><th>Week</th><th>Before</th><th>After</th></tr></thead><tbody>'];
    rows.forEach(function (w) {
      html.push('<tr><td>' + esc(w.week_start) + '</td><td>' + esc(String(w.before_target_tss)) + '</td><td>' + esc(String(w.after_target_tss)) + '</td></tr>');
    });
    html.push('</tbody></table>');
    host.innerHTML = html.join('');
    host.hidden = false;
  }

  function renderForm(s) {
    var host = document.getElementById('v2-plan-settings-form');
    if (!host) return;
    var raceOpts = (s.upcoming_races || []).map(function (r) {
      var sel = s.a_race_id === r.id ? ' selected' : '';
      return '<option value="' + esc(r.id) + '"' + sel + '>' + esc(r.name) + ' · ' + esc(r.race_date) + '</option>';
    }).join('');
    var days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var restChips = days.map(function (label, i) {
      var on = (s.rest_days || []).indexOf(i) >= 0;
      return '<label><input type="checkbox" data-rest-day="' + i + '"' + (on ? ' checked' : '') + '> ' + label + '</label>';
    }).join(' ');
    host.innerHTML =
      '<form id="ps-form" class="rv-stack">' +
      '<label class="rv-label">A race<select id="ps-race" class="rv-input">' + raceOpts + '</select></label>' +
      '<label class="rv-label">Block start (Monday)<input type="date" id="ps-block-start" class="rv-input" value="' + esc(s.block_start || '') + '"></label>' +
      '<label class="rv-label">Ramp % / week<input type="number" id="ps-ramp" class="rv-input" step="1" min="1" max="25" value="' + esc(String(Math.round((s.ramp_pct || 0.05) * 100))) + '"></label>' +
      '<label class="rv-label">Build weeks<input type="number" id="ps-build" class="rv-input" min="1" max="30" value="' + esc(String(s.build_weeks || 8)) + '"></label>' +
      '<label class="rv-label">Peak-hold weeks<input type="number" id="ps-peak-weeks" class="rv-input" min="0" max="8" value="' + esc(String(s.peak_hold_weeks || 4)) + '"></label>' +
      '<label class="rv-label">Peak TSS (blank = from chronic ' + esc(String(s.chronic_weekly_tss || '')) + ')<input type="number" id="ps-peak-tss" class="rv-input" value="' + esc(s.peak_tss != null ? String(s.peak_tss) : '') + '"></label>' +
      '<label class="rv-label">Taper factors (comma-separated)<input type="text" id="ps-taper" class="rv-input" value="' + esc((s.taper_factors || []).join(', ')) + '"></label>' +
      '<label class="rv-label">Race / recover factor<input type="number" id="ps-race-factor" class="rv-input" step="0.05" min="0.1" max="1" value="' + esc(String(s.race_week_factor || 0.4)) + '"></label>' +
      '<label class="rv-label">Recover weeks<input type="number" id="ps-recover" class="rv-input" min="0" max="4" value="' + esc(String(s.recover_weeks || 1)) + '"></label>' +
      '<label class="rv-label">Rebuild weeks<input type="number" id="ps-rebuild" class="rv-input" min="0" max="12" value="' + esc(String(s.rebuild_weeks || 4)) + '"></label>' +
      '<fieldset class="rv-stack"><legend class="rv-label">Preferred rest days</legend>' + restChips + '</fieldset>' +
      '<label class="rv-label">Max consecutive training days<input type="number" id="ps-max-consec" class="rv-input" min="1" max="14" value="' + esc(String(s.max_consecutive_days || 3)) + '"></label>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" id="ps-preview">Preview changes</button>' +
      '<button type="submit" class="rv-btn">Save</button></div>' +
      '<p class="rv-subtitle" id="ps-status"></p></form>';
    document.getElementById('ps-preview').addEventListener('click', function () {
      fetch('/api/plan/revamp-settings/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(bodyFromForm()),
      }).then(function (r) { return r.json(); }).then(renderPreview);
    });
    document.getElementById('ps-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      fetch('/api/plan/revamp-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(bodyFromForm()),
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw d; });
        return r.json();
      }).then(function () {
        document.getElementById('ps-status').textContent = 'Saved.';
        window.location.href = '/v2/training/plan';
      }).catch(function (err) {
        var msg = (err && err.detail && err.detail.message) || (err && err.detail) || 'Save refused';
        document.getElementById('ps-status').textContent = typeof msg === 'string' ? msg : JSON.stringify(msg);
      });
    });
  }

  function init() {
    fetch('/api/plan/revamp-settings', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state = data;
        renderForm(data);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();