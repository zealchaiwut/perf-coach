# API Tokens — Scoped read-only machine-caller credentials

Issue: [#1759](https://github.com/zealchaiwut/perf-coach/issues/1759)

Machine callers (e.g. viral-radar) need to read perf-coach data from the
Render web service without a browser session. API tokens provide a
`Authorization: Bearer <token>` credential that is scoped to a single user
and limited to read-only operations.

## How tokens work

1. A user (or admin on their behalf) calls `POST /api/auth/tokens` while
   authenticated via the normal session cookie.
2. The response includes a plaintext token — **store it immediately**. It is
   shown exactly once and never retrievable again.
3. The caller puts the plaintext token in the `Authorization` header:

   ```
   Authorization: Bearer <plaintext-token>
   ```

4. On each request the server hashes the presented token with SHA-256 and
   looks up the hash in the `api_tokens` table. A matching, non-revoked row
   authenticates the request as the token's owner.
5. **Read-only enforcement**: any mutating route (POST / PUT / PATCH / DELETE)
   that uses the `require_write` dependency returns `403 Forbidden` if the
   request is authenticated via a read-only Bearer token.

## Token endpoints

| Method | Path | Auth required | What it does |
|--------|------|---------------|--------------|
| `POST` | `/api/auth/tokens` | Session cookie or Bearer | Create a new read-only token |
| `GET` | `/api/auth/tokens` | Session cookie or Bearer | List your active (non-revoked) tokens |
| `DELETE` | `/api/auth/tokens/{token_id}` | Session cookie or Bearer | Revoke a token by id |

### Create a token

```http
POST /api/auth/tokens
Cookie: session=<your-session>

{"label": "viral-radar-hub"}
```

Response (`201`):

```json
{
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "token": "abc123...",
  "scope": "read",
  "label": "viral-radar-hub",
  "note": "Store this token securely — it will not be shown again."
}
```

### Revoke a token

```http
DELETE /api/auth/tokens/{token_id}
Cookie: session=<your-session>
```

Returns `204 No Content` on success. Revocation is a soft-delete
(`revoked_at` is set); the row is kept for audit purposes.

## Where the token lives in Render

The **caller** (e.g. viral-radar) stores the plaintext token as a Render
environment variable in its own service dashboard
(`Dashboard → Service → Environment → Add env var`).

The perf-coach web service stores only the **SHA-256 hash** in the `api_tokens`
Postgres table — never the plaintext. No Render environment variable is needed
on the perf-coach side; the DB is the source of truth.

## Rotation

To rotate a token without downtime:

1. Create a new token via `POST /api/auth/tokens`.
2. Update the caller's Render environment variable to the new plaintext token
   and redeploy the caller.
3. Verify the caller is working with the new token.
4. Revoke the old token via `DELETE /api/auth/tokens/{old_token_id}`.

## Security notes

- Tokens are 256-bit random secrets (`secrets.token_hex(32)`).
- The server hashes with SHA-256 (no salt needed for high-entropy random
  values). `secrets.compare_digest` is **not** used here because SHA-256 of a
  256-bit random value is already constant-time to compare in Python's `==`;
  timing attacks against a hash require knowing the plaintext, which an
  attacker cannot derive from the hash.
- CSRF protection is **not** applied to Bearer-token requests (they do not
  carry cookies, so they are not susceptible to CSRF).
- Tokens are user-scoped: a token holder can only read data belonging to the
  token's owner.
