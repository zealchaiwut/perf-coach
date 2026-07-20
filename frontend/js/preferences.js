/**
 * Preferences page — versioned training prefs + proposal lifecycle + JSON I/O.
 */
(function () {
  'use strict';

  var DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var _state = null;

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _fmtDay(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(String(iso).slice(0, 10) + 'T12:00:00');
      return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    } catch (e) {
      return String(iso).slice(0, 10);
    }
  }

  function _getNested(obj, field) {
    if (!obj) return null;
    if (field.indexOf('.') < 0) return obj[field];
    var parts = field.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (!cur || typeof cur !== 'object') return null;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function _setNested(obj, field, value) {
    if (field.indexOf('.') < 0) {
      obj[field] = value;
      return;
    }
    var parts = field.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]] || typeof cur[parts[i]] !== 'object') cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  function _provenance(active) {
    var src = active.source || 'user';
    var label = {
      user: 'you',
      user_import: 'you (import)',
      coach_proposal: 'coach proposal',
      carried_forward: 'carried forward',
    }[src] || src;
    var gap = active.origin_gap_code ? ' · ' + active.origin_gap_code : '';
    return label + ' · since v' + active.version + gap;
  }

  function _renderFields(active, catalog) {
    var root = document.getElementById('prefs-fields');
    if (!root) return;
    var p = active.payload || {};
    var html = '';

    // rest_days
    var days = _getNested(p, 'rest_days') || [];
    html +=
      '<div class="prefs-row">' +
        '<label>Rest days</label><div></div>' +
        '<div class="prefs-rest" id="field-rest_days">';
    for (var d = 0; d < 7; d++) {
      html +=
        '<label><input type="checkbox" value="' + d + '"' +
        (days.indexOf(d) >= 0 || days.indexOf(String(d)) >= 0 ? ' checked' : '') +
        '> ' + DOW[d] + '</label>';
    }
    html += '</div><div class="prefs-prov">' + esc(_provenance(active)) + '</div></div>';

    // strength_emphasis
    var se = _getNested(p, 'strength_emphasis') || 'same';
    html +=
      '<div class="prefs-row">' +
        '<label>Strength emphasis</label>' +
        '<select id="field-strength_emphasis">' +
          ['less', 'same', 'more'].map(function (v) {
            return '<option value="' + v + '"' + (se === v ? ' selected' : '') + '>' + v + '</option>';
          }).join('') +
        '</select>' +
        '<div class="prefs-prov">' + esc(_provenance(active)) + '</div></div>';

    // plyo_mode
    var pm = _getNested(p, 'plyo_mode') || 'off';
    html +=
      '<div class="prefs-row">' +
        '<label>Plyo mode</label>' +
        '<select id="field-plyo_mode">' +
          ['standalone', 'superset', 'off'].map(function (v) {
            return '<option value="' + v + '"' + (pm === v ? ' selected' : '') + '>' + v + '</option>';
          }).join('') +
        '</select>' +
        '<div class="prefs-prov">' + esc(_provenance(active)) + '</div></div>';

    function intRow(field, label) {
      var meta = (catalog && catalog[field]) || {};
      var val = _getNested(p, field);
      if (val == null) val = 0;
      var id = 'field-' + field.replace(/\./g, '_');
      html +=
        '<div class="prefs-row">' +
          '<label>' + esc(label) + '</label>' +
          '<input type="number" id="' + id + '" value="' + esc(val) + '"' +
            (meta.min != null ? ' min="' + meta.min + '"' : '') +
            (meta.max != null ? ' max="' + meta.max + '"' : '') +
            (meta.step != null ? ' step="' + meta.step + '"' : '') + '>' +
          '<div class="prefs-prov">' + esc(_provenance(active)) + '</div></div>';
    }

    intRow('plyo_sessions_per_week', 'Plyo sessions / week');
    intRow('long_run.mp_segment_min', 'Long-run MP segment (min)');
    intRow('stretch_daily_min', 'Daily stretch (min)');
    intRow('zone2_weekly_min', 'Zone-2 weekly target (min)');

    var notes = _getNested(p, 'notes') || '';
    html +=
      '<div class="prefs-row" style="grid-template-columns:1fr">' +
        '<label>Notes</label>' +
        '<textarea class="prefs-notes" id="field-notes" maxlength="200">' + esc(notes) + '</textarea>' +
        '<div class="prefs-prov">' + esc(_provenance(active)) + '</div></div>';

    root.innerHTML = html;
  }

  function _collectPayload() {
    var payload = {};
    var rest = [];
    document.querySelectorAll('#field-rest_days input:checked').forEach(function (el) {
      rest.push(Number(el.value));
    });
    payload.rest_days = rest;
    payload.strength_emphasis = document.getElementById('field-strength_emphasis').value;
    payload.plyo_mode = document.getElementById('field-plyo_mode').value;
    payload.plyo_sessions_per_week = Number(document.getElementById('field-plyo_sessions_per_week').value);
    _setNested(payload, 'long_run.mp_segment_min', Number(document.getElementById('field-long_run_mp_segment_min').value));
    payload.stretch_daily_min = Number(document.getElementById('field-stretch_daily_min').value);
    payload.zone2_weekly_min = Number(document.getElementById('field-zone2_weekly_min').value);
    payload.notes = document.getElementById('field-notes').value || '';
    return payload;
  }

  function _flightGlyph(status) {
    if (status === 'proposed') return '● PROPOSED';
    if (status === 'declined') return '◌ COOLDOWN';
    if (status === 'accepted') return '✓ ACTIVE';
    if (status === 'expired') return '○ EXPIRED';
    if (status === 'reverted') return '↩ REVERTED';
    return status;
  }

  function _renderInflight(proposals) {
    var root = document.getElementById('prefs-inflight');
    if (!root) return;
    var items = (proposals || []).filter(function (p) {
      return p && p.status !== 'expired'; // show settled lifecycle too except pure expired noise
    });
    if (!items.length) {
      root.innerHTML = '<div class="prefs-flight-item">Nothing in flight.</div>';
      return;
    }
    root.innerHTML = items.map(function (p) {
      var delta = p.delta || {};
      var line =
        '<strong>' + esc(_flightGlyph(p.status)) + '</strong> · ' +
        esc(delta.field || p.gap_code) + ': ' +
        esc(delta.from) + ' → ' + esc(delta.to);
      if (p.status === 'proposed' && p.expires_at) {
        line += ' · expires ' + esc(_fmtDay(p.expires_at));
      }
      if (p.status === 'declined' && p.decided_at) {
        line += ' · quiet until ' + esc(_fmtDay(new Date(new Date(p.decided_at).getTime() + 28 * 86400000).toISOString()));
      }
      if (p.review_outcome) {
        line += ' · ' + esc(String(p.review_outcome).replace(/_/g, ' '));
        if (p.review_outcome === 'gap_closed') line += ' · kept';
      }
      return '<div class="prefs-flight-item">' + line + '</div>';
    }).join('');
  }

  function _showErr(msg) {
    var el = document.getElementById('prefs-err');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = typeof msg === 'object' ? JSON.stringify(msg, null, 2) : String(msg);
  }

  function _apply(data) {
    _state = data;
    var active = data.active || {};
    document.getElementById('prefs-meta').textContent =
      'v' + active.version + ' · effective ' + _fmtDay(active.effective_from) +
      (active.confirmed_at ? ' · confirmed ' + _fmtDay(active.confirmed_at) : ' · not confirmed');
    var stale = document.getElementById('prefs-stale');
    if (stale) stale.hidden = !active.stale;
    _renderFields(active, data.catalog);
    _renderInflight(data.proposals);
  }

  function load() {
    return fetch('/api/preferences', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to load preferences');
        return r.json();
      })
      .then(_apply)
      .catch(function (e) {
        document.getElementById('prefs-meta').textContent = e.message || 'Error';
      });
  }

  function save() {
    _showErr(null);
    var payload = _collectPayload();
    fetch('/api/preferences', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: payload }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw j.detail || j;
          return j;
        });
      })
      .then(function () { return load(); })
      .catch(function (e) { _showErr(e); });
  }

  function confirm() {
    fetch('/api/preferences/confirm', { method: 'POST', credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('Confirm failed');
        return load();
      })
      .catch(function (e) { _showErr(e.message); });
  }

  function exportJson() {
    window.location.href = '/api/preferences/export';
  }

  function importJson(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var raw;
      try {
        raw = JSON.parse(reader.result);
      } catch (e) {
        _showErr('Invalid JSON');
        return;
      }
      fetch('/api/preferences/import', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(raw),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw j.detail || j;
            return j;
          });
        })
        .then(function () { return load(); })
        .catch(function (e) { _showErr(e); });
    };
    reader.readAsText(file);
  }

  function copyAiTemplate() {
    fetch('/api/preferences/ai-template', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to load template');
        return r.text();
      })
      .then(function (text) {
        return navigator.clipboard.writeText(text);
      })
      .then(function () {
        var btn = document.getElementById('prefs-ai-template');
        if (btn) {
          var prev = btn.textContent;
          btn.textContent = 'Copied';
          setTimeout(function () { btn.textContent = prev; }, 1500);
        }
      })
      .catch(function (e) { _showErr(e.message || e); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('prefs-save').addEventListener('click', save);
    document.getElementById('prefs-confirm').addEventListener('click', confirm);
    document.getElementById('prefs-export').addEventListener('click', exportJson);
    document.getElementById('prefs-import').addEventListener('change', function (e) {
      var f = e.target.files && e.target.files[0];
      importJson(f);
      e.target.value = '';
    });
    document.getElementById('prefs-ai-template').addEventListener('click', copyAiTemplate);
    load();
  });
})();
