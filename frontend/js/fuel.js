'use strict';

// Fuel today + Fuel week (Weight tab). Reuses apiFetch()/todayISO() from
// weight.js (loaded first — see weight.html's script tags).

// ── State ────────────────────────────────────────────────────────────────

let _fuelToday = null;      // last /api/fuel/today response
let _fuelWriteTimer = null; // debounce handle for entry writes
const FUEL_ENTRY_DEBOUNCE_MS = 400;

const FUEL_FIELDS = ['meat_g', 'rice_g', 'eggs', 'fruit_g', 'oil_tsp'];
const FUEL_STEP_DECIMALS = { meat_g: 0, rice_g: 0, eggs: 0, fruit_g: 0, oil_tsp: 1 };

const FUEL_DAY_TYPE_LABEL = {
  rest: 'REST',
  lift: 'LIFT',
  easy_run: 'EASY RUN',
  long_run: 'LONG RUN',
};
const FUEL_WEEKDAY_ABBR = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];

// ── Formatting helpers ───────────────────────────────────────────────────

function _fuelWeekdayLong(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric', month: 'short' });
}

function _fuelMondayOf(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  const dow = d.getDay();
  const diff = dow === 0 ? -6 : 1 - dow;
  d.setDate(d.getDate() + diff);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

// ── Fuel today: fetch + render ───────────────────────────────────────────

async function _fuelLoadToday() {
  try {
    const data = await apiFetch('/api/fuel/today');
    _fuelToday = data;
    _fuelRenderToday(data);
  } catch (e) {
    if (e.message !== 'auth') {
      console.error('Fuel today load failed:', e);
    }
  }
}

function _fuelRenderToday(d) {
  const pill = document.getElementById('fuel-daytype-pill');
  if (pill) pill.textContent = FUEL_DAY_TYPE_LABEL[d.day_type] || d.day_type.toUpperCase();

  const subline = document.getElementById('fuel-subline');
  if (subline) {
    const dateLabel = _fuelWeekdayLong(d.date);
    let text = dateLabel;
    if (d.burn > 0) text += ` · burn ~${d.burn.toLocaleString()} kcal`;
    subline.textContent = text;
    if (d.maintenance_source === 'estimated') {
      const chip = document.createElement('span');
      chip.className = 'fuel-estimated-chip';
      chip.textContent = 'estimated';
      chip.title = 'Maintenance is an estimate until Calibrate runs — click the cog to calibrate.';
      chip.addEventListener('click', _fuelToggleSettings);
      subline.appendChild(document.createTextNode(' '));
      subline.appendChild(chip);
    }
  }

  const phaseChip = document.getElementById('fuel-phase-chip');
  if (phaseChip && d.week_phase && d.week_phase !== 'base') {
    phaseChip.textContent = d.week_phase_reason || d.week_phase;
    phaseChip.className = `fuel-phase-chip phase-${d.week_phase}`;
    phaseChip.title = `Effective deficit: ${d.effective_deficit_kcal} kcal`;
    phaseChip.hidden = false;
  } else if (phaseChip) {
    phaseChip.hidden = true;
  }

  const budgetNum = document.getElementById('fuel-budget-num');
  if (budgetNum) budgetNum.textContent = d.budget.toLocaleString();

  const chip = document.getElementById('fuel-deficit-chip');
  if (chip) {
    if (d.deficit_reduced) {
      chip.className = 'fuel-deficit-chip reduced';
      chip.textContent = `deficit ${d.deficit_target} → ${d.deficit_applied}`;
    } else {
      chip.className = 'fuel-deficit-chip on-target';
      chip.textContent = `deficit -${d.deficit_applied}`;
    }
  }

  document.getElementById('fuel-chain-base').textContent = d.base_kcal.toLocaleString();
  document.getElementById('fuel-chain-burn').textContent = d.burn.toLocaleString();
  document.getElementById('fuel-chain-deficit').textContent = d.deficit_applied.toLocaleString();
  document.getElementById('fuel-chain-budget').textContent = d.budget.toLocaleString();

  const reducedNote = document.getElementById('fuel-reduced-note');
  if (reducedNote) {
    if (d.deficit_reduced) {
      reducedNote.hidden = false;
      reducedNote.textContent =
        `Deficit reduced ${d.deficit_target} → ${d.deficit_applied} because today's training burn ` +
        `would otherwise push energy availability below the floor.`;
    } else {
      reducedNote.hidden = true;
    }
  }

  document.getElementById('fuel-eaten-label').textContent = d.eaten.kcal.toLocaleString();
  document.getElementById('fuel-remaining-label').textContent = Math.max(0, d.remaining).toLocaleString();

  const fill = document.getElementById('fuel-bar-fill');
  if (fill) {
    const pct = d.budget > 0 ? Math.min(100, (d.eaten.kcal / d.budget) * 100) : 0;
    const over = d.eaten.kcal > d.budget;
    fill.style.width = (over ? 100 : pct) + '%';
    fill.className = 'fuel-bar-fill' + (over ? ' over' : '');
  }
  const tick = document.getElementById('fuel-bar-floor-tick');
  if (tick && d.budget > 0) {
    const floorPct = Math.min(100, Math.max(0, (d.ea_floor_kcal / d.budget) * 100));
    tick.style.left = floorPct + '%';
    tick.style.display = d.ea_floor_kcal < d.budget ? '' : 'none';
  }

  _fuelSetMacro('protein', d.eaten.protein_g, d.targets.protein_g);
  _fuelSetMacro('carbs', d.eaten.carbs_g, d.targets.carbs_g);
  _fuelSetMacro('fat', d.eaten.fat_g, d.targets.fat_g);

  FUEL_FIELDS.forEach((f) => {
    const input = document.getElementById('fuel-' + f);
    if (input && document.activeElement !== input) {
      input.value = d.entry[f];
    }
  });
  document.getElementById('fuel-other-kcal-label').textContent = (d.entry.other_kcal || 0).toLocaleString();
  _fuelUpdateRowKcal();

  _fuelRenderSuggestion(d.suggestion);

  const guard = document.getElementById('fuel-ea-guard');
  const guardText = document.getElementById('fuel-ea-guard-text');
  if (guard && guardText) {
    if (d.ea != null && d.ea < 30) {
      const needed = Math.max(0, Math.round(d.ea_floor_kcal - d.eaten.kcal));
      guard.hidden = false;
      guardText.innerHTML =
        `Energy availability ${d.ea} kcal/kg — below the 30 threshold. ` +
        `Eat at least <b>${needed}</b> more kcal today.`;
    } else {
      guard.hidden = true;
    }
  }
}

function _fuelSetMacro(name, eaten, target) {
  const eatenEl = document.getElementById(`fuel-${name}-eaten`);
  const targetEl = document.getElementById(`fuel-${name}-target`);
  const barEl = document.getElementById(`fuel-${name}-bar`);
  if (eatenEl) eatenEl.textContent = Math.round(eaten);
  if (targetEl) targetEl.textContent = Math.round(target);
  if (barEl) barEl.style.width = target > 0 ? Math.min(100, (eaten / target) * 100) + '%' : '0%';
}

function _fuelRenderSuggestion(s) {
  const el = document.getElementById('fuel-suggestion');
  if (!el) return;
  if (s.message) {
    el.hidden = false;
    el.textContent = s.message;
  } else if (s.text) {
    el.hidden = false;
    el.innerHTML = '<b>Suggested:</b> ' + s.text;
  } else {
    el.hidden = true;
  }
}

// ── Row kcal display (local, instant feedback) ──────────────────────────

const FUEL_ROW_KCAL_PER_UNIT = { meat_g: 1.65, rice_g: 1.30, eggs: 70.0, fruit_g: 0.60, oil_tsp: 45.0 };

function _fuelUpdateRowKcal() {
  FUEL_FIELDS.forEach((f) => {
    const input = document.getElementById('fuel-' + f);
    const kcalEl = document.getElementById('fuel-' + f + '-kcal');
    if (!input || !kcalEl) return;
    const v = parseFloat(input.value) || 0;
    kcalEl.textContent = Math.round(v * FUEL_ROW_KCAL_PER_UNIT[f]).toLocaleString();
  });
}

// ── Entry writes (debounced) ─────────────────────────────────────────────

function _fuelScheduleEntryWrite() {
  if (_fuelWriteTimer) clearTimeout(_fuelWriteTimer);
  _fuelWriteTimer = setTimeout(_fuelWriteEntry, FUEL_ENTRY_DEBOUNCE_MS);
}

async function _fuelWriteEntry(extraFields) {
  const body = { entry_date: todayISO() };
  FUEL_FIELDS.forEach((f) => {
    const input = document.getElementById('fuel-' + f);
    if (input) body[f] = parseFloat(input.value) || 0;
  });
  if (extraFields) Object.assign(body, extraFields);
  try {
    const res = await fetch('/api/fuel/entry', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _fuelCsrfToken() },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _fuelToday = data;
    _fuelRenderToday(data);
  } catch (e) {
    console.error('Fuel entry save failed:', e);
  }
}

function _fuelCsrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]+)/);
  return m ? m[1] : '';
}

// ── Steppers ─────────────────────────────────────────────────────────────

function _fuelInitSteppers() {
  document.querySelectorAll('.fuel-stepper-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const row = btn.closest('.fuel-log-row');
      const input = row.querySelector('.fuel-stepper-input');
      const step = parseFloat(btn.dataset.step);
      const field = input.id.replace('fuel-', '');
      const decimals = FUEL_STEP_DECIMALS[field] ?? 0;
      let v = (parseFloat(input.value) || 0) + step;
      if (v < 0) v = 0;
      input.value = decimals > 0 ? v.toFixed(decimals) : String(Math.round(v));
      _fuelUpdateRowKcal();
      _fuelScheduleEntryWrite();
    });
  });
  FUEL_FIELDS.forEach((f) => {
    const input = document.getElementById('fuel-' + f);
    if (input) {
      input.addEventListener('input', () => {
        _fuelUpdateRowKcal();
        _fuelScheduleEntryWrite();
      });
    }
  });
}

// ── Preset buttons ────────────────────────────────────────────────────────

const FUEL_PRESETS = {
  // Rough additions to the other_* bucket — not the 5 tracked rows.
  standard: { other_kcal: 550, other_protein_g: 35, other_carbs_g: 55, other_fat_g: 18 },
  postrun: { other_kcal: 350, other_protein_g: 25, other_carbs_g: 45, other_fat_g: 6 },
  snack: { other_kcal: 200, other_protein_g: 5, other_carbs_g: 28, other_fat_g: 8 },
};

function _fuelInitPresets() {
  document.querySelectorAll('.fuel-preset-btn[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = btn.dataset.preset;
      if (preset === 'reset') {
        FUEL_FIELDS.forEach((f) => {
          const input = document.getElementById('fuel-' + f);
          if (input) input.value = 0;
        });
        _fuelUpdateRowKcal();
        _fuelWriteEntry({
          other_kcal: 0, other_protein_g: 0, other_carbs_g: 0, other_fat_g: 0,
          meat_g: 0, rice_g: 0, eggs: 0, fruit_g: 0, oil_tsp: 0,
        });
        return;
      }
      const add = FUEL_PRESETS[preset];
      if (!add || !_fuelToday) return;
      const cur = _fuelToday.entry;
      _fuelWriteEntry({
        other_kcal: (cur.other_kcal || 0) + add.other_kcal,
        other_protein_g: add.other_protein_g,
        other_carbs_g: add.other_carbs_g,
        other_fat_g: add.other_fat_g,
      });
    });
  });
}

// ── Settings panel ────────────────────────────────────────────────────────

function _fuelToggleSettings() {
  const panel = document.getElementById('fuel-settings-panel');
  if (!panel) return;
  panel.hidden = !panel.hidden;
  if (!panel.hidden && _fuelToday) _fuelPopulateSettingsForm();
}

async function _fuelPopulateSettingsForm() {
  try {
    const s = await apiFetch('/api/fuel/settings');
    FUEL_SETTINGS_FIELDS.forEach((f) => {
      const input = document.getElementById('fs-' + f);
      if (input) input.value = s[f];
    });
    const toggle = document.getElementById('fs-auto_periodize');
    if (toggle) toggle.checked = s.auto_periodize !== false;
  } catch (e) {
    if (e.message !== 'auth') console.error('Fuel settings load failed:', e);
  }
}

const FUEL_SETTINGS_FIELDS = [
  'weight_kg', 'lean_mass_kg', 'base_kcal', 'deficit_kcal',
  'protein_g_per_kg', 'fat_g', 'ea_floor', 'run_kcal_per_kg_per_km',
];

function _fuelInitSettingsForm() {
  const toggle = document.getElementById('fuel-settings-toggle');
  if (toggle) toggle.addEventListener('click', _fuelToggleSettings);

  const saveBtn = document.getElementById('fuel-settings-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const body = {};
      FUEL_SETTINGS_FIELDS.forEach((f) => {
        const input = document.getElementById('fs-' + f);
        if (input && input.value !== '') body[f] = parseFloat(input.value);
      });
      const toggle = document.getElementById('fs-auto_periodize');
      if (toggle) body.auto_periodize = toggle.checked;
      const errEl = document.getElementById('fuel-settings-error');
      if (errEl) errEl.hidden = true;
      try {
        const res = await fetch('/api/fuel/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _fuelCsrfToken() },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          if (errEl) {
            errEl.hidden = false;
            errEl.textContent = err.detail || `Save failed (HTTP ${res.status})`;
          }
          return;
        }
        const data = await res.json();
        _fuelToday = data;
        _fuelRenderToday(data);
        document.getElementById('fuel-settings-panel').hidden = true;
      } catch (e) {
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = 'Save failed: ' + e.message;
        }
      }
    });
  }

  const calBtn = document.getElementById('fuel-calibrate-btn');
  if (calBtn) {
    calBtn.addEventListener('click', async () => {
      const errEl = document.getElementById('fuel-settings-error');
      try {
        const res = await fetch('/api/fuel/calibrate', {
          method: 'POST',
          headers: { 'X-CSRF-Token': _fuelCsrfToken() },
        });
        const data = await res.json();
        if (res.status === 422 && data.error_code === 'needs_more_data') {
          if (errEl) {
            errEl.hidden = false;
            errEl.textContent =
              `Not enough history yet (${data.days_logged}/${data.required_days} days, ` +
              `${data.entries_logged}/${data.required_entries} logged days).`;
          }
          return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await _fuelLoadToday();
        if (errEl) errEl.hidden = true;
      } catch (e) {
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = 'Calibrate failed: ' + e.message;
        }
      }
    });
  }
}

// ── Fuel week ─────────────────────────────────────────────────────────────

async function _fuelLoadWeek() {
  try {
    const weekStart = _fuelMondayOf(todayISO());
    const data = await apiFetch('/api/fuel/week?week_start=' + weekStart);
    _fuelRenderWeek(data);
  } catch (e) {
    if (e.message !== 'auth') {
      console.error('Fuel week load failed:', e);
    }
  }
}

function _fuelRenderWeek(w) {
  const container = document.getElementById('fuel-week-bars');
  if (!container) return;
  container.innerHTML = '';
  const today = todayISO();
  const maxBudget = Math.max(1, ...w.days.map((d) => d.budget));

  w.days.forEach((d, i) => {
    const col = document.createElement('div');
    col.className = 'fuel-week-day ' + d.day_type + (d.date === today ? ' today' : '');

    const bar = document.createElement('div');
    bar.className = 'fuel-week-bar ' + (d.is_actual ? 'actual' : 'planned');
    if (d.date === today) bar.classList.add('today');
    const height = Math.max(30, (d.budget / maxBudget) * 90);
    bar.style.minHeight = height + 'px';
    bar.textContent = d.budget.toLocaleString();
    col.appendChild(bar);

    const lbl = document.createElement('div');
    lbl.className = 'fuel-week-daylbl';
    lbl.textContent = FUEL_WEEKDAY_ABBR[i];
    col.appendChild(lbl);

    if (d.session_status === 'skipped') {
      const skipped = document.createElement('div');
      skipped.className = 'fuel-week-skipped';
      skipped.textContent = 'skipped ' + (d.day_type === 'lift' ? 'lift' : 'session');
      col.appendChild(skipped);
    } else {
      const eaten = document.createElement('div');
      eaten.className = 'fuel-week-eaten' + (d.eaten > d.budget ? ' over' : '');
      eaten.textContent = d.eaten.toLocaleString();
      col.appendChild(eaten);
    }

    container.appendChild(col);
  });

  const note = document.getElementById('fuel-week-note');
  if (note) {
    let phaseNote = '';
    if (w.week_phase && w.week_phase !== 'base') {
      phaseNote = ` <b>${w.week_phase_reason}</b> ·`;
    }
    note.innerHTML =
      `Budget follows the plan.${phaseNote} <b>Past days use logged workouts; future days use planned sessions.</b> ` +
      `Weekly <b>${w.weekly_budget_total.toLocaleString()}</b> vs ${w.weekly_maintenance_total.toLocaleString()} ` +
      `maintenance ≈ ${w.projected_kg_per_week >= 0 ? '-' : '+'}${Math.abs(w.projected_kg_per_week)} kg/week.`;
  }
}

// ── Plan-mismatch banner (AC4) ────────────────────────────────────────────

async function _fuelLoadPlanMismatch() {
  try {
    const s = await apiFetch('/api/fuel/settings');
    _fuelRenderPlanMismatch(s);
  } catch (e) {
    if (e.message !== 'auth') console.error('Fuel settings load failed:', e);
  }
}

function _fuelRenderPlanMismatch(s) {
  const banner = document.getElementById('fuel-plan-mismatch');
  if (!banner) return;
  if (s.consistency !== 'mismatch') {
    banner.hidden = true;
    return;
  }
  const textEl = document.getElementById('fuel-plan-mismatch-text');
  if (textEl) {
    textEl.textContent =
      `Plan implies ~${s.implied_deficit_kcal} kcal/day, Fuel is set to ${s.deficit_kcal}`;
  }
  banner.hidden = false;
}

function _fuelInitPlanMismatch() {
  const btn = document.getElementById('fuel-plan-sync-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const res = await fetch('/api/fuel/settings/sync-deficit', {
        method: 'POST',
        headers: { 'X-CSRF-Token': _fuelCsrfToken() },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      _fuelRenderPlanMismatch(updated);
      // Refresh both cards so budget and weekly projection reflect new deficit
      await _fuelLoadToday();
      await _fuelLoadWeek();
    } catch (e) {
      console.error('Sync deficit failed:', e);
    } finally {
      btn.disabled = false;
    }
  });
}

// ── Weekly cut review ─────────────────────────────────────────────────────

const _CUT_REVIEW_LABELS = {
  insufficient_data: 'Not enough data yet',
  slow_down: 'Slow down — losing too fast',
  on_track: 'On track',
  check_logging: 'Log food more consistently',
  recalibrate_maintenance: 'Consider recalibrating maintenance',
  increase_deficit: 'Behind plan — consider a small cut',
  ease_off: 'Ahead of plan — ease off',
  plateau: 'Plateau — weight has stalled',
};

async function _fuelLoadWeeklyReview() {
  const card = document.getElementById('cut-review-card');
  if (!card) return;
  try {
    const data = await apiFetch('/api/fuel/weekly-review');
    _fuelRenderWeeklyReview(data);
  } catch (e) {
    if (e.message !== 'auth') {
      const loading = document.getElementById('cut-review-loading');
      if (loading) loading.textContent = 'Review unavailable.';
    }
  }
}

function _fuelRenderWeeklyReview(d) {
  const loading = document.getElementById('cut-review-loading');
  const body = document.getElementById('cut-review-body');
  const badge = document.getElementById('cut-review-badge');
  if (!body) return;

  // Locked payload: no conclusions — leave the card empty (lock-group covers it).
  if (d.gated || d.recommendation === 'insufficient_coverage') {
    if (loading) loading.hidden = true;
    body.hidden = true;
    if (badge) badge.hidden = true;
    return;
  }

  if (loading) loading.hidden = true;
  body.hidden = false;

  const rec = d.recommendation;
  const headline = document.getElementById('cut-review-headline');
  if (headline) headline.textContent = _CUT_REVIEW_LABELS[rec] || rec;

  const action = document.getElementById('cut-review-action');
  if (action) action.textContent = d.action || '';

  // Plateau section: show day count + calibrate link when recommendation is plateau
  const plateauSection = document.getElementById('cut-review-plateau');
  if (plateauSection) {
    if (rec === 'plateau' && d.plateau_days != null) {
      const daysEl = document.getElementById('cut-review-plateau-days');
      if (daysEl) daysEl.textContent = d.plateau_days;
      plateauSection.hidden = false;
    } else {
      plateauSection.hidden = true;
    }
  }

  const actualEl = document.getElementById('cut-review-actual-rate');
  if (actualEl) {
    if (d.actual_rate_kg_per_week != null) {
      const val = Math.abs(d.actual_rate_kg_per_week).toFixed(2);
      const sign = d.actual_rate_kg_per_week < 0 ? '−' : '+';
      actualEl.textContent = sign + val;
    } else {
      actualEl.textContent = '—';
    }
  }

  const planEl = document.getElementById('cut-review-plan-rate');
  if (planEl) {
    if (d.plan_rate_kg_per_week != null) {
      const val = Math.abs(d.plan_rate_kg_per_week).toFixed(2);
      const sign = d.plan_rate_kg_per_week < 0 ? '−' : '+';
      planEl.textContent = sign + val;
    } else {
      planEl.textContent = '—';
    }
  }

  if (badge) {
    badge.textContent = rec.replace(/_/g, ' ');
    const colorMap = {
      on_track: 'on-target',
      insufficient_data: '',
      slow_down: 'reduced',
      ease_off: 'reduced',
      increase_deficit: '',
      check_logging: '',
      recalibrate_maintenance: '',
      plateau: '',
    };
    badge.className = 'fuel-deficit-chip ' + (colorMap[rec] || '');
    badge.style.display = '';
  }
}

// ── Init ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('fuel-section')) return; // page has no Fuel section
  _fuelInitSteppers();
  _fuelInitPresets();
  _fuelInitSettingsForm();
  _fuelInitPlanMismatch();
  _fuelLoadToday();
  _fuelLoadWeek();
  _fuelLoadPlanMismatch();
  _fuelLoadWeeklyReview();
});
