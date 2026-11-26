from __future__ import annotations
import json
import os
import re
import secrets
import shutil
import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken

from common.constants import (
    _EVENTS_COVER_NAME,
    _EVENTS_DECRYPTION_ERROR,
    _EVENTS_FIELD_MAX_LEN,
    _EVENTS_FILE,
    _EVENTS_HISTORY_FILE,
    _EVENTS_IMAGE_EXT,
    _EVENTS_IMAGES_SUBDIR,
    _EVENTS_LOCATION_ONLINE,
    _EVENTS_LOCATION_PHYSICAL,
    _EVENTS_NAME_MAX_LEN,
    _EVENTS_RECURRENCE_LABELS,
    _EVENTS_STATUS_ACTIVE,
    _EVENTS_STATUS_PAST,
    _EVENTS_STATUS_UPCOMING,
    _EVENTS_TEXT_MAX_LEN,
    _EVENTS_THUMB_SUFFIX,
    _EVENTS_UPLOADER_MAX_LEN,
)

_ID_PATTERN: re.Pattern = re.compile(r"^[a-f0-9]{8,32}$")
_IMAGE_NAME_PATTERN: re.Pattern = re.compile(r"^(cover|[a-f0-9]{8,32})(_thumb)?$")
_URL_PATTERN: re.Pattern = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)
_PHONE_PATTERN: re.Pattern = re.compile(r"^[0-9+()\-.\s]{7,25}$")
_DAY_PATTERN: re.Pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Repeat choices; each maps to an RFC 5545 RRULE.
_RECURRENCE_RULES: dict[str, str] = {
    "weekly": "FREQ=WEEKLY",
    "biweekly": "FREQ=WEEKLY;INTERVAL=2",
    "monthly": "FREQ=MONTHLY",
    "yearly": "FREQ=YEARLY",
}
# Safety cap when walking a series (about 40 years of weekly dates).
_MAX_OCCURRENCES: int = 2100


def _event_zone(event: dict) -> ZoneInfo | timezone:
    """The event's own time zone (where it repeats at the same wall-clock time)."""
    result: ZoneInfo | timezone = timezone.utc
    name: str = str(event.get("tz", "") or "")
    if name:
        try:
            result = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return result


def _shift_date(base: date, recurrence: str, n: int) -> date | None:
    """The n-th repeat date of *base*, or None when that month/year has no such day.

    Matches RRULE behaviour: the 31st skips shorter months and Feb 29 only
    repeats in leap years.
    """
    result: date | None = None
    if recurrence == "weekly":
        result = base + timedelta(weeks=n)
    elif recurrence == "biweekly":
        result = base + timedelta(weeks=2 * n)
    elif recurrence in ("monthly", "yearly"):
        months: int = n if recurrence == "monthly" else 12 * n
        index: int = base.year * 12 + (base.month - 1) + months
        try:
            result = date(index // 12, index % 12 + 1, base.day)
        except ValueError:
            result = None
    return result


def occurrences(event: dict):
    """Yields ``(start, end)`` UTC datetimes for every occurrence of *event*.

    A one-off event yields once. Repeats keep the same local wall-clock time
    in the event's time zone (so 7 PM stays 7 PM across daylight saving);
    all-day repeats keep their dates. Stops at ``repeat_until`` (inclusive
    date) or after a safety cap.
    """
    recurrence: str = str(event.get("recurrence", "") or "")
    start: datetime | None = EventStore.parse_time(event.get("start", ""))
    end: datetime | None = EventStore.parse_time(event.get("end", ""))
    if start is None or end is None:
        return
    if recurrence not in _RECURRENCE_RULES:
        yield start, end
        return
    zone = _event_zone(event)
    until: date | None = EventStore.parse_day(event.get("repeat_until", ""))
    first_day: date | None = EventStore.parse_day(event.get("start_day", "")) if event.get("all_day") else None
    last_day: date | None = EventStore.parse_day(event.get("end_day", "")) if event.get("all_day") else None
    local_start: datetime = start.astimezone(zone)
    base: date = first_day or local_start.date()
    span_days: int = ((last_day - first_day).days + 1) if first_day and last_day else 0
    duration: timedelta = end - start
    skipped: set[str] = set(event.get("skip_dates") or [])
    for n in range(_MAX_OCCURRENCES):
        day: date | None = _shift_date(base, recurrence, n)
        if day is None:
            continue
        if until is not None and day > until:
            break
        if day.isoformat() in skipped:
            # A single date removed from the series ("delete this date only").
            continue
        if span_days:
            occ_start = datetime.combine(day, time.min, tzinfo=zone)
            occ_end = datetime.combine(day + timedelta(days=span_days), time.min, tzinfo=zone)
        else:
            occ_start = datetime.combine(day, local_start.timetz().replace(tzinfo=None), tzinfo=zone)
            occ_end = occ_start + duration
        yield occ_start.astimezone(timezone.utc), occ_end.astimezone(timezone.utc)


def occurrence_at(event: dict, now: datetime) -> tuple[datetime, datetime, str] | None:
    """The occurrence that matters at *now*: the one happening, else the next one,
    else the last one. Returns ``(start, end, status)`` or None for no dates."""
    result: tuple[datetime, datetime, str] | None = None
    last: tuple[datetime, datetime] | None = None
    for occ_start, occ_end in occurrences(event):
        if occ_end > now:
            status: str = _EVENTS_STATUS_ACTIVE if occ_start <= now else _EVENTS_STATUS_UPCOMING
            result = (occ_start, occ_end, status)
            break
        last = (occ_start, occ_end)
    if result is None and last is not None:
        result = (last[0], last[1], _EVENTS_STATUS_PAST)
    return result


def is_series_date(event: dict, day: date) -> bool:
    """True when *day* (in the event's time zone) is one of the series' dates,
    ignoring any dates already skipped."""
    result: bool = False
    if str(event.get("recurrence", "") or "") in _RECURRENCE_RULES:
        zone = _event_zone(event)
        for occ_start, _ in occurrences(dict(event, skip_dates=[])):
            local_day: date = occ_start.astimezone(zone).date()
            if local_day == day:
                result = True
                break
            if local_day > day:
                break
    return result


_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _ics_escape(text: str) -> str:
    """Escapes text for an iCalendar TEXT value (RFC 5545 §3.3.11)."""
    return (
        str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    )


def _ics_fold(line: str) -> str:
    """Folds a content line so no physical line exceeds 75 octets (RFC 5545 §3.1)."""
    parts: list[str] = []
    current: str = ""
    size: int = 0
    for char in line:
        width: int = len(char.encode("utf-8"))
        limit: int = 75 if not parts else 74  # continuation lines start with a space
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
        current += char
        size += width
    parts.append(current)
    return "\r\n ".join(parts)


def build_ics(event: dict, page_url: str) -> str:
    """Builds a one-event iCalendar (.ics) file for *event*.

    Args:
        event: A stored event (times are UTC ``...Z`` strings).
        page_url: Link back to the event on the dashboard, added as URL and
                  at the end of the description.

    Returns:
        The calendar text with CRLF line endings.
    """
    def stamp(value: str) -> str:
        parsed: datetime | None = EventStore.parse_time(value)
        return parsed.strftime("%Y%m%dT%H%M%SZ") if parsed else ""

    first: date | None = EventStore.parse_day(event.get("start_day", "")) if event.get("all_day") else None
    last: date | None = EventStore.parse_day(event.get("end_day", "")) if event.get("all_day") else None
    dates: list[str]
    if first is not None and last is not None:
        # All-day: date values, end is the day after the last day (RFC 5545).
        dates = ["DTSTART;VALUE=DATE:" + first.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + (last + timedelta(days=1)).strftime("%Y%m%d")]
    else:
        dates = ["DTSTART:" + stamp(event.get("start", "")), "DTEND:" + stamp(event.get("end", ""))]
    recurrence: str = str(event.get("recurrence", "") or "")
    if recurrence in _RECURRENCE_RULES:
        rule: str = "RRULE:" + _RECURRENCE_RULES[recurrence]
        until: date | None = EventStore.parse_day(event.get("repeat_until", ""))
        zone = _event_zone(event)
        if first is None and event.get("tz") and zone is not timezone.utc:
            # Timed repeats are anchored in the event's time zone so they keep
            # their local time across daylight saving.
            start_dt: datetime | None = EventStore.parse_time(event.get("start", ""))
            end_dt: datetime | None = EventStore.parse_time(event.get("end", ""))
            if start_dt and end_dt:
                fmt: str = "%Y%m%dT%H%M%S"
                dates = [
                    f"DTSTART;TZID={event['tz']}:" + start_dt.astimezone(zone).strftime(fmt),
                    f"DTEND;TZID={event['tz']}:" + end_dt.astimezone(zone).strftime(fmt),
                ]
        if until is not None:
            if first is not None:
                rule += ";UNTIL=" + until.strftime("%Y%m%d")
            else:
                last_moment: datetime = datetime.combine(until, time(23, 59, 59), tzinfo=zone)
                rule += ";UNTIL=" + last_moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dates.append(rule)
        # Single dates removed from the series.
        start_dt = EventStore.parse_time(event.get("start", ""))
        for skip in sorted(event.get("skip_dates") or []):
            skip_day: date | None = EventStore.parse_day(skip)
            if skip_day is None or start_dt is None:
                continue
            if first is not None:
                dates.append("EXDATE;VALUE=DATE:" + skip_day.strftime("%Y%m%d"))
            elif event.get("tz") and zone is not timezone.utc:
                local_time: time = start_dt.astimezone(zone).time()
                dates.append(f"EXDATE;TZID={event['tz']}:" + datetime.combine(skip_day, local_time).strftime("%Y%m%dT%H%M%S"))
            else:
                dates.append("EXDATE:" + datetime.combine(skip_day, start_dt.time(), tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    location: dict = event.get("location") or {}
    where: str = location.get("link", "") if location.get("type") == _EVENTS_LOCATION_ONLINE else location.get("address", "")
    details: list[str] = []
    if event.get("description"):
        details.append(str(event["description"]))
    if location.get("type") == _EVENTS_LOCATION_ONLINE and location.get("link"):
        details.append("Join online: " + location["link"])
    if event.get("website"):
        details.append("Website: " + event["website"])
    details.append("Event page: " + page_url)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MeshBot//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event.get('id', '')}@meshbot-events",
        "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        *dates,
        "SUMMARY:" + _ics_escape(event.get("name", "")),
        "DESCRIPTION:" + _ics_escape("\n\n".join(details)),
    ]
    if where:
        lines.append("LOCATION:" + _ics_escape(where))
    lines += ["URL:" + page_url, "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


def upcoming_occurrences(events: list[dict], now: datetime, days: int = 30, limit: int = 8) -> list[dict]:
    """The next dates across *events*: those happening at *now* plus those
    starting within *days*. Repeats are expanded; happening-now first, then
    earliest first. Every happening-now date is returned; *limit* caps only
    the upcoming ones, so live events never crowd out what's next.

    All-day dates are given as ``first_day``/``last_day`` in the event's own
    time zone so they read the same for every viewer.
    """
    horizon: datetime = now + timedelta(days=days)
    found: list[dict] = []
    for event in events:
        zone = _event_zone(event)
        location: dict = event.get("location") or {}
        for occ_start, occ_end in occurrences(event):
            if occ_start >= horizon:
                break
            if occ_end <= now:
                continue
            item: dict = {
                "id": event.get("id", ""),
                "name": event.get("name", ""),
                "start": EventStore.format_time(occ_start),
                "end": EventStore.format_time(occ_end),
                "all_day": bool(event.get("all_day")),
                "status": _EVENTS_STATUS_ACTIVE if occ_start <= now else _EVENTS_STATUS_UPCOMING,
                "recurrence": event.get("recurrence", "") or "",
                "recurrence_label": _EVENTS_RECURRENCE_LABELS.get(str(event.get("recurrence", "") or ""), ""),
                "location": {"type": location.get("type", ""), "address": location.get("address", "")},
                "has_image": bool(event.get("has_image")),
                "updated_at": event.get("updated_at", ""),
            }
            if item["all_day"]:
                if not item["recurrence"] and event.get("start_day") and event.get("end_day"):
                    # One-off: its own calendar dates, exactly as entered.
                    item["first_day"], item["last_day"] = event["start_day"], event["end_day"]
                else:
                    item["first_day"] = occ_start.astimezone(zone).date().isoformat()
                    item["last_day"] = (occ_end - timedelta(microseconds=1)).astimezone(zone).date().isoformat()
            found.append(item)
    found.sort(key=lambda o: (o["status"] != _EVENTS_STATUS_ACTIVE, o["start"]))
    active: list[dict] = [o for o in found if o["status"] == _EVENTS_STATUS_ACTIVE]
    upcoming: list[dict] = [o for o in found if o["status"] != _EVENTS_STATUS_ACTIVE]
    return active + upcoming[:limit]


class EventStoreError(Exception):
    """Raised when the event files exist but cannot be read (e.g. wrong key).

    Writes are refused in that state so an unreadable file is never
    overwritten with an empty list.
    """


class EventStore:
    """Stores community events as two JSON files, encrypted like the chat logs.

    ``events.json`` holds events that have not ended yet; ``events_history.json``
    holds events whose end time has passed. Events are moved between the two
    automatically whenever the store is read or written, so an event that is
    edited to end in the future moves back to the current file.

    Images (the event's own picture and participant photos) are stored one file
    per image under ``images/<event_id>/``, encrypted with the same key. Each
    image has a small ``_thumb`` companion produced by the browser.

    Thread-safe: every public method holds a single lock.
    """

    # region Protected Variables
    _events_dir: str
    _images_dir: str
    _fernet: Fernet | None
    _lock: threading.RLock
    # endregion Protected Variables

    # region Constructor
    def __init__(self, events_dir: str, key: bytes | None = None) -> None:
        """Initialises the store.

        Args:
            events_dir: Directory holding the event files and image folders.
                        Created if it does not exist.
            key: Fernet key used to encrypt files at rest, or ``None`` to store
                 plain JSON and plain image bytes.
        """
        self._events_dir = events_dir
        self._images_dir = os.path.join(events_dir, _EVENTS_IMAGES_SUBDIR)
        self._fernet = Fernet(key) if key else None
        self._lock = threading.RLock()
        os.makedirs(self._images_dir, exist_ok=True)
    # endregion Constructor

    # region Public Functions
    @staticmethod
    def is_valid_id(value: str) -> bool:
        """Returns True if *value* looks like an event or photo ID."""
        return bool(_ID_PATTERN.match(value or ""))

    @staticmethod
    def is_valid_image_name(value: str) -> bool:
        """Returns True if *value* is a storable image name (cover / photo, optional _thumb)."""
        return bool(_IMAGE_NAME_PATTERN.match(value or ""))

    @staticmethod
    def detect_image_type(data: bytes) -> str | None:
        """Returns the MIME type of *data* from its magic bytes, or None if not an image we accept."""
        result: str | None = None
        for signature, mime in _IMAGE_SIGNATURES:
            if data.startswith(signature):
                result = mime
                break
        if result is None and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            result = "image/webp"
        return result

    @staticmethod
    def parse_time(value: str) -> datetime | None:
        """Parses an ISO-8601 timestamp into an aware UTC datetime.

        Naive values are treated as UTC. Returns None when unparseable.
        """
        result: datetime | None = None
        try:
            parsed: datetime = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            result = parsed.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
        return result

    @staticmethod
    def parse_day(value: str) -> date | None:
        """Parses a ``YYYY-MM-DD`` calendar date; None when missing or invalid."""
        result: date | None = None
        text: str = str(value or "").strip()
        if _DAY_PATTERN.match(text):
            try:
                result = date.fromisoformat(text)
            except ValueError:
                pass
        return result

    @staticmethod
    def format_time(value: datetime) -> str:
        """Formats an aware datetime as a UTC ISO-8601 string ending in ``Z``."""
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def validate(fields: dict) -> tuple[dict, dict]:
        """Validates and normalises the editable fields of an event.

        Args:
            fields: Raw values from the form (strings / booleans).

        Returns:
            ``(clean, errors)``. ``clean`` holds the normalised event fields;
            ``errors`` maps field names to messages and is empty when valid.
        """
        errors: dict = {}

        def text(name: str, max_len: int = _EVENTS_FIELD_MAX_LEN) -> str:
            value: str = str(fields.get(name, "") or "").strip()
            if len(value) > max_len:
                errors[name] = f"Must be {max_len} characters or fewer."
            return value

        def url(name: str, required: bool = False) -> str:
            value: str = text(name)
            if value and not _URL_PATTERN.match(value):
                errors[name] = "Must be a full link starting with http:// or https://"
            elif required and not value:
                errors[name] = "A link is required for an online event."
            return value

        name: str = text("name", _EVENTS_NAME_MAX_LEN)
        if not name:
            errors["name"] = "Name is required."
        description: str = text("description", _EVENTS_TEXT_MAX_LEN)

        all_day: bool = str(fields.get("all_day", "")).strip().lower() in ("1", "true", "on", "yes")
        start_day: str = ""
        end_day: str = ""
        start: datetime | None = EventStore.parse_time(fields.get("start", ""))
        end: datetime | None = EventStore.parse_time(fields.get("end", ""))
        if all_day:
            # All-day events keep their calendar dates (end_day = last day,
            # inclusive) so they show on the same days in every time zone.
            first: date | None = EventStore.parse_day(fields.get("start_day", ""))
            last: date | None = EventStore.parse_day(fields.get("end_day", ""))
            if first is None:
                errors["start"] = "Start date is required."
            if last is None:
                errors["end"] = "End date is required."
            if first is not None and last is not None:
                if last < first:
                    errors["end"] = "End date must be on or after the start date."
                start_day, end_day = first.isoformat(), last.isoformat()
                # Midnight-to-midnight; the browser sends its local midnights,
                # otherwise fall back to UTC midnights.
                if start is None:
                    start = datetime.combine(first, time.min, tzinfo=timezone.utc)
                if end is None:
                    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if start is None and "start" not in errors:
            errors["start"] = "Start date/time is required."
        if end is None and "end" not in errors:
            errors["end"] = "End date/time is required."
        if start is not None and end is not None and end < start and "end" not in errors:
            errors["end"] = "End must be after the start."

        recurrence: str = str(fields.get("recurrence", "") or "").strip().lower()
        if recurrence in ("", "none"):
            recurrence = ""
        elif recurrence not in _RECURRENCE_RULES:
            errors["recurrence"] = "Choose how often the event repeats."
            recurrence = ""
        repeat_until: str = ""
        if recurrence:
            until_text: str = str(fields.get("repeat_until", "") or "").strip()
            until_day: date | None = EventStore.parse_day(until_text)
            if until_text and until_day is None:
                errors["repeat_until"] = "Use a valid date."
            elif until_day is not None:
                first_date: date | None = EventStore.parse_day(start_day) if all_day else None
                if first_date is None and start is not None:
                    first_date = start.astimezone(_event_zone({"tz": fields.get("tz", "")})).date()
                if first_date is not None and until_day < first_date:
                    errors["repeat_until"] = "The repeat end date must be on or after the first date."
                repeat_until = until_day.isoformat()
        tz_name: str = str(fields.get("tz", "") or "").strip()[:64]
        if tz_name:
            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError):
                tz_name = ""

        location_type: str = str(fields.get("location_type", "") or "").strip().lower()
        address: str = ""
        link: str = ""
        if location_type == _EVENTS_LOCATION_PHYSICAL:
            address = text("location_address")
            if not address:
                errors["location_address"] = "An address is required for an in-person event."
        elif location_type == _EVENTS_LOCATION_ONLINE:
            link = url("location_link", required=True)
        else:
            errors["location_type"] = "Choose in person or online."

        website: str = url("website")
        contact_name: str = text("contact_name")
        contact_signal: str = text("contact_signal")
        contact_phone: str = text("contact_phone")
        if contact_phone and not _PHONE_PATTERN.match(contact_phone):
            errors["contact_phone"] = "Use digits and + ( ) - . only."
        phone_texts: bool = str(fields.get("contact_phone_texts", "")).strip().lower() in ("1", "true", "on", "yes")

        clean: dict = {
            "name": name,
            "description": description,
            "start": EventStore.format_time(start) if start else "",
            "end": EventStore.format_time(end) if end else "",
            "all_day": all_day,
            "start_day": start_day,
            "end_day": end_day,
            "recurrence": recurrence,
            "repeat_until": repeat_until,
            "tz": tz_name,
            "location": {"type": location_type, "address": address, "link": link},
            "website": website,
            "contact": {
                "name": contact_name,
                "signal": contact_signal,
                "phone": contact_phone,
                "phone_texts": phone_texts and bool(contact_phone),
            },
        }
        return clean, errors

    @staticmethod
    def status_of(event: dict, now: datetime | None = None) -> str:
        """Returns ``upcoming``, ``active`` or ``past`` for *event* at *now*."""
        moment: datetime = now or datetime.now(timezone.utc)
        found: tuple[datetime, datetime, str] | None = occurrence_at(event, moment)
        return found[2] if found is not None else _EVENTS_STATUS_UPCOMING

    @staticmethod
    def with_status(event: dict, now: datetime | None = None) -> dict:
        """A copy of *event* with ``status`` plus ``occurrence_start``/``occurrence_end``
        (the date happening now, else the next one, else the last one)."""
        moment: datetime = now or datetime.now(timezone.utc)
        found: tuple[datetime, datetime, str] | None = occurrence_at(event, moment)
        result: dict = dict(event, status=found[2] if found else _EVENTS_STATUS_UPCOMING)
        result["occurrence_start"] = EventStore.format_time(found[0]) if found else event.get("start", "")
        result["occurrence_end"] = EventStore.format_time(found[1]) if found else event.get("end", "")
        return result

    def list_events(self, now: datetime | None = None) -> list[dict]:
        """Returns every event (current and historical), archiving any that have ended.

        Each returned event carries a computed ``status`` field.
        """
        moment: datetime = now or datetime.now(timezone.utc)
        with self._lock:
            events: list[dict] = self._load_all(moment)
        return [EventStore.with_status(e, moment) for e in events]

    def get(self, event_id: str, now: datetime | None = None) -> dict | None:
        """Returns one event with its ``status``, or None if not found."""
        moment: datetime = now or datetime.now(timezone.utc)
        result: dict | None = None
        with self._lock:
            for event in self._load_all(moment):
                if event.get("id") == event_id:
                    result = EventStore.with_status(event, moment)
                    break
        return result

    @staticmethod
    def is_approved(event: dict) -> bool:
        """True when the event may be shown publicly.

        Events saved before reviews existed have no flag and count as approved.
        """
        return bool(event.get("approved", True))

    def create(self, clean: dict, has_image: bool = False, approved: bool = True) -> dict:
        """Adds a new event built from validated fields and returns it.

        Args:
            clean: Validated fields from :meth:`validate`.
            has_image: Whether a cover picture will be stored for it.
            approved: False for public submissions that wait for an organizer.
        """
        now_text: str = EventStore.format_time(datetime.now(timezone.utc))
        event: dict = dict(clean)
        event.update({
            "id": secrets.token_hex(8),
            "has_image": has_image,
            "approved": approved,
            "photos": [],
            "created_at": now_text,
            "updated_at": now_text,
        })
        with self._lock:
            events: list[dict] = self._load_all()
            events.append(event)
            self._save_all(events)
        return EventStore.with_status(event)

    def update(self, event_id: str, clean: dict, has_image: bool | None = None) -> dict | None:
        """Replaces the editable fields of an event. Photos and ID are kept.

        Args:
            event_id: The event to change.
            clean: Validated fields from :meth:`validate`.
            has_image: New value for ``has_image``, or None to leave it unchanged.

        Returns:
            The updated event, or None if it does not exist.
        """
        result: dict | None = None
        with self._lock:
            events: list[dict] = self._load_all()
            for event in events:
                if event.get("id") == event_id:
                    event.update(clean)
                    if has_image is not None:
                        event["has_image"] = has_image
                    event["updated_at"] = EventStore.format_time(datetime.now(timezone.utc))
                    result = event
                    break
            if result is not None:
                self._save_all(events)
        return EventStore.with_status(result) if result is not None else None

    def set_skip(self, event_id: str, day: date, skipped: bool = True) -> dict | None:
        """Removes (or restores) one date of a repeating event.

        Args:
            event_id: The repeating event.
            day: The date to skip or restore, in the event's own time zone.
            skipped: True to remove the date, False to bring it back.

        Returns:
            The updated event, or None if it does not exist.

        Raises:
            ValueError: The event doesn't repeat, or *day* isn't one of its dates.
        """
        result: dict | None = None
        with self._lock:
            events: list[dict] = self._load_all()
            for event in events:
                if event.get("id") == event_id:
                    if not event.get("recurrence"):
                        raise ValueError("Only repeating events have single dates to remove.")
                    if not is_series_date(event, day):
                        raise ValueError("That date isn't part of this event's schedule.")
                    dates: set[str] = set(event.get("skip_dates") or [])
                    if skipped:
                        dates.add(day.isoformat())
                    else:
                        dates.discard(day.isoformat())
                    event["skip_dates"] = sorted(dates)
                    event["updated_at"] = EventStore.format_time(datetime.now(timezone.utc))
                    result = event
                    break
            if result is not None:
                self._save_all(events)
        return EventStore.with_status(result) if result is not None else None

    def set_approved(self, event_id: str, approved: bool = True) -> dict | None:
        """Marks an event approved (public) or pending. Returns it, or None if missing."""
        result: dict | None = None
        with self._lock:
            events: list[dict] = self._load_all()
            for event in events:
                if event.get("id") == event_id:
                    event["approved"] = approved
                    event["updated_at"] = EventStore.format_time(datetime.now(timezone.utc))
                    result = event
                    break
            if result is not None:
                self._save_all(events)
        return EventStore.with_status(result) if result is not None else None

    def delete(self, event_id: str) -> bool:
        """Removes an event and all of its images. Returns False if it did not exist."""
        found: bool = False
        with self._lock:
            events: list[dict] = self._load_all()
            remaining: list[dict] = [e for e in events if e.get("id") != event_id]
            found = len(remaining) != len(events)
            if found:
                self._save_all(remaining)
                shutil.rmtree(self._event_image_dir(event_id), ignore_errors=True)
        return found

    def add_photo(self, event_id: str, uploader: str, full: bytes, thumb: bytes) -> dict | None:
        """Stores a participant photo and records it on the event.

        Returns the photo record, or None if the event does not exist.
        """
        result: dict | None = None
        with self._lock:
            events: list[dict] = self._load_all()
            for event in events:
                if event.get("id") == event_id:
                    photo_id: str = secrets.token_hex(8)
                    self.save_image(event_id, photo_id, full)
                    self.save_image(event_id, photo_id + _EVENTS_THUMB_SUFFIX, thumb)
                    result = {
                        "id": photo_id,
                        "uploader": uploader.strip()[:_EVENTS_UPLOADER_MAX_LEN],
                        "uploaded_at": EventStore.format_time(datetime.now(timezone.utc)),
                    }
                    event.setdefault("photos", []).append(result)
                    break
            if result is not None:
                self._save_all(events)
        return result

    def save_cover(self, event_id: str, full: bytes, thumb: bytes) -> None:
        """Stores (or replaces) the event's own picture and its thumbnail."""
        with self._lock:
            self.save_image(event_id, _EVENTS_COVER_NAME, full)
            self.save_image(event_id, _EVENTS_COVER_NAME + _EVENTS_THUMB_SUFFIX, thumb)

    def remove_cover(self, event_id: str) -> None:
        """Deletes the event's own picture and thumbnail, if present."""
        with self._lock:
            for name in (_EVENTS_COVER_NAME, _EVENTS_COVER_NAME + _EVENTS_THUMB_SUFFIX):
                path: str = self._image_path(event_id, name)
                if os.path.isfile(path):
                    os.remove(path)

    def save_image(self, event_id: str, name: str, data: bytes) -> None:
        """Writes one image file, encrypted when a key is configured."""
        if not (EventStore.is_valid_id(event_id) and EventStore.is_valid_image_name(name)):
            raise ValueError("Invalid image path")
        os.makedirs(self._event_image_dir(event_id), exist_ok=True)
        payload: bytes = self._fernet.encrypt(data) if self._fernet is not None else data
        self._write_atomic(self._image_path(event_id, name), payload)

    def read_image(self, event_id: str, name: str) -> bytes | None:
        """Returns the decrypted bytes of one image, or None if missing/unreadable."""
        result: bytes | None = None
        if EventStore.is_valid_id(event_id) and EventStore.is_valid_image_name(name):
            path: str = self._image_path(event_id, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    raw: bytes = f.read()
                if self._fernet is not None:
                    try:
                        result = self._fernet.decrypt(raw)
                    except InvalidToken:
                        result = raw if EventStore.detect_image_type(raw) else None
                else:
                    result = raw
        return result
    # endregion Public Functions

    # region Protected Functions
    def _event_image_dir(self, event_id: str) -> str:
        return os.path.join(self._images_dir, event_id)

    def _image_path(self, event_id: str, name: str) -> str:
        return os.path.join(self._event_image_dir(event_id), name + _EVENTS_IMAGE_EXT)

    @staticmethod
    def _write_atomic(path: str, payload: bytes) -> None:
        """Writes *payload* to a temp file and renames it over *path*."""
        tmp_path: str = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(payload)
        os.replace(tmp_path, path)

    def _read_file(self, filename: str) -> list[dict]:
        """Reads one event file. Missing file → empty list; unreadable → EventStoreError."""
        path: str = os.path.join(self._events_dir, filename)
        result: list[dict] = []
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                raw: str = f.read().strip()
            text: str | None = raw
            if raw and self._fernet is not None and not raw.startswith("["):
                try:
                    text = self._fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
                except InvalidToken:
                    text = None
            if text is None:
                raise EventStoreError(_EVENTS_DECRYPTION_ERROR.format(file=filename))
            if text:
                try:
                    data: object = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise EventStoreError(f"[EVENTS] {filename} is not valid JSON: {exc}") from exc
                if isinstance(data, list):
                    result = [e for e in data if isinstance(e, dict) and e.get("id")]
        return result

    def _write_file(self, filename: str, events: list[dict]) -> None:
        """Writes one event file, encrypted when a key is configured."""
        text: str = json.dumps(events, indent=1, ensure_ascii=False)
        if self._fernet is not None:
            text = self._fernet.encrypt(text.encode("utf-8")).decode("utf-8")
        os.makedirs(self._events_dir, exist_ok=True)
        self._write_atomic(os.path.join(self._events_dir, filename), text.encode("utf-8"))

    def _load_all(self, now: datetime | None = None) -> list[dict]:
        """Loads both files and re-files any event on the wrong side of its end time."""
        current: list[dict] = self._read_file(_EVENTS_FILE)
        history: list[dict] = self._read_file(_EVENTS_HISTORY_FILE)
        events: list[dict] = current + history
        moment: datetime = now or datetime.now(timezone.utc)
        misfiled: bool = any(EventStore.status_of(e, moment) == _EVENTS_STATUS_PAST for e in current) or any(
            EventStore.status_of(e, moment) != _EVENTS_STATUS_PAST for e in history
        )
        if misfiled:
            self._save_all(events, moment)
            events = [e for e in events if not EventStore._is_expired_submission(e, moment)]
        return events

    @staticmethod
    def _is_expired_submission(event: dict, now: datetime) -> bool:
        """True for a submission nobody approved before the event ended."""
        return not EventStore.is_approved(event) and EventStore.status_of(event, now) == _EVENTS_STATUS_PAST

    def _save_all(self, events: list[dict], now: datetime | None = None) -> None:
        """Splits events into current/history by end time and writes both files.

        Submissions that were never approved are deleted (with their images)
        once they end, instead of being kept in the history file.
        """
        moment: datetime = now or datetime.now(timezone.utc)
        for expired in [e for e in events if EventStore._is_expired_submission(e, moment)]:
            shutil.rmtree(self._event_image_dir(str(expired.get("id", ""))), ignore_errors=True)
        kept: list[dict] = [e for e in events if not EventStore._is_expired_submission(e, moment)]
        ordered: list[dict] = sorted(kept, key=lambda e: e.get("start", ""))
        current: list[dict] = [e for e in ordered if EventStore.status_of(e, moment) != _EVENTS_STATUS_PAST]
        history: list[dict] = [e for e in ordered if EventStore.status_of(e, moment) == _EVENTS_STATUS_PAST]
        self._write_file(_EVENTS_FILE, current)
        self._write_file(_EVENTS_HISTORY_FILE, history)
    # endregion Protected Functions
