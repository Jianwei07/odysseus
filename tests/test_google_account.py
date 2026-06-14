"""Shared Google identity component: scope minimization, legacy migration,
and the no-secret-leak guarantee on the frontend-facing view."""

import pytest

from src import google_account


@pytest.fixture
def prefs_store(monkeypatch):
    """In-memory stand-in for the per-user prefs persistence layer."""
    store: dict = {}

    def _load(owner=None):
        return dict(store.get(owner or "", {}))

    def _save(owner, prefs):
        store[owner or ""] = dict(prefs)

    monkeypatch.setattr("routes.prefs_routes._load_for_user", _load)
    monkeypatch.setattr("routes.prefs_routes._save_for_user", _save)
    return store


# ── scope minimization (security) ───────────────────────────────────────────

def test_requested_scopes_calendar_is_minimal():
    scopes = google_account.requested_scopes(["calendar"]).split()
    assert "openid" in scopes and "email" in scopes
    assert "https://www.googleapis.com/auth/calendar" in scopes
    # Gmail's broad mailbox scope must NOT be requested for a calendar-only grant.
    assert "https://mail.google.com/" not in scopes


def test_gmail_scope_is_opt_in():
    scopes = google_account.requested_scopes(["calendar", "gmail"]).split()
    assert "https://mail.google.com/" in scopes


# ── no-secret-leak guarantee ─────────────────────────────────────────────────

def test_safe_view_never_exposes_secrets():
    acc = {
        "id": "a1", "provider": "google", "label": "Google (me@x.com)",
        "email": "me@x.com", "client_id": "cid",
        "client_secret": "enc:supersecret", "refresh_token": "enc:rt",
        "access_token": "ya29.live", "access_expiry": "2030-01-01T00:00:00",
        "scopes": ["openid", "email"],
    }
    view = google_account.safe_view(acc)
    blob = repr(view)
    for secret in ("client_secret", "refresh_token", "access_token",
                   "enc:supersecret", "enc:rt", "ya29.live", "cid"):
        assert secret not in blob
    assert view["connected"] is True and view["email"] == "me@x.com"


def test_safe_view_connected_false_without_refresh_token():
    assert google_account.safe_view({"id": "a", "provider": "google"})["connected"] is False


# ── legacy migration + store roundtrip ──────────────────────────────────────

def test_legacy_calendar_accounts_migrated(prefs_store):
    prefs_store["owner@x"] = {"calendar_accounts": [{"id": "old", "provider": "google"}]}
    accounts = google_account.load_accounts("owner@x")
    assert [a["id"] for a in accounts] == ["old"]
    # Migration persists under the new key so it happens only once.
    assert prefs_store["owner@x"].get(google_account.GOOGLE_ACCOUNTS_KEY)


def test_upsert_get_delete_roundtrip(prefs_store):
    acc = google_account.upsert_account("o", {"provider": "google", "label": "G"})
    assert acc["id"]
    assert google_account.get_account("o", acc["id"])["label"] == "G"
    assert google_account.delete_account("o", acc["id"]) is True
    assert google_account.get_account("o", acc["id"]) is None
