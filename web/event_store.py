from __future__ import annotations
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone

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
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


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

        start: datetime | None = EventStore.parse_time(fields.get("start", ""))
        end: datetime | None = EventStore.parse_time(fields.get("end", ""))
        if start is None:
            errors["start"] = "Start date/time is required."
        if end is None:
            errors["end"] = "End date/time is required."
        if start is not None and end is not None and end < start:
            errors["end"] = "End must be after the start."

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
        start: datetime | None = EventStore.parse_time(event.get("start", ""))
        end: datetime | None = EventStore.parse_time(event.get("end", ""))
        result: str = _EVENTS_STATUS_UPCOMING
        if end is not None and end <= moment:
            result = _EVENTS_STATUS_PAST
        elif start is not None and start <= moment:
            result = _EVENTS_STATUS_ACTIVE
        return result

    def list_events(self, now: datetime | None = None) -> list[dict]:
        """Returns every event (current and historical), archiving any that have ended.

        Each returned event carries a computed ``status`` field.
        """
        moment: datetime = now or datetime.now(timezone.utc)
        with self._lock:
            events: list[dict] = self._load_all(moment)
        return [dict(e, status=EventStore.status_of(e, moment)) for e in events]

    def get(self, event_id: str, now: datetime | None = None) -> dict | None:
        """Returns one event with its ``status``, or None if not found."""
        moment: datetime = now or datetime.now(timezone.utc)
        result: dict | None = None
        with self._lock:
            for event in self._load_all(moment):
                if event.get("id") == event_id:
                    result = dict(event, status=EventStore.status_of(event, moment))
                    break
        return result

    def create(self, clean: dict, has_image: bool = False) -> dict:
        """Adds a new event built from validated fields and returns it."""
        now_text: str = EventStore.format_time(datetime.now(timezone.utc))
        event: dict = dict(clean)
        event.update({
            "id": secrets.token_hex(8),
            "has_image": has_image,
            "photos": [],
            "created_at": now_text,
            "updated_at": now_text,
        })
        with self._lock:
            events: list[dict] = self._load_all()
            events.append(event)
            self._save_all(events)
        return dict(event, status=EventStore.status_of(event))

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
        return dict(result, status=EventStore.status_of(result)) if result is not None else None

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
        return events

    def _save_all(self, events: list[dict], now: datetime | None = None) -> None:
        """Splits events into current/history by end time and writes both files."""
        moment: datetime = now or datetime.now(timezone.utc)
        ordered: list[dict] = sorted(events, key=lambda e: e.get("start", ""))
        current: list[dict] = [e for e in ordered if EventStore.status_of(e, moment) != _EVENTS_STATUS_PAST]
        history: list[dict] = [e for e in ordered if EventStore.status_of(e, moment) == _EVENTS_STATUS_PAST]
        self._write_file(_EVENTS_FILE, current)
        self._write_file(_EVENTS_HISTORY_FILE, history)
    # endregion Protected Functions
