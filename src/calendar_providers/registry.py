"""Calendar provider registry.

Single place that knows every backend. ``get_provider`` maps a calendar's
``source`` to an instance (used by routes + the agent tool); the
``CalendarCal.source`` value an unknown/legacy row carries falls back to the
local no-op provider so it is never pushed to a remote. ``available_providers``
drives the "+ Add Calendar" picker.

Add a new backend = drop a ``CalendarProvider`` subclass module and list it in
``_PROVIDER_CLASSES`` here. Nothing else needs to change.
"""

from __future__ import annotations

from .base import CalendarProvider
from .local import LocalProvider
from .caldav import CalDavProvider
from .google import GoogleCalendarProvider
from .outlook import OutlookProvider

# Order is the order the picker shows them.
_PROVIDER_CLASSES: list[type[CalendarProvider]] = [
    LocalProvider,
    CalDavProvider,
    GoogleCalendarProvider,
    OutlookProvider,
]

# Instantiated singletons keyed by provider id.
_PROVIDERS: dict[str, CalendarProvider] = {cls.id: cls() for cls in _PROVIDER_CLASSES}

_FALLBACK = _PROVIDERS["local"]


def get_provider(source: str | None) -> CalendarProvider:
    """Resolve a ``CalendarCal.source`` to its provider, defaulting to local."""
    return _PROVIDERS.get((source or "local"), _FALLBACK)


def available_providers() -> list[dict]:
    """Picker metadata for backends a user can add (excludes implicit local)."""
    return [p.describe() for p in _PROVIDERS.values() if p.addable]


def all_providers() -> list[CalendarProvider]:
    """Every registered provider instance (for fan-out operations like sync)."""
    return list(_PROVIDERS.values())
