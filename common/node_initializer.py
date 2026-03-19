from __future__ import annotations

import copy

from meshtastic import config_pb2
from meshtastic.mesh_interface import MeshInterface

from common.constants import (
    _MSG_NODE_INIT_APPLYING,
    _MSG_NODE_INIT_APPLIED,
    _MSG_NODE_INIT_RESTORING,
    _MSG_NODE_INIT_RESTORED,
    _MSG_NODE_INIT_SET,
    _MSG_NODE_INIT_NO_CHANGE,
    _MSG_NODE_INIT_VERIFY_OK,
    _MSG_NODE_INIT_VERIFY_WARN,
    _NODE_INIT_HOP_LIMIT,
    _NODE_INIT_NODE_INFO_BROADCAST_SECS,
    _NODE_INIT_REBROADCAST_MODE,
    _NODE_INIT_ROLE,
    _NODE_INIT_EXPECTED_CONFIG_OK_TO_MQTT,
    _NODE_INIT_EXPECTED_IGNORE_MQTT,
    _NODE_INIT_EXPECTED_MODEM_PRESET,
    _NODE_INIT_EXPECTED_REGION,
    _NODE_INIT_EXPECTED_TX_ENABLED,
    _NODE_INIT_EXPECTED_TX_POWER,
    _NODE_INIT_EXPECTED_USE_PRESET,
)


##THESE NEED MOVED TO THE CONSTANTS

# Protobuf-typed enum values used for field assignment.
# The int constants in constants.py carry the same numeric values and are used
# for comparison and logging; these are used only for the type-safe write.
_ROLE_ENUM_CLIENT = config_pb2.Config.DeviceConfig.Role.CLIENT
_REBROADCAST_ENUM_ALL = config_pb2.Config.DeviceConfig.RebroadcastMode.ALL
_ROLE_ENUM_CLIENT_MUTE = config_pb2.Config.DeviceConfig.Role.CLIENT_MUTE
_REBROADCAST_ENUM_NONE = config_pb2.Config.DeviceConfig.RebroadcastMode.NONE

_ROLE_ENUM = _ROLE_ENUM_CLIENT_MUTE #_ROLE_ENUM_CLIENT
_REBROADCAST_ENUM = _REBROADCAST_ENUM_NONE #_REBROADCAST_ENUM_ALL


class NodeInitializer:
    """Applies required bot configuration to the local Meshtastic node on startup and restores the original on shutdown.

    On construction the current LoRa and device configuration sections are
    snapshotted. Call ``apply()`` immediately after connecting to push the
    required settings to the device. Call ``restore()`` on a clean shutdown
    to return the device to its original state.

    Required settings applied by ``apply()``:
      - ``lora.hop_limit`` → 7
      - ``device.node_info_broadcast_secs`` → 21600 (6 hours)
      - ``device.role`` → CLIENT (0)
      - ``device.rebroadcast_mode`` → ALL (0)

    Expected settings verified (warnings logged on mismatch):
      - ``lora.region`` → US (1)
      - ``lora.use_preset`` → True
      - ``lora.modem_preset`` → MEDIUM_FAST (4)
      - ``lora.tx_enabled`` → True
      - ``lora.tx_power`` → 30 dBm
      - ``lora.ignore_mqtt`` → True
      - ``lora.config_ok_to_mqtt`` → False
    """

    # region Private Variables
    _iface: MeshInterface
    _original_lora: config_pb2.Config.LoRaConfig
    _original_device: config_pb2.Config.DeviceConfig
    # endregion Private Variables

    # region Constructor
    def __init__(self, iface: MeshInterface) -> None:
        """Snapshots the current node configuration and stores the interface for later use.

        Args:
            iface: The active MeshInterface connection to the local node.
        """
        self._iface = iface
        self._original_lora = copy.deepcopy(iface.localNode.localConfig.lora)
        self._original_device = copy.deepcopy(iface.localNode.localConfig.device)
    # endregion Constructor

    # region Private Functions
    def _apply_lora_settings(self) -> bool:
        """Writes required LoRa configuration values to the local node if they differ from the required values.

        Returns:
            True if at least one value was changed and writeConfig was called.
        """
        lora = self._iface.localNode.localConfig.lora
        dirty: bool = False

        if lora.hop_limit != _NODE_INIT_HOP_LIMIT:
            lora.hop_limit = _NODE_INIT_HOP_LIMIT
            print(_MSG_NODE_INIT_SET.format(field="hop_limit", value=_NODE_INIT_HOP_LIMIT))
            dirty = True
        else:
            print(_MSG_NODE_INIT_NO_CHANGE.format(field="hop_limit", value=_NODE_INIT_HOP_LIMIT))

        if dirty:
            self._iface.localNode.writeConfig("lora")
        return dirty

    def _apply_device_settings(self) -> bool:
        """Writes required device configuration values to the local node if they differ from the required values.

        Returns:
            True if at least one value was changed and writeConfig was called.
        """
        device = self._iface.localNode.localConfig.device
        dirty: bool = False

        if device.node_info_broadcast_secs != _NODE_INIT_NODE_INFO_BROADCAST_SECS:
            device.node_info_broadcast_secs = _NODE_INIT_NODE_INFO_BROADCAST_SECS
            print(_MSG_NODE_INIT_SET.format(field="node_info_broadcast_secs", value=_NODE_INIT_NODE_INFO_BROADCAST_SECS))
            dirty = True
        else:
            print(_MSG_NODE_INIT_NO_CHANGE.format(field="node_info_broadcast_secs", value=_NODE_INIT_NODE_INFO_BROADCAST_SECS))

        if device.role != _NODE_INIT_ROLE:
            device.role = _ROLE_ENUM
            print(_MSG_NODE_INIT_SET.format(field="role", value=_NODE_INIT_ROLE))
            dirty = True
        else:
            print(_MSG_NODE_INIT_NO_CHANGE.format(field="role", value=_NODE_INIT_ROLE))

        if device.rebroadcast_mode != _NODE_INIT_REBROADCAST_MODE:
            device.rebroadcast_mode = _REBROADCAST_ENUM
            print(_MSG_NODE_INIT_SET.format(field="rebroadcast_mode", value=_NODE_INIT_REBROADCAST_MODE))
            dirty = True
        else:
            print(_MSG_NODE_INIT_NO_CHANGE.format(field="rebroadcast_mode", value=_NODE_INIT_REBROADCAST_MODE))

        if dirty:
            self._iface.localNode.writeConfig("device")
        return dirty

    def _verify_settings(self) -> None:
        """Checks expected LoRa settings against known-good values and logs a warning for each mismatch."""
        lora = self._iface.localNode.localConfig.lora
        checks: list[tuple[str, object, object]] = [
            ("region (US=1)",                  lora.region,             _NODE_INIT_EXPECTED_REGION),
            ("use_preset",                     lora.use_preset,         _NODE_INIT_EXPECTED_USE_PRESET),
            ("modem_preset (MEDIUM_FAST=4)",   lora.modem_preset,       _NODE_INIT_EXPECTED_MODEM_PRESET),
            ("tx_enabled",                     lora.tx_enabled,         _NODE_INIT_EXPECTED_TX_ENABLED),
            ("tx_power (dBm)",                 lora.tx_power,           _NODE_INIT_EXPECTED_TX_POWER),
            ("ignore_mqtt",                    lora.ignore_mqtt,        _NODE_INIT_EXPECTED_IGNORE_MQTT),
            ("config_ok_to_mqtt",              lora.config_ok_to_mqtt,  _NODE_INIT_EXPECTED_CONFIG_OK_TO_MQTT),
        ]
        for field, actual, expected in checks:
            if actual == expected:
                print(_MSG_NODE_INIT_VERIFY_OK.format(field=field, value=actual))
            else:
                print(_MSG_NODE_INIT_VERIFY_WARN.format(field=field, expected=expected, actual=actual))
    # endregion Private Functions

    # region Public Functions      
    
    def apply(self) -> bool:
        """Applies required configuration settings to the local node if they differ from the required values.

        Writes both LoRa and device configuration sections back to the device if changes are made.
        Call this on startup immediately after connecting to the node.

        Logs each change made, or if no change was needed for a field. Also logs a verification
        of expected values for all relevant LoRa settings, which may differ from the required
        values but are still expected to be correct for the bot's operation.
        """
        print(_MSG_NODE_INIT_APPLYING)
        lora_changed: bool = self._apply_lora_settings()
        device_changed: bool = self._apply_device_settings()
        if lora_changed or device_changed:
            print(_MSG_NODE_INIT_APPLIED)
            self._verify_settings()
        else:
            print(_MSG_NODE_INIT_VERIFY_OK.format(field="all checked fields", value="already correct"))  
        return lora_changed or device_changed

    def restore(self) -> None:
        """Restores the original node configuration that was snapshotted on construction.

        Writes both LoRa and device configuration sections back to the device.
        Call this on clean shutdown to return the device to its pre-startup state.
        """
        print(_MSG_NODE_INIT_RESTORING)
        self._iface.localNode.localConfig.device.CopyFrom(self._original_device)
        self._iface.localNode.writeConfig("device")
        self._iface.localNode.localConfig.lora.CopyFrom(self._original_lora)
        self._iface.localNode.writeConfig("lora")
        print(_MSG_NODE_INIT_RESTORED)

    def update_iface(self, new_iface: MeshInterface) -> None:
        """Replaces the stored interface reference without affecting the saved configuration snapshot.

        Call this after the device has restarted and a new serial connection has been
        established. The original configuration snapshot taken at construction is
        preserved so that ``restore()`` can still return the device to its pre-startup state.

        Args:
            new_iface: The new active MeshInterface connection to the restarted node.
        """
        self._iface = new_iface
    # endregion Public Functions
