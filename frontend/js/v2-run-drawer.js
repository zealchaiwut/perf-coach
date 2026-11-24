(function (global) {
  'use strict';

  var esc = global.AppCommon ? global.AppCommon.escapeHtml.bind(global.AppCommon) : function (s) { return String(s); };
  var ids = [];
  var index = 0;
  var lastFocus = null;
  var currentId = null;
  var prefsCache = null;
  var shoesCache = null;
  var prefsInflight = null;
  var shoesInflight = null;

  function fetchPrefs() {
    if (prefsCache) return Promise.resolve(prefsCache);
    if (prefsInflight) return prefsInflight;
    prefsInflight = fetch('/api/user-preferences', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { row: {} }; })
      .catch(function () { return { row: {} }; })
      .then(function (data) { prefsCache = data; prefsInflight = null; return data; });
    return prefsInflight;
  }

  function fetchShoes() {
    if (shoesCache) return Promise.resolve(shoesCache);
    if (shoesInflight) return shoesInflight;
    shoesInflight = fetch('/api/athlete-shoes', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { shoes: [], default_shoe_id: null }; })
      .catch(function () { return { shoes: [], default_shoe_id: null }; })
      .then(function (data) { shoesCache = data; shoesInflight = null; return data; });
    return shoesInflight;
  }

  function clearLookups() {
    prefsCache = null;
    shoesCache = null;
    prefsInflight = null;
    shoesInflight = null;
  }

  function els() {
    return {
      backdrop: document.getElementById('v2-drawer-backdrop'),
      drawer: document.getElementById('v2-drawer'),
      body: document.getElementById('v2-drawer-body'),
    };
  }

  function toast(msg) {
    var el = document.getElementById('v2-toast') || document.getElementById('rv-toast');
    if (!el && global.RevampUI && global.RevampUI.showToast) {
      global.RevampUI.showToast(msg);
      return;
    }
    if (!el) return;
    el.textContent = msg;
    el.classList.add('is-visible');
    setTimeout(function () { el.classList.remove('is-visible'); }, 3200);
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

  function normalizeRunFullPayload(full) {
    full = full || {};
    var w = Object.assign({}, full.workout || {});
    var splits = Array.isArray(full.splits) ? full.splits : [];
    var sources = full.sources || {};
    var src = (w.source || '').toLowerCase();
    var hasStrava =
      !!sources.strava ||
      src.indexOf('strava') >= 0 ||
      !!w.strava_activity_pk ||
      !!w.strava_activity_url;
    var hasStryd =
      !!sources.stryd ||
      src.indexOf('stryd') >= 0 ||
      !!w.stryd_activity_pk;
    if (hasStrava && !sources.strava) sources.strava = {};
    return {
      workout: w,
      splits: splits,
      sources: { strava: sources.strava || null, stryd: sources.stryd || null },
      unified: full.unified || {},
      computed: full.computed || {},
      field_coverage: full.field_coverage || {
        strava: hasStrava,
        stryd: hasStryd,
        has_splits: splits.length > 0,
      },
      detected_profile: full.detected_profile || {},
      computed_tss: full.computed_tss != null ? full.computed_tss : null,
      tss_method: full.tss_method || w.tss_method || 'none',
      tss: full.tss != null ? full.tss : w.tss,
      tss_partial: !!full.tss_partial,
      tss_block: full.tss_block,
      plan_match: full.plan_match,
      plan_vs_actual: full.plan_vs_actual,
      session_signal: full.session_signal,
      aerobic_decoupling: full.aerobic_decoupling,
      intensity_zones: full.intensity_zones,
      form: full.form,
    };
  }

  function drawerChrome() {
    return (
      '<header class="rv-drawer-top">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-close" aria-label="Close">✕</button>' +
      '<div class="rv-row" style="gap:8px">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-prev" ' + (index <= 0 ? 'disabled' : '') + ' aria-label="Newer session">‹</button>' +
      '<span class="rv-mono" style="font-size:13px;font-weight:600;background:var(--rv-tile);padding:7px 12px;border-radius:999px">' +
      (index + 1) + ' of ' + ids.length + '</span>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-next" ' + (index >= ids.length - 1 ? 'disabled' : '') + ' aria-label="Older session">›</button></div>' +
      '<div class="rv-row" style="gap:4px">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-consult">Consult</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-drawer-shot" aria-label="Save as image">📷</button>' +
      '</div></header>'
    );
  }

  function bindChrome(workoutId) {
    var prev = document.getElementById('v2-drawer-prev');
    var next = document.getElementById('v2-drawer-next');
    if (document.getElementById('v2-drawer-close')) {
      document.getElementById('v2-drawer-close').onclick = close;
    }
    if (prev) prev.onclick = function () { if (index > 0) { index -= 1; loadCurrent(); } };
    if (next) next.onclick = function () { if (index < ids.length - 1) { index += 1; loadCurrent(); } };
    if (document.getElementById('v2-drawer-consult')) {
      document.getElementById('v2-drawer-consult').onclick = function () { consult(workoutId); };
    }
    if (document.getElementById('v2-drawer-shot')) {
      document.getElementById('v2-drawer-shot').onclick = screenshot;
    }
  }

  function consult(id) {
    fetch('/api/sessions/' + encodeURIComponent(id) + '/consult-prompt', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        var label = data.kind === 'race' ? 'race debrief' : 'session review';
        var caveat = (data.missing && data.missing.length)
          ? 'Not available: ' + data.missing.join(', ')
          : '';
        var msg = 'Copied · ' + label + ' · ' + (data.chars || 0).toLocaleString() + ' chars' +
          (caveat ? ' · ' + caveat : '');
        var text = data.prompt || '';
        function done() { toast(msg); }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(function () { toast('Could not copy'); });
        } else {
          toast('Copy unavailable');
        }
      })
      .catch(function () { toast('Could not build consult prompt'); });
  }

  function loadHtml2Canvas() {
    if (typeof global.html2canvas === 'function') {
      return Promise.resolve(global.html2canvas);
    }
    if (global._html2canvasPromise) return global._html2canvasPromise;
    global._html2canvasPromise = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = '/js/lib/html2canvas.min.js';
      s.onload = function () {
        if (typeof global.html2canvas === 'function') resolve(global.html2canvas);
        else reject(new Error('html2canvas missing'));
      };
      s.onerror = function () { reject(new Error('html2canvas failed')); };
      document.head.appendChild(s);
    });
    return global._html2canvasPromise;
  }

  function screenshot() {
    var e = els();
    if (!e.drawer) return;
    loadHtml2Canvas().then(function (h2c) {
      return h2c(e.drawer, { backgroundColor: '#f5f7fc', scale: 2 });
    }).then(function (canvas) {
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

  function loadCurrent() {
    var id = ids[index];
    currentId = id;
    var e = els();
    if (!id || !e.body) return;
    e.body.innerHTML = drawerChrome() + '<p class="rv-section-state">Loading session…</p>';
    bindChrome(id);

    if (!global.RunDetailView || !global.RunDetailView.render) {
      e.body.innerHTML = drawerChrome() + '<p class="rv-section-state">Run detail module failed to load. Refresh the page.</p>';
      bindChrome(id);
      return;
    }

    Promise.all([
      fetch('/api/workouts/' + encodeURIComponent(id) + '/full?streams=none', { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('full'); return r.json(); }),
      fetchPrefs(),
      fetchShoes(),
    ])
      .then(function (pair) {
        var payload = normalizeRunFullPayload(pair[0]);
        var w = payload.workout || {};
        e.body.innerHTML = drawerChrome() + '<div id="v2-rd4-host" class="rd4-drawer-host" aria-labelledby="rd4-title"></div>';
        bindChrome(id);
        var host = document.getElementById('v2-rd4-host');
        var syncMeta = {};
        if (global.V2SyncStatus && typeof global.V2SyncStatus.lastDetail === 'function') {
          var d = global.V2SyncStatus.lastDetail();
          var providers = (d && d.providers) || {};
          if (providers.strava) syncMeta.stravaLatest = { synced_at: providers.strava.last_success_at };
          if (providers.stryd) {
            syncMeta.strydLatest = { synced_at: providers.stryd.last_success_at };
            syncMeta.strydConnected = providers.stryd.connected !== false;
          }
        }
        var painted = global.RunDetailView.render(host, payload, pair[1], syncMeta);
        if (!painted) {
          host.innerHTML = '<section class="rd4-card"><p class="rd4-muted">Could not render run detail.</p></section>';
          return;
        }
        var feelHost = document.getElementById('rd4-feeling');
        if (feelHost && global.V2FeelButtons && w.id) {
          feelHost.innerHTML = '';
          global.V2FeelButtons.mount(feelHost, w.id, w.feeling);
        }
        var typeHost = document.getElementById('rd4-runtype');
        if (typeHost && global.V2RunTypeButtons && w.id) {
          typeHost.innerHTML = '';
          global.V2RunTypeButtons.mount(typeHost, w.id, w.run_subtype);
        }
      })
      .catch(function () {
        e.body.innerHTML = drawerChrome() + '<p class="rv-section-state">Could not load session.</p>';
        bindChrome(id);
      });
  }

  global.V2RunDrawer = { open: open, close: close, clearLookups: clearLookups };
})(window);