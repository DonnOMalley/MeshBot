from __future__ import annotations

from common.joke_api import JokeApi
from common.constants import _NODE_DB_DIR


class JokeManager:
    """Manages joke retrieval by delegating to :class:`~common.joke_api.JokeApi`.

    Acts as the command-layer facade for joke fetching, keeping the command
    handlers decoupled from the underlying API service implementation.
    """

    # region Protected Variables
    _joke_api: JokeApi
    # endregion Protected Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the manager with the directory used for cache persistence.

        Args:
            data_dir: Directory where the jokes cache file is stored.
            verbose: Whether to print debug messages.
        """
        self._joke_api = JokeApi(data_dir=data_dir, verbose=verbose)
    # endregion Constructor

    # region Public Functions
    def fetch_joke(self) -> str | None:
        """Fetches a joke from the API or falls back to the local cache.

        Returns:
            A joke string, or None if no joke is available from either source.
        """
        return self._joke_api.get_joke()
    # endregion Public Functions
