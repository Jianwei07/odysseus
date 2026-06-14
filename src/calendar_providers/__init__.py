"""Calendar provider abstraction package.

Public surface:

    from src.calendar_providers import get_provider, available_providers
    from src.calendar_providers.base import CalendarProvider, CalendarMeta, SyncResult
"""

from .registry import get_provider, available_providers  # noqa: F401
from .base import CalendarProvider, CalendarMeta, SyncResult  # noqa: F401

__all__ = [
    "get_provider",
    "available_providers",
    "CalendarProvider",
    "CalendarMeta",
    "SyncResult",
]
