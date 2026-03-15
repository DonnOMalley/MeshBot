from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from pubsub import pub
from common.chat_history import ChatHistory
from common.constants import (
    CHANNEL_NAME_PRIMARY,
    _EVENT_TEXT,
    _EVENT_DATA,
    _MSG_IGNORED,
    _MSG_CHANNEL_COMMAND_RECEIVED,
    _PACKET_KEY_CHANNEL,
    _PACKET_KEY_TO_ID,
    _BROADCAST_ID,
    _PACKET_TYPE_CHANNEL,
    _PACKET_TYPE_DM,
    _EXCLAMATION_PREFIX,
)
from common.meshtastic_helper import MeshtasticHelper
from configuration.node_configuration import NodeConfiguration
from messaging.command_register import CommandRegister
from messaging.command_handler import CommandHandler
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface

class BaseMonitor(ABC):
    """Abstract base class for Meshtastic message monitors.

    Handles pubsub event subscription, prefix-based command dispatch, and monitor
    lifecycle. Subclasses implement _is_message_relevant to define the filter
    predicate, and the four message-format properties to supply log strings
    appropriate to their context.
    """

    # region Protected Variables
    _iface: MeshInterface
    _config: NodeConfiguration
    _channel: channel_pb2.Channel
    _running: bool
    _case_sensitive: bool
    _command_register: CommandRegister
    _verbose: bool
    _chat_history: Optional[ChatHistory]
    # endregion Protected Variables

    # region Protected Properties
    @property
    @abstractmethod
    def _message_type(self) -> str:
        """The packet type this monitor handles: ``_PACKET_TYPE_CHANNEL`` or ``_PACKET_TYPE_DM``."""
        ...

    @property
    @abstractmethod
    def _msg_text_received(self) -> str:
        """Format string logged when a text message is received.

        Must accept ``sender`` and ``text`` keyword arguments.
        """
        ...

    @property
    @abstractmethod
    def _msg_data_received(self) -> str:
        """Format string logged when a data message is received.

        Must accept ``sender``, ``portnum``, and ``payload`` keyword arguments.
        """
        ...

    @property
    @abstractmethod
    def _msg_started(self) -> str:
        """Format string printed when the monitor starts.

        Must accept ``channel_name`` and ``index`` keyword arguments.
        """
        ...

    @property
    @abstractmethod
    def _msg_stopped(self) -> str:
        """Plain string printed when the monitor stops."""
        ...
    # endregion Protected Properties

    # region Constructor
    def __init__(
        self,
        iface: MeshInterface,
        config: NodeConfiguration,
        channel: channel_pb2.Channel,
        case_sensitive: bool = False,
        exclude_ootb: bool = False,
        user_defined_commands: dict[str, CommandHandler] | None = None,
        verbose: bool = False,
        chat_history: Optional[ChatHistory] = None,
        passphrase: Optional[str] = None,
    ) -> None:
        """Initialises the monitor with an active interface and target channel.

        Args:
            iface: The active MeshInterface connection to the Meshtastic device.
            config: The NodeConfiguration object containing local node information.
            channel: The channel used as the target for command replies.
            case_sensitive: When True, the bot prefix and command names must match
                            exactly as typed. Defaults to False (case-insensitive).
            exclude_ootb: When True, the out-of-the-box commands (ping, test) are
                          not registered. Defaults to False.
            user_defined_commands: Optional mapping of command name to handler for
                                   user-defined commands. Defaults to None.
            verbose: When True, prints received messages, dispatched commands, and
                     other monitoring events to the console. Defaults to False.
            chat_history: When provided, every received channel message is appended
                          to the log. Pass ``None`` (default) to disable logging.
            passphrase: Optional passphrase forwarded to command handlers that read
                        encrypted data files (e.g. ``!last``). Must match the value
                        used when those files were written.
        """
        self._iface = iface
        self._config = config
        self._channel = channel
        self._running = False
        self._case_sensitive = case_sensitive
        self._verbose = verbose
        self._chat_history = chat_history

        self._command_register = CommandRegister(
            iface=iface,
            config=config,
            channel=channel,
            user_defined_commands=user_defined_commands,
            exclude_ootb=exclude_ootb,
            verbose=verbose,
            passphrase=passphrase,
            chat_history=chat_history,
        )
    # endregion Constructor

    # region Protected Functions
    def _is_message_relevant(self, packet: dict) -> str | None:
        """Classifies an incoming packet as a channel message, DM, or irrelevant.

        Returns:
            ``_PACKET_TYPE_DM`` if ``toId`` matches the local node ID.
            ``_PACKET_TYPE_CHANNEL`` if the packet is on the monitored channel and
            addressed to all (``toId == '^all'``).
            ``None`` if the packet is neither relevant to this node nor this channel.
        """
        to_id: str | None = packet.get(_PACKET_KEY_TO_ID)
        result: str | None = None
        if to_id == self._config.node_id:
            result = _PACKET_TYPE_DM
        elif packet.get(_PACKET_KEY_CHANNEL, 0) == self._channel.index and to_id == _BROADCAST_ID:
            result = _PACKET_TYPE_CHANNEL
        return result

    def _on_text_message(self, packet: dict, interface: MeshInterface) -> mesh_pb2.MeshPacket | None:
        """Handles an incoming text packet, filtering by type and dispatching commands."""
        if self._verbose:
            print(f"Received text message packet: {packet}")
            
        result: mesh_pb2.MeshPacket | None = None
        packet_type: str | None = self._is_message_relevant(packet)
        if packet_type == self._message_type and self._config.node_id != MeshtasticHelper.get_node_id_from_packet(packet):
            result = self._handle_text_command(self._msg_text_received, packet)
        return result

    def _on_data_message(self, packet: dict, interface: MeshInterface) -> mesh_pb2.MeshPacket | None:
        """Handles an incoming data packet, filtering by type and logging the payload."""
        if self._verbose:
            print(f"Received data message packet: {packet}")
            
        result: mesh_pb2.MeshPacket | None = None
        packet_type: str | None = self._is_message_relevant(packet)
        if packet_type == self._message_type:
            result = self._handle_data_message(self._msg_data_received, packet)
        return result

    def _handle_text_command(self, msg_format: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Parses a text message and dispatches to the appropriate command handler.

        Recognises the bot prefix (@BotName) and the exclamation prefix (!). When
        either prefix is present the remainder is parsed as a command name and optional
        params. When no prefix is present the entire trimmed message is treated as the
        command name.

        Args:
            msg_format: Format string accepting ``sender`` and ``text`` used to log
                        the received message.
            packet: The full raw Meshtastic packet dictionary.
        """
        result: mesh_pb2.MeshPacket | None = None
        sender_node_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        sender_display_name: str = MeshtasticHelper.resolve_display_name(sender_node_id, self._iface)

        text: str = MeshtasticHelper.get_sender_text(packet)
        if self._chat_history is not None:
            self._chat_history.append(sender_display_name, text)
        if self._verbose:
            print(msg_format.format(sender=sender_display_name, text=text))

        trimmed_text: str = text.strip()        
        has_exclamation_prefix: bool = trimmed_text.startswith(_EXCLAMATION_PREFIX)

        if has_exclamation_prefix:
            prefix: str = _EXCLAMATION_PREFIX
            remainder_text: str = trimmed_text[len(prefix):].strip()
        else:
            remainder_text = trimmed_text

        parts: list[str] = remainder_text.split(None, 1)
        command: str = parts[0] if parts else ""
        params: str = parts[1] if len(parts) > 1 else ""
        lookup: str = command if self._case_sensitive else command.lower()
        if self._verbose:
            print(_MSG_CHANNEL_COMMAND_RECEIVED.format(command=command, sender=sender_node_id, params=params))

        commands: dict[str, CommandHandler] = self._command_register._commands
        matched_key: str | None = None
        if self._case_sensitive:
            if lookup in commands:
                matched_key = lookup
        else:
            matched_key = next((k for k in commands if k.lower() == lookup), None)

        if matched_key is not None:
            result = commands[matched_key](sender_node_id, params, packet)
        else:
            if self._verbose:
                print(_MSG_IGNORED.format(cmdPrefix=_EXCLAMATION_PREFIX, text=text))
            result = self._on_unrecognized_command(sender_node_id, packet)
        return result

    def _on_unrecognized_command(self, sender: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Called when a received message does not match any registered command.

        No-op by default. Subclasses may override to send a reply.

        Args:
            sender: The node ID string of the message sender.
            packet: The full raw Meshtastic packet dictionary.
        """

    def _handle_data_message(self, msg_format: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Handles an incoming data message. Reserved for future system-to-system messaging.

        Args:
            msg_format: Format string accepting ``sender``, ``portnum``, and ``payload``
                        used to log the received message.
            packet: The full raw Meshtastic packet dictionary.
        """
        sender_node_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        sender: str = MeshtasticHelper.resolve_display_name(sender_node_id, self._iface)

        portnum: int = MeshtasticHelper.get_port_number_from_packet(packet)
        payload: bytes = MeshtasticHelper.get_payload_from_packet(packet)
        if self._verbose:
            print(msg_format.format(sender=sender, portnum=portnum, payload=payload))
        
        return None

    def _subscribe_to_events(self) -> None:
        """Subscribes to the meshtastic pubsub text and data receive events."""
        pub.subscribe(self._on_text_message, _EVENT_TEXT)
        pub.subscribe(self._on_data_message, _EVENT_DATA)

    def _unsubscribe_from_events(self) -> None:
        """Unsubscribes from the meshtastic pubsub text and data receive events."""
        pub.unsubscribe(self._on_text_message, _EVENT_TEXT)
        pub.unsubscribe(self._on_data_message, _EVENT_DATA)
    # endregion Protected Functions

    # region Public Functions
    def start(self) -> None:
        """Begins monitoring for messages."""
        self._running = True
        channel_name: str = self._channel.settings.name or CHANNEL_NAME_PRIMARY
        self._subscribe_to_events()
        if self._verbose:
            print(self._msg_started.format(channel_name=channel_name, index=self._channel.index))

    def stop(self) -> None:
        """Stops the monitor and unsubscribes from all pubsub events."""
        self._unsubscribe_from_events()
        self._running = False
        if self._verbose:
            print(self._msg_stopped)
    # endregion Public Functions
