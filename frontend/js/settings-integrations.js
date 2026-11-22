(function () {
      function intFeedback(id, msg, type) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = msg;
        el.className = 'integration-feedback' + (type ? ' ' + type : '');
      }

      function renderComingSoon(cardId) {
        var card = document.getElementById(cardId);
        if (!card) return;
        var badgeId = cardId.replace('-card', '-badge');
        var badge = document.getElementById(badgeId);
        if (badge) {
          badge.textContent = 'Integration coming soon';
          badge.className = 'integration-badge integration-badge--unconfigured';
        }
        var actionsId = cardId.replace('-card', '-actions');
        var actions = document.getElementById(actionsId);
        if (actions) actions.innerHTML = '';
        var metaId = cardId.replace('-card', '-meta');
        var meta = document.getElementById(metaId);
        if (meta) meta.textContent = '';
        var formWrap = document.getElementById('stryd-form-wrap');
        if (cardId === 'stryd-card' && formWrap) formWrap.innerHTML = '';
        card.classList.add('integration-card--placeholder');
      }

      // ── Shared integration sync/debug log ───────────────────────────────────
      // window.intLog(source, level, msg, data) — source: 'strava'|'stryd'|'system',
      // level: 'info'|'success'|'error'. Reused by every integration.
      var _intLogEntries = [];

      function _intLogEsc(s) {
        return window.AppCommon.escapeHtml(s);
      }

      function _renderIntLog() {
        var body = document.getElementById('integration-log-body');
        if (!body) return;
        if (!_intLogEntries.length) {
          body.innerHTML = '<div class="integration-log-empty">No activity yet. Connect or sync to see data here.</div>';
          return;
        }
        var html = '';
        _intLogEntries.forEach(function (e) {
          var dataStr = '';
          if (e.data !== undefined && e.data !== null) {
            var raw;
            try { raw = typeof e.data === 'string' ? e.data : JSON.stringify(e.data); }
            catch (x) { raw = '[unserializable]'; }
            dataStr = ' <span class="integration-log-data">' + _intLogEsc(raw) + '</span>';
          }
          html += '<div class="integration-log-entry">' +
            '<span class="integration-log-ts">' + e.ts + '</span> ' +
            '<span class="integration-log-src integration-log-src--' + e.source + '">[' + e.source + ']</span> ' +
            '<span class="integration-log-lvl--' + e.level + '">' + _intLogEsc(e.msg) + '</span>' + dataStr +
            '</div>';
        });
        body.innerHTML = html;
        body.scrollTop = body.scrollHeight;
      }

      window.intLog = function (source, level, msg, data) {
        var ts;
        try { ts = new Date().toLocaleTimeString(); } catch (x) { ts = ''; }
        _intLogEntries.push({
          ts: ts,
          source: source || 'system',
          level: level || 'info',
          msg: msg || '',
          data: data,
        });
        if (_intLogEntries.length > 200) _intLogEntries.shift();
        _renderIntLog();
      };

      (function _initIntLogClear() {
        var btn = document.getElementById('integration-log-clear');
        if (btn) btn.addEventListener('click', function () { _intLogEntries = []; _renderIntLog(); });
      })();

      // ── Strava ─────────────────────────────────────────────────────────────

      var _stravaUserId = null;
      var _stravaSyncPollUnsub = null;
      var _stravaSyncPanelOpen = false;
      var _stravaHistoryOpen = false;
      var _stravaSinceDateValue = null;
      var _stravaShowPreview = true;

      function _stravaRelativeTime(isoStr) {
        if (!isoStr) return 'Never synced';
        var diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
        if (diff < 60) return 'Last synced just now';
        if (diff < 3600) return 'Last synced ' + Math.floor(diff / 60) + ' min ago';
        if (diff < 86400) return 'Last synced ' + Math.floor(diff / 3600) + ' hours ago';
        return 'Last synced ' + Math.floor(diff / 86400) + ' days ago';
      }

      function loadStravaSyncLatest() {
        var el = document.getElementById('strava-last-synced');
        if (!el) return;
        fetch('/api/sync/strava/latest')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            if (!d) { el.textContent = ''; return; }
            if (!d.synced_at) {
              el.textContent = 'Never synced';
            } else {
              el.textContent = _stravaRelativeTime(d.synced_at) +
                ': synced ' + d.activities_synced + ' activities (' + d.new_workouts + ' new workouts)';
            }
          })
          .catch(function () { el.textContent = ''; });
      }

      function _stravaSinceDefault(latestSyncedAt) {
        if (latestSyncedAt) {
          return new Date(latestSyncedAt).toISOString().slice(0, 10);
        }
        return window.AppCommon.addDaysISO(window.AppCommon.todayISO(), -90);
      }

      function _clearStravaSyncPoll() {
        if (_stravaSyncPollUnsub) {
          _stravaSyncPollUnsub();
          _stravaSyncPollUnsub = null;
        }
      }

      function openStravaSyncPanel() {
        if (_stravaSyncPanelOpen) { closeStravaSyncPanel(); return; }
        _stravaSyncPanelOpen = true;
        var btn = document.getElementById('strava-sync-now-btn');
        if (btn) btn.textContent = 'Close custom range';

        fetch('/api/sync/strava/latest')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            var sinceDefault = _stravaSinceDefault(d && d.synced_at);
            _renderStravaSyncPanel(sinceDefault);
          })
          .catch(function () { _renderStravaSyncPanel(_stravaSinceDefault(null)); });
      }

      function closeStravaSyncPanel() {
        _stravaSyncPanelOpen = false;
        _clearStravaSyncPoll();
        var panel = document.getElementById('strava-sync-panel');
        if (panel) panel.innerHTML = '';
        var btn = document.getElementById('strava-sync-now-btn');
        if (btn) btn.textContent = 'Custom range…';
      }

      function _renderStravaSyncPanel(sinceDefault) {
        var panel = document.getElementById('strava-sync-panel');
        if (!panel) return;
        _stravaSinceDateValue = sinceDefault;
        panel.innerHTML =
          '<div class="strava-sync-panel">' +
            '<div class="strava-sync-panel-row">' +
              '<label>Since <input type="date" id="strava-since-date" value="' + sinceDefault + '"></label>' +
              '<label><input type="checkbox" id="strava-preview-toggle"' + (_stravaShowPreview ? ' checked' : '') + '> Show preview first</label>' +
            '</div>' +
            '<div class="strava-sync-panel-row">' +
              '<button class="integration-btn integration-btn--secondary" id="strava-preview-btn">Preview</button>' +
              '<button class="integration-btn integration-btn--primary" id="strava-run-sync-btn">Run sync</button>' +
            '</div>' +
            '<div id="strava-panel-result"></div>' +
          '</div>';
        document.getElementById('strava-since-date').addEventListener('change', function () {
          _stravaSinceDateValue = this.value;
        });
        document.getElementById('strava-preview-toggle').addEventListener('change', function () {
          _stravaShowPreview = this.checked;
        });
        document.getElementById('strava-preview-btn').addEventListener('click', stravaPreview);
        document.getElementById('strava-run-sync-btn').addEventListener('click', stravaRunSync);
      }

      function _sinceDate() {
        return _stravaSinceDateValue;
      }

      function stravaPreview() {
        if (!_stravaUserId) return;
        var resultEl = document.getElementById('strava-panel-result');
        if (resultEl) resultEl.innerHTML = '<div class="strava-sync-progress">Loading preview…</div>';
        var params = 'user_id=' + encodeURIComponent(_stravaUserId);
        var since = _sinceDate();
        if (since) params += '&since_date=' + encodeURIComponent(since);
        params += '&limit=20';
        fetch('/api/sync/strava/dry-run?' + params)
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Preview failed'); });
            return r.json();
          })
          .then(function (d) {
            if (!resultEl) return;
            var rows = d.preview || [];
            window.intLog('strava', rows.length ? 'info' : 'info',
              'Preview: ' + rows.length + ' activit' + (rows.length === 1 ? 'y' : 'ies') + ' (since ' + (since || '90d') + ')',
              rows);
            if (!rows.length) {
              resultEl.innerHTML = '<div class="strava-sync-progress">No activities to preview for this date range.</div>';
              return;
            }
            var tbl =
              '<table class="strava-sync-preview-table">' +
                '<thead><tr><th>Date</th><th>Name</th><th>Type</th><th>Action</th></tr></thead>' +
                '<tbody>';
            rows.forEach(function (a) {
              var date = a.start_time ? a.start_time.slice(0, 10) : '—';
              var action = a.would_create_new
                ? '<span class="strava-sync-tag--new">New workout</span>'
                : '<span class="strava-sync-tag--match">Match existing</span>';
              tbl += '<tr><td>' + date + '</td><td>' + (a.name || '—') + '</td><td>' + (a.activity_type || '—') + '</td><td>' + action + '</td></tr>';
            });
            tbl += '</tbody></table>';
            resultEl.innerHTML = tbl;
          })
          .catch(function (err) {
            if (resultEl) resultEl.innerHTML = '<div class="strava-sync-error">' + (err.message || 'Preview failed') + '</div>';
          });
      }

      function stravaRunSync() {
        _clearStravaSyncPoll();
        var resultEl = document.getElementById('strava-panel-result');
        if (resultEl) resultEl.innerHTML = '<div class="strava-sync-progress">Starting sync…</div>';
        var since = _sinceDate();
        window.intLog('strava', 'info', 'Custom sync started', { since_date: since || null });
        _stravaStartSync({ sinceDate: since }, resultEl);
      }

      function stravaQuickSync(full) {
        _clearStravaSyncPoll();
        var label = full ? 'Sync all' : 'Sync new';
        window.intLog('strava', 'info', label + ' started', { full: full });
        _stravaStartSync({ full: full }, null);
      }

      function _stravaStartSync(opts, resultEl) {
        var payload = {};
        if (opts.full) payload.full = true;
        else if (opts.sinceDate) payload.since_date = opts.sinceDate;
        var body = JSON.stringify(payload);
        var startSync = function () {
          return fetch('/api/strava/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
          });
        };
        (window.ensureCsrfReady ? window.ensureCsrfReady(true) : Promise.resolve())
          .then(startSync)
          .then(function (r) {
            if (r.status === 409) throw new Error('Sync already in progress');
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Sync failed to start'); });
            return r.json();
          })
          .then(function () {
            if (resultEl) resultEl.innerHTML = '<div class="strava-sync-progress">Sync running…</div>';
            _startStravaSyncPoll();
          })
          .catch(function (err) {
            var msg = err.message || 'Sync failed';
            if (msg === 'CSRF token missing or invalid') {
              msg = 'Session security token expired — reload the page and try again.';
            }
            window.intLog('strava', 'error', msg);
            if (resultEl) resultEl.innerHTML = '<div class="strava-sync-error">' + msg + '</div>';
          });
      }

      function _startStravaSyncPoll() {
        if (_stravaSyncPollUnsub) return;
        _stravaSyncPollUnsub = window.SyncPoller.subscribe(_onStravaSyncPoll);
        window.SyncPoller.checkNow();
      }

      function _onStravaSyncPoll(job) {
        var resultEl = document.getElementById('strava-panel-result');
        if (!job || !resultEl) { _clearStravaSyncPoll(); return; }
        var status = job.status || 'idle';
        if (status === 'running' || status === 'pending') {
          var phase = job.phase || '';
          var fetched = job.current || 0;
          var msg = status === 'pending'
            ? 'Waiting to sync…'
            : (phase === 'reconciling'
              ? 'Matching workouts…'
              : 'Fetching activities… ' + fetched + ' fetched');
          resultEl.innerHTML = '<div class="strava-sync-progress">' + msg + '</div>';
        } else if (status === 'success') {
          _clearStravaSyncPoll();
          loadStravaSyncLatest();
          fetch('/api/sync/strava/latest')
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
              var n = d && d.new_workouts ? d.new_workouts : 0;
              window.intLog('strava', 'success', 'Sync complete', {
                activities_synced: d && d.activities_synced, new_workouts: n, synced_at: d && d.synced_at,
              });
              if (resultEl) {
                resultEl.innerHTML =
                  '<div class="strava-sync-success">Synced ' + n + ' new workouts. ' +
                  '<a href="' + (window.location.pathname.indexOf('/v2/') === 0 ? '/v2/training/log' : '/log') + '">View them →</a></div>';
              }
            });
        } else if (status === 'error') {
          _clearStravaSyncPoll();
          var errMsg = job.error || 'Sync failed';
          window.intLog('strava', 'error', 'Sync failed', { error: errMsg });
          if (resultEl) {
            resultEl.innerHTML =
              '<div class="strava-sync-error">' + errMsg + '</div>' +
              '<button class="integration-btn integration-btn--secondary" id="strava-retry-btn" style="margin-top:8px">Retry</button>';
            var retryBtn = document.getElementById('strava-retry-btn');
            if (retryBtn) retryBtn.addEventListener('click', stravaRunSync);
          }
        } else {
          // idle
          _clearStravaSyncPoll();
        }
      }

      function stravaReconcile() {
        if (!_stravaUserId) return;
        var reconcileBtn = document.getElementById('strava-reconcile-btn');
        if (reconcileBtn) reconcileBtn.disabled = true;
        intFeedback('strava-feedback', '', '');
        fetch('/api/sync/strava/reconcile?user_id=' + encodeURIComponent(_stravaUserId), { method: 'POST' })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Reconcile failed'); });
            return r.json();
          })
          .then(function (d) {
            intFeedback('strava-feedback',
              'Matched ' + (d.matched_to_existing || 0) + ', created ' + (d.created_new || 0) + '.',
              'success');
            loadStravaSyncLatest();
          })
          .catch(function (err) {
            intFeedback('strava-feedback', typeof err === 'string' ? err : (err.message || 'Reconcile failed'), 'error');
          })
          .finally(function () {
            if (reconcileBtn) reconcileBtn.disabled = false;
          });
      }

      // ── Sync history (AC B) ───────────────────────────────────────────────────

      function _syncStatusBadge(status) {
        var cls = 'sync-status-badge sync-status-badge--' + (status || 'pending');
        return '<span class="' + cls + '">' + (status || 'unknown') + '</span>';
      }

      function _formatDuration(seconds) {
        if (seconds == null) return '—';
        if (seconds < 60) return Math.round(seconds) + 's';
        return Math.round(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
      }

      function _formatHistoryTimestamp(iso) {
        if (!iso) return '—';
        try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
      }

      function loadStravaHistory() {
        var panel = document.getElementById('strava-history-panel');
        if (!panel) return;
        panel.innerHTML = '<div class="strava-sync-progress">Loading…</div>';
        fetch('/api/sync/history?source=strava&limit=5')
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (jobs) {
            if (!panel) return;
            if (!Array.isArray(jobs) || !jobs.length) {
              panel.innerHTML = '<div class="sync-history-empty">No sync history yet</div>';
              return;
            }
            var tbl =
              '<table class="strava-history-table">' +
                '<thead><tr>' +
                  '<th>Time</th><th>Type</th><th>Status</th><th>Duration</th><th>Counters</th>' +
                '</tr></thead><tbody>';
            jobs.forEach(function (job) {
              var counters = '+' + (job.activities_created || 0) +
                ' updated:' + (job.activities_updated || 0) +
                ' skip:' + (job.activities_skipped || 0);
              var errRow = job.status === 'failed' && job.error_message
                ? '<br><span class="sync-history-error-msg">' + job.error_message + '</span>'
                : '';
              tbl +=
                '<tr>' +
                  '<td>' + _formatHistoryTimestamp(job.started_at) + '</td>' +
                  '<td>' + (job.job_type || '—') + '</td>' +
                  '<td>' + _syncStatusBadge(job.status) + '</td>' +
                  '<td>' + _formatDuration(job.duration_seconds) + '</td>' +
                  '<td>' + counters + errRow + '</td>' +
                '</tr>';
            });
            tbl += '</tbody></table>';
            panel.innerHTML = tbl;
          })
          .catch(function () {
            if (panel) panel.innerHTML = '<div class="sync-history-empty">No sync history yet</div>';
          });
      }

      (function _initStravaHistoryToggle() {
        var toggle = document.getElementById('strava-history-toggle');
        var panel = document.getElementById('strava-history-panel');
        if (!toggle || !panel) return;
        toggle.addEventListener('click', function () {
          _stravaHistoryOpen = !_stravaHistoryOpen;
          if (!_stravaHistoryOpen) {
            panel.classList.remove('open');
            toggle.classList.remove('open');
            toggle.setAttribute('aria-expanded', 'false');
          } else {
            panel.classList.add('open');
            toggle.classList.add('open');
            toggle.setAttribute('aria-expanded', 'true');
            loadStravaHistory();
          }
        });
      })();

      function renderStravaDisconnected() {
        document.getElementById('strava-badge').textContent = 'Disconnected';
        document.getElementById('strava-badge').className = 'integration-badge integration-badge--disconnected';
        document.getElementById('strava-meta').textContent = '';
        var idRow = document.getElementById('strava-identity');
        if (idRow) { idRow.innerHTML = ''; idRow.style.display = 'none'; }
        var lastSynced = document.getElementById('strava-last-synced');
        if (lastSynced) lastSynced.textContent = '';
        var panel = document.getElementById('strava-sync-panel');
        if (panel) panel.innerHTML = '';
        _stravaSyncPanelOpen = false;
        var actions = document.getElementById('strava-actions');
        actions.innerHTML = '';
        var btn = document.createElement('button');
        btn.className = 'integration-btn integration-btn--primary';
        btn.textContent = 'Connect';
        btn.addEventListener('click', stravaConnect);
        actions.appendChild(btn);
      }

      function renderStravaConnected(athleteName, expiresAt, athleteId, profile) {
        var badgeText = 'Connected' + (athleteName ? ' — ' + athleteName : '');
        document.getElementById('strava-badge').textContent = badgeText;
        document.getElementById('strava-badge').className = 'integration-badge integration-badge--connected';
        var meta = '';
        if (expiresAt) {
          var exp = new Date(expiresAt);
          meta = 'Token expires ' + exp.toLocaleDateString();
        }
        document.getElementById('strava-meta').textContent = meta;

        // Identity / debug row: avatar + athlete name + profile id.
        var idRow = document.getElementById('strava-identity');
        if (idRow) {
          if (athleteName || athleteId) {
            var img = profile ? '<img src="' + profile + '" alt="" referrerpolicy="no-referrer">' : '';
            idRow.innerHTML = img +
              '<span>' + (athleteName ? _intLogEsc(athleteName) : 'Unknown athlete') + '</span>' +
              (athleteId ? ' <code>id: ' + _intLogEsc(athleteId) + '</code>' : '');
            idRow.style.display = '';
          } else {
            idRow.innerHTML = '';
            idRow.style.display = 'none';
          }
        }

        loadStravaSyncLatest();
        loadStravaDataQuality();

        var actions = document.getElementById('strava-actions');
        actions.innerHTML = '';

        var syncNewBtn = document.createElement('button');
        syncNewBtn.className = 'integration-btn integration-btn--primary';
        syncNewBtn.id = 'strava-sync-new-btn';
        syncNewBtn.textContent = 'Sync new';
        syncNewBtn.title = 'Pull activities since your last sync';
        syncNewBtn.addEventListener('click', function () { stravaQuickSync(false); });

        var syncAllBtn = document.createElement('button');
        syncAllBtn.className = 'integration-btn integration-btn--secondary';
        syncAllBtn.id = 'strava-sync-all-btn';
        syncAllBtn.textContent = 'Sync all';
        syncAllBtn.title = 'Pull your full Strava history';
        syncAllBtn.addEventListener('click', function () { stravaQuickSync(true); });

        var syncCustomBtn = document.createElement('button');
        syncCustomBtn.className = 'integration-btn integration-btn--secondary';
        syncCustomBtn.id = 'strava-sync-now-btn';
        syncCustomBtn.textContent = 'Custom range…';
        syncCustomBtn.addEventListener('click', openStravaSyncPanel);

        var reconcileBtn = document.createElement('button');
        reconcileBtn.className = 'integration-btn integration-btn--secondary';
        reconcileBtn.id = 'strava-reconcile-btn';
        reconcileBtn.textContent = 'Reconcile only';
        reconcileBtn.addEventListener('click', stravaReconcile);

        var discBtn = document.createElement('button');
        discBtn.className = 'integration-btn integration-btn--danger';
        discBtn.id = 'strava-disconnect-btn';
        discBtn.textContent = 'Disconnect';
        discBtn.addEventListener('click', stravaDisconnect);

        actions.appendChild(syncNewBtn);
        actions.appendChild(syncAllBtn);
        actions.appendChild(syncCustomBtn);
        actions.appendChild(reconcileBtn);
        actions.appendChild(discBtn);
      }

      function loadStravaDataQuality() {
        if (!_stravaUserId) return;
        fetch('/api/sync/strava/data-quality?user_id=' + encodeURIComponent(_stravaUserId))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (dq) {
            if (!dq) return;
            var panel = document.getElementById('strava-data-quality');
            if (panel) panel.style.display = '';
            function _set(id, val) {
              var el = document.getElementById(id);
              if (!el) return;
              el.textContent = val;
              if (id === 'dq-potential-dupes' && val > 0) {
                el.classList.add('strava-data-quality-val--warn');
              }
            }
            _set('dq-strava-activities', dq.strava_activities_count);
            _set('dq-workouts-strava', dq.workouts_with_strava_source_count);
            _set('dq-workouts-no-source', dq.workouts_without_source_count);
            _set('dq-stryd-synced', dq.is_stryd_synced_count);
            _set('dq-potential-dupes', dq.potential_dupes_count);
          })
          .catch(function () {});
      }

      function loadStravaStatus() {
        fetch('/api/strava/configured')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (cfg) {
            if (cfg && cfg.configured === false) {
              intFeedback(
                'strava-feedback',
                'Strava OAuth is not configured on this server. Set STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_STATE_SECRET in .env.',
                'error'
              );
            }
          })
          .catch(function () {});
        fetch('/api/strava/status')
          .then(function (r) {
            if (!r.ok) { renderComingSoon('strava-card'); return; }
            return r.json().then(function (st) {
              if (st.connected) {
                window.intLog('strava', 'success', 'Connected', {
                  athlete: st.athlete_name, athlete_id: st.athlete_id, scope: st.scope, expires_at: st.expires_at,
                });
                renderStravaConnected(st.athlete_name, st.expires_at, st.athlete_id, st.profile);
              } else {
                window.intLog('strava', 'info', 'Not connected');
                renderStravaDisconnected();
              }
            });
          })
          .catch(function () {
            window.intLog('strava', 'error', 'Status check failed');
            renderComingSoon('strava-card');
          });
      }

      function stravaConnect() {
        intFeedback('strava-feedback', '', '');
        fetch('/api/strava/connect')
          .then(function (r) {
            return r.json().then(function (d) {
              if (!r.ok) {
                var detail = d && d.detail;
                throw new Error(typeof detail === 'string' ? detail : 'Failed to initiate Strava connection');
              }
              if (!d.authorize_url) throw new Error('No authorize URL returned');
              // Same-tab redirect avoids mobile popup blockers (no window.open).
              window.location.href = d.authorize_url;
            });
          })
          .catch(function (err) {
            intFeedback('strava-feedback', (err && err.message) || 'Failed to initiate Strava connection', 'error');
          });
      }

      function _handleStravaOAuthReturn() {
        var params = new URLSearchParams(window.location.search);
        var result = params.get('strava');
        if (!result) return;
        if (result === 'connected') {
          intFeedback('strava-feedback', 'Strava connected!', 'success');
          loadStravaStatus();
        } else if (result === 'error') {
          intFeedback('strava-feedback', 'Strava connection failed or was cancelled. Please try again.', 'error');
        }
        params.delete('strava');
        var clean = window.location.pathname;
        var remainder = params.toString();
        if (remainder) clean += '?' + remainder;
        clean += '#integrations';
        history.replaceState(null, '', clean);
        var integrationsNav = document.querySelector('.settings-nav-item[data-section="integrations"]');
        if (integrationsNav) integrationsNav.click();
      }

      function stravaDisconnect() {
        if (!window.confirm('Disconnect Strava? You can reconnect any time, but scheduled/manual syncs will stop until you do.')) return;
        var discBtn = document.getElementById('strava-disconnect-btn');
        var syncNowBtn = document.getElementById('strava-sync-now-btn');
        var reconcileBtn = document.getElementById('strava-reconcile-btn');
        intFeedback('strava-feedback', '', '');
        _clearStravaSyncPoll();
        if (discBtn) discBtn.disabled = true;
        if (syncNowBtn) syncNowBtn.disabled = true;
        if (reconcileBtn) reconcileBtn.disabled = true;
        fetch('/api/strava/disconnect', { method: 'DELETE' })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { return Promise.reject(d.detail || 'Disconnect failed'); });
            return r.json();
          })
          .then(function () {
            window.intLog('strava', 'success', 'Disconnected — token deleted from server');
            renderStravaDisconnected();
            intFeedback('strava-feedback', 'Strava disconnected.', 'success');
          })
          .catch(function (err) {
            if (discBtn) discBtn.disabled = false;
            if (syncNowBtn) syncNowBtn.disabled = false;
            if (reconcileBtn) reconcileBtn.disabled = false;
            intFeedback('strava-feedback', typeof err === 'string' ? err : 'Disconnect failed', 'error');
          });
      }

      // ── Stryd ──────────────────────────────────────────────────────────────

      function renderStrydReauth(email) {
        document.getElementById('stryd-badge').textContent = 'Needs your password again';
        document.getElementById('stryd-badge').className = 'integration-badge integration-badge--reauth';
        document.getElementById('stryd-meta').textContent =
          (email ? email + ' — ' : '') + 'Stryd needs your password again';
        document.getElementById('stryd-form-wrap').innerHTML =
          '<p class="u-muted-13" style="margin:0 0 10px;">Your saved password is still on file, but Stryd rejected the session. Enter your password to refresh it.</p>' +
          '<div class="stryd-form" id="stryd-cred-form">' +
          '<label for="stryd-email">Email</label>' +
          '<input type="email" id="stryd-email" placeholder="Stryd email" autocomplete="username" aria-label="Stryd email" value="' + (email ? String(email).replace(/"/g, '&quot;') : '') + '">' +
          '<label for="stryd-password">Password</label>' +
          '<input type="password" id="stryd-password" placeholder="Stryd password" autocomplete="current-password" aria-label="Stryd password">' +
          '</div>';
        var actions = document.getElementById('stryd-actions');
        actions.innerHTML = '';
        var btn = document.createElement('button');
        btn.className = 'integration-btn integration-btn--primary';
        btn.id = 'stryd-connect-btn';
        btn.textContent = 'Reconnect';
        btn.addEventListener('click', strydConnect);
        actions.appendChild(btn);
        var disc = document.createElement('button');
        disc.className = 'integration-btn integration-btn--danger';
        disc.id = 'stryd-disconnect-btn';
        disc.textContent = 'Disconnect';
        disc.addEventListener('click', strydDisconnect);
        actions.appendChild(disc);
      }

      function renderStrydDisconnected() {
        document.getElementById('stryd-badge').textContent = 'Disconnected';
        document.getElementById('stryd-badge').className = 'integration-badge integration-badge--disconnected';
        document.getElementById('stryd-meta').textContent = '';
        var _ls = document.getElementById('stryd-last-synced'); if (_ls) _ls.textContent = '';
        var _ht = document.getElementById('stryd-history-toggle'); if (_ht) _ht.style.display = 'none';
        var _dq = document.getElementById('stryd-data-quality'); if (_dq) _dq.style.display = 'none';

        document.getElementById('stryd-form-wrap').innerHTML =
          '<p class="u-muted-13" style="margin:0 0 10px;">Stryd has no OAuth, so this app signs in on your ' +
          'behalf: your password is encrypted before it’s stored and used only to refresh your Stryd session.</p>' +
          '<div class="stryd-form" id="stryd-cred-form">' +
          '<label for="stryd-email">Email</label>' +
          '<input type="email" id="stryd-email" placeholder="Stryd email" autocomplete="username" aria-label="Stryd email">' +
          '<label for="stryd-password">Password</label>' +
          '<input type="password" id="stryd-password" placeholder="Stryd password" autocomplete="current-password" aria-label="Stryd password">' +
          '</div>';

        var actions = document.getElementById('stryd-actions');
        actions.innerHTML = '';
        var btn = document.createElement('button');
        btn.className = 'integration-btn integration-btn--primary';
        btn.id = 'stryd-connect-btn';
        btn.textContent = 'Connect';
        btn.addEventListener('click', strydConnect);
        actions.appendChild(btn);
      }

      function loadStrydSyncLatest() {
        var el = document.getElementById('stryd-last-synced');
        if (!el) return;
        fetch('/api/sync/stryd/latest')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            if (!d || !d.synced_at) { el.textContent = d ? 'Never synced' : ''; return; }
            el.textContent = 'Last synced ' + new Date(d.synced_at).toLocaleString() +
              ': ' + d.activities_synced + ' activities (' + d.new_workouts + ' new)';
          })
          .catch(function () { el.textContent = ''; });
      }

      function loadStrydDataQuality() {
        if (!_stravaUserId) return;
        fetch('/api/sync/stryd/data-quality?user_id=' + encodeURIComponent(_stravaUserId))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (dq) {
            if (!dq) return;
            var panel = document.getElementById('stryd-data-quality');
            if (panel) panel.style.display = '';
            function _set(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
            _set('dq-stryd-activities', dq.stryd_activities_count);
            _set('dq-workouts-stryd', dq.workouts_with_stryd_source_count);
            _set('dq-workouts-strava2', dq.workouts_with_strava_source_count);
            _set('dq-workouts-both', dq.workouts_with_both_count);
            _set('dq-workouts-tss', dq.workouts_with_tss_count);
          })
          .catch(function () {});
      }

      function loadStrydHistory() {
        var panel = document.getElementById('stryd-history-panel');
        if (!panel) return;
        panel.innerHTML = '<div class="strava-sync-progress">Loading…</div>';
        fetch('/api/sync/history?source=stryd&limit=5')
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (jobs) {
            if (!Array.isArray(jobs) || !jobs.length) {
              panel.innerHTML = '<div class="sync-history-empty">No sync history yet</div>';
              return;
            }
            var tbl = '<table class="strava-history-table"><thead><tr>' +
              '<th>Time</th><th>Type</th><th>Status</th><th>Counters</th></tr></thead><tbody>';
            jobs.forEach(function (job) {
              var counters = '+' + (job.activities_created || 0) + ' upd:' + (job.activities_updated || 0);
              var err = job.status === 'failed' && job.error_message
                ? '<br><span class="sync-history-error-msg">' + job.error_message + '</span>' : '';
              tbl += '<tr><td>' + (job.started_at ? new Date(job.started_at).toLocaleString() : '—') + '</td>' +
                '<td>' + (job.job_type || '—') + '</td>' +
                '<td><span class="sync-status-badge sync-status-badge--' + (job.status || 'pending') + '">' + (job.status || '?') + '</span></td>' +
                '<td>' + counters + err + '</td></tr>';
            });
            panel.innerHTML = tbl + '</tbody></table>';
          })
          .catch(function () { panel.innerHTML = '<div class="sync-history-empty">No sync history yet</div>'; });
      }

      (function _initStrydHistoryToggle() {
        var toggle = document.getElementById('stryd-history-toggle');
        var panel = document.getElementById('stryd-history-panel');
        if (!toggle || !panel) return;
        var open = false;
        toggle.addEventListener('click', function () {
          open = !open;
          panel.classList.toggle('open', open);
          toggle.classList.toggle('open', open);
          toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (open) loadStrydHistory();
        });
      })();

      function _strydErrMsg(err, fallback) {
        var msg = (err && err.message) ? err.message : (typeof err === 'string' ? err : fallback);
        if (msg === 'CSRF token missing or invalid') {
          return 'Session security token expired — reload the page and try again.';
        }
        return msg || fallback;
      }

      function _strydSetSyncBusy(busy, label) {
        ['stryd-sync-new-btn', 'stryd-sync-all-btn'].forEach(function (id) {
          var el = document.getElementById(id);
          if (!el) return;
          el.disabled = busy;
          if (!busy) {
            el.textContent = id === 'stryd-sync-all-btn' ? 'Sync all' : 'Sync new';
          } else if (label) {
            el.textContent = label;
          }
        });
      }

      function _strydSyncProgressLabel(job) {
        if (!job) return '…';
        if (job.phase === 'reconciling' && job.total) {
          return 'matching workouts (' + (job.current || 0) + '/' + job.total + ')';
        }
        if (job.items_synced) {
          return (job.phase || '…') + ' (' + job.items_synced + ' synced)';
        }
        return job.phase || '…';
      }

      function _strydStartSync(full) {
        var payload = full ? { full: true } : {};
        var label = full ? 'Sync all' : 'Sync new';
        _strydSetSyncBusy(true, 'Syncing…');
        window.intLog('stryd', 'info', label + ' started', payload);
        var startSync = function () {
          return fetch('/api/stryd/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        };
        (window.ensureCsrfReady ? window.ensureCsrfReady(true) : Promise.resolve())
          .then(startSync)
          .then(function (r) {
            if (r.status === 409) throw new Error('Sync already in progress');
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Sync failed to start'); });
            return r.json();
          })
          .then(function () { _startStrydSyncPoll(); })
          .catch(function (err) {
            window.intLog('stryd', 'error', _strydErrMsg(err, 'Sync failed'));
            _strydSetSyncBusy(false);
          });
      }

      function strydSyncNew() { _strydStartSync(false); }
      function strydSyncAll() { _strydStartSync(true); }

      var _strydSyncPollUnsub = null;

      function _clearStrydSyncPoll() {
        if (_strydSyncPollUnsub) {
          _strydSyncPollUnsub();
          _strydSyncPollUnsub = null;
        }
      }

      function _startStrydSyncPoll() {
        if (_strydSyncPollUnsub) return;
        _strydSyncPollUnsub = window.SyncPoller.subscribe(_onStrydSyncPoll);
        window.SyncPoller.checkNow();
      }

      function _onStrydSyncPoll(job) {
        var status = (job && job.status) || 'idle';
        if (status === 'running' || status === 'pending') {
          window.intLog('stryd', 'info', 'Phase: ' + _strydSyncProgressLabel(job));
        } else if (status === 'success') {
          _clearStrydSyncPoll();
          window.intLog('stryd', 'success', 'Sync complete', { items_synced: job.items_synced });
          loadStrydSyncLatest(); loadStrydDataQuality();
          _strydSetSyncBusy(false);
        } else if (status === 'error') {
          _clearStrydSyncPoll();
          window.intLog('stryd', 'error', 'Sync failed', { error: job.error });
          _strydSetSyncBusy(false);
        } else {
          // idle
          _clearStrydSyncPoll();
          _strydSetSyncBusy(false);
        }
      }

      function renderStrydConnected(email, expiresAt) {
        var badgeText = 'Connected' + (email ? ' — ' + email : '');
        document.getElementById('stryd-badge').textContent = badgeText;
        document.getElementById('stryd-badge').className = 'integration-badge integration-badge--connected';
        var meta = '';
        if (expiresAt) {
          var exp = new Date(expiresAt);
          meta = 'Session expires ' + exp.toLocaleDateString();
        }
        document.getElementById('stryd-meta').textContent = meta;
        document.getElementById('stryd-form-wrap').innerHTML = '';

        loadStrydSyncLatest();
        loadStrydDataQuality();
        var histToggle = document.getElementById('stryd-history-toggle');
        if (histToggle) histToggle.style.display = '';

        var actions = document.getElementById('stryd-actions');
        actions.innerHTML = '';

        var syncNewBtn = document.createElement('button');
        syncNewBtn.className = 'integration-btn integration-btn--primary';
        syncNewBtn.id = 'stryd-sync-new-btn';
        syncNewBtn.textContent = 'Sync new';
        syncNewBtn.title = 'Pull activities since your last sync';
        syncNewBtn.addEventListener('click', strydSyncNew);

        var syncAllBtn = document.createElement('button');
        syncAllBtn.className = 'integration-btn integration-btn--secondary';
        syncAllBtn.id = 'stryd-sync-all-btn';
        syncAllBtn.textContent = 'Sync all';
        syncAllBtn.title = 'Pull your full Stryd history';
        syncAllBtn.addEventListener('click', strydSyncAll);

        var btn = document.createElement('button');
        btn.className = 'integration-btn integration-btn--danger';
        btn.id = 'stryd-disconnect-btn';
        btn.textContent = 'Disconnect';
        btn.addEventListener('click', strydDisconnect);

        actions.appendChild(syncNewBtn);
        actions.appendChild(syncAllBtn);
        actions.appendChild(btn);
      }

      function loadStrydStatus() {
        fetch('/api/stryd/configured')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (cfg) {
            if (cfg && cfg.configured === false) {
              intFeedback(
                'stryd-feedback',
                'Stryd encryption is not configured on this server. Set STRYD_FERNET_KEY in .env.',
                'error'
              );
            }
          })
          .catch(function () {});
        fetch('/api/stryd/status')
          .then(function (r) {
            if (!r.ok) { renderComingSoon('stryd-card'); return; }
            return r.json().then(function (st) {
              if (!st.connected) {
                renderStrydDisconnected();
                return;
              }
              if (st.status === 'reauth_required') {
                renderStrydReauth(st.stryd_email);
                return;
              }
              renderStrydConnected(st.stryd_email, st.session_expires_at);
              if (st.status === 'unreachable') {
                intFeedback(
                  'stryd-feedback',
                  'Stryd is temporarily unreachable — your password is still saved.',
                  'info'
                );
              }
            });
          })
          .catch(function () { renderComingSoon('stryd-card'); });
      }

      function strydConnect() {
        var btn = document.getElementById('stryd-connect-btn');
        var emailEl = document.getElementById('stryd-email');
        var pwEl = document.getElementById('stryd-password');
        intFeedback('stryd-feedback', '', '');
        var email = emailEl ? emailEl.value.trim() : '';
        var password = pwEl ? pwEl.value : '';
        if (!email || !password) {
          intFeedback('stryd-feedback', 'Enter email and password.', 'error');
          return;
        }
        if (btn) btn.disabled = true;
        if (emailEl) emailEl.disabled = true;
        if (pwEl) pwEl.disabled = true;
        window.intLog('stryd', 'info', 'Connect attempt', { email: email });
        var _status = 0;
        var connect = function () {
          return fetch('/api/stryd/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password }),
          });
        };
        (window.ensureCsrfReady ? window.ensureCsrfReady() : Promise.resolve())
          .then(connect)
          .then(function (r) {
            _status = r.status;
            if (!r.ok) {
              return r.text().then(function (t) {
                var detail = t;
                try { detail = JSON.parse(t).detail || t; } catch (e) {}
                return Promise.reject({ status: r.status, detail: detail });
              });
            }
            return r.json();
          })
          .then(function (d) {
            window.intLog('stryd', 'success', 'Connected (HTTP ' + _status + ')', { athlete_id: d.athlete_id, email: d.stryd_user_email });
            intFeedback('stryd-feedback', 'Stryd connected!', 'success');
            renderStrydConnected(d.stryd_user_email, null);
          })
          .catch(function (err) {
            if (btn) btn.disabled = false;
            if (emailEl) emailEl.disabled = false;
            if (pwEl) pwEl.disabled = false;
            var raw = (err && err.detail) ? err.detail : (typeof err === 'string' ? err : 'Connection failed');
            var msg = _strydErrMsg({ message: raw }, 'Connection failed');
            var code = (err && err.status) ? err.status : _status;
            window.intLog('stryd', 'error', 'Connect failed (HTTP ' + (code || '?') + ')', { detail: msg });
            intFeedback('stryd-feedback', typeof msg === 'string' ? msg : 'Connection failed', 'error');
          });
      }

      function strydDisconnect() {
        if (!window.confirm('Disconnect Stryd? Stored credentials will be deleted from the server.')) return;
        var btn = document.getElementById('stryd-disconnect-btn');
        intFeedback('stryd-feedback', '', '');
        if (btn) btn.disabled = true;
        var disconnect = function () {
          return fetch('/api/stryd/disconnect', { method: 'DELETE' });
        };
        (window.ensureCsrfReady ? window.ensureCsrfReady() : Promise.resolve())
          .then(disconnect)
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { return Promise.reject(d.detail || 'Disconnect failed'); });
            return r.json();
          })
          .then(function () {
            renderStrydDisconnected();
            intFeedback('stryd-feedback', 'Stryd disconnected.', 'success');
          })
          .catch(function (err) {
            if (btn) btn.disabled = false;
            intFeedback('stryd-feedback', _strydErrMsg(typeof err === 'string' ? { message: err } : err, 'Disconnect failed'), 'error');
          });
      }

      // ── Google Drive Sleep ─────────────────────────────────────────────────

      function _driveSleepBadge(status) {
        var el = document.getElementById('drive-sleep-badge');
        if (!el) return;
        if (status === 'connected') {
          el.className = 'integration-badge integration-badge--connected';
          el.textContent = 'Connected';
        } else if (status === 'error') {
          el.className = 'integration-badge integration-badge--disconnected';
          el.textContent = 'Error';
        } else {
          el.className = 'integration-badge integration-badge--disconnected';
          el.textContent = 'Not connected';
        }
      }

      function _driveSleepActions(status) {
        var wrap = document.getElementById('drive-sleep-actions');
        var folderWrap = document.getElementById('drive-sleep-folder-wrap');
        if (!wrap) return;
        wrap.innerHTML = '';
        if (status === 'connected') {
          if (folderWrap) folderWrap.style.display = '';
          var disc = document.createElement('button');
          disc.type = 'button';
          disc.id = 'drive-sleep-disconnect-btn';
          disc.className = 'integration-btn integration-btn--danger';
          disc.textContent = 'Disconnect';
          disc.addEventListener('click', driveSleepDisconnect);
          wrap.appendChild(disc);
        } else {
          if (folderWrap) folderWrap.style.display = 'none';
          var conn = document.createElement('button');
          conn.type = 'button';
          conn.id = 'drive-sleep-connect-btn';
          conn.className = 'integration-btn integration-btn--primary';
          conn.textContent = 'Connect';
          conn.addEventListener('click', driveSleepConnect);
          wrap.appendChild(conn);
        }
      }

      function loadDriveSleepStatus() {
        fetch('/api/drive-sleep/status')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var status = data.status || 'not_connected';
            _driveSleepBadge(status);
            _driveSleepActions(status);
            if (status === 'connected' && data.folder_id) {
              var inp = document.getElementById('drive-sleep-folder-input');
              if (inp) inp.value = data.folder_id;
            }
            if (status === 'error') {
              intFeedback('drive-sleep-feedback', 'Connection error — please reconnect.', 'error');
            }
          })
          .catch(function () {
            _driveSleepBadge('not_connected');
            _driveSleepActions('not_connected');
          });
      }

      function driveSleepConnect() {
        var btn = document.getElementById('drive-sleep-connect-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Connecting…'; }
        fetch('/api/drive-sleep/connect')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.authorize_url) {
              window.location.href = data.authorize_url;
            }
          })
          .catch(function () {
            if (btn) { btn.disabled = false; btn.textContent = 'Connect'; }
            intFeedback('drive-sleep-feedback', 'Could not initiate connection. Try again.', 'error');
          });
      }

      function driveSleepDisconnect() {
        if (!window.confirm('Disconnect Google Drive? Sleep CSV imports will stop until you reconnect.')) return;
        var btn = document.getElementById('drive-sleep-disconnect-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Disconnecting…'; }
        var csrf = document.cookie.split('; ').reduce(function (v, c) {
          var p = c.split('='); return p[0] === 'csrf-token' ? decodeURIComponent(p[1]) : v;
        }, '');
        fetch('/api/drive-sleep/disconnect', { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } })
          .then(function () {
            intFeedback('drive-sleep-feedback', 'Disconnected from Google Drive.', 'success');
            loadDriveSleepStatus();
          })
          .catch(function () {
            if (btn) { btn.disabled = false; btn.textContent = 'Disconnect'; }
            intFeedback('drive-sleep-feedback', 'Disconnect failed. Try again.', 'error');
          });
      }

      (function () {
        var saveBtn = document.getElementById('drive-sleep-folder-save');
        if (saveBtn) {
          saveBtn.addEventListener('click', function () {
            var inp = document.getElementById('drive-sleep-folder-input');
            var fb = document.getElementById('drive-sleep-folder-feedback');
            var raw = (inp && inp.value.trim()) || '';
            // Accept full URL or bare ID
            var folderId = raw;
            var m = raw.match(/\/folders\/([^/?#]+)/);
            if (m) folderId = m[1];
            if (!folderId) {
              if (fb) { fb.textContent = 'Enter a folder ID or Drive URL.'; fb.style.color = 'var(--danger)'; }
              return;
            }
            var csrf = document.cookie.split('; ').reduce(function (v, c) {
              var p = c.split('='); return p[0] === 'csrf-token' ? decodeURIComponent(p[1]) : v;
            }, '');
            saveBtn.disabled = true;
            fetch('/api/drive-sleep/folder', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
              body: JSON.stringify({ folder_id: folderId }),
            })
              .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
              .then(function (res) {
                if (res.ok) {
                  if (fb) { fb.textContent = 'Folder saved.'; fb.style.color = 'var(--success)'; }
                } else {
                  if (fb) { fb.textContent = (res.d && res.d.detail) || 'Save failed.'; fb.style.color = 'var(--danger)'; }
                }
              })
              .catch(function () {
                if (fb) { fb.textContent = 'Save failed.'; fb.style.color = 'var(--danger)'; }
              })
              .finally(function () { saveBtn.disabled = false; });
          });
        }
      }());

      // Handle Drive Sleep OAuth return
      (function () {
        var params = new URLSearchParams(window.location.search);
        if (params.get('drive_sleep') === 'connected') {
          intFeedback('drive-sleep-feedback', 'Google Drive connected!', 'success');
        } else if (params.get('drive_sleep') === 'error') {
          intFeedback('drive-sleep-feedback', 'Connection failed. Please try again.', 'error');
        }
      }());

      window.addEventListener('userReady', function (e) {
        _stravaUserId = e.detail && e.detail.userId;
        _handleStravaOAuthReturn();
        loadStravaStatus();
        loadStrydStatus();
        loadDriveSleepStatus();
      });
}());
