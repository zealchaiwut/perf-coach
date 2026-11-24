(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };
  var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var TAPER_CHIPS = [
    { weeks: 1, factors: [0.70], label: '1 week \u00b7 70%' },
    { weeks: 2, factors: [0.75, 0.55], label: '2 weeks \u00b7 75% \u2192 55%' },
    { weeks: 3, factors: [0.85, 0.70, 0.50], label: '3 weeks \u00b7 85% \u2192 70% \u2192 50%' },
  ];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var state = {};
  var ui = { shape: 'standard', taperMode: 2, customFactors: [0.75, 0.55] };

  function fmtDayMon(iso) {
    var p = String(iso || '').slice(0, 10).split('-');
    var m = parseInt(p[1], 10);
    if (!m) return iso || '';
    return parseInt(p[2], 10) + ' ' + MONTHS[m - 1];
  }
  function mondayISO(iso) {
    var p = String(iso || '').slice(0, 10).split('-').map(Number);
    if (!p[1]) return iso;
    var d = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
    var day = d.getUTCDay();
    d.setUTCDate(d.getUTCDate() + (day === 0 ? -6 : 1 - day));
    return d.toISOString().slice(0, 10);
  }
  function factorsKey(factors) {
    return (factors || []).map(function (x) { return Math.round(Number(x) * 100); }).join(',');
  }
  function inferShape(s) {
    var taperN = (s.taper_factors || []).length;
    if (s.peak_hold_weeks === 0) return 'short';
    if (s.peak_hold_weeks === 2 && taperN === 2) return 'standard';
    return 'custom';
  }
  function inferTaperMode(factors) {
    var k = factorsKey(factors);
    if (k === '70') return 1;
    if (k === '75,55') return 2;
    if (k === '85,70,50') return 3;
    return 'custom';
  }
  function restDays() {
    var out = [];
    document.querySelectorAll('[data-rest-day]').forEach(function (b) {
      if (b.getAttribute('aria-pressed') === 'true') out.push(parseInt(b.getAttribute('data-rest-day'), 10));
    });
    return out;
  }
  function taperFactorsFromForm() {
    if (ui.taperMode === 'custom') {
      var inputs = document.querySelectorAll('#ps-taper-custom input');
      var vals = [];
      inputs.forEach(function (el) {
        var n = parseFloat(el.value, 10);
        if (!isNaN(n) && n > 0) vals.push(n > 1 ? n / 100 : n);
      });
      return vals.length ? vals : ui.customFactors;
    }
    var chip = TAPER_CHIPS.find(function (c) { return c.weeks === ui.taperMode; });
    return chip ? chip.factors.slice() : [0.75, 0.55];
  }
  function bodyFromForm() {
    var ramp = 0.05;
    var on = document.querySelector('[data-ramp].is-on');
    if (on) ramp = parseFloat(on.getAttribute('data-ramp'), 10);
    var peak = document.getElementById('ps-peak-tss').value.trim();
    return {
      ramp_pct: ramp,
      build_weeks: parseInt(document.getElementById('ps-build').value, 10),
      peak_hold_weeks: parseInt(document.getElementById('ps-peak-weeks').value, 10),
      peak_tss: peak === '' ? null : parseFloat(peak, 10),
      taper_factors: taperFactorsFromForm(),
      race_week_factor: parseFloat(document.getElementById('ps-race-factor').value, 10),
      recover_weeks: parseInt(document.getElementById('ps-recover').value, 10),
      rebuild_weeks: parseInt(document.getElementById('ps-rebuild').value, 10),
      a_race_id: document.getElementById('ps-race').value || null,
      block_start: document.getElementById('ps-block-start').value || null,
      max_consecutive_days: parseInt(document.getElementById('ps-max-consec').value, 10),
      rest_days: restDays(),
      shape: ui.shape,
      taper_weeks: taperFactorsFromForm().length,
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

  function stepper(id, val, min, max) {
    return '<div class="rv-wiz-stepper">' +
      '<button type="button" class="rv-wiz-sq" data-spin="' + id + '" data-dir="-1" aria-label="Fewer">\u2212</button>' +
      '<input type="hidden" id="' + id + '" value="' + esc(String(val)) + '">' +
      '<span class="rv-wiz-stepper__val" data-spin-val="' + id + '">' + esc(String(val)) + '</span>' +
      '<button type="button" class="rv-wiz-sq" data-spin="' + id + '" data-dir="1" aria-label="More">+</button></div>';
  }

  function renderForm(s) {
    var host = document.getElementById('v2-plan-settings-form');
    if (!host) return;
    ui.shape = inferShape(s);
    ui.taperMode = inferTaperMode(s.taper_factors);
    ui.customFactors = (s.taper_factors || [0.75, 0.55]).slice();
    var rest = s.rest_days || [];
    var raceCards = (s.upcoming_races || []).map(function (r) {
      var on = s.a_race_id === r.id;
      var dis = r.too_short;
      var tag = (r.priority || '') + ' \u00b7 ' + fmtDayMon(r.race_date).toUpperCase();
      return '<button type="button" class="rv-wiz-card' + (on ? ' is-on' : '') + (dis ? ' is-disabled' : '') + '"' +
        (dis ? ' aria-disabled="true"' : '') + ' data-pick-race="' + esc(r.id) + '">' +
        '<span class="rv-wiz-card__top">' + esc(r.name) + '<span class="rv-wiz-tag">' + esc(tag) + '</span></span>' +
        '<span class="rv-wiz-card__blurb">' + esc(dis ? (r.disabled_reason || 'Too short') : (r.weeks_away + ' weeks away')) + '</span></button>';
    }).join('') || '<p class="rv-subtitle">No upcoming races. Add one from Training \u00b7 Plan.</p>';
    var shapes = [
      { id: 'standard', title: 'Standard', blurb: 'Build, 2-week peak hold, 2-week taper.' },
      { id: 'short', title: 'Short', blurb: 'Build then taper. Best under 8 weeks.' },
      { id: 'custom', title: 'Custom', blurb: 'Set the weeks per phase yourself.' },
    ];
    var shapeCards = shapes.map(function (sh) {
      var on = ui.shape === sh.id;
      return '<button type="button" role="radio" class="rv-wiz-card' + (on ? ' is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-shape="' + sh.id + '">' +
        '<span class="rv-wiz-card__top">' + esc(sh.title) + '</span><span class="rv-wiz-card__blurb">' + esc(sh.blurb) + '</span></button>';
    }).join('');
    var rampPct = s.ramp_pct != null ? s.ramp_pct : 0.05;
    var segs = [
      { pct: 0.03, label: 'Gentle 3%' },
      { pct: 0.05, label: 'Standard 5%' },
      { pct: 0.07, label: 'Aggressive 7%' },
    ].map(function (r) {
      var on = Math.abs(rampPct - r.pct) < 0.001;
      return '<button type="button" role="radio" class="' + (on ? 'is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-ramp="' + r.pct + '">' + esc(r.label) + '</button>';
    }).join('');
    var taperBtns = TAPER_CHIPS.map(function (c) {
      var on = ui.taperMode === c.weeks;
      return '<button type="button" role="radio" class="rv-race-modal__chip rv-wiz-chip' + (on ? ' is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-taper="' + c.weeks + '">' + esc(c.label) + '</button>';
    }).join('') +
      '<button type="button" role="radio" class="rv-race-modal__chip rv-wiz-chip' + (ui.taperMode === 'custom' ? ' is-on' : '') + '" aria-checked="' + (ui.taperMode === 'custom' ? 'true' : 'false') + '" data-taper="custom">Custom</button>';
    var customInputs = ui.customFactors.map(function (f, i) {
      return '<label class="rv-race-modal__label">Week ' + (i + 1) +
        '<input class="rv-race-modal__input rv-race-modal__input--mono" type="number" min="1" max="100" step="1" value="' + esc(String(Math.round(Number(f) * 100))) + '"></label>';
    }).join('');
    var restBtns = DAYS.map(function (label, i) {
      var on = rest.indexOf(i) >= 0;
      return '<button type="button" class="rv-wiz-day" data-rest-day="' + i + '" aria-pressed="' + (on ? 'true' : 'false') + '">' + label + '</button>';
    }).join('');
    host.innerHTML =
      '<form id="ps-form" class="rv-stack">' +
      '<input type="hidden" id="ps-race" value="' + esc(s.a_race_id || '') + '">' +
      '<section class="rv-wiz-section"><h2 class="rv-label">Race</h2>' +
      '<div style="display:flex;flex-direction:column;gap:8px">' + raceCards + '</div></section>' +
      '<section class="rv-wiz-section"><h2 class="rv-label">Shape</h2>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="ps-block-start">Block starts <span class="rv-race-modal__hint">a Monday</span></label>' +
      '<input type="date" id="ps-block-start" class="rv-race-modal__input rv-race-modal__input--mono" value="' + esc(s.block_start || '') + '"></div>' +
      '<div class="rv-wiz-shapes" role="radiogroup" aria-label="Shape">' + shapeCards + '</div>' +
      '<div class="rv-wiz-steppers">' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Build weeks</span>' + stepper('ps-build', s.build_weeks || 8, 3, 30) + '</div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Peak-hold weeks</span>' + stepper('ps-peak-weeks', s.peak_hold_weeks || 0, 0, 8) + '</div>' +
      '</div>' +
      '<div class="rv-wiz-steppers">' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Recover weeks</span>' + stepper('ps-recover', s.recover_weeks || 1, 0, 4) + '</div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Rebuild weeks</span>' + stepper('ps-rebuild', s.rebuild_weeks || 4, 0, 12) + '</div>' +
      '</div></section>' +
      '<section class="rv-wiz-section"><h2 class="rv-label">Load</h2>' +
      '<div class="rv-wiz-tile rv-wiz-tile--row"><span class="rv-subtitle">Starting point \u00b7 your last 28 days</span>' +
      '<span class="rv-mono" style="font-weight:700">' + esc(String(Math.round(s.chronic_weekly_tss || 0))) + ' TSS/wk</span></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Weekly ramp</span>' +
      '<div class="rv-race-modal__seg rv-wiz-seg" role="radiogroup" aria-label="Weekly ramp">' + segs + '</div></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Taper</span>' +
      '<div role="radiogroup" aria-label="Taper" style="display:flex;gap:6px;flex-wrap:wrap">' + taperBtns + '</div>' +
      '<div id="ps-taper-custom" class="rv-wiz-steppers" ' + (ui.taperMode === 'custom' ? '' : 'hidden') + '>' + customInputs + '</div></div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="ps-peak-tss">Peak TSS <span class="rv-race-modal__hint">blank = from chronic</span></label>' +
      '<input type="number" id="ps-peak-tss" class="rv-race-modal__input rv-race-modal__input--mono" value="' + esc(s.peak_tss != null ? String(s.peak_tss) : '') + '"></div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="ps-race-factor">Race / recover factor</label>' +
      '<input type="number" id="ps-race-factor" class="rv-race-modal__input rv-race-modal__input--mono" step="0.05" min="0.1" max="1" value="' + esc(String(s.race_week_factor || 0.4)) + '"></div></section>' +
      '<section class="rv-wiz-section"><h2 class="rv-label">Your week</h2>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Rest days</span>' +
      '<div class="rv-wiz-days" role="group" aria-label="Rest days">' + restBtns + '</div></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Most training days in a row</span>' +
      stepper('ps-max-consec', s.max_consecutive_days || 3, 1, 6) + '</div></section>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" id="ps-preview">Preview changes</button>' +
      '<button type="submit" class="rv-btn">Save</button></div>' +
      '<p class="rv-subtitle" id="ps-status"></p></form>';
    bindForm();
  }

  function setSpin(id, val) {
    var hid = document.getElementById(id);
    var lab = document.querySelector('[data-spin-val="' + id + '"]');
    if (hid) hid.value = String(val);
    if (lab) lab.textContent = String(val);
  }

  function bindForm() {
    document.querySelectorAll('[data-pick-race]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.getAttribute('aria-disabled') === 'true') return;
        document.getElementById('ps-race').value = b.getAttribute('data-pick-race');
        document.querySelectorAll('[data-pick-race]').forEach(function (x) { x.classList.remove('is-on'); });
        b.classList.add('is-on');
      });
    });
    document.querySelectorAll('[data-shape]').forEach(function (b) {
      b.addEventListener('click', function () {
        ui.shape = b.getAttribute('data-shape');
        document.querySelectorAll('[data-shape]').forEach(function (x) {
          var on = x === b;
          x.classList.toggle('is-on', on);
          x.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        applyShapeFit();
      });
    });
    document.querySelectorAll('[data-ramp]').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('[data-ramp]').forEach(function (x) {
          var on = x === b;
          x.classList.toggle('is-on', on);
          x.setAttribute('aria-checked', on ? 'true' : 'false');
        });
      });
    });
    document.querySelectorAll('[data-taper]').forEach(function (b) {
      b.addEventListener('click', function () {
        var raw = b.getAttribute('data-taper');
        ui.taperMode = raw === 'custom' ? 'custom' : parseInt(raw, 10);
        document.querySelectorAll('[data-taper]').forEach(function (x) {
          var on = x === b;
          x.classList.toggle('is-on', on);
          x.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        var box = document.getElementById('ps-taper-custom');
        if (box) box.hidden = ui.taperMode !== 'custom';
      });
    });
    document.querySelectorAll('[data-rest-day]').forEach(function (b) {
      b.addEventListener('click', function () {
        var on = b.getAttribute('aria-pressed') !== 'true';
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    });
    document.querySelectorAll('[data-spin]').forEach(function (b) {
      b.addEventListener('click', function () {
        var id = b.getAttribute('data-spin');
        var dir = parseInt(b.getAttribute('data-dir'), 10);
        var bounds = { 'ps-build': [3, 30], 'ps-peak-weeks': [0, 8], 'ps-recover': [0, 4], 'ps-rebuild': [0, 12], 'ps-max-consec': [1, 6] };
        var hid = document.getElementById(id);
        var cur = parseInt(hid.value, 10) || 0;
        var bd = bounds[id] || [0, 99];
        setSpin(id, Math.max(bd[0], Math.min(bd[1], cur + dir)));
      });
    });
    var start = document.getElementById('ps-block-start');
    if (start) start.addEventListener('change', function () {
      start.value = mondayISO(start.value);
    });
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
      var body = bodyFromForm();
      var raceBtn = document.querySelector('[data-pick-race].is-on');
      var promote = Promise.resolve();
      if (raceBtn) {
        var rec = (state.upcoming_races || []).find(function (r) { return r.id === raceBtn.getAttribute('data-pick-race'); });
        if (rec && rec.priority !== 'A') {
          promote = fetch('/api/races/' + encodeURIComponent(rec.id), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ priority: 'A', role: 'a_race' }),
          });
        }
      }
      promote.then(function () {
        return fetch('/api/plan/revamp-settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(body),
        });
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

  function applyShapeFit() {
    var start = document.getElementById('ps-block-start').value;
    var race = (state.upcoming_races || []).find(function (r) { return r.id === document.getElementById('ps-race').value; });
    if (!race || !start) return;
    var a = Date.parse(mondayISO(start) + 'T00:00:00Z');
    var b = Date.parse(mondayISO(race.race_date) + 'T00:00:00Z');
    var weeks = (isNaN(a) || isNaN(b) || b < a) ? 0 : Math.floor((b - a) / 86400000 / 7) + 1;
    if (!weeks) return;
    var body = { weeks_available: weeks, shape: ui.shape, taper_weeks: taperFactorsFromForm().length };
    if (ui.shape === 'custom') {
      body.build_weeks = parseInt(document.getElementById('ps-build').value, 10);
      body.peak_hold_weeks = parseInt(document.getElementById('ps-peak-weeks').value, 10);
    }
    fetch('/api/plan/revamp-settings/fit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (fit) {
      if (!fit) return;
      setSpin('ps-build', fit.build_weeks);
      setSpin('ps-peak-weeks', fit.peak_hold_weeks);
    });
  }

  function renderOverrides(rows) {
    var host = document.getElementById('v2-plan-overrides');
    if (!host) return;
    if (!rows || !rows.length) {
      host.innerHTML = '<h2 class="rv-title">Gym overrides</h2><p class="rv-subtitle">None yet. Finish a gym session with Use these in future to store them.</p>';
      return;
    }
    host.innerHTML = '<h2 class="rv-title">Gym overrides</h2>' + rows.map(function (r) {
      var ov = r.override || {};
      var detail = ov.replacement ? ('→ ' + ov.replacement) : (ov.kg != null ? (ov.kg + ' kg') : JSON.stringify(ov));
      return '<div class="rv-row" data-override-id="' + r.id + '"><span>' + esc(r.template_key) +
        ' · ' + esc(r.exercise_key) + ' ' + esc(detail) +
        '</span><button type="button" class="rv-btn rv-btn--secondary" data-remove-override="' + r.id +
        '">Remove</button></div>';
    }).join('');
    host.querySelectorAll('[data-remove-override]').forEach(function (b) {
      b.addEventListener('click', function () {
        fetch('/api/plan/template-overrides/' + encodeURIComponent(b.getAttribute('data-remove-override')), {
          method: 'DELETE',
          credentials: 'same-origin',
        }).then(function () { loadOverrides(); });
      });
    });
  }

  function loadOverrides() {
    fetch('/api/plan/template-overrides', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { overrides: [] }; })
      .then(function (data) { renderOverrides((data && data.overrides) || []); })
      .catch(function () { renderOverrides([]); });
  }

  function init() {
    fetch('/api/plan/revamp-settings', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state = data;
        renderForm(data);
        loadOverrides();
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
