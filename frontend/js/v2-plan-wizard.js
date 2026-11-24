(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  var STEPS = [
    { id: 1, short: 'Race', title: 'Which race is this block for?', next: 'Next: shape \u203a' },
    { id: 2, short: 'Shape', title: 'How should the block run?', next: 'Next: load \u203a' },
    { id: 3, short: 'Load', title: 'How hard should it build?', next: 'Next: your week \u203a' },
    { id: 4, short: 'Your week', title: 'When do you rest?', next: 'Review \u203a' },
    { id: 5, short: 'Review', title: '', next: 'Create plan' },
  ];
  var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var DIST_PRESETS = [
    { label: '5K', km: 5 },
    { label: '10K', km: 10 },
    { label: 'Half', km: 21.0975 },
    { label: 'Marathon', km: 42.195 },
  ];
  var TAPER_CHIPS = [
    { weeks: 1, label: '1 week \u00b7 70%' },
    { weeks: 2, label: '2 weeks \u00b7 75% \u2192 55%' },
    { weeks: 3, label: '3 weeks \u00b7 85% \u2192 70% \u2192 50%' },
  ];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  var st = null;
  var opener = null;

  function isoParts(iso) {
    var p = String(iso || '').slice(0, 10).split('-');
    return { y: parseInt(p[0], 10), m: parseInt(p[1], 10), d: parseInt(p[2], 10) };
  }
  function mondayISO(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso;
    var d = new Date(Date.UTC(p.y, p.m - 1, p.d));
    var day = d.getUTCDay();
    var diff = day === 0 ? -6 : 1 - day;
    d.setUTCDate(d.getUTCDate() + diff);
    return d.toISOString().slice(0, 10);
  }
  function addDaysISO(iso, n) {
    var p = isoParts(iso);
    var d = new Date(Date.UTC(p.y, p.m - 1, p.d));
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function weeksToRace(startISO, raceISO) {
    if (!startISO || !raceISO) return 0;
    var a = Date.parse(mondayISO(startISO) + 'T00:00:00Z');
    var b = Date.parse(mondayISO(raceISO) + 'T00:00:00Z');
    if (isNaN(a) || isNaN(b) || b < a) return 0;
    return Math.floor((b - a) / 86400000 / 7) + 1;
  }
  function fmtDayMon(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso || '';
    return p.d + ' ' + MONTHS[p.m - 1];
  }
  function fmtCompact(iso) {
    var p = isoParts(iso);
    if (!p.m) return '';
    return p.d + MONTHS[p.m - 1].charAt(0);
  }
  function fmtLong(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso || '';
    var d = new Date(Date.UTC(p.y, p.m - 1, p.d));
    var wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getUTCDay()];
    return wd + ' ' + p.d + ' ' + MONTHS[p.m - 1] + ' ' + p.y;
  }
  function fmtHMS(sec) {
    if (sec == null) return '';
    var s = Math.abs(Math.round(sec));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h + ':' + String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0');
  }
  function parseHMS(text) {
    var t = String(text || '').trim();
    if (!t) return null;
    var parts = t.split(':');
    if (parts.length < 2 || parts.length > 3) return NaN;
    var nums = parts.map(function (p) { return /^\d+$/.test(p) ? parseInt(p, 10) : NaN; });
    if (nums.some(isNaN)) return NaN;
    if (nums.length === 2) return nums[0] * 60 + nums[1];
    return nums[0] * 3600 + nums[1] * 60 + nums[2];
  }
  function paceStr(sec, km) {
    if (!sec || !(km > 0)) return '';
    var p = Math.round(sec / km);
    var m = Math.floor(p / 60), r = p % 60;
    return m + ':' + String(r).padStart(2, '0') + ' /km';
  }
  function distChipOn(km, preset) {
    return Math.abs((km || 0) - preset.km) < 0.2;
  }
  function restList() {
    return (st.restDays || []).slice().sort(function (a, b) { return a - b; });
  }
  function restNames() {
    var names = restList().map(function (d) { return DAYS[d]; });
    if (!names.length) return 'no rest days';
    if (names.length === 1) return names[0];
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }
  function taperPctLabel(factors) {
    return (factors || []).map(function (x) { return Math.round(Number(x) * 100) + '%'; }).join(' \u2192 ');
  }
  function detailMsg(data, status) {
    var d = data && data.detail;
    if (!d) return 'HTTP ' + status;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]) return d[0].msg || d[0].message || d[0].error || JSON.stringify(d[0]);
    return d.message || d.error || JSON.stringify(d);
  }
  function api(method, url, body) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (text) {
        var data = {};
        if (text) {
          try { data = JSON.parse(text); } catch (e) { data = {}; }
        }
        if (!r.ok) throw new Error(detailMsg(data, r.status));
        return data;
      });
    });
  }
  function toast(msg) {
    if (window.RevampUI && window.RevampUI.showToast) window.RevampUI.showToast(msg);
    else {
      var el = document.getElementById('rv-toast');
      if (!el) return;
      el.textContent = msg;
      el.classList.add('is-visible');
      setTimeout(function () { el.classList.remove('is-visible'); }, 2800);
    }
  }

  function raceDate() {
    return st.race && st.race.race_date;
  }
  function weeksAvailable() {
    return weeksToRace(st.blockStart, raceDate());
  }

  function rootEl() {
    var el = document.getElementById('v2-plan-wiz-root');
    if (!el) {
      el = document.createElement('div');
      el.id = 'v2-plan-wiz-root';
      document.body.appendChild(el);
    }
    return el;
  }

  function defaultState(settings, startStep) {
    var defs = settings.defaults || {};
    var aRaces = (settings.upcoming_races || []).filter(function (r) { return r.priority === 'A' && !r.too_short; });
    var pick = aRaces[0] || null;
    var rest = (settings.rest_days && settings.rest_days.length) ? settings.rest_days.slice() : [];
    var ramp = settings.ramp_pct != null ? settings.ramp_pct : 0.05;
    if (ramp !== 0.03 && ramp !== 0.05 && ramp !== 0.07) ramp = 0.05;
    var taperN = (settings.taper_factors && settings.taper_factors.length) || 2;
    if (taperN < 1 || taperN > 3) taperN = 2;
    var weeks = pick ? weeksToRace(settings.next_monday, pick.race_date) : 0;
    var shape = weeks && weeks < 8 ? 'short' : 'standard';
    return {
      settings: settings,
      step: startStep || 1,
      race: pick,
      newName: '',
      newDate: '',
      newDist: '',
      newGoal: '',
      blockStart: settings.next_monday,
      shape: shape,
      taperWeeks: taperN,
      buildWeeks: settings.build_weeks || defs.build_weeks || 8,
      peakHoldWeeks: shape === 'short' ? 0 : 2,
      recoverWeeks: settings.recover_weeks != null ? settings.recover_weeks : (defs.recover_weeks || 1),
      rebuildWeeks: settings.rebuild_weeks != null ? settings.rebuild_weeks : (defs.rebuild_weeks || 4),
      afterOpen: false,
      rampPct: ramp,
      peakTss: null,
      peakOpen: false,
      restDays: rest,
      maxConsecutive: settings.max_consecutive_days || 3,
      fit: null,
      preview: null,
      weekCheck: null,
      layoutError: '',
      error: '',
      busy: false,
    };
  }

  function draftPayload() {
    var d = {
      a_race_id: st.race && st.race.id ? st.race.id : null,
      race_date: raceDate() || undefined,
      distance_km: st.race && st.race.distance_km != null ? st.race.distance_km : undefined,
      block_start: st.blockStart,
      shape: st.shape,
      weeks_available: weeksAvailable() || undefined,
      taper_weeks: st.taperWeeks,
      ramp_pct: st.rampPct,
      build_weeks: st.buildWeeks,
      peak_hold_weeks: st.peakHoldWeeks,
      recover_weeks: st.recoverWeeks,
      rebuild_weeks: st.rebuildWeeks,
      rest_days: restList(),
      max_consecutive_days: st.maxConsecutive,
      race_week_factor: (st.settings.defaults && st.settings.defaults.race_week_factor) || 0.4,
    };
    if (st.peakTss != null && st.peakTss !== '') d.peak_tss = Number(st.peakTss);
    if (st.fit && st.fit.taper_factors) d.taper_factors = st.fit.taper_factors;
    return d;
  }

  function refit() {
    var weeks = weeksAvailable();
    if (!weeks) {
      st.fit = null;
      st.layoutError = '';
      return Promise.resolve();
    }
    var body = {
      weeks_available: weeks,
      shape: st.shape,
      taper_weeks: st.taperWeeks,
    };
    if (st.shape === 'custom') {
      body.build_weeks = st.buildWeeks;
      body.peak_hold_weeks = st.peakHoldWeeks;
    }
    return api('POST', '/api/plan/revamp-settings/fit', body).then(function (fit) {
      st.fit = fit;
      st.buildWeeks = fit.build_weeks;
      st.peakHoldWeeks = fit.peak_hold_weeks;
      st.taperWeeks = fit.taper_weeks;
      st.layoutError = '';
    }).catch(function (e) {
      st.layoutError = e.message || 'Could not fit phases';
      st.fit = null;
    });
  }

  function refreshPreview() {
    if (!raceDate() || !st.blockStart) {
      st.preview = null;
      return Promise.resolve();
    }
    return api('POST', '/api/plan/revamp-settings/preview', draftPayload()).then(function (p) {
      st.preview = p;
      if (p.week_check) st.weekCheck = p.week_check;
      if (!p.allowed && p.layout_error) st.layoutError = p.layout_error.message || '';
    }).catch(function (e) {
      st.preview = { allowed: false, layout_error: { message: e.message } };
    });
  }

  function refreshWeekCheck() {
    return api('POST', '/api/plan/revamp-settings/week-check', {
      rest_days: restList(),
      max_consecutive_days: st.maxConsecutive,
    }).then(function (c) { st.weekCheck = c; });
  }

  function onKey(ev) {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      ev.stopPropagation();
      close(true);
    }
  }

  function close(discard) {
    document.removeEventListener('keydown', onKey, true);
    document.body.style.overflow = '';
    var root = document.getElementById('v2-plan-wiz-root');
    if (root) root.innerHTML = '';
    if (discard) st = null;
    if (opener && typeof opener.focus === 'function') {
      try { opener.focus(); } catch (e) {}
    }
    opener = null;
    if (/\bsetup=1\b/.test(location.search)) {
      try {
        var u = new URL(location.href);
        u.searchParams.delete('setup');
        history.replaceState({}, '', u.pathname + u.search + u.hash);
      } catch (e) {}
    }
  }

  function stepMeta(i) {
    var s = STEPS[i - 1];
    var race = st.race || {};
    var kicker = 'Set up a training block';
    var title = s.title;
    if (i === 2) kicker = (race.name || 'Race') + ' \u00b7 ' + fmtDayMon(race.race_date);
    if (i === 3) kicker = (race.name || 'Race') + ' \u00b7 ' + weeksAvailable() + ' weeks \u00b7 ' + (st.shape.charAt(0).toUpperCase() + st.shape.slice(1));
    if (i === 4) {
      var peak = st.preview && st.preview.peak_tss;
      kicker = (race.name || 'Race') + (peak ? ' \u00b7 peak ' + Math.round(peak) + ' TSS' : '');
    }
    if (i === 5) {
      kicker = 'Review';
      title = (race.name || 'Race') + ' block \u00b7 ' + weeksAvailable() + ' weeks';
    }
    return { kicker: kicker, title: title, next: s.next };
  }

  function progressHtml() {
    return '<div class="rv-wiz-steps" role="list">' + STEPS.map(function (s) {
      var cls = 'rv-wiz-step';
      var label = s.id + ' ' + s.short;
      if (st.step === s.id) { cls += ' is-on'; }
      else if (st.step > s.id) { cls += ' is-done'; label = '\u2713 ' + s.short; }
      var btn = st.step > s.id;
      return '<button type="button" class="' + cls + '" role="listitem"' +
        (btn ? ' data-jump="' + s.id + '"' : ' tabindex="-1"') +
        '><span class="rv-wiz-step__bar"></span><span class="rv-wiz-step__lbl">' + esc(label) + '</span></button>';
    }).join('') + '</div>';
  }

  function ribbonHtml(weeks, dashed) {
    var n = weeks && weeks.length ? weeks.length : weeksAvailable();
    if (!n) return '';
    var cols = 'style="grid-template-columns:repeat(' + n + ',minmax(0,1fr))"';
    var spans = [];
    if (weeks && weeks.length) {
      var i = 0;
      while (i < weeks.length) {
        var ph = weeks[i].phase || 'build';
        var j = i + 1;
        while (j < weeks.length && (weeks[j].phase || '') === ph) j += 1;
        var name = ph === 'peak_hold' ? 'PEAK' : ph === 'race_week' ? 'RACE' : ph.toUpperCase();
        var mod = ph === 'peak_hold' ? 'peak' : ph === 'race_week' ? 'race' : ph === 'taper' ? 'taper' : 'build';
        var extra = (ph === 'build' || ph === 'peak_hold' || ph === 'taper') ? ' \u00b7 ' + (j - i) + (ph === 'build' ? ' WK' : '') : '';
        spans.push('<div class="rv-wiz-ph rv-wiz-ph--' + mod + '" style="grid-column:span ' + (j - i) + '">' + esc(name + extra) + '</div>');
        i = j;
      }
    } else {
      var b = st.buildWeeks, p = st.peakHoldWeeks, t = st.taperWeeks;
      if (b) spans.push('<div class="rv-wiz-ph rv-wiz-ph--build" style="grid-column:span ' + b + '">BUILD \u00b7 ' + b + ' WK</div>');
      if (p) spans.push('<div class="rv-wiz-ph rv-wiz-ph--peak" style="grid-column:span ' + p + '">PEAK \u00b7 ' + p + '</div>');
      if (t) spans.push('<div class="rv-wiz-ph rv-wiz-ph--taper" style="grid-column:span ' + t + '">TAPER \u00b7 ' + t + '</div>');
      spans.push('<div class="rv-wiz-ph rv-wiz-ph--race">RACE</div>');
    }
    var labels = [];
    var start = st.blockStart;
    for (var w = 0; w < n; w++) {
      var iso = weeks && weeks[w] ? weeks[w].week_start : addDaysISO(start, w * 7);
      labels.push('<span>' + esc(fmtCompact(iso)) + '</span>');
    }
    return '<div class="rv-wiz-rib" ' + cols + '>' + spans.join('') + '</div>' +
      (dashed ? '' : '<div class="rv-wiz-wk" ' + cols + '>' + labels.join('') + '</div>');
  }

  function barsHtml(weeks, dashed) {
    weeks = weeks || [];
    if (!weeks.length) return '';
    var max = 1;
    weeks.forEach(function (w) { if (w.target_tss > max) max = w.target_tss; });
    var cols = 'style="grid-template-columns:repeat(' + weeks.length + ',minmax(0,1fr))"';
    var bars = weeks.map(function (w, idx) {
      var h = Math.max(8, Math.round((w.target_tss / max) * (dashed ? 104 : 114)));
      var ph = w.phase || 'build';
      var mod = ph === 'peak_hold' ? 'peak' : ph === 'race_week' ? 'race' : ph === 'taper' ? 'taper' : 'build';
      var over = w.over_ceiling ? ' is-over' : '';
      var dash = dashed ? ' rv-wiz-bar--dashed' : '';
      if (ph === 'race_week' && !dashed) {
        var lime = Math.round(h * 0.45);
        var rest = h - lime;
        return '<div class="rv-wiz-bar-stack"><div class="rv-wiz-bar rv-wiz-bar--lime" style="height:' + lime + 'px"></div>' +
          '<div class="rv-wiz-bar rv-wiz-bar--taper' + over + '" style="height:' + rest + 'px"></div></div>';
      }
      return '<div class="rv-wiz-bar rv-wiz-bar--' + mod + dash + over + '" style="height:' + h + 'px"></div>';
    }).join('');
    var firstPeak = -1, lastPeak = -1, firstTaper = -1;
    weeks.forEach(function (w, i) {
      if (w.phase === 'peak_hold') { if (firstPeak < 0) firstPeak = i; lastPeak = i; }
      if (w.phase === 'taper' && firstTaper < 0) firstTaper = i;
    });
    var lbls = weeks.map(function (w, i) {
      if (i === 0) return '<span>' + Math.round(w.target_tss) + '</span>';
      if (i === firstPeak || i === lastPeak) return '<span>' + Math.round(w.target_tss) + '</span>';
      if (w.phase === 'taper') return '<span>' + Math.round(w.target_tss) + '</span>';
      if (w.phase === 'race_week') return '<span>race</span>';
      return '<span></span>';
    }).join('');
    return '<div class="rv-wiz-bars" ' + cols + ' role="img" aria-label="Weekly targets">' + bars + '</div>' +
      '<div class="rv-wiz-wk" ' + cols + '>' + lbls + '</div>';
  }

  function guardHtml(weeks) {
    weeks = weeks || [];
    var hit = weeks.findIndex(function (w) { return w.over_ceiling; });
    if (hit < 0) return '<span class="rv-wiz-guard is-ok">Under the guardrail every week</span>';
    return '<span class="rv-wiz-guard is-bad">Week ' + (hit + 1) + ' crosses the guardrail</span>';
  }

  function step1Body() {
    var races = (st.settings.upcoming_races || []);
    var cards = races.length ? races.map(function (r) {
      var on = st.race && st.race.id === r.id && !st.newName;
      var dis = r.too_short;
      var tag = (r.priority || '') + ' \u00b7 ' + fmtDayMon(r.race_date).toUpperCase();
      return '<button type="button" class="rv-wiz-card' + (on ? ' is-on' : '') + (dis ? ' is-disabled' : '') + '"' +
        (dis ? ' aria-disabled="true"' : '') +
        ' data-pick-race="' + esc(r.id) + '"' +
        '><span class="rv-wiz-card__top">' + esc(r.name) + '<span class="rv-wiz-tag">' + esc(tag) + '</span></span>' +
        '<span class="rv-wiz-card__blurb">' + esc(dis ? (r.disabled_reason || 'Too short for a build block.') : (r.weeks_away + ' weeks away')) + '</span></button>';
    }).join('') : '<p class="rv-subtitle">No upcoming races yet.</p>';
    var km = parseFloat(st.newDist, 10);
    var chips = DIST_PRESETS.map(function (p) {
      return '<button type="button" class="rv-race-modal__chip' + (distChipOn(km, p) ? ' is-on' : '') + '" data-dist-chip="' + p.km + '">' + esc(p.label) + '</button>';
    }).join('');
    var goalSec = parseHMS(st.newGoal);
    var pace = (!isNaN(goalSec) && goalSec) ? paceStr(goalSec, km) : '';
    return '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Your upcoming races</span>' +
      '<div style="display:flex;flex-direction:column;gap:8px">' + cards + '</div></div>' +
      '<div class="rv-wiz-divider">or add the race</div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-name">Race name</label>' +
      '<input class="rv-race-modal__input" id="wiz-name" type="text" value="' + esc(st.newName) + '" autocomplete="off"></div>' +
      '<div class="rv-race-modal__pair">' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-date">Date</label>' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="wiz-date" type="date" value="' + esc(st.newDate) + '"></div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-dist">Distance <span class="rv-race-modal__hint">km</span></label>' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="wiz-dist" type="number" min="0.1" step="0.0001" value="' + esc(st.newDist) + '"></div></div>' +
      '<div class="rv-race-modal__chips">' + chips + '</div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-goal">Goal time <span class="rv-race-modal__hint">optional \u00b7 h:mm:ss</span></label>' +
      '<div class="rv-race-modal__goal-row">' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="wiz-goal" type="text" inputmode="numeric" placeholder="4:30:00" value="' + esc(st.newGoal) + '">' +
      '<span class="rv-race-modal__pace" id="wiz-pace"' + (pace ? '' : ' hidden') + '>' + (pace ? '= <b>' + esc(pace) + '</b>' : '') + '</span></div></div>' +
      '<span class="rv-subtitle" style="font-size:12.5px">Saved as your A race, role A race. Its result will recalibrate the projection.</span>';
  }

  function step2Body() {
    var weeks = weeksAvailable();
    var shapes = [
      { id: 'standard', title: 'Standard', blurb: 'Build, 2-week peak hold, 2-week taper.' },
      { id: 'short', title: 'Short', blurb: 'Build then taper. Best under 8 weeks.' },
      { id: 'custom', title: 'Custom', blurb: 'Set the weeks per phase yourself.' },
    ];
    var cards = shapes.map(function (s) {
      var on = st.shape === s.id;
      return '<button type="button" role="radio" class="rv-wiz-card' + (on ? ' is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-shape="' + s.id + '">' +
        '<span class="rv-wiz-card__top">' + esc(s.title) + '</span><span class="rv-wiz-card__blurb">' + esc(s.blurb) + '</span></button>';
    }).join('');
    var custom = '';
    if (st.shape === 'custom') {
      custom = '<div class="rv-wiz-steppers">' +
        stepper('Build', 'buildWeeks', st.buildWeeks, 3, 30) +
        stepper('Peak hold', 'peakHoldWeeks', st.peakHoldWeeks, 0, 8) +
        stepper('Taper', 'taperWeeks', st.taperWeeks, 1, 3) +
        '</div>';
    }
    var after = st.afterOpen
      ? '<div class="rv-wiz-steppers" style="margin-top:8px">' +
        stepper('Recover', 'recoverWeeks', st.recoverWeeks, 0, 4) +
        stepper('Rebuild', 'rebuildWeeks', st.rebuildWeeks, 0, 12) + '</div>'
      : '';
    var err = st.layoutError ? '<p class="rv-wiz-err" role="alert">' + esc(st.layoutError) + '</p>' : '';
    return '<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:end">' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-start">Block starts <span class="rv-race-modal__hint">a Monday</span></label>' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="wiz-start" type="date" value="' + esc(st.blockStart || '') + '"></div>' +
      '<div class="rv-wiz-tile"><span class="rv-subtitle" style="font-size:12px">Time to race day</span>' +
      '<span class="rv-wiz-tile__val">' + weeks + ' weeks</span></div></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="wiz-shape-lbl">Shape</span>' +
      '<div class="rv-wiz-shapes" role="radiogroup" aria-labelledby="wiz-shape-lbl">' + cards + '</div></div>' +
      custom +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">Your ' + weeks + ' weeks</span>' +
      ribbonHtml(st.preview && st.preview.weeks) +
      '<span class="rv-subtitle" style="font-size:12px">The split always fills the weeks you have; change the start date and it re-fits.</span></div>' +
      err +
      '<button type="button" class="rv-wiz-card" data-toggle-after style="flex-direction:row;justify-content:space-between;align-items:center">' +
      '<span class="rv-wiz-card__top" style="font-size:13.5px">After the race</span>' +
      '<span class="rv-wiz-card__blurb">Recover ' + st.recoverWeeks + ' wk \u00b7 rebuild ' + st.rebuildWeeks + ' wk \u203a</span></button>' +
      after;
  }

  function stepper(label, key, val, min, max) {
    return '<div class="rv-race-modal__field"><span class="rv-race-modal__label">' + esc(label) + '</span>' +
      '<div class="rv-wiz-stepper">' +
      '<button type="button" class="rv-wiz-sq" data-step="' + key + '" data-dir="-1" aria-label="Fewer" ' + (val <= min ? 'disabled' : '') + '>\u2212</button>' +
      '<span class="rv-wiz-stepper__val">' + val + '</span>' +
      '<button type="button" class="rv-wiz-sq" data-step="' + key + '" data-dir="1" aria-label="More" ' + (val >= max ? 'disabled' : '') + '>+</button>' +
      '</div></div>';
  }

  function step3Body() {
    var chronic = (st.preview && st.preview.chronic_weekly_tss != null)
      ? st.preview.chronic_weekly_tss
      : st.settings.chronic_weekly_tss;
    var peaks = (st.preview && st.preview.peak_by_ramp) || {};
    var ramps = [
      { pct: 0.03, key: '3', label: 'Gentle 3%' },
      { pct: 0.05, key: '5', label: 'Standard 5%' },
      { pct: 0.07, key: '7', label: 'Aggressive 7%' },
    ];
    var segs = ramps.map(function (r) {
      var on = Math.abs(st.rampPct - r.pct) < 0.001;
      var pk = peaks[r.key] != null ? 'peak ' + Math.round(peaks[r.key]) : '';
      return '<button type="button" role="radio" class="' + (on ? 'is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-ramp="' + r.pct + '">' +
        esc(r.label) + (pk ? '<small>' + esc(pk) + '</small>' : '') + '</button>';
    }).join('');
    var chips = TAPER_CHIPS.map(function (c) {
      var on = st.taperWeeks === c.weeks;
      return '<button type="button" role="radio" class="rv-race-modal__chip' + (on ? ' is-on' : '') + '" aria-checked="' + (on ? 'true' : 'false') + '" data-taper="' + c.weeks + '">' + esc(c.label) + '</button>';
    }).join('');
    var weeks = (st.preview && st.preview.weeks) || [];
    var peakBox = st.peakOpen
      ? '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="wiz-peak">Peak TSS</label>' +
        '<input class="rv-race-modal__input rv-race-modal__input--mono" id="wiz-peak" type="number" min="1" step="1" placeholder="' +
        esc(String((st.preview && st.preview.peak_tss) || st.settings.suggested_peak_tss || '')) + '" value="' +
        esc(st.peakTss != null ? String(st.peakTss) : '') + '"></div>'
      : '';
    return '<div class="rv-wiz-tile rv-wiz-tile--row"><span class="rv-subtitle">Starting point \u00b7 your last 28 days</span>' +
      '<span class="rv-mono" style="font-size:18px;font-weight:700">' + Math.round(chronic || 0) + ' TSS/wk</span></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="wiz-ramp-lbl">Weekly ramp</span>' +
      '<div class="rv-race-modal__seg rv-wiz-seg" role="radiogroup" aria-labelledby="wiz-ramp-lbl">' + segs + '</div></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="wiz-taper-lbl">Taper</span>' +
      '<div role="radiogroup" aria-labelledby="wiz-taper-lbl" style="display:flex;gap:6px;flex-wrap:wrap">' + chips + '</div></div>' +
      '<div class="rv-wiz-bars-wrap"><div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span class="rv-race-modal__label">Weekly targets</span>' + guardHtml(weeks) + '</div>' +
      barsHtml(weeks, false) + '</div>' +
      '<button type="button" class="rv-wiz-linkbtn" data-toggle-peak>Set my own peak \u203a</button>' +
      peakBox;
  }

  function step4Body() {
    var rest = restList();
    var days = DAYS.map(function (label, i) {
      var on = rest.indexOf(i) >= 0;
      return '<button type="button" class="rv-wiz-day" aria-pressed="' + (on ? 'true' : 'false') + '" data-rest="' + i + '">' + label + '</button>';
    }).join('');
    var typ = DAYS.map(function (label, i) {
      var on = rest.indexOf(i) >= 0;
      return '<div class="rv-wiz-typ' + (on ? ' is-rest' : '') + '">' + (on ? 'Rest' : 'Train') + '</div>';
    }).join('');
    var chk = st.weekCheck || {};
    var bad = chk.fits === false;
    return '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="wiz-rest-lbl">Rest days <span class="rv-race-modal__hint">tap to toggle</span></span>' +
      '<div class="rv-wiz-days" role="group" aria-labelledby="wiz-rest-lbl">' + days + '</div></div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px">' +
      '<div><span class="rv-race-modal__label">Most training days in a row</span>' +
      '<div class="rv-subtitle" style="font-size:12px">Plan warns before it schedules more.</div></div>' +
      '<div class="rv-wiz-stepper">' +
      '<button type="button" class="rv-wiz-sq" data-step="maxConsecutive" data-dir="-1" aria-label="Fewer days"' + (st.maxConsecutive <= 1 ? ' disabled' : '') + '>\u2212</button>' +
      '<span class="rv-wiz-stepper__val">' + st.maxConsecutive + '</span>' +
      '<button type="button" class="rv-wiz-sq" data-step="maxConsecutive" data-dir="1" aria-label="More days"' + (st.maxConsecutive >= 6 ? ' disabled' : '') + '>+</button>' +
      '</div></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label">A typical week</span>' +
      '<div class="rv-wiz-days">' + typ + '</div>' +
      '<span class="rv-wiz-check' + (bad ? ' is-bad' : '') + '">' + esc(chk.message || '') + '</span></div>';
  }

  function step5Body() {
    var race = st.race || {};
    var goal = race.goal_time_seconds ? fmtHMS(race.goal_time_seconds) : '';
    var pace = race.goal_time_seconds ? paceStr(race.goal_time_seconds, race.distance_km) : '';
    var dist = race.distance_km != null ? (Math.round(race.distance_km * 10) / 10) + ' km' : '';
    var factors = (st.fit && st.fit.taper_factors) || [];
    var chronic = (st.preview && st.preview.chronic_weekly_tss) || st.settings.chronic_weekly_tss || 0;
    var peak = (st.preview && st.preview.peak_tss) || 0;
    var weeks = (st.preview && st.preview.weeks) || [];
    var raceLine = [race.name, fmtLong(race.race_date), dist, goal ? ('goal ' + goal + (pace ? ' (' + pace + ')' : '')) : '', 'A race']
      .filter(Boolean).join(' \u00b7 ');
    var shapeLine = (st.shape.charAt(0).toUpperCase() + st.shape.slice(1)) + ' from ' + fmtDayMon(st.blockStart) +
      ': build ' + st.buildWeeks + ' \u00b7 peak hold ' + st.peakHoldWeeks + ' \u00b7 taper ' + st.taperWeeks +
      ' \u00b7 race week. After: recover ' + st.recoverWeeks + ', rebuild ' + st.rebuildWeeks + '.';
    var loadLine = 'From ' + Math.round(chronic) + ' TSS/wk \u00b7 +' + Math.round(st.rampPct * 100) +
      '% a week \u00b7 peak ' + Math.round(peak) + ' \u00b7 taper ' + taperPctLabel(factors) + ' \u00b7 race week 40%';
    var weekLine = 'Rest ' + restNames() + ' \u00b7 at most ' + st.maxConsecutive + ' days in a row';
    function row(k, text, step) {
      return '<div class="rv-wiz-rv"><span class="rv-wiz-rv__k">' + esc(k) + '</span><span>' + text +
        '</span><a href="#" data-jump="' + step + '">Edit</a></div>';
    }
    return '<div>' +
      row('Race', esc(raceLine), 1) +
      row('Shape', esc(shapeLine), 2) +
      row('Load', esc(loadLine), 3) +
      row('Your week', esc(weekLine), 4) +
      '</div>' +
      '<div class="rv-wiz-bars-wrap"><span class="rv-race-modal__label">Road to ' + esc(race.name || 'race') + '</span>' +
      barsHtml(weeks, true) + ribbonHtml(weeks, true) + '</div>' +
      '<span class="rv-subtitle" style="font-size:12.5px">Creating the plan sets weekly targets only. Your sessions and coach imports stay as they are, and you can change any of this later in Settings \u203a Plan.</span>';
  }

  function footerHint() {
    if (st.step !== 1) return '';
    var date = st.newName ? st.newDate : (st.race && st.race.race_date);
    var n = weeksToRace(st.settings.next_monday, date);
    if (!n) return '';
    return n + ' week' + (n === 1 ? '' : 's') + ' from next Monday';
  }

  function canNext() {
    if (st.busy) return false;
    if (st.step === 1) {
      if (st.newName.trim()) return !!(st.newDate && parseFloat(st.newDist, 10) > 0);
      return !!(st.race && st.race.id);
    }
    if (st.step === 2) return !st.layoutError && weeksAvailable() >= (st.settings.min_block_weeks || 6);
    if (st.step === 3) return !!(st.preview && st.preview.allowed);
    if (st.step === 4) return !!(st.weekCheck && st.weekCheck.fits);
    return true;
  }

  function paint() {
    var root = rootEl();
    var meta = stepMeta(st.step);
    var body = '';
    if (st.step === 1) body = step1Body();
    else if (st.step === 2) body = step2Body();
    else if (st.step === 3) body = step3Body();
    else if (st.step === 4) body = step4Body();
    else body = step5Body();
    var hint = footerHint();
    var back = st.step > 1
      ? '<button type="button" class="rv-btn rv-btn--ghost" data-wiz-back>\u2039 Back</button>'
      : '<span></span>';
    if (st.step === 1) {
      back = '<span class="rv-race-modal__summary">' + esc(hint) + '</span>';
    }
    var err = st.error && st.step === 1
      ? '<p class="rv-wiz-err rv-race-modal__alert" role="alert">' + esc(st.error) + '</p>'
      : '';
    var cancel = st.step === 1
      ? '<button type="button" class="rv-btn rv-btn--secondary" data-wiz-cancel>Cancel</button>'
      : '';
    root.innerHTML =
      '<div class="rv-race-modal-backdrop" id="v2-plan-wiz-backdrop">' +
      '<div class="rv-race-modal rv-wiz" id="v2-plan-wiz" role="dialog" aria-modal="true" aria-labelledby="v2-plan-wiz-title">' +
      '<div class="rv-race-modal__head"><div class="rv-wiz__kicker-row"><div>' +
      '<span class="rv-race-modal__kicker">' + esc(meta.kicker) + '</span>' +
      '<h2 class="rv-race-modal__title" id="v2-plan-wiz-title">' + esc(meta.title) + '</h2></div>' +
      '<button type="button" class="rv-race-modal__close" data-wiz-cancel aria-label="Close">\u00d7</button></div></div>' +
      progressHtml() +
      '<div class="rv-race-modal__body" id="v2-plan-wiz-body">' + body + '</div>' +
      err +
      '<div class="rv-race-modal__foot">' + back +
      '<div class="rv-race-modal__actions">' + cancel +
      '<button type="button" class="rv-btn rv-btn--primary" data-wiz-next' + (canNext() ? '' : ' disabled') + '>' +
      esc(meta.next) + '</button></div></div></div></div>';
    bind();
  }

  function bindRadios(group) {
    if (!group) return;
    group.addEventListener('keydown', function (ev) {
      var dir = ev.key === 'ArrowRight' || ev.key === 'ArrowDown' ? 1
        : ev.key === 'ArrowLeft' || ev.key === 'ArrowUp' ? -1 : 0;
      if (!dir) return;
      var items = Array.prototype.filter.call(group.querySelectorAll('[role="radio"]'), function (el) {
        return el.getAttribute('aria-disabled') !== 'true';
      });
      if (!items.length) return;
      ev.preventDefault();
      var i = items.indexOf(document.activeElement);
      var n = items[(i + dir + items.length) % items.length];
      n.focus();
      n.click();
    });
  }

  function bind() {
    var dlg = document.getElementById('v2-plan-wiz');
    var backdrop = document.getElementById('v2-plan-wiz-backdrop');
    if (!dlg) return;
    dlg.querySelectorAll('[data-wiz-cancel]').forEach(function (b) {
      b.addEventListener('click', function () { close(true); });
    });
    if (backdrop) backdrop.addEventListener('click', function (ev) {
      if (ev.target === backdrop) close(true);
    });
    dlg.querySelectorAll('[data-jump]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        ev.preventDefault();
        go(parseInt(b.getAttribute('data-jump'), 10));
      });
    });
    var back = dlg.querySelector('[data-wiz-back]');
    if (back) back.addEventListener('click', function () { go(st.step - 1); });
    var next = dlg.querySelector('[data-wiz-next]');
    if (next) next.addEventListener('click', onNext);
    dlg.querySelectorAll('[data-pick-race]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.getAttribute('aria-disabled') === 'true') return;
        var id = b.getAttribute('data-pick-race');
        st.race = (st.settings.upcoming_races || []).find(function (r) { return r.id === id; }) || null;
        st.newName = '';
        st.error = '';
        paint();
      });
    });
    dlg.querySelectorAll('[data-dist-chip]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        var el = document.getElementById('wiz-dist');
        if (el) el.value = chip.getAttribute('data-dist-chip');
        readNewRace();
        updateStep1Live();
      });
    });
    ['wiz-name', 'wiz-date', 'wiz-dist', 'wiz-goal'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', function () {
        readNewRace();
        updateStep1Live();
      });
    });
    var start = document.getElementById('wiz-start');
    if (start) start.addEventListener('change', function () {
      st.blockStart = mondayISO(start.value || st.settings.next_monday);
      refit().then(refreshPreview).then(paint);
    });
    dlg.querySelectorAll('[data-shape]').forEach(function (b) {
      b.addEventListener('click', function () {
        st.shape = b.getAttribute('data-shape');
        refit().then(refreshPreview).then(paint);
      });
    });
    dlg.querySelectorAll('[data-ramp]').forEach(function (b) {
      b.addEventListener('click', function () {
        st.rampPct = parseFloat(b.getAttribute('data-ramp'), 10);
        refreshPreview().then(paint);
      });
    });
    dlg.querySelectorAll('[data-taper]').forEach(function (b) {
      b.addEventListener('click', function () {
        st.taperWeeks = parseInt(b.getAttribute('data-taper'), 10);
        refit().then(refreshPreview).then(paint);
      });
    });
    dlg.querySelectorAll('[data-rest]').forEach(function (b) {
      b.addEventListener('click', function () {
        var d = parseInt(b.getAttribute('data-rest'), 10);
        var i = st.restDays.indexOf(d);
        if (i >= 0) st.restDays.splice(i, 1);
        else st.restDays.push(d);
        refreshWeekCheck().then(paint);
      });
    });
    dlg.querySelectorAll('[data-step]').forEach(function (b) {
      b.addEventListener('click', function () {
        var key = b.getAttribute('data-step');
        var dir = parseInt(b.getAttribute('data-dir'), 10);
        var bounds = { buildWeeks: [3, 30], peakHoldWeeks: [0, 8], taperWeeks: [1, 3], recoverWeeks: [0, 4], rebuildWeeks: [0, 12], maxConsecutive: [1, 6] };
        var bds = bounds[key] || [0, 99];
        st[key] = Math.max(bds[0], Math.min(bds[1], (st[key] || 0) + dir));
        if (key === 'maxConsecutive') refreshWeekCheck().then(paint);
        else if (key === 'recoverWeeks' || key === 'rebuildWeeks') paint();
        else refit().then(refreshPreview).then(paint);
      });
    });
    var togA = dlg.querySelector('[data-toggle-after]');
    if (togA) togA.addEventListener('click', function () { st.afterOpen = !st.afterOpen; paint(); });
    var togP = dlg.querySelector('[data-toggle-peak]');
    if (togP) togP.addEventListener('click', function () { st.peakOpen = !st.peakOpen; paint(); });
    var peak = document.getElementById('wiz-peak');
    if (peak) peak.addEventListener('change', function () {
      var v = peak.value.trim();
      st.peakTss = v === '' ? null : parseFloat(v, 10);
      refreshPreview().then(paint);
    });
    bindRadios(dlg.querySelector('[role="radiogroup"][aria-labelledby="wiz-shape-lbl"]'));
    bindRadios(dlg.querySelector('[role="radiogroup"][aria-labelledby="wiz-ramp-lbl"]'));
    bindRadios(dlg.querySelector('[role="radiogroup"][aria-labelledby="wiz-taper-lbl"]'));
  }

  function readNewRace() {
    var name = document.getElementById('wiz-name');
    var date = document.getElementById('wiz-date');
    var dist = document.getElementById('wiz-dist');
    var goal = document.getElementById('wiz-goal');
    st.newName = name ? name.value : st.newName;
    st.newDate = date ? date.value : st.newDate;
    st.newDist = dist ? dist.value : st.newDist;
    st.newGoal = goal ? goal.value : st.newGoal;
    if (st.newName.trim()) st.race = {
      name: st.newName.trim(),
      race_date: st.newDate,
      distance_km: parseFloat(st.newDist, 10) || null,
      goal_time_seconds: parseHMS(st.newGoal),
    };
  }

  function updateStep1Live() {
    var pace = document.getElementById('wiz-pace');
    var km = parseFloat(st.newDist, 10);
    var goalSec = parseHMS(st.newGoal);
    if (pace) {
      if (!isNaN(goalSec) && goalSec && km > 0) {
        pace.hidden = false;
        pace.innerHTML = '= <b>' + esc(paceStr(goalSec, km)) + '</b>';
      } else {
        pace.hidden = true;
      }
    }
    var hint = document.querySelector('#v2-plan-wiz .rv-race-modal__summary');
    if (hint) hint.textContent = footerHint();
    var next = document.querySelector('[data-wiz-next]');
    if (next) next.disabled = !canNext();
    document.querySelectorAll('[data-dist-chip]').forEach(function (chip) {
      var p = DIST_PRESETS.find(function (x) { return String(x.km) === chip.getAttribute('data-dist-chip'); });
      chip.classList.toggle('is-on', p ? distChipOn(km, p) : false);
    });
  }

  function go(step) {
    st.step = Math.max(1, Math.min(5, step));
    st.error = '';
    var p = Promise.resolve();
    if (st.step >= 2) p = p.then(refit).then(refreshPreview);
    if (st.step === 4) p = p.then(refreshWeekCheck);
    p.then(paint);
  }

  function fieldStep(msg) {
    var m = String(msg || '').toLowerCase();
    if (/rest|consecutive/.test(m)) return 4;
    if (/ramp|peak_tss|taper_factor|guardrail/.test(m)) return 3;
    if (/build|peak_hold|taper|layout|block|shape|recover|rebuild/.test(m)) return 2;
    if (/a_race|race/.test(m)) return 1;
    return 2;
  }

  function onNext() {
    if (!canNext()) return;
    if (st.step === 1) {
      commitRace().then(function () { go(2); }).catch(function (e) {
        st.error = e.message || 'Could not save race';
        paint();
      });
      return;
    }
    if (st.step < 5) {
      go(st.step + 1);
      return;
    }
    createPlan();
  }

  function commitRace() {
    readNewRace();
    if (st.newName.trim()) {
      var goal = parseHMS(st.newGoal);
      if (st.newGoal && isNaN(goal)) {
        return Promise.reject(new Error('Goal time must be h:mm:ss'));
      }
      var payload = {
        name: st.newName.trim(),
        date: st.newDate,
        distance_km: parseFloat(st.newDist, 10),
        priority: 'A',
        role: 'a_race',
      };
      if (goal) payload.goal_time_seconds = goal;
      st.busy = true;
      paint();
      return api('POST', '/api/races', payload).then(function (race) {
        st.busy = false;
        st.race = race;
        st.newName = '';
        return api('GET', '/api/plan/revamp-settings').then(function (s) {
          st.settings = s;
          if (!st.blockStart) st.blockStart = s.next_monday;
        });
      }).catch(function (e) {
        st.busy = false;
        throw e;
      });
    }
    if (st.race && st.race.priority !== 'A') {
      st.busy = true;
      paint();
      return api('PATCH', '/api/races/' + encodeURIComponent(st.race.id), { priority: 'A', role: 'a_race' }).then(function (race) {
        st.busy = false;
        st.race = race;
        return api('GET', '/api/plan/revamp-settings').then(function (s) { st.settings = s; });
      }).catch(function (e) {
        st.busy = false;
        throw e;
      });
    }
    return Promise.resolve();
  }

  function createPlan() {
    st.busy = true;
    paint();
    var body = draftPayload();
    api('PUT', '/api/plan/revamp-settings', body).then(function () {
      st.busy = false;
      var name = (st.race && st.race.name) || 'your race';
      close(true);
      var reload = window.V2TrainingPlan && window.V2TrainingPlan.reload;
      var p = reload ? reload() : Promise.resolve();
      return Promise.resolve(p).then(function () {
        toast('Plan created for ' + name);
      });
    }).catch(function (e) {
      st.busy = false;
      st.error = e.message || 'Could not create plan';
      st.step = fieldStep(st.error);
      paint();
    });
  }

  function open() {
    opener = document.activeElement;
    document.addEventListener('keydown', onKey, true);
    document.body.style.overflow = 'hidden';
    api('GET', '/api/plan/revamp-settings').then(function (s) {
      var aRaces = (s.upcoming_races || []).filter(function (r) { return r.priority === 'A' && !r.too_short; });
      var start = aRaces.length ? 2 : 1;
      st = defaultState(s, start);
      var p = Promise.resolve();
      if (start === 2) p = refit().then(refreshPreview);
      return p.then(paint);
    }).catch(function (e) {
      st = defaultState({ upcoming_races: [], defaults: {}, next_monday: mondayISO(new Date().toISOString().slice(0, 10)), rest_days: [] }, 1);
      st.error = e.message || 'Could not load settings';
      paint();
    });
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target.closest('[data-plan-setup]');
    if (!t) return;
    ev.preventDefault();
    open();
  });

  function boot() {
    if (/\bsetup=1\b/.test(location.search)) open();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.V2PlanWizard = { open: open, close: close };
})();
