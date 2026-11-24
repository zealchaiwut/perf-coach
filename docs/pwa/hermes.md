# Hermes morning brief — perf-coach contract

The Hermes change lives in the Hermes repo. This file is the perf-coach side:
URLs, auth, and when to wake the sleeping free-tier server.

## Auth

Machine callers use the existing API token:

```
Authorization: Bearer <api_token>
```

Tokens are stored hashed in `api_tokens` and resolved by `resolve_user` in
`backend/auth.py`. A read-scoped token is enough for the GET endpoints below.
Do not send a session cookie from Hermes.

## Wake the server first

Free-tier Render sleeps. About **10 minutes before** the brief is sent:

```
GET /api/mobile/ping
```

- Response: **204**
- No database work, no auth required
- Safe to retry; ignore the body

If ping is slow or fails, still send the brief. The installed app will wake
the server itself from the status pill.

## Today's session for the brief

```
GET /api/mobile/today-link
Authorization: Bearer <api_token>
```

JSON shape:

| Field | Meaning |
| --- | --- |
| `date` | Asia/Bangkok `YYYY-MM-DD` |
| `kind` | today's session kind (`strength`, `run`, `rest`, …) |
| `session_id` | planned session id, or null |
| `session_name` | planned session name, or null |
| `gym_url` | `/m/gym/{id}` when today is strength, else null |
| `today_url` | always `/m/today` |
| `weigh_in_url` | always `/m/body/weigh-in` |

## Links to put in the brief

Open in the **installed** app (manifest `start_url` is `/m/today`, scope `/`).
These paths are served from the app shell cache when offline.

| When | Label | URL |
| --- | --- | --- |
| Always | Today | `/m/today` |
| Today is strength and `gym_url` is set | Start {session_name} | `/m/gym/{session_id}` |
| Always | Weigh in | `/m/body/weigh-in` |

Example strength day:

- Start Strength A · economy → `https://<host>/m/gym/<session_id>`
- Weigh in → `https://<host>/m/body/weigh-in`

The gym URL opens the session overview. If a gym session is already in
progress on that phone, the same URL resumes the player.

## Origin

Use the same public origin as the installed PWA (UAT or PRD). Relative paths
above are on that origin.
