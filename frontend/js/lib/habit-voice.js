/**
 * habit-voice.js — Coaching copy for habit logging surfaces (issue #920).
 *
 * All coaching strings for the quick-log, streak-feedback, and milestone
 * surfaces are produced here. No surface hard-codes its own copy strings.
 *
 * Mirror of backend/services/habit_voice.py — same branching logic so
 * frontend rendering stays in sync with backend-computed framing.
 *
 * Public API
 * ----------
 * HabitVoice.compose(habit, weekDone, weekTarget, totalLogs, isMiss, currentStreak)
 *   → { message, framing, showIdentity, nextMilestone }
 *
 * HabitVoice.identityLine(habitName)
 *   → string for "you are becoming" copy
 */
(function (root) {
  'use strict';

  var _MILESTONES = [10, 25, 30, 50, 75, 100, 150, 200, 250, 365, 500, 750, 1000];
  var _MILESTONE_SET = new Set(_MILESTONES);
  var _STREAK_LANDMARKS = new Set([7, 14, 21, 30, 60, 90, 180, 365]);

  function _nextMilestone(total) {
    for (var i = 0; i < _MILESTONES.length; i++) {
      if (_MILESTONES[i] > total) return _MILESTONES[i];
    }
    return null;
  }

  function _isWeeklyHabit(habit) {
    if (habit.schedule_type === 'times_per_week') return true;
    var wt = habit.weekly_target != null ? parseFloat(habit.weekly_target) : null;
    return wt !== null && wt < 7;
  }

  /**
   * Compose coaching copy for one habit log event.
   *
   * @param {object} habit        - Habit row from /api/habits/summary
   * @param {number} weekDone     - Completions in current Mon–Sun week (from API)
   * @param {number|null} weekTarget  - Habit's weekly target (from API)
   * @param {number} totalLogs    - All-time log count (from API)
   * @param {boolean} isMiss      - True when triggered by a recognised missed day
   * @param {number} currentStreak - Current streak length (default 0)
   * @returns {{ message: string, framing: string, showIdentity: boolean, nextMilestone: number|null }}
   */
  function compose(habit, weekDone, weekTarget, totalLogs, isMiss, currentStreak) {
    var name = (habit && habit.name) ? habit.name : 'this habit';
    var streak = currentStreak || 0;
    var wd = weekDone != null ? Math.floor(weekDone) : 0;
    var wt = weekTarget != null ? Math.floor(weekTarget) : 7;

    // ── Milestone detection ──────────────────────────────────────────────────
    if (_MILESTONE_SET.has(totalLogs)) {
      var nxt = _nextMilestone(totalLogs);
      var msg = 'You’ve logged ' + name + ' ' + totalLogs + ' times.';
      if (nxt !== null) msg += ' Next landmark: ' + nxt + '.';
      return { message: msg, framing: 'milestone', showIdentity: true, nextMilestone: nxt };
    }

    // ── Miss acknowledgement ─────────────────────────────────────────────────
    if (isMiss) {
      var missMsg = 'Yesterday slipped—' + wd + ' of ' + wt +
        ' this week still puts you ahead of most.';
      return { message: missMsg, framing: 'miss', showIdentity: false, nextMilestone: null };
    }

    // ── Streak landmark ──────────────────────────────────────────────────────
    if (streak > 0 && _STREAK_LANDMARKS.has(streak)) {
      var sMsg = streak + '-period streak on ' + name + '. ' +
        'You are becoming someone who does this consistently.';
      return { message: sMsg, framing: 'streak', showIdentity: true, nextMilestone: null };
    }

    // ── Weekly-cadence framing (< 7×/week) ───────────────────────────────────
    if (_isWeeklyHabit(habit)) {
      var wMsg = wd >= wt
        ? 'On track—' + wd + ' of ' + wt + ' this week.'
        : wd + ' of ' + wt + ' this week. Keep going.';
      return { message: wMsg, framing: 'weekly', showIdentity: false, nextMilestone: null };
    }

    // ── Routine daily log ────────────────────────────────────────────────────
    return { message: 'Logged. Keep it going.', framing: 'routine', showIdentity: false, nextMilestone: null };
  }

  /**
   * Return identity-framing copy for a habit name.
   * Only call this when showIdentity is true.
   */
  function identityLine(habitName) {
    var n = habitName || 'this habit';
    return 'You are becoming someone who prioritises ' + n + '.';
  }

  root.HabitVoice = { compose: compose, identityLine: identityLine };
}(window));
