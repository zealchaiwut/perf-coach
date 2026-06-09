# Strava Integration Setup

## Manual Setup Checklist

1. **Create a Strava API Application**
   - Go to https://www.strava.com/settings/api
   - Fill in Application Name, Website, and Authorization Callback Domain
   - Set the Authorization Callback Domain to your deployment domain (e.g. `localhost` for local dev)
   - Note the **Client ID** and **Client Secret**

2. **Set Environment Variables**
   ```
   STRAVA_CLIENT_ID=<your client ID>
   STRAVA_CLIENT_SECRET=<your client secret>
   STRAVA_REDIRECT_URI=https://<your-domain>/api/strava/callback
   STRAVA_STATE_SECRET=<random 32+ char string>
   ```

3. **Generate `STATE_SECRET`**
   - Run `python -c "import secrets; print(secrets.token_hex(32))"` and store the output as `STRAVA_STATE_SECRET`
   - This secret signs CSRF-protection tokens in the OAuth flow

4. **OAuth Flow**
   - Call `GET /api/strava/connect` → receive `authorize_url`
   - Open URL in browser; user authorises the app
   - Strava redirects to `/api/strava/callback` with `code` and `state`
   - Tokens are stored in `strava_tokens` table

5. **Verify Connection**
   - Call `GET /api/strava/status` → should return `{"connected": true, ...}`

## Sync workflow

### Triggering a manual sync

1. Navigate to **Settings → Integrations** and expand the Strava card.
2. Click **Sync now** to open the sync panel.
3. Optionally set a **Since** date (defaults to the last synced date or 90 days back for a fresh user).
4. Click **Preview** to see which activities would be created or matched without writing to the database.
5. Click **Run sync** to start the pull. Progress is shown in the panel and in the nav status bar while the job is running.
6. When the job completes, the panel shows new-workout counts and a link to the training log.

The sync history panel (below the sync controls) shows the last 5 jobs with their status, duration, and counters. Click **Sync history** to expand it.

### What happens during a sync run

1. `POST /api/strava/sync` is called; the server starts a background thread and returns 202 immediately.
2. The worker calls `sync_strava_activities(user_id, since_date)` from `backend/services/strava_sync.py`.
3. Activities are fetched from the Strava API page-by-page (`after` epoch filter) and upserted into the `strava_activities` table.
4. A `SyncJob` row is written to the `sync_jobs` table tracking status, counters, and any error.
5. After pulling completes, a reconcile phase merges `strava_activities` into the canonical `workouts` table.
6. `GET /api/sync/status` (polled every 2 s by the UI) reflects the running job state; the job registry is in-memory (`backend/services/sync_jobs.py`).

### Deduplication logic

- Each Strava activity is upserted by `strava_activity_id` (unique index on `strava_activities`).
- Re-running the same date range is fully idempotent: existing rows are updated in place, no duplicates are created.
- During reconcile, a Strava activity is matched to an existing workout by `strava_activity_pk`; if no match exists, a new workout row is created.
- The `activities_updated` counter tracks upserts to existing rows; `activities_created` tracks brand-new inserts.

### Scheduled sync (coming soon)

Automatic background syncs every hour are planned. For now, manual sync only. The Settings page shows a placeholder for this feature.

To run a one-off sync from the command line (e.g., from a cron job):

```bash
python scripts/run_strava_sync.py --user_id <UUID> --env uat
```

Omit `--user_id` to fall back to the first user with a connected Strava token. See `scripts/run_strava_sync.py --help` for full usage.

## Known Limitations

- **Polling only.** Sync is manual (triggered from Settings) or via CLI. Webhook / real-time push is not implemented.
- **Single athlete.** One Strava account per user. Multi-account and athlete-team scenarios are not supported.
- **Activity types.** Only standard Strava activity types (Run, Ride, etc.) are reconciled. Uncommon sport types may map to a generic workout type.
- **Scheduled sync.** Automatic background syncs are planned but not yet active. The Settings page shows a placeholder.

## Notes

- Tokens are refreshed automatically when less than 5 minutes remain on the access token.
- To revoke access, call `DELETE /api/strava/disconnect`. This removes the local token row and optionally calls the Strava deauthorize endpoint.
- Sync job history is stored persistently in the `sync_jobs` table and queryable via `GET /api/sync/history`.
