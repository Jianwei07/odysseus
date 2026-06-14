"""Shared Google OAuth + account API (``/api/google``).

Feature-neutral so every Google consumer reuses one sign-in: Calendar today,
Gmail next. The OAuth identity + token lifecycle live in
:mod:`src.google_account`; this router is the HTTP surface for connecting,
listing, and removing Google accounts. Secrets are encrypted at rest and never
returned (only :func:`src.google_account.safe_view`).

Redirect URI is derived from the incoming request origin, so a self-hosted
instance on any host/port works without configuration.
"""

from __future__ import annotations

import html
import logging
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routes.calendar_routes import _require_user
from src import google_account
from src.secret_storage import encrypt, decrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google", tags=["google"])

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Capabilities this connect flow currently requests. Calendar only for now;
# adding "gmail" here (once the email XOAUTH2 seam is wired) is the single
# change needed to widen the grant. Kept minimal so a leaked token's blast
# radius matches exactly the features the user connected.
_CAPABILITIES = ["calendar"]


def _redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/google/oauth/callback"


@router.get("/accounts")
async def list_google_accounts(request: Request):
    """All connected Google accounts for the user (secrets stripped)."""
    owner = _require_user(request)
    return {"accounts": [google_account.safe_view(a)
                         for a in google_account.load_accounts(owner, provider="google")]}


@router.post("/accounts")
async def add_google_account(request: Request):
    """Create a Google account shell from the user's OAuth client creds.

    Returns the account id + an authorize URL to complete OAuth consent.
    """
    owner = _require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    client_id = (body.get("client_id") or "").strip()
    client_secret = (body.get("client_secret") or "").strip()
    if not (client_id and client_secret):
        raise HTTPException(400, "client_id and client_secret are required")
    acc = google_account.upsert_account(owner, {
        "provider": "google",
        "label": (body.get("label") or "Google").strip(),
        "client_id": client_id,
        "client_secret": encrypt(client_secret),
        "scopes": google_account.requested_scopes(_CAPABILITIES).split(),
    })
    return {"ok": True, "id": acc["id"],
            "authorize_url": f"/api/google/oauth/authorize/{acc['id']}"}


@router.delete("/accounts/{account_id}")
async def delete_google_account(account_id: str, request: Request):
    """Delete a Google account and the local calendars/events it owned."""
    from core.database import SessionLocal, CalendarCal, CalendarEvent
    owner = _require_user(request)
    if not google_account.get_account(owner, account_id):
        raise HTTPException(404, "Account not found")
    db = SessionLocal()
    try:
        cals = db.query(CalendarCal).filter(
            CalendarCal.owner == owner, CalendarCal.account_id == account_id).all()
        for cal in cals:
            db.query(CalendarEvent).filter(CalendarEvent.calendar_id == cal.id).delete()
            db.delete(cal)
        db.commit()
    finally:
        db.close()
    google_account.delete_account(owner, account_id)
    return {"ok": True}


@router.get("/oauth/authorize/{account_id}")
async def google_oauth_authorize(account_id: str, request: Request):
    """Redirect the user to Google's consent screen for this account."""
    owner = _require_user(request)
    acc = google_account.get_account(owner, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    params = {
        "client_id": acc["client_id"],
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": google_account.requested_scopes(_CAPABILITIES),
        "access_type": "offline",
        "prompt": "consent",
        "state": account_id,
    }
    return RedirectResponse(_AUTH_URL + "?" + urllib.parse.urlencode(params))


@router.get("/oauth/callback")
async def google_oauth_callback(code: str, state: str, request: Request):
    """Exchange the auth code for tokens, store the refresh token, sync."""
    owner = _require_user(request)
    acc = google_account.get_account(owner, state)
    if not acc:
        return HTMLResponse(_oauth_result_page("Error", "Account not found."), status_code=404)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN_URL, data={
                "code": code,
                "client_id": acc["client_id"],
                "client_secret": decrypt(acc.get("client_secret") or ""),
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            })
        if resp.status_code != 200:
            return HTMLResponse(_oauth_result_page(
                "Authorization Failed", html.escape(resp.text[:300])), status_code=400)
        tokens = resp.json()
        refresh = tokens.get("refresh_token")
        if not refresh:
            return HTMLResponse(_oauth_result_page(
                "Authorization Failed",
                "Google did not return a refresh token. Remove the app's access at "
                "myaccount.google.com/permissions and try again."), status_code=400)
        acc["refresh_token"] = encrypt(refresh)
        access_token = tokens.get("access_token")
        if access_token:
            from datetime import datetime as _dt, timedelta as _td
            acc["access_token"] = access_token
            acc["access_expiry"] = (_dt.utcnow() + _td(seconds=int(tokens.get("expires_in", 3600)))).isoformat()
            # Label the account with its address (best-effort).
            email = await google_account.fetch_user_email(access_token)
            if email:
                acc["email"] = email
                acc["label"] = f"Google ({email})"
        google_account.upsert_account(owner, acc)
    except Exception as e:
        logger.exception("Google OAuth exchange failed")
        return HTMLResponse(_oauth_result_page("Error", html.escape(str(e)[:300])), status_code=500)
    # Initial calendar sync (best-effort) so events show up immediately.
    try:
        from src.calendar_providers import get_provider
        await get_provider("google").sync(owner)
    except Exception:
        logger.warning("Initial Google calendar sync failed", exc_info=True)
    return HTMLResponse(_oauth_result_page(
        "Connected", "Google is connected. You can close this window and return to Odysseus.",
        success=True))


def _oauth_result_page(title: str, message: str, success: bool = False) -> str:
    """Minimal OAuth result page (mirrors routes/mcp_routes._oauth_result_page)."""
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    color = "#00661a" if success else "#e06c75"
    icon = "&#10003;" if success else "&#10007;"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{safe_title}</title>
<style>
  body {{ font-family: 'Fira Code', monospace; background: #0f0f0f; color: #e0e0e0;
    display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
  .card {{ background: #1a1a1a; border: 1px solid #333; border-radius: 12px;
    padding: 2rem; max-width: 420px; text-align: center; }}
  .icon {{ font-size: 3rem; color: {color}; margin-bottom: 1rem; }}
  h2 {{ color: {color}; margin-bottom: 0.5rem; font-size: 1.1rem; }}
  p {{ color: #aaa; font-size: 0.85rem; line-height: 1.5; }}
</style></head>
<body><div class="card">
  <div class="icon">{icon}</div>
  <h2>{safe_title}</h2>
  <p>{safe_message}</p>
</div></body></html>"""
