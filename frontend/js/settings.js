(function () {
  var VALID_SECTIONS = ['profile', 'thresholds', 'personal-records', 'integrations', 'queue', 'about'];
  var DEFAULT_SECTION = 'profile';

  // ── Queue tab (Phase 3): the signed-in user's background jobs ──────────────
  var QUEUE_LABELS = {
    strava_sync: 'Strava sync',
    stryd_sync: 'Stryd sync',
    garmin_sync: 'Garmin sync',
    backfill: 'Performance backfill',
    banister_refit: 'Banister refit',
    precompute: 'Load recompute'
  };
  var queueLoaded = false;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function renderQueue(jobs) {
    var body = document.getElementById('queue-body');
    if (!body) return;
    if (!jobs || !jobs.length) {
      body.innerHTML = '<p class="queue-empty">No background jobs yet. Syncs and recomputes will appear here.</p>';
      return;
    }
    var rows = jobs.map(function (j) {
      var label = QUEUE_LABELS[j.job_type] || j.job_type;
      var status = j.status || 'queued';
      var attempts = (j.attempts && j.max_attempts) ? (j.attempts + '/' + j.max_attempts) : '';
      var err = (status === 'failed' && j.error) ? '<div class="queue-error">' + esc(j.error) + '</div>' : '';
      return (
        '<li class="queue-item">' +
          '<div class="queue-item-main">' +
            '<span class="queue-label">' + esc(label) + '</span>' +
            '<span class="queue-status queue-status--' + esc(status) + '">' + esc(status) + '</span>' +
          '</div>' +
          '<div class="queue-item-meta">' +
            '<span>Queued ' + esc(fmtTime(j.created_at)) + '</span>' +
            (j.finished_at ? '<span>Finished ' + esc(fmtTime(j.finished_at)) + '</span>' : '') +
            (attempts ? '<span>Attempt ' + esc(attempts) + '</span>' : '') +
          '</div>' + err +
        '</li>'
      );
    }).join('');
    body.innerHTML = '<ul class="queue-list">' + rows + '</ul>';
  }

  function loadQueue() {
    var body = document.getElementById('queue-body');
    var stamp = document.getElementById('queue-updated');
    if (body) body.innerHTML = '<p class="queue-empty">Loading…</p>';
    return fetch('/api/queue', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { jobs: [] }; })
      .then(function (data) {
        renderQueue(data.jobs || []);
        queueLoaded = true;
        if (stamp) stamp.textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      })
      .catch(function () {
        if (body) body.innerHTML = '<p class="queue-empty">Could not load the queue. Try Refresh.</p>';
      });
  }

  function activateSection(sectionId) {
    if (VALID_SECTIONS.indexOf(sectionId) === -1) {
      sectionId = DEFAULT_SECTION;
    }

    document.querySelectorAll('.settings-section').forEach(function (el) {
      el.classList.remove('active');
      el.style.display = 'none';
    });

    document.querySelectorAll('.settings-nav-item').forEach(function (el) {
      el.classList.remove('active');
      el.setAttribute('aria-selected', 'false');
      el.setAttribute('tabindex', '-1');
    });

    var target = document.getElementById('section-' + sectionId);
    if (target) {
      target.style.display = 'block';
      target.classList.add('active');
    }

    var navItem = document.querySelector('[data-section="' + sectionId + '"]');
    if (navItem) {
      navItem.classList.add('active');
      navItem.setAttribute('aria-selected', 'true');
      navItem.setAttribute('tabindex', '0');
    }

    // Lazy-load the queue the first time its tab is opened.
    if (sectionId === 'queue' && !queueLoaded) {
      loadQueue();
    }
  }

  function getSectionFromHash() {
    var hash = window.location.hash.replace('#', '').trim();
    return hash || DEFAULT_SECTION;
  }

  var navItems = Array.prototype.slice.call(document.querySelectorAll('.settings-nav-item'));
  var visibleNavItems = navItems.filter(function (el) { return !el.hasAttribute('hidden'); });

  navItems.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var section = btn.getAttribute('data-section');
      if (window.location.hash !== '#' + section) {
        window.location.hash = section;
      } else {
        activateSection(section);
      }
    });

    // Roving-tabindex arrow-key navigation between tabs (WAI-ARIA tabs pattern)
    btn.addEventListener('keydown', function (e) {
      var key = e.key;
      if (key !== 'ArrowRight' && key !== 'ArrowLeft' && key !== 'Home' && key !== 'End') return;
      e.preventDefault();
      var idx = visibleNavItems.indexOf(btn);
      if (idx === -1) return;
      var nextIdx = idx;
      if (key === 'ArrowRight') nextIdx = (idx + 1) % visibleNavItems.length;
      else if (key === 'ArrowLeft') nextIdx = (idx - 1 + visibleNavItems.length) % visibleNavItems.length;
      else if (key === 'Home') nextIdx = 0;
      else if (key === 'End') nextIdx = visibleNavItems.length - 1;
      var nextBtn = visibleNavItems[nextIdx];
      if (nextBtn) {
        nextBtn.focus();
        var section = nextBtn.getAttribute('data-section');
        if (window.location.hash !== '#' + section) {
          window.location.hash = section;
        } else {
          activateSection(section);
        }
      }
    });
  });

  window.addEventListener('hashchange', function () {
    activateSection(getSectionFromHash());
  });

  var queueRefresh = document.getElementById('queue-refresh');
  if (queueRefresh) {
    queueRefresh.addEventListener('click', function () { loadQueue(); });
  }

  activateSection(getSectionFromHash());
}());
