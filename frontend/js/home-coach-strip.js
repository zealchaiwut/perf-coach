/**
 * Home Coach — Today strip (brief v4).
 * Priority: synced workout → planned today (nudge) → rest day → upcoming next.
 */
(function () {
  'use strict';

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _chipClass(tone) {
    if (tone === 'ok') return 'hc-chip hc-chip--ok';
    if (tone === 'warn') return 'hc-chip hc-chip--warn';
    return 'hc-chip hc-chip--info';
  }

  /** Top 2 focus rows — titles match full-brief section headlines. */
  function _focusRows(brief) {
    var dig = (brief.digest && brief.digest.focus) || [];
    var bySid = {};
    (brief.sections || []).forEach(function (s) {
      if (s && s.id) bySid[s.id] = s;
    });
    return dig.slice(0, 2).map(function (f, i) {
      var sec = f.section_id ? bySid[f.section_id] : null;
      var headline = (sec && sec.headline) || f.title || '';
      return {
        rank: f.rank != null ? f.rank : i + 1,
        headline: headline,
      };
    }).filter(function (r) { return r.headline; });
  }

  function _sessionBlock(today) {
    var done = today.completed_workout;
    if (done && done.name) {
      var typeTag = (done.type || 'run').toString().toUpperCase();
      var stats = done.stats_line || '';
      var praise = done.praise || 'Good work. Session logged.';
      return (
        '<div class="hc-sess hc-sess--done">' +
          '<div class="hc-sess-label"><span class="hc-tag hc-tag--done">TODAY\'S WORKOUT</span></div>' +
          '<div class="hc-sess-t">' + esc(done.name) +
            ' <span class="hc-tag">' + esc(typeTag) + '</span></div>' +
          (stats ? '<div class="hc-sess-stats">' + esc(stats) + '</div>' : '') +
          '<div class="hc-sess-praise">' + esc(praise) + '</div>' +
        '</div>'
      );
    }

    var plan = today.planned_today;
    if (plan && plan.kind === 'rest') {
      return (
        '<div class="hc-sess hc-sess--rest">' +
          '<div class="hc-sess-label"><span class="hc-tag hc-tag--rest">REST DAY</span></div>' +
          '<div class="hc-sess-t">' + esc(plan.name || 'Rest') + '</div>' +
          '<div class="hc-sess-praise hc-sess-praise--rest">' +
            esc(plan.nudge || 'Rest day. Recover well. No training needed.') +
          '</div>' +
        '</div>'
      );
    }

    if (plan && plan.kind === 'workout' && plan.name) {
      var pType = (plan.type || 'run').toString().toUpperCase();
      var pMeta = plan.summary || '';
      return (
        '<div class="hc-sess hc-sess--plan">' +
          '<div class="hc-sess-label"><span class="hc-tag hc-tag--next">TODAY\'S PLAN</span></div>' +
          '<div class="hc-sess-t">' + esc(plan.name) +
            ' <span class="hc-tag">' + esc(pType) + '</span></div>' +
          (pMeta ? '<div class="hc-sess-m">' + esc(pMeta) + '</div>' : '') +
          '<div class="hc-sess-nudge">' +
            esc(plan.nudge || 'Still on the plan for today. Get this one done.') +
          '</div>' +
        '</div>'
      );
    }

    var sess = today.session || {};
    var typeTag = (sess.type || 'run').toString().toUpperCase();
    var name = sess.name || 'Today';
    var meta = sess.summary || '';
    var when = sess.date ? ('Planned ' + sess.date) : '';
    return (
      '<div class="hc-sess">' +
        '<div class="hc-sess-label"><span class="hc-tag hc-tag--next">NEXT WORKOUT</span></div>' +
        '<div class="hc-sess-t">' + esc(name) +
          ' <span class="hc-tag">' + esc(typeTag) + '</span></div>' +
        (when ? '<div class="hc-sess-m">' + esc(when) + '</div>' : '') +
        (meta ? '<div class="hc-sess-m">' + esc(meta) + '</div>' : '') +
      '</div>'
    );
  }

  function _ctaBlock(mode) {
    // mode: 'done' | 'rest' | 'default'
    if (mode === 'done' || mode === 'rest') {
      return (
        '<div class="hc-today-cta">' +
          '<button type="button" class="hc-cta hc-cta--ghost" data-hc-log-niggle>Log niggle / illness</button>' +
        '</div>'
      );
    }
    return (
      '<div class="hc-today-cta">' +
        '<button type="button" class="hc-cta hc-cta--lime" data-hc-log-metrics>Log today\'s metrics · 30s</button>' +
        '<button type="button" class="hc-cta hc-cta--ghost" data-hc-log-niggle>Log niggle / illness</button>' +
      '</div>'
    );
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief || !brief.today) {
      el.innerHTML = '';
      el.hidden = true;
      return;
    }
    el.hidden = false;
    var today = brief.today || {};
    var chips = today.chips || [];
    var updated = brief.brief_date || '';
    var rows = _focusRows(brief);
    var hasDone = !!(today.completed_workout && today.completed_workout.name);
    var isRest = !!(today.planned_today && today.planned_today.kind === 'rest' && !hasDone);
    var ctaMode = hasDone ? 'done' : (isRest ? 'rest' : 'default');

    var chipsHtml = chips.map(function (c) {
      return '<span class="' + _chipClass(c.tone) + '">' + esc(c.text) + '</span>';
    }).join('');

    // Pipeline v2: append WEEK DRAFT READY chip when a reviewable draft exists.
    // Fetched async; first paint may omit it, then we patch the chips row.
    function _appendDraftChip() {
      fetch('/api/plan/draft-status', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (st) {
          if (!st || !st.ready) return;
          var row = el.querySelector('.hc-today-chips');
          if (!row) {
            row = document.createElement('div');
            row.className = 'hc-today-chips';
            var todayCard = el.querySelector('.hc-today');
            if (todayCard) todayCard.appendChild(row);
          }
          if (row.querySelector('[data-hc-draft-chip]')) return;
          var a = document.createElement('a');
          a.className = 'hc-chip hc-chip--info';
          a.setAttribute('data-hc-draft-chip', '1');
          a.href = st.deeplink || '/log?tab=plan';
          a.textContent = 'WEEK DRAFT READY';
          a.style.textDecoration = 'none';
          row.appendChild(a);
        })
        .catch(function () { /* ignore */ });
    }
    _appendDraftChip();

    var focusHtml;
    if (rows.length) {
      focusHtml = rows.map(function (r) {
        return (
          '<div class="hc-focus-item">' +
            '<span class="hc-f-n">' + esc(r.rank) + '</span>' +
            '<span class="hc-q">' + esc(r.headline) + '</span>' +
          '</div>'
        );
      }).join('');
    } else {
      focusHtml =
        '<div class="hc-focus-item">' +
          '<span class="hc-q">' + esc(today.today_verdict || '') + '</span>' +
        '</div>';
    }

    el.innerHTML =
      '<div class="hc-today">' +
        '<div class="hc-today-head">' +
          '<h2 class="hc-today-t">TODAY · COACH</h2>' +
          (updated ? '<span class="hc-today-d">' + esc(updated) + '</span>' : '') +
        '</div>' +
        '<div class="hc-today-body">' +
          _sessionBlock(today) +
          '<div class="hc-coach-line">' +
            focusHtml +
            '<button type="button" class="hc-a" data-hc-open-brief>why? → full brief</button>' +
          '</div>' +
          _ctaBlock(ctaMode) +
        '</div>' +
        (chipsHtml ? '<div class="hc-today-chips">' + chipsHtml + '</div>' : '') +
      '</div>';

    el.querySelector('[data-hc-open-brief]') &&
      el.querySelector('[data-hc-open-brief]').addEventListener('click', function () {
        if (window.CoachBrief && typeof window.CoachBrief.open === 'function') {
          window.CoachBrief.open(brief);
        }
      });
    el.querySelector('[data-hc-log-metrics]') &&
      el.querySelector('[data-hc-log-metrics]').addEventListener('click', function () {
        var row = document.getElementById('row-log');
        if (row) row.hidden = false;
        var btn = document.getElementById('lts-cta-btn') || document.querySelector('.lts-cta-btn');
        if (btn) btn.click();
        else if (row) row.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    el.querySelector('[data-hc-log-niggle]') &&
      el.querySelector('[data-hc-log-niggle]').addEventListener('click', function () {
        if (typeof window.openInjuryLog === 'function') window.openInjuryLog();
        else window.location.href = '/log#injury';
      });
  }

  window.HomeCoachStrip = { render: render };
})();
