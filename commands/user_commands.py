from __future__ import annotations
from commands.joke_manager import JokeManager
from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface
from common.chat_history import ChatHistory

from common.constants import (
    CMD_JOKE,
    CMD_HELLO,
    _HELLO_CONSOLE_RESPONSE,
    _HELLO_RESPONSE_NO_PARAMS,
    _JOKE_CONSOLE_SENT,
    _JOKE_ERROR_RESPONSE,
    _NODE_DB_DIR,
    _CHAT_HISTORY_BOT_SENDER
)
_HELLO_RESPONSE: str = _HELLO_RESPONSE_NO_PARAMS + " :: {hop_count} 🐇hops"


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
    _joke_manager: JokeManager
    _chat_history: ChatHistory | None
    _verbose: bool
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
    ) -> None:
        """Initialises the user commands with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection used to send reply messages.
            config: The NodeConfiguration object containing local node information.
            channel: The channel on which replies will be broadcast.
            verbose: When True, prints a console confirmation for each command handled.
            data_dir: Directory used to persist the joke cache file. Defaults to the
                      shared ``data`` directory.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._verbose = verbose
        self._joke_manager = JokeManager(data_dir=data_dir)
        self._chat_history = chat_history
    # endregion Constructor

    # region Protected Functions
    
    # def _cmd_hey_hey(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
    #     """Responds to the 'heyhey' command with a personalised greeting and hop count.

    #     Args:
    #         sender: The node ID string of the message sender.
    #         params: Any text that followed the command name (unused).
    #         packet: The full raw Meshtastic packet dictionary.
    #     """
    #     display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
    #     hop_count: int = MeshtasticHelper.get_hop_count_from_packet(packet)
    #     return MeshtasticHelper.send_text_message(
    #         iface=self._iface,
    #         channelIndex=self._channel.index,
    #         packet=packet,
    #         message=_HEY_HEY_RESPONSE.format(display_name=display_name, hop_count=hop_count),
    #         consoleMsg=_HEY_HEY_CONSOLE_RESPONSE.format(display_name=display_name, hop_count=hop_count) if self._verbose else None,
    #         destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None
    #     )
    
    
    def _cmd_hello(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Responds to the custom hello2 command with a personalised greeting and hop count.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        display_name: str = MeshtasticHelper.resolve_display_name(sender, self._iface)
        hop_count: int = MeshtasticHelper.get_hop_count_from_packet(packet)
        return MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            packet=packet,
            message=_HELLO_RESPONSE.format(display_name=display_name, hop_count=hop_count),
            consoleMsg=_HELLO_CONSOLE_RESPONSE.format(display_name=display_name, params=params) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER
        )

    def _cmd_joke(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Responds to the 'joke' command with a joke fetched from JokeAPI or the local cache.

        Fetches a fresh joke from the JokeAPI and saves it to the local cache. Falls
        back to a randomly selected cached joke if the API is unavailable. Sends an
        error reply when neither source has a joke available.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        joke: str | None = self._joke_manager.fetch_joke()
        message: str = joke if joke is not None else _JOKE_ERROR_RESPONSE
        return MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            packet=packet,
            message=message,
            consoleMsg=_JOKE_CONSOLE_SENT.format(sender=sender) if self._verbose else None,
            destinationId=sender if MeshtasticHelper.is_direct_message(packet, self._config.node_id) else None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER
        )
    # endregion Protected Functions

    # region Public Functions
    def get_commands(self) -> dict[str, CommandHandler]:
        """Returns the user-defined command dispatch table.

        Returns:
            A dict mapping command name strings to their handler callables.
        """
        return {
            f"{CMD_HELLO}2": self._cmd_hello,
            # _CMD_HEY_HEY: self._cmd_hey_hey
            CMD_JOKE: self._cmd_joke,
        }
    # endregion Public Functions