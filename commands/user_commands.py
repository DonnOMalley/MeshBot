from __future__ import annotations
import threading
from commands.user_command_helper import UserCommandHelper
from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface
from common.chat_history import ChatHistory

from common.constants import (
    CMD_JOKE,
    CMD_HELLO,
    CMD_RANGE,
    _CMD_SEND_DELAY,
    _HELLO_CONSOLE_RESPONSE,
    _JOKE_CONSOLE_SENT,
    _NODE_DB_DIR,
    _CHAT_HISTORY_BOT_SENDER,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_WEB_RESPONSES,
    _RANGE_TEST_DEFAULT_DELAY_MINUTES,
    _RANGE_TEST_DEFAULT_REQUESTS,
    _RANGE_TEST_MAX_DELAY_MINUTES,
    _RANGE_TEST_MAX_REQUESTS,
    _RANGE_TEST_MIN_DELAY_MINUTES,
    _RANGE_TEST_MIN_REQUESTS,
    _RANGE_TEST_MSG_TEMPLATE,
    _RANGE_TEST_CONSOLE_SENT,
    _RANGE_TEST_SECONDS_PER_MINUTE,
)


class UserCommands:
    """Provides user-defined command handlers for the DAMNBot application.

    Registers custom commands that extend or override the default out-of-the-box
    bot commands. Handlers are retrieved via get_commands() and passed to the
    ChannelMonitor as user_defined_commands.
    """

    # region Protected Variables
    _iface: MeshInterface
    _config: NodeConfiguration
    _channel: channel_pb2.Channel
    _chat_history: ChatHistory | None
    _verbose: bool
    _helper: UserCommandHelper
    _range_test_requests: int
    _range_test_delay_minutes: int
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        iface: MeshInterface,
        config: NodeConfiguration,
        channel: channel_pb2.Channel,
        chat_history: ChatHistory | None = None,
        verbose: bool = False,
        data_dir: str = _NODE_DB_DIR,
        range_test_requests: int = _RANGE_TEST_DEFAULT_REQUESTS,
        range_test_delay_minutes: int = _RANGE_TEST_DEFAULT_DELAY_MINUTES,
    ) -> None:
        """Initialises the user commands with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection used to send reply messages.
            config: The NodeConfiguration object containing local node information.
            channel: The channel on which replies will be broadcast.
            chat_history: Optional chat history to which bot replies are appended.
            verbose: When True, prints a console confirmation for each command handled.
            data_dir: Directory used to persist the joke cache file. Defaults to the
                      shared ``data`` directory.
            range_test_requests: Number of messages the !range command sends. Clamped
                                  to [1, 10]. Defaults to 5.
            range_test_delay_minutes: Minutes between each !range message. Clamped
                                       to [1, 10]. Defaults to 1.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._verbose = verbose
        self._chat_history = chat_history
        self._helper = UserCommandHelper(data_dir=data_dir)
        self._range_test_requests = range_test_requests
        self._range_test_delay_minutes = range_test_delay_minutes
    # endregion Constructor

    # region Protected Functions
    
    
    def _cmd_hello(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Responds to the custom hello2 command with a personalised greeting and hop count.

        When the packet originates from a web user the response is written into
        the packet rather than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
        hop_count: int = MeshtasticHelper.get_hop_count_from_packet(packet)
        message: str = self._helper.compute_hello(display_name, hop_count)
        result: mesh_pb2.MeshPacket | None
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
            result = None
        else:
            result = MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                packet=packet,
                message=message,
                consoleMsg=_HELLO_CONSOLE_RESPONSE.format(display_name=display_name, params=params) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )
        return result

    def _cmd_joke(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Responds to the 'joke' command with a joke fetched from JokeAPI or the local cache.

        Fetches a fresh joke from the JokeAPI and saves it to the local cache. Falls
        back to a randomly selected cached joke if the API is unavailable. Sends an
        error reply when neither source has a joke available. When the packet
        originates from a web user the response is written into the packet rather
        than transmitted over the mesh.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        message: str = self._helper.compute_joke()
        result: mesh_pb2.MeshPacket | None = None
        if MeshtasticHelper.is_web_user_packet(packet):
            packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES] = [message]
            result = None        
        else:
            result = MeshtasticHelper.send_text_message(
                iface=self._iface,
                channelIndex=self._channel.index,
                packet=packet,
                message=message,
                consoleMsg=_JOKE_CONSOLE_SENT.format(sender=sender) if self._verbose else None,
                destinationId=MeshtasticHelper.get_message_destination_id(packet, sender, self._config.node_id),
                chat_history=self._chat_history,
                chat_sender=_CHAT_HISTORY_BOT_SENDER,
            )
        return result
    
    def _cmd_range_test(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Sends a series of range-test messages with a configurable count and interval.

        The number of messages and the delay between them can be overridden at
        call time by supplying them as space-separated integers in ``params``
        (e.g. ``3 2`` for 3 messages, 2 minutes apart). Values outside the
        allowed [1, 10] bounds are clamped silently. Configured defaults are
        used for any parameter that is absent or non-numeric.

        Args:
            sender: The node ID string of the message sender.
            params: Optional override values: ``"<requests> <delay_minutes>"``.
            packet: The full raw Meshtastic packet dictionary.
        """
        parts: list[str] = params.split()
        num_requests: int = self._range_test_requests
        delay_minutes: int = self._range_test_delay_minutes
        if len(parts) >= 1 and parts[0].isdigit():
            num_requests = int(parts[0])
        if len(parts) >= 2 and parts[1].isdigit():
            delay_minutes = int(parts[1])
        num_requests = max(_RANGE_TEST_MIN_REQUESTS, min(_RANGE_TEST_MAX_REQUESTS, num_requests))
        delay_minutes = max(_RANGE_TEST_MIN_DELAY_MINUTES, min(_RANGE_TEST_MAX_DELAY_MINUTES, delay_minutes))
        for i in range(1, num_requests + 1):
            timer_delay: float = _CMD_SEND_DELAY + (i - 1) * delay_minutes * _RANGE_TEST_SECONDS_PER_MINUTE
            message: str = _RANGE_TEST_MSG_TEMPLATE.format(i=i, total=num_requests)
            threading.Timer(
                timer_delay,
                MeshtasticHelper.send_text_message,
                kwargs=dict(
                    iface=self._iface,
                    channelIndex=self._channel.index,
                    packet=packet,
                    message=message,
                    consoleMsg=_RANGE_TEST_CONSOLE_SENT.format(i=i, total=num_requests, sender=sender) if self._verbose else None,
                    destinationId=sender,
                    chat_history=self._chat_history,
                    chat_sender=_CHAT_HISTORY_BOT_SENDER,
                ),
            ).start()
    # endregion Protected Functions

    # region Public Functions
    def get_commands(self) -> dict[str, CommandHandler]:
        """Returns the user-defined command dispatch table.

        Returns:
            A dict mapping command name strings to their handler callables.
        """
        return {
            # CMD_HELLO: self._cmd_hello,
            f"{CMD_HELLO}2": self._cmd_hello,
            CMD_JOKE: self._cmd_joke,
            CMD_RANGE: self._cmd_range_test,
        }
    # endregion Public Functions