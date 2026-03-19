from __future__ import annotations

import random

import requests

from common.api_service import ApiService
from common.constants import (
    _AFFIRM_API_FAILED_CONSOLE,
    _AFFIRM_API_KEY,
    _AFFIRM_API_TIMEOUT,
    _AFFIRM_API_URL,
    _AFFIRM_CACHE_FILE,
    _AFFIRM_NO_AFFIRMS_CONSOLE,
    _NODE_DB_DIR,
)


class AffirmationApi(ApiService):
    """Fetches and caches affirmations from the affirmations.dev API.

    Affirmations are retrieved on demand — no background polling is used.  Each
    unique affirmation fetched from the remote API is persisted to the local cache
    file so that it can be served as a fallback when the remote API is not reachable.
    """

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the affirmation API service with the given data directory.

        Args:
            data_dir: Directory where the affirmation cache file is stored.
            verbose: When True, prints diagnostic messages to the console.
        """
        super().__init__(
            cache_file=_AFFIRM_CACHE_FILE,
            data_dir=data_dir,
            poll_interval_seconds=None,
            verbose=verbose,
        )
    # endregion Constructor

    # region Protected Functions
    def _fetch_from_api(self) -> str | None:
        """Requests a single affirmation from the affirmations.dev API.

        Returns:
            The affirmation text string on success, or None if the request fails
            or the response does not contain a usable affirmation.
        """
        result: str | None = None
        try:
            response = requests.get(_AFFIRM_API_URL, timeout=_AFFIRM_API_TIMEOUT)
            if response.status_code == 200:
                data: dict = response.json()
                raw: object = data.get(_AFFIRM_API_KEY)
                if raw:
                    result = str(raw)
        except Exception:
            pass
        return result

    def _merge_into_cache(self, raw_data: object) -> None:
        """Appends a new affirmation to the local cache if not already present.

        Args:
            raw_data: The affirmation string returned by :meth:`_fetch_from_api`.
        """
        affirmation: str = str(raw_data)
        cached: object = self._load_raw_cache()
        affirmations: list[str] = [str(a) for a in cached if a] if isinstance(cached, list) else []
        if affirmation not in affirmations:
            affirmations.append(affirmation)
            self._save_raw_cache(affirmations)
    # endregion Protected Functions

    # region Public Functions
    def get_affirmation(self) -> str | None:
        """Returns an affirmation from the API, or falls back to a randomly selected cached one.

        Attempts to fetch a fresh affirmation and persist it to the local cache.
        When the API is unavailable an affirmation is chosen at random from the
        existing cache.

        Returns:
            An affirmation string, or None if neither the API nor the local cache has one.
        """
        affirmation: str | None = self._fetch_from_api()
        if affirmation is not None:
            self._merge_into_cache(affirmation)
        else:
            if self._verbose:
                print(_AFFIRM_API_FAILED_CONSOLE)
            cached: object = self._load_raw_cache()
            affirmations: list[str] = [str(a) for a in cached if a] if isinstance(cached, list) else []
            affirmation = random.choice(affirmations) if affirmations else None
            if affirmation is None and self._verbose:
                print(_AFFIRM_NO_AFFIRMS_CONSOLE)
        return affirmation
    # endregion Public Functions
