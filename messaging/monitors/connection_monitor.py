from __future__ import annotations
import threading
from pubsub import pub
from meshtastic.mesh_interface import MeshInterface
from common.constants import (
    _EVENT_CONNECTION_LOST,
    _MSG_CONNECTION_MONITOR_STARTED,
    _MSG_CONNECTION_MONITOR_STOPPED,
)


class ConnectionMonitor:
    """Monitors the Meshtastic serial connection and signals when it is lost.

    Subscribes to the ``meshtastic.connection.lost`` pubsub event and sets an
    internal :class:`threading.Event` when the connection drops. The main loop
    waits on this event to detect disconnects and trigger a reconnect sequence.
    """

    # region Protected Variables
    _disconnect_event: threading.Event
    _running: bool
    _verbose: bool
    # endregion Protected Variables

    # region Constructor
    def __init__(self, verbose: bool = False) -> None:
        """Initialises the connection monitor.

        Args:
            verbose: When True, prints a console line when the monitor starts and stops.
        """
        self._disconnect_event = threading.Event()
        self._running = False
        self._verbose = verbose
    # endregion Constructor

    # region Protected Functions
    def _on_connection_lost(self, interface: MeshInterface) -> None:
        """Handles the meshtastic.connection.lost pubsub event.

        Sets the internal disconnect event so the outer reconnect loop can react.

        Args:
            interface: The MeshInterface that lost its connection (unused).
        """
        self._disconnect_event.set()
    # endregion Protected Functions

    # region Public Functions
    def wait(self, timeout: float) -> bool:
        """Waits up to ``timeout`` seconds for a disconnect event to be signalled.

        Args:
            timeout: Maximum number of seconds to wait.

        Returns:
            True if a disconnect was signalled within the timeout, False otherwise.
        """
        return self._disconnect_event.wait(timeout=timeout)

    def acknowledge(self) -> None:
        """Clears the disconnect signal once the main loop has handled it."""
        self._disconnect_event.clear()

    def start(self) -> None:
        """Begins monitoring for connection-lost events."""
        self._running = True
        pub.subscribe(self._on_connection_lost, _EVENT_CONNECTION_LOST)
        if self._verbose:
            print(_MSG_CONNECTION_MONITOR_STARTED)

    def stop(self) -> None:
        """Stops monitoring for connection-lost events."""
        pub.unsubscribe(self._on_connection_lost, _EVENT_CONNECTION_LOST)
        self._running = False
        if self._verbose:
            print(_MSG_CONNECTION_MONITOR_STOPPED)
    # endregion Public Functions
