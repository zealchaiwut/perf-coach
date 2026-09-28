/**
 * Home "Road to {A-race}" card (WC-17 mock) — countdown, goal/estimate/range,
 * race-specific End/Spd, and needs-result warnings for past B races.
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _header(title) {
    return (
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-flag-2"></i>' + esc(title) + '</h2>' +
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

  function _fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : ''));
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }

  function _daysUntil(iso) {
    if (!iso) return null;
    var a = new Date(window.AppCommon.todayISO() + 'T00:00:00');
    var b = new Date(String(iso).slice(0, 10) + 'T00:00:00');
    return Math.round((b - a) / 86400000);
  }

  function _roadTitle(name) {
    if (!name) return 'Road to your A-race';
    var short = name.replace(/\s+\d{4}$/, '').trim();
    return 'Road to ' + short;
  }

  function _needsResultRaces(races) {
    var today = window.AppCommon.todayISO();
    return (races || []).filter(function (r) {
      return r.type !== 'checkpoint' && r.date && r.date < today &&
        !(r.status === 'done' && r.actual_time_seconds != null);
    });
  }

  function _needsResultBanner(races) {
    var needs = _needsResultRaces(races);
    if (!needs.length) return '';
    var r = needs[0];
    var msg = (r.name || 'Race') + ' needs a result';
    if (r.suggested_actual_time_seconds) {
      msg += ' — prefilled ' + _fmtTime(r.suggested_actual_time_seconds) + ' from matched workout';
    }
    return (
      '<div class="hrc-warn">' +
        '<span class="hrc-warn-ic">⚠</span>' +
        '<span>' + esc(msg) + '</span>' +
        '<a href="/log#performance" class="hrc-warn-link">Record →</a>' +
      '</div>'
    );
  }

  function _raceScoresHtml(primary) {
    var sc = primary && primary.computed && primary.computed.scores;
    if (!sc || sc.kind !== 'required') return '';
    return (
      '<div class="hrc-scores">' +
        '<span class="hrc-scores-lab">Race-specific</span>' +
        '<span class="hrc-score-pill">End ' + esc(String(sc.end)) + '</span>' +
        '<span class="hrc-score-pill">Spd ' + esc(String(sc.spd)) + '</span>' +
      '</div>'
    );
  }

  function _paint(host, primary, allRaces) {
    if (!primary) {
      host.innerHTML = _header('Road to your A-race') +
        '<div class="hrc-empty">' +
          '<div class="hrc-empty-sub">No upcoming A-race set yet.</div>' +
          '<a class="hrc-empty-cta" href="/log#performance">Set a race on Performance →</a>' +
        '</div>';
      return;
    }

    var distKm = parseFloat(primary.distance || 0);
    var days = _daysUntil(primary.date);
    var goalSec = primary.goal_time_seconds || null;
    var est = primary.computed && primary.computed.estimate;
    var estSec = est && est.est != null ? est.est : null;
    var bandMin = est && est.band != null ? Math.max(1, Math.round(est.band / 60)) : null;
    var rangeHtml = '';
    if (estSec != null && est && est.band != null) {
      rangeHtml =
        '<div class="hrc-est"><div class="hrc-est-k">Range</div>' +
          '<div class="hrc-est-v">' + esc(_fmtTime(estSec - est.band)) + ' – ' + esc(_fmtTime(estSec + est.band)) + '</div>' +
        '</div>';
    }
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

    host.innerHTML =
      _header(_roadTitle(primary.name)) +
      _needsResultBanner(allRaces) +
      '<div class="hrc-race">' +
        (days != null
          ? '<div class="hrc-days"><div class="hrc-days-n">' + Math.max(0, days) + '</div><div class="hrc-days-k">days</div></div>'
          : '') +
        '<div class="hrc-info">' +
          '<div class="hrc-info-t">' + esc(primary.name || 'Unnamed') + '</div>' +
          '<div class="hrc-info-m">' + esc(_fmtDate(primary.date)) +
            (distKm ? ' · ' + distKm.toFixed(1) + ' km' : '') +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="hrc-stats">' +
        '<div class="hrc-est"><div class="hrc-est-k">Goal</div>' +
          '<div class="hrc-est-v">' + esc(goalSec ? _fmtTime(goalSec) : '—') + '</div></div>' +
        (estSec != null
          ? '<div class="hrc-est"><div class="hrc-est-k">Estimate</div>' +
              '<div class="hrc-est-v hrc-est-v--ok">' + esc(_fmtTime(estSec)) + '</div>' +
              (bandMin ? '<div class="hrc-est-s">± ' + bandMin + ' min</div>' : '') +
            '</div>'
          : '') +
        rangeHtml +
        gapHtml +
      '</div>' +
      _raceScoresHtml(primary);
  }

  function _paintPrimary(host, primary, allRaces) {
    _paint(host, primary, allRaces || (primary ? [primary] : []));
  }

  function render(host, primary) {
    if (!host) return;

    function _fromBundle(bundle) {
      var races = (bundle && Array.isArray(bundle.races)) ? bundle.races : [];
      var found =
        races.find(function (r) { return r.type === 'race' && r.priority === 'A' && r.status !== 'done'; }) ||
        races.find(function (r) { return r.type === 'race' && r.status !== 'done'; }) ||
        null;
      if (!found && primary && primary.name) {
        found = primary;
        if (!races.length) races = [primary];
      }
      _paint(host, found, races);
    }

    if (primary && primary.name) {
      _paintPrimary(host, primary, [primary]);
    } else {
      host.innerHTML = _header('Road to your A-race') + '<div class="hrc-loading">Loading…</div>';
    }

    fetch('/api/plan/computed')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(_fromBundle)
      .catch(function () {
        if (primary && primary.name) {
          _paintPrimary(host, primary, [primary]);
        } else {
          _paint(host, null, []);
        }
      });
  }

  window.HomeRaceCard = { render: render };
})();
