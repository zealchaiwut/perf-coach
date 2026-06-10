# Weight Page — Redesign Investigation

## File Paths

| Asset | Path |
|---|---|
| Weight page HTML | `frontend/pages/weight.html` |
| Weight targets page HTML | `frontend/pages/weight-targets.html` |
| Weight page JS | `frontend/js/weight.js` |
| Weight targets JS | `frontend/js/weight-targets.js` |
| Weight status service | `backend/services/weight_status.py` |
| Weight plan service (new) | `backend/services/weight_plan.py` |
| All weight endpoints | `backend/main.py` (lines ~553–1245) |

## Endpoint Response Shapes

### `GET /api/weight-entries`

Query params: `user_id`, `from` (date), `to` (date), `limit`, `offset`

```json
{
  "entries": [
    {
      "id": "<uuid>",
      "user_id": "<uuid>",
      "entry_date": "YYYY-MM-DD",
      "entry_time": "HH:MM:SS or null",
      "weight_kg": 82.5,
      "notes": "string or null",
      "source": "manual|imported|backfill",
      "created_at": "<iso datetime>",
      "updated_at": "<iso datetime>"
    }
  ],
  "count": 42,
  "min_kg": 80.0,
  "max_kg": 85.0,
  "avg_kg": 82.3
}
```

### `GET /api/weight-targets/active`

Query param: `user_id`

Pre-ticket response shape (all fields still required for backward compat):

```json
{
  "target": {
    "id": "<uuid>",
    "user_id": "<uuid>",
    "start_weight_kg": 85.0,
    "start_date": "YYYY-MM-DD",
    "target_weight_kg": 75.0,
    "target_date": "YYYY-MM-DD",
    "status": "active",
    "notes": "string or null",
    "end_weight_kg": null,
    "ended_at": null,
    "created_at": "<iso datetime>",
    "updated_at": "<iso datetime>",
    "progress_pct": 42.0,
    "kg_to_go": 5.8,
    "days_remaining": 73,
    "required_pace_kg_per_week": 0.555,
    "current_pace_kg_per_week": 0.48,
    "projected_end_date": "YYYY-MM-DD or null",
    "status_label": "on_track|behind|ahead|no_data"
  }
}
```

Post-ticket additions: `plan_today_kg`, `gap_kg`, `gap_direction`, `gap_basis`, `milestones`.
See Part B — Endpoint in issue #420 for full shape.

### Chart endpoint: `GET /api/weight-chart`

Query params: `user_id`, `from`, `to`, `include_target` (bool)

```json
{
  "actuals": [{"date": "YYYY-MM-DD", "weight_kg": 82.5, "entry_id": "<uuid>"}],
  "trend": [{"date": "YYYY-MM-DD", "weight_kg": 82.1}],
  "target": {
    "target_weight_kg": 75.0,
    "target_date": "YYYY-MM-DD",
    "projected_path": [{"date": "YYYY-MM-DD", "weight_kg": 83.0}]
  },
  "stats": {"delta_kg": -2.1, "delta_days": 30, "count": 18}
}
```

The `projected_path` in the chart response is the scheduled plan line (linear interpolation from start to target), generated inside `main.py` around line 1380–1420.

## Chart Library

**Chart.js 4.4.0** — loaded via CDN in `weight.html`:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
```

Canvas element id: `weight-chart`. The instance is managed in `frontend/js/weight.js`.

## Milestone Logic

**Currently absent.** No milestone generation exists anywhere. `weight.js` calls `renderMilestones(_activeTarget, chartData.stats)` (line 802) but that function renders from whatever fields the active-target response provides — which has none yet. The AC for issue #420 defines the milestone spec.

## `no_data` Enum Leak Locations

| Location | File:Line | Context |
|---|---|---|
| `weight_status.py:32` | `backend/services/weight_status.py:32` | `compute_status_label` returns `"no_data"` when `current_avg_kg is None` |
| `_pr_trend` returns `"no_data"` | `backend/main.py:1687,1691` | Personal records trend helper, unrelated to weight |
| `home.js comment` | `frontend/js/home.js:558` | JS comment: `/* stable or no_data */` — no rendering impact |
| `_compute_weight_target_active` | `backend/main.py:999` | Calls `_compute_status_label` which can emit `no_data`; result stored in `status_label` field and returned to client |

The primary leak path is: `compute_status_label` → `status_label` field in active-target response → `weight-targets.js:236–244` renders `status_label` as a UI pill without guarding for `no_data`. The `labelMap` on line 244 falls back to class `'on-track'` for unknown values, so the pill shows the raw string `"no_data"` when no data is present.

After this ticket, `gap_direction: "no_data"` is the canonical field; `status_label` is retained as a deprecated field.

---

## Post-ship verification

Results recorded after the weight redesign shipped (sprint 53.1, issue #427).

### Fresh-user (no data, no target set)

- Weight page loads without JS errors on a new account with zero weight entries and no target.
- Empty-state UI renders correctly; no-data coach strip state displayed.
- Chart renders cleanly with no actuals/trend/plan lines and no crash.

### Active flow (hero log + backfill row)

- User with an active target logs today's weight via hero stepper → entry saves, plan-vs-actual delta updates immediately, coach strip reflects new state, milestone chart redraws.
- Backfill row used to enter weight for 5 days ago → entry saves to correct date, 7-day rolling average recalculates, `gap_direction` reflects updated average.

### Behind-plan render

- Seeded entries set user more than 0.2 kg above target trajectory.
- Coach strip shows behind-plan state (amber); gap indicator is negative (heavier than plan); correct copy displayed.

### Ahead-of-plan render

- Seeded entries set user more than 0.2 kg below target trajectory.
- Coach strip shows ahead-of-plan state (green); gap indicator is positive (lighter than plan); milestone dates shift correctly.

### No-target render

- Weight target removed from an account that has existing weight entries.
- Plan line absent from chart; milestone section hidden or shows appropriate empty state; no JS errors.
