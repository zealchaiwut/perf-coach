(function (global) {
  'use strict';

  var esc = global.AppCommon ? global.AppCommon.escapeHtml.bind(global.AppCommon) : function (s) { return String(s); };
  var ids = [];
  var index = 0;
  var lastFocus = null;
  var currentId = null;

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
    document.removeEventListener('keydown', onKey);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
    currentId = null;
  }

  function open(workoutId, allRunIds) {
    ids = allRunIds || [workoutId];
    index = Math.max(0, ids.indexOf(workoutId));
    currentId = workoutId;
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

  function formatDur(sec) {
    if (!sec) return '—';
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = Math.floor(sec % 60);
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
  }

  function formatPace(secsPerKm) {
    if (!secsPerKm) return '—';
    var m = Math.floor(secsPerKm / 60);
    var s = Math.round(secsPerKm % 60);
    return m + ':' + String(s).padStart(2, '0');
  }

  function chip(text, style) {
    return '<span class="rv-chip" style="' + (style || '') + '">' + esc(text) + '</span>';
  }

  function loadCurrent() {
    var id = ids[index];
    currentId = id;
    var e = els();
    if (!id || !e.body) return;
    e.body.innerHTML = '<p class="rv-section-state">Loading session…</p>';
    fetch('/api/workouts/' + encodeURIComponent(id) + '/full?streams=summary', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) { render(data); })
      .catch(function () { e.body.innerHTML = '<p class="rv-section-state">Could not load session.</p>'; });
  }

  function powerZonesBlock(stryd) {
    var pz = (stryd && stryd.power_zones) || null;
    if (!pz || !Array.isArray(pz.zones) || !Array.isArray(pz.seconds_in_zones)) return '';
    var total = pz.seconds_in_zones.reduce(function (a, b) { return a + (b || 0); }, 0);
    if (!total) return '';
    var colors = ['#86efac', '#bef264', '#fbbf24', '#fb923c', '#ef4444'];
    var bar = '';
    var rows = '';
    pz.zones.forEach(function (z, i) {
      var sec = pz.seconds_in_zones[i] || 0;
      var pct = Math.round((sec / total) * 100);
      var mins = Math.round(sec / 60);
      var lo = z.power_low != null ? Math.round(z.power_low) : '—';
      var hi = z.power_high != null ? Math.round(z.power_high) : '—';
      bar += '<span class="rv-zone-seg" style="width:' + pct + '%;background:' + (colors[i] || '#ccc') + '"></span>';
      rows +=
        '<div class="rv-zone-row">' +
        '<span class="rv-zone-dot" style="background:' + (colors[i] || '#ccc') + '"></span>' +
        '<span style="font-weight:600">' + esc(z.name || ('Zone ' + (i + 1))) + '</span>' +
        '<span class="rv-mono rv-subtitle" style="margin:0">' + lo + '–' + hi + ' W</span>' +
        '<span class="rv-mono" style="text-align:right">' + mins + 'm</span>' +
        '<span class="rv-mono rv-subtitle" style="margin:0;text-align:right">' + pct + '%</span></div>';
    });
    return (
      '<section class="rv-drawer-sec">' +
      '<div class="rv-row"><span class="rv-label" style="margin:0">Time in power zones</span>' + chip('STRYD', 'background:#6d4fd6;color:#fff') + '</div>' +
      '<div class="rv-zone-bar">' + bar + '</div>' +
      '<div class="rv-zone-table">' + rows + '</div>' +
      (pz.ftp ? '<span class="rv-subtitle" style="margin:0">FTP ' + Math.round(pz.ftp) + ' W, from Stryd</span>' : '') +
      '</section>'
    );
  }

  function repsBlock(splits) {
    var laps = (splits || []).filter(function (s) {
      return s.duration_seconds > 0 && (s.distance_km || s.avg_power || s.avg_hr);
    });
    if (laps.length < 2) return '';
    var baseHr = laps[0].avg_hr;
    var rows = laps.slice(0, 12).map(function (s, i) {
      var pace = '';
      if (s.distance_km && parseFloat(s.distance_km) > 0 && s.duration_seconds) {
        pace = formatPace(s.duration_seconds / parseFloat(s.distance_km));
      }
      var hrDelta = (s.avg_hr != null && baseHr != null) ? 'HR ' + (s.avg_hr - baseHr >= 0 ? '+' : '') + (s.avg_hr - baseHr) : '—';
      return (
        '<div class="rv-rep-row">' +
        '<span class="rv-mono" style="font-weight:600">' + (s.split_index || i + 1) + '</span>' +
        '<span class="rv-mono">' + esc(pace || '—') + '</span>' +
        '<span class="rv-mono">' + (s.avg_power != null ? s.avg_power + ' W' : '—') + '</span>' +
        '<span class="rv-mono">' + (s.avg_hr != null ? s.avg_hr : '—') + '</span>' +
        '<span class="rv-mono rv-subtitle" style="margin:0">' + esc(i === 0 ? '—' : hrDelta) + '</span></div>'
      );
    }).join('');
    return (
      '<div style="margin-top:12px">' +
      '<div class="rv-row" style="padding:0 4px 6px"><span class="rv-label" style="margin:0">Reps</span><span class="rv-subtitle" style="margin:0">From laps</span></div>' +
      '<div class="rv-rep-row rv-rep-head"><span>Rep</span><span>Pace</span><span>Power</span><span>Avg HR</span><span>vs rep 1</span></div>' +
      rows + '</div>'
    );
  }

  function scoreRow(label, sig) {
    if (!sig) return '';
    var val = sig.value != null ? Math.round(sig.value) : '—';
    var reason = sig.reason ? sig.reason.replace(/_/g, ' ') : 'logged';
    return (
      '<div class="rv-row" style="align-items:flex-start">' +
      '<span style="font-weight:600">' + esc(label) + '</span>' +
      '<span><span class="rv-mono" style="font-weight:600">' + esc(String(val)) + '</span> ' +
      '<span class="rv-subtitle" style="margin:0">· ' + esc(reason) + '</span></span></div>'
    );
  }

  function formBlock(form, strydLinked) {
    var gct = form && form.gct_ms != null ? form.gct_ms + ' ms' : 'not imported';
    var lss = form && form.lss_kn_m != null ? form.lss_kn_m + ' kN/m' : 'not imported';
    var vo = form && form.vertical_oscillation_cm != null ? form.vertical_oscillation_cm + ' cm' : 'not imported';
    var missing = !form || (form.gct_ms == null && form.lss_kn_m == null && form.vertical_oscillation_cm == null);
    return (
      '<section class="rv-drawer-sec">' +
      '<div class="rv-row"><span class="rv-label" style="margin:0">Form</span>' + (strydLinked ? chip('STRYD', 'background:#6d4fd6;color:#fff') : '') + '</div>' +
      '<div class="rv-drawer-trio">' +
      miniStat('Ground contact', gct, missing) +
      miniStat('Leg spring stiffness', lss, missing) +
      miniStat('Vertical oscillation', vo, missing) +
      '</div>' +
      (missing && strydLinked
        ? '<p class="rv-warn-inline">Economy score needs these metrics. Turn on form import in Settings → Integrations.</p>'
        : '') +
      '</section>'
    );
  }

  function miniStat(label, val, muted) {
    return (
      '<div class="rv-drawer-mini">' +
      '<span class="rv-subtitle" style="margin:0;font-size:12px">' + esc(label) + '</span>' +
      '<span class="rv-mono" style="font-size:17px;font-weight:600' + (muted ? ';color:var(--rv-muted)' : '') + '">' + esc(String(val)) + '</span></div>'
    );
  }

  function bigStat(val, unit, label) {
    return (
      '<div class="rv-drawer-mini" style="padding:12px 14px">' +
      '<span class="rv-mono" style="font-size:24px;font-weight:600">' + esc(String(val)) +
      (unit ? ' <span class="rv-subtitle" style="margin:0">' + esc(unit) + '</span>' : '') + '</span>' +
      '<span class="rv-subtitle" style="margin:0;font-size:12px">' + esc(label) + '</span></div>'
    );
  }

  function loadGridCell(label, val, unit, pill) {
    return (
      '<div class="rv-drawer-cell' + (pill ? ' rv-drawer-cell--accent' : '') + '">' +
      (pill ? '<span class="rv-stryd-pill">STRYD</span>' : '') +
      '<span class="rv-subtitle" style="margin:0;font-size:12px;font-weight:700">' + esc(label) + '</span>' +
      '<span class="rv-mono" style="font-size:24px;font-weight:600">' + esc(val != null && val !== '' ? val : '—') +
      (unit && val != null ? ' <span class="rv-subtitle" style="margin:0">' + esc(unit) + '</span>' : '') + '</span></div>'
    );
  }

  function consult(id) {
    fetch('/api/sessions/' + encodeURIComponent(id) + '/consult-prompt', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        var label = data.kind === 'race' ? 'race debrief' : 'session review';
        var msg = 'Copied · ' + label + ' · ' + (data.chars || 0).toLocaleString() + ' chars';
        var text = data.prompt || '';
        function done() { toast(msg); }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(function () { toast('Could not copy'); });
        } else {
          toast('Copy consult prompt from clipboard fallback unavailable');
        }
      })
      .catch(function () { toast('Could not build consult prompt'); });
  }

  function screenshot() {
    var e = els();
    if (typeof global.html2canvas !== 'function') {
      toast('Screenshot tool not loaded');
      return;
    }
    if (!e.drawer) return;
    global.html2canvas(e.drawer, { backgroundColor: '#f5f7fc', scale: 2 }).then(function (canvas) {
      canvas.toBlob(function (blob) {
        if (!blob) { toast('Screenshot failed'); return; }
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'session-' + (currentId || 'run') + '.png';
        a.click();
        URL.revokeObjectURL(url);
        toast('Saved session image');
      });
    }).catch(function () { toast('Screenshot failed'); });
  }

  function render(data) {
    var w = data.workout || data;
    var tss = data.tss_block || {};
    var notice = tss.tss_dual_notice;
    var stryd = (data.sources && data.sources.stryd) || null;
    var method = w.tss_method_override || data.tss_method || tss.method || 'power';
    var pva = data.plan_vs_actual;
    var sig = data.session_signal || {};
    var e = els();

    var planBlock = '';
    if (pva) {
      var dSign = (pva.delta_tss || 0) >= 0 ? '+' : '';
      planBlock =
        '<section class="rv-drawer-sec">' +
        '<div class="rv-row"><span class="rv-label" style="margin:0">Plan vs actual</span>' +
        '<a href="/v2/training/plan" style="font-size:13px;font-weight:600">Open week in Plan</a></div>' +
        '<div class="rv-drawer-trio">' +
        miniStat('Planned', (pva.planned_tss != null ? Math.round(pva.planned_tss) + ' TSS' : '—'), false) +
        miniStat('Actual', (pva.actual_tss != null ? Math.round(pva.actual_tss) + ' TSS' : '—'), false) +
        '<div class="rv-drawer-mini" style="background:var(--rv-warn-bg)">' +
        '<span class="rv-subtitle" style="margin:0;font-size:12px;color:var(--rv-warn-ink)">Difference</span>' +
        '<span class="rv-mono" style="font-weight:600;color:var(--rv-warn-ink)">' +
        esc(dSign + (pva.delta_tss != null ? pva.delta_tss : '—')) +
        (pva.delta_pct != null ? ' · ' + dSign + pva.delta_pct + '%' : '') + '</span></div></div>' +
        repsBlock(data.splits || []) +
        '</section>';
    }

    var pace = w.average_pace_seconds_per_km || (w.distance_km && w.duration_seconds
      ? w.duration_seconds / w.distance_km : null);

    e.body.innerHTML =
      '<header class="rv-drawer-top">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-close" aria-label="Close">✕</button>' +
      '<div class="rv-row" style="gap:8px">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-prev" ' + (index <= 0 ? 'disabled' : '') + ' aria-label="Newer session">‹</button>' +
      '<span class="rv-mono" style="font-size:13px;font-weight:600;background:var(--rv-tile);padding:7px 12px;border-radius:999px">' +
      (index + 1) + ' of ' + ids.length + '</span>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-next" ' + (index >= ids.length - 1 ? 'disabled' : '') + ' aria-label="Older session">›</button></div>' +
      '<div class="rv-row" style="gap:4px">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-consult">Consult</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-shot" aria-label="Save as image">📷</button></div></header>' +

      '<section class="rv-drawer-sec">' +
      '<div class="rv-row" style="flex-wrap:wrap">' +
      chip('RUN', 'background:#dbe4fd;color:#1e3fb0') +
      (data.plan_match ? chip('COACH PLAN', 'background:#eef2fb;color:#33405e') : chip('UNPLANNED', 'background:#eef2fb')) +
      (method === 'stryd' ? chip('STRYD', 'background:#0b1530;color:#fff') : '') + '</div>' +
      '<h2 id="v2-drawer-title" style="margin:8px 0 4px;font-size:1.6rem">' + esc(w.name || 'Run') + '</h2>' +
      '<p class="rv-subtitle" style="margin:0">' + esc(w.workout_date || '') +
      (w.start_time ? ' · started ' + esc(String(w.start_time).slice(11, 16)) : '') + '</p>' +
      '<div class="rv-drawer-trio">' +
      bigStat(w.distance_km != null ? w.distance_km : '—', 'km', 'Distance') +
      bigStat(formatDur(w.duration_seconds), '', 'Duration') +
      bigStat(pace ? formatPace(pace) : '—', '/km', 'Avg pace') + '</div>' +
      '<div class="rv-row" style="flex-wrap:wrap;align-items:center"><span class="rv-subtitle" style="margin:0;font-weight:600">How did it feel?</span><div id="v2-drawer-feel"></div></div>' +
      '</section>' +

      planBlock +

      '<section class="rv-drawer-sec rv-drawer-sec--grid">' +
      '<span class="rv-label" style="margin:0 0 4px 4px">Load and intensity</span>' +
      '<div class="rv-drawer-grid">' +
      loadGridCell('TSS (' + method + ')', tss.tss != null ? Math.round(tss.tss) : null, '', false) +
      loadGridCell('Zone 2', w.zone2_minutes, 'min', false) +
      loadGridCell('Cadence', w.avg_cadence_spm || (data.form && data.form.cadence_spm), 'spm', stryd) +
      loadGridCell('Avg HR', w.avg_hr, 'bpm', false) +
      loadGridCell('Normalised power', w.np, 'W', stryd) +
      loadGridCell('Avg power', w.avg_power, 'W', stryd) +
      loadGridCell('Max HR', w.max_hr, 'bpm', false) +
      loadGridCell('Stride', w.avg_stride_m, 'm', stryd) +
      loadGridCell('Elevation', w.elevation_m, 'm', false) +
      '</div>' +
      (notice ? '<p class="rv-warn-inline">Stryd reports <b>' + esc(tss.tss_stryd) + '</b>; power method computes <b>' +
        esc(tss.tss_power) + '</b>. Week totals follow your TSS source choice.</p>' : '') +
      '<div class="rv-row" style="margin-top:8px;flex-wrap:wrap">' +
      '<button type="button" class="rv-btn' + (method === 'power' ? ' rv-btn--primary' : ' rv-btn--secondary') + '" data-tss-method="power">Power method</button>' +
      '<button type="button" class="rv-btn' + (method === 'stryd' ? ' rv-btn--primary' : ' rv-btn--secondary') + '" data-tss-method="stryd">Stryd</button></div>' +
      '</section>' +

      powerZonesBlock(stryd) +

      '<section class="rv-drawer-sec rv-drawer-sec--scores">' +
      '<div class="rv-row"><span class="rv-label" style="margin:0">What this session did to your scores</span>' +
      '<a href="/v2/performance" style="font-size:13px;font-weight:600">Performance</a></div>' +
      scoreRow('Endurance', sig.endurance) +
      scoreRow('Speed', sig.speed) +
      (w.durability_signal != null ? scoreRow('Durability', { value: w.durability_signal, reason: 'rep drift' }) : '') +
      '</section>' +

      formBlock(data.form, !!stryd) +

      '<section class="rv-drawer-sec">' +
      '<span class="rv-label" style="margin:0">Notes</span>' +
      '<p class="rv-subtitle" style="margin:0;white-space:pre-wrap">' + esc(w.remarks || '—') + '</p></section>';

    document.getElementById('v2-drawer-close').onclick = close;
    document.getElementById('v2-drawer-prev').onclick = function () { if (index > 0) { index -= 1; loadCurrent(); } };
    document.getElementById('v2-drawer-next').onclick = function () { if (index < ids.length - 1) { index += 1; loadCurrent(); } };
    document.getElementById('v2-drawer-consult').onclick = function () { consult(w.id); };
    document.getElementById('v2-drawer-shot').onclick = screenshot;

    if (global.V2FeelButtons) {
      global.V2FeelButtons.mount(document.getElementById('v2-drawer-feel'), w.id, w.feeling);
    }

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

  global.V2RunDrawer = { open: open, close: close };
})(window);