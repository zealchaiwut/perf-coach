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

  setTodayLabel();

  window.addEventListener('userReady', function (e) {
    refreshCards(e.detail.userId);
  });

  window.addEventListener('userChanged', function (e) {
    refreshCards(e.detail.userId);
  });

  // Refresh when returning to tab (handles cross-tab entry submissions)
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      var uid = window.getCurrentUserId ? window.getCurrentUserId() : null;
      if (uid) refreshCards(uid);
    }
  });
}());
