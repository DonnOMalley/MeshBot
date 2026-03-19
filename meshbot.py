import time

from common.app_arguments import AppArguments
from common.constants import (
    _MSG_NODE_INIT_APPLYING,
    _MSG_NODE_INIT_APPLIED,
    CHANNEL_NAME_PRIMARY,
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
    _MSG_CHANNEL_MONITOR_STOPPING,
    _MSG_DM_MONITOR_STOPPING,
    _MSG_NODE_MONITOR_STOPPING,
    _MSG_CONNECTION_MONITOR_STOPPING,
    _WEB_DASHBOARD_URL,
    _RECONNECT_DELAY_SECONDS,
    _MSG_RECONNECT_ATTEMPT,
    _MSG_RECONNECT_SUCCESS,
    _MSG_RECONNECT_FAILED,
    _MSG_NODE_INIT_REBOOT_WAIT,
    _MSG_NODE_INIT_RECONNECT_SUCCESS,
    _NODE_INIT_REBOOT_INITIAL_WAIT,
)
from common.console_logger import ConsoleLogger
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from common.node_initializer import NodeInitializer
from common.chat_history import ChatHistory
from common.today_in_history_api import TodayInHistoryApi
from common.zen_quotes_api import ZenQuotesApi
from configuration.node_configuration import NodeConfiguration
from messaging.bot_broadcaster import BotBroadcaster
from messaging.monitors.channel_monitor import ChannelMonitor
from messaging.monitors.connection_monitor import ConnectionMonitor
from messaging.monitors.dm_monitor import DMMonitor
from messaging.monitors.node_monitor import NodeMonitor
from commands.user_commands import UserCommands
from web.tile_cache import TileCache
from web.web_server import WebServer
import meshtastic.serial_interface
from meshtastic import channel_pb2

def _build_primary_channel_monitor(
    iface: meshtastic.serial_interface.SerialInterface,
    config: NodeConfiguration,
    channel: channel_pb2.Channel,
    args: AppArguments,
    chat_history: ChatHistory,):
    """Constructs a ChannelMonitor bound to the primary channel for the given interface.

    Args:
        iface: The active serial interface to the Meshtastic device.
        config: Node configuration for the connected device.
        channel: The channel to monitor for incoming messages.
        args: Parsed application arguments controlling monitor behaviour.
        chat_history: Chat history instance to which received messages are appended.
        web_url: Full URL of the web dashboard passed through to the ``!web`` command.

    Returns:
        A fully configured ChannelMonitor ready to be started.
    """
    monitor: ChannelMonitor = ChannelMonitor(
        iface=iface,
        config=config,
        channel=channel,
        case_sensitive=args.case_sensitive,
        exclude_ootb=True,
        user_defined_commands=None,
        verbose=args.verbose,
        chat_history=chat_history,
        passphrase=args.encryption_key,
    )
    return monitor

def _build_channel_monitor(
    iface: meshtastic.serial_interface.SerialInterface,
    config: NodeConfiguration,
    channel: channel_pb2.Channel,
    args: AppArguments,
    chat_history: ChatHistory,
    web_url: str = "",
) -> ChannelMonitor:
    """Constructs a ChannelMonitor bound to the given interface and channel.

    Args:
        iface: The active serial interface to the Meshtastic device.
        config: Node configuration for the connected device.
        channel: The channel to monitor for incoming messages.
        args: Parsed application arguments controlling monitor behaviour.
        chat_history: Chat history instance to which received messages are appended.
        web_url: Full URL of the web dashboard passed through to the ``!web`` command.

    Returns:
        A fully configured ChannelMonitor ready to be started.
    """
    monitor: ChannelMonitor = ChannelMonitor(
        iface=iface,
        config=config,
        channel=channel,
        case_sensitive=args.case_sensitive,
        exclude_ootb=args.exclude_ootb,
        user_defined_commands=UserCommands(iface, config, channel, chat_history=chat_history, verbose=args.verbose, range_test_requests=args.range_test_requests, range_test_delay_minutes=args.range_test_delay_minutes).get_commands(),
        verbose=args.verbose,
        chat_history=chat_history,
        passphrase=args.encryption_key,
        web_url=web_url,
    )
    return monitor

def _build_dm_monitor(
    iface: meshtastic.serial_interface.SerialInterface,
    config: NodeConfiguration,
    channel: channel_pb2.Channel,
    args: AppArguments,
    web_url: str = "",
) -> DMMonitor:
    """Constructs a DMMonitor bound to the given interface and channel.

    Args:
        iface: The active serial interface to the Meshtastic device.
        config: Node configuration for the connected device.
        channel: The channel used for sending DM replies.
        args: Parsed application arguments controlling monitor behaviour.
        web_url: Full URL of the web dashboard passed through to the ``!web`` command.

    Returns:
        A fully configured DMMonitor ready to be started.
    """
    monitor: DMMonitor = DMMonitor(
        iface=iface,
        config=config,
        channel=channel,
        case_sensitive=args.case_sensitive,
        exclude_ootb=args.exclude_ootb,
        user_defined_commands=UserCommands(iface, config, channel, verbose=args.verbose, range_test_requests=args.range_test_requests, range_test_delay_minutes=args.range_test_delay_minutes).get_commands(),
        verbose=args.verbose,
        passphrase=args.encryption_key,
        web_url=web_url,
    )
    return monitor

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

def reconnect_device(iface: meshtastic.serial_interface.SerialInterface, args: AppArguments, node_initializer: NodeInitializer) -> meshtastic.serial_interface.SerialInterface:
    print(_MSG_NODE_INIT_REBOOT_WAIT)
    try:
        iface.close()
    except Exception:
        pass
    time.sleep(_NODE_INIT_REBOOT_INITIAL_WAIT)
    reconnect_ok = False
    while not reconnect_ok:
        try:
            iface = meshtastic.serial_interface.SerialInterface()
            reconnect_ok = iface is not None and iface.devPath is not None
            time.sleep(_RECONNECT_DELAY_SECONDS)
        except Exception as reconnect_err:
            if args.verbose:
                print(_MSG_RECONNECT_FAILED.format(error=reconnect_err, delay=_RECONNECT_DELAY_SECONDS))
            time.sleep(_RECONNECT_DELAY_SECONDS)
    return iface

def main() -> None:
    """Entry point for the DAMNBot application.

    Parses command-line arguments, connects to the Meshtastic device via serial,
    resolves the target channel, sends the welcome message, starts the channel
    monitor, and sends the signoff message on exit. If the serial connection is
    lost at runtime the bot automatically stops the monitors, waits briefly, and
    re-establishes the connection without sending any lifecycle messages.
    """
    args: AppArguments
    config: NodeConfiguration
    primary_channel: channel_pb2.Channel | None = None
    secondary_channel: channel_pb2.Channel | None = None
    secondary_channel_name: str | None = None
    primary_channel_monitor: ChannelMonitor
    current_channel_monitor: ChannelMonitor
    connection_monitor: ConnectionMonitor
    console_logger: ConsoleLogger
    dm_monitor: DMMonitor
    node_monitor: NodeMonitor
    bot_broadcaster: BotBroadcaster
    web_server: WebServer
    chat_history: ChatHistory
    iface: meshtastic.serial_interface.SerialInterface | None
    node_initializer: NodeInitializer
    zen_quotes_api: ZenQuotesApi
    today_in_history_api: TodayInHistoryApi
    reboot_triggered: bool
    reconnect_ok: bool
    keyboard_interrupted: bool
    reconnected: bool
    disconnected: bool
    current_time: float
    last_checkin_time: float

    console_logger = ConsoleLogger()
    args = AppArguments()
    args.parse()

    if args.verbose:
        print(_VERBOSE_ARGS_MESSAGE.format(
            bot_name=args.bot_name,
            bot_description=args.bot_description,
            channel=args.channel or "(prompt)",
            case_sensitive=args.case_sensitive,
            exclude_ootb=args.exclude_ootb,
            no_node_init=args.no_node_init,
            node_retention_days=args.node_retention_days,
            encrypted=args.encryption_key is not None,
            verbose=args.verbose,
            web_url=args.web_url,
            web_port=args.web_port,
            range_test_requests=args.range_test_requests,
            range_test_delay=args.range_test_delay_minutes,
            zen_quotes_poll_interval=args.zen_quotes_poll_interval_minutes,
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
        config = NodeConfiguration(iface)
        if args.verbose:
            print(_NODE_IDENTITY_MESSAGE.format(long_name=config.long_name, short_name=config.short_name, node_id=config.node_id))

        node_initializer = NodeInitializer(iface)
        reboot_triggered: bool = False
        settings_changed: bool = False
        if not args.no_node_init:
            print(_MSG_NODE_INIT_APPLYING)
            settings_changed = node_initializer.apply()
            # reboot_triggered = node_initializer._apply_lora_settings()
            # settings_changed = node_initializer._apply_device_settings() or settings_changed
            print(_MSG_NODE_INIT_APPLIED)
            
        if(settings_changed == True):
            print("Device configuration changed but reboot not triggered — waiting briefly before continuing...")
            reboot_triggered = True
            iface.localNode.reboot()
            time.sleep(_NODE_INIT_REBOOT_INITIAL_WAIT)
        

        if reboot_triggered:
            iface = reconnect_device(iface, args, node_initializer)
            config = NodeConfiguration(iface)
            node_initializer.update_iface(iface)
            print(_MSG_NODE_INIT_RECONNECT_SUCCESS)
        else:
            print("Device reboot not triggered")
            
        node_db = NodeDatabase(
            retention_days=args.node_retention_days,
            passphrase=args.encryption_key,
            verbose=args.verbose,
        )
        node_db.load_from_interface(iface)
        node_db.prune()

        zen_quotes_api = ZenQuotesApi(
            poll_interval_minutes=args.zen_quotes_poll_interval_minutes,
            verbose=args.verbose,
        )
        today_in_history_api = TodayInHistoryApi(verbose=args.verbose)

        primary_channel = _resolve_channel(CHANNEL_NAME_PRIMARY, config)
        if(primary_channel is None):
            print(_MSG_CHANNEL_NOT_FOUND_NAME.format(name=CHANNEL_NAME_PRIMARY))
        else:
            if(args.channel is not None and CHANNEL_NAME_PRIMARY != args.channel):
                secondary_channel = _resolve_channel(args.channel, config)
                secondary_channel_name = None if secondary_channel is None else secondary_channel.settings.name
                
            if(primary_channel is not None):
                primary_channel_monitor = _build_primary_channel_monitor(iface, config, primary_channel, args, ChatHistory(channel_name=CHANNEL_NAME_PRIMARY, passphrase=args.encryption_key))            
            
            if(secondary_channel is not None and secondary_channel_name is not None):
                    chat_history = ChatHistory(channel_name=secondary_channel_name, passphrase=args.encryption_key)
                    bot_broadcaster = BotBroadcaster(
                        iface,
                        config,
                        bot_name=args.bot_name,
                        verbose=args.verbose,
                        web_url=_WEB_DASHBOARD_URL.format(host=args.web_url, port=args.web_port),
                        chat_history=chat_history,
                    )
                    bot_broadcaster.send_welcome_message(secondary_channel)

                    current_channel_monitor = _build_channel_monitor(iface, config, secondary_channel, args, chat_history, web_url=_WEB_DASHBOARD_URL.format(host=args.web_url, port=args.web_port))
                    dm_monitor = _build_dm_monitor(iface, config, secondary_channel, args, web_url=_WEB_DASHBOARD_URL.format(host=args.web_url, port=args.web_port))
                    node_monitor = NodeMonitor(iface=iface, db=node_db, verbose=args.verbose)

                    primary_channel_monitor.start()
                    current_channel_monitor.start()
                    dm_monitor.start()
                    node_monitor.start()

                    connection_monitor = ConnectionMonitor(verbose=args.verbose)
                    connection_monitor.start()

                    tile_cache: TileCache = TileCache()
                    web_server = WebServer(
                        node_db=node_db,
                        iface=iface,
                        channel=secondary_channel,
                        config=config,
                        bot_name=args.bot_name,
                        tile_cache=tile_cache,
                        bot_description=args.bot_description,
                        case_sensitive=args.case_sensitive,
                        host=args.web_url,
                        passphrase=args.encryption_key,
                        port=args.web_port,
                        chat_history=chat_history,
                        console_logger=console_logger,
                    )
                    web_server.start()
                    tile_cache.start()

                    print(_MSG_BOT_STARTED.format(bot_name=args.bot_name, channel_name=secondary_channel_name))
                    print(_MSG_STOP_APPLICATION)

                    keyboard_interrupted = False
                    while not keyboard_interrupted:
                        last_checkin_time = time.time()
                        disconnected = False

                        try:
                            while not disconnected:
                                if connection_monitor.wait(timeout=_MONITOR_POLL_INTERVAL):
                                    connection_monitor.acknowledge()
                                    disconnected = True
                                else:
                                    current_time = time.time()
                                    if secondary_channel is not None and current_time - last_checkin_time >= _CHECKIN_INTERVAL:
                                        bot_broadcaster.send_checkin_message(secondary_channel)
                                        last_checkin_time = current_time
                        except KeyboardInterrupt:
                            keyboard_interrupted = True

                        print(_MSG_CHANNEL_MONITOR_STOPPING)
                        primary_channel_monitor.stop()
                        current_channel_monitor.stop()
                        print(_MSG_DM_MONITOR_STOPPING)
                        dm_monitor.stop()
                        print(_MSG_NODE_MONITOR_STOPPING)
                        node_monitor.stop()

                        if keyboard_interrupted and secondary_channel is not None:
                            bot_broadcaster.send_signoff_message(secondary_channel)
                            if not args.no_node_init:
                                node_initializer.restore()
                        else:
                            try:
                                iface.close()
                            except Exception:
                                pass

                            reconnected = False
                            while not reconnected and not keyboard_interrupted:
                                if args.verbose:
                                    print(_MSG_RECONNECT_ATTEMPT.format(delay=_RECONNECT_DELAY_SECONDS))
                                try:
                                    time.sleep(_RECONNECT_DELAY_SECONDS)
                                    iface = meshtastic.serial_interface.SerialInterface()
                                    reconnected = iface is not None and iface.devPath is not None
                                except KeyboardInterrupt:
                                    keyboard_interrupted = True
                                except Exception as reconnect_err:
                                    if args.verbose:
                                        print(_MSG_RECONNECT_FAILED.format(error=reconnect_err, delay=_RECONNECT_DELAY_SECONDS))

                            if reconnected:
                                config = NodeConfiguration(iface)
                                node_db.load_from_interface(iface)
                                secondary_channel = MeshtasticHelper.get_channel_by_name(config.channels, secondary_channel_name)
                                if secondary_channel is not None:
                                    bot_broadcaster = BotBroadcaster(
                                        iface,
                                        config,
                                        bot_name=args.bot_name,
                                        verbose=args.verbose,
                                        web_url=_WEB_DASHBOARD_URL.format(host=args.web_url, port=args.web_port),
                                        chat_history=chat_history,
                                    )
                                    current_channel_monitor = _build_channel_monitor(iface, config, secondary_channel, args, chat_history)
                                    dm_monitor = _build_dm_monitor(iface, config, secondary_channel, args)
                                    node_monitor = NodeMonitor(iface=iface, db=node_db, verbose=args.verbose)

                                    current_channel_monitor.start()
                                    dm_monitor.start()
                                    node_monitor.start()

                                    web_server.update_iface(iface, secondary_channel)

                                    if args.verbose:
                                        print(_MSG_RECONNECT_SUCCESS)
                                else:
                                    keyboard_interrupted = True

                    print(_MSG_CONNECTION_MONITOR_STOPPING)
                    zen_quotes_api.stop_polling()
                    today_in_history_api.stop_polling()
                    connection_monitor.stop()

                    try:
                        iface.close()
                    except Exception:
                        pass

    print(_MSG_DISCONNECTED)


if __name__ == "__main__":
    main()
