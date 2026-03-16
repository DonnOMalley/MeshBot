from __future__ import annotations


class LastCommandResult:
    """Encapsulates the outcome of computing the !last command response.

    Separates the error path from the success path so the caller can handle
    each case without re-parsing the parameters or re-querying the history.
    """

    # region Public Variables
    error_message: str | None
    messages: list[str]
    was_capped: bool
    original_count: int
    channel_name: str
    # endregion Public Variables

    # region Constructor
    def __init__(
        self,
        error_message: str | None = None,
        messages: list[str] | None = None,
        was_capped: bool = False,
        original_count: int = 0,
        channel_name: str = "",
    ) -> None:
        """Initialises the result with parsed command data.

        Args:
            error_message: The error message to send as DM, or None on success.
            messages: The chat history messages to send, oldest-first. Defaults to
                      an empty list when not supplied.
            was_capped: True if the requested count exceeded the per-command maximum.
            original_count: The originally requested count before capping was applied.
            channel_name: The channel name that was searched for history.
        """
        self.error_message = error_message
        self.messages = messages if messages is not None else []
        self.was_capped = was_capped
        self.original_count = original_count
        self.channel_name = channel_name
    # endregion Constructor
