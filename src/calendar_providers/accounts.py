"""Calendar's view of the shared Google account store.

The Google OAuth identity is now owned by :mod:`src.google_account` (a single
sign-in shared across Calendar, Gmail, …). This module is a thin compatibility
shim so existing ``from . import accounts as account_store`` imports keep
working; it just re-exports the shared store's functions.
"""

from __future__ import annotations

from src.google_account import (  # noqa: F401
    GOOGLE_ACCOUNTS_KEY as CALENDAR_ACCOUNTS_KEY,
    load_accounts,
    save_accounts,
    get_account,
    upsert_account,
    delete_account,
    safe_view,
)
