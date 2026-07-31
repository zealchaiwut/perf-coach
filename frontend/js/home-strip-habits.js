(function () {
  'use strict';

  var _WH   = window.WheelHelpers;
  var _habitsBlock = null;

  /* ── Helpers ── */

  // Delegates to the shared escaper (issue #1603).
  function _esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _bangkokTodayStr() {
    return window.AppCommon.todayISO();
  }

  function _showToast(msg, isErr) {
    if (typeof UIStates !== 'undefined' && UIStates.showToast) {
      UIStates.showToast(msg, isErr ? 'error' : 'success');
      return;
    }
    var el = document.createElement('div');
    el.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);' +
      'background:' + (isErr ? 'var(--danger)' : '#0b1530') +
      ';color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;z-index:9999;';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 3500);
  }

  /* ── Today-check circle ── */

  function _todayCheckHTML(habit, isChecked) {
    if (habit.auto_fill_source) {
      return '<div class="hw-autofill-marker" title="Auto-filled from ' +
        _esc(habit.auto_fill_source) + '" aria-label="Auto-filled">&#8226;</div>';
    }
    var name = _esc(habit.name || 'habit');
    if (isChecked) {
      return '<div class="hw-check-circle hw-check-circle--done"' +
        ' data-habit-id="' + _esc(habit.id) + '" title="Tap to uncheck"' +
        ' role="button" tabindex="0" aria-pressed="true"' +
        ' aria-label="' + name + ', done today. Activate to uncheck.">' +
        '<i class="ti ti-check"></i></div>';
    }
    return '<div class="hw-check-circle hw-check-circle--empty"' +
      ' data-habit-id="' + _esc(habit.id) + '" title="Tap to check"' +
      ' role="button" tabindex="0" aria-pressed="false"' +
      ' aria-label="' + name + ', not done today. Activate to check.">+</div>';
  }

  /* ── Habits widget ── */

  function _renderHabits(habits) {
    var widget = document.getElementById('home-habits-widget');
    if (!widget) return;

    if (!habits || !habits.daily_habits || habits.daily_habits.length === 0) {
      widget.innerHTML =
        '<div class="card-head">' +
          '<h2 class="ttl"><i class="ti ti-checkbox"></i>This week\'s habits</h2>' +
          '<a href="/habits" class="hw-all-link">All habits &#8594;</a>' +
        '</div>' +
        '<div class="hw-empty">Add habits to track your week. <a href="/habits">Add habits</a></div>';
      return;
    }

    var wheel    = habits.wheel || [];
    var pct      = habits.pct_elapsed != null ? habits.pct_elapsed : 0;
    var fullDays = _WH
      ? (wheel || []).filter(function (w) { return w.state === 'full'; }).length
      : 0;

    var allDaily = habits.daily_habits || [];
    var trainingHabits = allDaily.filter(function (h) { return h.section === 'training'; });
    var generalHabits  = allDaily.filter(function (h) { return h.section !== 'training'; });

    /* Build rows for one section, capped at maxCount */
    function _buildSectionRows(habitsArr, maxCount) {
      var rows = '';
      var shown = habitsArr.slice(0, maxCount);
      shown.forEach(function (h) {
        var isChecked = !!h.today_checked;
        var streak    = h.streak != null ? h.streak : 0;
        var weekCount = h.week_count != null ? h.week_count : 0;
        var iconChip  = _WH
          ? _WH.habitIconHTML(h.icon, h.color, 28)
          : '<span style="background:' + (h.color || '#9ca3af') + ';border-radius:8px;' +
            'width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;">' +
            '<i class="ti ' + _esc(h.icon || 'ti-checkbox') + '"></i></span>';
        var flameBadge = streak >= 3
          ? '<span class="hw-flame-badge">&#x1F525;' + streak + '</span>'
          : '';
        rows +=
          '<div class="hw-habit-row" data-habit-id="' + _esc(h.id) + '">' +
            '<div class="hw-habit-icon">' + iconChip + '</div>' +
            '<div class="hw-habit-info">' +
              '<span class="hw-habit-name">' + _esc(h.name) + '</span>' +
              flameBadge +
            '</div>' +
            '<span class="hw-week-count">' + weekCount + '/7</span>' +
            _todayCheckHTML(h, isChecked) +
          '</div>';
      });
      return rows;
    }

    /* Wheel */
    var wheelHTML = _WH ? _WH.buildWheelSvg(wheel, pct, { fullDays: fullDays }) : '';

    /* Build section HTML — Training first, General second */
    var listHTML = '';
    if (trainingHabits.length > 0) {
      listHTML +=
        '<div class="hw-section-hdr">Training</div>' +
        _buildSectionRows(trainingHabits, 5);
    }
    if (generalHabits.length > 0) {
      if (trainingHabits.length > 0) {
        listHTML += '<div class="hw-section-hdr">General</div>';
      }
      listHTML += _buildSectionRows(generalHabits, 5);
    }

    var totalDaily = allDaily.length;
    var shownCount = Math.min(trainingHabits.length, 5) + Math.min(generalHabits.length, 5);
    var remaining  = Math.max(0, totalDaily - shownCount);

    /* Footer */
    var footerHTML =
      '<div class="hw-footer">' +
        (remaining > 0
          ? '<span class="hw-footer-more">+' + remaining + ' more</span> &middot; ' : '') +
        '<span class="hw-footer-hint">tap &#9675; to check today</span>' +
        ' &middot; <a href="/habits" class="hw-footer-manage">manage &#8594;</a>' +
      '</div>';

    widget.innerHTML =
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-checkbox"></i>This week\'s habits</h2>' +
        '<a href="/habits" class="hw-all-link">All habits &#8594;</a>' +
      '</div>' +
      '<div class="hw-body">' +
        '<div class="hw-wheel-wrap">' + wheelHTML + '</div>' +
        '<div class="hw-habits-list">' + listHTML + '</div>' +
      '</div>' +
      footerHTML;

    _wireCheckCircles(widget, habits);
  }

  /* ── Today-check wiring ── */

  function _wireCheckCircles(widget, habits) {
    var today = _bangkokTodayStr();
    var habitMap = {};
    var allHabits = habits.daily_habits || [];
    allHabits.forEach(function (h) { habitMap[h.id] = h; });

    widget.querySelectorAll('.hw-check-circle').forEach(function (el) {
      if (el._hasListener) return;
      el._hasListener = true;

      /* Keyboard activation — the circle is a div with role="button" (no
         native activation keys), so Enter/Space must be wired up by hand
         to match native <button> behavior for keyboard users. */
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          el.click();
        }
      });

      el.addEventListener('click', async function () {
        var hid     = el.getAttribute('data-habit-id');
        var habit   = habitMap[hid];
        if (!habit || habit.auto_fill_source) return;

        var isDone = el.classList.contains('hw-check-circle--done');

        /* Optimistic update */
        if (isDone) {
          el.classList.replace('hw-check-circle--done', 'hw-check-circle--empty');
          el.innerHTML = '+';
          el.setAttribute('aria-pressed', 'false');
        } else {
          el.classList.replace('hw-check-circle--empty', 'hw-check-circle--done');
          el.innerHTML = '<i class="ti ti-check"></i>';
          el.setAttribute('aria-pressed', 'true');
        }

        try {
          if (isDone) {
            var logId = el.getAttribute('data-log-id');
            if (!logId) {
              var delByDate = await fetch(
                '/api/habits/' + encodeURIComponent(hid) + '/log?date=' + today,
                { method: 'DELETE' }
              );
              if (!delByDate.ok && delByDate.status !== 404) throw new Error('delete failed');
            } else {
              var delRes = await fetch('/api/habits/logs/' + logId, { method: 'DELETE' });
              if (!delRes.ok) throw new Error('delete failed');
              el.removeAttribute('data-log-id');
            }
            /* Locally update today_checked in cached block */
            if (_habitsBlock) {
              (_habitsBlock.daily_habits || []).forEach(function (h) {
                if (h.id === hid) h.today_checked = false;
              });
              (_habitsBlock.top_habits || []).forEach(function (h) {
                if (h.id === hid) h.today_checked = false;
              });
            }
          } else {
            var postRes = await fetch('/api/habits/logs', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ habit_id: hid, logged_date: today }),
            });
            if (!postRes.ok) throw new Error('post failed');
            var postData = await postRes.json();
            if (postData && postData.id) el.setAttribute('data-log-id', String(postData.id));
            /* Locally update today_checked in cached block */
            if (_habitsBlock) {
              (_habitsBlock.daily_habits || []).forEach(function (h) {
                if (h.id === hid) h.today_checked = true;
              });
              (_habitsBlock.top_habits || []).forEach(function (h) {
                if (h.id === hid) h.today_checked = true;
              });
            }
          }
          /* Re-render from local state — no summary re-fetch */
          if (_habitsBlock) _renderHabits(_habitsBlock);
        } catch (_) {
          /* Revert optimistic update */
          if (isDone) {
            el.classList.replace('hw-check-circle--empty', 'hw-check-circle--done');
            el.innerHTML = '<i class="ti ti-check"></i>';
            el.setAttribute('aria-pressed', 'true');
          } else {
            el.classList.replace('hw-check-circle--done', 'hw-check-circle--empty');
            el.innerHTML = '+';
            el.setAttribute('aria-pressed', 'false');
          }
          _showToast('Could not save. Try again.', true);
        }
      });
    });
  }

  /* ── Public API ── */

  function render(summary) {
    _habitsBlock = (summary && summary.habits) ? summary.habits : null;
    _renderHabits(_habitsBlock);
  }

  window.HomeStripHabits = { render: render };
})();
