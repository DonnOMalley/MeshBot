from __future__ import annotations
from typing import Optional
from pubsub import pub
from common.constants import (
    _EVENT_NODE_INFO,
    _MSG_NODE_MONITOR_STARTED,
    _MSG_NODE_MONITOR_STOPPED,
    _MSG_NODE_INFO_RECEIVED,
)
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from meshtastic.mesh_interface import MeshInterface


class NodeMonitor:
    """Monitors the mesh for node info announcements and keeps the node database current.

    Subscribes to the ``meshtastic.receive.user`` pubsub event, which is fired
    whenever a remote node broadcasts its identity (NodeInfo packet). Each received
    announcement is upserted into the supplied :class:`~common.node_database.NodeDatabase`.
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
                when node info packets are received.
            verbose: When True, prints a console line for each node info packet
                     received. Defaults to False.
        """
        self._iface = iface
        self._db = db
        self._running = False
        self._verbose = verbose
    # endregion Constructor

    # region Protected Functions
    def _on_node_info(self, packet: dict, interface: MeshInterface) -> None:
        """Handles an incoming node info packet and upserts the sender into the database.

        Args:
            packet: The raw Meshtastic packet dictionary for the node info message.
            interface: The MeshInterface that received the packet (unused).
        """
        sender_node_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        if self._verbose:
            print(_MSG_NODE_INFO_RECEIVED.format(sender=sender_node_id))

        decoded: dict = packet.get("decoded", {})
        user: dict = decoded.get("user", {})
        long_name: str = user.get("longName", "")
        short_name: str = user.get("shortName", "")
        node_id: str = user.get("id", "") or sender_node_id
        role: str = user.get("role", "") or ""
        hardware_model: str = user.get("hwModel", "") or ""
        hops_away: Optional[int] = packet.get("hopsAway")

        if node_id:
            self._db.upsert(node_id, long_name, short_name, role, hardware_model, hops_away=hops_away)
    # endregion Protected Functions

    # region Public Functions
    def start(self) -> None:
        """Begins monitoring for node info announcements."""
        self._running = True
        pub.subscribe(self._on_node_info, _EVENT_NODE_INFO)
        if self._verbose:
            print(_MSG_NODE_MONITOR_STARTED)

    def stop(self) -> None:
        """Stops the monitor and unsubscribes from node info events."""
        pub.unsubscribe(self._on_node_info, _EVENT_NODE_INFO)
        self._running = False
        if self._verbose:
            print(_MSG_NODE_MONITOR_STOPPED)
    # endregion Public Functions
