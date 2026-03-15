from __future__ import annotations
import threading
from configuration.node_configuration import NodeConfiguration
from messaging.bot_commands import BotCommands
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface
from common.meshtastic_helper import MeshtasticHelper
from common.constants import (
    CMD_LIST,
    _MSG_BOT_COMMAND_LIST_DM_SENT,
    _CMD_SEND_DELAY,
    _CMD_LIST_HEADER,
    _CMD_LIST_ITEM_FORMAT,
)


class CommandRegister:
    """Maintains the command dispatch table for a monitor.

    Registers OOTB commands (hello, ping, test) unless excluded, then applies any
    user-defined overrides. An additional built-in `cmdlist` command is always
    registered last so callers can discover what commands are available.
    """

    # region Protected Variables
    _iface: MeshInterface
    _config: NodeConfiguration
    _channel: channel_pb2.Channel
    _commands: dict[str, CommandHandler]
    _verbose: bool
    _passphrase: str | None
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        iface: MeshInterface,
        config: NodeConfiguration,
        channel: channel_pb2.Channel,
        user_defined_commands: dict[str, CommandHandler] | None = None,
        exclude_ootb: bool = False,
        verbose: bool = False,
        passphrase: str | None = None,
    ) -> None:
        """Initialises the register and applies any supplied handler overrides.

        Args:
            iface: The active MeshInterface connection to the Meshtastic device.
            config: The NodeConfiguration object containing local node information.
            channel: The channel object used to scope the command handlers.
            user_defined_commands: Optional mapping of command name to handler callable
                                   for user-defined commands. Each entry overrides or
                                   extends the default OOTB handlers when a prefix is
                                   present.
            exclude_ootb: When True, the OOTB ping and test commands are not
                          registered. Hello is always registered. Defaults to False.
            verbose: When True, command handlers print console confirmations.
            passphrase: Optional passphrase forwarded to OOTB command handlers that
                        need to read encrypted data files (e.g. ``!last``).
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._commands = {}
        self._verbose = verbose
        self._passphrase = passphrase

        if not exclude_ootb:
            for name, callback_fn in BotCommands(iface, config, channel, verbose=verbose, passphrase=passphrase).initialize_default_responses().items():
                self._commands[name] = callback_fn

        if user_defined_commands:
            for name, callback_fn in user_defined_commands.items():
                self._commands[name] = callback_fn

        self._commands[CMD_LIST] = self._cmd_list
    # endregion Constructor

    # region Protected Functions
    def _cmd_list(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Sends a formatted list of all registered commands as a DM to the sender.

        The list is always sent as a direct message to the sender regardless of
        whether the command was issued on a channel or via DM, keeping the
        channel free of lengthy command-list responses.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name (unused).
            packet: The full raw Meshtastic packet dictionary.
        """
        result: mesh_pb2.MeshPacket | None = None
        items: list[str] = [_CMD_LIST_ITEM_FORMAT.format(cmd=cmd) for cmd in sorted(self._commands.keys())]

        # Send the DM immediately. Schedule the channel notification on a background
        # thread after a delay so the receive thread is not blocked — both messages
        # must have distinct replyIds to prevent the radio from deduplicating them.
        result = MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            packet={},
            message=_CMD_LIST_HEADER + "\n" + "\n".join(items),
            destinationId=sender,
        )

        threading.Timer(
            _CMD_SEND_DELAY,
            MeshtasticHelper.send_text_message,
            kwargs=dict(
                iface=self._iface,
                channelIndex=self._channel.index,
                packet=packet,
                message=_MSG_BOT_COMMAND_LIST_DM_SENT,
                destinationId=None,
            ),
        ).start()
        return result
    # endregion Protected Functions
