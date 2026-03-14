from __future__ import annotations
import threading
from typing import Optional
from common.constants import (
    CMD_HELLO,
    CMD_PING,
    CMD_TEST,
    CMD_LAST,
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
    _BROADCAST_ID,
    _PACKET_KEY_TO_ID,
    _CMD_SEND_DELAY,
    _CMD_LAST_MAX_MESSAGES,
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
    _reply_as_dm: bool
    _passphrase: Optional[str]
    _data_dir: str
    # endregion Protected Variables

    # region Constructor
    def __init__(self, iface: MeshInterface, config: NodeConfiguration, channel: channel_pb2.Channel, verbose: bool = False, reply_as_dm: bool = False, passphrase: Optional[str] = None, data_dir: str = _NODE_DB_DIR) -> None:
        """Initialises the command handler with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection used to send reply messages.
            config: The NodeConfiguration object containing local node information.
            channel: The channel on which replies will be broadcast.
            verbose: When True, prints a console confirmation for each command handled.
            reply_as_dm: When True, replies are sent as direct messages to the sender
                         instead of being broadcast on the channel.
            passphrase: Optional passphrase used to decrypt chat history files when
                        serving the ``!last`` command. Must match the value used at
                        write time. Defaults to ``None`` (plain-text files).
            data_dir: Directory containing the chat history log files.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._verbose = verbose
        self._reply_as_dm = reply_as_dm
        self._passphrase = passphrase
        self._data_dir = data_dir
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
            destinationId=sender if self._reply_as_dm else None
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
            destinationId=sender if self._reply_as_dm else None
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
            destinationId=sender if self._reply_as_dm else None
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
                from_channel: bool = packet.get(_PACKET_KEY_TO_ID) == _BROADCAST_ID
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
        }
    # endregion Public Functions
