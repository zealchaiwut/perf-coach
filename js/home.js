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

  // ── Sleep / Energy / Mood 7-day digest chart ──────────────────────────────

  var trendChart = null;

  async function loadTrendChart(userId) {
    var body = document.getElementById('section-trend-body');
    if (!body) return;
    try {
      var res = await fetch(
        '/trends/summary?user_id=' + encodeURIComponent(userId) + '&range=7d'
      );
      if (!res.ok) throw new Error('server error');
      var summary = await res.json();

      var labels = summary.sleep.series.map(function (d) {
        var dt = new Date(d.date + 'T00:00:00');
        return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' });
      });
      var sleepData = summary.sleep.series.map(function (d) { return d.hours; });
      var energyData = summary.energy.series.map(function (d) { return d.value; });
      var moodData = summary.mood.series.map(function (d) { return d.value; });

      if (!body.querySelector('#trend-chart')) {
        body.innerHTML = '<div class="trend-chart-wrap"><canvas id="trend-chart"></canvas></div>';
      }

      if (trendChart) {
        trendChart.data.labels = labels;
        trendChart.data.datasets[0].data = sleepData;
        trendChart.data.datasets[1].data = energyData;
        trendChart.data.datasets[2].data = moodData;
        trendChart.update();
        return;
      }

      var ctx = document.getElementById('trend-chart').getContext('2d');
      trendChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'Sleep (h)',
              data: sleepData,
              yAxisID: 'ySleep',
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99,102,241,0.08)',
              borderWidth: 2,
              pointRadius: 3,
              spanGaps: false,
              fill: false,
              tension: 0.3,
            },
            {
              label: 'Energy',
              data: energyData,
              yAxisID: 'yScore',
              borderColor: '#f59e0b',
              backgroundColor: 'rgba(245,158,11,0.08)',
              borderWidth: 2,
              pointRadius: 3,
              spanGaps: false,
              fill: false,
              tension: 0.3,
            },
            {
              label: 'Mood',
              data: moodData,
              yAxisID: 'yScore',
              borderColor: '#10b981',
              backgroundColor: 'rgba(16,185,129,0.08)',
              borderWidth: 2,
              pointRadius: 3,
              spanGaps: false,
              fill: false,
              tension: 0.3,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: { font: { size: 11 }, boxWidth: 12, padding: 8 },
            },
          },
          scales: {
            x: {
              ticks: { font: { size: 10 }, maxRotation: 0 },
              grid: { display: false },
            },
            ySleep: {
              type: 'linear',
              position: 'left',
              min: 0,
              max: 12,
              title: { display: true, text: 'Sleep (h)', font: { size: 10 } },
              ticks: { font: { size: 10 }, stepSize: 3 },
              grid: { color: 'rgba(0,0,0,0.06)' },
            },
            yScore: {
              type: 'linear',
              position: 'right',
              min: 0,
              max: 5,
              title: { display: true, text: '1–5', font: { size: 10 } },
              ticks: { font: { size: 10 }, stepSize: 1 },
              grid: { display: false },
            },
          },
          animation: false,
        },
      });
    } catch (e) {
      body.innerHTML = '<p class="dash-section-empty">Unable to load trend data</p>';
    }
  }

  // ── Today's check-in card ──────────────────────────────────────────────────

  var CHECKIN_COLLAPSE_KEY = 'perf-coach.checkin-collapsed';

  function pillGroupValue(groupId) {
    var active = document.querySelector('#' + groupId + ' .pill.active');
    return active ? parseInt(active.getAttribute('data-val'), 10) : null;
  }

  function setPillGroupValue(groupId, val) {
    var pills = document.querySelectorAll('#' + groupId + ' .pill');
    pills.forEach(function (p) {
      if (parseInt(p.getAttribute('data-val'), 10) === val) {
        p.classList.add('active');
      } else {
        p.classList.remove('active');
      }
    });
  }

  function wireUpPillGroups() {
    ['pills-sleep-quality', 'pills-energy', 'pills-mood'].forEach(function (gid) {
      var group = document.getElementById(gid);
      if (!group) return;
      group.querySelectorAll('.pill').forEach(function (p) {
        p.addEventListener('click', function () {
          var wasActive = p.classList.contains('active');
          group.querySelectorAll('.pill').forEach(function (q) { q.classList.remove('active'); });
          if (!wasActive) p.classList.add('active');
        });
      });
    });
  }

  function getCheckinInputs() {
    var rhr = document.getElementById('checkin-rhr');
    var hrv = document.getElementById('checkin-hrv');
    var sleep = document.getElementById('checkin-sleep');
    var notes = document.getElementById('checkin-notes');
    return {
      resting_hr: rhr && rhr.value !== '' ? parseInt(rhr.value, 10) : null,
      hrv: hrv && hrv.value !== '' ? parseInt(hrv.value, 10) : null,
      sleep_hours: sleep && sleep.value !== '' ? parseFloat(sleep.value) : null,
      sleep_quality: pillGroupValue('pills-sleep-quality'),
      energy: pillGroupValue('pills-energy'),
      mood: pillGroupValue('pills-mood'),
      notes: notes && notes.value.trim() !== '' ? notes.value.trim() : null,
    };
  }

  function fillCheckinForm(data) {
    var rhr = document.getElementById('checkin-rhr');
    var hrv = document.getElementById('checkin-hrv');
    var sleep = document.getElementById('checkin-sleep');
    var notes = document.getElementById('checkin-notes');
    if (rhr) rhr.value = data.resting_hr !== null && data.resting_hr !== undefined ? data.resting_hr : '';
    if (hrv) hrv.value = data.hrv !== null && data.hrv !== undefined ? data.hrv : '';
    if (sleep) sleep.value = data.sleep_hours !== null && data.sleep_hours !== undefined ? data.sleep_hours : '';
    if (notes) notes.value = data.notes || '';
    setPillGroupValue('pills-sleep-quality', data.sleep_quality);
    setPillGroupValue('pills-energy', data.energy);
    setPillGroupValue('pills-mood', data.mood);
  }

  function setCheckinStatus(savedText, errorText) {
    var savedEl = document.getElementById('checkin-saved');
    var errorEl = document.getElementById('checkin-error');
    if (savedEl) savedEl.textContent = savedText || '';
    if (errorEl) errorEl.textContent = errorText || '';
  }

  function applyCheckinCollapse() {
    var body = document.getElementById('checkin-body');
    var toggle = document.getElementById('checkin-toggle');
    var collapsed = localStorage.getItem(CHECKIN_COLLAPSE_KEY) === '1';
    if (!body || !toggle) return;
    if (collapsed) {
      body.hidden = true;
      toggle.classList.add('collapsed');
    } else {
      body.hidden = false;
      toggle.classList.remove('collapsed');
    }
  }

  function initCheckinToggle() {
    var toggle = document.getElementById('checkin-toggle');
    if (!toggle) return;
    applyCheckinCollapse();
    toggle.addEventListener('click', function () {
      var body = document.getElementById('checkin-body');
      var isCollapsed = body && body.hidden;
      if (isCollapsed) {
        body.hidden = false;
        toggle.classList.remove('collapsed');
        localStorage.setItem(CHECKIN_COLLAPSE_KEY, '0');
      } else {
        body.hidden = true;
        toggle.classList.add('collapsed');
        localStorage.setItem(CHECKIN_COLLAPSE_KEY, '1');
      }
    });
  }

  async function loadCheckinSection(userId) {
    var today = todayISO();
    try {
      var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + today);
      if (res.ok) {
        var data = await res.json();
        fillCheckinForm(data);
      }
      // 404 is expected if no row yet — leave form empty
    } catch (e) {
      // Network failure — leave form empty, don't block UI
    }
  }

  var _checkinUserId = null;

  function initCheckinSave() {
    var btn = document.getElementById('checkin-save');
    if (!btn) return;
    btn.addEventListener('click', async function () {
      if (!_checkinUserId) return;
      var today = todayISO();
      var payload = getCheckinInputs();
      btn.disabled = true;
      setCheckinStatus('', '');
      try {
        var res = await fetch(
          '/api/daily-metrics/' + encodeURIComponent(_checkinUserId) + '/' + today,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }
        );
        if (res.ok) {
          var saved = new Date();
          var hh = String(saved.getHours()).padStart(2, '0');
          var mm = String(saved.getMinutes()).padStart(2, '0');
          setCheckinStatus('Saved at ' + hh + ':' + mm, '');
          setTimeout(function () { setCheckinStatus('', ''); }, 3000);
          loadTrendChart(_checkinUserId);
        } else {
          var errBody;
          try { errBody = await res.json(); } catch (_) { errBody = {}; }
          var msg = (errBody && errBody.detail)
            ? (typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail))
            : ('Save failed (' + res.status + ')');
          setCheckinStatus('', msg);
        }
      } catch (e) {
        setCheckinStatus('', 'Network error — please try again');
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ── Weekly digest card ─────────────────────────────────────────────────────

  function digestCacheKey(userId) {
    return 'perf-coach.weekly-digest.' + (userId || 'anon');
  }

  function getDigestCache(userId) {
    try {
      var cached = JSON.parse(localStorage.getItem(digestCacheKey(userId)));
      if (cached && cached.date === todayISO()) return cached.data;
    } catch (_) {}
    return null;
  }

  function setDigestCache(userId, data) {
    try {
      localStorage.setItem(digestCacheKey(userId), JSON.stringify({ date: todayISO(), data: data }));
    } catch (_) {}
  }

  function _daysWithData(payload) {
    if (!payload || !payload.readiness || !payload.readiness.series) return 0;
    var count = 0;
    payload.readiness.series.forEach(function (s) { if (s.score != null) count++; });
    return count;
  }

  function _parseDeltaInt(str) {
    if (str == null) return null;
    var n = parseInt(str, 10);
    return isNaN(n) ? null : n;
  }

  function _parseDeltaFloat(str) {
    if (str == null) return null;
    var n = parseFloat(String(str).replace(/[^0-9.\-+]/g, ''));
    return isNaN(n) ? null : n;
  }

  function _parseDeltaPct(str) {
    if (str == null) return null;
    var n = parseFloat(String(str).replace('%', ''));
    return isNaN(n) ? null : n;
  }

  function _peakTssDay(series) {
    if (!series || !series.length) return null;
    var maxVal = -Infinity;
    var maxDate = null;
    series.forEach(function (s) {
      if (s.value != null && s.value > maxVal) { maxVal = s.value; maxDate = s.date; }
    });
    if (!maxDate) return null;
    return new Date(maxDate + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long' });
  }

  function _hrvTrailingBelowCount(series, avg) {
    if (!series || !series.length || avg == null) return 0;
    var count = 0;
    for (var i = series.length - 1; i >= 0; i--) {
      if (series[i].value != null && series[i].value < avg) { count++; } else { break; }
    }
    return count;
  }

  // Minimum absolute delta required before a line is shown
  var DIGEST_MIN_DELTA = { readiness: 2, sleep: 0.3, hrv: 3, tss_pct: 15 };

  function buildDigestLines(payload) {
    var lines = [];
    var deltas = payload.deltas || {};
    var d;

    // Avg readiness with week-over-week delta
    if (payload.readiness && payload.readiness.avg != null) {
      d = _parseDeltaInt(deltas.readiness);
      if (d != null && Math.abs(d) >= DIGEST_MIN_DELTA.readiness) {
        lines.push('Avg readiness ' + Math.round(payload.readiness.avg) + ' (' + (d > 0 ? '+' : '') + d + ' vs last week)');
      }
    }

    // Sleep change in hours ("Sleep up 0.4h" / "Sleep down 0.4h")
    if (payload.sleep && payload.sleep.avg_hours != null) {
      d = _parseDeltaFloat(deltas.sleep);
      if (d != null && Math.abs(d) >= DIGEST_MIN_DELTA.sleep) {
        var sleepDir = d > 0 ? 'up' : 'down';
        lines.push('Sleep ' + sleepDir + ' ' + Math.abs(d).toFixed(1) + 'h');
      }
    }

    // TSS % change with peak day called out
    if (payload.tss && payload.tss.series) {
      d = _parseDeltaPct(deltas.tss);
      if (d != null && Math.abs(d) >= DIGEST_MIN_DELTA.tss_pct) {
        var tssDir = d > 0 ? 'up' : 'down';
        var tssPeak = _peakTssDay(payload.tss.series);
        var tssLine = 'TSS ' + tssDir + ' ' + Math.abs(Math.round(d)) + '%';
        if (tssPeak) tssLine += ' — biggest day ' + tssPeak;
        lines.push(tssLine);
      }
    }

    // HRV trending below baseline last N days
    if (payload.hrv && payload.hrv.avg != null && payload.hrv.series) {
      d = _parseDeltaInt(deltas.hrv);
      if (d != null && d <= -DIGEST_MIN_DELTA.hrv) {
        var belowCount = _hrvTrailingBelowCount(payload.hrv.series, payload.hrv.avg);
        if (belowCount >= 2) {
          lines.push('HRV trending below baseline last ' + belowCount + ' day' + (belowCount === 1 ? '' : 's'));
        }
      }
    }

    return lines.slice(0, 5);
  }

  function renderDigestSection(payload) {
    var body = document.getElementById('section-digest-body');
    if (!body) return;

    if (!payload || _daysWithData(payload) < 7) {
      body.innerHTML = '<p class="digest-empty">Not enough data yet — keep logging.</p>';
      return;
    }

    var lines = buildDigestLines(payload);

    if (lines.length === 0) {
      body.innerHTML = '<p class="digest-empty">No notable changes this week</p>';
      return;
    }

    var ul = document.createElement('ul');
    ul.className = 'digest-lines';
    lines.forEach(function (text) {
      var li = document.createElement('li');
      li.className = 'digest-line';
      li.textContent = text;
      ul.appendChild(li);
    });
    body.innerHTML = '';
    body.appendChild(ul);
  }

  async function loadWeeklyDigestSection(userId) {
    var cached = getDigestCache(userId);
    if (cached) {
      renderDigestSection(cached);
      return;
    }

    var data = null;
    try {
      var res = await fetch('/trends/summary?user_id=' + encodeURIComponent(userId) + '&range=7d');
      if (!res.ok) throw new Error('server error');
      data = await res.json();
    } catch (_) {
      data = (typeof MOCK_TRENDS_SUMMARY !== 'undefined') ? MOCK_TRENDS_SUMMARY : null;
    }

    setDigestCache(userId, data);
    renderDigestSection(data);
  }

  // ── Readiness card ────────────────────────────────────────────────────────

  var READINESS_THRESHOLDS = { red: 50, amber: 70 };

  var READINESS_LABELS = {
    green: 'Green - go',
    amber: 'Amber - moderate',
    red:   'Red - back off',
  };

  var READINESS_INTERP = {
    green: "You're well-recovered and ready to perform.",
    amber: 'Keep it moderate — listen to your body.',
    red:   'Your body needs extra recovery today.',
  };

  var READINESS_COMP_EXPL = {
    HRV:    'Heart rate variability reflects autonomic recovery.',
    RHR:    'Elevated resting HR signals residual fatigue.',
    Sleep:  'Sleep quality and duration drive physical restoration.',
    Energy: 'Subjective energy level shapes workout quality.',
  };

  function readinessBand(score) {
    if (score == null) return 'neutral';
    if (score < READINESS_THRESHOLDS.red)    return 'red';
    if (score <= READINESS_THRESHOLDS.amber) return 'amber';
    return 'green';
  }

  function fmtAbsDelta(val, unit) {
    if (val == null) return null;
    var rounded = Math.round(val * 10) / 10;
    var sign = rounded >= 0 ? '+' : '';
    var num = Number.isInteger(rounded) ? rounded : rounded.toFixed(1);
    return sign + num + (unit ? ' ' + unit : '');
  }

  function deltaClass(dispDelta) {
    if (dispDelta == null) return 'neu';
    if (Math.abs(dispDelta) < 0.5) return 'neu';
    return dispDelta > 0 ? 'pos' : 'neg';
  }

  function buildInterpretation(band, components) {
    var hrv   = components.find(function (c) { return c.key === 'hrv'; });
    var rhr   = components.find(function (c) { return c.key === 'rhr'; });
    var sleep = components.find(function (c) { return c.key === 'sleep'; });
    var en    = components.find(function (c) { return c.key === 'energy'; });

    var hrvD   = hrv   && !hrv.missing   ? hrv.dispDelta   : null;
    var rhrD   = rhr   && !rhr.missing   ? rhr.dispDelta   : null;
    var sleepD = sleep && !sleep.missing ? sleep.dispDelta : null;
    var enD    = en    && !en.missing    ? en.dispDelta    : null;

    if (band === 'green') {
      if (hrvD   != null && hrvD   >= 5)    return 'HRV is up — autonomic recovery looks strong.';
      if (sleepD != null && sleepD >= 0.5)  return 'Good sleep last night — body is primed to go.';
      if (enD    != null && enD    >= 1)    return 'Energy is high — a great time for a quality session.';
      return "You're well-recovered and ready to perform.";
    }
    if (band === 'amber') {
      if (sleepD != null && sleepD < -0.5)  return 'Sleep was below your average — moderate intensity is wise.';
      if (rhrD   != null && rhrD   < -1)    return 'Resting HR is slightly elevated — ease into today.';
      if (hrvD   != null && hrvD   < -3)    return 'HRV is a touch low — a moderate session makes sense.';
      return 'Keep it moderate — listen to your body today.';
    }
    if (band === 'red') {
      if (hrvD   != null && hrvD   < -8)    return 'HRV is significantly suppressed — prioritise rest today.';
      if (sleepD != null && sleepD < -1)    return 'Sleep deficit detected — a full rest day is recommended.';
      if (rhrD   != null && rhrD   < -2)    return 'Resting HR is elevated — your body is still recovering.';
      return 'Your body needs extra recovery today.';
    }
    return '';
  }

  function applyReadinessCard(readiness, metrics, trends) {
    var card     = document.getElementById('readiness-card');
    var scoreEl  = document.getElementById('readiness-score');
    var pillEl   = document.getElementById('readiness-pill');
    var interpEl = document.getElementById('readiness-interp');
    var chipsEl  = document.getElementById('readiness-chips');
    var bdEl     = document.getElementById('readiness-breakdown');
    if (!card) return;

    var score = readiness ? Math.round(readiness.score) : null;
    var band  = readinessBand(score);

    card.classList.remove('readiness-card--green', 'readiness-card--amber', 'readiness-card--red');
    if (band !== 'neutral') card.classList.add('readiness-card--' + band);

    scoreEl.textContent = score != null ? score : '—';
    scoreEl.className = 'readiness-score' + (band !== 'neutral' ? ' readiness-score--' + band : '');

    pillEl.textContent = band !== 'neutral' ? READINESS_LABELS[band] : '—';
    pillEl.className = 'readiness-pill' + (band !== 'neutral' ? ' readiness-pill--' + band : '');

    var missing = (readiness && readiness.missing_data) || {};
    var todayHrv    = metrics ? metrics.hrv        : null;
    var todayRhr    = metrics ? metrics.resting_hr : null;
    var todaySleep  = metrics ? metrics.sleep_hours : null;
    var todayEnergy = metrics ? metrics.energy      : null;
    var baseHrv     = trends && trends.hrv    ? trends.hrv.avg         : null;
    var baseRhr     = trends && trends.rhr    ? trends.rhr.avg         : null;
    var baseSleep   = trends && trends.sleep  ? trends.sleep.avg_hours : null;
    var baseEnergy  = trends && trends.energy ? trends.energy.avg      : null;

    function absDelta(a, b) {
      return (a == null || b == null) ? null : a - b;
    }

    var components = [
      {
        key: 'hrv',    label: 'HRV',    missing: missing.hrv,
        value: todayHrv,    unit: 'ms',  baseline: baseHrv,    baseUnit: 'ms',
        deltaUnit: 'ms',
        rawDelta:  absDelta(todayHrv, baseHrv),
        dispDelta: absDelta(todayHrv, baseHrv),
      },
      {
        key: 'rhr',    label: 'RHR',    missing: missing.rhr,
        value: todayRhr,    unit: 'bpm', baseline: baseRhr,    baseUnit: 'bpm',
        deltaUnit: 'bpm',
        rawDelta:  absDelta(todayRhr, baseRhr),
        // lower RHR is better — invert sign for colour class only
        dispDelta: absDelta(baseRhr, todayRhr),
      },
      {
        key: 'sleep',  label: 'Sleep',  missing: missing.sleep,
        value: todaySleep,  unit: 'h',   baseline: baseSleep,  baseUnit: 'h',
        deltaUnit: 'h',
        rawDelta:  absDelta(todaySleep, baseSleep),
        dispDelta: absDelta(todaySleep, baseSleep),
      },
      {
        key: 'energy', label: 'Energy', missing: missing.energy,
        value: todayEnergy, unit: '/5',  baseline: baseEnergy, baseUnit: '/5',
        deltaUnit: '',
        rawDelta:  absDelta(todayEnergy, baseEnergy),
        dispDelta: absDelta(todayEnergy, baseEnergy),
      },
    ];

    interpEl.textContent = band !== 'neutral' ? buildInterpretation(band, components) : '';

    // Chips
    chipsEl.innerHTML = '';
    components.forEach(function (c) {
      var chip = document.createElement('span');
      chip.className = 'readiness-chip';
      var lbl = document.createElement('span');
      lbl.className = 'readiness-chip-label';
      lbl.textContent = c.label;
      var dlt = document.createElement('span');
      dlt.className = 'readiness-chip-delta';
      if (c.missing || c.value == null) {
        dlt.textContent = '—';
        dlt.classList.add('readiness-chip-delta--neu');
      } else {
        var dStr = c.rawDelta != null ? fmtAbsDelta(c.rawDelta, c.deltaUnit) : '—';
        dlt.textContent = dStr;
        dlt.classList.add('readiness-chip-delta--' + deltaClass(c.dispDelta));
      }
      chip.appendChild(lbl);
      chip.appendChild(dlt);
      chipsEl.appendChild(chip);
    });

    // Breakdown
    bdEl.innerHTML = '';
    components.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'readiness-breakdown-row';

      var hdr = document.createElement('div');
      hdr.className = 'readiness-breakdown-header';

      var name = document.createElement('span');
      name.className = 'readiness-breakdown-name';
      name.textContent = c.label;

      var valEl = document.createElement('span');
      valEl.className = 'readiness-breakdown-value';
      valEl.textContent = (c.missing || c.value == null)
        ? '—'
        : (Number.isInteger(c.value) ? c.value : Number(c.value).toFixed(1)) + ' ' + c.unit;

      var blEl = document.createElement('span');
      blEl.className = 'readiness-breakdown-baseline';
      blEl.textContent = c.baseline != null
        ? 'baseline ' + (Number.isInteger(c.baseline) ? Math.round(c.baseline) : Number(c.baseline).toFixed(1)) + ' ' + c.baseUnit
        : '';

      var dltEl = document.createElement('span');
      dltEl.className = 'readiness-breakdown-delta';
      if (c.missing || c.value == null || c.rawDelta == null) {
        dltEl.textContent = '—';
        dltEl.style.color = '#aaa';
      } else {
        var dStr = fmtAbsDelta(c.rawDelta, c.deltaUnit);
        dltEl.textContent = dStr;
        var dc = deltaClass(c.dispDelta);
        dltEl.style.color = dc === 'pos' ? '#16a34a' : dc === 'neg' ? '#dc2626' : '#888';
      }

      hdr.appendChild(name);
      hdr.appendChild(valEl);
      hdr.appendChild(blEl);
      hdr.appendChild(dltEl);

      var expl = document.createElement('div');
      expl.className = 'readiness-breakdown-expl';
      expl.textContent = READINESS_COMP_EXPL[c.label] || '';

      row.appendChild(hdr);
      row.appendChild(expl);
      bdEl.appendChild(row);
    });
  }

  function initReadinessToggle() {
    var card = document.getElementById('readiness-card');
    if (!card) return;
    card.addEventListener('click', function () {
      var bd   = document.getElementById('readiness-breakdown');
      var icon = document.getElementById('readiness-expand-icon');
      if (!bd) return;
      var isOpen = !bd.hidden;
      bd.hidden = isOpen;
      if (icon) icon.classList.toggle('open', !isOpen);
      card.setAttribute('aria-expanded', String(!isOpen));
    });
  }

  async function loadReadinessCard(userId) {
    var today = todayISO();
    var readiness = null, metrics = null, trends = null;

    try {
      var [rRes, mRes, tRes] = await Promise.all([
        fetch('/api/readiness/today?user_id=' + encodeURIComponent(userId)),
        fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + today),
        fetch('/trends/summary?user_id=' + encodeURIComponent(userId) + '&range=7d'),
      ]);
      if (rRes.ok)  readiness = await rRes.json();
      if (mRes.ok)  metrics   = await mRes.json();
      if (tRes.ok)  trends    = await tRes.json();
    } catch (_) {}

    // Fall back to mock data when API is unavailable
    if (!readiness && typeof MOCK_READINESS_TODAY !== 'undefined') readiness = MOCK_READINESS_TODAY;
    if (!metrics   && typeof MOCK_DAILY_METRICS_TODAY !== 'undefined') metrics = MOCK_DAILY_METRICS_TODAY;
    if (!trends    && typeof MOCK_TRENDS_SUMMARY !== 'undefined')      trends  = MOCK_TRENDS_SUMMARY;

    applyReadinessCard(readiness, metrics, trends);
  }

  // ── Wiring ─────────────────────────────────────────────────────────────────

  function refreshSections(userId) {
    loadReadinessCard(userId);
    loadWeightSection(userId);
    loadHabitsSection(userId);
    loadTrainingSection(userId);
    loadCheckinSection(userId);
    loadTrendChart(userId);
    loadWeeklyDigestSection(userId);
  }

  setTodayLabel();
  wireUpPillGroups();
  initCheckinToggle();
  initCheckinSave();
  initReadinessToggle();

  window.addEventListener('userReady', function (e) {
    _checkinUserId = e.detail.userId;
    refreshCards(e.detail.userId);
    refreshSections(e.detail.userId);
  });

  window.addEventListener('userChanged', function (e) {
    _checkinUserId = e.detail.userId;
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
