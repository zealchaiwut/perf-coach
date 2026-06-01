# Feel Entries

## Purpose

Feel entries capture a user's subjective training feel for a given day. Each entry records an optional RPE (Rate of Perceived Exertion) score on a 1–10 scale and optional free-text notes. Together they let users track how their body and mind responded to training load over time, independent of objective metrics like heart rate or pace.

Feel entries complement the objective data in `workouts`, `daily_metrics`, and `training_load` snapshots. They are particularly useful for weekly review workflows where you want to correlate subjective feel with TSB/ATL curves.

## Data Shape

Each feel entry has the following fields:

| Field | Type | Constraints |
|---|---|---|
| `id` | UUID | auto-generated |
| `user_id` | UUID | required, immutable |
| `feel_date` | date (YYYY-MM-DD) | required, immutable, cannot be in the future |
| `workout_id` | UUID \| null | optional, set manually or via auto-link |
| `rpe_1_to_10` | integer \| null | 1–10 inclusive; at least one of `rpe_1_to_10` or `notes` required |
| `notes` | text \| null | max 10,000 characters; free-text subjective observations |
| `created_at` | datetime | auto-generated |
| `updated_at` | datetime | updated on PATCH |

**RPE scale guidance:**
- 1–3: Very easy / recovery
- 4–6: Moderate / aerobic
- 7–8: Hard / threshold
- 9–10: Maximal effort / race

## Auto-Link Behaviour

When a new feel entry is POSTed without an explicit `workout_id`, the system attempts to auto-link it to a workout on the same date for the same user:

- **Exactly one workout** on that date → `workout_id` is set to that workout's ID.
- **Multiple workouts** on that date → `workout_id` remains `null` (ambiguous; link manually via PATCH).
- **No workouts** on that date → `workout_id` remains `null`.

Auto-link failure (e.g., database error) does not fail the POST — the entry is saved with `workout_id: null` and a warning is logged.

You can also trigger auto-link manually for existing entries via:

```
POST /api/feel/auto-link?user_id={uid}&feel_date={YYYY-MM-DD}
```

This links all unlinked entries for that user/date that have exactly one candidate workout. Re-running is idempotent (already-linked entries are skipped).

## Search Endpoint

Search feel entries by keyword in the `notes` field:

```
GET /api/feel/search?user_id={uid}&q={term}[&from={YYYY-MM-DD}][&to={YYYY-MM-DD}]
```

**Behaviour:**
- Case-insensitive substring match using `ILIKE`.
- Returns at most **50 results** per call (no pagination).
- Results ordered by `feel_date` descending, then `created_at` descending.
- Each result includes all standard feel entry fields plus a `preview` field.
- `preview` contains ~80 characters around the match with the matched text wrapped in `**bold markdown**`.
- Returns HTTP 422 if `q` is fewer than 2 characters.

**Response shape:**
```json
{
  "results": [
    {
      "id": "...",
      "feel_date": "2026-05-10",
      "rpe_1_to_10": 7,
      "notes": "Good workout. Hamstring held up well...",
      "preview": "Good workout. **Hamstring** held up well...",
      ...
    }
  ],
  "count": 1
}
```

## Query Examples

**All entries for a user in May 2026:**
```
GET /api/feel?user_id={uid}&from=2026-05-01&to=2026-05-31
```

**Entries with an RPE score only:**
```
GET /api/feel?user_id={uid}&has_rpe=true
```

**Summary stats for the last 30 days:**
```
GET /api/feel/summary?user_id={uid}&from=2026-05-02&to=2026-06-01
```

**Search for 'hamstring' mentions:**
```
GET /api/feel/search?user_id={uid}&q=hamstring
```

**Search restricted to a date range:**
```
GET /api/feel/search?user_id={uid}&q=hamstring&from=2026-05-01&to=2026-05-31
```

**Summary endpoint fields:**
```
GET /api/feel/summary?user_id={uid}&from=2026-05-01&to=2026-05-31
```
Returns:
```json
{
  "total_entries": 10,
  "linked_to_workouts": 4,
  "standalone": 6,
  "avg_rpe": 5.86,
  "min_rpe": 1,
  "max_rpe": 10,
  "rpe_distribution": {"1": 1, "3": 1, "4": 1, "5": 1, "7": 1, "8": 1, "9": 1, "10": 1},
  "entries_with_notes": 8,
  "avg_notes_length_chars": 112.5,
  "date_range": {"first": "2026-05-02", "last": "2026-05-28"}
}
```

## Example Weekly Review Workflow

1. **Load the week's feel entries:**
   ```
   GET /api/feel?user_id={uid}&from=2026-05-26&to=2026-06-01
   ```
   Note which days have entries and their RPE values.

2. **Cross-reference with training load:**
   ```
   GET /api/training-load/snapshots?user_id={uid}&from=2026-05-26&to=2026-06-01
   ```
   Compare TSB (freshness) values against the feel RPE scores. High RPE on negative TSB days is expected; high RPE on positive TSB days may indicate illness or life stress.

3. **Search for recurring issues:**
   ```
   GET /api/feel/search?user_id={uid}&q=hamstring&from=2026-05-01&to=2026-06-01
   ```
   Recurring keywords in notes (e.g., "hamstring", "tight", "heavy legs") across multiple weeks can surface injury patterns before they become acute.

4. **Get monthly summary stats:**
   ```
   GET /api/feel/summary?user_id={uid}&from=2026-05-01&to=2026-05-31
   ```
   Use `avg_rpe`, `rpe_distribution`, and `entries_with_notes` to gauge overall training load perception for the month.

5. **Log next week's entry immediately after each workout:**
   ```
   POST /api/feel
   {"user_id": "...", "feel_date": "2026-06-02", "rpe_1_to_10": 6, "notes": "Good aerobic effort. No issues."}
   ```
   The system auto-links to the workout if there is exactly one for that day.
