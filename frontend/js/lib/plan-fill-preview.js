/* Shared pattern-fill preview pane (admin Plan library + Plan suggestions).
 * One layout: exercises/blocks table | muscle TSS, then pick-by-pick budget.
 * window.PlanFillPreview — load before admin-plan-library.js / training-plan.js.
 */
(function (global) {
  'use strict';

  var STYLE_ID = 'plan-fill-preview-css';
  var STYLE_VER = '20260806align1';

  function esc(s) {
    if (global.AppCommon && typeof global.AppCommon.escapeHtml === 'function') {
      return global.AppCommon.escapeHtml(s);
    }
    // AppCommon is required — never re-implement entity substitution here
    // (see tests/test_frontend_shared_lib__1603.py).
    return String(s == null ? '' : s);
  }

  var CSS = [
    '.preview-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(220px,0.7fr);gap:16px;align-items:start;margin-top:4px;min-width:0;}',
    '@media (max-width:900px){.preview-layout{grid-template-columns:1fr;}}',
    '.preview-pane{background:#fff;border:1px solid var(--border);border-radius:12px;padding:12px 14px 14px;min-width:0;}',
    '.preview-pane-h{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);margin:0 0 10px;}',
    '.preview-ex-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12.5px;}',
    '.preview-ex-table th,.preview-ex-table td{text-align:left;padding:8px 10px;border-bottom:1px solid rgba(0,0,0,0.06);vertical-align:top;}',
    '.preview-ex-table th{font-size:10px;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);font-weight:800;}',
    /* Col widths: keep Prescription/Min/TSS from drifting to the far right */
    '.preview-ex-table th:nth-child(1),.preview-ex-table td:nth-child(1){width:38%;}',
    '.preview-ex-table th:nth-child(2),.preview-ex-table td:nth-child(2){width:34%;}',
    '.preview-ex-table th:nth-child(3),.preview-ex-table td:nth-child(3){width:14%;}',
    '.preview-ex-table th:nth-child(4),.preview-ex-table td:nth-child(4){width:14%;}',
    '.preview-ex-table td.rx{overflow-wrap:anywhere;}',
    '.preview-ex-table td.num,.preview-ex-table th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}',
    '.preview-ex-table tfoot td{font-weight:700;border-bottom:none;padding-top:10px;}',
    '.preview-block-sec{margin:0 0 12px;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:#fff;}',
    '.preview-block-sec:last-of-type{margin-bottom:8px;}',
    '.preview-block-h{padding:7px 10px;background:#f7f8fa;border-bottom:1px solid var(--border);font-size:10px;font-weight:800;letter-spacing:0.04em;text-transform:uppercase;color:var(--text-sub);}',
    '.preview-block-sec .preview-ex-table{margin:0;}',
    '.preview-block-sec .preview-ex-table th,.preview-block-sec .preview-ex-table td{padding:7px 10px;}',
    '.preview-block-sec .preview-ex-table thead th{background:#fff;}',
    '.preview-spend{display:flex;justify-content:space-between;gap:12px;padding:8px 4px 0;font-size:12.5px;font-weight:700;border-top:1px solid var(--border);margin-top:4px;}',
    '.preview-spend .num{font-variant-numeric:tabular-nums;white-space:nowrap;}',
    '.preview-side{display:block;position:sticky;top:12px;min-width:0;}',
    '@media (max-width:900px){.preview-side{position:static;}}',
    '.muscle-tss-table{width:100%;border-collapse:collapse;font-size:12px;}',
    '.muscle-tss-table th,.muscle-tss-table td{padding:5px 8px;border-bottom:1px solid rgba(0,0,0,0.06);}',
    '.muscle-tss-table th{font-size:10px;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);text-align:left;}',
    '.muscle-tss-table td.num,.muscle-tss-table th.num{text-align:right;}',
    '.muscle-tss-table tfoot td{font-weight:700;border-bottom:none;border-top:1px solid var(--border);}',
    '.muscle-bar{display:block;height:4px;margin-top:3px;border-radius:2px;background:#fdba74;max-width:100%;}',
    '.budget-trace-block{margin-top:10px;min-width:0;max-width:100%;clear:both;}',
    '.budget-trace-list{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;line-height:1.6;max-height:min(50vh,480px);overflow:auto;padding:0 0 8px;}',
    '.bt-group{border:1px solid var(--border);border-radius:9px;margin-bottom:7px;overflow:hidden;background:#fff;}',
    '.bt-group-skip{opacity:0.72;}',
    '.bt-group-h{padding:6px 10px;background:#f7f8fa;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:10px;font-weight:700;letter-spacing:0.04em;color:var(--text-sub);}',
    '.bt-group-label{font-weight:700;color:var(--text-sub);letter-spacing:0.04em;text-transform:none;}',
    '.bt-group-meta{font-weight:700;color:var(--text-sub);text-align:right;}',
    '.bt-picks{display:block;}',
    '.bt-pick{padding:7px 10px;border-bottom:1px solid #f1f2f5;background:#fff;}',
    '.bt-pick:last-child{border-bottom:none;}',
    '.bt-name{display:block;font-family:inherit;font-size:12.5px;font-weight:700;color:var(--ink);line-height:1.35;}',
    '.bt-rx{display:block;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;color:var(--text-sub);margin-top:2px;line-height:1.5;}',
    '.bt-spend-val{color:var(--primary,#2563eb);font-weight:600;}',
    '.bt-score-line{display:block;margin-top:2px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;color:var(--text-sub);line-height:1.5;}',
    '.bt-score{color:#7c3aed;font-weight:700;}',
    '.bt-bias,.bt-rand{color:var(--text-sub);font-weight:600;}',
    '.bt-alts{display:block;margin-top:3px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:9.5px;color:#9ca3af;line-height:1.45;}',
    '.bt-remain{display:block;margin-top:3px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10px;color:#9ca3af;line-height:1.4;}',
    '.bt-start,.bt-end,.bt-exhausted,.bt-inline{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;color:#9ca3af;padding:4px 2px 8px;}',
    '.bt-end{margin-top:2px;padding:7px 10px;background:#f7f8fa;border-radius:8px;color:var(--text-sub);font-weight:600;}',
    '.bt-exhausted{padding:7px 10px;margin-bottom:7px;background:#fffbeb;border:1px solid #fcd34d;border-radius:9px;color:#92400e;font-weight:600;}',
    '.bt-note{color:#9ca3af;}',
    '.plan-fill-preview-wrap .muted,.preview-layout .muted{color:var(--text-sub);}',
  ].join('\n');

  function ensureStyles() {
    if (typeof document === 'undefined') return;
    var existing = document.getElementById(STYLE_ID);
    if (existing && existing.getAttribute('data-ver') === STYLE_VER) return;
    if (existing) existing.remove();
    var el = document.createElement('style');
    el.id = STYLE_ID;
    el.setAttribute('data-ver', STYLE_VER);
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  function budgetRemainHtml(tss, mins, note) {
    return '<div class="bt-remain">remaining ' + esc(tss) + ' TSS · ' + esc(mins) + ' min' +
      (note ? ' <span class="bt-note">[' + esc(note) + ']</span>' : '') +
      '</div>';
  }

  function poolCountIndex(poolCounts) {
    var byKey = {};
    var byLabel = {};
    ((poolCounts && poolCounts.blocks) || []).forEach(function (b) {
      if (b.key) byKey[b.key] = b;
      if (b.label) byLabel[b.label] = b;
    });
    return { byKey: byKey, byLabel: byLabel };
  }

  function poolInCount(idx, ev) {
    var b = null;
    if (ev.key && idx.byKey[ev.key]) b = idx.byKey[ev.key];
    else if (ev.label && idx.byLabel[ev.label]) b = idx.byLabel[ev.label];
    return b && b.matched_count != null ? b.matched_count : null;
  }

  function pickSpendLine(ev) {
    var spend = '<span class="bt-spend-val">' + esc(ev.spend_min) + ' min, ' +
      esc(ev.spend_tss) + ' TSS</span>';
    var isRun = ev.kind === 'run' || (ev.sets == null && (ev.pace_mult != null || ev.duration_min != null));
    if (isRun) {
      var bits = [];
      var rep = ev.repeat != null ? Number(ev.repeat) : 0;
      var per = ev.duration_min != null ? Number(ev.duration_min) : null;
      if (rep > 1 && per != null) bits.push(rep + ' × ' + per + ' min');
      else if (per != null) bits.push(per + ' min');
      else if (ev.block_min != null) bits.push(ev.block_min + ' min');
      if (ev.target) bits.push(String(ev.target));
      if (ev.rest_min != null && rep > 1) bits.push(ev.rest_min + ' min rest');
      return bits.join(' · ') + ' → ' + spend;
    }
    return (ev.sets != null ? ev.sets : '?') + ' × ' + (ev.reps || '?') +
      (ev.load ? ' · ' + ev.load : '') + ' → ' + spend;
  }

  function pickScoreLine(ev) {
    if (ev.score != null && ev.bias != null && ev.random != null) {
      return '<div class="bt-score-line">score <span class="bt-score">' + esc(ev.score) +
        '</span> = bias ' + esc(ev.bias) + ' × random ' + esc(ev.random) + '</div>';
    }
    if (ev.pace_mult != null) {
      var pace = Number(ev.pace_mult);
      var line = 'pace ×' + (isFinite(pace) ? pace.toFixed(2) : esc(ev.pace_mult)) + ' threshold';
      if (ev.target) line += ' · ' + ev.target;
      return '<div class="bt-score-line">' + esc(line) + '</div>';
    }
    return '';
  }

  function budgetTraceHtml(trace, poolCounts) {
    if (!trace || !trace.length) return '';
    var idx = poolCountIndex(poolCounts);
    var html = [];
    var groupOpen = false;
    var pickBuf = [];

    function flushPicks() {
      if (!pickBuf.length) return;
      html.push('<div class="bt-picks">' + pickBuf.join('') + '</div>');
      pickBuf = [];
    }
    function closeGroup() {
      flushPicks();
      if (groupOpen) {
        html.push('</div>');
        groupOpen = false;
      }
    }

    trace.forEach(function (ev) {
      var op = ev.op || '';
      if (op === 'budget_start') {
        html.push('<div class="bt-start">session ' + esc(ev.remain_tss) + ' TSS · ' +
          esc(ev.remain_min) + ' min</div>');
        return;
      }
      if (op === 'group_open') {
        closeGroup();
        var inPool = poolInCount(idx, ev);
        var meta = esc(ev.group_tss) + ' TSS / ' + esc(ev.group_min) + ' min';
        if (inPool != null) meta += ' · ' + inPool + ' in pool';
        html.push('<div class="bt-group">' +
          '<div class="bt-group-h">' +
          '<span class="bt-group-label">' + esc(ev.label || 'Group') +
          ' · pick ' + esc(ev.n) + '</span>' +
          '<span class="bt-group-meta">' + meta + '</span>' +
          '</div>');
        groupOpen = true;
        return;
      }
      if (op === 'group_skip') {
        closeGroup();
        html.push('<div class="bt-group bt-group-skip">' +
          '<div class="bt-group-h"><span class="bt-group-label">skip ' +
          esc(ev.label || '') + '</span>' +
          (ev.reason ? '<span class="bt-group-meta">' + esc(ev.reason) + '</span>' : '') +
          '</div></div>');
        return;
      }
      if (op === 'budget_remain') {
        if (ev.note) {
          pickBuf.push('<div class="bt-inline">' + budgetRemainHtml(ev.remain_tss, ev.remain_min, ev.note) + '</div>');
        }
        return;
      }
      if (op === 'budget_pick') {
        var alts = '';
        if (ev.top && ev.top.length > 1) {
          alts = '<div class="bt-alts">runners-up: ' +
            ev.top.slice(1, 3).map(function (t) {
              return esc(t.name) + ' ' + esc(t.score);
            }).join(', ') + '</div>';
        }
        pickBuf.push(
          '<div class="bt-pick">' +
            '<span class="bt-name">' + esc(ev.name || '?') + '</span>' +
            '<span class="bt-rx">' + pickSpendLine(ev) + '</span>' +
            pickScoreLine(ev) +
            alts +
            budgetRemainHtml(ev.remain_tss_after, ev.remain_min_after, ev.note || null) +
          '</div>'
        );
        return;
      }
      if (op === 'budget_exhausted') {
        flushPicks();
        html.push('<div class="bt-exhausted">Budget exhausted · ' +
          esc(ev.remain_tss) + ' TSS, ' + esc(ev.remain_min) + ' min left</div>');
        return;
      }
      if (op === 'budget_end') {
        closeGroup();
        var nLabel = ev.kind === 'run' ? 'blocks' : 'exercises';
        html.push('<div class="bt-end">Done · ' + esc(ev.exercise_count) + ' ' + nLabel +
          ' · leftover ' + esc(ev.remain_tss) + ' TSS, ' + esc(ev.remain_min) + ' min</div>');
      }
    });
    closeGroup();
    return html.join('');
  }

  function fillLogHtml(log, poolCounts) {
    if (!log) return '';
    var budgetBody = budgetTraceHtml(log.budget_trace || [], poolCounts);
    if (!budgetBody) return '';
    return '<div class="budget-trace-block">' +
      '<div class="budget-trace-list">' + budgetBody + '</div></div>';
  }

  function muscleSummaryHtml(summary, footprint) {
    var rows = summary && summary.length
      ? summary
      : Object.keys(footprint || {}).map(function (p) {
          return { part: p, tss: footprint[p] };
        }).sort(function (a, b) { return b.tss - a.tss; });
    if (!rows.length) {
      return '<div class="muted">No muscle TSS yet — exercises need body_parts.</div>';
    }
    var max = rows.reduce(function (m, r) { return Math.max(m, Number(r.tss) || 0); }, 0);
    var total = rows.reduce(function (s, r) { return s + (Number(r.tss) || 0); }, 0);
    var PART_LABEL = {
      calf: 'calf / shin', quad: 'quad', hamstring: 'hamstring', glute: 'glute',
      hip: 'hip', core: 'core', back: 'back', shoulder: 'shoulder',
      chest: 'chest', arm: 'arm', other: 'other',
    };
    return '<table class="muscle-tss-table"><thead><tr>' +
      '<th>Muscle</th><th class="num">TSS</th><th class="num">%</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var tss = Number(r.tss) || 0;
        var pct = total > 0 ? Math.round(tss / total * 100) : 0;
        var w = max > 0 ? Math.round(tss / max * 100) : 0;
        var label = PART_LABEL[r.part] || r.part;
        return '<tr><td>' + esc(label) +
          '<span class="muscle-bar" style="width:' + w + '%"></span></td>' +
          '<td class="num">' + tss.toFixed(1) + '</td>' +
          '<td class="num">' + pct + '%</td></tr>';
      }).join('') +
      '</tbody><tfoot><tr><td>Total</td><td class="num">' + total.toFixed(1) +
      '</td><td class="num">100%</td></tr></tfoot></table>';
  }

  function exerciseTableHtml(exs) {
    var totalTss = 0;
    var totalMin = 0;
    var order = [];
    var byBlock = {};
    (exs || []).forEach(function (x) {
      var b = (x && x.block) ? String(x.block) : 'Exercises';
      if (!byBlock[b]) {
        byBlock[b] = [];
        order.push(b);
      }
      byBlock[b].push(x);
      var tss = x.spend_tss != null ? Number(x.spend_tss) : null;
      var mins = x.spend_min != null ? Number(x.spend_min) : null;
      if (tss != null) totalTss += tss;
      if (mins != null) totalMin += mins;
    });
    if (!order.length) {
      return '<div class="muted">No exercises.</div>';
    }
    var sections = order.map(function (b) {
      var rows = byBlock[b].map(function (x) {
        var tss = x.spend_tss != null ? Number(x.spend_tss) : null;
        var mins = x.spend_min != null ? Number(x.spend_min) : null;
        var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : '';
        return '<tr><td>' + esc(x.name || '') + '</td>' +
          '<td class="rx">' + esc(sr + (x.load ? ' · ' + x.load : '')) + '</td>' +
          '<td class="num">' + (mins != null ? mins.toFixed(1) : '—') + '</td>' +
          '<td class="num">' + (tss != null ? tss.toFixed(1) : '—') + '</td></tr>';
      }).join('');
      return '<div class="preview-block-sec">' +
        '<div class="preview-block-h">' + esc(b) + '</div>' +
        '<table class="preview-ex-table"><thead><tr>' +
        '<th>Exercise</th><th>Prescription</th>' +
        '<th class="num">Min</th><th class="num">TSS</th></tr></thead><tbody>' +
        rows + '</tbody></table></div>';
    }).join('');
    return sections +
      '<div class="preview-spend"><span>Session spend</span>' +
      '<span class="num">' + totalMin.toFixed(1) + ' min · ' + totalTss.toFixed(1) + ' TSS</span></div>';
  }

  function runBlockPrescription(b) {
    var bits = [];
    var rep = b.repeat != null ? Number(b.repeat) : 0;
    var per = b.duration_min != null ? Number(b.duration_min) : null;
    var rest = b.rest_min != null ? Number(b.rest_min) : null;
    var pace = b.pace_mult != null ? Number(b.pace_mult) : null;
    if (rep > 1 && per != null) bits.push(rep + ' × ' + per + ' min');
    else if (per != null) bits.push(per + ' min');
    if (b.target) bits.push(String(b.target));
    if (pace != null && isFinite(pace)) bits.push('@ ×' + pace.toFixed(2) + ' threshold');
    if (rep > 1 && rest != null) bits.push(rest + ' min rest');
    return bits.join(' · ');
  }

  function blocksTableHtml(blocks) {
    var totalTss = 0;
    var totalMin = 0;
    var rows = (blocks || []).map(function (b) {
      var tss = b.spend_tss != null ? Number(b.spend_tss) : null;
      var mins = b.block_min != null ? Number(b.block_min) : (
        b.duration_min != null ? Number(b.duration_min) : null
      );
      var rep = b.repeat != null ? Number(b.repeat) : 0;
      if (rep > 1 && b.duration_min != null) {
        var rest = b.rest_min != null ? Number(b.rest_min) : 0;
        mins = Number(b.duration_min) * rep + rest * Math.max(0, rep - 1);
      }
      if (tss != null) totalTss += tss;
      if (mins != null) totalMin += mins;
      return '<tr><td>' + esc(b.phase || '') + '</td>' +
        '<td class="rx">' + esc(runBlockPrescription(b)) + '</td>' +
        '<td class="num">' + (mins != null ? mins.toFixed(0) : '—') + '</td>' +
        '<td class="num">' + (tss != null ? tss.toFixed(1) : '—') + '</td></tr>';
    }).join('');
    return '<table class="preview-ex-table"><thead><tr>' +
      '<th>Phase</th><th>Prescription</th>' +
      '<th class="num">Min</th><th class="num">TSS</th></tr></thead><tbody>' + rows +
      '</tbody><tfoot><tr><td colspan="2">Session spend</td>' +
      '<td class="num">' + totalMin.toFixed(0) + '</td>' +
      '<td class="num">' + totalTss.toFixed(1) + '</td></tr></tfoot></table>';
  }

  /**
   * Full shared pane: exercises|muscle grid + budget trace.
   * session: { exercises, blocks, workout_type, muscle_footprint|_muscle_footprint,
   *            muscle_summary?, fill_log?, pool_counts? }
   * opts.showBudget — include pick-by-pick budget (default true)
   * opts.showMuscle — force muscle column on/off; default: on when data exists
   *                   (admin preview always shows the column)
   */
  function sessionPaneHtml(session, opts) {
    opts = opts || {};
    ensureStyles();
    session = session || {};
    var exs = session.exercises || [];
    var blocks = session.blocks || [];
    var wt = String(session.workout_type || '').toLowerCase();
    var isRun = wt === 'run' || (!exs.length && blocks.length);
    var main;
    if (isRun && blocks.length) {
      main = blocksTableHtml(blocks);
    } else if (exs.length) {
      main = exerciseTableHtml(exs);
    } else {
      main = '<div class="muted">No content returned — check patterns / pool.</div>';
    }
    var footprint = session.muscle_footprint || session._muscle_footprint || null;
    var summary = session.muscle_summary || null;
    var hasMuscleData = !!(summary && summary.length) ||
      !!(footprint && Object.keys(footprint).some(function (k) { return Number(footprint[k]) > 0; }));
    var showMuscle = opts.showMuscle === true || (opts.showMuscle !== false && hasMuscleData);
    // Admin live preview always keeps the muscle column (even empty).
    if (opts.alwaysMuscle) showMuscle = true;
    var poolCounts = session.pool_counts || opts.pool_counts || null;
    var log = session.fill_log || null;
    if (!log && session.budget_trace) {
      log = { budget_trace: session.budget_trace };
    }
    var showBudget = opts.showBudget !== false;

    var layout;
    if (showMuscle) {
      layout = '<div class="preview-layout">' +
        '<div class="preview-pane preview-pane-ex">' +
          '<div class="preview-pane-h">' + (isRun ? 'Session blocks' : 'Exercises') + '</div>' +
          main +
        '</div>' +
        '<aside class="preview-pane preview-side">' +
          '<div class="preview-pane-h">Muscle TSS</div>' +
          muscleSummaryHtml(summary, footprint) +
        '</aside></div>';
    } else {
      layout = '<div class="preview-pane preview-pane-ex">' +
        '<div class="preview-pane-h">' + (isRun ? 'Session blocks' : 'Exercises') + '</div>' +
        main +
      '</div>';
    }
    return layout + (showBudget ? fillLogHtml(log, poolCounts) : '');
  }

  global.PlanFillPreview = {
    ensureStyles: ensureStyles,
    sessionPaneHtml: sessionPaneHtml,
    budgetTraceHtml: budgetTraceHtml,
    fillLogHtml: fillLogHtml,
    muscleSummaryHtml: muscleSummaryHtml,
    exerciseTableHtml: exerciseTableHtml,
    blocksTableHtml: blocksTableHtml,
    poolCountIndex: poolCountIndex,
    STYLE_VER: STYLE_VER,
  };
})(typeof window !== 'undefined' ? window : globalThis);
