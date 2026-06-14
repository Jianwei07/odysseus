"""
Calendar provider abstraction.

Odysseus keeps the local ``calendar_events`` table (core/database.py) as the
canonical read store the UI, reminders, and agent all read from. A
``CalendarProvider`` is the *remote adapter* for one backend (CalDAV, Google,
…): it pulls remote events into that shared table (``sync``) and pushes local
edits back out (``push_create``/``push_update``/``push_delete``). Local
persistence stays in the route layer so every provider shares one transaction
path; providers only own the remote side, which is exactly the part that used
to be ``if cal.source == "caldav": ...`` branches scattered through
``routes/calendar_routes.py``.

Concrete providers live alongside this module; ``registry.get_provider`` maps a
calendar's ``source`` string to an instance.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field


@dataclass
class CalendarMeta:
    """A calendar exposed by a provider (maps to one ``CalendarCal`` row)."""
    id: str
    name: str
    color: str = "#5b8abf"
    source: str = "local"
    account_id: str | None = None


@dataclass
class SyncResult:
    """Outcome of a ``sync`` pull. Mirrors the dict shape the CalDAV sync and
    the ``/api/calendar/sync`` endpoint already return, so existing callers and
    the frontend keep working unchanged."""
    ok: bool = True
    synced: int = 0
    errors: list = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"ok": self.ok, "synced": self.synced, "errors": self.errors}
        if self.skipped is not None:
            d["skipped"] = self.skipped
        return d


class CalendarProvider(ABC):
    """Remote adapter for one calendar backend.

    Subclasses set the class-level metadata (used to drive the "+ Add Calendar"
    picker) and override only the operations their backend supports. Defaults
    are safe no-ops so a local/offline provider needs no overrides.

    Contract for the write-through hooks: they push an *already-persisted* local
    change to the remote and must be **best-effort** — never raise, return a
    dict (``{"ok": ...}`` / ``{"skipped": ...}``), and leave the local DB as the
    source of truth on failure. This matches ``caldav_writeback.writeback_event``.
    """

    # ── UI / registry metadata ──────────────────────────────────────────
    id: str = ""               # matches CalendarCal.source ("local"/"caldav"/"google")
    label: str = ""            # human label for the picker
    auth_type: str = "none"    # "none" | "password" | "oauth"
    enabled: bool = True       # False => shown disabled ("coming soon")
    addable: bool = True       # False => not offered in "+ Add Calendar" (e.g. local)

    # ── operations ──────────────────────────────────────────────────────
    async def sync(self, owner: str) -> dict:
        """Pull remote events into the local ``calendar_events`` table.
        Local-only providers have nothing to pull."""
        return {"ok": True, "synced": 0, "errors": [], "skipped": "local provider"}

    async def push_create(self, owner: str, calendar_id: str, ev: dict) -> dict:
        """Push a newly-created local event to the remote."""
        return {"skipped": "local provider"}

    async def push_update(self, owner: str, calendar_id: str, ev: dict) -> dict:
        """Push an updated local event to the remote."""
        return {"skipped": "local provider"}

    async def push_delete(self, owner: str, calendar_id: str, uid: str) -> dict:
        """Remove an event from the remote."""
        return {"skipped": "local provider"}

    def describe(self) -> dict:
        """Picker-facing metadata."""
        return {
            "id": self.id,
            "label": self.label,
            "auth_type": self.auth_type,
            "enabled": self.enabled,
        }
