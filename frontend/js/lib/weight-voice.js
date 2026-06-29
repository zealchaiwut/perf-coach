/**
 * weight-voice.js — Coaching copy for weight chart surfaces (issue #923).
 *
 * All user-facing strings for the verdict banner, projection line, and
 * what-if panel are produced here. No surface hard-codes its own copy.
 *
 * Public API
 * ----------
 * WeightVoice.verdictCopy(todayMarker, actuals, stats)
 *   → { pillText, message, state }
 *
 * WeightVoice.projectionLabel(goalKg, dateStr)
 *   → string  forward-looking label for the projected path line
 *
 * WeightVoice.whatIfHeadline(targetDate)
 *   → string  "still-winnable" headline for the what-if panel
 *
 * WeightVoice.nearMilestoneCopy(weeksAway)
 *   → string|null  short-horizon copy when ≤4 weeks from next milestone
 *
 * WeightVoice.dashIfNull(val, fmt)
 *   → string  '—' when val is null/undefined, otherwise fmt(val) or String(val)
 */
(function (root) {
  'use strict';

  /**
   * verdictCopy — coaching copy for the chart verdict banner.
   *
   * Reads only fields already present in the W1 (/api/weight-chart) response:
   *   todayMarker.{trend_kg, plan_kg, gap_kg, gap_direction}
   *   actuals  — array of {date, weight_kg} actual weigh-ins
   *   stats    — {delta_7d_kg, current_weight_kg}
   *
   * @param {object}   todayMarker
   * @param {Array}    actuals
   * @param {object}   stats
   * @returns {{ pillText: string|null, message: string, state: string }}
   */
  function verdictCopy(todayMarker, actuals, stats) {
    if (!todayMarker || todayMarker.trend_kg == null || todayMarker.plan_kg == null) {
      return { pillText: null, message: '—', state: 'no_data' };
    }

    var tm      = todayMarker;
    var gapDir  = tm.gap_direction;

    if (!gapDir || gapDir === 'no_data') {
      return { pillText: null, message: '—', state: 'no_data' };
    }

    var trendStr = tm.trend_kg.toFixed(1);
    var planStr  = tm.plan_kg.toFixed(1);
    var absGap   = tm.gap_kg != null ? Math.abs(tm.gap_kg).toFixed(1) : '?';

    if (gapDir === 'ahead') {
      return {
        pillText: 'AHEAD −' + absGap + ' kg',
        message:  'Your 7-day trend (' + trendStr + ' kg) is running ahead of plan (' + planStr + ' kg) — keep that pace.',
        state:    'ahead'
      };
    }

    if (gapDir === 'on_plan') {
      return {
        pillText: 'ON TRACK',
        message:  'Trend right on plan at ' + trendStr + ' kg — consistent logging is working.',
        state:    'on_plan'
      };
    }

    if (gapDir === 'behind') {
      var lever = _nextLever(actuals, stats);
      return {
        pillText: 'BEHIND +' + absGap + ' kg',
        message:  'Trend (' + trendStr + ' kg) is above plan (' + planStr + ' kg). ' + lever,
        state:    'behind'
      };
    }

    return { pillText: null, message: '—', state: 'no_data' };
  }

  function _nextLever(actuals, stats) {
    var last7 = (actuals || []).slice(-7).filter(function (a) {
      return a.weight_kg != null;
    });
    if (last7.length >= 2) {
      return 'Repeat your two lightest days from last week.';
    }
    return 'Aim for a lighter day tomorrow to nudge the trend down.';
  }

  /**
   * projectionLabel — forward-looking label for the projected-from-trend path.
   * Frames the scenario as a realistic path forward, not a comparison to the
   * original plan slope.
   *
   * @param {number|null} goalKg   - projected goal weight
   * @param {string|null} dateStr  - ISO date string of projected arrival
   * @returns {string}
   */
  function projectionLabel(goalKg, dateStr) {
    if (goalKg == null && !dateStr) return 'Your path from here';
    var datePart = '';
    if (dateStr) {
      var d = new Date(dateStr + 'T00:00:00');
      datePart = ' by ' + d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
    var kgPart = goalKg != null ? ' · ' + goalKg.toFixed(0) + ' kg' : '';
    return 'Realistic path from today' + kgPart + datePart;
  }

  /**
   * whatIfHeadline — "still-winnable" framing for the what-if panel.
   *
   * @param {string|null} targetDate - ISO date string of original goal date
   * @returns {string}
   */
  function whatIfHeadline(targetDate) {
    if (!targetDate) return 'Even a small adjustment gets you there.';
    var d   = new Date(targetDate + 'T00:00:00');
    var lbl = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    return 'Even at a gentler rate you’d arrive by ' + lbl + '.';
  }

  /**
   * nearMilestoneCopy — short-horizon copy when within 4 weeks of next milestone.
   *
   * @param {number|null} weeksAway - estimated weeks at current rate
   * @returns {string|null}
   */
  function nearMilestoneCopy(weeksAway) {
    if (weeksAway == null || weeksAway <= 0 || weeksAway > 4) return null;
    var n = Math.max(1, Math.round(weeksAway));
    return 'About ' + n + ' week' + (n === 1 ? '' : 's') + ' at this rate';
  }

  /**
   * dashIfNull — null-safe value formatter.
   *
   * @param {*}          val
   * @param {Function}  [fmt]
   * @returns {string}
   */
  function dashIfNull(val, fmt) {
    if (val == null) return '—'; // em-dash —
    return fmt ? fmt(val) : String(val);
  }

  root.WeightVoice = {
    verdictCopy:       verdictCopy,
    projectionLabel:   projectionLabel,
    whatIfHeadline:    whatIfHeadline,
    nearMilestoneCopy: nearMilestoneCopy,
    dashIfNull:        dashIfNull
  };
}(window));
