(function (global) {
  'use strict';

  var BKK = 'Asia/Bangkok';

  function esc(s) {
    return global.AppCommon ? global.AppCommon.escapeHtml(String(s)) : String(s);
  }

  function parseIso(iso) {
    if (!iso) return null;
    try {
      return new Date(iso);
    } catch (e) {
      return null;
    }
  }

  function clockLabel(iso) {
    var ts = parseIso(iso);
    if (!ts) return '';
    var time = new Intl.DateTimeFormat('en-GB', {
      timeZone: BKK,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(ts);
    var day = new Intl.DateTimeFormat('en-CA', { timeZone: BKK }).format(ts);
    var today = global.AppCommon && global.AppCommon.todayISO
      ? global.AppCommon.todayISO()
      : new Intl.DateTimeFormat('en-CA', { timeZone: BKK }).format(new Date());
    if (day === today) return time;
    var pretty = new Intl.DateTimeFormat('en-GB', {
      timeZone: BKK,
      day: 'numeric',
      month: 'short',
    }).format(ts);
    return pretty + ' ' + time;
  }

  function latestSuccess(providers) {
    var best = null;
    ['strava', 'stryd'].forEach(function (key) {
      var iso = (providers[key] || {}).last_success_at;
      if (!iso) return;
      if (!best || iso > best) best = iso;
    });
    return best;
  }

  function providerName(key) {
    return key === 'strava' ? 'Strava' : 'Stryd';
  }

  function failedLabel(key, p) {
    if (key === 'stryd' && p.needs_reauth) return 'Stryd needs reconnecting';
    return providerName(key) + ' sync failed';
  }

  function providerStateOf(p) {
    return p.state || (global.V2SyncStatus ? global.V2SyncStatus.providerState(p) : 'ok');
  }

  function rowTime(p) {
    if (!p || p.connected === false) return 'Not connected';
    if (p.needs_reauth) return 'Needs password';
    return clockLabel(p.last_success_at) || 'Never';
  }

  function mount(container, opts) {
    opts = opts || {};
    var onRefresh = opts.onRefresh || function () {};
    var lastIdleSynced = null;
    var wasRunning = false;
    var lastDetail = null;
    var panelOpen = false;

    function toast(msg) {
      var el = document.getElementById('v2-toast') || document.getElementById('rv-toast');
      if (!el) return;
      el.textContent = msg;
      el.classList.add('is-visible');
      setTimeout(function () { el.classList.remove('is-visible'); }, 3200);
    }

    function ensureShell() {
      if (container.querySelector('#v2-sync-pills')) return;
      var onLog = typeof window !== 'undefined' && window.location && window.location.pathname.indexOf('/v2/training/log') >= 0;
      container.innerHTML =
        '<div class="rv-sync-pills" id="v2-sync-pills"></div>' +
        '<div class="rv-sync-widget" id="v2-sync-widget">' +
          '<button type="button" class="rv-btn rv-btn--secondary" id="v2-sync-now" aria-expanded="false" aria-controls="v2-sync-panel" title="Show sync options">' +
            '<span class="rv-sync-toggle-label">Sync</span>' +
            '<span class="rv-sync-chevron" aria-hidden="true">▾</span>' +
          '</button>' +
        '</div>' +
        (onLog
          ? '<button type="button" class="rv-btn rv-btn--primary" id="v2-log-strength">Log a strength session</button>'
          : '');
      var logStr = document.getElementById('v2-log-strength');
      if (logStr) {
        logStr.addEventListener('click', function () {
          if (global.V2StrengthDrawer) global.V2StrengthDrawer.openEdit(null);
        });
      }
      ensurePanel();
      bindToggle();
    }

    function ensurePanel() {
      if (document.getElementById('v2-sync-panel')) return;
      var backdrop = document.createElement('div');
      backdrop.id = 'v2-sync-backdrop';
      backdrop.className = 'rv-sync-backdrop';
      backdrop.hidden = true;
      var panel = document.createElement('div');
      panel.id = 'v2-sync-panel';
      panel.className = 'rv-sync-panel';
      panel.hidden = true;
      panel.innerHTML =
        '<div class="rv-sync-row" data-provider="strava">' +
          '<div class="rv-sync-row-info">' +
            '<span class="rv-sync-row-logo rv-sync-row-logo--strava">St</span>' +
            '<div class="rv-sync-row-text">' +
              '<span class="rv-sync-row-name">Strava</span>' +
              '<span class="rv-sync-row-time" id="v2-sync-time-strava">…</span>' +
            '</div>' +
          '</div>' +
          '<button type="button" class="rv-sync-row-btn" id="v2-sync-btn-strava">Sync new</button>' +
        '</div>' +
        '<div class="rv-sync-row" data-provider="stryd">' +
          '<div class="rv-sync-row-info">' +
            '<span class="rv-sync-row-logo rv-sync-row-logo--stryd">S</span>' +
            '<div class="rv-sync-row-text">' +
              '<span class="rv-sync-row-name">Stryd</span>' +
              '<span class="rv-sync-row-time" id="v2-sync-time-stryd">…</span>' +
            '</div>' +
          '</div>' +
          '<button type="button" class="rv-sync-row-btn" id="v2-sync-btn-stryd">Sync new</button>' +
        '</div>';
      document.body.appendChild(backdrop);
      document.body.appendChild(panel);
      backdrop.addEventListener('click', closePanel);
      document.getElementById('v2-sync-btn-strava').addEventListener('click', function () {
        closePanel();
        startSync('/api/strava/sync', 'Strava');
      });
      document.getElementById('v2-sync-btn-stryd').addEventListener('click', function () {
        closePanel();
        startSync('/api/stryd/sync', 'Stryd');
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && panelOpen) closePanel();
      });
      document.addEventListener('click', function (e) {
        if (!panelOpen) return;
        var toggle = document.getElementById('v2-sync-now');
        if (panel.contains(e.target) || (toggle && toggle.contains(e.target))) return;
        closePanel();
      });
      window.addEventListener('resize', positionPanel);
      window.addEventListener('scroll', positionPanel, true);
    }

    function positionPanel() {
      var panel = document.getElementById('v2-sync-panel');
      var toggle = document.getElementById('v2-sync-now');
      if (!panel || !toggle || panel.hidden) return;
      var rect = toggle.getBoundingClientRect();
      panel.style.position = 'fixed';
      panel.style.top = (rect.bottom + 7) + 'px';
      var panelWidth = panel.offsetWidth || 224;
      var left = rect.left + rect.width / 2 - panelWidth / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - panelWidth - 8));
      panel.style.right = 'auto';
      panel.style.left = left + 'px';
    }

    function openPanel() {
      var panel = document.getElementById('v2-sync-panel');
      var backdrop = document.getElementById('v2-sync-backdrop');
      var toggle = document.getElementById('v2-sync-now');
      if (!panel || !toggle) return;
      paintPanel(lastDetail);
      panel.hidden = false;
      if (backdrop) backdrop.hidden = false;
      positionPanel();
      toggle.setAttribute('aria-expanded', 'true');
      panelOpen = true;
      var first = panel.querySelector('button:not(:disabled)');
      if (first) first.focus();
    }

    function closePanel() {
      var panel = document.getElementById('v2-sync-panel');
      var backdrop = document.getElementById('v2-sync-backdrop');
      var toggle = document.getElementById('v2-sync-now');
      var wasOpen = panelOpen;
      if (panel) panel.hidden = true;
      if (backdrop) backdrop.hidden = true;
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
      panelOpen = false;
      if (wasOpen && toggle) toggle.focus();
    }

    function bindToggle() {
      var toggle = document.getElementById('v2-sync-now');
      if (!toggle || toggle.dataset.bound === '1') return;
      toggle.dataset.bound = '1';
      toggle.addEventListener('click', function (e) {
        e.stopPropagation();
        if (toggle.disabled) return;
        if (panelOpen) closePanel();
        else openPanel();
      });
    }

    function paintPanel(detail) {
      var providers = (detail && detail.providers) || {};
      var running = !!(detail && (detail.overall === 'syncing' ||
        detail.status === 'running' || detail.status === 'pending'));
      ['strava', 'stryd'].forEach(function (key) {
        var p = providers[key] || {};
        var timeEl = document.getElementById('v2-sync-time-' + key);
        var btn = document.getElementById('v2-sync-btn-' + key);
        if (timeEl) timeEl.textContent = rowTime(p);
        if (btn) {
          var blocked = running || p.connected === false || !!p.needs_reauth;
          btn.disabled = blocked;
        }
      });
    }

    function renderPills(detail) {
      ensureShell();
      var pills = document.getElementById('v2-sync-pills');
      if (!pills) return;
      var providers = (detail && detail.providers) || {};
      var parts = [];
      var syncing = [];
      var failed = [];
      var stale = [];
      var okNames = [];
      var ready = !!(detail && detail.raw);

      if (ready) {
        ['strava', 'stryd'].forEach(function (key) {
          var p = providers[key] || {};
          var state = providerStateOf(p);
          if (state === 'syncing') {
            syncing.push(providerName(key));
          } else if (state === 'failed') {
            failed.push({ key: key, p: p });
          } else if (state === 'stale') {
            stale.push({ key: key, p: p });
          } else if (p.connected !== false) {
            okNames.push(providerName(key));
          }
        });
      }

      if (syncing.length) {
        parts.push(
          '<span class="rv-sync-pill rv-sync-pill--syncing">' +
          '<span class="rv-sync-spinner" aria-hidden="true"></span>' +
          'Syncing ' + esc(syncing.join(' + ')) + '…</span>'
        );
      }

      failed.forEach(function (item) {
        var title = item.p.last_error ? esc(item.p.last_error) : '';
        parts.push(
          '<a class="rv-sync-pill rv-sync-pill--failed" href="/v2/settings#integrations"' +
          (title ? ' title="' + title + '"' : '') + '>' +
          '<span class="rv-sync-dot rv-sync-dot--red" aria-hidden="true"></span>' +
          esc(failedLabel(item.key, item.p)) + '</a>'
        );
      });
      stale.forEach(function (item) {
        var when = clockLabel(item.p.last_success_at) || 'unknown';
        parts.push(
          '<a class="rv-sync-pill rv-sync-pill--stale" href="/v2/settings#integrations">' +
          '<span class="rv-sync-dot rv-sync-dot--amber" aria-hidden="true"></span>' +
          esc(providerName(item.key) + ' last synced ' + when) + '</a>'
        );
      });
      if (ready && !syncing.length && okNames.length) {
        var okTime = null;
        ['strava', 'stryd'].forEach(function (key) {
          var p = providers[key] || {};
          if (providerStateOf(p) === 'ok' && p.last_success_at && (!okTime || p.last_success_at > okTime)) {
            okTime = p.last_success_at;
          }
        });
        var time = clockLabel(okTime || latestSuccess(providers));
        parts.push(
          '<span class="rv-sync-pill rv-sync-pill--ok">' +
          '<span class="rv-sync-dot rv-sync-dot--green" aria-hidden="true"></span>' +
          '<b>' + esc(okNames.join(' + ')) + '</b>' +
          (time ? '<span class="rv-subtitle" style="margin:0">' + esc(time) + '</span>' : '') +
          '</span>'
        );
      }
      pills.innerHTML = parts.join('');

      var running = !!(detail && (detail.overall === 'syncing' ||
        detail.status === 'running' || detail.status === 'pending'));
      var toggle = document.getElementById('v2-sync-now');
      if (toggle) {
        toggle.disabled = running;
        if (running) toggle.setAttribute('aria-busy', 'true');
        else toggle.removeAttribute('aria-busy');
        var label = toggle.querySelector('.rv-sync-toggle-label');
        if (label) label.textContent = running ? 'Syncing…' : 'Sync';
      }
      paintPanel(detail);
    }

    function startSync(url, label) {
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full: false }),
      })
        .then(function (r) {
          if (r.status === 409) {
            toast('Sync already running');
            if (global.V2SyncStatus) global.V2SyncStatus.poll();
            return;
          }
          if (r.status === 422) {
            toast(label + ' is not connected');
            return;
          }
          if (!r.ok) throw new Error('sync failed');
          toast('Syncing ' + label + '…');
          if (global.SyncPoller) global.SyncPoller.start();
          if (global.V2SyncStatus) global.V2SyncStatus.poll();
        })
        .catch(function () { toast('Could not start ' + label + ' sync'); });
    }

    function handleDetail(detail) {
      lastDetail = detail || { status: 'idle', providers: {}, overall: 'ok' };
      renderPills(lastDetail);
      var running = !!(detail && (detail.overall === 'syncing' ||
        detail.status === 'running' || detail.status === 'pending'));
      if (wasRunning && !running) {
        onRefresh();
        var data = (detail && detail.raw) || {};
        if (data.items_synced != null && data.items_synced !== lastIdleSynced) {
          toast((data.items_synced || 0) + ' sessions synced');
          lastIdleSynced = data.items_synced;
        }
      }
      wasRunning = running;
    }

    function handleRaw(data) {
      if (global.V2SyncStatus && data) return;
      handleDetail({
        status: (data && data.status) || 'idle',
        providers: (data && data.providers) || {},
        overall: data && (data.status === 'running' || data.status === 'pending') ? 'syncing' : 'ok',
        raw: data,
      });
    }

    document.addEventListener('rv:sync-status', function (ev) {
      handleDetail(ev.detail);
    });
    ensureShell();
    renderPills({ status: 'idle', providers: {}, overall: 'ok' });
    if (global.V2SyncStatus && global.V2SyncStatus.lastDetail()) {
      handleDetail(global.V2SyncStatus.lastDetail());
    } else {
      fetch('/api/sync/status').then(function (r) { return r.ok ? r.json() : null; }).then(handleRaw);
    }
    if (global.SyncPoller) {
      global.SyncPoller.subscribe(handleRaw);
    }
  }

  global.V2SyncToolbar = { mount: mount, clockLabel: clockLabel };
})(window);
