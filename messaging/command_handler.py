from __future__ import annotations
from typing import Protocol, runtime_checkable
from meshtastic import mesh_pb2


@runtime_checkable
class CommandHandler(Protocol):
    """Protocol defining the signature for all bot command handler functions.

    Implement this interface to register a custom command with the bot:

    Example::

        def my_command(sender: str, params: str, packet: dict) -> None:
            print(f"Received from {sender} with params: {params}")

        register = CommandRegister(iface, config, channel,
                                   user_defined_commands={"mycommand": my_command})
    """

    # region Public Functions
    def __call__(self, sender: str, params: str, packet: dict) -> mesh_pb2.MeshPacket | None:
        """Handle an incoming bot command.

        Args:
            sender: The node ID string of the message sender.
            params: Any text that followed the command name in the message.
            packet: The full raw Meshtastic packet dictionary.
        """
        ...
    # endregion Public Functions
