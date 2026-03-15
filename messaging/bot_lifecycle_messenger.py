from __future__ import annotations
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface
from common.constants import (
    _BOT_WELCOME_MESSAGE,
    _BOT_CHECKIN_MESSAGE,
    _BOT_SIGNOFF_MESSAGE,
    _BOT_WELCOME_MESSAGE_SENT,
    _BOT_CHECKIN_MESSAGE_SENT,
    _BOT_SIGNOFF_MESSAGE_SENT,
)
from configuration.node_configuration import NodeConfiguration


class BotLifecycleMessenger:
    """Sends pre-defined bot lifecycle messages over the Meshtastic network."""

    # region Protected Variables
    _bot_name: str
    _iface: MeshInterface
    _config: NodeConfiguration
    _verbose: bool
    _web_url: str
    # endregion Protected Variables

    # region Constructor
    def __init__(self, iface: MeshInterface, config: NodeConfiguration, bot_name: str, verbose: bool = False, web_url: str = "") -> None:
        """Initialises the broadcaster with an active Meshtastic interface.

        Args:
            iface: The active MeshInterface connection used to transmit messages.
            config: The NodeConfiguration object containing local node information.
            bot_name: The display name of the bot used in lifecycle messages.
            verbose: When True, prints a console confirmation for each message sent.
            web_url: The full URL of the web dashboard included in the welcome message.
        """
        self._bot_name = bot_name
        self._iface = iface
        self._config = config
        self._verbose = verbose
        self._web_url = web_url
    # endregion Constructor

    # region Protected Functions
    def _broadcast_message(self, channel: channel_pb2.Channel, channel_msg: str, console_msg: str) -> None:
        """Sends a message on the channel and prints a console log.

        Args:
            channel: The channel on which to send the message.
            channel_msg: The message text to broadcast on the channel.
            console_msg: The message text to print to the console.
        """
        self._iface.sendText(channel_msg, channelIndex=channel.index)
        if self._verbose:
            print(console_msg.format(name=channel.settings.name, index=channel.index))
    # endregion Protected Functions

    # region Public Functions
    def send_welcome_message(self, channel: channel_pb2.Channel) -> None:
        """Broadcasts the bot online announcement to the specified channel.

        Args:
            channel: The channel on which to send the welcome message.
        """
        message: str = _BOT_WELCOME_MESSAGE.format(
            bot_name=self._bot_name,
            long_name=self._config.long_name,
            short_name=self._config.short_name,
            node_id=self._config.node_id,
            web_url=self._web_url,
        )
        self._broadcast_message(channel, message, _BOT_WELCOME_MESSAGE_SENT)

    def send_checkin_message(self, channel: channel_pb2.Channel) -> None:
        """Broadcasts a periodic check-in message to the specified channel.

        Args:
            channel: The channel on which to send the check-in message.
        """
        message: str = _BOT_CHECKIN_MESSAGE.format(bot_name=self._bot_name)
        self._broadcast_message(channel, message, _BOT_CHECKIN_MESSAGE_SENT)

    def send_signoff_message(self, channel: channel_pb2.Channel) -> None:
        """Broadcasts the bot going-offline announcement to the specified channel.

        Args:
            channel: The channel on which to send the signoff message.
        """
        message: str = _BOT_SIGNOFF_MESSAGE.format(bot_name=self._bot_name)
        self._broadcast_message(channel, message, _BOT_SIGNOFF_MESSAGE_SENT)
    # endregion Public Functions
