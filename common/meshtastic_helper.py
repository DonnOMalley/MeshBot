from __future__ import annotations
from typing import Optional
from common.chat_history import ChatHistory
from common.constants import (
    CHANNEL_NAME_PRIMARY,
    _BROADCAST_ID,
    _PACKET_KEY_ID,
    _PACKET_KEY_FROM_ID,
    _PACKET_KEY_FROM_NUM,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_PORTNUM,
    _PACKET_KEY_PAYLOAD,
    _PACKET_KEY_TEXT,
    _PACKET_KEY_HOP_START,
    _PACKET_KEY_HOP_LIMIT,
    _PACKET_KEY_TO_ID,
    _FORMAT_SHORT_NAME,
    _LATITUDE_SCALE,
    _LONGITUDE_SCALE,
    _MSG_NO_CHANNELS,
    _CHANNEL_LIST_HEADER,
    _CHANNEL_LIST_SEPARATOR,
    _CHANNEL_LIST_ROW,
    _CHANNEL_NAME_PRIMARY_LABEL,
    _CHANNEL_NAME_FORMAT,
    _ROLE_NAMES,
    _WEB_USER_NODE_ID_BYTE,
)
from meshtastic import channel_pb2, mesh_pb2
from meshtastic.mesh_interface import MeshInterface

_NODE_ID_UNKNOWN: str = "Unknown"


class NodeInfo:
    """Holds identity and position information for a single Meshtastic network node."""

    # region Public Variables
    long_name: str
    short_name: str
    node_id: str
    device_type: str
    device_mode: str
    latitude: Optional[float]
    longitude: Optional[float]
    # endregion Public Variables

    # region Constructor
    def __init__(
        self,
        long_name: str,
        short_name: str,
        node_id: str,
        device_type: str,
        device_mode: str,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> None:
        """Initialises the node info record with identity and position data.

        Args:
            long_name: The human-readable long name of the node.
            short_name: The abbreviated short name of the node.
            node_id: The unique node identifier (e.g. '!deadbeef').
            device_type: The hardware model identifier reported by the node.
            device_mode: The operational role assigned to the node.
            latitude: GPS latitude in decimal degrees, or None if unavailable.
            longitude: GPS longitude in decimal degrees, or None if unavailable.
        """
        self.long_name = long_name
        self.short_name = short_name
        self.node_id = node_id
        self.device_type = device_type
        self.device_mode = device_mode
        self.latitude = latitude
        self.longitude = longitude
    # endregion Constructor


class MeshtasticHelper:
    """Provides static utility methods for working with Meshtastic node data."""

    # region Public Functions
    @staticmethod
    def resolve_display_name(sender: str, iface: Optional[MeshInterface] = None) -> str:
        """Resolves a human-readable display name for a sender node ID.

        Looks up the sender in the interface's live node table. If the node is
        not found, returns the raw sender ID string as a fallback.

        Args:
            sender: The node ID string of the message sender (e.g. '!deadbeef').
            iface: Optional live MeshInterface to look up node identity from.

        Returns:
            A formatted display string such as 'Alice (ALI)', or the raw sender
            ID if no node record exists.
        """
        parts: list[str] = []
        
        if iface is not None and iface.nodes:
            sender_node_dict: dict | None = iface.nodes.get(sender)
            if sender_node_dict is not None: 
                user = sender_node_dict.get("user", {})
                long_name: str = user.get("longName", "")
                short_name: str = user.get("shortName", "")

                if long_name:
                    parts.append(long_name)
                if short_name:
                    parts.append(_FORMAT_SHORT_NAME.format(short_name=short_name))
            else:
                print(f"Warning: Node not found in node table. Cannot resolve display name for sender {sender}.")
        
        return " ".join(parts) if len(parts) > 0 else sender

    @staticmethod
    def get_channels(iface: MeshInterface) -> list[channel_pb2.Channel]:
        """Loads and returns the active channel list from the local node.

        Args:
            iface: The active MeshInterface connection to read channels from.

        Returns:
            A list of Channel objects that have an assigned role.
        """
        return [ch for ch in (iface.localNode.channels or []) if ch.role]
    
    @staticmethod
    def get_node_id_from_node_num(node_num: int | None) -> str:
        """Converts a numeric node number to a Meshtastic-format hex node ID string.

        Args:
            node_num: The integer node number to convert, or None if unavailable.

        Returns:
            A hex node ID string like '!deadbeef', or 'Unknown' if node_num is None.
        """
        node_id: str = f"!{node_num:08x}" if node_num is not None else _NODE_ID_UNKNOWN
        return node_id
    
    @staticmethod
    def get_node_num_from_packet(packet: dict) -> Optional[int]:
        """Extracts the sender node number from a Meshtastic packet, if available.

        Args:
            packet: The raw Meshtastic packet dict.

        Returns:
            The sender's node number as an integer, or None if unavailable.
        """
        return packet.get(_PACKET_KEY_FROM_NUM)

    @staticmethod
    def get_node_id_from_packet(packet: dict) -> str:
        """Extracts the sender node ID from a Meshtastic packet.

        Args:
            packet: The raw Meshtastic packet dict.

        Returns:
            The sender's node ID string, resolved from 'fromId' or converted from 'from'.
        """
        return packet.get(_PACKET_KEY_FROM_ID) or MeshtasticHelper.get_node_id_from_node_num(MeshtasticHelper.get_node_num_from_packet(packet))

    @staticmethod
    def get_port_number_from_packet(packet: dict) -> int:
        """Extracts the port number from the decoded section of a Meshtastic packet.

        Args:
            packet: The raw Meshtastic packet dict.

        Returns:
            The integer port number, or 0 if absent.
        """
        return packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_PORTNUM, 0)

    @staticmethod
    def get_payload_from_packet(packet: dict) -> bytes:
        """Extracts the raw payload bytes from the decoded section of a Meshtastic packet.

        Args:
            packet: The raw Meshtastic packet dict.

        Returns:
            The payload bytes, or an empty bytes object if absent.
        """
        return packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_PAYLOAD, b"")

    @staticmethod
    def get_hop_count_from_packet(packet: dict) -> int:
        """Calculates the number of hops a received packet travelled.

        Args:
            packet: The raw Meshtastic packet dict from a received message.

        Returns:
            The number of hops the message travelled, or 0 if the required
            fields are absent from the packet.
        """
        result: int = 0
        if _PACKET_KEY_HOP_START in packet and _PACKET_KEY_HOP_LIMIT in packet:
            result = packet[_PACKET_KEY_HOP_START] - packet[_PACKET_KEY_HOP_LIMIT]
        return result

    @staticmethod
    def get_local_node_info(iface: MeshInterface) -> tuple[str, str, str]:
        """Reads and returns the long name, short name, and node ID of the local node.

        Args:
            iface: The active MeshInterface connection to read identity from.

        Returns:
            A tuple of (long_name, short_name, node_id).
        """
        long_name: str = iface.getLongName() or ""
        short_name: str = iface.getShortName() or ""
        node_num: int = iface.myInfo.my_node_num if iface.myInfo else 0
        node_id: str = MeshtasticHelper.get_node_id_from_node_num(node_num)
        return long_name, short_name, node_id

    @staticmethod
    def get_node_list(iface: MeshInterface) -> dict[str, NodeInfo]:
        """Builds and returns a node registry from the interface's known-nodes table.

        Args:
            iface: The active MeshInterface connection whose node table is read.

        Returns:
            A dict mapping node ID strings to NodeInfo objects. Empty if no nodes
            are known.
        """
        # ourNode = iface.getNode('^local')
        # print(f'Our node preferences: \n{ourNode.localConfig}')
        
        nodes: dict[str, NodeInfo] = {}
        if iface.nodes is not None:
            for node_id, node_data in iface.nodes.items():
                position: dict = node_data.get("position", {})
                lat_i: Optional[int] = position.get("latitudeI")
                lon_i: Optional[int] = position.get("longitudeI")
                latitude: Optional[float] = lat_i * _LATITUDE_SCALE if lat_i is not None else None
                longitude: Optional[float] = lon_i * _LONGITUDE_SCALE if lon_i is not None else None

                user: dict = node_data.get("user", {})
                nodes[node_id] = NodeInfo(
                    long_name=user.get("longName", ""),
                    short_name=user.get("shortName", ""),
                    node_id=node_id,
                    device_type=user.get("hwModel", ""),
                    device_mode=user.get("role", ""),
                    latitude=latitude,
                    longitude=longitude,
                )
        else:
            print("Warning: No nodes found in interface node table.")
        return nodes

    @staticmethod
    def get_channel_by_index(channels: list[channel_pb2.Channel], channel_index: int) -> Optional[channel_pb2.Channel]:
        """Looks up a channel by its numeric index.

        Args:
            channels: The list of active channels to search.
            channel_index: The zero-based channel index to search for.

        Returns:
            The matching Channel object, or None if no channel with that index exists.
        """
        return next((ch for ch in channels if ch.index == channel_index), None)

    @staticmethod
    def get_channel_by_name(channels: list[channel_pb2.Channel], channel_name: str) -> Optional[channel_pb2.Channel]:
        """Looks up a channel by its display name.

        Any variation of 'primary' or '(primary)' (case-insensitive) is treated as an
        alias for the channel at index 0. All other name comparisons are case-insensitive.

        Args:
            channels: The list of active channels to search.
            channel_name: The channel name to search for.

        Returns:
            The matching Channel object, or None if no match is found.
        """
        result: Optional[channel_pb2.Channel] = None
        normalized: str = channel_name.strip().lower().strip("()")
        if normalized == CHANNEL_NAME_PRIMARY:
            result = next((ch for ch in channels if ch.index == 0), None)
        else:
            result = next((ch for ch in channels if ch.settings.name.lower() == channel_name.lower()),None)
        
        return result
      
    @staticmethod
    def get_sender_text(packet: dict) -> str:
        """Extracts the text content from a decoded Meshtastic text message packet.

        Args:
            packet: The raw Meshtastic packet dict.

        Returns:
            The message text string, or an empty string if absent.
        """
        return packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_TEXT, "")
        
    @staticmethod
    def get_message_id(packet: dict) -> Optional[int]:
        """Extracts the message ID from a received Meshtastic packet.

        Args:
            packet: The raw meshtastic packet dict from a received message.

        Returns:
            The integer message ID, or None if the field is absent.
        """
        return packet.get(_PACKET_KEY_ID)

    @staticmethod
    def get_hop_count(packet: dict) -> int:
        """Calculates the hop count from a received Meshtastic packet.

        Args:
            packet: The raw meshtastic packet dict from a received message.

        Returns:
            The number of hops the message travelled, or -1 if the required
            fields are absent from the packet.
        """
        result: int = -1
        if _PACKET_KEY_HOP_START in packet and _PACKET_KEY_HOP_LIMIT in packet:
            hop_start: int = packet[_PACKET_KEY_HOP_START]
            hop_limit: int = packet[_PACKET_KEY_HOP_LIMIT]
            if hop_limit >= hop_start:
                result = hop_limit - hop_start
        return result

    @staticmethod
    def list_channels(channels: list[channel_pb2.Channel]) -> None:
        """Prints a formatted table of all active channels to the console.

        Args:
            channels: The list of active channels to display.
        """
        if not channels:
            print(_MSG_NO_CHANNELS)
        else:
            print(_CHANNEL_LIST_HEADER)
            print(_CHANNEL_LIST_SEPARATOR)
            for ch in channels:
                name: str = (
                    ch.settings.name
                    if ch.settings.name
                    else _CHANNEL_NAME_PRIMARY_LABEL
                    if ch.index == 0
                    else _CHANNEL_NAME_FORMAT.format(index=ch.index)
                )
                role_name: str = _ROLE_NAMES.get(ch.role, str(ch.role))
                uplink: str = "Yes" if ch.settings.uplink_enabled else "No"
                downlink: str = "Yes" if ch.settings.downlink_enabled else "No"
                print(
                    _CHANNEL_LIST_ROW.format(
                        index=ch.index,
                        name=name,
                        role=role_name,
                        uplink=uplink,
                        downlink=downlink,
                    )
                )
    
    @staticmethod
    def is_web_user_packet(packet: dict) -> bool:
        """Returns True if the packet originates from a web portal user.

        Web user node IDs start with the reserved prefix ``'!fe'`` (the web user
        node ID byte). Command handlers use this to avoid transmitting a mesh
        message and instead write the response directly into the packet so the
        web server can read it back.

        Args:
            packet: The raw packet dict to inspect.

        Returns:
            True if the packet's fromId begins with the web user node ID prefix.
        """
        from_id: str = packet.get(_PACKET_KEY_FROM_ID, "")
        return from_id.startswith(f"!{_WEB_USER_NODE_ID_BYTE}")

    @staticmethod
    def is_direct_message(packet: dict, bot_node_id: str) -> bool:
        """Returns True if the packet is a direct message addressed to the bot.

        A packet is a DM when its destination node ID matches the bot's own node
        ID. Channel broadcasts carry '"^all"' as the destination and are not DMs.

        Args:
            packet: The raw Meshtastic packet dict to inspect.
            bot_node_id: The bot's own node ID string (e.g. '!deadbeef').

        Returns:
            True if the packet was sent directly to the bot, False otherwise.
        """
        to_id: str = packet.get(_PACKET_KEY_TO_ID, _BROADCAST_ID)
        return to_id == bot_node_id
    
    @staticmethod
    def get_message_destination_id(packet: dict, sender: str, bot_node_id: str) -> str | None:
        """Extracts the destination node ID from a Meshtastic packet.

        Args:
            packet: The raw Meshtastic packet dict.
            sender: The node ID string of the message sender.
            bot_node_id: The bot's own node ID string (e.g. '!deadbeef').

        Returns:
            The destination node ID if the packet is a direct message, None otherwise.
        """
        return (sender if MeshtasticHelper.is_direct_message(packet, bot_node_id) else None)

    @staticmethod
    def send_text_message(iface: MeshInterface, channelIndex: int, message: str, packet: dict, destinationId: str | None = None, consoleMsg: str | None = None, chat_history: Optional[ChatHistory] = None, chat_sender: str = "") -> mesh_pb2.MeshPacket | None:
        """Sends a text message reply on the specified channel, or as a DM.

        Prints consoleMsg to the console if provided, then sends the message text.
        If the originating packet contains a message ID, the reply is linked to
        it via replyId so the recipient's device can thread the conversation.
        When chat_history is supplied and destinationId is None (a channel send),
        the message is appended to the chat log using chat_sender as the author.

        Args:
            iface: The active MeshInterface connection to send the message on.
            channelIndex: The zero-based index of the channel to send on.
            message: The text content to broadcast on the channel.
            packet: The raw Meshtastic packet dict of the message being replied to.
            destinationId: When provided, sends a direct message to this node ID
                           instead of broadcasting on the channel.
            consoleMsg: Optional text to print to the console before sending.
            chat_history: When provided and the send is a channel broadcast
                          (destinationId is None), the message is appended to the log.
            chat_sender: The sender label written to the chat log. Defaults to an
                         empty string; callers should pass the bot label constant.
        """
        result: mesh_pb2.MeshPacket | None = None
        if consoleMsg:
            print(consoleMsg)
        message_id: int | None = MeshtasticHelper.get_message_id(packet)
        if destinationId is not None:
            if message_id is not None:
                result = iface.sendText(message, destinationId=destinationId, wantAck=True, replyId=message_id)
            else:
                result = iface.sendText(message, destinationId=destinationId, wantAck=True)
        elif message_id is not None:
            result = iface.sendText(message, channelIndex=channelIndex, replyId=message_id)
        else:
            result = iface.sendText(message, channelIndex=channelIndex)
        if destinationId is None and chat_history is not None:
            chat_history.append(chat_sender, message)
            
        return result

    # endregion Public Functions
