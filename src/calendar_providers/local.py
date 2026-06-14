"""Local (table-only) calendar provider.

Events created against a local calendar live solely in the ``calendar_events``
table — there is no remote to sync to or push to, so every operation is the
inherited no-op. Also used as the fallback for any unknown/legacy ``source``
(e.g. ``import``), which by design must never be pushed to a remote.
"""

from __future__ import annotations

from .base import CalendarProvider


class LocalProvider(CalendarProvider):
    id = "local"
    label = "Local"
    auth_type = "none"
    enabled = True
    addable = False  # the default calendar is implicit; not offered in the picker
