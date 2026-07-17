/**
 * Home week plan — same data as Training > Plan (`/api/planned-sessions`),
 * read-only teaser of the current Mon–Sun week. Edit on Plan tab.
 */
(function () {
  'use strict';

  var DOW = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _iso(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function _mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var dow = (x.getDay() + 6) % 7; // 0=Mon
    x.setDate(x.getDate() - dow);
    return x;
  }

  function _addDays(d, n) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() + n);
    return x;
  }

  function _parseISO(iso) {
    var p = iso.split('-');
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  function _fam(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift';
  }

  function _sessionMeta(p) {
    var s = p.structure || {};
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0;
        var r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      var tgt = (s.blocks.find(function (b) { return b.target; }) || {}).target;
      return (tot ? tot + 'min' : '') + (tgt ? ' · ' + tgt : '');
    }
    if (Array.isArray(s.exercises) && s.exercises.length) {
      return s.exercises.length + ' exercise' + (s.exercises.length > 1 ? 's' : '');
    }
    return p.notes ? String(p.notes).slice(0, 40) : '';
  }

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>' +
      '<div class="brief-skeleton brief-skeleton--week">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el, msg) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>' +
      '<div class="brief-unavail">' + esc(msg || 'Could not load week plan') + '</div>';
  }

  function _dayRowHtml(day, todayStr) {
    var isToday = day.date === todayStr;
    var planned = day.planned || [];
    var dow = day.dow || DOW[(_parseISO(day.date).getDay() + 6) % 7];
    var dnum = _parseISO(day.date).getDate();

    var body;
    if (!planned.length) {
      body = '<div class="hpl-rest">Rest</div>';
    } else {
      body = planned.map(function (p) {
        var fam = _fam(p.session_type);
        var meta = _sessionMeta(p);
        var name = p.name || '(untitled)';
        if (name.length > 42) name = name.slice(0, 40) + '…';
        return (
          '<div class="hpl-sess hpl-sess--' + fam + '">' +
            '<div class="hpl-sess-top">' +
              '<span class="hpl-tag hpl-tag--' + fam + '">' + esc(fam) + '</span>' +
            '</div>' +
            '<div class="hpl-name">' + esc(name) + '</div>' +
            (meta ? '<div class="hpl-meta">' + esc(meta) + '</div>' : '') +
          '</div>'
        );
      }).join('');
    }

    return (
      '<div class="hpl-day' + (isToday ? ' hpl-day--today' : '') + '">' +
        '<div class="hpl-label">' +
          '<span class="hpl-dow">' + esc(dow) + '</span>' +
          '<span class="hpl-dnum">' + dnum + '</span>' +
        '</div>' +
        '<div class="hpl-body">' + body + '</div>' +
      '</div>'
    );
  }

  function render(el) {
    if (!el) return;
    renderSkeleton(el);

    var monday = _mondayOf(new Date());
    var from = _iso(monday);
    var to = _iso(_addDays(monday, 6));
    var todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });

    fetch('/api/planned-sessions?from=' + from + '&to=' + to)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var days = (data && data.days) || [];
        el.innerHTML =
          '<div class="card-head">' +
            '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
            '<a href="/log#plan">Full plan &#8594;</a>' +
          '</div>' +
          '<div class="hpl-list">' +
            days.map(function (d) { return _dayRowHtml(d, todayStr); }).join('') +
          '</div>';
      })
      .catch(function () {
        renderUnavailable(el);
      });
  }

  window.HomeBriefWeekPlanCard = {
    render: render,
    renderSkeleton: renderSkeleton,
    renderUnavailable: renderUnavailable,
  };
})();
