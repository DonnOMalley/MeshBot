"""Shared constants used across the DAMNBot application."""

from meshtastic import channel_pb2

# region CLI Arguments
_ARG_BOT_NAME: str = "bot_name"
_ARG_CASE_SENSITIVE: str = "--CaseSensitive"
_ARG_CHANNEL: str = "--Channel"
_ARG_CONFIG: str = "--Config"
_ARG_ENCRYPTION_KEY: str = "--EncryptionKey"
_ARG_EXCLUDE_OOTB: str = "--ExcludeOOTB"
_ARG_NODE_RETENTION_DAYS: str = "--NodeRetentionDays"
_ARG_VERBOSE: str = "--Verbose"

_DEFAULT_CONFIG_FILE: str = "meshbot.config"
_CONFIG_SECTION: str = "meshbot"

_APP_DESCRIPTION: str = "A configurable Meshtastic channel bot."
_APP_EPILOG: str = (
    "Examples:\n"
    "  python meshbot.py DAMNbot\n"
    "  python meshbot.py DAMNbot --Channel primary\n"
    "  python meshbot.py DAMNbot --Channel MyMesh --CaseSensitive\n"
    "  python meshbot.py DAMNbot --Channel MyMesh --ExcludeOOTB\n"
    "  python meshbot.py DAMNbot --Channel MyMesh --Verbose\n"
    "  python meshbot.py DAMNbot --NodeRetentionDays 60\n"
    "  python meshbot.py DAMNbot --EncryptionKey mysecret\n"
    "  python meshbot.py --Config path/to/my.config\n"
    "  python meshbot.py  (uses meshbot.config in current directory if present)\n"
    "\n"
    "Config file format (INI, section [meshbot]):\n"
    "  bot_name          = DAMNbot\n"
    "  Channel           = MyMesh\n"
    "  CaseSensitive     = false\n"
    "  ExcludeOOTB       = false\n"
    "  NodeRetentionDays = 30\n"
    "  EncryptionKey     = mysecret\n"
    "  Verbose           = false\n"
)
_HELP_BOT_NAME: str = (
    "The display name for the bot. Used as the command prefix (@BotName) and in "
    "lifecycle messages sent to the channel. May be omitted when bot_name is set "
    "in a config file."
)
_HELP_CONFIG: str = (
    "Path to an INI config file supplying default argument values. "
    "If omitted, 'meshbot.config' in the current directory is used automatically "
    "when it exists. Command-line arguments always override config file values."
)
_HELP_CASE_SENSITIVE: str = (
    "When set, the bot prefix and command names must match exactly as typed, "
    "including letter case. By default the checks are case-insensitive."
)
_HELP_CHANNEL: str = (
    "Name of the channel to monitor. When provided the bot connects directly "
    "without prompting for a channel index. Use 'primary' for the primary channel."
)
_HELP_EXCLUDE_OOTB: str = (
    "When set, the out-of-the-box default commands (ping, test) are not registered. "
    "Only the hello command remains active by default."
)
_HELP_VERBOSE: str = (
    "When set, enables verbose console output. Prints received messages, "
    "dispatched commands, and sent message notifications to the console."
)
_HELP_NODE_RETENTION_DAYS: str = (
    "Number of days without activity before a node is removed from the local "
    "database. Defaults to 30 days."
)
_HELP_ENCRYPTION_KEY: str = (
    "Passphrase used to encrypt and decrypt local data files. "
    "When omitted, data is stored as plain text. "
    "For security, prefer setting this in the config file rather than on the command line."
)
# endregion CLI Arguments

# region Bot Command Names
CMD_LIST: str = "list"
CMD_HELLO: str = "hello"
CMD_PING: str = "ping"
CMD_TEST: str = "test"
CMD_LAST: str = "last"
_EXCLAMATION_PREFIX: str = "!"
# endregion Bot Command Names

# region Channel Names
CHANNEL_NAME_PRIMARY: str = "primary"
# endregion Channel Names

# region Application Messages (Startup)
_VERBOSE_ARGS_MESSAGE: str = (
    "[ARGS] bot_name={bot_name} | channel={channel} | "
    "CaseSensitive={case_sensitive} | ExcludeOOTB={exclude_ootb} | "
    "NodeRetentionDays={node_retention_days} | Encrypted={encrypted} | Verbose={verbose}"
)
# endregion Application Messages (Startup)

# region Application Settings
_MONITOR_POLL_INTERVAL: float = 0.1
_CHECKIN_INTERVAL: float = 7200.0
# endregion Application Settings

# region Application Messages
_STARTUP_MESSAGE: str = "Connecting to Meshtastic device via serial..."
_NODE_IDENTITY_MESSAGE: str = "Bot node: {long_name} ({short_name}) [{node_id}]"
_CHANNEL_PROMPT: str = "\nEnter the index of the channel to use: "
_MSG_NO_SERIAL_DEVICE: str = (
    "No Meshtastic device found on any serial port. "
    "Ensure the device is connected via USB and try again."
)
_MSG_SERIAL_CONNECTION_ERROR: str = "Failed to open serial connection to Meshtastic device: {error}"
_MSG_NO_VALID_INDEX: str = "No valid index entered. No message sent."
_MSG_CHANNEL_NOT_FOUND_INDEX: str = "Channel index {index} not found in the active channel list. No message sent."
_MSG_CHANNEL_NOT_FOUND_NAME: str = "Channel '{name}' not found in the active channel list. No message sent."
_MSG_DISCONNECTED: str = "\nDisconnected."
_MSG_BOT_STARTED: str = "\n{bot_name} is running on channel '{channel_name}'."
_MSG_STOP_APPLICATION: str = "\nPress Ctrl+C to stop...\n"
_MSG_BOT_COMMAND_LIST_DM_SENT: str = "Command List sent in DM."
# endregion Application Messages

# region Pubsub Event Names
_EVENT_TEXT: str = "meshtastic.receive.text"
_EVENT_DATA: str = "meshtastic.receive.data"
# endregion Pubsub Event Names

# region Packet Keys
_PACKET_KEY_ID: str = "id"
_PACKET_KEY_FROM_ID: str = "fromId"
_PACKET_KEY_FROM_NUM: str = "from"
_PACKET_KEY_DECODED: str = "decoded"
_PACKET_KEY_PORTNUM: str = "portnum"
_PACKET_KEY_PAYLOAD: str = "payload"
_PACKET_KEY_TEXT: str = "text"
_PACKET_KEY_HOP_START: str = "hopStart"
_PACKET_KEY_HOP_LIMIT: str = "hopLimit"
_PACKET_KEY_CHANNEL: str = "channel"
_PACKET_KEY_TO_ID: str = "toId"
_BROADCAST_ID: str = "^all"
# endregion Packet Keys

# region Packet Types
_PACKET_TYPE_CHANNEL: str = "channel"
_PACKET_TYPE_DM: str = "dm"
# endregion Packet Types

# region Node Display Formats
_FORMAT_SHORT_NAME: str = "({short_name})"
# endregion Node Display Formats

# region Geographic Scales
_LATITUDE_SCALE: float = 1e-7
_LONGITUDE_SCALE: float = 1e-7
# endregion Geographic Scales

# region Channel List Display
_MSG_NO_CHANNELS: str = "No active channels found on this node."
_CHANNEL_LIST_HEADER: str = f"\n{'Index':<8} {'Name':<20} {'Role':<12} {'UpLink / DownLink'}"
_CHANNEL_LIST_SEPARATOR: str = "-" * 56
_CHANNEL_LIST_ROW: str = "{index:<8} {name:<20} {role:<12} {uplink} / {downlink}"
_CHANNEL_NAME_PRIMARY_LABEL: str = "(primary)"
_CHANNEL_NAME_FORMAT: str = "channel_{index}"
_ROLE_NAMES: dict[int, str] = {
    v.number: v.name
    for v in channel_pb2.Channel.DESCRIPTOR.fields_by_name["role"].enum_type.values
}
# endregion Channel List Display

# region Channel Monitor Messages
_MSG_IGNORED: str = "[BOT] Message ignored (no '{cmdPrefix}' prefix to indicate a command.): {text}"
_MSG_UNKNOWN_COMMAND: str = "[BOT] Unknown command '{command}' from {sender}."
_MSG_CHANNEL_COMMAND_RECEIVED: str = "[BOT] Command '{command}' received from {sender} | params: '{params}'"
_MSG_CHANNEL_MONITORING_STARTED: str = "\nMonitoring channel '{channel_name}' (index {index})."
_MSG_CHANNEL_MONITOR_STOPPED: str = "\nChannel monitor stopped."
_MSG_CHANNEL_TEXT_RECEIVED: str = "[TEXT] From {sender}: {text}"
_MSG_CHANNEL_DATA_RECEIVED: str = "[DATA] From {sender} on portnum {portnum}: {payload}"
# endregion Channel Monitor Messages

# region DM Monitor Messages
_MSG_DM_MONITORING_STARTED: str = "\nMonitoring direct messages(dm)."
_MSG_DM_MONITOR_STOPPED: str = "\nDM monitor stopped."
_MSG_DM_TEXT_RECEIVED: str = "[DM] From {sender}: {text}"
_MSG_DM_DATA_RECEIVED: str = "[DM DATA] From {sender} on portnum {portnum}: {payload}"
_MSG_DM_UNKNOWN_COMMAND: str = (
    "I only respond to specific commands. "
    "Send !list to see the available options."
)
# endregion DM Monitor Messages

# region Bot Command Responses
_HELLO_RESPONSE_WITH_PARAMS: str = "Hello there {display_name}, thanks for saying hi and passing along the following: {params}"
_HELLO_RESPONSE_NO_PARAMS: str = "Hello there {display_name}, thanks for saying hi! I'm here to help."
_HELLO_CONSOLE_RESPONSE: str = "[BOT] Hello command received from {display_name}"

_PING_RESPONSE: str = "Pong! 🏓"
_PING_CONSOLE_RESPONSE: str = "[BOT] Ping received from {sender}. Pong! 🏓"

_TEST_RESPONSE: str = "Hops: {hop_count} 🐇"
_TEST_RESPONSE_DIRECT: str = "Hey neighbor - Direct Connect here!"
_TEST_CONSOLE_RESPONSE: str = "[BOT] Test command received from {sender}."

_MSG_LAST_USAGE: str = "Usage: !last <count> <channel>\nExample: !last 5 OMalleyLand"
_MSG_LAST_NOT_FOUND: str = "No history found for channel: {channel}"
_MSG_LAST_HEADER: str = "Last {count} messages from {channel}:"
_MSG_LAST_DM_INCOMING: str = "Sending you the last {count} message(s) from {channel} in DM."
_MSG_LAST_CAPPED: str = "Requested {requested} messages but the mesh limit is {max}. Sending the last {max} instead."
_MSG_LAST_CONSOLE: str = "[BOT] last — {count} messages from '{channel}' sent to {sender}"
# endregion Bot Command Responses

# region Command Send Delays
_CMD_SEND_DELAY: float = 2.0
_CMD_LIST_HEADER: str = "Available commands:"
_CMD_LIST_ITEM_FORMAT: str = "- !{cmd}"
_CMD_LAST_MAX_MESSAGES: int = 5
# endregion Command Send Delays

# region Node Database
_NODE_DB_DIR: str = "data"
_NODE_DB_FILE: str = "nodes.json"
_NODE_DB_SALT_FILE: str = "salt.bin"
_NODE_DB_DEFAULT_RETENTION_DAYS: int = 30
_NODE_DB_LOADED: str = "Node database loaded: {count} node(s)."
_NODE_DB_PRUNED: str = "Node database pruned: {count} stale node(s) removed (retention: {days} days)."
_NODE_DB_ADDED: str = "[NODE DB] Added    {node_id} | {long_name} ({short_name})"
_NODE_DB_UPDATED: str = "[NODE DB] Updated  {node_id} | {long_name} ({short_name}) | Last seen: {delta} ago"
_NODE_DB_NO_CHANGE: str = "[NODE DB] No change {node_id}"
_NODE_DB_DECRYPTION_ERROR: str = (
    "Failed to decrypt node database. "
    "Verify that --EncryptionKey matches the value used when the file was created."
)
# endregion Node Database

# region Chat History
_CHAT_HISTORY_FILE_FORMAT: str = "{channel_name}.txt"
_CHAT_HISTORY_LINE_FORMAT: str = "[{timestamp}] {sender}: {text}\n"
_CHAT_HISTORY_TIMESTAMP_FORMAT: str = "%Y-%m-%d %H:%M:%S UTC"
# endregion Chat History

# region Web Dashboard
_WEB_SERVER_HOST: str = "0.0.0.0"
_WEB_SERVER_PORT: int = 5000
_WEB_SERVER_HISTORY_LIMIT: int = 200
_WEB_SERVER_MAX_SEND_LENGTH: int = 228
_WEB_SERVER_STARTED: str = "Web dashboard running at http://localhost:{port}"
# endregion Web Dashboard

# region Node Monitor Messages
_EVENT_NODE_INFO: str = "meshtastic.receive.user"
_MSG_NODE_MONITOR_STARTED: str = "\nMonitoring node announcements."
_MSG_NODE_MONITOR_STOPPED: str = "\nNode monitor stopped."
_MSG_NODE_INFO_RECEIVED: str = "[NODE] Node info received from {sender}"
# endregion Node Monitor Messages

# region Bot Lifecycle Messages
_BOT_WELCOME_MESSAGE: str = f"Hello Mesh! {{bot_name}} is online.\nRunning on {{long_name}} ({{short_name}})\n\nMessage me here or send me a DM\n\nSend !{CMD_LIST} to see the list of available commands"
_BOT_CHECKIN_MESSAGE: str = f"{{bot_name}} just checking in... Still online\nSend !{CMD_LIST} to see the list of available commands"
_BOT_SIGNOFF_MESSAGE: str = "{bot_name} signing off!\n\nCatch you on the flip side!"

_BOT_WELCOME_MESSAGE_SENT: str = "Welcome message sent on channel '{index}: {name}' ."
_BOT_CHECKIN_MESSAGE_SENT: str = "Check-in message sent on channel '{index}: {name}'."
_BOT_SIGNOFF_MESSAGE_SENT: str = "Signoff message sent on channel '{index}: {name}'."
# endregion Bot Lifecycle Messages
