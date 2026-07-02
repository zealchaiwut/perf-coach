/* ============================================================================
   WeightCurrentCard — SHARED renderer for the "current weight" block used on
   both the weight tab (weight.html) and the home page (home.html).

   Single source of truth: previously the weight tab had renderHeroCardA /
   renderCoachStrip and home had its own separate widget. Both now call
   WeightCurrentCard.render() so the markup, copy, and logic never drift.

   Markup contract — the host page must provide these element ids inside one
   container (see WeightCurrentCard.MARKUP for the canonical block):
     #hca-date-sub  #hca-avg  #hca-weight
     #hca-pill-week #hca-pill-month
     #coach-strip   #coach-text

   Data contract:
     render(chartData, activeTarget)
       chartData.stats.{current_weight_kg, current_avg_kg, delta_7d_kg, delta_30d_kg}
       chartData.actuals[]           — for the relative "logged …" date
       chartData.logged_today        — coach strip state
       chartData.today_delta_kg      — coach strip direction
       activeTarget.{start_weight_kg, target_weight_kg}  — pill/coach direction
   ========================================================================== */
(function (global) {
  'use strict';

  // Canonical block markup — host pages can inject this instead of hand-copying.
  var MARKUP =
    '<div class="hca-top">' +
      '<span class="hca-label">CURRENT WEIGHT</span>' +
      '<span class="hca-date-sub" id="hca-date-sub"></span>' +
    '</div>' +
    '<div class="hca-middle">' +
      '<div class="hca-col">' +
        '<div class="hca-col-label">7-day avg</div>' +
        '<div class="hca-avg" id="hca-avg">--</div>' +
      '</div>' +
      '<div class="hca-weight" id="hca-weight">--</div>' +
      '<div class="hca-col hca-col-right">' +
        '<div class="hca-col-label">Change</div>' +
        '<div class="hca-pills">' +
          '<span class="delta-pill neutral" id="hca-pill-week">This wk: --</span>' +
          '<span class="delta-pill neutral" id="hca-pill-month">This mo: --</span>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="coach-strip coach-grey" id="coach-strip">' +
      '<span id="coach-text">😴 No entry yet today — log your weight to wake me up</span>' +
    '</div>';

  function _relativeLoggedDate(actuals) {
    if (!actuals || !actuals.length) return '';
    var lastDate = actuals[actuals.length - 1].date;
    if (!lastDate) return '';
    var today = new Date().toISOString().slice(0, 10);
    if (lastDate === today) return 'Today';
    var d = new Date(lastDate + 'T00:00:00');
    var mo = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    var diffDays = Math.round(
      (new Date(today + 'T00:00:00') - new Date(lastDate + 'T00:00:00')) / 86400000
    );
    if (diffDays === 1) return 'Logged yesterday · ' + mo;
    return 'Logged ' + diffDays + ' days ago · ' + mo;
  }

  function _pillClass(delta, activeTarget) {
    if (delta == null || Math.abs(delta) < 0.05) return 'neutral';
    if (!activeTarget) return delta < 0 ? 'toward' : 'away';
    var isLossGoal = activeTarget.target_weight_kg < activeTarget.start_weight_kg;
    var towardTarget = isLossGoal ? delta < 0 : delta > 0;
    return towardTarget ? 'toward' : 'away';
  }

  function _renderPill(id, delta, label, activeTarget) {
    var el = document.getElementById(id);
    if (!el) return;
    if (delta == null) {
      el.textContent = label + ': --';
      el.className = 'delta-pill neutral';
      return;
    }
    var isFlat = Math.abs(delta) < 0.05;
    var arrow = isFlat ? '→' : (delta < 0 ? '↓' : '↑');
    el.textContent = label + ': ' + arrow + ' ' + Math.abs(delta).toFixed(1) + ' kg';
    el.className = 'delta-pill ' + _pillClass(delta, activeTarget);
  }

  function renderStats(chartData, activeTarget) {
    var stats = chartData ? chartData.stats : null;
    var actuals = chartData ? (chartData.actuals || []) : [];

    var dateSubEl = document.getElementById('hca-date-sub');
    if (dateSubEl) dateSubEl.textContent = _relativeLoggedDate(actuals);

    var avgEl = document.getElementById('hca-avg');
    if (avgEl) {
      avgEl.textContent = stats && stats.current_avg_kg != null
        ? stats.current_avg_kg.toFixed(1) + ' kg'
        : '--';
    }

    var weightEl = document.getElementById('hca-weight');
    if (weightEl) {
      weightEl.textContent = stats && stats.current_weight_kg != null
        ? stats.current_weight_kg.toFixed(1) + ' kg'
        : '--';
    }

    _renderPill('hca-pill-week', stats ? stats.delta_7d_kg : null, 'This wk', activeTarget);
    _renderPill('hca-pill-month', stats ? stats.delta_30d_kg : null, 'This mo', activeTarget);

    // EWMA weekly rate indicator — show/hide based on data availability
    var rateRow = document.getElementById('ewma-rate-row');
    var ratePill = document.getElementById('ewma-rate-pill');
    var rate = stats ? stats.weekly_rate_ewma_kg : null;
    if (rateRow && ratePill) {
      if (rate == null) {
        rateRow.hidden = true;
      } else {
        rateRow.hidden = false;
        var isFlat = Math.abs(rate) < 0.01;
        var arrow = isFlat ? '→' : (rate < 0 ? '↓' : '↑');
        var sign = rate > 0 ? '+' : '';
        ratePill.textContent = arrow + ' ' + sign + rate.toFixed(2) + ' kg/wk';
        var isLossGoal = !activeTarget || activeTarget.target_weight_kg < activeTarget.start_weight_kg;
        var cls = isFlat ? 'neutral' : (rate < 0 ? (isLossGoal ? 'toward' : 'away') : (isLossGoal ? 'away' : 'toward'));
        ratePill.className = 'delta-pill ' + cls;
      }
    }
  }

  function renderCoachStrip(chartData, activeTarget) {
    var strip = document.getElementById('coach-strip');
    var textEl = document.getElementById('coach-text');
    if (!strip || !textEl) return;

    var loggedToday = chartData && chartData.logged_today;
    var todayDeltaKg = chartData ? chartData.today_delta_kg : null;

    if (!loggedToday) {
      strip.className = 'coach-strip coach-grey';
      textEl.textContent = '😴 No entry yet today — log your weight to wake me up';
      return;
    }

    var isLossGoal = activeTarget
      ? activeTarget.target_weight_kg < activeTarget.start_weight_kg
      : true;
    var isFlat = todayDeltaKg == null || Math.abs(todayDeltaKg) < 0.05;
    var movedToward = isFlat || (isLossGoal ? todayDeltaKg < 0 : todayDeltaKg > 0);

    if (movedToward) {
      strip.className = 'coach-strip coach-green';
      textEl.textContent = '🎉 You did well — on pace this week';
    } else {
      strip.className = 'coach-strip coach-amber';
      textEl.textContent = isLossGoal
        ? '💪 Up a little — new day, keep going'
        : '💪 Down a little — new day, keep going';
    }
  }

  function render(chartData, activeTarget) {
    renderStats(chartData, activeTarget);
    renderCoachStrip(chartData, activeTarget);
  }

  global.WeightCurrentCard = {
    MARKUP: MARKUP,
    render: render,
    renderStats: renderStats,
    renderCoachStrip: renderCoachStrip
  };
}(window));
