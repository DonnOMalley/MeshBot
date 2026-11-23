from __future__ import annotations
from datetime import datetime
from pubsub import pub
from common.constants import (
    _EVENT_RECEIVE_ANY,
    _LATITUDE_SCALE,
    _LONGITUDE_SCALE,
    _MSG_NODE_MONITOR_STARTED,
    _MSG_NODE_MONITOR_STOPPED,
    _MSG_NODE_INFO_RECEIVED,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_FROM_NUM,
    _PACKET_KEY_HOP_LIMIT,
    _PACKET_KEY_HOP_START,
    _PACKET_KEY_LATITUDE_I,
    _PACKET_KEY_LONGITUDE_I,
    _PACKET_KEY_POSITION,
    _PACKET_KEY_RX_TIME,
    _PACKET_KEY_USER,
    _USER_KEY_HW_MODEL,
    _USER_KEY_ID,
    _USER_KEY_LONG_NAME,
    _USER_KEY_ROLE,
    _USER_KEY_SHORT_NAME,
)
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from meshtastic.mesh_interface import MeshInterface


class NodeMonitor:
    """Keeps the node database current from every packet heard on the mesh.

    Subscribes to the parent ``meshtastic.receive`` pubsub topic, which receives
    every packet type (text, position, telemetry, node info, routing, encrypted
    packets on other channels, ...). Any packet from a node proves it is alive,
    so its ``last_seen`` is refreshed; node info packets also update its identity
    and position packets also update its location.
    """

    # region Protected Variables
    _iface: MeshInterface
    _db: NodeDatabase
    _running: bool
    _verbose: bool
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        iface: MeshInterface,
        db: NodeDatabase,
        verbose: bool = False,
    ) -> None:
        """Initialises the monitor with an active interface and node database.

        Args:
            iface: The active MeshInterface connection to the Meshtastic device.
            db: The :class:`~common.node_database.NodeDatabase` instance to update
                when packets are received.
            verbose: When True, prints a console line for each node info packet
                     received. Defaults to False.
        """
        self._iface = iface
        self._db = db
        self._running = False
        self._verbose = verbose
    # endregion Constructor

    # region Protected Functions
    @staticmethod
    def _get_hops_away(packet: dict) -> int | None:
        """Returns hopStart - hopLimit when the packet carries both, else None."""
        result: int | None = None
        hop_start: int | None = packet.get(_PACKET_KEY_HOP_START)
        hop_limit: int | None = packet.get(_PACKET_KEY_HOP_LIMIT)
        if hop_start is not None and hop_limit is not None and hop_start >= hop_limit:
            result = hop_start - hop_limit
        return result

    def _on_packet(self, packet: dict, interface: MeshInterface) -> None:
        """Handles any received packet and refreshes the sender in the database.

        Args:
            packet: The raw Meshtastic packet dictionary.
            interface: The MeshInterface that received the packet (unused).
        """
        if packet.get(_PACKET_KEY_FROM_NUM):
            sender_node_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
            decoded: dict = packet.get(_PACKET_KEY_DECODED, {}) or {}
            user: dict = decoded.get(_PACKET_KEY_USER, {}) or {}
            position: dict = decoded.get(_PACKET_KEY_POSITION, {}) or {}
            lat_i: int | None = position.get(_PACKET_KEY_LATITUDE_I)
            lon_i: int | None = position.get(_PACKET_KEY_LONGITUDE_I)
            heard_at: datetime | None = NodeDatabase.epoch_to_datetime(packet.get(_PACKET_KEY_RX_TIME))

            if user and self._verbose:
                print(_MSG_NODE_INFO_RECEIVED.format(sender=sender_node_id))

            # A node info packet names the node; otherwise identify it by sender.
            node_id: str = user.get(_USER_KEY_ID, "") or sender_node_id
            if node_id:
                self._db.upsert(
                    node_id,
                    long_name=user.get(_USER_KEY_LONG_NAME, "") or "",
                    short_name=user.get(_USER_KEY_SHORT_NAME, "") or "",
                    role=user.get(_USER_KEY_ROLE, "") or "",
                    hardware_model=user.get(_USER_KEY_HW_MODEL, "") or "",
                    # A position of exactly 0,0 means "no fix", not a real location.
                    latitude=lat_i * _LATITUDE_SCALE if lat_i else None,
                    longitude=lon_i * _LONGITUDE_SCALE if lon_i else None,
                    hops_away=NodeMonitor._get_hops_away(packet),
                    heard_at=heard_at,
                )
    # endregion Protected Functions

    # region Public Functions
    def start(self) -> None:
        """Begins monitoring all received packets."""
        self._running = True
        pub.subscribe(self._on_packet, _EVENT_RECEIVE_ANY)
        if self._verbose:
            print(_MSG_NODE_MONITOR_STARTED)

    def stop(self) -> None:
        """Stops the monitor and unsubscribes from packet events."""
        pub.unsubscribe(self._on_packet, _EVENT_RECEIVE_ANY)
        self._running = False
        if self._verbose:
            print(_MSG_NODE_MONITOR_STOPPED)
    # endregion Public Functions
