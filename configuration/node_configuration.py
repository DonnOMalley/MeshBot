from __future__ import annotations
from typing import Optional
from common.meshtastic_helper import MeshtasticHelper, NodeInfo
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface

class NodeConfiguration:
    """Reads and stores configuration data from a live Meshtastic interface.

    Populates channel, local node identity, and peer node information from the
    device on construction (when an interface is supplied) or on an explicit call
    to init_configuration().
    """

    # region Protected Variables
    _local_long_name: str
    _local_short_name: str
    _local_node_id: str
    # endregion Protected Variables

    # region Public Variables
    channels: list[channel_pb2.Channel]
    # nodes: dict[str, NodeInfo]
    # endregion Public Variables

    # region Public Properties
    @property
    def long_name(self) -> str:
        """The human-readable long name of the local Meshtastic node."""
        return self._local_long_name

    @property
    def short_name(self) -> str:
        """The abbreviated short name of the local Meshtastic node."""
        return self._local_short_name

    @property
    def node_id(self) -> str:
        """The unique node identifier string of the local Meshtastic node (e.g. '!deadbeef')."""
        return self._local_node_id
    # endregion Public Properties

    # region Constructor
    def __init__(self, iface: Optional[MeshInterface] = None) -> None:
        """Initialises the configuration, optionally populating from a live interface.

        Args:
            iface: An active MeshInterface connection. When provided,
                   init_configuration() is called automatically.
        """
        self.channels = []
        self._local_long_name = ""
        self._local_short_name = ""
        self._local_node_id = ""
        # self.nodes = {}
        if iface is not None:
            self.init_configuration(iface)
    # endregion Constructor

    # region Public Functions
    def init_configuration(self, iface: MeshInterface) -> None:
        """Populates all configuration data from the supplied Meshtastic interface.

        Args:
            iface: An active MeshInterface connection to read configuration from.
        """
        self.channels = MeshtasticHelper.get_channels(iface)
        self._local_long_name, self._local_short_name, self._local_node_id = MeshtasticHelper.get_local_node_info(iface)
        # self.nodes = MeshtasticHelper.get_node_list(iface)s
    # endregion Public Functions