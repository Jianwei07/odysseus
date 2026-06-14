"""Storage for OAuth-style calendar accounts (Google, later Outlook).

CalDAV keeps its own ``caldav_accounts`` pref key and loader
(``src/caldav_sync._load_caldav_accounts``) untouched — this module manages a
separate ``calendar_accounts`` list for the OAuth providers so existing CalDAV
users are unaffected. Both stores live in per-user prefs
(``routes/prefs_routes``) and secrets are encrypted with ``src/secret_storage``.

Account dict shape (Google)::

    {
      "id": "<uuid>",
      "provider": "google",
      "label": "Google (you@gmail.com)",
      "client_id": "<oauth client id>",
      "client_secret": "<encrypted>",
      "refresh_token": "<encrypted>",      # set after OAuth consent
      "access_token": "<cached, plaintext, short-lived>",
      "access_expiry": "<iso8601 utc>",
    }
"""

from __future__ import annotations

import uuid

CALENDAR_ACCOUNTS_KEY = "calendar_accounts"
_SECRET_FIELDS = ("client_secret", "refresh_token")


def load_accounts(owner: str, provider: str | None = None) -> list[dict]:
    """All OAuth calendar accounts for *owner*, optionally filtered by provider."""
    from routes.prefs_routes import _load_for_user
    prefs = _load_for_user(owner) or {}
    accounts = list(prefs.get(CALENDAR_ACCOUNTS_KEY) or [])
    if provider:
        accounts = [a for a in accounts if a.get("provider") == provider]
    return accounts


def save_accounts(owner: str, accounts: list[dict]) -> None:
    from routes.prefs_routes import _load_for_user, _save_for_user
    prefs = _load_for_user(owner) or {}
    prefs[CALENDAR_ACCOUNTS_KEY] = accounts
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
    """Account stripped of secrets, for returning to the frontend."""
    return {
        "id": account.get("id", ""),
        "provider": account.get("provider", ""),
        "label": account.get("label", "") or account.get("provider", ""),
        "connected": bool(account.get("refresh_token")),
    }
