/*
 * home-grid.js — Home dashboard layout engine (gridstack.js).
 *
 * Replaces the previous hand-placed CSS grid (four per-breakpoint sets of
 * grid-column/grid-row rules) with a gridstack instance driven by a declarative
 * registry: one fixed widget ORDER, plus a column-span per breakpoint. gridstack
 * does the packing (float:false → auto-compaction), and `sizeToContent` sizes
 * each item's HEIGHT to its widget's real content — so a tall widget (Readiness
 * with the CTL/ATL/TSB trio) and a short one (Sleep) each get exactly the height
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
    { id: 'home-top-row-right',     w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Readiness
    { id: 'home-today-rec-card',    w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Today's recommendation
    { id: 'home-next-workout-card', w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Next + Recent
    { id: 'home-performance-card',  w: { 8: 2, 6: 2, 4: 2, 1: 1 } }, // Performance
    { id: 'home-training-card',     w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Training
    { id: 'home-perf-container',    w: { 8: 4, 6: 3, 4: 4, 1: 1 } }, // Personal records
    { id: 'home-habits-widget',     w: { 8: 4, 6: 4, 4: 4, 1: 1 } }, // Habits
    { id: 'home-weight-widget',     w: { 8: 4, 6: 3, 4: 4, 1: 1 } }, // Weight
    { id: 'home-sleep-card',        w: { 8: 4, 6: 2, 4: 2, 1: 1 } }, // Sleep
    { id: 'home-goal-card',         w: { 8: 4, 6: 3, 4: 4, 1: 1 } }  // Race goal
  ];

  function colFor(width) {
    if (width >= 1000) return 8;
    if (width >= 760) return 6;
    if (width >= 480) return 4;
    return 1;
  }

  var container = null;
  var grid = null;
  var curCol = null;
  var mo = null;
  var relayoutTimer = null;

  function itemEl(id) {
    var c = document.getElementById(id);
    return c ? c.closest('.grid-stack-item') : null;
  }

  // Re-measure every item's content height and re-pack. Runs on init, on
  // breakpoint change (content can change too — e.g. Readiness drops the
  // CTL trio below 480px via CSS), and whenever widget content mutates.
  // The observer is detached during the pass so gridstack's own DOM writes
  // can't retrigger it.
  function relayout() {
    if (!grid) return;
    if (mo) mo.disconnect();
    grid.batchUpdate();
    REGISTRY.forEach(function (r) {
      var el = itemEl(r.id);
      if (el) grid.resizeToContent(el);
    });
    grid.commit();
    grid.compact('list');
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

    mo = new MutationObserver(scheduleRelayout);
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
