/* Outbox flusher + bundle refresh for the phone PWA. */
(function (global) {
  "use strict";
  var BACKOFF = [2000, 4000, 8000, 16000, 32000, 60000];
  var state = {
    waking: false,
    wakingSince: 0,
    lastSyncedAt: null,
    lastError: null
  };
  var flushTimer = null;
  var flushing = false;

  function emit() {
    global.dispatchEvent(new CustomEvent("pc:sync", { detail: snapshot() }));
  }

  function snapshot() {
    return {
      waking: state.waking,
      wakingSince: state.wakingSince,
      lastSyncedAt: state.lastSyncedAt,
      lastError: state.lastError
    };
  }

  function csrfHeaders() {
    var headers = { "Content-Type": "application/json" };
    var m = document.cookie.match(/(?:^|; )csrf-token=([^;]+)/);
    if (m) headers["X-CSRF-Token"] = decodeURIComponent(m[1]);
    return headers;
  }

  function markWaking(on) {
    state.waking = !!on;
    if (on && !state.wakingSince) state.wakingSince = Date.now();
    if (!on) state.wakingSince = 0;
    emit();
  }

  function timedFetch(url, opts, ms) {
    var ctrl = new AbortController();
    var t = setTimeout(function () { ctrl.abort(); }, ms || 4000);
    opts = opts || {};
    opts.signal = ctrl.signal;
    opts.credentials = "same-origin";
    var started = Date.now();
    return fetch(url, opts).then(function (r) {
      clearTimeout(t);
      if (Date.now() - started > 3000) markWaking(true);
      return r;
    }).catch(function (err) {
      clearTimeout(t);
      markWaking(true);
      throw err;
    });
  }

  function enqueue(op) {
    return MStore.putOutbox(op).then(function () {
      emit();
      scheduleFlush(0);
      return op;
    });
  }

  function nextDelay(attempts) {
    var i = Math.min(Math.max(attempts, 0), BACKOFF.length - 1);
    return BACKOFF[i];
  }

  function scheduleFlush(ms) {
    if (flushTimer) clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, ms || 0);
  }

  function flush() {
    if (flushing) return Promise.resolve();
    flushing = true;
    var started = Date.now();
    return MStore.listOutbox().then(function (ops) {
      if (!ops || !ops.length) {
        markWaking(false);
        flushing = false;
        emit();
        return;
      }
      return timedFetch("/api/mobile/sync", {
        method: "POST",
        headers: csrfHeaders(),
        body: JSON.stringify({ ops: ops })
      }, 8000).then(function (r) {
        if (!r.ok) throw new Error("sync " + r.status);
        markWaking(false);
        return r.json();
      }).then(function (body) {
        var results = (body && body.ops) || [];
        var chain = Promise.resolve();
        results.forEach(function (row, i) {
          var op = ops[i];
          if (!op) return;
          chain = chain.then(function () {
            if (row.status === "applied" || row.status === "duplicate") {
              return MStore.deleteOutbox(op.client_mutation_id);
            }
            op.attempts = (op.attempts || 0) + 1;
            op.last_error = row.error || row.status;
            op.conflict = row.status === "conflict";
            op.server_version = row.server_version || null;
            return MStore.putOutbox(op);
          });
        });
        state.lastSyncedAt = Date.now();
        state.lastError = null;
        return chain;
      }).catch(function (err) {
        state.lastError = String(err && err.message || err);
        if (Date.now() - started < 90000) scheduleFlush(nextDelay((ops[0] && ops[0].attempts) || 0));
      }).then(function () {
        flushing = false;
        emit();
        return MStore.listOutbox().then(function (left) {
          if (left && left.length && !state.waking) scheduleFlush(nextDelay(1));
        });
      });
    }).catch(function () {
      flushing = false;
    });
  }

  function refreshBundle() {
    return MStore.getBundle().then(function (row) {
      var headers = {};
      if (row && row.etag) headers["If-None-Match"] = row.etag;
      var started = Date.now();
      return timedFetch("/api/mobile/bundle?days=7", { headers: headers }, 4000).then(function (r) {
        if (Date.now() - started > 3000) markWaking(true);
        else markWaking(false);
        if (r.status === 304) {
          state.lastSyncedAt = Date.now();
          emit();
          return row && row.payload;
        }
        if (!r.ok) throw new Error("bundle " + r.status);
        var etag = r.headers.get("etag");
        return r.json().then(function (payload) {
          return MStore.setBundle(payload, etag).then(function () {
            state.lastSyncedAt = Date.now();
            global.dispatchEvent(new CustomEvent("pc:bundle", { detail: payload }));
            emit();
            return payload;
          });
        });
      }).catch(function () {
        markWaking(true);
        return row && row.payload;
      });
    });
  }

  function ping() {
    return timedFetch("/api/mobile/ping", { method: "GET" }, 4000).catch(function () {
      markWaking(true);
    });
  }

  function boot() {
    global.addEventListener("online", function () { ping(); scheduleFlush(0); refreshBundle(); });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) { ping(); scheduleFlush(0); refreshBundle(); }
    });
    ping();
    scheduleFlush(200);
    refreshBundle();
  }

  global.MSync = {
    enqueue: enqueue,
    flush: flush,
    refreshBundle: refreshBundle,
    ping: ping,
    snapshot: snapshot,
    nextDelay: nextDelay,
    boot: boot,
    markWaking: markWaking
  };
})(window);
