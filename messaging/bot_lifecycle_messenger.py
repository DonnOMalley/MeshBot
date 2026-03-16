from __future__ import annotations
from typing import Optional
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface
from common.chat_history import ChatHistory
from common.constants import (
    _BOT_WELCOME_MESSAGE,
    _BOT_CHECKIN_MESSAGE,
    _BOT_SIGNOFF_MESSAGE,
    _BOT_WELCOME_MESSAGE_SENT,
    _BOT_CHECKIN_MESSAGE_SENT,
    _BOT_SIGNOFF_MESSAGE_SENT,
    _CHAT_HISTORY_BOT_SENDER,
)
from configuration.node_configuration import NodeConfiguration

from common.chat_history import ChatHistory
from common.meshtastic_helper import MeshtasticHelper

class BotLifecycleMessenger:
    """Sends pre-defined bot lifecycle messages over the Meshtastic network."""

    # region Protected Variables
    _bot_name: str
    _iface: MeshInterface
    _config: NodeConfiguration
    _verbose: bool
    _web_url: str
    _chat_history: Optional[ChatHistory]
    # endregion Protected Variables

    # region Constructor
    def __init__(self, iface: MeshInterface, config: NodeConfiguration, bot_name: str, verbose: bool = False, web_url: str = "", chat_history: Optional[ChatHistory] = None) -> None:
        """Initialises the broadcaster with an active Meshtastic interface.

        Args:
            iface: The active MeshInterface connection used to transmit messages.
            config: The NodeConfiguration object containing local node information.
            bot_name: The display name of the bot used in lifecycle messages.
            verbose: When True, prints a console confirmation for each message sent.
            web_url: The full URL of the web dashboard included in the welcome message.
            chat_history: When provided, lifecycle messages broadcast to the channel
                          are appended to the log under the ``[BOT]`` sender label.
        """
        self._bot_name = bot_name
        self._iface = iface
        self._config = config
        self._verbose = verbose
        self._web_url = web_url
        self._chat_history = chat_history
    # endregion Constructor

    # region Protected Functions
    def _broadcast_message(self, channel: channel_pb2.Channel, channel_msg: str, console_msg: str) -> None:
        """Sends a message on the channel, logs it to chat history, and prints a console log.

        Args:
            channel: The channel on which to send the message.
            channel_msg: The message text to broadcast on the channel.
            console_msg: The message text to print to the console.
        """        
        MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=channel.index,
            message=channel_msg,
            packet={},
            consoleMsg=console_msg.format(name=channel.settings.name, index=channel.index) if self._verbose else None,
            destinationId=None,
            chat_history=self._chat_history,
            chat_sender=_CHAT_HISTORY_BOT_SENDER,
        )
            
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
