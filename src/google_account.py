"""Shared Google OAuth identity — the single auth unit for all Google features.

One Google sign-in grants access that multiple Odysseus features consume:
**Calendar** today, **Gmail** next (see the seam at the bottom of this file).
Rather than re-authorizing per feature, a single ``google_accounts`` record
holds the OAuth client + refresh token + the set of granted scopes, and every
consumer asks this module for a fresh access token.

Storage lives in per-user prefs (``routes.prefs_routes``); the two secret
fields (``client_secret``, ``refresh_token``) are Fernet-encrypted at rest via
``src.secret_storage`` so a stolen DB/backup never yields plaintext. ``data/``
(holding the DB + key) is gitignored, so nothing secret ships in a contribution.

Account dict shape::

    {
      "id": "<uuid>",
      "provider": "google",                # always "google" here
      "label": "Google (you@gmail.com)",
      "email": "you@gmail.com",            # filled from userinfo after consent
      "client_id": "<oauth client id>",
      "client_secret": "<enc:...>",        # Fernet-encrypted
      "refresh_token": "<enc:...>",        # Fernet-encrypted, set after consent
      "access_token": "<cached, short-lived>",
      "access_expiry": "<iso8601 utc>",
      "scopes": ["openid", "email", ".../auth/calendar"],
      "calendars": {local_id: {gcal_id, name}},  # owned by the calendar feature
    }

Only ``safe_view`` is ever returned to the frontend — it strips every secret.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# Pref key for the shared Google identity store. Legacy calendar-only records
# lived under ``calendar_accounts``; ``load_accounts`` migrates them in place.
GOOGLE_ACCOUNTS_KEY = "google_accounts"
_LEGACY_KEY = "calendar_accounts"
_SECRET_FIELDS = ("client_secret", "refresh_token")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# ── Scope registry ──────────────────────────────────────────────────────────
# A capability maps to the OAuth scope(s) it needs. We request only the scopes
# for the capabilities actually enabled, so a leaked token can't reach features
# the user never connected. ``openid``/``email`` are always requested so we can
# label the account with its address.
BASE_SCOPES = ["openid", "email"]
SCOPES = {
    "calendar": "https://www.googleapis.com/auth/calendar",
    # Gmail IMAP/SMTP XOAUTH2 needs the broad mailbox scope. Defined here so the
    # Gmail seam (below) is a one-line capability addition — NOT requested yet.
    "gmail": "https://mail.google.com/",
}


def requested_scopes(capabilities: list[str]) -> str:
    """Space-joined scope string for the given capabilities (+ base scopes)."""
    scopes = list(BASE_SCOPES)
    for cap in capabilities:
        scope = SCOPES.get(cap)
        if scope and scope not in scopes:
            scopes.append(scope)
    return " ".join(scopes)


# ── Account store ─────────────────────────────────────────────────────────
def load_accounts(owner: str, provider: str | None = None) -> list[dict]:
    """All Google accounts for *owner*. Migrates legacy ``calendar_accounts``."""
    from routes.prefs_routes import _load_for_user, _save_for_user
    prefs = _load_for_user(owner) or {}
    accounts = list(prefs.get(GOOGLE_ACCOUNTS_KEY) or [])
    if not accounts and prefs.get(_LEGACY_KEY):
        # One-time migration: calendar_accounts → google_accounts.
        accounts = list(prefs.get(_LEGACY_KEY) or [])
        prefs[GOOGLE_ACCOUNTS_KEY] = accounts
        _save_for_user(owner, prefs)
        logger.info("Migrated %d legacy calendar_accounts to google_accounts for owner", len(accounts))
    if provider:
        accounts = [a for a in accounts if a.get("provider") == provider]
    return accounts


def save_accounts(owner: str, accounts: list[dict]) -> None:
    from routes.prefs_routes import _load_for_user, _save_for_user
    prefs = _load_for_user(owner) or {}
    prefs[GOOGLE_ACCOUNTS_KEY] = accounts
    _save_for_user(owner, prefs)


def get_account(owner: str, account_id: str) -> dict | None:
    return next((a for a in load_accounts(owner) if a.get("id") == account_id), None)


def upsert_account(owner: str, account: dict) -> dict:
    """Insert or replace an account by id (generating one if absent)."""
    if not account.get("id"):
        account["id"] = str(uuid.uuid4())
    accounts = load_accounts(owner)
    idx = next((i for i, a in enumerate(accounts) if a.get("id") == account["id"]), None)
    if idx is None:
        accounts.append(account)
    else:
        accounts[idx] = account
    save_accounts(owner, accounts)
    return account


def delete_account(owner: str, account_id: str) -> bool:
    accounts = load_accounts(owner)
    remaining = [a for a in accounts if a.get("id") != account_id]
    if len(remaining) == len(accounts):
        return False
    save_accounts(owner, remaining)
    return True


def safe_view(account: dict) -> dict:
    """Account stripped of every secret, for returning to the frontend."""
    return {
        "id": account.get("id", ""),
        "provider": account.get("provider", "google"),
        "label": account.get("label", "") or account.get("email", "") or "Google",
        "email": account.get("email", ""),
        "scopes": list(account.get("scopes") or []),
        "connected": bool(account.get("refresh_token")),
    }


# ── Token lifecycle ─────────────────────────────────────────────────────────
async def get_access_token(owner: str, account: dict) -> str:
    """Return a valid access token for *account*, refreshing + caching as needed.

    Consumed by every Google feature (calendar today, gmail next). Persists the
    refreshed token back to the account store so concurrent callers reuse it.
    """
    from src.secret_storage import decrypt
    tok = account.get("access_token")
    exp = account.get("access_expiry")
    if tok and exp:
        try:
            if datetime.fromisoformat(exp) - timedelta(seconds=60) > datetime.utcnow():
                return tok
        except ValueError:
            pass
    refresh = decrypt(account.get("refresh_token") or "")
    client_id = account.get("client_id") or ""
    client_secret = decrypt(account.get("client_secret") or "")
    if not (refresh and client_id and client_secret):
        raise RuntimeError("Google account not fully authorized")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        })
    resp.raise_for_status()
    data = resp.json()
    account["access_token"] = data["access_token"]
    account["access_expiry"] = (
        datetime.utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)))
    ).isoformat()
    upsert_account(owner, account)
    return account["access_token"]


async def fetch_user_email(access_token: str) -> str:
    """Best-effort OpenID userinfo lookup to label the account. "" on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code == 200:
            return (resp.json().get("email") or "").strip()
    except Exception:
        logger.debug("userinfo lookup failed", exc_info=True)
    return ""


# ── Gmail seam (phase 2 — NOT wired yet) ─────────────────────────────────────
# Adding Gmail is mechanical from here:
#   1. Request the "gmail" capability in the authorize flow (adds SCOPES["gmail"]).
#   2. On connect, auto-provision an EmailAccount (imap.gmail.com:993 /
#      smtp.gmail.com:465, from=email, auth_mode="google_oauth",
#      google_account_id=account["id"]).
#   3. In routes/email_helpers: when auth_mode == "google_oauth", replace
#      conn.login(...) / smtp.login(...) with XOAUTH2 using get_access_token().
# The existing inbox UI + the 3 agent email tools then work unchanged.
