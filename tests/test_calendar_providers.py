"""Calendar provider abstraction: registry resolution, Google event mapping,
and CalDAV delegation."""

import datetime as dt

import pytest

from src.calendar_providers import get_provider, available_providers
from src.calendar_providers.local import LocalProvider
from src.calendar_providers.caldav import CalDavProvider
from src.calendar_providers.google import (
    GoogleCalendarProvider,
    _parse_google_dt,
    _to_google_node,
    _stable_cal_id,
)


# ── registry ─────────────────────────────────────────────────────────────

def test_registry_resolves_known_sources():
    assert isinstance(get_provider("google"), GoogleCalendarProvider)
    assert isinstance(get_provider("caldav"), CalDavProvider)
    assert isinstance(get_provider("local"), LocalProvider)


def test_registry_unknown_and_none_fall_back_to_local():
    # Legacy/unknown sources must never be pushed to a remote.
    assert isinstance(get_provider("import"), LocalProvider)
    assert isinstance(get_provider(None), LocalProvider)


def test_available_providers_excludes_local_includes_google():
    ids = {p["id"] for p in available_providers()}
    assert "google" in ids and "caldav" in ids
    assert "local" not in ids  # implicit, not user-addable
    outlook = next(p for p in available_providers() if p["id"] == "outlook")
    assert outlook["enabled"] is False  # "coming soon"


# ── Google event mapping ───────────────────────────────────────────────────

def test_parse_google_timed_event_converts_to_utc_naive():
    d, _, all_day, is_utc = _parse_google_dt({"dateTime": "2026-06-14T15:00:00+09:00"})
    assert d == dt.datetime(2026, 6, 14, 6, 0)  # +09:00 -> 06:00 UTC
    assert all_day is False and is_utc is True


def test_parse_google_all_day_event():
    d, _, all_day, is_utc = _parse_google_dt({"date": "2026-06-14"})
    assert d == dt.datetime(2026, 6, 14, 0, 0)
    assert all_day is True and is_utc is False


def test_to_google_node_roundtrip_shapes():
    timed = _to_google_node(dt.datetime(2026, 6, 14, 6, 0), all_day=False, is_utc=True)
    assert timed == {"dateTime": "2026-06-14T06:00:00Z", "timeZone": "UTC"}
    allday = _to_google_node(dt.datetime(2026, 6, 14), all_day=True, is_utc=False)
    assert allday == {"date": "2026-06-14"}


def test_event_body_maps_rrule_and_drops_none_timezone():
    body = GoogleCalendarProvider()._event_body({
        "summary": "Standup", "description": "", "location": "",
        "dtstart": dt.datetime(2026, 6, 14, 9, 0), "dtend": dt.datetime(2026, 6, 14, 9, 30),
        "all_day": False, "is_utc": False, "rrule": "FREQ=WEEKLY",
    })
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY"]
    assert "timeZone" not in body["start"]  # None stripped for naive-local


def test_stable_cal_id_is_deterministic():
    a = _stable_cal_id("acc1", "primary")
    assert a == _stable_cal_id("acc1", "primary")
    assert a != _stable_cal_id("acc1", "other@group.calendar.google.com")


# ── CalDAV delegation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caldav_provider_delegates_to_writeback(monkeypatch):
    calls = {}

    async def fake_writeback(owner, source, cal_id, ev, *, delete=False):
        calls.update(owner=owner, source=source, cal_id=cal_id, ev=ev, delete=delete)
        return {"ok": True}

    import src.caldav_writeback as wb
    monkeypatch.setattr(wb, "writeback_event", fake_writeback)

    res = await CalDavProvider().push_delete("me", "cal1", "uid-9")
    assert res == {"ok": True}
    assert calls == {"owner": "me", "source": "caldav", "cal_id": "cal1",
                     "ev": {"uid": "uid-9"}, "delete": True}


@pytest.mark.asyncio
async def test_local_provider_push_is_noop():
    res = await LocalProvider().push_create("me", "cal1", {"uid": "x"})
    assert res.get("skipped")
