// Shared /api/sync/status poller (perf/hot-paths Task 6).
//
// Five independent pollers used to exist (nav.js, training-log.js x2,
// settings.html x2), each with its own setInterval/setTimeout loop hitting
// the same endpoint. This module is the single home for that polling: one
// timer, subscriber callbacks, start-on-demand (only polls while a sync is
// actually running).
//
// No build step in this project (plain <script> tags, served as
// FileResponse), so this attaches to `window.SyncPoller` and must be loaded
// before any consumer (nav.js, training-log.js, settings.html).
(function (global) {
  'use strict';

  var POLL_INTERVAL_MS = 3000;
  var _timer = null;
  var _inFlight = false;
  var _subscribers = [];

  function _notify(data) {
    // Copy so a subscriber unsubscribing mid-notify doesn't skip callbacks.
    _subscribers.slice().forEach(function (cb) {
      try {
        cb(data);
      } catch (e) {
        /* one bad subscriber shouldn't break the others */
      }
    });
  }

  function stop() {
    if (_timer) {
      clearInterval(_timer);
      _timer = null;
    }
  }

  function start() {
    if (_timer) return;
    _timer = setInterval(_poll, POLL_INTERVAL_MS);
  }

  function _poll() {
    if (_inFlight) return;
    _inFlight = true;
    fetch('/api/sync/status')
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (data) {
        _inFlight = false;
        if (!data) {
          stop();
          _notify(null);
          return;
        }
        _notify(data);
        if (data.status === 'running') {
          start();
        } else {
          stop();
        }
      })
      .catch(function () {
        _inFlight = false;
        stop();
        _notify(null);
      });
  }

  // Fire one immediate status check (page load, or right after a sync POST
  // returns 202/409) and begin interval polling if a job turns out active.
  function checkNow() {
    _poll();
  }

  function subscribe(cb) {
    _subscribers.push(cb);
    return function unsubscribe() {
      var idx = _subscribers.indexOf(cb);
      if (idx !== -1) _subscribers.splice(idx, 1);
    };
  }

  // Promise-based "wait until the current sync finishes" helper, for call
  // sites that trigger a sync and need to await its completion rather than
  // subscribe to ongoing updates (e.g. sequential multi-provider syncs).
  function waitForIdle() {
    return new Promise(function (resolve, reject) {
      var unsub = subscribe(function (data) {
        if (!data || data.status === 'idle') {
          unsub();
          resolve(data);
          return;
        }
        if (data.status === 'error') {
          unsub();
          reject(new Error(data.error || 'Sync failed'));
          return;
        }
        if (data.status !== 'running') {
          unsub();
          resolve(data);
        }
        // else still running — keep waiting for the next notification.
      });
      checkNow();
    });
  }

  global.SyncPoller = {
    subscribe: subscribe,
    checkNow: checkNow,
    waitForIdle: waitForIdle,
    start: start,
    stop: stop,
  };
})(typeof window !== 'undefined' ? window : this);
