from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface

from common.constants import _HELLO_CONSOLE_RESPONSE, CMD_HELLO
_HELLO_RESPONSE: str = "Ack: {hop_count} 🐇"

# _CMD_HEY_HEY: str = "heyhey"
# _HEY_HEY_RESPONSE: str = "Hey Hey!! Great to hear from you {display_name}! {hop_count} 🐇"
# _HEY_HEY_CONSOLE_RESPONSE: str = "[BOT] HeyHey command received from {display_name} after {hop_count} 🐇"

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
    _verbose: bool
    # endregion Protected Variables

    # region Constructor
    def __init__(self, iface: MeshInterface, config: NodeConfiguration, channel: channel_pb2.Channel, verbose: bool = False) -> None:
        """Initialises the user commands with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection used to send reply messages.
            config: The NodeConfiguration object containing local node information.
            channel: The channel on which replies will be broadcast.
            verbose: When True, prints a console confirmation for each command handled.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._verbose = verbose
    # endregion Constructor

    # region Protected Functions
    def _cmd_hello(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
      return MeshtasticHelper.send_text_message(
          iface=self._iface,
          channelIndex=self._channel.index,
          packet=packet,
          message=_HELLO_RESPONSE.format(hop_count=MeshtasticHelper.get_hop_count_from_packet(packet)),
          consoleMsg=_HELLO_CONSOLE_RESPONSE.format(display_name=MeshtasticHelper.resolve_display_name(sender, self._iface), params=params) if self._verbose else None
      )

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
    #         consoleMsg=_HEY_HEY_CONSOLE_RESPONSE.format(display_name=display_name, hop_count=hop_count) if self._verbose else None
    #     )
    
    # endregion Protected Functions

    # region Public Functions
    def get_commands(self) -> dict[str, CommandHandler]:
        """Returns the user-defined command dispatch table.

        Returns:
            A dict mapping command name strings to their handler callables.
        """
        return {
            CMD_HELLO: self._cmd_hello,
            # _CMD_HEY_HEY: self._cmd_hey_hey
        }
    # endregion Public Functions