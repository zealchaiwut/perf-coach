/**
 * Home "This morning" strip (home revamp v2) — four quick asks: weigh in,
 * today's session, habits, wellness metrics. Reuses the same endpoints the old
 * home weight widget (home.js's _hwwInitStepper) and habits strip
 * (home-strip-habits.js) already used — no new backend surface.
 *
 * window.HomeMorning.render(host, ctx):
 *   ctx.summary        — /api/home/summary payload (for weight + habits blocks)
 *   ctx.weekDays        — /api/planned-sessions `days` array (for today's session)
 *   ctx.onOpenSession(id)
 *   ctx.onMarkDone(id)  — should POST /api/planned-sessions/{id}/mark-done
 *   ctx.onWeightLogged() — called after a successful weight log/patch
 *   ctx.onHabitToggle()  — called after a successful habit log/unlog
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _famClass(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift';
  }

  function _isOpenPlanned(p) {
    if (!p || p.session_type === 'rest') return false;
    var s = p.status || 'planned';
    if (s === 'done_auto' || s === 'done_manual') return false;
    if (s === 'missed' || s === 'missed_auto' || s === 'missed_manual') return false;
    return true;
  }

  function _sessionDisplayName(p) {
    var n = (p && p.name) ? String(p.name).trim() : '';
    if (n) return n;
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength' || t === 'plyo') return 'Strength session';
    if (t === 'stretch') return 'Stretch session';
    return 'Easy run';
  }

  function _sessionMeta(p) {
    var s = p.structure || {};
    if (Array.isArray(s.exercises) && s.exercises.length) {
      var bits = [s.exercises.length + ' exercise' + (s.exercises.length > 1 ? 's' : '')];
      var tss = p.estimated_tss != null ? p.estimated_tss : null;
      if (tss != null) bits.push('~' + Math.round(tss) + ' TSS');
      if (p.notes) bits.push(String(p.notes).slice(0, 60));
      return bits.join(' · ');
    }
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0, r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      var bits2 = [];
      if (tot) bits2.push(tot + ' min');
      if (p.estimated_tss != null) bits2.push('~' + Math.round(p.estimated_tss) + ' TSS');
      if (p.notes) bits2.push(String(p.notes).slice(0, 60));
      return bits2.join(' · ');
    }
    return p.notes ? String(p.notes).slice(0, 80) : '';
  }

  function _todaySession(weekDays) {
    var today = _todayISO();
    var day = (weekDays || []).find(function (d) { return d.date === today; });
    if (!day) return null;
    // Prefer an open (not-yet-done) non-rest session; fall back to any
    // non-rest so a done_auto/done_manual session still counts as "session
    // done" rather than looking like a rest day.
    var planned = (day.planned || []).filter(function (p) {
      return ((p.session_type || '').toLowerCase() !== 'rest');
    });
    if (!planned.length) return null;
    var open = planned.filter(_isOpenPlanned);
    return open.length ? open[0] : planned[0];
  }

  function _nextAfterToday(weekDays) {
    var today = _todayISO();
    var days = weekDays || [];
    for (var i = 0; i < days.length; i++) {
      if (days[i].date <= today) continue;
      var open = (days[i].planned || []).filter(_isOpenPlanned);
      if (open.length) return { day: days[i], p: open[0] };
    }
    return null;
  }

  function _fmtShortDay(iso) {
    try {
      var d = new Date(iso + 'T12:00:00');
      var dow = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
      var mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
      return dow + ' ' + d.getDate() + ' ' + mon;
    } catch (_) {
      return iso;
    }
  }

  // ── State (per render() call) ──────────────────────────────────────────

  function render(host, ctx) {
    if (!host) return;
    ctx = ctx || {};
    var summary = ctx.summary || {};
    var weightBlock = summary.weight || null;
    var habitsBlock = summary.habits || null;
    var session = _todaySession(ctx.weekDays);

    var done = { weight: !!(weightBlock && weightBlock.logged_today), session: false, habits: false, metrics: false };
    if (habitsBlock && Array.isArray(habitsBlock.daily_habits) && habitsBlock.daily_habits.length) {
      done.habits = habitsBlock.daily_habits.every(function (h) { return !!h.today_checked; });
    } else {
      done.habits = true; // no habits tracked → nothing to ask
    }
    if (!session) {
      done.session = true; // rest day / nothing planned → nothing to ask
    } else {
      var st = session.status || 'planned';
      done.session = (st === 'done_auto' || st === 'done_manual');
    }
    done.metrics = !!(summary.readiness && summary.readiness.logged);

    function _rowsDoneCount() {
      return (done.weight ? 1 : 0) + (done.session ? 1 : 0) + (done.habits ? 1 : 0) + (done.metrics ? 1 : 0);
    }

    function _paint() {
      var n = _rowsDoneCount();
      var allDone = n === 4;
      var wrap = host.querySelector('#hm-morning');
      if (wrap) wrap.classList.toggle('hm-all-done', allDone);
      var cnt = host.querySelector('#hm-cnt');
      if (cnt) cnt.textContent = n + ' of 4 done';
      var dots = host.querySelector('#hm-dots');
      if (dots) {
        dots.innerHTML = [0, 1, 2, 3].map(function (i) {
          return '<span class="hm-pd' + (i < n ? ' on' : '') + '"></span>';
        }).join('');
      }
      // Session/habits/metrics collapse when done. Weight stays visible with
      // "Logged · Change" until the whole morning is complete — otherwise
      // the stepper vanishes and users hunt for it on Weight trend.
      ['session', 'habits', 'metrics'].forEach(function (k) {
        var row = host.querySelector('.hm-row[data-k="' + k + '"]');
        if (row) row.classList.toggle('hm-row--done', done[k]);
      });
      var weightRow = host.querySelector('.hm-row[data-k="weight"]');
      if (weightRow) weightRow.classList.toggle('hm-row--done', allDone && done.weight);
    }

    // ── Weigh-in row (ported from home.js's _hwwInitStepper) ──────────────

    function _loggedKgLabel() {
      if (weightBlock && weightBlock.last_entry_kg != null) {
        return Number(weightBlock.last_entry_kg).toFixed(1);
      }
      if (weightBlock && weightBlock.current_kg != null) {
        return Number(weightBlock.current_kg).toFixed(1);
      }
      return null;
    }

    function _weightRowHtml() {
      var trend = weightBlock && weightBlock.seven_day_avg != null
        ? Number(weightBlock.seven_day_avg).toFixed(1) + ' kg'
        : (weightBlock && weightBlock.current_kg != null ? Number(weightBlock.current_kg).toFixed(1) + ' kg' : '—');
      var sub = done.weight
        ? ('logged ' + (_loggedKgLabel() != null ? _loggedKgLabel() + ' kg' : 'today'))
        : ('trend ' + trend);
      return (
        '<div class="hm-row" data-k="weight">' +
          '<span class="hm-ic hm-ic--weight">&#9878;</span>' +
          '<span class="hm-tx"><span class="hm-t">Weigh in</span>' +
            '<span class="hm-s">' + esc(sub) + '</span></span>' +
          '<span class="hm-act" id="hm-weight-act"></span>' +
        '</div>'
      );
    }

    function _wireWeightRow() {
      var actEl = host.querySelector('#hm-weight-act');
      if (!actEl) return;
      var prefill = weightBlock && weightBlock.last_entry_kg != null
        ? Number(weightBlock.last_entry_kg).toFixed(1) : '';

      function _showLoggedSummary() {
        var kg = _loggedKgLabel();
        actEl.innerHTML =
          (kg != null ? '<span class="hm-logged">Logged ' + esc(kg) + ' kg</span>' : '') +
          '<button type="button" class="hm-btn hm-btn--ghost" id="hm-w-change">Change</button>';
        var changeBtn = actEl.querySelector('#hm-w-change');
        if (changeBtn) {
          changeBtn.addEventListener('click', function () {
            _renderStepper(kg != null ? parseFloat(kg) : (prefill !== '' ? parseFloat(prefill) : null));
          });
        }
      }

      function _renderStepper(currentVal) {
        actEl.innerHTML =
          '<span class="hm-step">' +
            '<button type="button" id="hm-w-minus" aria-label="Decrease weight">&minus;</button>' +
            '<input id="hm-w-input" type="number" inputmode="decimal" step="0.1" min="20" max="300"' +
              ' value="' + (currentVal != null ? currentVal : '') + '" placeholder="—">' +
            '<button type="button" id="hm-w-plus" aria-label="Increase weight">+</button>' +
          '</span>' +
          '<button type="button" class="hm-btn hm-btn--lime" id="hm-w-log">Log</button>';

        var input = actEl.querySelector('#hm-w-input');
        var logBtn = actEl.querySelector('#hm-w-log');
        var minusBtn = actEl.querySelector('#hm-w-minus');
        var plusBtn = actEl.querySelector('#hm-w-plus');

        function _syncLogLabel() {
          var raw = input.value.trim();
          if (raw !== '' && !isNaN(parseFloat(raw))) {
            logBtn.textContent = 'Log ' + parseFloat(raw).toFixed(1) + ' kg';
            logBtn.setAttribute('data-hm-log-val', parseFloat(raw).toFixed(1));
          } else {
            logBtn.textContent = 'Log';
            logBtn.removeAttribute('data-hm-log-val');
          }
        }

        function _step(delta) {
          var cur = input.value === '' ? NaN : parseFloat(input.value);
          var next = isNaN(cur) ? (delta > 0 ? 20 : 300) : Math.min(300, Math.max(20, Math.round((cur + delta) * 10) / 10));
          input.value = next.toFixed(1);
          _syncLogLabel();
        }
        minusBtn.addEventListener('click', function () { _step(-0.1); });
        plusBtn.addEventListener('click', function () { _step(0.1); });
        input.addEventListener('input', _syncLogLabel);
        _syncLogLabel();

        logBtn.addEventListener('click', async function () {
          var raw = input.value.trim();
          if (raw === '' || isNaN(parseFloat(raw))) return;
          var val = parseFloat(raw);
          if (val < 20 || val > 300) return;
          logBtn.disabled = true;
          var todayStr = _todayISO();
          try {
            var res = await fetch('/api/weight-entries', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ entry_date: todayStr, weight_kg: val })
            });
            if (res.status === 409) {
              var conflictData = null;
              try { conflictData = await res.json(); } catch (_) {}
              var entryId = conflictData && conflictData.existing_id ? conflictData.existing_id : null;
              if (entryId) {
                var patchRes = await fetch('/api/weight-entries/' + entryId, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ weight_kg: val })
                });
                if (!patchRes.ok) { logBtn.disabled = false; return; }
              }
            } else if (!res.ok) {
              logBtn.disabled = false;
              return;
            }
            if (!weightBlock) weightBlock = {};
            weightBlock.logged_today = true;
            weightBlock.last_entry_kg = val;
            done.weight = true;
            var subEl = host.querySelector('.hm-row[data-k="weight"] .hm-s');
            if (subEl) subEl.textContent = 'logged ' + val.toFixed(1) + ' kg';
            _showLoggedSummary();
            _paint();
            if (ctx.onWeightLogged) ctx.onWeightLogged();
          } catch (_) {
            logBtn.disabled = false;
          }
        });
      }

      if (done.weight) {
        _showLoggedSummary();
      } else {
        _renderStepper(prefill !== '' ? parseFloat(prefill) : null);
      }
    }

    // ── Session row ─────────────────────────────────────────────────────

    function _sessionRowHtml() {
      if (!session) {
        return (
          '<div class="hm-row hm-row--done" data-k="session">' +
            '<span class="hm-ic hm-ic--session">&#127947;</span>' +
            '<span class="hm-tx"><span class="hm-t">No session today</span>' +
              '<span class="hm-s">rest day / nothing planned</span></span>' +
          '</div>'
        );
      }
      var acts = done.session
        ? ''
        : ('<span class="hm-act">' +
            '<button type="button" class="hm-btn hm-btn--blue" id="hm-sess-open">Open</button>' +
            '<button type="button" class="hm-btn hm-btn--ghost" id="hm-sess-done">Mark done</button>' +
          '</span>');
      return (
        '<div class="hm-row" data-k="session">' +
          '<span class="hm-ic hm-ic--session">&#127947;</span>' +
          '<span class="hm-tx"><span class="hm-t">' + esc(_sessionDisplayName(session)) + '</span>' +
            '<span class="hm-s">' + esc(_sessionMeta(session)) + '</span></span>' +
          acts +
        '</div>'
      );
    }

    function _wireSessionRow() {
      if (!session || done.session) return;
      var openBtn = host.querySelector('#hm-sess-open');
      if (openBtn) openBtn.addEventListener('click', function () {
        if (ctx.onOpenSession) ctx.onOpenSession(session.id);
      });
      var doneBtn = host.querySelector('#hm-sess-done');
      if (doneBtn) doneBtn.addEventListener('click', function () {
        // Local optimistic only — the row hides immediately; the actual
        // mark-done POST (and any resulting data refresh) is the caller's
        // responsibility via onMarkDone.
        done.session = true;
        _paint();
        if (ctx.onMarkDone) ctx.onMarkDone(session.id);
      });
    }

    // ── Habits row (ported from home-strip-habits.js's check-circle logic) ─

    function _habitsRowHtml() {
      var habits = (habitsBlock && habitsBlock.daily_habits) || [];
      if (!habits.length) {
        return (
          '<div class="hm-row hm-row--done" data-k="habits">' +
            '<span class="hm-ic hm-ic--habits">&#10003;</span>' +
            '<span class="hm-tx"><span class="hm-t">Habits</span>' +
              '<span class="hm-s">no habits tracked</span></span>' +
          '</div>'
        );
      }
      var HAB_CAP = 4;
      var shown = habits.slice(0, HAB_CAP);
      var more = habits.length - shown.length;
      var chips = shown.map(function (h) {
        var on = !!h.today_checked;
        return (
          '<button type="button" class="hm-hab' + (on ? ' hm-hab--on' : '') + '" data-habit-id="' + esc(h.id) + '">' +
            '<span class="hm-hab-bx">&#10003;</span>' + esc(h.name) +
          '</button>'
        );
      }).join('');
      if (more > 0) {
        chips += '<a class="hm-hab hm-hab--more" href="/habits">+' + more + ' more</a>';
      }
      // Row completes when all tracked habits are checked (not just the
      // shown cap) — matching the done.habits derivation above.
      return (
        '<div class="hm-row" data-k="habits">' +
          '<span class="hm-ic hm-ic--habits">&#10003;</span>' +
          '<span class="hm-tx"><span class="hm-t">Habits</span>' +
            '<span class="hm-s">tap to tick today</span></span>' +
          '<span class="hm-act hm-habs">' + chips + '</span>' +
        '</div>'
      );
    }

    function _openLogToday() {
      var row = document.getElementById('row-log');
      if (row) {
        row.hidden = false;
        row.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function _metricsRowHtml() {
      if (done.metrics) {
        var score = summary.readiness && summary.readiness.score;
        var scoreBit = score != null ? 'score ' + score : 'logged today';
        return (
          '<div class="hm-row" data-k="metrics">' +
            '<span class="hm-ic hm-ic--session">&#9829;</span>' +
            '<span class="hm-tx"><span class="hm-t">Readiness metrics</span>' +
              '<span class="hm-s">' + esc(scoreBit) + '</span></span>' +
            '<span class="hm-act"><button type="button" class="hm-btn hm-btn--ghost" id="hm-metrics-log">Change</button></span>' +
          '</div>'
        );
      }
      return (
        '<div class="hm-row" data-k="metrics">' +
          '<span class="hm-ic hm-ic--session">&#9829;</span>' +
          '<span class="hm-tx"><span class="hm-t">Readiness metrics</span>' +
            '<span class="hm-s">sleep quality, HRV, energy</span></span>' +
          '<span class="hm-act"><button type="button" class="hm-btn hm-btn--lime" id="hm-metrics-log">Log metrics</button></span>' +
        '</div>'
      );
    }

    function _wireMetricsRow() {
      var btn = host.querySelector('#hm-metrics-log');
      if (btn) btn.addEventListener('click', _openLogToday);
    }

    function _wireHabitsRow() {
      var today = _todayISO();
      var habits = (habitsBlock && habitsBlock.daily_habits) || [];
      var byId = {};
      habits.forEach(function (h) { byId[h.id] = h; });

      host.querySelectorAll('.hm-hab').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          var hid = btn.getAttribute('data-habit-id');
          var habit = byId[hid];
          if (!habit) return;
          var wasOn = btn.classList.contains('hm-hab--on');
          btn.classList.toggle('hm-hab--on', !wasOn);
          try {
            if (wasOn) {
              var delRes = await fetch('/api/habits/' + encodeURIComponent(hid) + '/log?date=' + today, { method: 'DELETE' });
              if (!delRes.ok && delRes.status !== 404) throw new Error('delete failed');
              habit.today_checked = false;
            } else {
              var postRes = await fetch('/api/habits/logs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ habit_id: hid, logged_date: today })
              });
              if (!postRes.ok) throw new Error('post failed');
              habit.today_checked = true;
            }
            done.habits = habits.every(function (h) { return !!h.today_checked; });
            _paint();
            if (ctx.onHabitToggle) ctx.onHabitToggle();
          } catch (_) {
            btn.classList.toggle('hm-hab--on', wasOn);
          }
        });
      });
    }

    // ── All-done footer ─────────────────────────────────────────────────

    function _allDoneHtml() {
      var next = _nextAfterToday(ctx.weekDays);
      var nextLine = '';
      if (next) {
        var bits = [_fmtShortDay(next.day.date), _sessionDisplayName(next.p)];
        var meta = _sessionMeta(next.p);
        if (meta) bits.push(meta);
        nextLine = '<span class="hm-s">next: ' + esc(bits.join(' · ')) + '</span>';
      }
      return (
        '<div class="hm-done">' +
          '<span class="hm-done-ic">&#10003;</span>' +
          '<span><span class="hm-t">Morning done — weight, session, habits and metrics all logged.</span>' +
            nextLine + '</span>' +
          '<span style="margin-left:auto"><button type="button" class="hm-btn hm-btn--ghost hm-btn--s" id="hm-undo">Undo</button></span>' +
        '</div>'
      );
    }

    host.innerHTML =
      '<div class="hm-morning" id="hm-morning">' +
        '<div class="hm-head">' +
          '<span class="hm-k">This morning</span>' +
          '<span class="hm-prog"><span class="hm-pdots" id="hm-dots"></span>' +
            '<span class="hm-cnt" id="hm-cnt"></span></span>' +
        '</div>' +
        '<div class="hm-rows">' +
          _weightRowHtml() +
          _sessionRowHtml() +
          _habitsRowHtml() +
          _metricsRowHtml() +
        '</div>' +
        _allDoneHtml() +
      '</div>';

    _wireWeightRow();
    _wireSessionRow();
    _wireHabitsRow();
    _wireMetricsRow();

    var undoBtn = host.querySelector('#hm-undo');
    if (undoBtn) {
      undoBtn.addEventListener('click', function () {
        // Session is the only row this widget can locally revert (weight and
        // habits are server-backed and would need a real un-log call, which
        // the mock doesn't offer either — Undo here only clears the local
        // "session marked done" optimism).
        done.session = !!session ? false : true;
        _paint();
      });
    }

    _paint();
  }

  window.HomeMorning = { render: render };
})();
