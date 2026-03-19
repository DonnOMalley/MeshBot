from __future__ import annotations

from common.affirmation_api import AffirmationApi
from common.constants import _NODE_DB_DIR


class AffirmationManager:
    """Manages affirmation retrieval by delegating to :class:`~common.affirmation_api.AffirmationApi`.

    Acts as the command-layer facade for affirmation fetching, keeping the command
    handlers decoupled from the underlying API service implementation.
    """

    # region Protected Variables
    _affirmation_api: AffirmationApi
    # endregion Protected Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR, verbose: bool = False) -> None:
        """Initialises the manager with the directory used for cache persistence.

        Args:
            data_dir: Directory where the affirmations cache file is stored.
            verbose: Whether to print debug messages.
        """
        self._affirmation_api = AffirmationApi(data_dir=data_dir, verbose=verbose)
    # endregion Constructor

    # region Public Functions
    def fetch_affirmation(self) -> str | None:
        """Fetches an affirmation from the API or falls back to the local cache.

        Returns:
            An affirmation string, or None if no affirmation is available from either source.
        """
        return self._affirmation_api.get_affirmation()
    # endregion Public Functions
