/**
 * Home "Race" card (home revamp v2) — countdown + goal vs. estimate for the
 * primary A-race. Sourced entirely from GET /api/plan/computed's `races`
 * array: same bundle home.js's old _renderGoalCard read for goal/date, and
 * the SAME estimate field (`race.computed.estimate`) training-performance.js
 * uses for its race cards / time-curve projection — that field comes from
 * the authoritative time_curve engine. Deliberately does NOT call
 * /api/plans/{id}/projection: training-performance.js documents that
 * endpoint runs a separate, less-integrated estimate model that has
 * disagreed with this one in production (see its _renderPerfProjection
 * comment) — using it here would risk the same two-numbers-for-one-race bug.
 *
 * No season bar (projection has no phase boundaries to draw one from).
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _header() {
    return (
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-flag-2"></i>Race</h2>' +
        '<a href="/log#performance">Performance &#8594;</a>' +
      '</div>'
    );
  }

  function _fmtTime(secs) {
    if (secs == null || !isFinite(secs)) return '—';
    secs = Math.round(secs);
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
  }

  function _fmtSignedTime(deltaSecs) {
    if (deltaSecs == null || !isFinite(deltaSecs)) return '—';
    var sign = deltaSecs > 0 ? '+' : (deltaSecs < 0 ? '\u2212' : '');
    var abs = Math.round(Math.abs(deltaSecs));
    var m = Math.floor(abs / 60);
    var s = abs % 60;
    return sign + m + ':' + String(s).padStart(2, '0');
  }

  function _fmtPace(secPerKm) {
    if (secPerKm == null || !isFinite(secPerKm) || secPerKm <= 0) return '';
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    return m + ':' + String(s).padStart(2, '0') + '/km';
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : ''));
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
  }

  function _daysUntil(iso) {
    if (!iso) return null;
    var today = window.AppCommon.todayISO();
    var msPerDay = 86400000;
    var a = new Date(today + 'T00:00:00');
    var b = new Date(iso + 'T00:00:00');
    if (isNaN(a.getTime()) || isNaN(b.getTime())) return null;
    return Math.round((b - a) / msPerDay);
  }

  function render(host) {
    if (!host) return;
    host.innerHTML = _header() + '<div class="hrc-loading">Loading…</div>';

    fetch('/api/plan/computed')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (bundle) {
        var races = (bundle && Array.isArray(bundle.races)) ? bundle.races : [];
        var primary =
          races.find(function (r) { return r.type === 'race' && r.priority === 'A' && r.status !== 'done'; }) ||
          races.find(function (r) { return r.type === 'race' && r.status !== 'done'; }) ||
          null;

        if (!primary) {
          host.innerHTML = _header() +
            '<div class="hrc-empty">' +
              '<div class="hrc-empty-sub">No upcoming race set yet.</div>' +
              '<a class="hrc-empty-cta" href="/log#performance">Set a race on Performance &#8594;</a>' +
            '</div>';
          return;
        }

        var distKm = parseFloat(primary.distance || 0);
        var days = _daysUntil(primary.date);
        var weeksOut = days != null ? Math.max(0, Math.round(days / 7)) : null;

        var goalSec = primary.goal_time_seconds || null;
        var goalPace = goalSec && distKm ? _fmtPace(goalSec / distKm) : '';

        var est = primary.computed && primary.computed.estimate;
        var estSec = est && est.est != null ? est.est : null;
        var estBand = est && est.band != null ? Math.max(1, Math.round(est.band / 60)) : null;

        var gapHtml = '';
        if (goalSec != null && estSec != null) {
          var gapSec = estSec - goalSec;
          var inside = Math.abs(gapSec) <= 30;
          gapHtml =
            '<div class="hrc-est"><div class="hrc-est-k">Gap</div>' +
              '<div class="hrc-est-v">' + esc(_fmtSignedTime(gapSec)) + '</div>' +
              '<div class="hrc-est-s">' + (inside ? 'inside goal' : (gapSec > 0 ? 'behind goal' : 'ahead of goal')) + '</div>' +
            '</div>';
        }

        var estHtml = estSec != null
          ? '<div class="hrc-est"><div class="hrc-est-k">Estimate</div>' +
              '<div class="hrc-est-v hrc-est-v--ok">' + esc(_fmtTime(estSec)) + '</div>' +
              '<div class="hrc-est-s">' + (estBand != null ? '&plusmn; ' + estBand + ' min' : '') + '</div>' +
            '</div>'
          : '';

        host.innerHTML =
          _header() +
          '<div class="hrc-race">' +
            (days != null
              ? '<div class="hrc-days"><div class="hrc-days-n">' + Math.max(0, days) + '</div><div class="hrc-days-k">days</div></div>'
              : '') +
            '<div class="hrc-info">' +
              '<div class="hrc-info-t">' + esc(primary.name || 'Unnamed') + '</div>' +
              '<div class="hrc-info-m">' + esc(_fmtDate(primary.date)) +
                (distKm ? ' &middot; ' + distKm.toFixed(2) + ' km' : '') +
                ' &middot; A-priority' +
                (weeksOut != null ? ' &middot; ' + weeksOut + ' weeks out' : '') +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="hrc-stats">' +
            '<div class="hrc-est"><div class="hrc-est-k">Goal</div>' +
              '<div class="hrc-est-v">' + esc(goalSec ? _fmtTime(goalSec) : '—') + '</div>' +
              '<div class="hrc-est-s">' + esc(goalPace) + '</div>' +
            '</div>' +
            estHtml +
            gapHtml +
          '</div>';
      })
      .catch(function () {
        host.innerHTML = _header() + '<div class="hrc-empty"><div class="hrc-empty-sub">Could not load race.</div></div>';
      });
  }

  window.HomeRaceCard = { render: render };
})();
