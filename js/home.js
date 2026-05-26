(function () {
  function todayISO() {
    return new Date().toISOString().slice(0, 10);
  }

  function setTodayLabel() {
    var el = document.getElementById('today-label');
    if (!el) return;
    var d = new Date();
    el.textContent = d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  }

  // Parse a duration string like "45 min", "10m", "1h 30m" → minutes (number)
  function parseDurationMin(str) {
    if (!str) return 0;
    var total = 0;
    var h = str.match(/(\d+)\s*h/i);
    var m = str.match(/(\d+)\s*m(?:in)?(?!\w)/i);
    if (h) total += parseInt(h[1], 10) * 60;
    if (m) total += parseInt(m[1], 10);
    return total;
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setClass(id, cls) {
    var el = document.getElementById(id);
    if (el) { el.className = 'dash-card-sub ' + (cls || ''); }
  }

  async function loadWeightCard(userId) {
    var today = todayISO();
    var sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    var lastWeekStart = sevenDaysAgo.toISOString().slice(0, 10);

    try {
      var res = await fetch('/api/weight?user_id=' + encodeURIComponent(userId));
      if (!res.ok) throw new Error('server error');
      var entries = await res.json();

      var todayEntry = null;
      for (var i = entries.length - 1; i >= 0; i--) {
        if (entries[i].recorded_date === today) { todayEntry = entries[i]; break; }
      }

      if (!todayEntry) {
        setText('card-weight-value', '—');
        setText('card-weight-sub', 'Not logged today');
        setClass('card-weight-sub', 'muted');
        return;
      }

      setText('card-weight-value', todayEntry.weight_kg + ' kg');

      // Last week's average (7 days ago up to yesterday)
      var yesterday = new Date();
      yesterday.setDate(yesterday.getDate() - 1);
      var yesterdayStr = yesterday.toISOString().slice(0, 10);
      var lastWeekEntries = entries.filter(function (e) {
        return e.recorded_date >= lastWeekStart && e.recorded_date <= yesterdayStr;
      });

      if (lastWeekEntries.length === 0) {
        setText('card-weight-sub', 'No prior data');
        setClass('card-weight-sub', 'muted');
        return;
      }

      var avg = lastWeekEntries.reduce(function (s, e) { return s + e.weight_kg; }, 0) / lastWeekEntries.length;
      var diff = todayEntry.weight_kg - avg;
      var sign = diff > 0 ? '▲' : '▼';
      var cls = diff > 0 ? 'pending' : 'done';
      if (Math.abs(diff) < 0.05) { sign = '—'; cls = 'muted'; }
      setText('card-weight-sub', sign + ' ' + Math.abs(diff).toFixed(1) + ' kg vs last week avg');
      setClass('card-weight-sub', cls);
    } catch (e) {
      setText('card-weight-value', '—');
      setText('card-weight-sub', 'Unable to load');
      setClass('card-weight-sub', 'muted');
    }
  }

  async function loadHabitsCard(userId) {
    var today = todayISO();
    try {
      var [habitsRes, logsRes] = await Promise.all([
        fetch('/api/habits?user_id=' + encodeURIComponent(userId)),
        fetch('/api/habits/logs?user_id=' + encodeURIComponent(userId) + '&from=' + today + '&to=' + today),
      ]);
      if (!habitsRes.ok || !logsRes.ok) throw new Error('server error');
      var habits = await habitsRes.json();
      var logs = await logsRes.json();

      var total = habits.length;
      var done = logs.length;
      var pending = total - done;

      setText('card-habits-value', done + ' / ' + total);

      if (total === 0) {
        setText('card-habits-sub', 'No habits yet');
        setClass('card-habits-sub', 'muted');
      } else if (pending === 0) {
        setText('card-habits-sub', 'All done today');
        setClass('card-habits-sub', 'done');
      } else {
        setText('card-habits-sub', pending + ' pending today');
        setClass('card-habits-sub', 'pending');
      }
    } catch (e) {
      setText('card-habits-value', '—');
      setText('card-habits-sub', 'Unable to load');
      setClass('card-habits-sub', 'muted');
    }
  }

  async function loadTrainingCard(userId) {
    var today = todayISO();
    try {
      var res = await fetch(
        '/api/workouts?user_id=' + encodeURIComponent(userId) + '&from=' + today + '&to=' + today
      );
      if (!res.ok) throw new Error('server error');
      var workouts = await res.json();

      if (workouts.length === 0) {
        setText('card-training-value', 'Rest day');
        setText('card-training-sub', '');
        setClass('card-training-sub', 'muted');
        return;
      }

      var w = workouts[0];
      // Fetch full workout to compute duration from exercises
      var detailRes = await fetch('/api/workouts/' + encodeURIComponent(w.id));
      var detail = detailRes.ok ? await detailRes.json() : null;

      var totalMin = 0;
      if (detail && detail.exercises) {
        detail.exercises.forEach(function (ex) {
          totalMin += parseDurationMin(ex.duration);
        });
      }

      var label = w.name || w.workout_type;
      setText('card-training-value', label);
      if (totalMin > 0) {
        setText('card-training-sub', totalMin + ' min');
        setClass('card-training-sub', '');
      } else {
        setText('card-training-sub', w.workout_type);
        setClass('card-training-sub', 'muted');
      }
    } catch (e) {
      setText('card-training-value', '—');
      setText('card-training-sub', 'Unable to load');
      setClass('card-training-sub', 'muted');
    }
  }

  async function loadStreakCard(userId) {
    try {
      var res = await fetch('/api/stats/active-streak?user_id=' + encodeURIComponent(userId));
      if (!res.ok) throw new Error('server error');
      var data = await res.json();
      setText('card-streak-value', '🔥 ' + data.current_streak);
      if (data.current_streak >= 7) {
        setText('card-streak-sub', 'Best ever: ' + data.longest_streak);
        setClass('card-streak-sub', '');
      } else {
        setText('card-streak-sub', 'consecutive days');
        setClass('card-streak-sub', 'muted');
      }
    } catch (e) {
      setText('card-streak-value', '🔥 0');
      setText('card-streak-sub', 'Unable to load');
      setClass('card-streak-sub', 'muted');
    }
  }

  function refreshCards(userId) {
    loadWeightCard(userId);
    loadHabitsCard(userId);
    loadTrainingCard(userId);
    loadStreakCard(userId);
  }

  // ── Mini weight chart ──────────────────────────────────────────────────────

  var miniWeightChart = null;

  function last14Days() {
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 13);
    return cutoff.toISOString().slice(0, 10);
  }

  async function loadWeightSection(userId) {
    var body = document.getElementById('section-weight-body');
    if (!body) return;
    try {
      var res = await fetch('/api/weight?user_id=' + encodeURIComponent(userId));
      if (!res.ok) throw new Error('server error');
      var entries = await res.json();

      var cutoff = last14Days();
      var visible = entries
        .filter(function (e) { return e.recorded_date >= cutoff; })
        .sort(function (a, b) { return a.recorded_date.localeCompare(b.recorded_date); });

      if (visible.length === 0) {
        body.innerHTML = '<p class="dash-section-empty">No weight entries yet</p>';
        if (miniWeightChart) { miniWeightChart.destroy(); miniWeightChart = null; }
        return;
      }

      // Restore canvas if it was replaced by an empty-state message
      if (!body.querySelector('#mini-weight-chart')) {
        body.innerHTML = '<div class="mini-chart-wrap"><canvas id="mini-weight-chart"></canvas></div>';
      }

      var labels = visible.map(function (e) { return e.recorded_date; });
      var weights = visible.map(function (e) { return e.weight_kg; });
      var allVals = weights;
      var padding = 0.3;
      var minY = Math.min.apply(null, allVals) - padding;
      var maxY = Math.max.apply(null, allVals) + padding;

      if (miniWeightChart) {
        miniWeightChart.data.labels = labels;
        miniWeightChart.data.datasets[0].data = weights;
        miniWeightChart.options.scales.y.min = minY;
        miniWeightChart.options.scales.y.max = maxY;
        miniWeightChart.update();
        return;
      }

      var ctx = document.getElementById('mini-weight-chart').getContext('2d');
      miniWeightChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            data: weights,
            showLine: false,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBackgroundColor: '#9ca3af',
            pointBorderColor: '#9ca3af',
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          scales: {
            x: { display: false },
            y: { display: false, min: minY, max: maxY },
          },
          animation: false,
        },
      });
    } catch (e) {
      body.innerHTML = '<p class="dash-section-empty">Unable to load weight data</p>';
    }
  }

  // ── Habits today section ───────────────────────────────────────────────────

  async function loadHabitsSection(userId) {
    var list = document.getElementById('home-habit-list');
    if (!list) return;
    var today = todayISO();
    try {
      var results = await Promise.all([
        fetch('/api/habits?user_id=' + encodeURIComponent(userId)),
        fetch('/api/habits/logs?user_id=' + encodeURIComponent(userId) + '&from=' + today + '&to=' + today),
      ]);
      if (!results[0].ok || !results[1].ok) throw new Error('server error');
      var habits = await results[0].json();
      var logs = await results[1].json();

      list.innerHTML = '';
      if (habits.length === 0) {
        list.innerHTML = '<li class="dash-section-empty">No habits yet</li>';
        return;
      }

      habits.forEach(function (habit) {
        var done = logs.some(function (l) { return l.habit_id === habit.id; });
        var li = document.createElement('li');
        li.className = 'home-habit-row';
        li.id = 'home-habit-row-' + habit.id;

        var cb = document.createElement('span');
        cb.className = 'home-habit-cb' + (done ? ' checked' : '');
        cb.setAttribute('aria-label', done ? 'Completed' : 'Not completed');
        if (done) {
          cb.innerHTML = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        }

        var name = document.createElement('span');
        name.className = 'home-habit-name';
        name.textContent = habit.name;

        var streak = document.createElement('span');
        streak.className = 'home-habit-streak';
        streak.textContent = '…';

        var rate = document.createElement('span');
        rate.className = 'home-habit-rate';
        rate.textContent = '';

        li.appendChild(cb);
        li.appendChild(name);
        li.appendChild(streak);
        li.appendChild(rate);
        list.appendChild(li);

        // Load stats async
        fetch('/api/habits/stats?user_id=' + encodeURIComponent(userId) + '&habit_id=' + encodeURIComponent(habit.id) + '&days=30')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            var row = document.getElementById('home-habit-row-' + habit.id);
            if (!row) return;
            var sEl = row.querySelector('.home-habit-streak');
            var rEl = row.querySelector('.home-habit-rate');
            if (data && data.streak > 0) {
              sEl.textContent = '🔥 ' + data.streak + ' day' + (data.streak === 1 ? '' : 's');
            } else {
              sEl.textContent = '—';
            }
            if (data && data.days_completed > 0) {
              rEl.textContent = Math.round(data.completion_rate * 100) + '%';
            } else {
              rEl.textContent = '';
            }
          })
          .catch(function () {
            var row = document.getElementById('home-habit-row-' + habit.id);
            if (row) row.querySelector('.home-habit-streak').textContent = '';
          });
      });
    } catch (e) {
      list.innerHTML = '<li class="dash-section-empty">Unable to load habits</li>';
    }
  }

  // ── Recent training section ────────────────────────────────────────────────

  function relativeDate(dateStr) {
    var today = todayISO();
    if (dateStr === today) return 'Today';
    var yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    if (dateStr === yesterday.toISOString().slice(0, 10)) return 'Yesterday';
    var d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function trainingIcon(workoutType) {
    var cardioTypes = ['run', 'cardio', 'cycling', 'swimming', 'walking', 'hike', 'hiking', 'bike'];
    var t = (workoutType || '').toLowerCase();
    for (var i = 0; i < cardioTypes.length; i++) {
      if (t.indexOf(cardioTypes[i]) !== -1) return '🏃';
    }
    return '🏋️';
  }

  async function loadTrainingSection(userId) {
    var list = document.getElementById('home-training-list');
    if (!list) return;

    var oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    var fromStr = oneYearAgo.toISOString().slice(0, 10);
    var toStr = todayISO();

    try {
      var res = await fetch(
        '/api/workouts?user_id=' + encodeURIComponent(userId) +
        '&from=' + fromStr + '&to=' + toStr
      );
      if (!res.ok) throw new Error('server error');
      var workouts = await res.json();

      list.innerHTML = '';
      if (workouts.length === 0) {
        list.innerHTML = '<li class="dash-section-empty">No training yet</li>';
        return;
      }

      var recent = workouts.slice(0, 7);

      // Fetch details for all 7 in parallel to get duration + rpe
      var details = await Promise.all(recent.map(function (w) {
        return fetch('/api/workouts/' + encodeURIComponent(w.id))
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; });
      }));

      recent.forEach(function (w, i) {
        var detail = details[i];
        var totalMin = 0;
        var maxRpe = null;
        if (detail && detail.exercises) {
          detail.exercises.forEach(function (ex) {
            totalMin += parseDurationMin(ex.duration);
            if (ex.rpe !== null && ex.rpe !== undefined) {
              maxRpe = maxRpe === null ? ex.rpe : Math.max(maxRpe, ex.rpe);
            }
          });
        }

        var li = document.createElement('li');
        li.className = 'home-training-row';

        var icon = document.createElement('span');
        icon.className = 'home-training-icon';
        icon.textContent = trainingIcon(w.workout_type);

        var name = document.createElement('span');
        name.className = 'home-training-name';
        name.textContent = w.name || w.workout_type;

        var dateEl = document.createElement('span');
        dateEl.className = 'home-training-date';
        dateEl.textContent = relativeDate(w.workout_date);

        var meta = document.createElement('span');
        meta.className = 'home-training-meta';
        var metaParts = [];
        if (totalMin > 0) metaParts.push(totalMin + ' min');
        if (maxRpe !== null) metaParts.push('RPE ' + maxRpe);
        meta.textContent = metaParts.join(' · ');

        li.appendChild(icon);
        li.appendChild(name);
        li.appendChild(dateEl);
        if (metaParts.length > 0) li.appendChild(meta);
        list.appendChild(li);
      });
    } catch (e) {
      list.innerHTML = '<li class="dash-section-empty">Unable to load training data</li>';
    }
  }

  // ── Wiring ─────────────────────────────────────────────────────────────────

  function refreshSections(userId) {
    loadWeightSection(userId);
    loadHabitsSection(userId);
    loadTrainingSection(userId);
  }

  setTodayLabel();

  window.addEventListener('userReady', function (e) {
    refreshCards(e.detail.userId);
    refreshSections(e.detail.userId);
  });

  window.addEventListener('userChanged', function (e) {
    refreshCards(e.detail.userId);
    refreshSections(e.detail.userId);
  });

  // Refresh when returning to tab (handles cross-tab entry submissions)
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
      if (uid) { refreshCards(uid); refreshSections(uid); }
    }
  });
}());
