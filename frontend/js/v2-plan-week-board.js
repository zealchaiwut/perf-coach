(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  function toast(msg) {
    if (window.RevampUI && window.RevampUI.showToast) {
      window.RevampUI.showToast(msg);
    }
  }

  function cardClass(item) {
    var kind = (item.kind || item.session_type || '').toLowerCase();
    if (item.kind === 'rest') return 'rv-sess--rest';
    if (kind.indexOf('race') >= 0) return 'rv-sess--race';
    if (kind === 'quality_run') return 'rv-sess--quality';
    if (kind === 'run') return 'rv-sess--run';
    return 'rv-sess--support';
  }

  function sessionCard(item) {
    var locked = item.locked || item.plan_source === 'coach';
    var kind = (item.kind || item.session_type || '').toLowerCase();
    var isRace = kind.indexOf('race') >= 0;
    var who = locked ? 'COACH · LOCKED' : (isRace ? 'RACE' : 'SUPPORT');
    var whoCls = locked ? 'rv-sess-who--coach' : (isRace ? 'rv-sess-who--race' : 'rv-sess-who--support');
    var cls = 'rv-sess rv-session ' + cardClass(item) + (locked ? ' rv-session--locked rv-sess--locked' : '');
    var drag = locked ? '' : ' draggable="true"';
    var meta = [];
    if (item.estimated_tss != null) meta.push(Math.round(item.estimated_tss) + ' TSS');
    return (
      '<article class="' + cls + '"' + drag +
      ' data-id="' + esc(item.id) + '" data-date="' + esc(item.planned_date) + '"' +
      ' data-locked="' + (locked ? '1' : '0') + '" tabindex="0">' +
      '<span class="rv-sess-who ' + whoCls + '">' + esc(who) + '</span>' +
      '<span class="rv-sess-title">' + esc(item.name) + '</span>' +
      (meta.length ? '<span class="rv-sess-meta">' + esc(meta.join(' · ')) + '</span>' : '') +
      (!locked ? (
        '<div class="rv-week-card-actions">' +
        '<button type="button" class="rv-sess-edit" data-edit-id="' + esc(item.id) + '">Edit</button>' +
        '<label class="sr-only">Move <select class="rv-move-select" data-move-id="' + esc(item.id) + '" aria-label="Move to day">' +
        '</select></label>' +
        '</div>'
      ) : '') +
      '</article>'
    );
  }

  function mount(host, options) {
    var state = { weekStart: options.weekStart, dragId: null, onWeekChanged: options.onWeekChanged };
    var loadGen = 0;

    function weekQuery() {
      return '?week_start=' + encodeURIComponent(state.weekStart);
    }

    function friendlyBoardError(r) {
      if (!r) return 'Could not load this week. Check your connection.';
      if (r.status === 401 || r.status === 403) return 'Session expired — refresh and try again.';
      return 'Could not load this week. Try again.';
    }

    function load() {
      var gen = ++loadGen;
      return fetch('/api/plan/revamp-week-board' + weekQuery(), { credentials: 'include' })
        .then(function (r) {
          if (!r.ok) throw new Error(friendlyBoardError(r));
          return r.json();
        })
        .then(function (data) {
          if (gen !== loadGen) return null;
          return data;
        });
    }

    function tssNavLine(wl) {
      if (!wl) return '';
      var tot = Math.round((wl.logged_tss || 0) + (wl.planned_tss || 0));
      var tgt = Math.round(wl.target_tss || 0);
      var st = 'on target';
      if (wl.headroom_state === 'over_ceiling') st = 'over ceiling';
      else if (wl.headroom_state === 'over_target') st = 'over target';
      return tot + ' / ' + tgt + ' TSS · ' + st;
    }

    function loadWeekLoad() {
      var gen = loadGen;
      return fetch('/api/plan/revamp-week-load' + weekQuery(), { credentials: 'include' })
        .then(function (r) {
          if (r.status === 204) return null;
          if (!r.ok) throw new Error(friendlyBoardError(r));
          return r.json();
        })
        .then(function (wl) {
          if (gen !== loadGen) return null;
          state.lastWl = wl;
          if (wl && options.weekLoadEl && options.renderWeekLoad) {
            options.renderWeekLoad(options.weekLoadEl, wl);
          }
          var tssEl = document.getElementById('v2-week-nav-tss');
          if (tssEl) tssEl.textContent = tssNavLine(wl);
          return wl;
        })
        .catch(function (e) {
          if (gen !== loadGen) return null;
          if (options.weekLoadEl && window.V2TrainingPlan && window.V2TrainingPlan.sectionError) {
            window.V2TrainingPlan.sectionError(
              options.weekLoadEl,
              "This week's load",
              e.message || friendlyBoardError(),
              loadWeekLoad
            );
          }
          return null;
        });
    }

    function dayNum(iso) {
      var p = String(iso || '').split('-');
      return p.length === 3 ? String(parseInt(p[2], 10)) : iso;
    }

    function fmtWeekOf(start, end) {
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      var a = String(start || '').split('-');
      var b = String(end || start || '').split('-');
      var ad = parseInt(a[2], 10);
      var bd = parseInt(b[2], 10);
      var am = parseInt(a[1], 10);
      var bm = parseInt(b[1], 10);
      if (!am) return start;
      if (am === bm) return ad + ' – ' + bd + ' ' + months[am - 1];
      return ad + ' ' + months[am - 1] + ' – ' + bd + ' ' + months[bm - 1];
    }

    function render(data) {
      var headHost = document.getElementById('v2-plan-week-head') || host;
      var boardHost = document.getElementById('v2-plan-week-board') || host;
      var head =
        '<div class="rv-card rv-week-nav">' +
        '<div class="rv-week-nav-left">' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-prev" aria-label="Previous week">‹</button>' +
        '<span class="rv-week-nav-title">Week of ' + esc(fmtWeekOf(data.week_start, data.week_end)) + '</span>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-next" aria-label="Next week">›</button>' +
        '<span class="rv-week-nav-tss" id="v2-week-nav-tss">' + esc(tssNavLine(state.lastWl)) + '</span>' +
        '</div>' +
        '<div class="rv-week-nav-actions">' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-coach-import-open">Import coach week</button>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-new">+ New session</button>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-export">Export</button>' +
        '</div></div>';
      var cols = data.days.map(function (day) {
        var colCls = 'rv-week-col' + (day.rest_placeholder ? ' rv-week-col--rest' : '');
        var body = day.items.map(sessionCard).join('');
        if (day.rest_placeholder && !day.items.length) {
          body += '<div class="rv-sess rv-sess--restday">Rest day</div>';
        }
        return (
          '<div class="' + colCls + '" data-date="' + esc(day.date) + '" data-weekday="' + day.weekday + '">' +
          '<div class="rv-week-col-head"><span class="rv-week-dh">' + esc((day.label || '').toUpperCase()) +
          ' <span class="rv-week-dn">' + esc(dayNum(day.date)) + '</span></span>' +
          '<button type="button" class="rv-btn rv-btn--ghost-plus" data-add-date="' + esc(day.date) + '" title="Add session">+</button></div>' +
          '<div class="rv-week-col-body">' + body + '</div></div>'
        );
      }).join('');
      var suggestBar =
        '<button type="button" class="rv-suggest-banner" id="v2-suggest-open">' +
        '<span class="rv-suggest-copy"><span class="rv-suggest-title">Suggest sessions</span>' +
        '<span class="rv-suggest-sub">fill the gap to target · mobility and drills · respects rest days</span></span>' +
        '<span class="rv-suggest-chevron" aria-hidden="true">›</span></button>' +
        '<div id="v2-suggest-panel" class="rv-card rv-stack" hidden></div>';
      var boardCard =
        '<div class="rv-card rv-week-board-card">' +
        '<div class="rv-week-board">' + cols + '</div>' +
        '<p class="rv-week-board-note">Coach sessions are locked. Drag support sessions between days, or click one to edit its exercises — the totals above update as you go.</p>' +
        '</div>';
      if (headHost !== boardHost) {
        headHost.innerHTML = head + suggestBar;
        boardHost.innerHTML = boardCard;
      } else {
        boardHost.innerHTML = head + suggestBar + boardCard;
      }

      function q(sel) {
        return headHost.querySelector(sel) || boardHost.querySelector(sel);
      }

      boardHost.querySelectorAll('.rv-move-select').forEach(function (sel) {
        data.days.forEach(function (d) {
          var opt = document.createElement('option');
          opt.value = d.date;
          opt.textContent = d.label;
          sel.appendChild(opt);
        });
      });

      var prev = q('#v2-week-prev');
      var next = q('#v2-week-next');
      if (prev) prev.onclick = function () { shiftWeek(-7); };
      if (next) next.onclick = function () { shiftWeek(7); };
      function openNew(d) {
        if (window.V2SessionEditor && window.V2SessionEditor.openPlanned) {
          window.V2SessionEditor.openPlanned({
            plannedDate: d,
            weekStart: data.week_start,
            onSaved: refresh,
          });
        }
      }
      boardHost.querySelectorAll('[data-add-date]').forEach(function (btn) {
        btn.onclick = function () { openNew(btn.getAttribute('data-add-date')); };
      });
      var newBtn = q('#v2-week-new');
      if (newBtn) {
        newBtn.onclick = function () { openNew(data.week_start); };
      }
      var expBtn = q('#v2-week-export');
      if (expBtn) {
        expBtn.onclick = function () {
          var lines = ['Week of ' + fmtWeekOf(data.week_start, data.week_end)];
          (data.days || []).forEach(function (d) {
            var names = (d.items || []).map(function (it) { return it.name; }).join(', ');
            lines.push((d.label || d.date) + ': ' + (names || 'rest'));
          });
          var text = lines.join('\n');
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () { toast('Week copied'); });
          }
        };
      }
      boardHost.querySelectorAll('[data-edit-id]').forEach(function (btn) {
        btn.onclick = function (ev) {
          ev.stopPropagation();
          var id = btn.getAttribute('data-edit-id');
          var card = boardHost.querySelector('[data-id="' + id + '"]');
          var d = card ? card.getAttribute('data-date') : data.week_start;
          if (window.V2SessionEditor && window.V2SessionEditor.openPlanned) {
            window.V2SessionEditor.openPlanned({
              sessionId: id,
              plannedDate: d,
              weekStart: data.week_start,
              onSaved: refresh,
            });
          }
        };
      });
      bindDnD(boardHost, data);
      bindCoachPopover(boardHost);
      bindKeyboardMove(boardHost);
      bindCoachImport(headHost, data);
      bindSuggestFill(headHost, data);
    }

    function bindSuggestFill(host, data) {
      var open = host.querySelector('#v2-suggest-open');
      var panel = host.querySelector('#v2-suggest-panel');
      if (!open || !panel) return;
      open.onclick = function () {
        var post = window.AppCommon && window.AppCommon.fetchWithCsrf
          ? window.AppCommon.fetchWithCsrf
          : function (u, o) { return fetch(u, o); };
        post('/api/plan/revamp-suggest/preview' + weekQuery(), {
          method: 'POST',
          credentials: 'include',
        }).then(function (r) {
          if (!r.ok) throw new Error(r.status === 403 ? 'Session expired — refresh and try again' : 'Suggest failed (' + r.status + ')');
          return r.json();
        }).then(function (payload) {
          panel.hidden = false;
          if (!payload.proposed || !payload.proposed.length) {
            panel.innerHTML = '<p class="rv-subtitle">' + esc(payload.message || 'Nothing to suggest.') + '</p>';
            return;
          }
          var rows = payload.proposed.map(function (p) {
            return '<li>' + esc(p.planned_date) + ' · ' + esc(p.name) + ' · ' + esc(String(p.estimated_tss)) + ' TSS</li>';
          }).join('');
          panel.innerHTML =
            '<p class="rv-subtitle">Gap ' + esc(String(payload.gap_tss)) + ' TSS → target ' + esc(String(payload.target_tss)) + '</p>' +
            '<ul class="rv-subtitle">' + rows + '</ul>' +
            '<button type="button" class="rv-btn" id="v2-suggest-apply">Apply suggestions</button>';
          panel.querySelector('#v2-suggest-apply').onclick = function () {
            post('/api/plan/revamp-suggest/apply', {
              method: 'POST',
              credentials: 'include',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ proposed: payload.proposed }),
            }).then(function (r) {
              if (!r.ok) throw new Error('Could not apply suggestions. Try again.');
              return r.json();
            }).then(function () {
              panel.hidden = true;
              refresh();
            }).catch(function (e) {
              panel.hidden = false;
              panel.innerHTML = '<p class="rv-subtitle" role="alert">' + esc(e.message || 'Could not apply suggestions.') + '</p>';
              toast(e.message || 'Could not apply suggestions');
            });
          };
        }).catch(function (e) {
          panel.hidden = false;
          panel.innerHTML = '<p class="rv-subtitle" role="alert">' + esc(e.message || 'Could not suggest sessions.') + '</p>';
          toast(e.message || 'Could not suggest sessions');
        });
      };
    }

    function bindCoachImport(host, data) {
      var openBtn = host.querySelector('#v2-coach-import-open');
      var panel = document.getElementById('v2-coach-import');
      var backdrop = document.getElementById('v2-coach-import-backdrop');
      var text = document.getElementById('v2-coach-import-text');
      var preview = document.getElementById('v2-coach-import-preview');
      var parseBtn = document.getElementById('v2-coach-import-parse');
      var commitBtn = document.getElementById('v2-coach-import-commit');
      var cancelBtn = document.getElementById('v2-coach-import-cancel');
      var photoInput = document.getElementById('v2-coach-import-photo');
      var photoHint = document.getElementById('v2-coach-import-photo-hint');
      var photoWrap = document.getElementById('v2-coach-import-photo-wrap');
      var photoCaps = null;
      var parsedRows = [];

      function close() {
        if (panel) panel.hidden = true;
        if (backdrop) backdrop.hidden = true;
      }
      function show() {
        if (panel) panel.hidden = false;
        if (backdrop) backdrop.hidden = false;
        parsedRows = [];
        if (commitBtn) commitBtn.disabled = true;
        if (preview) preview.innerHTML = '';
        fetch('/api/plan/coach-week-import/photo-capabilities', { credentials: 'include' })
          .then(function (r) { return r.json(); })
          .then(function (caps) {
            photoCaps = caps;
            if (photoHint) photoHint.textContent = caps.message || '';
            if (photoWrap) photoWrap.hidden = false;
            if (photoInput) {
              photoInput.disabled = !caps.vision_enabled;
            }
          })
          .catch(function () {
            if (photoHint) photoHint.textContent = '';
          });
      }
      if (openBtn) openBtn.onclick = show;
      if (cancelBtn) cancelBtn.onclick = close;
      if (backdrop) backdrop.onclick = close;

      function renderPreview(payload) {
        parsedRows = payload.rows || [];
        if (!preview) return;
        if (!payload.commit_allowed) {
          preview.innerHTML = '<p class="rv-subtitle" style="color:#b91c1c">Fix unparsed lines before import.</p>';
          if (commitBtn) commitBtn.disabled = true;
        } else if (commitBtn) {
          commitBtn.disabled = false;
        }
        var html = ['<table class="rv-subtitle" style="width:100%"><thead><tr><th>Day</th><th>Name</th><th>TSS</th><th></th></tr></thead><tbody>'];
        parsedRows.forEach(function (row, idx) {
          if (row.parse_status !== 'ok') {
            html.push('<tr><td colspan="4" style="color:#b91c1c">Unparsed: ' + esc(row.raw) + '</td></tr>');
            return;
          }
          var flag = row.inferred ? ' <span style="color:#b45309">inferred</span>' : '';
          html.push(
            '<tr data-idx="' + idx + '"><td>' + esc(row.planned_date) + '</td>' +
            '<td><input class="rv-input" data-field="name" value="' + esc(row.name) + '"></td>' +
            '<td><input class="rv-input" data-field="target_tss" style="width:72px" value="' + esc(String(row.target_tss)) + '"></td>' +
            '<td>' + flag + '</td></tr>'
          );
        });
        html.push('</tbody></table>');
        preview.innerHTML = html.join('');
        preview.querySelectorAll('tr[data-idx]').forEach(function (tr) {
          var i = parseInt(tr.getAttribute('data-idx'), 10);
          tr.querySelectorAll('input').forEach(function (inp) {
            inp.addEventListener('change', function () {
              var field = inp.getAttribute('data-field');
              if (field === 'target_tss') parsedRows[i].target_tss = parseFloat(inp.value, 10);
              else parsedRows[i][field] = inp.value;
            });
          });
        });
      }

      if (photoInput) {
        photoInput.onchange = function () {
          var file = photoInput.files && photoInput.files[0];
          if (!file || !photoCaps || !photoCaps.vision_enabled) return;
          var fd = new FormData();
          fd.append('file', file);
          fetch('/api/plan/coach-week-import/parse-photo?week_start=' + encodeURIComponent(data.week_start), {
            method: 'POST',
            credentials: 'include',
            body: fd,
          })
            .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
            .then(function (res) {
              if (!res.ok && !res.body.rows) {
                if (photoHint) photoHint.textContent = res.body.message || 'Photo import unavailable.';
                return;
              }
              renderPreview(res.body);
            });
        };
      }
      if (parseBtn) {
        parseBtn.onclick = function () {
          fetch('/api/plan/coach-week-import/parse', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ week_start: data.week_start, text: text ? text.value : '' }),
          }).then(function (r) {
            if (!r.ok) throw new Error('Could not parse coach week. Try again.');
            return r.json();
          }).then(renderPreview).catch(function (e) {
            if (preview) preview.innerHTML = '<p class="rv-subtitle" role="alert">' + esc(e.message || 'Could not parse coach week.') + '</p>';
            toast(e.message || 'Could not parse coach week');
          });
        };
      }
      if (commitBtn) {
        commitBtn.onclick = function () {
          fetch('/api/plan/coach-week-import/commit', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ week_start: data.week_start, rows: parsedRows }),
          }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw d; });
            return r.json();
          }).then(function () {
            close();
            refresh();
          }).catch(function () { toast('Import blocked — fix unparsed rows.'); });
        };
      }
    }

    function shiftWeek(days) {
      var ac = window.AppCommon || {};
      state.weekStart = ac.addDaysISO ? ac.addDaysISO(state.weekStart, days) : state.weekStart;
      if (state.onWeekChanged) state.onWeekChanged(state.weekStart);
      refresh();
    }

    function showBoardError(msg) {
      var boardHost = document.getElementById('v2-plan-week-board') || host;
      boardHost.innerHTML =
        '<div class="rv-card rv-plan-section-error" role="alert">' +
        '<p class="rv-subtitle">' + esc(msg) + '</p>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-board-retry">Retry</button></div>';
      var btn = boardHost.querySelector('#v2-board-retry');
      if (btn) btn.onclick = refresh;
    }

    function refresh() {
      load().then(function (data) {
        if (!data) return;
        render(data);
        return loadWeekLoad();
      }).catch(function (e) {
        showBoardError(e.message || friendlyBoardError());
      });
    }

    function ruleEvaluate(id, targetDate, cb) {
      fetch('/api/plan/rule-evaluate', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'move', session_id: id, planned_date: targetDate }),
      }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
        .then(cb);
    }

    function patchMove(id, targetDate, confirmWarnings, cb) {
      fetch('/api/planned-sessions/' + id, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ planned_date: targetDate, confirm_warnings: !!confirmWarnings }),
      }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
        .then(cb);
    }

    function applyMove(id, targetDate) {
      ruleEvaluate(id, targetDate, function (ev) {
        if (ev.body.level === 'block') {
          var msg = (ev.body.results && ev.body.results[0] && ev.body.results[0].message) || 'Move blocked';
          toast(msg);
          refresh();
          return;
        }
        function doPatch(confirm) {
          patchMove(id, targetDate, confirm, function (res) {
            if (res.status === 409 && res.body.needs_confirm) {
              var warn = (res.body.plan_rules && res.body.plan_rules[0] && res.body.plan_rules[0].message) || 'Confirm move?';
              if (window.confirm(warn)) doPatch(true);
              else refresh();
              return;
            }
            if (res.status >= 400) {
              toast('Could not move session');
              refresh();
              return;
            }
            refresh();
          });
        }
        doPatch(ev.body.level !== 'warn');
      });
    }

    function bindDnD(host, data) {
      host.querySelectorAll('.rv-session[draggable="true"]').forEach(function (card) {
        card.addEventListener('dragstart', function (ev) {
          state.dragId = card.getAttribute('data-id');
          ev.dataTransfer.setData('text/plain', state.dragId);
        });
      });
      host.querySelectorAll('.rv-week-col').forEach(function (col) {
        col.addEventListener('dragover', function (ev) { ev.preventDefault(); });
        col.addEventListener('drop', function (ev) {
          ev.preventDefault();
          var id = ev.dataTransfer.getData('text/plain') || state.dragId;
          var target = col.getAttribute('data-date');
          if (id && target) applyMove(id, target);
        });
      });
    }

    function bindCoachPopover(host) {
      var backdrop = document.getElementById('v2-coach-popover-backdrop');
      var pop = document.getElementById('v2-coach-popover');
      var body = document.getElementById('v2-coach-popover-body');
      var closeBtn = document.getElementById('v2-coach-popover-close');
      function close() {
        if (backdrop) backdrop.hidden = true;
        if (pop) pop.hidden = true;
      }
      if (closeBtn) closeBtn.onclick = close;
      if (backdrop) backdrop.onclick = close;
      host.querySelectorAll('.rv-session--locked').forEach(function (card) {
        card.addEventListener('click', function () {
          var id = card.getAttribute('data-id');
          var item = null;
          data.days.forEach(function (d) {
            d.items.forEach(function (it) { if (it.id === id) item = it; });
          });
          if (!item) return;
          if (body) body.textContent = item.notes || 'No notes for this coach session.';
          if (backdrop) backdrop.hidden = false;
          if (pop) pop.hidden = false;
        });
      });
    }

    function bindKeyboardMove(host) {
      host.querySelectorAll('.rv-move-select').forEach(function (sel) {
        sel.addEventListener('change', function () {
          var id = sel.getAttribute('data-move-id');
          var target = sel.value;
          var card = host.querySelector('[data-id="' + id + '"]');
          var origin = card ? card.getAttribute('data-date') : null;
          if (target && id && target !== origin) {
            applyMove(id, target);
          }
          sel.selectedIndex = 0;
        });
      });
    }

    refresh();
  }

  window.V2PlanWeekBoard = { mount: mount };
})();