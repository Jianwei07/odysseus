"""Google Calendar provider — native Calendar REST API (v3).

Talks to ``https://www.googleapis.com/calendar/v3`` over httpx using an OAuth
bearer token refreshed from the account's stored refresh token. ``sync`` pulls
each calendar in the account's calendarList into the shared ``calendar_events``
table (origin ``"google"``), mirroring the upsert/prune shape of
``src/caldav_sync._sync_blocking``; the write-through hooks POST/PUT/DELETE the
matching Google event.

The remote Google calendar id for each local ``CalendarCal`` is kept in the
account's ``calendars`` map (``{local_id: {gcal_id, name}}``) so we never have
to encode it into the primary key.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx

from .base import CalendarProvider
from . import accounts as account_store

logger = logging.getLogger(__name__)

_API = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/calendar"
_LOOKBACK_DAYS = 365
_LOOKAHEAD_DAYS = 365


def _stable_cal_id(account_id: str, gcal_id: str) -> str:
    """Deterministic local CalendarCal.id for a remote Google calendar."""
    h = hashlib.sha1(f"google:{account_id}:{gcal_id}".encode()).hexdigest()[:16]
    return f"gcal_{h}"


def _parse_google_dt(node: dict) -> tuple[datetime, datetime | None, bool, bool]:
    """Parse a Google start/end node → (dt_naive_utc, None, all_day, is_utc).

    All-day events use ``{"date": "YYYY-MM-DD"}``; timed events use
    ``{"dateTime": ISO8601, "timeZone": ...}``. We store naive-UTC like the rest
    of the calendar code, flagging ``is_utc`` for timed events.
    """
    if node.get("date"):
        d = datetime.fromisoformat(node["date"])
        return d.replace(hour=0, minute=0, second=0, microsecond=0), None, True, False
    raw = node["dateTime"]
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt, None, False, True
    return dt, None, False, False


def _to_google_node(dt: datetime, all_day: bool, is_utc: bool) -> dict:
    if all_day:
        return {"date": dt.date().isoformat()}
    # Stored naive; treat as UTC when flagged (matches serializer's Z-suffix).
    return {"dateTime": dt.replace(microsecond=0).isoformat() + ("Z" if is_utc else ""),
            "timeZone": "UTC" if is_utc else None}


class GoogleCalendarProvider(CalendarProvider):
    id = "google"
    label = "Google Calendar"
    auth_type = "oauth"
    enabled = True

    # ── auth ────────────────────────────────────────────────────────────
    async def _access_token(self, owner: str, account: dict) -> str:
        """Return a valid access token, refreshing + caching as needed."""
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
        account_store.upsert_account(owner, account)
        return account["access_token"]

    def _account_for_calendar(self, owner: str, calendar_id: str) -> tuple[dict | None, str | None]:
        """Resolve (account, remote_gcal_id) for a local calendar id."""
        for acc in account_store.load_accounts(owner, provider="google"):
            cals = acc.get("calendars") or {}
            entry = cals.get(calendar_id)
            if entry:
                return acc, entry.get("gcal_id")
        return None, None

    # ── sync (pull) ───────────────────────────────────────────────────────
    async def sync(self, owner: str) -> dict:
        result = {"calendars": 0, "events": 0, "deleted": 0, "errors": []}
        accounts = account_store.load_accounts(owner, provider="google")
        for account in accounts:
            if not account.get("refresh_token"):
                continue
            try:
                await self._sync_account(owner, account, result)
            except Exception as e:  # never let one account break the others
                logger.exception("Google sync failed for account %s", account.get("id"))
                result["errors"].append(str(e)[:200])
        return result

    async def _sync_account(self, owner: str, account: dict, result: dict) -> None:
        token = await self._access_token(owner, account)
        headers = {"Authorization": f"Bearer {token}"}
        time_min = (datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)).isoformat() + "Z"
        time_max = (datetime.utcnow() + timedelta(days=_LOOKAHEAD_DAYS)).isoformat() + "Z"

        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            cal_list = (await client.get(f"{_API}/users/me/calendarList")).json()
            cal_map = dict(account.get("calendars") or {})
            for item in cal_list.get("items", []):
                gcal_id = item["id"]
                local_id = _stable_cal_id(account["id"], gcal_id)
                name = item.get("summaryOverride") or item.get("summary") or "Google"
                color = item.get("backgroundColor") or "#5b8abf"
                cal_map[local_id] = {"gcal_id": gcal_id, "name": name}
                self._upsert_calendar(owner, local_id, name, color, account["id"])
                result["calendars"] += 1
                events = await self._fetch_events(client, gcal_id, time_min, time_max)
                ev_result = self._upsert_events(owner, local_id, events)
                result["events"] += ev_result["events"]
                result["deleted"] += ev_result["deleted"]
            account["calendars"] = cal_map
            account_store.upsert_account(owner, account)

    async def _fetch_events(self, client, gcal_id, time_min, time_max) -> list[dict]:
        items, page_token = [], None
        while True:
            params = {"timeMin": time_min, "timeMax": time_max,
                      "singleEvents": "false", "maxResults": 2500,
                      "showDeleted": "false"}
            if page_token:
                params["pageToken"] = page_token
            import urllib.parse as _u
            url = f"{_API}/calendars/{_u.quote(gcal_id)}/events"
            data = (await client.get(url, params=params)).json()
            items.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def _upsert_calendar(self, owner, local_id, name, color, account_id) -> None:
        from core.database import CalendarCal, SessionLocal
        db = SessionLocal()
        try:
            cal = db.query(CalendarCal).filter(
                CalendarCal.id == local_id, CalendarCal.owner == owner).first()
            if not cal:
                db.add(CalendarCal(id=local_id, owner=owner, name=name,
                                   color=color, source="google", account_id=account_id))
            else:
                if cal.name != name:
                    cal.name = name
            db.commit()
        finally:
            db.close()

    def _upsert_events(self, owner, local_id, g_events) -> dict:
        from core.database import CalendarEvent, SessionLocal
        out = {"events": 0, "deleted": 0}
        db = SessionLocal()
        try:
            seen = set()
            for g in g_events:
                if g.get("status") == "cancelled" or not g.get("start"):
                    continue
                uid = g["id"]
                seen.add(uid)
                dtstart, _, all_day, is_utc = _parse_google_dt(g["start"])
                if g.get("end"):
                    dtend, _, _, _ = _parse_google_dt(g["end"])
                elif all_day:
                    dtend = dtstart + timedelta(days=1)
                else:
                    dtend = dtstart + timedelta(hours=1)
                rrule = ""
                for r in (g.get("recurrence") or []):
                    if r.startswith("RRULE:"):
                        rrule = r[len("RRULE:"):]
                        break
                row = db.query(CalendarEvent).filter(CalendarEvent.uid == uid).first()
                fields = dict(
                    calendar_id=local_id,
                    summary=g.get("summary", ""),
                    description=g.get("description", ""),
                    location=g.get("location", ""),
                    dtstart=dtstart, dtend=dtend, all_day=all_day,
                    is_utc=is_utc, rrule=rrule, origin="google",
                )
                if row:
                    for k, v in fields.items():
                        setattr(row, k, v)
                else:
                    db.add(CalendarEvent(uid=uid, **fields))
                out["events"] += 1
            db.commit()

            # Prune google-origin rows that vanished upstream (window-scoped via
            # seen set; only origin=="google" so local edits are never deleted).
            if seen:
                stale = db.query(CalendarEvent).filter(
                    CalendarEvent.calendar_id == local_id,
                    CalendarEvent.origin == "google",
                    ~CalendarEvent.uid.in_(seen),
                ).all()
                for ev in stale:
                    db.delete(ev)
                out["deleted"] += len(stale)
                db.commit()
        finally:
            db.close()
        return out

    # ── write-through (push) ────────────────────────────────────────────
    def _event_body(self, ev: dict) -> dict:
        body = {
            "summary": ev.get("summary", ""),
            "description": ev.get("description", ""),
            "location": ev.get("location", ""),
            "start": _to_google_node(ev["dtstart"], ev.get("all_day", False), ev.get("is_utc", False)),
            "end": _to_google_node(ev["dtend"], ev.get("all_day", False), ev.get("is_utc", False)),
        }
        # Drop None timeZone keys Google rejects.
        for side in ("start", "end"):
            body[side] = {k: v for k, v in body[side].items() if v is not None}
        if ev.get("rrule"):
            body["recurrence"] = [f"RRULE:{ev['rrule']}"]
        return body

    async def _request(self, owner, calendar_id, method, ev_uid=None, json=None) -> dict:
        account, gcal_id = self._account_for_calendar(owner, calendar_id)
        if not account or not gcal_id:
            return {"skipped": "no google account for calendar"}
        try:
            token = await self._access_token(owner, account)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        import urllib.parse as _u
        base = f"{_API}/calendars/{_u.quote(gcal_id)}/events"
        url = base if ev_uid is None else f"{base}/{_u.quote(ev_uid)}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                resp = await client.request(method, url, json=json)
            if resp.status_code >= 400:
                logger.warning("Google %s %s -> %s: %s", method, url, resp.status_code, resp.text[:200])
                return {"ok": False, "error": resp.text[:200]}
            return {"ok": True}
        except Exception as e:
            logger.exception("Google write-through failed")
            return {"ok": False, "error": str(e)[:200]}

    async def push_create(self, owner: str, calendar_id: str, ev: dict) -> dict:
        body = self._event_body(ev)
        # Reuse our uuid hex as the Google event id (valid base32hex) so later
        # update/delete address the same event.
        uid = (ev.get("uid") or "").replace("-", "").lower()
        if uid and all(c in "0123456789abcdefghijklmnopqrstuv" for c in uid) and 5 <= len(uid) <= 1024:
            body["id"] = uid
        return await self._request(owner, calendar_id, "POST", json=body)

    async def push_update(self, owner: str, calendar_id: str, ev: dict) -> dict:
        return await self._request(owner, calendar_id, "PUT", ev_uid=ev.get("uid"), json=self._event_body(ev))

    async def push_delete(self, owner: str, calendar_id: str, uid: str) -> dict:
        return await self._request(owner, calendar_id, "DELETE", ev_uid=uid)
