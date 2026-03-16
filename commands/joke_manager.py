from __future__ import annotations
import json
import os
import random
import requests

from common.constants import (
    _JOKE_API_KEY,
    _JOKE_API_TIMEOUT,
    _JOKE_API_URL,
    _JOKE_CACHE_FILE,
    _NODE_DB_DIR,
    _JOKE_API_FAILED_CONSOLE,
    _JOKE_NO_JOKES_CONSOLE,
)


class JokeManager:
    """Manages joke retrieval from the JokeAPI and persistence to a local cache.

    Fetches jokes from the remote API and stores each unique joke in a JSON file
    so that they can be served as a fallback if the API is unavailable.
    """

    # region Protected Variables
    _data_dir: str
    _verbose: bool = False
    # endregion Protected Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the manager with the directory used for cache persistence.

        Args:
            data_dir: Directory where the jokes cache file is stored.
            verbose: Whether to print debug messages.
        """
        self._data_dir = data_dir
        self._verbose = verbose
    # endregion Constructor

    # region Private Functions
    def _fetch_joke_from_api(self) -> str | None:
        """Requests a single safe joke from the JokeAPI.

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

    def _load_cached_jokes(self) -> list[str]:
        """Loads the list of previously cached jokes from disk.

        Returns:
            A list of joke strings. Returns an empty list if the file does not
            exist or cannot be read.
        """
        jokes: list[str] = []
        path: str = os.path.join(self._data_dir, _JOKE_CACHE_FILE)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data: object = json.load(f)
                if isinstance(data, list):
                    jokes = [str(j) for j in data if j]
            except Exception:
                pass
        return jokes

    def _save_joke_to_cache(self, joke: str) -> None:
        """Appends a joke to the local cache file if it is not already present.

        Creates the data directory and cache file if they do not yet exist.
        Silently ignores any write errors.

        Args:
            joke: The joke text to persist.
        """
        jokes: list[str] = self._load_cached_jokes()
        if joke not in jokes:
            jokes.append(joke)
            os.makedirs(self._data_dir, exist_ok=True)
            path: str = os.path.join(self._data_dir, _JOKE_CACHE_FILE)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(jokes, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def _pick_fallback_joke(self) -> str | None:
        """Returns a randomly selected joke from the local cache.

        Returns:
            A random joke string, or None if the cache is empty.
        """
        jokes: list[str] = self._load_cached_jokes()
        result: str | None = random.choice(jokes) if jokes else None
        return result
    # endregion Private Functions

    # region Public Functions
    def fetch_joke(self) -> str | None:
        """Fetches a joke from the API, persists it, and falls back to the cache if unavailable.

        Returns:
            A joke string, or None if no joke is available from either source.
        """
        joke: str | None = self._fetch_joke_from_api()
        if joke is not None:
            self._save_joke_to_cache(joke)
        else:
            if self._verbose:
                print(_JOKE_API_FAILED_CONSOLE)
            joke = self._pick_fallback_joke()
            if joke is None and self._verbose:
                print(_JOKE_NO_JOKES_CONSOLE)
        return joke
    # endregion Public Functions
