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
    _HELLO_CONSOLE_RESPONSE,
    _PING_CONSOLE_RESPONSE,
    _TEST_CONSOLE_RESPONSE,
    _MSG_LAST_DM_INCOMING,
    _MSG_LAST_CAPPED,
    _MSG_LAST_CONSOLE,
    _NODE_DB_DIR,
    _CMD_SEND_DELAY,
    _CMD_LAST_MAX_MESSAGES,
    _EVENT_TRACEROUTE,
    _TRACE_RESPONSE_WAITING,
    _TRACE_CONSOLE_SENT,
    _TRACE_CONSOLE_RECEIVED,
    _TRACE_HOP_LIMIT,
    _TRACE_DURATION_SUFFIX,
    _CHAT_HISTORY_BOT_SENDER,
    _WEB_CONSOLE_RESPONSE,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_WEB_RESPONSES,
)
from common.chat_history import ChatHistory
from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.bot_command_helper import BotCommandHelper
from messaging.command_handler import CommandHandler
from messaging.last_command_result import LastCommandResult
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
    _helper: BotCommandHelper
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
        self._helper = BotCommandHelper(iface=iface, data_dir=data_dir, passphrase=passphrase, web_url=web_url)
        pub.subscribe(self._on_traceroute_response, _EVENT_TRACEROUTE)
    # endregion Constructor

    # region Protected Functions
    def _cmd_hello(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'hello' command with a personalised greeting.

        When the packet originates from a web user the response is written into
        the packet rather than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name.
            packet: The full raw Meshtastic packet dictionary.
        """
        display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
        message: str = self._helper.compute_hello(display_name, params)
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
        else:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=message,
                packet=packet,
                consoleMsg=_HELLO_CONSOLE_RESPONSE.format(display_name=display_name, params=params) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )

    def _cmd_ping(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'ping' command with a pong reply on the channel.

        When the packet originates from a web user the response is written into
        the packet rather than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        message: str = self._helper.compute_ping()
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
        else:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=message,
                packet=packet,
                consoleMsg=_PING_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )

    def _cmd_test(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'test' command with the observed hop count.

        Sends a direct-connect message when the hop count is zero, otherwise
        reports the number of hops the message travelled. When the packet
        originates from a web user the response is written into the packet
        rather than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        hops_taken: int = MeshtasticHelper.get_hop_count_from_packet(packet)
        message: str = self._helper.compute_test(hops_taken)
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
        else:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=message,
                packet=packet,
                consoleMsg=_TEST_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )

    def _cmd_last(self, sender: str, params: str, packet: dict) -> None:
        """Sends the last N messages from a channel's history as individual DMs.

        Delegates parsing and history retrieval to the helper, then handles all
        mesh transmissions. When the command originates from a channel, posts a
        single notification on that channel first so observers know DMs are incoming.
        Each history message is sent as a separate DM via a ``threading.Timer`` so
        the Meshtastic receive thread is never blocked. Messages are delivered
        oldest-first.

        When the packet originates from a web user, all response messages are
        collected synchronously into the packet rather than transmitted over the
        mesh or scheduled via timers.

        Args:
            sender: The node ID string of the message sender.
            params: Space-separated string containing the count and channel name
                    (e.g. ``'10 OMalleyLand'``).
            packet: The full raw Meshtastic packet dictionary.
        """
        is_web_dm: bool = MeshtasticHelper.is_web_user_packet(packet)
        result: LastCommandResult = self._helper.compute_last(params)
        if is_web_dm:
            responses: list[str] = []
            if result.error_message is not None:
                responses.append(result.error_message)
            else:
                if result.was_capped:
                    responses.append(_MSG_LAST_CAPPED.format(requested=result.original_count, max=_CMD_LAST_MAX_MESSAGES))
                for msg in result.messages:
                    responses.append(msg)
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = responses
        else:
            if result.error_message is not None:
                MeshtasticHelper.send_text_message(
                    iface=self._iface,
                    channelIndex=self._channel.index,
                    packet={},
                    message=result.error_message,
                    destinationId=sender,
                )
            else:
                from_channel: bool = not MeshtasticHelper.is_direct_message(packet, self._config.node_id)
                # Send cap warning first (always a DM, uses packet={} to avoid consuming the original reply context)
                if result.was_capped:
                    MeshtasticHelper.send_text_message(
                        iface=self._iface,
                        channelIndex=self._channel.index,
                        packet={},
                        message=_MSG_LAST_CAPPED.format(requested=result.original_count, max=_CMD_LAST_MAX_MESSAGES),
                        destinationId=sender,
                    )
                if from_channel:
                    MeshtasticHelper.send_text_message(
                        iface=self._iface,
                        channelIndex=self._channel.index,
                        packet=packet,
                        message=_MSG_LAST_DM_INCOMING.format(count=len(result.messages), channel=result.channel_name),
                        destinationId=None,
                        chat_history=self._chat_history,
                        chat_sender=_CHAT_HISTORY_BOT_SENDER,
                    )
                # Send oldest message first. When from a channel the notification
                # already consumed the original packet so all DMs use packet={}.
                # When from DM the first timer carries packet=packet for a reply
                # context; subsequent ones use packet={} to avoid deduplication.
                for i, msg in enumerate(result.messages):
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
                    print(_MSG_LAST_CONSOLE.format(count=len(result.messages), channel=result.channel_name, sender=display_name))

    def _cmd_trace(self, sender: str, params: str, packet: dict) -> None:
        """Sends a traceroute request to the requester and stores the pending result context.

        Sends an acknowledgement to the requester, records the origin context so the
        response can be routed correctly, then issues a traceroute to the sender's node.
        When the packet originates from a web user the acknowledgement is written into
        the packet; the async traceroute result will not be delivered via the DM endpoint.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [_TRACE_RESPONSE_WAITING]
        else:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=_TRACE_RESPONSE_WAITING,
                packet=packet,
                consoleMsg=_TRACE_CONSOLE_SENT.format(sender=sender) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )
        self._pending_traces[sender] = (MeshtasticHelper.is_direct_message(packet, self._config.node_id), time.time())
        self._iface.sendTraceRoute(dest=sender, hopLimit=_TRACE_HOP_LIMIT)#, channelIndex=self._channel.index)

    def _cmd_web(self, sender: str, params: str, packet: dict) -> None:
        """Responds to the 'web' command with the URL of the web dashboard.

        When the packet originates from a web user the response is written into
        the packet rather than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        message: str = self._helper.compute_web()
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
        else:
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=message,
                packet=packet,
                consoleMsg=_WEB_CONSOLE_RESPONSE.format(sender=sender) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
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
        to_id: str = packet.get("toId", "") #(_PACKET_KEY_TO_ID, "")
        print(f"Received trace response from {from_id} to {to_id}")
        pending: tuple[bool, float] | None = self._pending_traces.pop(from_id, None)
        if pending is not None:
            # as_dm: bool = pending[0]
            elapsed: float = time.time() - pending[1]
            result: str = self._helper.format_traceroute(packet) + _TRACE_DURATION_SUFFIX.format(seconds=elapsed)
            MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                message=result,
                packet={},
                destinationId=from_id, #if as_dm else None, #Updated to Force DM for all trace responses to avoid channel spam and ensure delivery even when original command came from a channel.
                consoleMsg=_TRACE_CONSOLE_RECEIVED.format(sender=from_id) if self._verbose else None,
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )

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
