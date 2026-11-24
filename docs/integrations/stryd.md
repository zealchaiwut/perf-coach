# Stryd Integration Setup

## Manual Setup Checklist

1. **Obtain a Fernet Encryption Key**
   ```python
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   ```
   Store the output as `STRYD_FERNET_KEY`. **Keep this value secret and back it up** — losing it means encrypted passwords in the database cannot be recovered.

2. **Set Environment Variables**
   ```
   STRYD_FERNET_KEY=<Fernet key from above>
   ```

3. **Connect via API**
   - Call `POST /api/stryd/connect` with `{"email": "...", "password": "..."}`
   - The password is encrypted with Fernet before storage; the plaintext is never persisted
   - On success, a row is written to `stryd_credentials`

4. **Session Lifecycle**
   - Stryd sessions last approximately 25 days
   - Sessions are refreshed automatically (re-authenticating with the stored encrypted password) when less than 1 day remains
   - If re-authentication fails (wrong password, account locked), `GET /api/stryd/status` returns `connected: false` and **deletes** the credentials row

5. **Verify Connection**
   - Call `GET /api/stryd/status` → should return `{"connected": true, ...}`

6. **Revoke Access**
   - Call `DELETE /api/stryd/disconnect` to remove the credentials row

## Security Notes

- Passwords are encrypted at rest using Fernet symmetric encryption
- The Fernet key must be set via the `STRYD_FERNET_KEY` environment variable
- Session tokens are stored in plaintext (they expire); only the password is encrypted
