from __future__ import annotations

import os
import random

import requests

from common.api_service import ApiService
from common.constants import (
    _NODE_DB_DIR,
    _RANGE_TEST_SECONDS_PER_MINUTE,
    _ZEN_QUOTES_API_FAILED_CONSOLE,
    _ZEN_QUOTES_API_TIMEOUT,
    _ZEN_QUOTES_API_URL,
    _ZEN_QUOTES_CACHE_FILE,
    _ZEN_QUOTES_DEFAULT_POLL_INTERVAL_MINUTES,
    _ZEN_QUOTES_KEY_AUTHOR,
    _ZEN_QUOTES_KEY_HTML,
    _ZEN_QUOTES_KEY_QUOTE,
    _ZEN_QUOTES_MERGED_CONSOLE,
    _ZEN_QUOTES_NO_QUOTES_CONSOLE,
)


class ZenQuote:
    """Holds a single Zen Quote with its text, author, and HTML representation."""

    # region Public Variables
    quote: str
    author: str
    html: str
    # endregion Public Variables

    # region Constructor
    def __init__(self, quote: str, author: str, html: str) -> None:
        """Initialises the record with the quote text, author, and HTML.

        Args:
            quote: The plain-text content of the quote.
            author: The name of the person attributed to the quote.
            html: The pre-formatted HTML representation combining quote and author.
        """
        self.quote = quote
        self.author = author
        self.html = html
    # endregion Constructor

    # region Public Functions
    def to_dict(self) -> dict:
        """Serialises this record to a JSON-compatible dictionary.

        Returns:
            A dict with ``q``, ``a``, and ``h`` keys matching the ZenQuotes API schema.
        """
        return {
            _ZEN_QUOTES_KEY_QUOTE: self.quote,
            _ZEN_QUOTES_KEY_AUTHOR: self.author,
            _ZEN_QUOTES_KEY_HTML: self.html,
        }

    @staticmethod
    def from_dict(data: dict) -> ZenQuote:
        """Deserialises a ZenQuote from a dictionary.

        Args:
            data: A dict with ``q``, ``a``, and ``h`` keys.

        Returns:
            A populated :class:`ZenQuote` instance.
        """
        return ZenQuote(
            quote=data.get(_ZEN_QUOTES_KEY_QUOTE, ""),
            author=data.get(_ZEN_QUOTES_KEY_AUTHOR, ""),
            html=data.get(_ZEN_QUOTES_KEY_HTML, ""),
        )
    # endregion Public Functions


class ZenQuotesApi(ApiService):
    """Polls the ZenQuotes API for inspirational quotes and maintains a deduplicated local cache.

    Quotes are fetched at the configured interval (default 1 hour) by a background
    daemon thread.  The cache file (``zen_quotes.json``) accumulates unique entries
    deduplicated by their HTML field.  Call :meth:`get_zen_quote` to retrieve a
    randomly selected quote from the cache.
    """

    # region Constructor
    def __init__(
        self,
        data_dir: str = _NODE_DB_DIR,
        poll_interval_minutes: int = _ZEN_QUOTES_DEFAULT_POLL_INTERVAL_MINUTES,
        verbose: bool = False,
    ) -> None:
        """Initialises the Zen Quotes service and starts background polling.

        Args:
            data_dir: Directory where the quotes cache file is stored.
            poll_interval_minutes: Minutes between automatic polls of the ZenQuotes API.
                                   Defaults to 60.
            verbose: When True, prints diagnostic messages to the console.
        """
        super().__init__(
            cache_file=_ZEN_QUOTES_CACHE_FILE,
            data_dir=data_dir,
            poll_interval_seconds=float(poll_interval_minutes * 60),
            verbose=verbose,
        )
    # endregion Constructor

    # region Protected Functions
    def _fetch_from_api(self) -> list[dict] | None:
        """Requests the quotes list from the ZenQuotes API.

        Returns:
            A list of dicts each containing ``q``, ``a``, and ``h`` keys on success,
            or None if the request fails or the response is not a usable list.
        """
        result: list[dict] | None = None
        try:
            response = requests.get(_ZEN_QUOTES_API_URL, timeout=_ZEN_QUOTES_API_TIMEOUT)
            if response.status_code == 200:
                data: object = response.json()
                if isinstance(data, list) and data:
                    result = [
                        item for item in data
                        if isinstance(item, dict) and item.get(_ZEN_QUOTES_KEY_HTML)
                    ]
        except Exception:
            pass
        if result is None and self._verbose:
            print(_ZEN_QUOTES_API_FAILED_CONSOLE)
        return result

    def _merge_into_cache(self, raw_data: object) -> None:
        """Merges newly fetched quotes into the cache, deduplicating by HTML content.

        Args:
            raw_data: A list of quote dicts as returned by :meth:`_fetch_from_api`.
        """
        if not isinstance(raw_data, list):
            return
        cached: object = self._load_raw_cache()
        existing: list[dict] = cached if isinstance(cached, list) else []
        existing_htmls: set[str] = {
            entry.get(_ZEN_QUOTES_KEY_HTML, "")
            for entry in existing
            if isinstance(entry, dict)
        }
        new_quotes: list[dict] = [
            q for q in raw_data
            if isinstance(q, dict) and q.get(_ZEN_QUOTES_KEY_HTML, "") not in existing_htmls
        ]
        if new_quotes:
            merged: list[dict] = existing + new_quotes
            self._save_raw_cache(merged)
            if self._verbose:
                print(_ZEN_QUOTES_MERGED_CONSOLE.format(new=len(new_quotes), total=len(merged)))
    # endregion Protected Functions

    # region Public Functions
    def get_zen_quote(self) -> ZenQuote | None:
        """Returns a randomly selected quote from the local cache.

        When the cache file does not yet exist, one on-demand API fetch is attempted
        to seed it before the random selection.

        Returns:
            A :class:`ZenQuote` with the quote text, author, and HTML, or None if
            no quotes are available from either source.
        """
        path: str = self._get_cache_path()
        if not os.path.isfile(path):
            raw: list[dict] | None = self._fetch_from_api()
            if raw is not None:
                self._merge_into_cache(raw)
        cached: object = self._load_raw_cache()
        quotes: list[dict] = [q for q in cached if isinstance(q, dict)] if isinstance(cached, list) else []
        result: ZenQuote | None = ZenQuote.from_dict(random.choice(quotes)) if quotes else None
        if result is None and self._verbose:
            print(_ZEN_QUOTES_NO_QUOTES_CONSOLE)
        return result
    # endregion Public Functions
