from __future__ import annotations

import random

import requests

from common.api_service import ApiService
from common.constants import (
    _JOKE_API_FAILED_CONSOLE,
    _JOKE_API_KEY,
    _JOKE_API_TIMEOUT,
    _JOKE_API_URL,
    _JOKE_CACHE_FILE,
    _JOKE_NO_JOKES_CONSOLE,
    _NODE_DB_DIR,
)


class JokeApi(ApiService):
    """Fetches and caches jokes from JokeAPI v2.

    Jokes are retrieved on demand — no background polling is used.  Each unique
    joke fetched from the remote API is persisted to the local cache file so that
    it can be served as a fallback when the remote API is not reachable.
    """

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the joke API service with the given data directory.

        Args:
            data_dir: Directory where the joke cache file is stored.
            verbose: When True, prints diagnostic messages to the console.
        """
        super().__init__(
            cache_file=_JOKE_CACHE_FILE,
            data_dir=data_dir,
            poll_interval_seconds=None,
            verbose=verbose,
        )
    # endregion Constructor

    # region Protected Functions
    def _fetch_from_api(self) -> str | None:
        """Requests a single safe joke from the JokeAPI v2.

        Returns:
            The joke text string on success, or None if the request fails or the
            response does not contain a usable joke.
        """
        result: str | None = None
        try:
            response = requests.get(_JOKE_API_URL, timeout=_JOKE_API_TIMEOUT)
            if response.status_code == 200:
                data: dict = response.json()
                raw: object = data.get(_JOKE_API_KEY)
                if raw:
                    result = str(raw)
        except Exception:
            pass
        return result

    def _merge_into_cache(self, raw_data: object) -> None:
        """Appends a new joke to the local cache if not already present.

        Args:
            raw_data: The joke string returned by :meth:`_fetch_from_api`.
        """
        joke: str = str(raw_data)
        cached: object = self._load_raw_cache()
        jokes: list[str] = [str(j) for j in cached if j] if isinstance(cached, list) else []
        if joke not in jokes:
            jokes.append(joke)
            self._save_raw_cache(jokes)
    # endregion Protected Functions

    # region Public Functions
    def get_joke(self) -> str | None:
        """Returns a joke from the API, or falls back to a randomly selected cached joke.

        Attempts to fetch a fresh joke and persist it to the local cache.  When
        the API is unavailable a joke is chosen at random from the existing cache.

        Returns:
            A joke string, or None if neither the API nor the local cache has one.
        """
        joke: str | None = self._fetch_from_api()
        if joke is not None:
            self._merge_into_cache(joke)
        else:
            if self._verbose:
                print(_JOKE_API_FAILED_CONSOLE)
            cached: object = self._load_raw_cache()
            jokes: list[str] = [str(j) for j in cached if j] if isinstance(cached, list) else []
            joke = random.choice(jokes) if jokes else None
            if joke is None and self._verbose:
                print(_JOKE_NO_JOKES_CONSOLE)
        return joke
    # endregion Public Functions
