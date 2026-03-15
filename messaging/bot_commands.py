from __future__ import annotations
import threading
import time
from pubsub import pub
from typing import Optional
from common.constants import (
    CMD_HELLO,
    CMD_PING,
    CMD_TEST,
    CMD_LAST,
    CMD_TRACE,
    CMD_WEB,
    _HELLO_RESPONSE_WITH_PARAMS,
    _HELLO_RESPONSE_NO_PARAMS,
    _HELLO_CONSOLE_RESPONSE,
    _PING_RESPONSE,
    _PING_CONSOLE_RESPONSE,
    _TEST_RESPONSE,
    _TEST_RESPONSE_DIRECT,
    _TEST_CONSOLE_RESPONSE,
    _MSG_LAST_USAGE,
    _MSG_LAST_NOT_FOUND,
    _MSG_LAST_DM_INCOMING,
    _MSG_LAST_CAPPED,
    _MSG_LAST_CONSOLE,
    _NODE_DB_DIR,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_TRACEROUTE,
    _PACKET_KEY_TRACE_ROUTE,
    _PACKET_KEY_TRACE_ROUTE_BACK,
    _PACKET_KEY_TRACE_SNR_TOWARDS,
    _PACKET_KEY_TRACE_SNR_BACK,
    _CMD_SEND_DELAY,
    _CMD_LAST_MAX_MESSAGES,
    _EVENT_TRACEROUTE,
    _TRACE_RESPONSE_WAITING,
    _TRACE_CONSOLE_SENT,
    _TRACE_CONSOLE_RECEIVED,
    _TRACE_DIRECT,
    _TRACE_RESULT_FORMAT,
    _TRACE_RESULT_NO_BACK_FORMAT,
    _TRACE_HOP_LIMIT,
    _TRACE_LABEL_BOT,
    _TRACE_LABEL_YOU,
    _TRACE_JOIN_SEP,
    _TRACE_DURATION_SUFFIX,
    _TRACE_SNR_SCALE,
    _TRACE_SNR_VALUE_FORMAT,
    _TRACE_SNR_VALUE_SEP,
    _TRACE_SNR_LINE_FWD,
    _TRACE_SNR_LINE_BACK,
    _CHAT_HISTORY_BOT_SENDER,
    _WEB_RESPONSE,
    _WEB_CONSOLE_RESPONSE,
)
from common.chat_history import ChatHistory
from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface


class BotCommands:
    """Implements the OOTB command handlers that send replies over the Meshtastic network."""

    # region Protected Variables
    _iface: MeshInterface
    _config: NodeConfiguration
    _channel: channel_pb2.Channel
    _verbose: bool
    _passphrase: Optional[str]
    _data_dir: str
    _chat_history: Optional[ChatHistory]
    _pending_traces: dict[str, tuple[bool, float]]
    _web_url: str
    # endregion Protected Variables

    # region Constructor
    def __init__(self, iface: MeshInterface, config: NodeConfiguration, channel: channel_pb2.Channel, verbose: bool = False, passphrase: Optional[str] = None, data_dir: str = _NODE_DB_DIR, chat_history: Optional[ChatHistory] = None, web_url: str = "") -> None:
        """Initialises the command handler with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection used to send reply messages.
            config: The NodeConfiguration object containing local node information.
            channel: The channel on which replies will be broadcast.
            verbose: When True, prints a console confirmation for each command handled.
            passphrase: Optional passphrase used to decrypt chat history files when
                        serving the ``!last`` command. Must match the value used at
                        write time. Defaults to ``None`` (plain-text files).
            data_dir: Directory containing the chat history log files.
            chat_history: When provided, bot replies sent to the channel are appended
                          to the log under the ``[BOT]`` sender label.
            web_url: Full URL of the web dashboard (e.g. ``http://localhost:7331``).
                     Returned verbatim by the ``!web`` command. Defaults to empty string.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._verbose = verbose
        self._passphrase = passphrase
        self._data_dir = data_dir
        self._chat_history = chat_history
        self._pending_traces = {}
        self._web_url = web_url
        pub.subscribe(self._on_traceroute_response, _EVENT_TRACEROUTE)
    # endregion Constructor

    # region Protected Functions
    def _cmd_hello(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'hello' command with a personalised greeting.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name.
            packet: The full raw Meshtastic packet dictionary.
        """
        display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
        if params:
            message: str = _HELLO_RESPONSE_WITH_PARAMS.format(display_name=display_name, params=params)
        else:
            message = _HELLO_RESPONSE_NO_PARAMS.format(display_name=display_name)

        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=message,
            packet=packet,
            consoleMsg=_HELLO_CONSOLE_RESPONSE.format(display_name=display_name, params=params) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )

    def _cmd_ping(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'ping' command with a pong reply on the channel.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=_PING_RESPONSE,
            packet=packet,
            consoleMsg=_PING_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )

    def _cmd_test(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'test' command with the observed hop count.

        Sends a direct-connect message when the hop count is zero, otherwise
        reports the number of hops the message travelled.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        hops_taken: int = MeshtasticHelper.get_hop_count_from_packet(packet)
        if hops_taken == 0:
            message: str = _TEST_RESPONSE_DIRECT
        else:
            message = _TEST_RESPONSE.format(hop_count=hops_taken)

        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=message,
            packet=packet,
            consoleMsg=_TEST_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )

    def _cmd_last(self, sender: str, params: str, packet: dict) -> None:
        """Sends the last N messages from a channel's history as individual DMs.

        Parses the command params as ``<count> <channel_name>``. When the command
        originates from a channel, posts a single notification on that channel first
        so observers know DMs are incoming. Each history message is then sent as a
        separate DM using a ``threading.Timer`` per message so the Meshtastic
        receive thread is never blocked. Messages are delivered oldest-first.

        Args:
            sender: The node ID string of the message sender.
            params: Space-separated string containing the count and channel name
                    (e.g. ``'10 OMalleyLand'``).
            packet: The full raw Meshtastic packet dictionary.
        """
        parts: list[str] = params.strip().split(None, 1)
        valid: bool = len(parts) == 2 and parts[0].isdigit() and int(parts[0]) > 0
        if not valid:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                packet={},
                message=_MSG_LAST_USAGE,
                destinationId=sender,
            )
        else:
            count: int = int(parts[0])
            channel_name: str = parts[1]
            capped: bool = count > _CMD_LAST_MAX_MESSAGES
            if capped:
                count = _CMD_LAST_MAX_MESSAGES
            messages: list[str] = ChatHistory.read_last(channel_name, count, self._data_dir, self._passphrase)
            if not messages:
                MeshtasticHelper.send_text_message(
                    iface=self._iface,
                    channelIndex=self._channel.index,
                    packet={},
                    message=_MSG_LAST_NOT_FOUND.format(channel=channel_name),
                    destinationId=sender,
                )
            else:
                from_channel: bool = not MeshtasticHelper.is_direct_message(packet, self._config.node_id)
                # Send cap warning first (always a DM, uses packet={} to avoid consuming the original reply context)
                if capped:
                    MeshtasticHelper.send_text_message(
                        iface=self._iface,
                        channelIndex=self._channel.index,
                        packet={},
                        message=_MSG_LAST_CAPPED.format(requested=int(parts[0]), max=_CMD_LAST_MAX_MESSAGES),
                        destinationId=sender,
                    )
                if from_channel:
                    MeshtasticHelper.send_text_message(
                        iface=self._iface,
                        channelIndex=self._channel.index,
                        packet=packet,
                        message=_MSG_LAST_DM_INCOMING.format(count=len(messages), channel=channel_name),
                        destinationId=None,
                        chat_history=self._chat_history,
                        chat_sender=_CHAT_HISTORY_BOT_SENDER,
                    )
                # Send oldest message first. When from a channel the notification
                # already consumed the original packet so all DMs use packet={}.
                # When from DM the first timer carries packet=packet for a reply
                # context; subsequent ones use packet={} to avoid deduplication.
                ordered: list[str] = list(reversed(messages))
                for i, msg in enumerate(ordered):
                    delay: float = _CMD_SEND_DELAY * (i + 1) if from_channel else _CMD_SEND_DELAY * i
                    pkt: dict = {} if from_channel or i > 0 else packet
                    threading.Timer(
                        delay,
                        MeshtasticHelper.send_text_message,
                        kwargs=dict(
                            iface=self._iface,
                            channelIndex=self._channel.index,
                            packet=pkt,
                            message=msg,
                            destinationId=sender,
                        ),
                    ).start()
                if self._verbose:
                    display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
                    print(_MSG_LAST_CONSOLE.format(count=len(messages), channel=channel_name, sender=display_name))

    def _cmd_trace(self, sender: str, params: str, packet: dict) -> None:
        """Sends a traceroute request to the requester and stores the pending result context.

        Sends an acknowledgement to the requester, records the origin context so the
        response can be routed correctly, then issues a traceroute to the sender's node.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=_TRACE_RESPONSE_WAITING,
            packet=packet,
            consoleMsg=_TRACE_CONSOLE_SENT.format(sender=sender) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )
        self._pending_traces[sender] = (MeshtasticHelper.is_direct_message(packet, self._config.node_id), time.time())
        self._iface.sendTraceRoute(dest=sender, hopLimit=_TRACE_HOP_LIMIT, channelIndex=self._channel.index)

    def _cmd_web(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'web' command with the URL of the web dashboard.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=_WEB_RESPONSE.format(web_url=self._web_url),
            packet=packet,
            consoleMsg=_WEB_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )

    def _on_traceroute_response(self, packet: dict, interface: MeshInterface) -> None:
        """Handles a received traceroute response and sends the formatted result to the requester.

        Looks up the originating sender in the pending traces dict. If found, formats
        the route and sends it as a DM or channel message depending on where the
        original ``!trace`` command came from.

        Args:
            packet: The raw Meshtastic traceroute response packet.
            interface: The MeshInterface that received the packet (unused).
        """
        from_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        pending: tuple[bool, float] | None = self._pending_traces.pop(from_id, None)
        if pending is not None:
            as_dm: bool = pending[0]
            elapsed: float = time.time() - pending[1]
            result: str = self._format_traceroute(packet) + _TRACE_DURATION_SUFFIX.format(seconds=elapsed)
            if self._verbose:
                print(_TRACE_CONSOLE_RECEIVED.format(sender=from_id))
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=result,
                packet={},
                destinationId=from_id if as_dm else None,
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )

    def _format_traceroute(self, packet: dict) -> str:
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

    def _node_label(self, node_num: int) -> str:
        """Resolves a short display label for a node given its numeric ID.

        Args:
            node_num: The integer node number to resolve.

        Returns:
            The node's short name if found in the interface table, otherwise
            the ``'!hex'`` node ID string.
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
    # endregion Protected Functions

    # region Public Functions
    def initialize_default_responses(self) -> dict[str, CommandHandler]:
        """Returns the default command dispatch table for this bot.

        Returns:
            A dict mapping command name strings to their handler callables.
        """
        return {
            CMD_HELLO: self._cmd_hello,
            CMD_PING: self._cmd_ping,
            CMD_TEST: self._cmd_test,
            CMD_LAST: self._cmd_last,
            CMD_TRACE: self._cmd_trace,
            CMD_WEB: self._cmd_web,
        }
    # endregion Public Functions
