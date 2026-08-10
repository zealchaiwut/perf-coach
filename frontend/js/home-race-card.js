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
 * Progress bar is a simple elapsed fill from race.created_at → race.date
 * (no named build/peak/taper segments — those phase boundaries aren't in
 * the plan/computed payload).
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

  function _daysBetween(isoA, isoB) {
    if (!isoA || !isoB) return null;
    var a = new Date(String(isoA).slice(0, 10) + 'T00:00:00');
    var b = new Date(String(isoB).slice(0, 10) + 'T00:00:00');
    if (isNaN(a.getTime()) || isNaN(b.getTime())) return null;
    return Math.round((b - a) / 86400000);
  }

  function _daysUntil(iso) {
    return _daysBetween(window.AppCommon.todayISO(), iso);
  }

  // Simple countdown progress: created_at → race date. Returns '' when we
  // can't compute an honest span (missing created_at, inverted dates, etc.).
  function _progressHtml(primary, daysLeft) {
    var startIso = primary.created_at ? String(primary.created_at).slice(0, 10) : null;
    var raceIso = primary.date ? String(primary.date).slice(0, 10) : null;
    if (!startIso || !raceIso) return '';

    var total = _daysBetween(startIso, raceIso);
    if (total == null || total <= 0) return '';

    var today = window.AppCommon.todayISO();
    var elapsed = _daysBetween(startIso, today);
    if (elapsed == null) return '';
    elapsed = Math.max(0, Math.min(total, elapsed));
    var pct = Math.round((elapsed / total) * 100);
    var left = daysLeft != null ? Math.max(0, daysLeft) : Math.max(0, total - elapsed);
    var weekNow = Math.max(1, Math.min(Math.ceil(total / 7), Math.ceil(Math.max(1, elapsed) / 7) || 1));
    var weekTotal = Math.max(1, Math.ceil(total / 7));

    return (
      '<div class="hrc-progress">' +
        '<div class="hrc-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '"' +
          ' aria-label="Race countdown progress">' +
          '<div class="hrc-progress-fill" style="width:' + pct + '%"></div>' +
        '</div>' +
        '<div class="hrc-progress-meta">' +
          '<span>week ' + weekNow + ' of ' + weekTotal + '</span>' +
          '<span>' + left + ' day' + (left === 1 ? '' : 's') + ' left</span>' +
        '</div>' +
      '</div>'
    );
  }

  function render(host, primary) {
    if (!host) return;
    host.innerHTML = _header() + '<div class="hrc-loading">Loading…</div>';

    function _paint(primaryRace) {
      if (!primaryRace) {
        host.innerHTML = _header() +
          '<div class="hrc-empty">' +
            '<div class="hrc-empty-sub">No upcoming race set yet.</div>' +
            '<a class="hrc-empty-cta" href="/log#performance">Set a race on Performance &#8594;</a>' +
          '</div>';
        return;
      }
      _paintPrimary(primaryRace);
    }

    // Phase B: prefer slim race from /api/home/summary (no cold plan/computed).
    if (primary !== undefined) {
      _paint(primary || null);
      return;
    }

    fetch('/api/plan/computed')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (bundle) {
        var races = (bundle && Array.isArray(bundle.races)) ? bundle.races : [];
        var found =
          races.find(function (r) { return r.type === 'race' && r.priority === 'A' && r.status !== 'done'; }) ||
          races.find(function (r) { return r.type === 'race' && r.status !== 'done'; }) ||
          null;
        _paint(found);
      })
      .catch(function () { _paint(null); });
  }

  function _paintPrimary(primary) {
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
          '</div>' +
          _progressHtml(primary, days);
  }

  window.HomeRaceCard = { render: render };
})();
