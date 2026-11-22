(function (global) {
  'use strict';

  var BKK = 'Asia/Bangkok';

  function esc(s) {
    return global.AppCommon ? global.AppCommon.escapeHtml(String(s)) : String(s);
  }

  function bkkNow() {
    return new Date();
  }

  function parseIso(iso) {
    if (!iso) return null;
    try {
      return new Date(iso);
    } catch (e) {
      return null;
    }
  }

  function relativeLabel(iso) {
    var ts = parseIso(iso);
    if (!ts) return 'never';
    var now = bkkNow();
    var diffMs = now - ts;
  if (diffMs < 0) diffMs = 0;
    var mins = diffMs / 60000;
    var fmtToday = new Intl.DateTimeFormat('en-GB', {
      timeZone: BKK,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    var dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: BKK, year: 'numeric', month: '2-digit', day: '2-digit' });
    var todayKey = dayFmt.format(now);
    var tsKey = dayFmt.format(ts);
    if (todayKey === tsKey) return fmtToday.format(ts);
    if (mins < 48 * 60) {
      var hrs = Math.max(1, Math.round(mins / 60));
      return hrs + ' h ago';
    }
    var days = Math.round(mins / (60 * 24));
    return days + ' d ago';
  }

  function dotClass(provider) {
    if (!provider || !provider.connected) return 'rv-sync-dot--red';
    if (provider.last_error) return 'rv-sync-dot--red';
    var ts = parseIso(provider.last_success_at);
    if (!ts) return 'rv-sync-dot--amber';
    var ageH = (bkkNow() - ts) / 3600000;
    if (ageH >= 48) return 'rv-sync-dot--amber';
    return 'rv-sync-dot--green';
  }

  function mount(container, opts) {
    opts = opts || {};
    var onRefresh = opts.onRefresh || function () {};
    var lastIdleSynced = null;

    function toast(msg) {
      var el = document.getElementById('v2-toast') || document.getElementById('rv-toast');
      if (!el) return;
      el.textContent = msg;
      el.classList.add('is-visible');
      setTimeout(function () { el.classList.remove('is-visible'); }, 3200);
    }

    function renderProviders(data) {
      var prov = (data && data.providers) || {};
      var running = (data && (data.status === 'running' || data.status === 'pending'));
      var lines = [];
      ['strava', 'stryd'].forEach(function (key) {
        var p = prov[key] || {};
        var wait = p.pending_count > 0 ? ' · ' + p.pending_count + ' waiting' : '';
        var label = p.connected ? relativeLabel(p.last_success_at) : 'not connected';
        lines.push(
          '<span class="rv-row" style="gap:7px;font-size:13px">' +
          '<span class="rv-sync-dot ' + dotClass(p) + '" aria-hidden="true"></span>' +
          '<b>' + esc(key === 'strava' ? 'Strava' : 'Stryd') + '</b>' +
          '<span class="rv-subtitle" style="margin:0">' + esc(label) + esc(wait) + '</span></span>'
        );
      });
      var btnLabel = running ? 'Syncing…' : 'Sync now';
      lines.push(
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-sync-now" ' +
        (running ? 'disabled aria-busy="true"' : '') + '>' + btnLabel + '</button>'
      );
      var onLog = typeof window !== 'undefined' && window.location && window.location.pathname.indexOf('/v2/training/log') >= 0;
      if (onLog) {
        lines.push(
          '<button type="button" class="rv-btn rv-btn--primary" id="v2-log-strength">Log strength session</button>'
        );
      }
      container.innerHTML = lines.join('');
      var btn = document.getElementById('v2-sync-now');
      if (btn) {
        btn.addEventListener('click', startSync);
      }
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
            return pollStatus().then(renderProviders);
          }
          if (!r.ok) throw new Error('sync failed');
          if (global.SyncPoller) global.SyncPoller.start();
          return pollStatus().then(renderProviders);
        })
        .catch(function () { toast('Could not start sync'); });
    }

    function handleStatus(data) {
      renderProviders(data || { status: 'idle' });
      if (data && data.status === 'idle' && data.items_synced != null && data.items_synced !== lastIdleSynced) {
        if (lastIdleSynced != null) {
          toast((data.items_synced || 0) + ' sessions synced');
          onRefresh();
        }
        lastIdleSynced = data.items_synced;
      }
      if (data && (data.status === 'running' || data.status === 'pending')) {
        if (global.SyncPoller) global.SyncPoller.start();
      }
    }

    pollStatus().then(handleStatus);
    if (global.SyncPoller) {
      global.SyncPoller.subscribe(handleStatus);
    }
  }

  global.V2SyncToolbar = { mount: mount, dotClass: dotClass, relativeLabel: relativeLabel };
})(window);