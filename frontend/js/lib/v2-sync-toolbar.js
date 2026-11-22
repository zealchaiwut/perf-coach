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
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: BKK,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(ts);
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

  function mount(container, opts) {
    opts = opts || {};
    var onRefresh = opts.onRefresh || function () {};
    var lastIdleSynced = null;
    var wasRunning = false;

    function toast(msg) {
      var el = document.getElementById('v2-toast') || document.getElementById('rv-toast');
      if (!el) return;
      el.textContent = msg;
      el.classList.add('is-visible');
      setTimeout(function () { el.classList.remove('is-visible'); }, 3200);
    }

    function renderPills(detail) {
      var providers = (detail && detail.providers) || {};
      var parts = [];
      var syncing = [];
      var failed = [];
      var okNames = [];
      var ready = !!(detail && detail.raw);

      if (ready) {
        ['strava', 'stryd'].forEach(function (key) {
          var p = providers[key] || {};
          var state = p.state || (global.V2SyncStatus ? global.V2SyncStatus.providerState(p) : 'ok');
          if (state === 'syncing') {
            syncing.push(providerName(key));
          } else if (state === 'failed') {
            failed.push({ key: key, p: p });
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
      if (ready && !syncing.length && okNames.length) {
        var time = clockLabel(latestSuccess(providers));
        var dot = (detail && detail.overall === 'stale') ? 'rv-sync-dot--amber' : 'rv-sync-dot--green';
        parts.push(
          '<span class="rv-sync-pill rv-sync-pill--ok">' +
          '<span class="rv-sync-dot ' + dot + '" aria-hidden="true"></span>' +
          '<b>' + esc(okNames.join(' + ')) + '</b>' +
          (time ? '<span class="rv-subtitle" style="margin:0">' + esc(time) + '</span>' : '') +
          '</span>'
        );
      }

      var running = !!(detail && (detail.overall === 'syncing' ||
        detail.status === 'running' || detail.status === 'pending'));
      parts.push(
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-sync-now" ' +
        (running ? 'disabled aria-busy="true"' : '') + '>' +
        (running ? 'Syncing…' : 'Sync now') + '</button>'
      );
      var onLog = typeof window !== 'undefined' && window.location && window.location.pathname.indexOf('/v2/training/log') >= 0;
      if (onLog) {
        parts.push(
          '<button type="button" class="rv-btn rv-btn--primary" id="v2-log-strength">Log a strength session</button>'
        );
      }
      container.innerHTML = parts.join('');
      var btn = document.getElementById('v2-sync-now');
      if (btn) btn.addEventListener('click', startSync);
      var logStr = document.getElementById('v2-log-strength');
      if (logStr) {
        logStr.addEventListener('click', function () {
          if (global.V2StrengthDrawer) global.V2StrengthDrawer.openEdit(null);
        });
      }
    }

    function pollStatus() {
      return fetch('/api/sync/status').then(function (r) { return r.ok ? r.json() : null; });
    }

    function startSync() {
      fetch('/api/strava/sync', { method: 'POST' })
        .then(function (r) {
          if (r.status === 409) {
            toast('Sync already running');
            if (global.V2SyncStatus) global.V2SyncStatus.poll();
            return;
          }
          if (!r.ok) throw new Error('sync failed');
          if (global.SyncPoller) global.SyncPoller.start();
          if (global.V2SyncStatus) global.V2SyncStatus.poll();
        })
        .catch(function () { toast('Could not start sync'); });
    }

    function handleDetail(detail) {
      renderPills(detail || { status: 'idle', providers: {}, overall: 'ok' });
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
    renderPills({ status: 'idle', providers: {}, overall: 'ok' });
    if (global.V2SyncStatus && global.V2SyncStatus.lastDetail()) {
      handleDetail(global.V2SyncStatus.lastDetail());
    } else {
      pollStatus().then(handleRaw);
    }
    if (global.SyncPoller) {
      global.SyncPoller.subscribe(handleRaw);
    }
  }

  global.V2SyncToolbar = { mount: mount, clockLabel: clockLabel };
})(window);
