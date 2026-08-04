/**
 * Home "Today's plan" card — the forward-looking focal point (Home
 * today-focal-point UX review). Sits top row, beside Readiness — the slot
 * that used to hold the retrospective Recent Workouts list, which answered
 * "what did I already do" instead of "what should I do today". Recent
 * workouts moved to its own #home-recent-workouts-card below Training; this
 * card takes over the prominent spot.
 *
 * Same data source as the Plan tab and the Week plan teaser
 * (home-brief-week-plan-card.js): GET /api/planned-sessions?from=&to=. No
 * new endpoint, no LLM — day/type/TSS come straight from PlannedSession rows
 * and the same formula-only estimated_tss the Plan tab already shows (see
 * backend/main.py _planned_session_dict). Three states:
 *   1. One or more real (non-"rest") planned sessions today → show them.
 *   2. Nothing planned today, but the week has planned sessions elsewhere
 *      (or today is an explicit "rest" PlannedSession row) → honest
 *      "Rest day" state, not a silent blank.
 *   3. Zero non-rest planned sessions for the WHOLE week → honest "No plan
 *      for today" state — a blank week almost always means no plan has ever
 *      been drafted (no A-race set), not that the planner reviewed today and
 *      recommended nothing. Same wording convention as the Week plan
 *      teaser's own zero-plan notice.
 */
(function () {
  'use strict';

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  // ── Date helpers — same Mon-Sun week math as home-brief-week-plan-card.js
  // (DUPLICATED intentionally: a five-line local helper is cheaper than a
  // shared module for two call sites, same call this codebase already makes
  // for _hpfBlockDelta in home-readiness-training-sleep.js). ──────────────

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

  function _fam(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift'; // 'strength' and anything unrecognized
  }

  // Session meta line — DUPLICATED from home-brief-week-plan-card.js's
  // _sessionMeta (same PlannedSession.structure shape, same summarization).
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
    return p.notes ? String(p.notes).slice(0, 60) : '';
  }

  // Real logged TSS (p.actual.tss) when the session is done/matched; the
  // server-computed historical-baseline estimate (p.estimated_tss, "~" —
  // only present while still achievable, see backend _planned_session_dict)
  // otherwise. Never fabricates a number — same rule as training-plan.js's
  // _sessionTss/_sessionTssBadge, duplicated here for this read-only card.
  function _sessionTss(p) {
    if (p.actual && p.actual.tss != null) return { value: p.actual.tss, estimated: false };
    if (p.estimated_tss != null) return { value: p.estimated_tss, estimated: true };
    return null;
  }

  function _tssBadgeHtml(p) {
    var t = _sessionTss(p);
    if (!t) return '';
    var label = (t.estimated ? '~' : '') + Math.round(t.value) + ' TSS';
    return '<span class="tfc-tss' + (t.estimated ? ' is-estimated' : '') + '">' + esc(label) + '</span>';
  }

  function _statusChipHtml(p) {
    if (p.status === 'done_auto' || p.status === 'done_manual') {
      return '<span class="hc-tag hc-tag--done">done</span>';
    }
    if (p.status === 'needs_review') {
      return '<span class="hc-tag">needs review</span>';
    }
    if (p.status === 'missed' || p.status === 'missed_auto' || p.status === 'missed_manual') {
      return '<span class="hc-tag">missed</span>';
    }
    return '';
  }

  function _sessHtml(p) {
    var fam = _fam(p.session_type);
    var name = p.name || '(untitled)';
    if (name.length > 46) name = name.slice(0, 44) + '…';
    var meta = _sessionMeta(p);
    return (
      '<div class="tfc-sess tfc-sess--' + fam + '">' +
        '<div class="tfc-sess-top">' +
          '<span class="hpl-tag hpl-tag--' + fam + '">' + esc(fam) + '</span>' +
          _tssBadgeHtml(p) +
          _statusChipHtml(p) +
        '</div>' +
        '<div class="tfc-name">' + esc(name) + '</div>' +
        (meta ? '<div class="tfc-meta">' + esc(meta) + '</div>' : '') +
      '</div>'
    );
  }

  function _headHtml() {
    return (
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-calendar-event"></i>Today\'s plan</h2>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>'
    );
  }

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      _headHtml() +
      '<div class="brief-skeleton">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el, msg) {
    if (!el) return;
    el.innerHTML =
      _headHtml() +
      '<div class="brief-unavail">' + esc(msg || 'Could not load today\'s plan') + '</div>';
  }

  function _emptyHtml(iconClass, message, subHtml) {
    return (
      '<div class="tfc-empty">' +
        '<i class="ti ' + iconClass + ' tfc-empty-icon" aria-hidden="true"></i>' +
        '<p class="tfc-empty-msg">' + message + '</p>' +
        (subHtml || '') +
      '</div>'
    );
  }

  function render(el) {
    if (!el) return;
    renderSkeleton(el);

    var monday = _mondayOf(new Date());
    var from = _iso(monday);
    var to = _iso(_addDays(monday, 6));
    var todayStr = window.AppCommon.todayISO();

    fetch('/api/planned-sessions?from=' + from + '&to=' + to)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var days = (data && data.days) || [];
        var today = days.find(function (d) { return d.date === todayStr; }) || null;

        // An explicit "rest" PlannedSession row is a deliberate day off, not
        // a real session to display — filter it out the same way the backend
        // itself does when deciding whether a day has real content (see
        // backend/main.py's `non_rest` filter).
        var todayPlanned = ((today && today.planned) || []).filter(function (p) {
          return p.session_type !== 'rest';
        });
        var todayUnplanned = (today && today.unplanned) || [];

        var totalRealPlanned = days.reduce(function (n, d) {
          return n + (d.planned || []).filter(function (p) { return p.session_type !== 'rest'; }).length;
        }, 0);

        if (todayPlanned.length) {
          el.innerHTML =
            _headHtml() +
            '<div class="tfc-list">' +
              todayPlanned.map(_sessHtml).join('') +
            '</div>';
          return;
        }

        if (!totalRealPlanned) {
          // Zero planned sessions across the whole week — almost always means
          // no plan has ever been drafted (no A-race set), not a genuine
          // all-rest week. Same wording as the Week plan teaser's own notice.
          el.innerHTML =
            _headHtml() +
            _emptyHtml(
              'ti-calendar-off',
              'No plan for today. Set a goal race on ' +
                '<a href="/log#performance">Performance</a> to generate one.'
            );
          return;
        }

        // Rest day within an active plan — honest, not a blank.
        var subHtml = '';
        if (todayUnplanned.length) {
          var first = todayUnplanned[0];
          var extra = todayUnplanned.length > 1 ? ' +' + (todayUnplanned.length - 1) + ' more' : '';
          subHtml = '<p class="tfc-empty-sub">Logged anyway: ' + esc(first.name || 'workout') + esc(extra) + '</p>';
        }
        el.innerHTML =
          _headHtml() +
          _emptyHtml('ti-moon-stars', 'Rest day — nothing planned for today. Recover well.', subHtml);
      })
      .catch(function () {
        renderUnavailable(el);
      });
  }

  window.HomeTodayPlanCard = {
    render: render,
    renderSkeleton: renderSkeleton,
    renderUnavailable: renderUnavailable,
  };
})();
