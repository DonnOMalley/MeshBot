from __future__ import annotations

import random

from commands.affirmation_manager import AffirmationManager
from commands.joke_manager import JokeManager
from common.constants import (
    _AFFIRM_ERROR_RESPONSE,
    _JOKE_ERROR_RESPONSE,
    _MESH_MAX_MESSAGE_CHARS,
    _NODE_DB_DIR,
    _TIH_ERROR_RESPONSE,
    _TIH_LINK_NOT_A_REPLY,
    _TIH_LINK_NOT_FOUND,
    _TIH_LINK_NO_LINK,
    _TIH_MESSAGE_ELLIPSIS,
    _TIH_MESSAGE_TEMPLATE,
    _USER_HELLO_RESPONSE,
)
from common.today_in_history_api import TodayInHistoryApi


class UserCommandHelper:
    """Provides the pure command logic for all user-defined bot commands.

    Computes response messages and fetches data for each user command without
    performing any mesh transmissions. This separation allows the same logic
    to be reused by both the Meshtastic command handlers and the web dashboard.
    """

    # region Protected Variables
    _joke_manager: JokeManager
    _affirmation_manager: AffirmationManager
    _tih_api: TodayInHistoryApi
    _tih_sent: dict[int, dict]
    # endregion Protected Variables

    # region Constructor
    def __init__(self, data_dir: str = _NODE_DB_DIR) -> None:
        """Initialises the helper with shared command context.

        Args:
            data_dir: Directory used to persist the joke and affirmation cache files.
                      Defaults to the shared data directory.
        """
        self._joke_manager = JokeManager(data_dir=data_dir)
        self._affirmation_manager = AffirmationManager(data_dir=data_dir)
        self._tih_api = TodayInHistoryApi(data_dir=data_dir)
        self._tih_sent = {}
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

    def compute_affirmation(self) -> str:
        """Fetches an affirmation and returns the message text.

        Attempts to retrieve a fresh affirmation from the affirmations.dev API,
        falling back to the local cache when the API is unavailable.

        Returns:
            An affirmation string from the API or cache, or an error message when
            neither source has an affirmation available.
        """
        affirmation: str | None = self._affirmation_manager.fetch_affirmation()
        result: str = affirmation if affirmation is not None else _AFFIRM_ERROR_RESPONSE
        return result

    def compute_tih(self) -> tuple[str, dict]:
        """Picks a random Today in History event and returns it as a mesh-safe message.

        Reads from the daily cache file populated by :class:`TodayInHistoryApi`.
        The returned string is formatted as ``YEAR: text`` and truncated to fit
        within the Meshtastic maximum message length if necessary.

        Returns:
            A two-tuple of (formatted_message, event_dict). The event_dict
            contains ``year``, ``text``, and ``wikipedia`` keys, or is empty
            when no events are available.
        """
        events: list[dict] = self._tih_api.get_events()
        result: tuple[str, dict]
        if not events:
            result = (_TIH_ERROR_RESPONSE, {})
        else:
            event: dict = random.choice(events)
            year: str = str(event.get("year", ""))
            text: str = str(event.get("text", ""))
            message: str = _TIH_MESSAGE_TEMPLATE.format(year=year, text=text)
            if len(message) > _MESH_MAX_MESSAGE_CHARS:
                truncated: str = message[: _MESH_MAX_MESSAGE_CHARS - 1] + _TIH_MESSAGE_ELLIPSIS
                result = (truncated, event)
            else:
                result = (message, event)
        return result

    def register_tih_sent(self, msg_id: int, event: dict) -> None:
        """Records the mapping from a sent message ID to its TIH event.

        Enables :meth:`compute_tih_link` to resolve a reply's ``replyId`` back
        to the original event and return its Wikipedia URL.

        Args:
            msg_id: The Meshtastic packet ID of the sent TIH message.
            event: The event dict with ``year``, ``text``, and ``wikipedia`` keys.
        """
        self._tih_sent[msg_id] = event

    def compute_tih_link(self, reply_id: int | None) -> str:
        """Returns the Wikipedia URL for the TIH event identified by a reply message ID.

        Looks up the supplied ``reply_id`` in the cache of previously sent TIH
        messages. The cache is populated by :meth:`register_tih_sent` each time
        the bot sends a TIH response over the mesh.

        Args:
            reply_id: The ``replyId`` from the incoming packet, or ``None`` if the
                      message is not a reply.

        Returns:
            The Wikipedia URL string for the matched event, or an explanatory
            error message when the reply ID is absent, unrecognised, or the
            event has no link.
        """
        result: str
        if reply_id is None:
            result = _TIH_LINK_NOT_A_REPLY
        else:
            event: dict | None = self._tih_sent.get(reply_id)
            if event is None:
                result = _TIH_LINK_NOT_FOUND
            else:
                wikipedia: str = str(event.get("wikipedia", ""))
                result = wikipedia if wikipedia else _TIH_LINK_NO_LINK
        return result
    # endregion Public Functions
