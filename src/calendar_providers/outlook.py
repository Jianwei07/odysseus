"""Outlook / Microsoft 365 calendar provider — placeholder.

Registered but disabled so the "+ Add Calendar" picker can advertise it as
"coming soon". Implementing it later means filling in the Microsoft Graph
calls here (OAuth + /me/events) — the interface and wiring already exist.
"""

from __future__ import annotations

from .base import CalendarProvider


class OutlookProvider(CalendarProvider):
    id = "outlook"
    label = "Outlook"
    auth_type = "oauth"
    enabled = False  # picker shows it disabled; not yet implemented
