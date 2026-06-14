# Google integration (shared sign-in)

One Google OAuth sign-in is the single auth unit for all Google features in
Odysseus. Calendar consumes it today; Gmail is a designed-for, not-yet-wired
follow-up. Setup once, reuse everywhere — no per-feature re-authorization.

## Architecture

```
        ┌─────────────────────────────┐
        │  Google account (1 OAuth)   │  src/google_account.py
        │  client_id/secret + refresh │  (account store + token refresh + scopes)
        └──────────────┬──────────────┘
                get_access_token(owner, account)
                 ┌──────┴──────┐
        GoogleCalendarProvider   Gmail (phase 2)
        → calendar grid          → existing inbox + email tools
```

- **`src/google_account.py`** — owns the OAuth identity: per-user
  `google_accounts` pref store (migrates legacy `calendar_accounts`),
  scope registry, token refresh/cache, `safe_view`.
- **`routes/google_routes.py`** — `/api/google/*`: account CRUD + OAuth
  authorize/callback. Feature-neutral so Gmail reuses it.
- **`src/calendar_providers/google.py`** — calendar consumer; pulls events into
  the shared `calendar_events` table and writes through on edits.
- **`static/js/google_connect.js`** — one connect form used by both the calendar
  settings overlay and Settings → Integrations.

## Security / privacy

- **Encrypted at rest.** `client_secret` and `refresh_token` are Fernet-encrypted
  (`src/secret_storage.py`, key `data/.app_key`, mode `0o600`). A stolen DB or
  backup yields no plaintext secret.
- **Nothing ships in the repo.** `data/` (DB + key) and `.env` are gitignored.
- **Self-hosted.** The OAuth redirect URI is derived from the request origin, so
  any host/port works without configuration.
- **Secrets never leave the backend.** Only `safe_view` (`id`/`provider`/`label`/
  `email`/`scopes`/`connected`) is returned to the frontend; covered by
  `tests/test_google_account.py`.
- **Minimal scope.** A calendar connect requests only
  `openid email https://www.googleapis.com/auth/calendar`. The broad Gmail
  mailbox scope is requested only when the Gmail feature is enabled.

## Setup

1. Google Cloud Console → create/select a project → enable the
   **Google Calendar API**.
2. OAuth consent screen → External; add your address as a test user.
3. Credentials → Create OAuth Client ID → **Web application**. Add redirect URI:
   `http://<your-host>:<port>/api/google/oauth/callback`
   (e.g. `http://localhost:7070/api/google/oauth/callback`).
4. In Odysseus: Settings → Integrations → **+ Add Integration → Google**
   (or Calendar gear ⚙ → Add calendar → **+ Google**). Paste the client ID +
   secret, click Connect, approve consent. The calendar syncs automatically.

## Gmail seam (phase 2 — not wired)

Mechanical from the current state (see `src/google_account.py` bottom):

1. Add `"gmail"` to the connect flow's requested capabilities (adds
   `https://mail.google.com/`).
2. Give `EmailAccount` an `auth_mode` (`password`|`google_oauth`) +
   `google_account_id`; auto-provision a Gmail account on connect
   (imap.gmail.com:993 / smtp.gmail.com:465).
3. In `routes/email_helpers.py`, when `auth_mode == "google_oauth"`, replace
   `conn.login(...)` / `smtp.login(...)` with XOAUTH2 using
   `google_account.get_access_token(...)`.

The existing inbox UI and the three agent email tools then work unchanged.
