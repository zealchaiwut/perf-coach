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

## Notes

- The current implementation uses the first user (alphabetically) as the single-user target. Multi-user OAuth is out of scope for this sprint.
- Tokens are refreshed automatically when less than 5 minutes remain on the access token.
- To revoke access, call `DELETE /api/strava/disconnect`. This removes the local token row and optionally calls the Strava deauthorize endpoint.
