from __future__ import annotations
from common.constants import (
    _MSG_STOP_APPLICATION,
    _PACKET_TYPE_DM,
    _MSG_DM_MONITORING_STARTED,
    _MSG_DM_MONITOR_STOPPED,
    _MSG_DM_TEXT_RECEIVED,
    _MSG_DM_DATA_RECEIVED,
    _MSG_DM_UNKNOWN_COMMAND,
)
from common.meshtastic_helper import MeshtasticHelper
from messaging.monitors.base_monitor import BaseMonitor
from meshtastic import mesh_pb2


class DMMonitor(BaseMonitor):
    """Monitors incoming direct messages addressed to this node and dispatches commands.

    Filters to packets whose destination node ID matches the local node. Recognised
    bot commands are routed to the registered command handlers. Replies are sent as
    direct messages back to the sender.
    """

    # region Protected Properties
    @property
    def _reply_as_dm(self) -> bool:
        return True

    @property
    def _message_type(self) -> str:
        return _PACKET_TYPE_DM

    @property
    def _msg_text_received(self) -> str:
        return _MSG_DM_TEXT_RECEIVED

    @property
    def _msg_data_received(self) -> str:
        return _MSG_DM_DATA_RECEIVED

    @property
    def _msg_started(self) -> str:
        return f"{_MSG_DM_MONITORING_STARTED}{_MSG_STOP_APPLICATION}"

    @property
    def _msg_stopped(self) -> str:
        return _MSG_DM_MONITOR_STOPPED
    # endregion Protected Properties

    # region Protected Functions
    def _on_unrecognized_command(self, sender: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Sends a DM to the sender explaining that only commands are supported."""
        return MeshtasticHelper.send_text_message(
            iface=self._iface,
            channelIndex=self._channel.index,
            message=_MSG_DM_UNKNOWN_COMMAND,
            packet=packet,
            destinationId=sender,
        )
    # endregion Protected Functions
