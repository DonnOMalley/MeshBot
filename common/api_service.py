from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod

from common.constants import (
    _API_SERVICE_POLL_ERROR,
    _NODE_DB_DIR,
)


class ApiService(ABC):
    """Abstract base class for remote web API services with optional background polling and offline caching.

    Subclasses implement :meth:`_fetch_from_api` to retrieve data from their
    respective remote endpoints and :meth:`_merge_into_cache` to persist
    deduplicated results to a local JSON file.

    When a ``poll_interval_seconds`` value is provided a daemon thread is started
    automatically on construction and calls :meth:`refresh` on every interval.
    Call :meth:`stop_polling` to signal the thread to exit cleanly on shutdown.
    """

    # region Protected Variables
    _data_dir: str
    _cache_file: str
    _verbose: bool
    _poll_interval_seconds: float | None
    _stop_event: threading.Event
    _poll_thread: threading.Thread | None
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        cache_file: str,
        data_dir: str = _NODE_DB_DIR,
        poll_interval_seconds: float | None = None,
        verbose: bool = False,
    ) -> None:
        """Initialises the service and optionally starts background polling.

        Args:
            cache_file: Filename (not path) of the JSON cache file within ``data_dir``.
            data_dir: Directory where the cache file is stored.
            poll_interval_seconds: Seconds between automatic API refreshes.
                                   When ``None`` no polling thread is started.
            verbose: When True, prints diagnostic messages to the console.
        """
        self._data_dir = data_dir
        self._cache_file = cache_file
        self._verbose = verbose
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._poll_thread = None
        os.makedirs(self._data_dir, exist_ok=True)
        if self._poll_interval_seconds is not None:
            self._start_polling()
    # endregion Constructor

    # region Protected Functions
    @abstractmethod
    def _fetch_from_api(self) -> object | None:
        """Fetches fresh data from the remote API endpoint.

        Returns:
            The parsed response data on success, or None if the request fails or
            the response does not contain usable data.
        """
        ...

    @abstractmethod
    def _merge_into_cache(self, raw_data: object) -> None:
        """Merges newly fetched data into the local cache file.

        Implementations are responsible for loading the existing cache, merging
        with deduplication where appropriate, and saving the result.

        Args:
            raw_data: The data returned by :meth:`_fetch_from_api`.
        """
        ...

    def _get_cache_path(self) -> str:
        """Returns the absolute path to the local cache file.

        Returns:
            The full file-system path as a string.
        """
        return os.path.join(self._data_dir, self._cache_file)

    def _load_raw_cache(self) -> object | None:
        """Reads and returns the parsed JSON content of the cache file.

        Returns:
            The deserialised JSON object, or None if the file does not exist or
            cannot be read or parsed.
        """
        path: str = self._get_cache_path()
        result: object | None = None
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    result = json.load(f)
            except Exception:
                pass
        return result

    def _save_raw_cache(self, data: object) -> None:
        """Serialises ``data`` to the cache file as indented JSON.

        Silently ignores any write errors.

        Args:
            data: The JSON-serialisable object to persist.
        """
        os.makedirs(self._data_dir, exist_ok=True)
        path: str = self._get_cache_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _start_polling(self) -> None:
        """Starts the background polling daemon thread if not already running."""
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._stop_event.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Background loop — calls :meth:`refresh` immediately on start, then after each interval."""
        stopped: bool = False
        while not stopped:
            try:
                self.refresh()
            except Exception as e:
                if self._verbose:
                    print(_API_SERVICE_POLL_ERROR.format(name=type(self).__name__, error=e))
            stopped = self._stop_event.wait(self._poll_interval_seconds)
    # endregion Protected Functions

    # region Public Functions
    def refresh(self) -> None:
        """Fetches fresh data from the API and merges it into the local cache.

        If the API call returns None the local cache is left unchanged.
        """
        raw: object | None = self._fetch_from_api()
        if raw is not None:
            self._merge_into_cache(raw)

    def stop_polling(self) -> None:
        """Signals the background polling thread to stop and waits for it to exit."""
        self._stop_event.set()
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
    # endregion Public Functions
