(function () {
      // Profile section: display_name, email, timezone, week_start_day
      var _baseline = {};

      function _initials(displayName, email) {
        var src = (displayName || email || '').trim();
        if (!src) return 'U';
        var words = src.split(/\s+/).filter(Boolean);
        if (words.length >= 2) {
          return (words[0][0] + words[words.length - 1][0]).toUpperCase();
        }
        return src[0].toUpperCase();
      }

      function _currentValues() {
        var h = document.getElementById('profile-height-cm').value.trim();
        return {
          display_name: document.getElementById('profile-display-name').value,
          timezone: document.getElementById('profile-timezone').value,
          week_start_day: parseInt(document.getElementById('profile-week-start').value, 10),
          birth_date: document.getElementById('profile-birth-date').value || null,
          height_cm: h === '' ? null : parseFloat(h),
          athlete_context: document.getElementById('profile-athlete-context').value.trim(),
          weekly_zone2_target_min: (function () {
            var el = document.getElementById('profile-zone2-target');
            if (!el || el.value.trim() === '') return 150;
            return parseInt(el.value, 10);
          })(),
        };
      }

      function _isDirty() {
        var cur = _currentValues();
        return cur.display_name !== (_baseline.display_name || '')
          || cur.timezone !== (_baseline.timezone || 'Asia/Bangkok')
          || cur.week_start_day !== (_baseline.week_start_day || 1)
          || cur.birth_date !== (_baseline.birth_date || null)
          || cur.height_cm !== (_baseline.height_cm === undefined ? null : _baseline.height_cm)
          || cur.athlete_context !== (_baseline.athlete_context || '')
          || cur.weekly_zone2_target_min !== (_baseline.weekly_zone2_target_min == null ? 150 : _baseline.weekly_zone2_target_min);
      }

      function _updateContextCount() {
        var el = document.getElementById('profile-athlete-context');
        var out = document.getElementById('profile-athlete-context-count');
        if (el && out) out.textContent = el.value.length + '/200';
      }

      function _updateSaveBtn() {
        var btn = document.getElementById('profile-save-btn');
        if (btn) btn.disabled = !_isDirty();
      }

      function _clearFieldErrors() {
        ['profile-display-name-error', 'profile-timezone-error', 'profile-week-start-error',
          'profile-birth-date-error', 'profile-height-cm-error', 'profile-athlete-context-error',
          'profile-weekly-zone2-target-min-error']
          .forEach(window._settingsClearFieldError);
      }

      function _setFeedback(msg, type) {
        var el = document.getElementById('profile-feedback');
        if (!el) return;
        el.textContent = msg;
        el.className = 'settings-feedback' + (type ? ' ' + type : '');
      }

      function _loadPrefs() {
        fetch('/api/user-preferences')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var row = data.row || {};
            _baseline = {
              display_name: row.display_name || '',
              timezone: row.timezone || 'Asia/Bangkok',
              week_start_day: row.week_start_day || 1,
              birth_date: row.birth_date || null,
              height_cm: row.height_cm === undefined ? null : row.height_cm,
              athlete_context: row.athlete_context || '',
              weekly_zone2_target_min: row.weekly_zone2_target_min == null ? 150 : row.weekly_zone2_target_min,
            };

            var bdEl = document.getElementById('profile-birth-date');
            if (bdEl) bdEl.value = _baseline.birth_date || '';

            var hEl = document.getElementById('profile-height-cm');
            if (hEl) hEl.value = _baseline.height_cm === null ? '' : String(_baseline.height_cm);

            var acEl = document.getElementById('profile-athlete-context');
            if (acEl) acEl.value = _baseline.athlete_context;
            _updateContextCount();
            var z2El = document.getElementById('profile-zone2-target');
            if (z2El) z2El.value = String(_baseline.weekly_zone2_target_min);

            var dnEl = document.getElementById('profile-display-name');
            if (dnEl) {
              dnEl.value = _baseline.display_name;
              dnEl.placeholder = row.user_name || 'Display name';
            }

            var emailEl = document.getElementById('profile-email');
            if (emailEl) emailEl.value = row.user_email || '';

            var uidEl = document.getElementById('profile-user-id');
            if (uidEl) uidEl.value = row.user_id || '';
            var uidCopy = document.getElementById('profile-user-id-copy');
            if (uidCopy && !uidCopy._wired) {
              uidCopy._wired = true;
              uidCopy.addEventListener('click', function () {
                var v = uidEl ? uidEl.value : '';
                if (!v) return;
                var done = function () {
                  uidCopy.classList.add('copied');
                  uidCopy.textContent = 'Copied';
                  setTimeout(function () { uidCopy.classList.remove('copied'); uidCopy.textContent = 'Copy'; }, 1500);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(v).then(done).catch(done);
                } else {
                  try { uidEl.removeAttribute('readonly'); uidEl.select(); document.execCommand('copy'); uidEl.setAttribute('readonly', ''); } catch (e) {}
                  done();
                }
              });
            }

            var tzEl = document.getElementById('profile-timezone');
            if (tzEl) tzEl.value = _baseline.timezone;

            var wsEl = document.getElementById('profile-week-start');
            if (wsEl) wsEl.value = String(_baseline.week_start_day);

            var initialsEl = document.getElementById('settings-avatar-initials');
            if (initialsEl) {
              initialsEl.textContent = _initials(_baseline.display_name || row.user_name, row.user_email);
            }

            _updateSaveBtn();
          })
          .catch(function () {
            _setFeedback('Failed to load profile.', 'error');
          });
      }

      function _handleSave() {
        var btn = document.getElementById('profile-save-btn');
        _clearFieldErrors();
        _setFeedback('', '');

        var cur = _currentValues();
        var patch = {};
        if (cur.display_name !== (_baseline.display_name || '')) patch.display_name = cur.display_name;
        if (cur.timezone !== (_baseline.timezone || 'Asia/Bangkok')) patch.timezone = cur.timezone;
        if (cur.week_start_day !== (_baseline.week_start_day || 1)) patch.week_start_day = cur.week_start_day;
        if (cur.birth_date !== (_baseline.birth_date || null)) patch.birth_date = cur.birth_date;
        var baseHeight = _baseline.height_cm === undefined ? null : _baseline.height_cm;
        if (cur.height_cm !== baseHeight) patch.height_cm = cur.height_cm;
        if (cur.athlete_context !== (_baseline.athlete_context || '')) {
          patch.athlete_context = cur.athlete_context;
        }
        var baseZ2 = _baseline.weekly_zone2_target_min == null ? 150 : _baseline.weekly_zone2_target_min;
        if (cur.weekly_zone2_target_min !== baseZ2) patch.weekly_zone2_target_min = cur.weekly_zone2_target_min;

        if (!Object.keys(patch).length) return;

        if (btn) btn.disabled = true;
        fetch('/api/user-preferences', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
          .then(function (r) {
            if (!r.ok) {
              return r.json().then(function (d) { return Promise.reject(d); });
            }
            return r.json();
          })
          .then(function (saved) {
            _baseline = {
              display_name: saved.display_name || '',
              timezone: saved.timezone || 'Asia/Bangkok',
              week_start_day: saved.week_start_day || 1,
              birth_date: saved.birth_date || null,
              height_cm: saved.height_cm === undefined ? null : saved.height_cm,
              athlete_context: saved.athlete_context || '',
              weekly_zone2_target_min: saved.weekly_zone2_target_min == null ? 150 : saved.weekly_zone2_target_min,
            };
            var initialsEl = document.getElementById('settings-avatar-initials');
            if (initialsEl) {
              var emailEl = document.getElementById('profile-email');
              initialsEl.textContent = _initials(_baseline.display_name, emailEl ? emailEl.value : '');
            }
            _setFeedback('Saved.', 'success');
            _updateSaveBtn();
          })
          .catch(function (errData) {
            if (btn) btn.disabled = false;
            var detail = errData && errData.detail;
            if (Array.isArray(detail)) {
              detail.forEach(function (e) {
                var errElId = 'profile-' + (e.field || '').replace(/_/g, '-') + '-error';
                window._settingsSetFieldError(errElId, e.msg || 'Invalid value');
              });
              _setFeedback('Fix the errors above and try again.', 'error');
            } else {
              _setFeedback(typeof detail === 'string' ? detail : 'Save failed.', 'error');
            }
          });
      }

      ['profile-display-name', 'profile-timezone', 'profile-week-start',
        'profile-birth-date', 'profile-height-cm', 'profile-athlete-context',
        'profile-zone2-target'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('input', _updateSaveBtn);
        if (el) el.addEventListener('change', _updateSaveBtn);
      });

      var acInput = document.getElementById('profile-athlete-context');
      if (acInput) acInput.addEventListener('input', _updateContextCount);

      var saveBtn = document.getElementById('profile-save-btn');
      if (saveBtn) saveBtn.addEventListener('click', _handleSave);

      function _loadDevices() {
        var box = document.getElementById('profile-devices');
        if (!box) return;
        fetch('/api/mobile/devices')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var rows = (data && data.devices) || [];
            if (!rows.length) {
              box.textContent = 'No remembered devices.';
              return;
            }
            box.innerHTML = '';
            rows.forEach(function (d) {
              var row = document.createElement('div');
              row.className = 'profile-device-row';
              var last = d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : 'unknown';
              row.innerHTML = '<div><strong></strong><div class="rv-hint"></div></div>';
              row.querySelector('strong').textContent = d.label || 'Phone';
              row.querySelector('.rv-hint').textContent = 'Last seen ' + last;
              var btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'rv-btn rv-btn--ghost';
              btn.textContent = 'Sign out device';
              btn.addEventListener('click', function () {
                fetch('/api/mobile/devices/' + encodeURIComponent(d.id), { method: 'DELETE' })
                  .then(function () { _loadDevices(); });
              });
              row.appendChild(btn);
              box.appendChild(row);
            });
          })
          .catch(function () {
            box.textContent = '';
          });
      }

      window.addEventListener('userReady', function () {
        _loadPrefs();
        _loadDevices();
      });
}());
