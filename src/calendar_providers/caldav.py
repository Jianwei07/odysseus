"""CalDAV calendar provider.

A thin OOP wrapper over the existing function-based CalDAV implementation
(``src/caldav_sync.py`` + ``src/caldav_writeback.py``) — no logic is duplicated
or rewritten, it is just exposed through the ``CalendarProvider`` interface so
routes can call it uniformly via ``registry.get_provider``.
"""

from __future__ import annotations

from .base import CalendarProvider


class CalDavProvider(CalendarProvider):
    id = "caldav"
    label = "CalDAV"
    auth_type = "password"
    enabled = True

    async def sync(self, owner: str) -> dict:
        from src.caldav_sync import sync_caldav
        return await sync_caldav(owner)

    async def push_create(self, owner: str, calendar_id: str, ev: dict) -> dict:
        from src.caldav_writeback import writeback_event
        return await writeback_event(owner, "caldav", calendar_id, ev)

    async def push_update(self, owner: str, calendar_id: str, ev: dict) -> dict:
        # CalDAV write-back is an upsert (PUT by UID), so update == create.
        from src.caldav_writeback import writeback_event
        return await writeback_event(owner, "caldav", calendar_id, ev)

    async def push_delete(self, owner: str, calendar_id: str, uid: str) -> dict:
        from src.caldav_writeback import writeback_event
        return await writeback_event(owner, "caldav", calendar_id, {"uid": uid}, delete=True)
