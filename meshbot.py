import time

from common.app_arguments import AppArguments
from common.constants import (
    _STARTUP_MESSAGE,
    _VERBOSE_ARGS_MESSAGE,
    _NODE_IDENTITY_MESSAGE,
    _CHANNEL_PROMPT,
    _MSG_NO_VALID_INDEX,
    _MSG_CHANNEL_NOT_FOUND_INDEX,
    _MSG_CHANNEL_NOT_FOUND_NAME,
    _MSG_DISCONNECTED,
    _MSG_NO_SERIAL_DEVICE,
    _MSG_SERIAL_CONNECTION_ERROR,
    _MONITOR_POLL_INTERVAL,
    _CHECKIN_INTERVAL,
    _MSG_BOT_STARTED,
    _MSG_STOP_APPLICATION,
)
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from common.chat_history import ChatHistory
from configuration.node_configuration import NodeConfiguration
from messaging.bot_lifecycle_messenger import BotLifecycleMessenger
from messaging.monitors.channel_monitor import ChannelMonitor
from messaging.monitors.dm_monitor import DMMonitor
from messaging.monitors.node_monitor import NodeMonitor
from commands.user_commands import UserCommands
from web.web_server import WebServer
import meshtastic.serial_interface
from meshtastic import channel_pb2


def _resolve_channel(channel_name: str | None, config: NodeConfiguration) -> channel_pb2.Channel | None:
    """Resolves the target channel from command-line arguments or interactive user input.

    If --Channel was provided, looks up the channel by name directly. Otherwise, lists
    all available channels and prompts the user to enter a channel index.

    Args:
        channel_name: Optional name of the channel to use.
        config: Initialised node configuration holding the available channel list.

    Returns:
        The resolved Channel object, or None if the channel could not be found or the
        user did not supply a valid index.
    """
    result: channel_pb2.Channel | None = None
    err_msg: str | None = None

    if channel_name is not None:
        result = MeshtasticHelper.get_channel_by_name(config.channels, channel_name)
        if result is None:
            err_msg = _MSG_CHANNEL_NOT_FOUND_NAME.format(name=channel_name)
    else:
        MeshtasticHelper.list_channels(config.channels)
        channel_index_raw_input: str = input(_CHANNEL_PROMPT).strip()
        if channel_index_raw_input.isdigit():
            channel_index: int = int(channel_index_raw_input)
            result = MeshtasticHelper.get_channel_by_index(config.channels, channel_index)
            if result is None:
                err_msg = _MSG_CHANNEL_NOT_FOUND_INDEX.format(index=channel_index)
        else:
            err_msg = _MSG_NO_VALID_INDEX

    if err_msg is not None:
        print(err_msg)

    return result


def main() -> None:
    """Entry point for the DAMNBot application.

    Parses command-line arguments, connects to the Meshtastic device via serial,
    resolves the target channel, sends the welcome message, starts the channel
    monitor, and sends the signoff message on exit.
    """
    args: AppArguments
    config: NodeConfiguration
    current_channel: channel_pb2.Channel | None
    last_checkin_time: float = 0.0
    channel_monitor: ChannelMonitor
    dm_monitor: DMMonitor
    node_monitor: NodeMonitor
    bot_lifecycle_messenger: BotLifecycleMessenger
    web_server: WebServer

    args = AppArguments()
    args.parse()

    if args.verbose:
        print(_VERBOSE_ARGS_MESSAGE.format(
            bot_name=args.bot_name,
            channel=args.channel or "(prompt)",
            case_sensitive=args.case_sensitive,
            exclude_ootb=args.exclude_ootb,
            node_retention_days=args.node_retention_days,
            encrypted=args.encryption_key is not None,
            verbose=args.verbose,
        ))
        print(_STARTUP_MESSAGE)

    try:
        iface = meshtastic.serial_interface.SerialInterface()
    except Exception as e:
        print(_MSG_SERIAL_CONNECTION_ERROR.format(error=e))
        iface = None

    if iface is None or iface.devPath is None:
        print(_MSG_NO_SERIAL_DEVICE)
    else:

        with iface:
            config = NodeConfiguration(iface)
            if args.verbose:
                print(_NODE_IDENTITY_MESSAGE.format(long_name=config.long_name, short_name=config.short_name, node_id=config.node_id))

            node_db = NodeDatabase(
                retention_days=args.node_retention_days,
                passphrase=args.encryption_key,
                verbose=args.verbose,
            )
            node_db.load_from_interface(iface)
            node_db.prune()

            # Use channel from command line arguments or prompt user to select channel from list of available channels. Exit if no valid channel is selected.
            current_channel = _resolve_channel(args.channel, config)

            if current_channel is not None:
                bot_lifecycle_messenger = BotLifecycleMessenger(iface, config, bot_name=args.bot_name, verbose=args.verbose)
                bot_lifecycle_messenger.send_welcome_message(current_channel)

                chat_history = ChatHistory(channel_name=current_channel.settings.name or "primary", passphrase=args.encryption_key)

                channel_monitor = ChannelMonitor(iface=iface,
                                                config=config,
                                                channel=current_channel,
                                                case_sensitive=args.case_sensitive,
                                                exclude_ootb=args.exclude_ootb,
                                                user_defined_commands=UserCommands(iface, config, current_channel, verbose=args.verbose).get_commands(),
                                                verbose=args.verbose,
                                                chat_history=chat_history,
                                                passphrase=args.encryption_key)
                dm_monitor = DMMonitor(iface=iface,
                                                config=config,
                                                channel=current_channel,
                                                case_sensitive=args.case_sensitive,
                                                exclude_ootb=args.exclude_ootb,
                                                user_defined_commands=UserCommands(iface, config, current_channel, verbose=args.verbose).get_commands(),
                                                verbose=args.verbose,
                                                passphrase=args.encryption_key)
                node_monitor = NodeMonitor(iface=iface, db=node_db, verbose=args.verbose)

                channel_monitor.start()
                dm_monitor.start()
                node_monitor.start()

                web_server = WebServer(
                    node_db=node_db,
                    iface=iface,
                    channel=current_channel,
                    passphrase=args.encryption_key,
                )
                web_server.start()

                print(_MSG_BOT_STARTED.format(bot_name=args.bot_name, channel_name=(current_channel.settings.name or "primary")))
                print(_MSG_STOP_APPLICATION)

                last_checkin_time = time.time()
                try:
                    while True:
                        time.sleep(_MONITOR_POLL_INTERVAL)
                        current_time: float = time.time()
                        if current_time - last_checkin_time >= _CHECKIN_INTERVAL:
                            bot_lifecycle_messenger.send_checkin_message(current_channel)
                            last_checkin_time = current_time
                except KeyboardInterrupt:
                    channel_monitor.stop()
                    dm_monitor.stop()
                    node_monitor.stop()
                bot_lifecycle_messenger.send_signoff_message(current_channel)

        print(_MSG_DISCONNECTED)


if __name__ == "__main__":
    main()
