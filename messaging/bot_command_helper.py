from __future__ import annotations
from typing import Optional

from meshtastic.mesh_interface import MeshInterface

from common.chat_history import ChatHistory
from common.meshtastic_helper import MeshtasticHelper
from common.constants import (
    _CMD_LAST_MAX_MESSAGES,
    _HELLO_RESPONSE_NO_PARAMS,
    _HELLO_RESPONSE_WITH_PARAMS,
    _MSG_LAST_NOT_FOUND,
    _MSG_LAST_USAGE,
    _NODE_DB_DIR,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_TRACE_ROUTE,
    _PACKET_KEY_TRACE_ROUTE_BACK,
    _PACKET_KEY_TRACE_SNR_BACK,
    _PACKET_KEY_TRACE_SNR_TOWARDS,
    _PACKET_KEY_TRACEROUTE,
    _PING_RESPONSE,
    _TEST_RESPONSE,
    _TEST_RESPONSE_DIRECT,
    _TRACE_DIRECT,
    _TRACE_JOIN_SEP,
    _TRACE_LABEL_BOT,
    _TRACE_LABEL_YOU,
    _TRACE_RESULT_FORMAT,
    _TRACE_RESULT_NO_BACK_FORMAT,
    _TRACE_SNR_LINE_BACK,
    _TRACE_SNR_LINE_FWD,
    _TRACE_SNR_SCALE,
    _TRACE_SNR_VALUE_FORMAT,
    _TRACE_SNR_VALUE_SEP,
    _WEB_RESPONSE,
)
from messaging.last_command_result import LastCommandResult


class BotCommandHelper:
    """Provides the pure command logic for all built-in bot commands.

    Computes response messages and reads data for each command without
    performing any mesh transmissions. This separation allows the same
    logic to be reused by both the Meshtastic command handlers and the
    web dashboard without requiring a live interface for sending.
    """

    # region Protected Variables
    _iface: MeshInterface
    _data_dir: str
    _passphrase: Optional[str]
    _web_url: str
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        iface: MeshInterface,
        data_dir: str = _NODE_DB_DIR,
        passphrase: Optional[str] = None,
        web_url: str = "",
    ) -> None:
        """Initialises the helper with shared command context.

        Args:
            iface: The active MeshInterface used for node label resolution in
                   traceroute formatting. Not used for sending messages.
            data_dir: Directory containing chat history files.
            passphrase: Optional passphrase for decrypting encrypted history files.
            web_url: Full URL of the web dashboard, returned verbatim by the web command.
        """
        self._iface = iface
        self._data_dir = data_dir
        self._passphrase = passphrase
        self._web_url = web_url
    # endregion Constructor

    # region Private Functions
    def _node_label(self, node_num: int) -> str:
        """Resolves a short display label for a node given its numeric ID.

        Args:
            node_num: The integer node number to resolve.

        Returns:
            The node's short name if found in the interface table, otherwise
            the '!hex' node ID string.
        """
        node_id: str = MeshtasticHelper.get_node_id_from_node_num(node_num)
        label: str = node_id
        if self._iface.nodes:
            node_data: dict | None = self._iface.nodes.get(node_id)
            if node_data is not None:
                short_name: str = node_data.get("user", {}).get("shortName", "")
                if short_name:
                    label = short_name
        return label

    def _format_snr_lines(self, snr_towards: list[int], snr_back: list[int]) -> str:
        """Formats SNR readings from a traceroute into appended dB annotation lines.

        Args:
            snr_towards: Raw SNR values (int8 × 4) for each hop on the forward route.
            snr_back: Raw SNR values (int8 × 4) for each hop on the return route.

        Returns:
            A string with zero, one, or two SNR lines prefixed by a newline,
            or an empty string when no SNR data is present.
        """
        fwd_values: str = _TRACE_SNR_VALUE_SEP.join(
            _TRACE_SNR_VALUE_FORMAT.format(snr=v / _TRACE_SNR_SCALE) for v in snr_towards
        )
        back_values: str = _TRACE_SNR_VALUE_SEP.join(
            _TRACE_SNR_VALUE_FORMAT.format(snr=v / _TRACE_SNR_SCALE) for v in snr_back
        )
        suffix: str = ""
        if fwd_values:
            suffix = suffix + _TRACE_SNR_LINE_FWD.format(values=fwd_values)
        if back_values:
            suffix = suffix + _TRACE_SNR_LINE_BACK.format(values=back_values)
        return suffix
    # endregion Private Functions

    # region Public Functions
    def compute_hello(self, display_name: str, params: str) -> str:
        """Builds the hello command response message.

        Args:
            display_name: The resolved display name of the sender.
            params: Any extra text passed after the command name (may be empty).

        Returns:
            A greeting string that includes the params when non-empty, or a
            plain hello greeting otherwise.
        """
        result: str
        if params:
            result = _HELLO_RESPONSE_WITH_PARAMS.format(display_name=display_name, params=params)
        else:
            result = _HELLO_RESPONSE_NO_PARAMS.format(display_name=display_name)
        return result

    def compute_ping(self) -> str:
        """Returns the ping command response message.

        Returns:
            The fixed pong response string.
        """
        return _PING_RESPONSE

    def compute_test(self, hop_count: int) -> str:
        """Builds the test command response message.

        Args:
            hop_count: The number of hops the incoming packet travelled.

        Returns:
            A direct-connect message when hop_count is zero, otherwise a
            formatted hop count string.
        """
        result: str
        if hop_count == 0:
            result = _TEST_RESPONSE_DIRECT
        else:
            result = _TEST_RESPONSE.format(hop_count=hop_count)
        return result

    def compute_web(self) -> str:
        """Returns the web dashboard URL command response message.

        Returns:
            The formatted web dashboard URL string using the URL supplied at
            construction time.
        """
        return _WEB_RESPONSE.format(web_url=self._web_url)

    def compute_last(self, params: str) -> LastCommandResult:
        """Parses and resolves the !last command, reading the requested chat history.

        Validates the parameter string, caps the count to the per-command maximum,
        and reads the channel history from disk. The returned messages are ordered
        oldest-first, ready for sequential delivery.

        Args:
            params: The raw parameter string from the command (e.g. '5 OMalleyLand').

        Returns:
            A LastCommandResult containing either a single error_message (on invalid
            input or missing history) or the resolved list of messages.
        """
        parts: list[str] = params.strip().split(None, 1)
        valid: bool = len(parts) == 2 and parts[0].isdigit() and int(parts[0]) > 0
        result: LastCommandResult
        if not valid:
            result = LastCommandResult(error_message=_MSG_LAST_USAGE)
        else:
            original_count: int = int(parts[0])
            channel_name: str = parts[1]
            was_capped: bool = original_count > _CMD_LAST_MAX_MESSAGES
            count: int = _CMD_LAST_MAX_MESSAGES if was_capped else original_count
            messages: list[str] = ChatHistory.read_last(channel_name, count, self._data_dir, self._passphrase)
            if not messages:
                result = LastCommandResult(error_message=_MSG_LAST_NOT_FOUND.format(channel=channel_name))
            else:
                result = LastCommandResult(
                    messages=list(reversed(messages)),
                    was_capped=was_capped,
                    original_count=original_count,
                    channel_name=channel_name,
                )
        return result

    def format_traceroute(self, packet: dict) -> str:
        """Formats a raw traceroute response packet into a human-readable string.

        Args:
            packet: The raw Meshtastic traceroute response packet.

        Returns:
            A formatted string describing the full route, SNR readings, and relay count.
        """
        traceroute: dict = packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_TRACEROUTE, {})
        route: list[int] = traceroute.get(_PACKET_KEY_TRACE_ROUTE, [])
        route_back: list[int] = traceroute.get(_PACKET_KEY_TRACE_ROUTE_BACK, [])
        snr_towards: list[int] = traceroute.get(_PACKET_KEY_TRACE_SNR_TOWARDS, [])
        snr_back_values: list[int] = traceroute.get(_PACKET_KEY_TRACE_SNR_BACK, [])
        result: str
        if not route and not route_back:
            result = _TRACE_DIRECT
        else:
            route_labels: list[str] = [_TRACE_LABEL_BOT] + [self._node_label(n) for n in route] + [_TRACE_LABEL_YOU]
            route_str: str = _TRACE_JOIN_SEP.join(route_labels)
            relay_count: int = len(route)
            if route_back:
                back_labels: list[str] = [_TRACE_LABEL_YOU] + [self._node_label(n) for n in route_back] + [_TRACE_LABEL_BOT]
                back_str: str = _TRACE_JOIN_SEP.join(back_labels)
                result = _TRACE_RESULT_FORMAT.format(route=route_str, back=back_str, relays=relay_count)
            else:
                result = _TRACE_RESULT_NO_BACK_FORMAT.format(route=route_str, relays=relay_count)
        result = result + self._format_snr_lines(snr_towards, snr_back_values)
        return result
    # endregion Public Functions
