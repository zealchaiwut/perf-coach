/**
 * Weekly check-in page controller (issue #926).
 *
 * Fetches GET /api/weekly-check-in and renders four sections:
 *   1. Week summary (three fact lines)
 *   2. Bright spot (one highlight)
 *   3. Next-week lever (one action)
 *   4. Recommit beat (top 3 focus habits with keep/adjust controls)
 *
 * Focus-habit cooldown is stored in localStorage so no new DB field is needed.
 * When building=true the correlation fetch is skipped (AC10) — the backend
 * enforces this and returns correlations_fetched=false.
 */

'use strict';

// ── Constants ─────────────────────────────────────────────────────────────────

const LS_KEY = 'checkin_cooldowns';    // localStorage key for cooldown map
// Cooldown period is returned by the API as cooldown_days per habit.
// We also store the server's value locally so keep/adjust reflect it.

// ── DOM refs ──────────────────────────────────────────────────────────────────

const $weekLabel      = document.getElementById('week-label');
const $skeleton       = document.getElementById('skeleton');
const $baseline       = document.getElementById('baseline-section');
const $baselineReason = document.getElementById('baseline-reason');
const $full           = document.getElementById('full-section');
const $recommitCard   = document.getElementById('recommit-card');
const $recommitNotice = document.getElementById('recommit-notice');
const $habitRows      = document.getElementById('habit-rows');

// Week summary line elements
const $lineWeight   = document.getElementById('line-weight');
const $lineHabits   = document.getElementById('line-habits');
const $lineTraining = document.getElementById('line-training');

// Bright spot
const $brightText   = document.getElementById('bright-spot-text');
const $brightSource = document.getElementById('bright-spot-source');

// Lever
const $leverText    = document.getElementById('lever-text');

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _setWeekLabel();
  _load();
});

// ── Week label ────────────────────────────────────────────────────────────────

function _setWeekLabel() {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - today.getDay() + (today.getDay() === 0 ? -6 : 1));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  $weekLabel.textContent = `${fmt(monday)} – ${fmt(sunday)}`;
}

// ── Data load ─────────────────────────────────────────────────────────────────

async function _load() {
  try {
    const resp = await fetch('/api/weekly-check-in', { credentials: 'include' });
    if (resp.status === 401) {
      window.location.href = '/login';
      return;
    }
    if (!resp.ok) {
      _showError('Unable to load check-in data. Please try again later.');
      return;
    }
    const data = await resp.json();
    _render(data);
  } catch (err) {
    _showError('Network error. Please check your connection.');
  }
}

// ── Render ────────────────────────────────────────────────────────────────────

function _render(data) {
  $skeleton.hidden = true;

  if (data.building) {
    _renderBaseline(data);
  } else {
    _renderFull(data);
  }

  if (data.focus_habits && data.focus_habits.length > 0) {
    _renderRecommitBeat(data.focus_habits);
  }
}

function _renderBaseline(data) {
  $baseline.hidden = false;
  $full.hidden = true;
  if (data.reason) {
    $baselineReason.textContent = data.reason;
  }
}

function _renderFull(data) {
  $full.hidden = false;
  $baseline.hidden = true;

  const ws = data.week_summary || {};

  // Weight trend
  if (ws.weight_trend) {
    $lineWeight.textContent = ws.weight_trend;
  } else {
    $lineWeight.innerHTML = '<span class="line-null">Not enough weight data yet.</span>';
  }

  // Habit consistency
  if (ws.habit_consistency) {
    $lineHabits.textContent = ws.habit_consistency;
  } else {
    $lineHabits.innerHTML = '<span class="line-null">No habit data this week.</span>';
  }

  // Training note
  if (ws.training_note) {
    $lineTraining.textContent = ws.training_note;
  } else {
    $lineTraining.innerHTML = '<span class="line-null">No workouts logged this week.</span>';
  }

  // Bright spot
  if (data.bright_spot) {
    $brightText.textContent = data.bright_spot.text;
    if (data.bright_spot.source) {
      const label = {
        correlation: 'Data-backed',
        consistency: 'Consistency',
        streak: 'Streak',
        training: 'Training',
      }[data.bright_spot.source] || data.bright_spot.source;
      $brightSource.innerHTML = `<span class="source-chip">${label}</span>`;
    }
  } else {
    document.getElementById('bright-spot-card').hidden = true;
  }

  // Next-week lever
  if (data.next_lever) {
    $leverText.textContent = data.next_lever.text;
  } else {
    document.getElementById('lever-card').hidden = true;
  }
}

// ── Recommit beat ─────────────────────────────────────────────────────────────

function _renderRecommitBeat(focusHabits) {
  _focusHabitsCache = focusHabits;
  $recommitCard.hidden = false;
  $habitRows.innerHTML = '';

  const cooldowns = _loadCooldowns();

  focusHabits.forEach((habit) => {
    const cooldownDays = habit.cooldown_days || 7;
    const adjustedAt = cooldowns[habit.id] || null;
    const inCooldown = adjustedAt
      ? _daysSince(adjustedAt) < cooldownDays
      : false;
    const daysLeft = adjustedAt
      ? cooldownDays - _daysSince(adjustedAt)
      : 0;

    const row = document.createElement('div');
    row.className = 'habit-row';

    const pct = typeof habit.consistency_percent === 'number'
      ? Math.round(habit.consistency_percent)
      : 0;
    const weekDone = habit.week_done ?? 0;
    const weekTarget = habit.weekly_target ?? 7;

    row.innerHTML = `
      <div class="habit-info">
        <div class="habit-name">${_esc(habit.name)}</div>
        <div class="habit-meta">${weekDone} of ${weekTarget} this week · ${pct}% consistency</div>
        ${inCooldown ? `<div class="cooldown-badge">Adjust available in ${daysLeft} day${daysLeft !== 1 ? 's' : ''}</div>` : ''}
      </div>
      <div class="habit-controls">
        <button class="btn-keep" data-habit-id="${_esc(habit.id)}" data-action="keep">Keep</button>
        <button class="btn-adjust" data-habit-id="${_esc(habit.id)}" data-action="adjust"
          ${inCooldown ? 'disabled aria-disabled="true"' : ''}>Adjust</button>
      </div>
    `;

    $habitRows.appendChild(row);
  });

  $habitRows.addEventListener('click', _onRecommitClick);
}

function _onRecommitClick(evt) {
  const btn = evt.target.closest('[data-action]');
  if (!btn) return;

  const habitId = btn.dataset.habitId;
  const action  = btn.dataset.action;

  if (action === 'keep') {
    _handleKeep(habitId, btn);
  } else if (action === 'adjust' && !btn.disabled) {
    _handleAdjust(habitId, btn);
  }
}

function _handleKeep(habitId, btn) {
  // Keep = confirm habit stays; no server change needed.
  btn.textContent = 'Kept';
  btn.disabled = true;
  const adjBtn = btn.closest('.habit-controls').querySelector('[data-action="adjust"]');
  if (adjBtn) adjBtn.disabled = true;
  _flashNotice();
}

function _handleAdjust(habitId, btn) {
  // Adjust = record cooldown start; prompt user to visit Habits settings to swap.
  const cooldowns = _loadCooldowns();
  cooldowns[habitId] = new Date().toISOString().slice(0, 10);
  _saveCooldowns(cooldowns);

  btn.disabled = true;
  btn.textContent = 'Adjusted';
  const keepBtn = btn.closest('.habit-controls').querySelector('[data-action="keep"]');
  if (keepBtn) keepBtn.disabled = true;

  // Update the cooldown badge
  const row = btn.closest('.habit-row');
  const infoEl = row.querySelector('.habit-info');
  let badge = infoEl.querySelector('.cooldown-badge');
  if (!badge) {
    badge = document.createElement('div');
    badge.className = 'cooldown-badge';
    infoEl.appendChild(badge);
  }

  const focusHabit = _focusHabitsCache.find((h) => h.id === habitId);
  const cooldownDays = focusHabit ? (focusHabit.cooldown_days || 7) : 7;
  badge.textContent = `Adjust available in ${cooldownDays} day${cooldownDays !== 1 ? 's' : ''}`;

  _flashNotice();
}

function _flashNotice() {
  $recommitNotice.classList.add('visible');
  setTimeout(() => $recommitNotice.classList.remove('visible'), 3500);
}

// ── LocalStorage helpers ──────────────────────────────────────────────────────

let _focusHabitsCache = [];

function _loadCooldowns() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || '{}');
  } catch {
    return {};
  }
}

function _saveCooldowns(map) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(map));
  } catch {
    // Ignore storage errors (private browsing, full quota)
  }
}

function _daysSince(isoDate) {
  const then = new Date(isoDate);
  const now  = new Date();
  const diff = now - then;
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

// ── Error state ───────────────────────────────────────────────────────────────

function _showError(msg) {
  $skeleton.hidden = true;
  const div = document.createElement('div');
  div.className = 'error-msg';
  div.textContent = msg;
  document.getElementById('content').appendChild(div);
}

// ── XSS guard ─────────────────────────────────────────────────────────────────

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Populate _focusHabitsCache when render is called
// (hoisted capture — must follow _render so the reference is live)
