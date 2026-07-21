/*
 * home-grid.js — Home dashboard layout engine (gridstack.js).
 *
 * Replaces the previous hand-placed CSS grid (four per-breakpoint sets of
 * grid-column/grid-row rules) with a gridstack instance driven by a declarative
 * registry: one fixed widget ORDER, plus a column-span per breakpoint. gridstack
 * does the packing (float:false → auto-compaction), and `sizeToContent` sizes
 * each item's HEIGHT to its widget's real content — so a tall widget (Readiness
 * with the CTL/ATL/TSB/ACWR tiles) and a short one (Sleep) each get exactly the height
 * they need, with no hand-tuned row spans and no clipping.
 *
 * The widget CONTENT is still rendered by the existing modules (home.js,
 * home-readiness-training-sleep.js, home-strip-habits.js) into the same
 * container ids — this file only wraps those containers in gridstack items and
 * manages their width/position. A MutationObserver re-fits heights whenever a
 * widget's content changes (async data fills, habit toggles, etc.).
 *
 * staticGrid:true → no drag/resize this pass (the registry is the only source of
 * layout). Flipping it to false is the whole migration path to hand-rearrange.
 */
(function () {
  'use strict';

  var GRID_ID = 'home-dashboard-grid';

  // Fixed order (top → bottom / left → right at each breakpoint) with the
  // column span per column-count. Keys are the live widget container ids.
  var REGISTRY = [
    { id: 'home-top-row-right',          w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Readiness
    { id: 'home-next-workout-card',      w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Recent workouts
    { id: 'home-performance-card',       w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Performance
    { id: 'home-today-rec-card',         w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Coach digest
    { id: 'home-brief-week-plan-card',   w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Week plan
    { id: 'home-training-card',          w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Training
    { id: 'home-perf-container',         w: { 8: 4, 6: 3, 4: 4, 1: 1 } }, // Personal records
    { id: 'home-habits-widget',          w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Habits
    { id: 'home-weight-widget',          w: { 8: 4, 6: 3, 4: 4, 1: 1 } }, // Weight
    { id: 'home-sleep-card',             w: { 8: 4, 6: 2, 4: 2, 1: 1 } }, // Sleep
    { id: 'home-goal-card',              w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Race goal
  ];

  function colFor(width) {
    if (width >= 1000) return 8;
    if (width >= 760) return 6;
    if (width >= 480) return 4;
    return 1;
  }

  var REGISTRY_IDS = {};
  REGISTRY.forEach(function (r) { REGISTRY_IDS[r.id] = true; });

  var container = null;
  var grid = null;
  var curCol = null;
  var mo = null;
  var relayoutTimer = null;

  // Widget ids whose content has mutated since the last relayout() pass —
  // populated by the MutationObserver callback, consumed (and cleared) by
  // relayout() so it can resizeToContent only those widgets instead of all
  // 11. dirtyAll forces a full pass (init, breakpoint change, or a mutation
  // we couldn't trace back to a known widget container).
  var dirtyIds = {};
  var dirtyAll = false;

  function itemEl(id) {
    var c = document.getElementById(id);
    return c ? c.closest('.grid-stack-item') : null;
  }

  // Walk a mutation's target up to the nearest ancestor that is one of the
  // REGISTRY widget containers (or the container itself, if untraceable).
  function widgetIdFor(node) {
    var el = node && node.nodeType === 1 ? node : (node && node.parentNode);
    while (el && el !== container) {
      if (el.id && REGISTRY_IDS[el.id]) return el.id;
      el = el.parentNode;
    }
    return null;
  }

  // Side-by-side pairs that should share a row height.
  var HEIGHT_PAIRS = [
    ['home-next-workout-card', 'home-performance-card'],
    ['home-today-rec-card', 'home-brief-week-plan-card'],
  ];

  function clearPairStretch() {
    HEIGHT_PAIRS.forEach(function (pair) {
      pair.forEach(function (id) {
        var c = document.getElementById(id);
        if (c) {
          c.style.minHeight = '';
          c.style.height = '';
        }
      });
    });
  }

  function applyPairStretch() {
    HEIGHT_PAIRS.forEach(function (pair) {
      pair.forEach(function (id) {
        var item = itemEl(id);
        var card = document.getElementById(id);
        if (!item || !card) return;
        var box = item.querySelector('.grid-stack-item-content');
        if (!box) return;
        var h = Math.ceil(box.clientHeight);
        if (h > 0) card.style.minHeight = h + 'px';
      });
    });
  }

  // After sizeToContent, raise the shorter of a same-row pair to the taller.
  function equalizePair(idA, idB) {
    var a = itemEl(idA);
    var b = itemEl(idB);
    if (!a || !b || !grid) return;
    var na = a.gridstackNode;
    var nb = b.gridstackNode;
    if (!na || !nb) return;
    // Stacked (different rows) — leave natural heights alone.
    if (na.y !== nb.y) return;
    var maxH = Math.max(na.h || 0, nb.h || 0);
    if (!maxH) return;
    if ((na.h || 0) < maxH) grid.update(a, { h: maxH });
    if ((nb.h || 0) < maxH) grid.update(b, { h: maxH });
  }

  function equalizeAllPairs() {
    HEIGHT_PAIRS.forEach(function (pair) {
      equalizePair(pair[0], pair[1]);
    });
  }

  // Re-measure item content height(s) and re-pack. Runs on init, on
  // breakpoint change (content can change too — e.g. Readiness drops the
  // load tiles below 480px via CSS), and whenever widget content mutates.
  // The observer is detached during the pass so gridstack's own DOM writes
  // can't retrigger it.
  //
  // resizeToContent is the expensive part (forces a layout read per widget),
  // so it's scoped to only the widget(s) that actually mutated + their
  // equalizePair partner (equalizePair compares both sides' heights, so the
  // partner needs an up-to-date read too) — everything else keeps its
  // last-known-correct height. compact('list')/equalizeAllPairs()/
  // applyPairStretch() still run over the full registry every time: they're
  // cheap (a handful of items, no forced reflow beyond what applyPairStretch
  // already did) and re-packing/re-stretching is a whole-grid concern, not a
  // per-widget one. dirtyAll (or an empty dirty set, e.g. init/breakpoint
  // change) falls back to resizing everything, same as before.
  function relayout() {
    if (!grid) return;
    if (mo) mo.disconnect();

    var idsToResize;
    if (dirtyAll || Object.keys(dirtyIds).length === 0) {
      idsToResize = REGISTRY.map(function (r) { return r.id; });
    } else {
      var scoped = {};
      Object.keys(dirtyIds).forEach(function (id) { scoped[id] = true; });
      HEIGHT_PAIRS.forEach(function (pair) {
        if (scoped[pair[0]] || scoped[pair[1]]) {
          scoped[pair[0]] = true;
          scoped[pair[1]] = true;
        }
      });
      idsToResize = Object.keys(scoped);
    }
    dirtyIds = {};
    dirtyAll = false;

    clearPairStretch();
    grid.batchUpdate();
    idsToResize.forEach(function (id) {
      var el = itemEl(id);
      if (el) grid.resizeToContent(el);
    });
    grid.commit();
    grid.compact('list');
    equalizeAllPairs();
    applyPairStretch();
    if (mo && container) {
      mo.observe(container, { childList: true, subtree: true, characterData: true });
    }
  }

  function applyColumns(col) {
    grid.batchUpdate();
    grid.column(col, 'list');
    REGISTRY.forEach(function (r) {
      var el = itemEl(r.id);
      if (el) grid.update(el, { w: r.w[col] });
    });
    grid.commit();
    curCol = col;
    // Column width changed for every widget — all of them may need a fresh
    // content measurement (wrapping/line-count can change), not just
    // whichever happened to be flagged dirty by a stray mutation.
    dirtyAll = true;
    relayout();
  }

  function onResize() {
    if (!container || !grid) return;
    var col = colFor(container.clientWidth);
    if (col !== curCol) applyColumns(col);
  }

  function scheduleRelayout() {
    clearTimeout(relayoutTimer);
    relayoutTimer = setTimeout(relayout, 120);
  }

  // MutationObserver callback: record which widget(s) the mutations belong
  // to (falling back to dirtyAll if a mutation can't be traced to a known
  // widget container), then debounce as before.
  function onMutate(records) {
    for (var i = 0; i < records.length; i++) {
      var id = widgetIdFor(records[i].target);
      if (id) {
        dirtyIds[id] = true;
      } else {
        dirtyAll = true;
      }
    }
    scheduleRelayout();
  }

  function init() {
    container = document.getElementById(GRID_ID);
    if (!container || typeof GridStack === 'undefined') return;
    if (grid) return; // idempotent

    curCol = colFor(container.clientWidth);
    // Seed each item's width for the current breakpoint before init so
    // gridstack reads them from the markup.
    REGISTRY.forEach(function (r) {
      var el = itemEl(r.id);
      if (el) el.setAttribute('gs-w', String(r.w[curCol]));
    });

    grid = GridStack.init({
      column: curCol,
      // Small cell unit: sizeToContent rounds each item's height up to the
      // nearest cell, so a small unit keeps the fit tight (no big dead gap).
      cellHeight: 10,
      // gridstack insets each item's content by this margin on all sides, so the
      // visible gap between two adjacent widgets is ~2×margin ≈ 16px — matching
      // the 16px spacing around the "Log today's metrics" banner above the grid.
      margin: 8,
      float: false,
      animate: false,
      staticGrid: true,
      sizeToContent: true
    }, container);

    mo = new MutationObserver(onMutate);
    mo.observe(container, { childList: true, subtree: true, characterData: true });

    if (window.ResizeObserver) {
      new ResizeObserver(onResize).observe(container);
    } else {
      window.addEventListener('resize', onResize);
    }

    relayout();
  }

  window.HomeGrid = { init: init, relayout: relayout };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
