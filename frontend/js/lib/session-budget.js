/* Shared Session budget block (pins + spend bar + refill note).
 * Used by the session modal and (later) the plan slot editor.
 * window.SessionBudget — load before training-plan.js.
 */
(function (global) {
  'use strict';

  var STYLE_ID = 'session-budget-css';
  var STYLE_VER = '20260805sb1';

  function esc(s) {
    if (global.AppCommon && typeof global.AppCommon.escapeHtml === 'function') {
      return global.AppCommon.escapeHtml(s);
    }
    // AppCommon is required — never re-implement entity substitution here
    // (see tests/test_frontend_shared_lib__1603.py).
    return String(s == null ? '' : s);
  }

  var CSS = [
    '.sb-pins{margin-top:14px;border:1px solid #dfe3fb;background:#f7f8fe;border-radius:12px;padding:12px 14px;}',
    '.sb-pinhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;flex-wrap:wrap;}',
    '.sb-pinhead .sb-t{font-size:12.5px;font-weight:700;color:#3b4bb8;}',
    '.sb-pinhead .sb-s{font-family:var(--mono,ui-monospace,monospace);font-size:10px;color:#7b87c9;}',
    '.sb-pinrow{display:flex;gap:9px;align-items:center;flex-wrap:wrap;}',
    '.sb-pin{background:#fff;border:1px solid var(--border,#e8eaf0);border-radius:9px;padding:7px 10px;min-width:138px;}',
    '.sb-pin.is-disabled{opacity:.5;}',
    '.sb-pin .sb-k{font-family:var(--mono,ui-monospace,monospace);font-size:8px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#9ca3af;margin-bottom:3px;}',
    '.sb-pinctl{display:flex;align-items:center;gap:2px;}',
    '.sb-pinctl button{width:22px;height:25px;border:none;background:#f7f9fd;border-radius:5px;color:#6b7280;font-size:13px;cursor:pointer;}',
    '.sb-pinctl button:hover{background:#f1f4fa;color:var(--ink,#1b2340);}',
    '.sb-pinctl input{flex:1;min-width:0;border:none;background:none;font-family:var(--mono,ui-monospace,monospace);font-size:17px;font-weight:700;text-align:center;color:var(--ink,#1b2340);}',
    '.sb-pinctl input:focus{outline:none;}',
    '.sb-pinctl input.unset{color:#9ca3af;}',
    '.sb-btrack{height:9px;border-radius:99px;background:#e4e8f7;overflow:hidden;position:relative;margin-top:11px;}',
    '.sb-btrack i{display:block;height:100%;float:left;}',
    '.sb-btrack i.pinned{background:#8b5cf6;}',
    '.sb-btrack i.filled{background:#4f6ef7;}',
    '.sb-btrack i.over{background:#d97706;}',
    '.sb-btrack b{position:absolute;top:-3px;bottom:-3px;width:2px;background:#3b4bb8;}',
    '.sb-bfoot{display:flex;justify-content:space-between;font-family:var(--mono,ui-monospace,monospace);font-size:10px;color:#5b67a8;margin-top:6px;gap:8px;flex-wrap:wrap;}',
    '.sb-bfoot .warn{color:#d97706;font-weight:700;}',
    '.sb-bfoot .vio{color:#8b5cf6;font-weight:700;}',
    '.sb-refillrow{display:flex;align-items:center;gap:9px;margin-top:10px;flex-wrap:wrap;}',
    '.sb-refnote{font-family:var(--mono,ui-monospace,monospace);font-size:10px;color:#7b87c9;}',
    '.sb-refnote.block{color:#d97706;font-weight:700;}',
    '.sb-go{padding:9px 16px;border-radius:9px;border:none;background:var(--accent,#cff245);color:var(--ink,#1b2340);font-size:12.5px;font-weight:700;cursor:pointer;white-space:nowrap;font-family:inherit;}',
    '.sb-go:disabled{opacity:.5;cursor:default;background:#eef0e4;color:#b6bba8;}',
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

  function num(v, fallback) {
    var n = Number(v);
    return isFinite(n) ? n : (fallback != null ? fallback : 0);
  }

  function isPinned(ex) {
    if (!ex) return false;
    if (ex.pinned === true) return true;
    if (ex.pinned === false) return false;
    var src = String(ex.source || 'generated').toLowerCase();
    return src && src !== 'generated' && src !== 'pattern';
  }

  function spendOf(ex) {
    var tss = ex && ex.spend_tss != null ? Number(ex.spend_tss) : NaN;
    var mins = ex && ex.spend_min != null ? Number(ex.spend_min) : NaN;
    if (!isFinite(tss)) tss = 1;
    if (!isFinite(mins)) {
      var sets = Number(ex && ex.sets) || 3;
      mins = Math.max(2, sets * 2.5);
    }
    return { tss: tss, min: mins };
  }

  /** Compute bar + refill contract from budget pins and exercise rows. */
  function analyze(opts) {
    opts = opts || {};
    var budgetTss = opts.budgetTss != null && opts.budgetTss !== '' ? num(opts.budgetTss) : null;
    var budgetMin = opts.budgetMin != null && opts.budgetMin !== '' ? num(opts.budgetMin) : null;
    var exercises = opts.exercises || [];
    var pinnedTss = 0;
    var filledTss = 0;
    var pinnedCount = 0;
    exercises.forEach(function (ex) {
      var skipped = String(ex.state || 'done') === 'skipped';
      var s = spendOf(ex);
      if (isPinned(ex)) {
        pinnedTss += s.tss;
        pinnedCount += 1;
      } else if (!skipped) {
        filledTss += s.tss;
      }
    });
    pinnedTss = Math.round(pinnedTss * 10) / 10;
    filledTss = Math.round(filledTss * 10) / 10;
    var total = Math.round((pinnedTss + filledTss) * 10) / 10;
    var hasBudget = budgetTss != null && budgetTss > 0;
    var overBudget = hasBudget && total > budgetTss;
    var pinnedExceeds = hasBudget && pinnedTss > budgetTss;
    var noBudget = (budgetTss == null || budgetTss <= 0) && (budgetMin == null || budgetMin <= 0);
    var remainTss = hasBudget ? Math.max(0, Math.round((budgetTss - pinnedTss) * 10) / 10) : 0;
    var note;
    var blocked = false;
    if (noBudget) {
      blocked = true;
      note = 'needs TSS or duration pinned to fill from patterns';
    } else if (pinnedExceeds) {
      blocked = true;
      note = 'pinned rows already exceed the budget — unpin one or raise the pin';
    } else {
      note = 'keeps ' + pinnedCount + ' pinned row' + (pinnedCount === 1 ? '' : 's') +
        ' · refills the rest' + (hasBudget ? (' to ' + Math.round(remainTss) + ' TSS') : '');
    }
    return {
      budgetTss: budgetTss,
      budgetMin: budgetMin,
      pinnedTss: pinnedTss,
      filledTss: filledTss,
      total: total,
      pinnedCount: pinnedCount,
      overBudget: overBudget,
      pinnedExceeds: pinnedExceeds,
      noBudget: noBudget,
      remainTss: remainTss,
      blocked: blocked,
      note: note,
    };
  }

  function barHtml(a) {
    if (!a.budgetTss || a.budgetTss <= 0) {
      return '<div class="sb-btrack"></div>' +
        '<div class="sb-bfoot"><span>set a TSS pin to see spend vs budget</span><span></span></div>';
    }
    var budget = a.budgetTss;
    var total = a.total;
    var over = total > budget;
    var track;
    var left;
    var right;
    if (over) {
      track = '<div class="sb-btrack"><i class="over" style="width:100%"></i>' +
        '<b style="left:' + Math.min(96, (budget / Math.max(total, 1)) * 100) + '%"></b></div>';
      left = '<span class="warn">' + total + ' pinned+filled</span> of ' + budget + ' TSS';
      right = '<span class="warn">' + Math.round((total - budget) * 10) / 10 + ' over</span>';
    } else {
      var pw = (a.pinnedTss / budget) * 100;
      var fw = (a.filledTss / budget) * 100;
      track = '<div class="sb-btrack">' +
        '<i class="pinned" style="width:' + pw + '%"></i>' +
        '<i class="filled" style="width:' + fw + '%"></i>' +
        '<b style="left:100%"></b></div>';
      left = '<span class="vio">' + a.pinnedTss + ' pinned</span> + ' + a.filledTss +
        ' filled = ' + total + ' of ' + budget + ' TSS';
      right = Math.round((budget - total) * 10) / 10 + ' under';
    }
    return track + '<div class="sb-bfoot"><span>' + left + '</span><span>' + right + '</span></div>';
  }

  /**
   * Render the Session budget block.
   * opts: { duration, tss, distance, distanceDisabled, exercises, refillBusy,
   *         showRefill, refillLabel, ids }
   */
  function html(opts) {
    ensureStyles();
    opts = opts || {};
    var dur = opts.duration;
    var tss = opts.tss;
    var dist = opts.distance;
    var distDisabled = opts.distanceDisabled !== false; // default disabled unless run
    var a = analyze({
      budgetTss: tss,
      budgetMin: dur,
      exercises: opts.exercises || [],
    });
    var durUnset = dur == null || dur === '' || !(Number(dur) > 0);
    var tssUnset = tss == null || tss === '' || !(Number(tss) > 0);
    var refillLab = opts.refillLabel || (opts.hasStructure ? 'Refill unpinned' : 'Fill from patterns');
    var refillDisabled = a.blocked || !!opts.refillBusy;
    var refillHtml = opts.showRefill === false ? '' :
      '<div class="sb-refillrow">' +
        '<button type="button" class="sb-go" id="' + esc(opts.refillId || 'pl-sm-ai-go') + '"' +
          (refillDisabled ? ' disabled' : '') + '>' +
          (opts.refillBusy ? '…' : esc(refillLab)) + '</button>' +
        '<span class="sb-refnote' + (a.blocked ? ' block' : '') + '" id="' +
          esc(opts.noteId || 'pl-sm-ref-note') + '">' + esc(a.note) + '</span>' +
      '</div>';

    return '<div class="sb-pins" id="' + esc(opts.rootId || 'pl-sm-budget') + '">' +
      '<div class="sb-pinhead"><span class="sb-t">Session budget</span>' +
        '<span class="sb-s">what this session is meant to cost · drives Refill</span></div>' +
      '<div class="sb-pinrow">' +
        '<span class="sb-pin"><span class="sb-k">Duration · min</span>' +
          '<span class="sb-pinctl">' +
            '<button type="button" data-sb-bump="dur" data-d="-5" aria-label="Decrease duration">−</button>' +
            '<input id="' + esc(opts.durId || 'pl-sm-pin-dur') + '" inputmode="numeric" ' +
              'aria-label="Duration minutes" class="' + (durUnset ? 'unset' : '') + '" value="' +
              esc(durUnset ? '' : String(Math.round(Number(dur)))) + '" placeholder="—"/>' +
            '<button type="button" data-sb-bump="dur" data-d="5" aria-label="Increase duration">+</button>' +
          '</span></span>' +
        '<span class="sb-pin"><span class="sb-k">TSS</span>' +
          '<span class="sb-pinctl">' +
            '<button type="button" data-sb-bump="tss" data-d="-5" aria-label="Decrease TSS">−</button>' +
            '<input id="' + esc(opts.tssId || 'pl-sm-pin-tss') + '" inputmode="numeric" ' +
              'aria-label="Target TSS" class="' + (tssUnset ? 'unset' : '') + '" value="' +
              esc(tssUnset ? '' : String(Math.round(Number(tss)))) + '" placeholder="—"/>' +
            '<button type="button" data-sb-bump="tss" data-d="5" aria-label="Increase TSS">+</button>' +
          '</span></span>' +
        '<span class="sb-pin' + (distDisabled ? ' is-disabled' : '') + '"><span class="sb-k">Distance · km</span>' +
          '<span class="sb-pinctl">' +
            '<input id="' + esc(opts.distId || 'pl-sm-pin-dist') + '" ' +
              (distDisabled ? 'disabled ' : '') +
              'aria-label="Distance km" value="' +
              esc(dist != null && Number(dist) > 0 ? String(dist) : '—') + '"/>' +
          '</span></span>' +
      '</div>' +
      '<div id="' + esc(opts.barId || 'pl-sm-budget-bar') + '">' + barHtml(a) + '</div>' +
      refillHtml +
      (opts.error
        ? '<div class="pl-sm-ai-err" style="margin-top:8px;" role="alert">' + esc(opts.error) + '</div>'
        : '') +
    '</div>';
  }

  function wire(root, handlers) {
    handlers = handlers || {};
    if (!root) return;
    root.querySelectorAll('[data-sb-bump]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var kind = btn.getAttribute('data-sb-bump');
        var d = Number(btn.getAttribute('data-d')) || 0;
        if (handlers.onBump) handlers.onBump(kind, d);
      });
    });
    ['pl-sm-pin-dur', 'pl-sm-pin-tss', 'pl-sm-pin-dist'].forEach(function (id) {
      var el = root.querySelector('#' + id) || document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', function () {
        if (handlers.onChange) handlers.onChange(id, el.value);
      });
      el.addEventListener('input', function () {
        if (handlers.onInput) handlers.onInput(id, el.value);
      });
    });
  }

  global.SessionBudget = {
    analyze: analyze,
    barHtml: barHtml,
    html: html,
    wire: wire,
    ensureStyles: ensureStyles,
    isPinned: isPinned,
    spendOf: spendOf,
  };
})(typeof window !== 'undefined' ? window : globalThis);
