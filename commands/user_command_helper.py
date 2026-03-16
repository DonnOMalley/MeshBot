from __future__ import annotations

from commands.joke_manager import JokeManager
from common.constants import (
    _JOKE_ERROR_RESPONSE,
    _NODE_DB_DIR,
    _USER_HELLO_RESPONSE,
)


class UserCommandHelper:
    """Provides the pure command logic for all user-defined bot commands.

    Computes response messages and fetches data for each user command without
    performing any mesh transmissions. This separation allows the same logic
    to be reused by both the Meshtastic command handlers and the web dashboard.
    """

    # region Protected Variables
    _joke_manager: JokeManager
    # endregion Protected Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR) -> None:
        """Initialises the helper with shared command context.

        Args:
            data_dir: Directory used to persist the joke cache file. Defaults to
                      the shared data directory.
        """
        self._joke_manager = JokeManager(data_dir=data_dir)
    # endregion Constructor

    # region Public Functions
    def compute_hello(self, display_name: str, hop_count: int) -> str:
        """Builds the user hello command response message with hop count.

        Args:
            display_name: The resolved display name of the sender.
            hop_count: The number of hops the incoming packet travelled.

        Returns:
            A greeting string that includes the display name and hop count.
        """
        return _USER_HELLO_RESPONSE.format(display_name=display_name, hop_count=hop_count)

    def compute_joke(self) -> str:
        """Fetches a joke and returns the message text.

        Attempts to retrieve a fresh joke from the JokeAPI, falling back to the
        local cache when the API is unavailable.

        Returns:
            A joke string from the API or cache, or an error message when neither
            source has a joke available.
        """
        joke: str | None = self._joke_manager.fetch_joke()
        result: str = joke if joke is not None else _JOKE_ERROR_RESPONSE
        return result
    # endregion Public Functions
