from __future__ import annotations

import html
import json
import os
import re
import threading
from datetime import datetime

import requests

from common.constants import (
    _NODE_DB_DIR,
    _TODAY_IN_HISTORY_API_FAILED_CONSOLE,
    _TODAY_IN_HISTORY_API_TIMEOUT,
    _TODAY_IN_HISTORY_API_URL,
    _TODAY_IN_HISTORY_FILE_FORMAT,
    _TODAY_IN_HISTORY_KEY_DATA,
    _TODAY_IN_HISTORY_KEY_EVENTS,
    _TODAY_IN_HISTORY_KEY_LINKS,
    _TODAY_IN_HISTORY_KEY_TEXT,
    _TODAY_IN_HISTORY_KEY_WIKIPEDIA,
    _TODAY_IN_HISTORY_KEY_YEAR,
    _TODAY_IN_HISTORY_POLL_INTERVAL_SECONDS,
    _TODAY_IN_HISTORY_SAVED_CONSOLE,
    _TODAY_IN_HISTORY_SUBDIR,
)

# Compiled regex patterns — implementation internals used only in this module
_RE_FOOTNOTE: re.Pattern[str] = re.compile(r"\[\d+\]")
_RE_YEAR: re.Pattern[str] = re.compile(r"^(\d+)")
_RE_YEAR_PREFIX: re.Pattern[str] = re.compile(r"^\d+\s*[\u2013\u2014\-]+\s*")


class TodayInHistoryApi:
    """Fetches and caches 'Today in History' events from the ZenQuotes Today API.

    On construction a daemon thread is started immediately.  The thread calls
    the API once for today's date if the corresponding cache file does not yet
    exist, then waits one hour before checking again.  This means only one API
    request is ever made per calendar day, regardless of how many times the
    service restarts.

    Cache files are stored under ``<data_dir>/TodayInHistory/MM-DD.json`` and
    contain a JSON array of event dicts.  Call :meth:`get_events` to read the
    cached events for today.
    """

    # region Private Variables
    _data_dir: str
    _verbose: bool
    _stop_event: threading.Event
    _poll_thread: threading.Thread
    # endregion Private Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the service and starts the background fetch thread.

        Args:
            data_dir: Root data directory.  Cache files are written under
                      ``<data_dir>/TodayInHistory/``.
            verbose: When True, prints diagnostic messages to the console.
        """
        self._data_dir = data_dir
        self._verbose = verbose
        self._stop_event = threading.Event()
        cache_dir: str = os.path.join(data_dir, _TODAY_IN_HISTORY_SUBDIR)
        os.makedirs(cache_dir, exist_ok=True)
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
    # endregion Constructor

    # region Private Functions
    def _cache_path_for(self, month: int, day: int) -> str:
        """Returns the absolute path to the cache file for the given month and day.

        Args:
            month: The month number (1–12).
            day: The day of the month (1–31).

        Returns:
            The full file-system path as a string.
        """
        filename: str = _TODAY_IN_HISTORY_FILE_FORMAT.format(month=month, day=day)
        return os.path.join(self._data_dir, _TODAY_IN_HISTORY_SUBDIR, filename)

    def _normalize_event(self, raw: dict) -> dict | None:
        """Converts a raw API event dict into a normalised form with year, text, and wikipedia keys.

        Decodes HTML entities, strips footnote references, extracts the year
        from the start of the text, and picks the first article Wikipedia URL
        from the event's ``links`` map.

        Args:
            raw: A raw event dict from the API response.

        Returns:
            A normalised dict with ``year``, ``text``, and ``wikipedia`` keys,
            or None if the event contains no usable text.
        """
        result: dict | None = None
        raw_text: str = raw.get(_TODAY_IN_HISTORY_KEY_TEXT, "")
        if raw_text:
            decoded: str = html.unescape(raw_text)
            clean: str = _RE_FOOTNOTE.sub("", decoded).strip()
            year_match: re.Match[str] | None = _RE_YEAR.match(clean)
            year: str = year_match.group(1) if year_match else ""
            body_text: str = _RE_YEAR_PREFIX.sub("", clean)
            links: object = raw.get(_TODAY_IN_HISTORY_KEY_LINKS, {})
            wikipedia: str = ""
            if isinstance(links, dict):
                article_link: object = links.get("1") or links.get("0")
                if isinstance(article_link, dict):
                    wikipedia = str(article_link.get("1", ""))
            result = {
                _TODAY_IN_HISTORY_KEY_YEAR: year,
                _TODAY_IN_HISTORY_KEY_TEXT: body_text,
                _TODAY_IN_HISTORY_KEY_WIKIPEDIA: wikipedia,
            }
        return result

    def _fetch_events(self, month: int, day: int) -> list[dict] | None:
        """Requests today's events from the ZenQuotes Today in History API.

        The API returns ``{ data: { Events: [...] } }`` where each event contains
        ``text``, ``html``, and ``links`` fields.  Each raw event is normalised
        via :meth:`_normalize_event` before being stored.

        Args:
            month: The month number (1–12).
            day: The day of the month (1–31).

        Returns:
            A list of normalised event dicts on success, or None if the request
            fails or the response does not contain usable data.
        """
        result: list[dict] | None = None
        try:
            url: str = _TODAY_IN_HISTORY_API_URL.format(month=month, day=day)
            response = requests.get(url, timeout=_TODAY_IN_HISTORY_API_TIMEOUT)
            if response.status_code == 200:
                body: object = response.json()
                if isinstance(body, dict):
                    data_section: object = body.get(_TODAY_IN_HISTORY_KEY_DATA)
                    if isinstance(data_section, dict):
                        raw_events: object = data_section.get(_TODAY_IN_HISTORY_KEY_EVENTS)
                        if isinstance(raw_events, list):
                            candidate: list[dict] = []
                            for raw in raw_events:
                                if isinstance(raw, dict):
                                    normalized: dict | None = self._normalize_event(raw)
                                    if normalized:
                                        candidate.append(normalized)
                            if candidate:
                                result = candidate
        except Exception:
            pass
        return result

    def _ensure_today(self) -> None:
        """Fetches and caches today's events if the cache file does not already exist."""
        now: datetime = datetime.now()
        path: str = self._cache_path_for(now.month, now.day)
        if not os.path.isfile(path):
            events: list[dict] | None = self._fetch_events(now.month, now.day)
            if events is not None:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(events, f, indent=2, ensure_ascii=False)
                    if self._verbose:
                        print(_TODAY_IN_HISTORY_SAVED_CONSOLE.format(
                            count=len(events), month=now.month, day=now.day
                        ))
                except Exception:
                    pass
            elif self._verbose:
                print(_TODAY_IN_HISTORY_API_FAILED_CONSOLE.format(month=now.month, day=now.day))

    def _poll_loop(self) -> None:
        """Background loop — checks for today's cache immediately then every hour."""
        stopped: bool = False
        while not stopped:
            try:
                self._ensure_today()
            except Exception:
                pass
            stopped = self._stop_event.wait(_TODAY_IN_HISTORY_POLL_INTERVAL_SECONDS)
    # endregion Private Functions

    # region Public Functions
    def get_events(self) -> list[dict]:
        """Returns today's cached 'Today in History' events.

        Reads the cache file for the current calendar date.  If the file does
        not exist (e.g. the background thread has not yet had a chance to fetch),
        an empty list is returned.

        Returns:
            A list of event dicts, each typically containing ``year`` and ``text``
            keys.  Returns an empty list if no data is available.
        """
        now: datetime = datetime.now()
        path: str = self._cache_path_for(now.month, now.day)
        result: list[dict] = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data: object = json.load(f)
                if isinstance(data, list):
                    result = [e for e in data if isinstance(e, dict)]
            except Exception:
                pass
        return result

    def stop_polling(self) -> None:
        """Signals the background polling thread to stop and waits for it to exit."""
        self._stop_event.set()
        if self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
    # endregion Public Functions
