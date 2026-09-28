/**
 * Home "Today's session" card (WC-17 mock) — workout detail with exercise list.
 * Picks today's planned session (not the next open session forward).
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _fam(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'mobility' || t === 'stretch') return 'stretch';
    return 'lift';
  }

  function _chipLabel(p) {
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength') return 'LIFT';
    if (t === 'mobility') return 'MOBILITY';
    if (t === 'plyo') return 'PLYO';
    return 'RUN';
  }

  function _displayName(p) {
    var n = (p && p.name) ? String(p.name).trim() : '';
    if (n) return n;
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength') return 'Strength session';
    if (t === 'mobility') return 'Mobility';
    return 'Easy run';
  }

  function _todaySessions(weekDays) {
    var today = _todayISO();
    var day = (weekDays || []).find(function (d) { return d.date === today; });
    if (!day) return [];
    return (day.planned || []).filter(function (p) {
      return (p.session_type || '').toLowerCase() !== 'rest';
    });
  }

  function _pickPrimary(sessions) {
    if (!sessions.length) return null;
    var core = sessions.filter(function (p) {
      return (p.session_type || '').toLowerCase() !== 'mobility';
    });
    return core[0] || sessions[0];
  }

  function _durationLabel(p) {
    var s = (p && p.structure) || {};
    if (s.duration_minutes != null && isFinite(Number(s.duration_minutes))) {
      return Math.round(Number(s.duration_minutes)) + ' min';
    }
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0;
        var r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      if (tot) return tot + ' min';
    }
    return '';
  }

  function _exerciseLines(p) {
    var s = (p && p.structure) || {};
    var out = [];
    if (Array.isArray(s.exercises)) {
      s.exercises.forEach(function (ex) {
        if (!ex || !ex.name) return;
        var bits = [ex.name];
        if (ex.sets && ex.reps) bits.push(ex.sets + ' × ' + ex.reps);
        else if (ex.reps) bits.push(String(ex.reps));
        out.push(bits.join(' · '));
      });
    }
    if (Array.isArray(s.blocks)) {
      s.blocks.forEach(function (b) {
        if (b && b.label) {
          var line = b.label;
          if (b.duration_min) line += ' · ' + b.duration_min + ' min';
          if (b.target) line += ' · ' + b.target;
          out.push(line);
        }
      });
    }
    return out.slice(0, 8);
  }

  function _statusLabel(p) {
    var st = (p && p.status) || 'planned';
    if (st === 'done_auto' || st === 'done_manual') return 'Done';
    if (st.indexOf('missed') === 0) return 'Missed';
    if (st === 'skipped') return 'Skipped';
    return 'Planned';
  }

  function render(host, opts) {
    if (!host) return;
    opts = opts || {};
    var sessions = _todaySessions(opts.weekDays);
    var p = _pickPrimary(sessions);

    if (!p) {
      host.innerHTML =
        '<div class="hts-card hts-card--empty">' +
          '<div class="hts-head"><span class="hts-k">Today\'s session</span></div>' +
          '<div class="hts-body">' +
            '<p class="hts-empty-msg">Rest day — nothing scheduled.</p>' +
            '<a class="hts-link" href="/log#plan">View week plan →</a>' +
          '</div>' +
        '</div>';
      return;
    }

    var fam = _fam(p.session_type);
    var dur = _durationLabel(p);
    var exercises = _exerciseLines(p);
    var status = _statusLabel(p);
    var openUrl = '/log?tab=plan&session=' + encodeURIComponent(p.id);

    host.innerHTML =
      '<div class="hts-card">' +
        '<div class="hts-head">' +
          '<span class="hts-k">Today\'s session</span>' +
          '<span class="hts-status hts-status--' + esc(status.toLowerCase()) + '">' + esc(status) + '</span>' +
        '</div>' +
        '<div class="hts-body">' +
          '<div class="hts-title-row">' +
            '<span class="hts-tag hts-tag--' + fam + '">' + esc(_chipLabel(p)) + '</span>' +
            '<span class="hts-name">' + esc(_displayName(p)) + '</span>' +
            (dur ? '<span class="hts-dur">' + esc(dur) + '</span>' : '') +
          '</div>' +
          (exercises.length
            ? '<ul class="hts-exercises">' +
                exercises.map(function (line) {
                  return '<li>' + esc(line) + '</li>';
                }).join('') +
              '</ul>'
            : '<p class="hts-meta">' + esc(p.notes || 'Open for full session detail.') + '</p>') +
          '<div class="hts-actions">' +
            '<button type="button" class="hts-btn hts-btn--primary" id="hts-open">Open session</button>' +
            (status === 'Planned'
              ? '<button type="button" class="hts-btn hts-btn--ghost" id="hts-done">Mark done</button>'
              : '') +
          '</div>' +
        '</div>' +
      '</div>';

    var openBtn = host.querySelector('#hts-open');
    if (openBtn) {
      openBtn.addEventListener('click', function () {
        if (opts.onOpen) opts.onOpen(p.id);
        else window.location.href = openUrl;
      });
    }
    var doneBtn = host.querySelector('#hts-done');
    if (doneBtn) {
      doneBtn.addEventListener('click', function () {
        if (opts.onMarkDone) opts.onMarkDone(p.id);
      });
    }
  }

  window.HomeTodaySession = { render: render };
})();
