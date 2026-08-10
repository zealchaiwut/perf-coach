/**
 * Shared "Next up" / "Today's workout" hero card.
 *
 * Extracted from training-plan.js's #plan-next-up renderer so the same
 * component can be reused on Home (#home-next-up, home revamp v2). Ports
 * the Plan tab's pick/format helpers as local copies rather than exporting
 * them from training-plan.js, so this file has no dependency on that page's
 * closure and can render standalone anywhere AppCommon + this script are
 * loaded.
 *
 * window.NextUpCard.render(host, opts):
 *   opts.days            — /api/planned-sessions `days` array (REQUIRED)
 *   opts.weekTargetTss    — optional week TSS target, for "% of week"
 *   opts.onOpen(id)       — "Open session" click
 *   opts.onMarkDone(id)   — "Mark done" click
 *   opts.onSuggest()      — optional "Suggest sessions" click (empty state)
 *   opts.title            — header label, default 'Next up'
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  var DOW = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _parseISO(s) {
    var p = String(s).split('-');
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  // ── Ported from training-plan.js (kept in sync by hand; see file header) ──

  function _famClass(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift';
  }

  function _sessionTypeChipLabel(p) {
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength') return 'LIFT';
    if (t === 'plyo') return 'PLYO';
    if (t === 'stretch') return 'STRETCH';
    if (t === 'rest') return 'REST';
    return 'RUN';
  }

  function _sessionDisplayName(p) {
    var n = (p && p.name) ? String(p.name).trim() : '';
    if (n) return n;
    if (p && p.actual && p.actual.name) {
      n = String(p.actual.name).trim();
      if (n) return n;
    }
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength' || t === 'plyo') return 'Strength session';
    if (t === 'stretch') return 'Stretch session';
    if (t === 'rest') return 'Rest day';
    return 'Easy run';
  }

  // Real logged TSS (p.actual.tss) when done/matched; the server-computed
  // estimate (p.estimated_tss, "~") otherwise. Never fabricates a number.
  function _sessionTss(p) {
    if (p && p.actual && p.actual.tss != null) return { value: p.actual.tss, estimated: false };
    if (p && p.estimated_tss != null && isFinite(Number(p.estimated_tss))) {
      return { value: Number(p.estimated_tss), estimated: true };
    }
    return null;
  }

  function _plannedTargetTss(p) {
    if (!p) return null;
    if (p.planned_tss != null && isFinite(Number(p.planned_tss))) return Number(p.planned_tss);
    var s = p.structure || {};
    if (s.target_tss != null && isFinite(Number(s.target_tss))) return Number(s.target_tss);
    if (p.estimated_tss != null && isFinite(Number(p.estimated_tss))) return Number(p.estimated_tss);
    return null;
  }

  function _plannedDurationMin(p) {
    var s = (p && p.structure) || {};
    if (s.duration_minutes != null && isFinite(Number(s.duration_minutes))) {
      return Math.round(Number(s.duration_minutes));
    }
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0;
        var r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      return tot || null;
    }
    return null;
  }

  // Strength sessions count exercises rather than a duration.
  function _plannedExerciseCount(p) {
    var s = (p && p.structure) || {};
    if (Array.isArray(s.exercises) && s.exercises.length) return s.exercises.length;
    return null;
  }

  function _plannedMeta(p) {
    var s = p.structure || {};
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0, r = Math.max(1, Number(b.repeat) || 1);
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

  function _sessionCue(p) {
    if (!p) return null;
    if (p.notes && String(p.notes).trim()) {
      var n = String(p.notes).trim().replace(/\s+/g, ' ');
      if (n.length > 140) n = n.slice(0, 137) + '…';
      return n;
    }
    var s = p.structure || {};
    if (s.cue && String(s.cue).trim()) return String(s.cue).trim();
    if (s.key_instruction && String(s.key_instruction).trim()) return String(s.key_instruction).trim();
    if (Array.isArray(s.blocks)) {
      for (var i = 0; i < s.blocks.length; i++) {
        var b = s.blocks[i];
        if (b && b.notes && String(b.notes).trim()) return String(b.notes).trim();
        if (b && b.cue && String(b.cue).trim()) return String(b.cue).trim();
      }
    }
    return null;
  }

  function _isOpenPlanned(p) {
    if (!p || p.session_type === 'rest') return false;
    var s = p.status || 'planned';
    if (s === 'done_auto' || s === 'done_manual') return false;
    if (s === 'missed' || s === 'missed_auto' || s === 'missed_manual') return false;
    return true;
  }

  function _pickNextUp(days) {
    var today = _todayISO();
    var best = null;
    (days || []).forEach(function (day) {
      if (day.date < today) return;
      (day.planned || []).forEach(function (p) {
        if (!_isOpenPlanned(p)) return;
        if (!best || day.date < best.day.date) best = { p: p, day: day };
      });
    });
    return best;
  }

  function _fmtHeroDate(iso) {
    var d = _parseISO(iso);
    var dow = DOW[(d.getDay() + 6) % 7];
    var short = dow.charAt(0) + dow.slice(1).toLowerCase() + ' ' + d.getDate() + ' ' + MON[d.getMonth()];
    if (iso === _todayISO()) return short + ' · today';
    return short;
  }

  function _fmtThenDate(iso) {
    var d = _parseISO(iso);
    var dow = DOW[(d.getDay() + 6) % 7];
    return dow.charAt(0) + dow.slice(1).toLowerCase() + ' ' + d.getDate();
  }

  function _pickThenAfter(days, current) {
    if (!current) return null;
    var afterDate = current.day.date;
    var afterId = current.p.id;
    var passed = false;
    for (var i = 0; i < (days || []).length; i++) {
      var day = days[i];
      if (day.date < afterDate) continue;
      var planned = day.planned || [];
      for (var j = 0; j < planned.length; j++) {
        var p = planned[j];
        if (!passed) {
          if (p.id === afterId) { passed = true; continue; }
          if (day.date === afterDate) continue;
        }
        if (_isOpenPlanned(p)) {
          return {
            fam: _famClass(p.session_type),
            chip: _sessionTypeChipLabel(p),
            text: 'then ' + _fmtThenDate(day.date) + ' · ' + _sessionDisplayName(p)
          };
        }
      }
      if (passed && day.date > afterDate && !planned.length) {
        return { fam: null, chip: null, text: 'then ' + _fmtThenDate(day.date) + ' · rest day — nothing scheduled' };
      }
    }
    return null;
  }

  // ── Self-contained styling (matches training-plan.js's .pl-hero block, so
  // the component looks identical wherever it's mounted) ──────────────────

  var _STYLE_ID = 'next-up-card-styles';
  var _CSS = [
    '.pl-hero{background:#fff;border-radius:14px;border:1px solid var(--border);overflow:hidden;box-shadow:0 2px 8px rgba(20,28,70,.07);}',
    '.pl-hero-top{display:flex;align-items:center;gap:9px;padding:9px 18px;background:linear-gradient(90deg,#eef2ff,#f7f9ff);border-bottom:1px solid #e2e8fd;}',
    '.pl-hero-k{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#3b4bb8;}',
    '.pl-hero-d{font-family:var(--mono);font-size:9.5px;color:#7b87c9;margin-left:auto;}',
    '.pl-hero-body{display:flex;align-items:center;gap:20px;padding:15px 18px;flex-wrap:wrap;}',
    '.pl-hero-left{flex:1;min-width:250px;}',
    '.pl-hero-name{font-size:19px;font-weight:700;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-name{font-size:17px;}}',
    '.pl-hero-meta{font-family:var(--mono);font-size:11px;color:var(--text-sub);margin-top:6px;}',
    '.pl-hero-cue{display:inline-flex;align-items:center;gap:7px;margin-top:9px;background:#f7f8fe;border:1px solid #dfe3fb;border-radius:9px;padding:7px 11px;font-size:12.5px;color:#3b4bb8;}',
    '.pl-hero-stats{display:flex;gap:9px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-stats{display:grid;grid-template-columns:repeat(3,1fr);width:100%;}}',
    '.pl-hero-stat{background:var(--tile);border-radius:10px;padding:9px 13px;min-width:78px;text-align:center;}',
    '.pl-hero-stat .k{font-family:var(--mono);font-size:8px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-sub);margin-bottom:4px;}',
    '.pl-hero-stat .v{font-family:var(--mono);font-size:17px;font-weight:700;}',
    '.pl-hero-acts{display:flex;gap:8px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-acts{width:100%;}.pl-hero-acts .pl-hero-btn{flex:1;}}',
    '.pl-hero-btn{border:none;border-radius:10px;padding:11px 18px;font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;background:var(--primary);color:#fff;}',
    '.pl-hero-btn.ghost{background:#fff;color:var(--text-sub);border:1px solid var(--border);font-weight:600;}',
    '.pl-hero-foot{display:flex;align-items:center;gap:9px;padding:9px 18px;background:var(--tile);border-top:1px solid var(--border);}',
    '.pl-hero-then{font-family:var(--mono);font-size:10px;color:var(--text-sub);}',
    '.pl-hero-empty-msg{font-size:14px;color:var(--text-sub);margin-bottom:10px;}',
    // Standalone (not-nested-under-.plan-panel) variant of the type chip, so
    // this component renders correctly outside the Plan tab too.
    '.pl-stypetag{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.04em;padding:3px 8px;border-radius:6px;background:var(--tile);color:var(--text-sub);}',
    '.pl-stypetag.run{background:#e4e8fd;color:#3b4bb8;}',
    '.pl-stypetag.lift{background:#efe9fd;color:#6d3fd1;}',
    '.pl-stypetag.plyo{background:#fef3c7;color:#92400e;}',
    '.pl-stypetag.stretch{background:#d4f0e2;color:#1e6438;}'
  ].join('');

  function _injectStyles() {
    if (document.getElementById(_STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = _STYLE_ID;
    style.textContent = _CSS;
    document.head.appendChild(style);
  }

  function render(host, opts) {
    if (!host) return;
    _injectStyles();
    opts = opts || {};
    var days = opts.days || [];
    var title = opts.title || 'Next up';
    var weekTargetTss = opts.weekTargetTss;

    var next = _pickNextUp(days);
    if (!next) {
      host.innerHTML =
        '<div class="pl-hero pl-hero--empty">' +
          '<div class="pl-hero-top"><span class="pl-hero-k">' + esc(title) + '</span></div>' +
          '<div class="pl-hero-body">' +
            '<div class="pl-hero-empty-msg">Nothing scheduled from today forward.</div>' +
            (opts.onSuggest ? '<button type="button" class="pl-hero-btn" id="nuc-suggest">Suggest sessions</button>' : '') +
          '</div>' +
        '</div>';
      var sug = host.querySelector('#nuc-suggest');
      if (sug) sug.addEventListener('click', function () { opts.onSuggest(); });
      return;
    }

    var p = next.p;
    var fam = _famClass(p.session_type);
    var cue = _sessionCue(p);
    var isStrength = ((p.session_type || '').toLowerCase() === 'strength');
    var exCount = _plannedExerciseCount(p);
    var dur = _plannedDurationMin(p);
    var tss = _sessionTss(p) || (function () {
      var pt = _plannedTargetTss(p);
      return pt != null ? { value: pt, estimated: true } : null;
    })();
    var weekT = weekTargetTss != null ? Number(weekTargetTss) : null;
    var share = (tss && weekT) ? Math.round((tss.value / weekT) * 100) + '%' : '—';

    var metaBits = [];
    if (isStrength && exCount != null) metaBits.push(exCount + ' exercise' + (exCount === 1 ? '' : 's'));
    else if (dur != null) metaBits.push(dur + ' min');
    var soft = _plannedMeta(p);
    if (soft && metaBits.indexOf(soft) === -1) metaBits.push(soft);
    metaBits.push('planned');

    var then = _pickThenAfter(days, next);
    var cueHtml = cue ? '<div class="pl-hero-cue"><span aria-hidden="true">💡</span><span>' + esc(cue) + '</span></div>' : '';
    var thenHtml = then
      ? '<div class="pl-hero-foot">' +
          (then.chip ? '<span class="pl-stypetag ' + (then.fam || '') + '" style="opacity:.55">' + esc(then.chip) + '</span>' : '') +
          '<span class="pl-hero-then">' + esc(then.text) + '</span></div>'
      : '';

    var primaryStatLabel = (isStrength && exCount != null) ? 'Exercises' : 'Duration';
    var primaryStatVal = (isStrength && exCount != null) ? exCount : (dur != null ? dur : '—');

    host.innerHTML =
      '<div class="pl-hero">' +
        '<div class="pl-hero-top"><span class="pl-hero-k">' + esc(title) + '</span>' +
          '<span class="pl-hero-d">' + esc(_fmtHeroDate(next.day.date)) + '</span></div>' +
        '<div class="pl-hero-body">' +
          '<div class="pl-hero-left">' +
            '<div class="pl-hero-name"><span class="pl-stypetag ' + fam + '">' + esc(_sessionTypeChipLabel(p)) + '</span> ' +
              esc(_sessionDisplayName(p)) + '</div>' +
            '<div class="pl-hero-meta">' + esc(metaBits.join(' · ')) + '</div>' +
            cueHtml +
          '</div>' +
          '<div class="pl-hero-stats">' +
            '<div class="pl-hero-stat"><div class="k">' + esc(primaryStatLabel) + '</div><div class="v">' + esc(primaryStatVal) + '</div></div>' +
            '<div class="pl-hero-stat"><div class="k">TSS</div><div class="v">' +
              (tss ? ((tss.estimated ? '~' : '') + Math.round(tss.value)) : '—') + '</div></div>' +
            '<div class="pl-hero-stat"><div class="k">Of week</div><div class="v">' + esc(share) + '</div></div>' +
          '</div>' +
          '<div class="pl-hero-acts">' +
            '<button type="button" class="pl-hero-btn" id="nuc-open">Open session</button>' +
            '<button type="button" class="pl-hero-btn ghost" id="nuc-done">Mark done</button>' +
          '</div>' +
        '</div>' + thenHtml +
      '</div>';

    var openBtn = host.querySelector('#nuc-open');
    if (openBtn) openBtn.addEventListener('click', function () { if (opts.onOpen) opts.onOpen(p.id); });
    var doneBtn = host.querySelector('#nuc-done');
    if (doneBtn) doneBtn.addEventListener('click', function () { if (opts.onMarkDone) opts.onMarkDone(p.id); });
  }

  window.NextUpCard = { render: render };
})();
