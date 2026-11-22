(function () {
      // Performance Thresholds section
      // Baseline holds the displayed value for each field (row[field] ?? defaults[field]).
      // PATCH sends only fields that differ from the baseline so unchanged values are omitted.
      var _tBaseline = { ftp_w: null, threshold_hr: null, max_hr: null, threshold_pace_seconds_per_km: null, zone2_hr_min: null, zone2_hr_max: null };
      var _tDefaults = { ftp_w: 280, threshold_hr: 170, max_hr: 190, threshold_pace_seconds_per_km: 270, zone2_hr_min: 130, zone2_hr_max: 155 };
      var _tFieldToErrorId = {
        'ftp_w': 'thresholds-ftp-error',
        'threshold_hr': 'thresholds-hr-error',
        'max_hr': 'thresholds-max-hr-error',
        'threshold_pace_seconds_per_km': 'thresholds-pace-error',
        'zone2_hr_min': 'thresholds-zone2-hr-error',
        'zone2_hr_max': 'thresholds-zone2-hr-error',
      };

      function _secsToMMSS(secs) {
        if (secs == null) return '';
        var m = Math.floor(secs / 60);
        var s = secs % 60;
        return m + ':' + (s < 10 ? '0' : '') + s;
      }

      function _parsePace(str) {
        // Kept for backwards compatibility; threshold pace now uses a numeric seconds input.
        // Accepts "4:30", "4:30/km" — returns integer seconds or null on failure
        if (!str || !str.trim()) return null;
        var clean = str.trim().replace(/\s*\/\s*km\s*$/i, '').trim();
        var match = clean.match(/^(\d{1,2}):(\d{2})$/);
        if (!match) return null;
        var mins = parseInt(match[1], 10);
        var secs = parseInt(match[2], 10);
        if (secs >= 60) return null;
        return mins * 60 + secs;
      }

      function _tClearErrors() {
        ['thresholds-ftp-error', 'thresholds-hr-error', 'thresholds-max-hr-error', 'thresholds-pace-error']
          .forEach(window._settingsClearFieldError);
        window._settingsSetFieldError('thresholds-zone2-hr-error', '');
        ['thresholds-zone2-hr-min', 'thresholds-zone2-hr-max'].forEach(function (id) {
          var el = document.getElementById(id);
          if (el) el.removeAttribute('aria-invalid');
        });
      }

      function _tSetFeedback(msg, type) {
        var el = document.getElementById('thresholds-feedback');
        if (!el) return;
        el.textContent = msg;
        el.className = 'settings-feedback' + (type ? ' ' + type : '');
      }

      function _tLoadPrefs() {
        fetch('/api/user-preferences')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var row = data.row || {};
            var defs = data.defaults || _tDefaults;

            // For the three AC-required fields (FTP, HR, Pace): show blank when not stored
            // so that reloading the page leaves the input empty when no value is saved (AC4).
            // Other fields (Max HR, Zone 2) continue to show system defaults.
            var displayFtp   = row.ftp_w != null ? row.ftp_w : null;
            var displayHr    = row.threshold_hr != null ? row.threshold_hr : null;
            var displayMaxHr = row.max_hr != null ? row.max_hr : (defs.max_hr != null ? defs.max_hr : _tDefaults.max_hr);
            var displayPace  = row.threshold_pace_seconds_per_km != null
              ? row.threshold_pace_seconds_per_km : null;
            var displayZ2Min = row.zone2_hr_min != null ? row.zone2_hr_min : (defs.zone2_hr_min != null ? defs.zone2_hr_min : _tDefaults.zone2_hr_min);
            var displayZ2Max = row.zone2_hr_max != null ? row.zone2_hr_max : (defs.zone2_hr_max != null ? defs.zone2_hr_max : _tDefaults.zone2_hr_max);

            _tBaseline = {
              ftp_w: displayFtp,
              threshold_hr: displayHr,
              max_hr: displayMaxHr,
              threshold_pace_seconds_per_km: displayPace,
              zone2_hr_min: displayZ2Min,
              zone2_hr_max: displayZ2Max,
            };

            var ftpEl = document.getElementById('thresholds-ftp');
            if (ftpEl) ftpEl.value = displayFtp != null ? String(displayFtp) : '';

            var hrEl = document.getElementById('thresholds-hr');
            if (hrEl) hrEl.value = displayHr != null ? String(displayHr) : '';

            var maxHrEl = document.getElementById('thresholds-max-hr');
            if (maxHrEl) maxHrEl.value = String(displayMaxHr);

            var paceEl = document.getElementById('thresholds-pace');
            if (paceEl) paceEl.value = displayPace != null ? String(displayPace) : '';

            var z2MinEl = document.getElementById('thresholds-zone2-hr-min');
            if (z2MinEl) z2MinEl.value = String(displayZ2Min);

            var z2MaxEl = document.getElementById('thresholds-zone2-hr-max');
            if (z2MaxEl) z2MaxEl.value = String(displayZ2Max);

            // Populate "last set" timestamps (AC2)
            _tSetLastSet('thresholds-ftp-last-set', row.ftp_w_updated_at);
            _tSetLastSet('thresholds-hr-last-set', row.threshold_hr_updated_at);
            _tSetLastSet('thresholds-pace-last-set', row.threshold_pace_seconds_per_km_updated_at);
          })
          .catch(function () {
            _tSetFeedback('Failed to load thresholds.', 'error');
          });
      }

      function _tFmtTimestamp(iso) {
        if (!iso) return '';
        try {
          var d = new Date(iso);
          return 'Last set: ' + d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        } catch (e) { return ''; }
      }

      function _tSetLastSet(elId, isoString) {
        var el = document.getElementById(elId);
        if (!el) return;
        el.textContent = _tFmtTimestamp(isoString);
      }

      function _tValidateAndBuildPatch() {
        _tClearErrors();
        var patch = {};
        var hasError = false;

        // FTP
        var ftpEl = document.getElementById('thresholds-ftp');
        var ftpVal = ftpEl ? ftpEl.value.trim() : '';
        if (ftpVal === '') {
          if (_tBaseline.ftp_w !== null) patch.ftp_w = null;
        } else {
          var ftpNum = parseInt(ftpVal, 10);
          if (isNaN(ftpNum) || ftpNum < 50 || ftpNum > 600) {
            window._settingsSetFieldError('thresholds-ftp-error', 'FTP must be between 50 and 600 W');
            hasError = true;
          } else if (ftpNum !== _tBaseline.ftp_w) {
            patch.ftp_w = ftpNum;
          }
        }

        // Threshold HR
        var hrEl = document.getElementById('thresholds-hr');
        var hrVal = hrEl ? hrEl.value.trim() : '';
        if (hrVal === '') {
          if (_tBaseline.threshold_hr !== null) patch.threshold_hr = null;
        } else {
          var hrNum = parseInt(hrVal, 10);
          if (isNaN(hrNum) || hrNum < 100 || hrNum > 220) {
            window._settingsSetFieldError('thresholds-hr-error', 'Threshold HR must be between 100 and 220 bpm');
            hasError = true;
          } else if (hrNum !== _tBaseline.threshold_hr) {
            patch.threshold_hr = hrNum;
          }
        }

        // Max HR
        var maxHrEl = document.getElementById('thresholds-max-hr');
        var maxHrVal = maxHrEl ? maxHrEl.value.trim() : '';
        if (maxHrVal === '') {
          if (_tBaseline.max_hr !== null) patch.max_hr = null;
        } else {
          var maxHrNum = parseInt(maxHrVal, 10);
          if (isNaN(maxHrNum) || maxHrNum < 120 || maxHrNum > 230) {
            window._settingsSetFieldError('thresholds-max-hr-error', 'Max HR must be between 120 and 230 bpm');
            hasError = true;
          } else if (maxHrNum !== _tBaseline.max_hr) {
            patch.max_hr = maxHrNum;
          }
        }

        // Threshold Pace (numeric seconds/km — AC1/AC6 of issue #1022)
        var paceEl = document.getElementById('thresholds-pace');
        var paceVal = paceEl ? paceEl.value.trim() : '';
        if (paceVal === '') {
          if (_tBaseline.threshold_pace_seconds_per_km !== null) patch.threshold_pace_seconds_per_km = null;
        } else {
          var paceSecs = parseInt(paceVal, 10);
          if (isNaN(paceSecs) || paceSecs < 180 || paceSecs > 540) {
            window._settingsSetFieldError('thresholds-pace-error', 'Threshold Pace must be a number between 180 and 540 (sec/km)');
            hasError = true;
          } else if (paceSecs !== _tBaseline.threshold_pace_seconds_per_km) {
            patch.threshold_pace_seconds_per_km = paceSecs;
          }
        }

        // Zone 2 HR band (cross-field: min must be < max)
        var z2MinEl = document.getElementById('thresholds-zone2-hr-min');
        var z2MaxEl = document.getElementById('thresholds-zone2-hr-max');
        var z2MinVal = z2MinEl ? z2MinEl.value.trim() : '';
        var z2MaxVal = z2MaxEl ? z2MaxEl.value.trim() : '';
        var z2MinNum = z2MinVal !== '' ? parseInt(z2MinVal, 10) : null;
        var z2MaxNum = z2MaxVal !== '' ? parseInt(z2MaxVal, 10) : null;

        if (z2MinNum !== null && z2MaxNum !== null && z2MinNum >= z2MaxNum) {
          window._settingsSetFieldError('thresholds-zone2-hr-error', 'Min must be less than Max');
          if (z2MinEl) z2MinEl.setAttribute('aria-invalid', 'true');
          if (z2MaxEl) z2MaxEl.setAttribute('aria-invalid', 'true');
          hasError = true;
        } else {
          if (z2MinVal === '') {
            if (_tBaseline.zone2_hr_min !== null) patch.zone2_hr_min = null;
          } else if (z2MinNum !== null && z2MinNum !== _tBaseline.zone2_hr_min) {
            patch.zone2_hr_min = z2MinNum;
          }
          if (z2MaxVal === '') {
            if (_tBaseline.zone2_hr_max !== null) patch.zone2_hr_max = null;
          } else if (z2MaxNum !== null && z2MaxNum !== _tBaseline.zone2_hr_max) {
            patch.zone2_hr_max = z2MaxNum;
          }
        }

        return hasError ? null : patch;
      }

      function _tHandleSave() {
        var btn = document.getElementById('thresholds-save-btn');
        _tSetFeedback('', '');

        var patch = _tValidateAndBuildPatch();
        if (patch === null) {
          _tSetFeedback('Fix the errors above and try again.', 'error');
          return;
        }

        // No fields changed — nothing to save
        if (!Object.keys(patch).length) {
          _tSetFeedback('No changes to save.', '');
          return;
        }

        if (btn) btn.disabled = true;
        fetch('/api/user-preferences', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { return Promise.reject(d); });
            return r.json();
          })
          .then(function (saved) {
            var defs = _tDefaults;
            _tBaseline = {
              ftp_w: saved.ftp_w,
              threshold_hr: saved.threshold_hr,
              max_hr: saved.max_hr,
              threshold_pace_seconds_per_km: saved.threshold_pace_seconds_per_km,
              zone2_hr_min: saved.zone2_hr_min != null ? saved.zone2_hr_min : defs.zone2_hr_min,
              zone2_hr_max: saved.zone2_hr_max != null ? saved.zone2_hr_max : defs.zone2_hr_max,
              weekly_zone2_target_min: saved.weekly_zone2_target_min,
            };
            // Update pace display as numeric seconds (input is type=number — issue #1022)
            var paceEl = document.getElementById('thresholds-pace');
            if (paceEl) paceEl.value = _tBaseline.threshold_pace_seconds_per_km != null
              ? String(_tBaseline.threshold_pace_seconds_per_km) : '';
            // Refresh timestamps from the saved row (AC2)
            _tSetLastSet('thresholds-ftp-last-set', saved.ftp_w_updated_at);
            _tSetLastSet('thresholds-hr-last-set', saved.threshold_hr_updated_at);
            _tSetLastSet('thresholds-pace-last-set', saved.threshold_pace_seconds_per_km_updated_at);
            _tSetFeedback('Preferences saved.', 'success');
          })
          .catch(function (errData) {
            var detail = errData && errData.detail;
            if (Array.isArray(detail)) {
              detail.forEach(function (e) {
                var errElId = _tFieldToErrorId[e.field] ||
                  ('thresholds-' + (e.field || '').replace(/_/g, '-').replace('threshold-', '') + '-error');
                window._settingsSetFieldError(errElId, e.msg || 'Invalid value');
              });
              _tSetFeedback('Fix the errors above and try again.', 'error');
            } else {
              _tSetFeedback(typeof detail === 'string' ? detail : 'Save failed.', 'error');
            }
          })
          .finally(function () {
            if (btn) btn.disabled = false;
          });
      }

      // "Use default" buttons clear their field (signals "revert to system default")
      document.querySelectorAll('.thresholds-default-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var field = btn.getAttribute('data-field');
          var inputId = 'thresholds-' + field;
          var el = document.getElementById(inputId);
          if (el) el.value = '';
          var errEl = document.getElementById(inputId + '-error');
          if (errEl) errEl.textContent = '';
          _tSetFeedback('', '');
        });
      });

      var tSaveBtn = document.getElementById('thresholds-save-btn');
      if (tSaveBtn) tSaveBtn.addEventListener('click', _tHandleSave);

      // ── Threshold suggestions ─────────────────────────────────────────────
      // Fetches /api/thresholds/suggestions and shows an inline suggestion banner
      // with formula text and an Accept button per field (AC5).
      // Clicking Accept calls POST /api/thresholds/suggestions/accept and writes
      // the value to user_preferences; the banner then disappears (AC6).

      function _loadThresholdSuggestions() {
        fetch('/api/thresholds/suggestions')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data || !data.pending) return;
            var pending = data.pending;
            if (pending.ftp_w) {
              _showSuggestionBanner('thresholds-ftp-suggestion', 'thresholds-ftp', 'ftp_w', pending.ftp_w, false);
            }
            if (pending.threshold_hr) {
              _showSuggestionBanner('thresholds-hr-suggestion', 'thresholds-hr', 'threshold_hr', pending.threshold_hr, false);
            }
            if (pending.threshold_pace_seconds_per_km) {
              _showSuggestionBanner('thresholds-pace-suggestion', 'thresholds-pace', 'threshold_pace_seconds_per_km', pending.threshold_pace_seconds_per_km, true);
            }
          })
          .catch(function () {});
      }

      function _showSuggestionBanner(bannerId, inputId, prefKey, suggestion, isPace) {
        var banner = document.getElementById(bannerId);
        if (!banner) return;
        var rawValue = suggestion.value;
        var formula = suggestion.formula || '';

        var displayVal = isPace
          ? (_secsToMMSS(rawValue) + '/km')
          : (Math.round(rawValue) + (prefKey === 'ftp_w' ? ' W' : ' bpm'));

        var suggestText = 'Suggested ' + displayVal;
        if (formula) suggestText += ' — ' + formula;

        banner.innerHTML = '';
        var textSpan = document.createElement('span');
        textSpan.className = 'suggestion-text';
        textSpan.textContent = suggestText;

        var acceptBtn = document.createElement('button');
        acceptBtn.type = 'button';
        acceptBtn.className = 'suggestion-accept-btn';
        acceptBtn.textContent = 'Accept';
        acceptBtn.addEventListener('click', function () {
          acceptBtn.disabled = true;
          function _readCsrf() {
            var csrf = '';
            var metaEl = document.querySelector('meta[name="csrf-token"]');
            if (metaEl) csrf = metaEl.getAttribute('content');
            if (!csrf) {
              document.cookie.split(';').forEach(function (c) {
                var pair = c.trim();
                if (pair.startsWith('csrf-token=')) csrf = decodeURIComponent(pair.slice('csrf-token='.length));
              });
            }
            return csrf;
          }
          function _acceptWithCsrf() {
            var csrf = _readCsrf();
            if (csrf) return Promise.resolve(csrf);
            return fetch('/api/csrf-token').then(function (r) {
              return r.ok ? r.json() : {};
            }).then(function (d) {
              return (d && d.csrf_token) || _readCsrf();
            });
          }
          _acceptWithCsrf().then(function (csrf) {
            return fetch('/api/thresholds/suggestions/accept', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
              body: JSON.stringify({ keys: [prefKey] }),
            });
          })
            .then(function (r) { return r.json(); })
            .then(function (result) {
              var written = result.written || {};
              if (prefKey in written) {
                // Update the input field with the accepted value.
                // Pace input is numeric (seconds) since issue #1022 — use raw value.
                var inputEl = document.getElementById(inputId);
                if (inputEl) {
                  inputEl.value = String(written[prefKey]);
                }
                // Update baseline so dirty-check recognises the new value as saved
                if (prefKey in _tBaseline) _tBaseline[prefKey] = written[prefKey];
                // Hide the banner (AC6)
                banner.classList.remove('visible');
                banner.innerHTML = '';
                // Refresh timestamps
                _tLoadPrefs();
              } else {
                acceptBtn.disabled = false;
              }
            })
            .catch(function () { acceptBtn.disabled = false; });
        });

        banner.appendChild(textSpan);
        banner.appendChild(acceptBtn);
        banner.classList.add('visible');
      }

      // Zone 2 habit is auto-seeded via coach_habit_targets (Habits page).

      // ── CP staleness / Update CP (#1877) ─────────────────────────────────
      // GET /api/cp/staleness is read-only; CP only changes when the athlete
      // clicks Update CP, which POSTs /api/cp/update (also logs cp_history).
      function _loadCpHistory() {
        fetch('/api/cp/history')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            var el = document.getElementById('cp-history-line');
            if (!el || !d || !d.history || !d.history.length) return;
            el.textContent = 'CP history: ' + d.history.slice(0, 4).map(function (h) {
              return h.effective_date + ' ' + h.cp_w + ' W';
            }).join(' · ');
          })
          .catch(function () {});
      }

      function _loadCpStaleness() {
        _loadCpHistory();
        fetch('/api/cp/staleness')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            var el = document.getElementById('cp-staleness-banner');
            if (!el || !d || !d.stale) return;
            el.innerHTML = '';
            var txt = document.createElement('span');
            txt.className = 'suggestion-text';
            var msg = d.suggested_cp_w
              ? 'CP looks out of date. Suggested ' + d.suggested_cp_w + ' W'
                + (d.suggestion_basis ? ' (from ' + d.suggestion_basis.date + ' run, ' + d.suggestion_basis.avg_power_w + ' W avg)' : '')
              : 'CP has not been updated in 6 weeks. Consider re-testing.';
            if (d.stryd_cp_w) msg += ' · Stryd CP ' + d.stryd_cp_w + ' W';
            txt.textContent = msg;
            el.appendChild(txt);
            [['suggested', d.suggested_cp_w], ['stryd', d.stryd_cp_w]].forEach(function (c) {
              if (!c[1]) return;
              var b = document.createElement('button');
              b.type = 'button';
              b.className = 'suggestion-accept-btn';
              b.textContent = 'Update CP to ' + c[1] + ' W' + (c[0] === 'stryd' ? ' (Stryd)' : '');
              b.addEventListener('click', function () {
                b.disabled = true;
                fetch('/api/cp/update', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ cp_w: c[1], source: c[0] })
                }).then(function (r) {
                  if (!r.ok) { b.disabled = false; return; }
                  el.innerHTML = '';
                  _tLoadPrefs();
                  _loadCpHistory();
                }).catch(function () { b.disabled = false; });
              });
              el.appendChild(b);
            });
          })
          .catch(function () {});
      }

      window.addEventListener('userReady', function () {
        _tLoadPrefs();
        _loadThresholdSuggestions();
        _loadCpStaleness();
        _loadDeviceZones();
      });

      // ── Device zones: read-only display from Stryd (AC10) ─────────────────
      function _loadDeviceZones() {
        fetch('/api/thresholds/device-zones')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data || !data.source) return;
            var emptyEl = document.getElementById('device-zones-empty');
            var tableEl = document.getElementById('device-zones-table');
            if (emptyEl) emptyEl.style.display = 'none';
            if (tableEl) tableEl.style.display = '';

            var ftpEl = document.getElementById('device-ftp-value');
            if (ftpEl) ftpEl.textContent = data.critical_power_w != null ? String(data.critical_power_w) : '—';

            var listEl = document.getElementById('device-zones-list');
            if (listEl && data.zones) {
              listEl.innerHTML = '';
              Object.keys(data.zones).sort().forEach(function (z) {
                var label = document.createElement('span');
                label.style.fontWeight = '600';
                label.textContent = z.toUpperCase() + ':';
                var val = document.createElement('span');
                val.textContent = data.zones[z] != null ? data.zones[z] + ' W' : '—';
                listEl.appendChild(label);
                listEl.appendChild(val);
              });
            }

            var dateEl = document.getElementById('device-zones-date');
            if (dateEl && data.activity_date) {
              dateEl.textContent = 'From Stryd activity on ' + data.activity_date;
            }
          })
          .catch(function () {});
      }
}());
