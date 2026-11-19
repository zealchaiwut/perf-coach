(function (global) {
  'use strict';

  var esc = global.AppCommon ? global.AppCommon.escapeHtml.bind(global.AppCommon) : function (s) { return String(s); };
  var ids = [];
  var index = 0;
  var lastFocus = null;

  function els() {
    return {
      backdrop: document.getElementById('v2-drawer-backdrop'),
      drawer: document.getElementById('v2-drawer'),
      body: document.getElementById('v2-drawer-body'),
    };
  }

  function toast(msg) {
    var el = document.getElementById('v2-toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('is-visible');
    setTimeout(function () { el.classList.remove('is-visible'); }, 2800);
  }

  function close() {
    var e = els();
    if (!e.drawer) return;
    e.drawer.classList.remove('is-open');
    e.drawer.hidden = true;
    if (e.backdrop) {
      e.backdrop.classList.remove('is-open');
      e.backdrop.hidden = true;
    }
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function open(workoutId, allRunIds) {
    ids = allRunIds || [workoutId];
    index = Math.max(0, ids.indexOf(workoutId));
    lastFocus = document.activeElement;
    var e = els();
    if (e.backdrop) { e.backdrop.hidden = false; e.backdrop.classList.add('is-open'); }
    if (e.drawer) { e.drawer.hidden = false; e.drawer.classList.add('is-open'); }
    loadCurrent();
    if (e.backdrop) e.backdrop.onclick = close;
    document.addEventListener('keydown', onKey);
  }

  function onKey(ev) {
    if (ev.key === 'Escape') close();
  }

  function loadCurrent() {
    var id = ids[index];
    var e = els();
    if (!id || !e.body) return;
    e.body.innerHTML = '<p class="rv-section-state">Loading session…</p>';
    fetch('/api/workouts/' + encodeURIComponent(id) + '/full?streams=summary')
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) { render(data); })
      .catch(function () { e.body.innerHTML = '<p class="rv-section-state">Could not load session.</p>'; });
  }

  function render(data) {
    var w = data.workout || data;
    var tss = data.tss_block || { tss: data.tss, method: data.tss_method, tss_power: w.tss_power, tss_stryd: w.tss_stryd };
    var notice = tss.tss_dual_notice;
    var e = els();
    var feelBtns = ['hard', 'ok', 'easy'].map(function (f) {
      var on = (w.feeling || '') === f ? ' rv-btn--primary' : ' rv-btn--secondary';
      return '<button type="button" class="rv-btn' + on + '" data-feel="' + f + '">' + f + '</button>';
    }).join('');
    var method = (w.tss_method_override || tss.method || 'power');
    e.body.innerHTML =
      '<div class="rv-row" style="justify-content:space-between">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-close">Close</button>' +
      '<span>' + (index + 1) + ' of ' + ids.length + '</span>' +
      '<motion-nav></motion-nav></div>'.replace('<motion-nav></motion-nav>',
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-prev" ' + (index <= 0 ? 'disabled' : '') + '>Prev</button>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-next" ' + (index >= ids.length - 1 ? 'disabled' : '') + '>Next</button>') +
      '<h2 id="v2-drawer-title" style="margin:12px 0">' + esc(w.name || 'Run') + '</h2>' +
      '<p class="rv-subtitle">' + esc(w.workout_date || '') + '</p>' +
      '<div class="rv-row">' + feelBtns + '</div>' +
      (notice ? '<p class="rv-chip" style="background:var(--rv-warn-bg);color:var(--rv-warn-ink)">TSS differs: power ' +
        esc(tss.tss_power) + ' vs Stryd ' + esc(tss.tss_stryd) + '</p>' : '') +
      '<div class="rv-row">' +
      '<div class="rv-metric"><span class="rv-label">Distance</span><br><strong>' + esc(w.distance_km != null ? w.distance_km + ' km' : '—') + '</strong></div>' +
      '<div class="rv-metric"><span class="rv-label">Duration</span><br><strong>' + esc(w.duration_seconds ? Math.round(w.duration_seconds / 60) + ' min' : '—') + '</strong></div>' +
      '<div class="rv-metric"><span class="rv-label">TSS</span><br><strong>' + esc(tss.tss != null ? tss.tss : '—') + '</strong></div>' +
      '</div>' +
      '<p class="rv-label" style="margin-top:12px">TSS source</p>' +
      '<div class="rv-row">' +
      '<button type="button" class="rv-btn' + (method === 'power' ? ' rv-btn--primary' : ' rv-btn--secondary') + '" data-tss-method="power">Power method</button>' +
      '<button type="button" class="rv-btn' + (method === 'stryd' ? ' rv-btn--primary' : ' rv-btn--secondary') + '" data-tss-method="stryd">Stryd</button>' +
      '</div>' +
      '<div class="rv-stack" style="margin-top:12px">' +
      gridCell('Avg HR', w.avg_hr) +
      gridCell('Avg power', w.avg_power) +
      gridCell('NP', w.np) +
      gridCell('Cadence', w.avg_cadence_spm) +
      gridCell('Elevation', w.elevation_m) +
      '</div>';

    document.getElementById('v2-drawer-close').onclick = close;
    document.getElementById('v2-drawer-prev').onclick = function () { if (index > 0) { index -= 1; loadCurrent(); } };
    document.getElementById('v2-drawer-next').onclick = function () { if (index < ids.length - 1) { index += 1; loadCurrent(); } };
    e.body.querySelectorAll('[data-feel]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var val = btn.getAttribute('data-feel');
        var next = (w.feeling === val) ? null : val;
        fetch('/api/workouts/' + encodeURIComponent(w.id), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ feeling: next }),
        }).catch(function () { toast('Could not save feeling'); });
      });
    });
    e.body.querySelectorAll('[data-tss-method]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var m = btn.getAttribute('data-tss-method');
        fetch('/api/workouts/' + encodeURIComponent(w.id), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tss_method_override: m }),
        }).then(function (r) {
          if (!r.ok) throw new Error();
          global.dispatchEvent(new Event('v2:log-refresh'));
          loadCurrent();
        }).catch(function () { toast('Could not update TSS source'); });
      });
    });
  }

  function gridCell(label, val) {
    return '<div class="rv-metric"><span class="rv-label">' + esc(label) + '</span><br><strong>' +
      esc(val != null && val !== '' ? val : '—') + '</strong></div>';
  }

  global.V2RunDrawer = { open: open, close: close };
})(window);