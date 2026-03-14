from __future__ import annotations
from common.constants import (
    _MSG_STOP_APPLICATION,
    _PACKET_TYPE_CHANNEL,
    _MSG_CHANNEL_MONITORING_STARTED,
    _MSG_CHANNEL_MONITOR_STOPPED,
    _MSG_CHANNEL_TEXT_RECEIVED,
    _MSG_CHANNEL_DATA_RECEIVED,
)
from messaging.monitors.base_monitor import BaseMonitor


class ChannelMonitor(BaseMonitor):
    """Monitors a single Meshtastic channel and dispatches incoming text commands."""

    # region Protected Properties
    @property
    def _message_type(self) -> str:
        return _PACKET_TYPE_CHANNEL

    @property
    def _msg_text_received(self) -> str:
        return _MSG_CHANNEL_TEXT_RECEIVED

    @property
    def _msg_data_received(self) -> str:
        return _MSG_CHANNEL_DATA_RECEIVED

    @property
    def _msg_started(self) -> str:
        return f"{_MSG_CHANNEL_MONITORING_STARTED}{_MSG_STOP_APPLICATION}"

    @property
    def _msg_stopped(self) -> str:
        return _MSG_CHANNEL_MONITOR_STOPPED
    # endregion Protected Properties