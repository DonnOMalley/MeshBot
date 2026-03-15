# MeshBot

A configurable Meshtastic channel bot with a multi-page web dashboard. Monitors a Meshtastic mesh network channel via serial connection, responds to commands, tracks nodes, logs chat history, and exposes a local web UI for monitoring and sending messages.

---

## Features

- Monitors a configured channel and responds to bot commands
- Responds to direct messages (DMs)
- Tracks and persists node information with configurable retention
- Logs channel chat history to disk (with optional encryption)
- Optional command prefix case-sensitivity control
- Periodic check-in messages to the channel
- Welcome message includes the web dashboard URL
- Optional bot description displayed in the web header
- Traceroute command with SNR readings and elapsed time in the response
- Multi-page web dashboard (Flask) with dashboard, nodes, chat, and about pages
- Node table: GPS position column with Google Maps link
- Node table: web-initiated traceroute with live spinner and inline result card
- Node table: live filter input (long name, short name, device type)
- Node table: CSV export button for downloading the current node list
- Node favourite/star system persisted to disk
- Extensible user-defined commands via `commands/user_commands.py`

---

## Requirements

- Python 3.14+
- A Meshtastic device connected via USB serial

### Python packages

Install dependencies with:

```bash
pip install -r requirements.txt
```

Dependencies: `cryptography`, `flask`, `meshtastic`, `pubsub`

---

## Configuration

Copy `meshbot.config.example` to `meshbot.config` and edit it:

```ini
[meshbot]
bot_name          = MyBot
bot_description   = A Meshtastic bot
Channel           = MyChannel
CaseSensitive     = false
ExcludeOOTB       = false
NodeRetentionDays = 30
EncryptionKey     =
Verbose           = false
WebUrl            = localhost
WebPort           = 6969
```

| Key                 | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `bot_name`          | Display name of the bot. Used in messages and as the command prefix (`@BotName`).     |
| `bot_description`   | Optional description shown in the web header beneath the bot name.                    |
| `Channel`           | Channel name to join on startup. Omit to be prompted at launch.                       |
| `CaseSensitive`     | When `true`, command prefix and names must match exact case.                          |
| `ExcludeOOTB`       | When `true`, built-in commands (`ping`, `test`, `hello`, `last`) are not registered.  |
| `NodeRetentionDays` | Days of inactivity before a node is removed from the local database. Default: `30`.   |
| `EncryptionKey`     | Passphrase to encrypt the node database and chat history. Leave blank for plain text. |
| `Verbose`           | When `true`, prints received messages, dispatched commands, and sent notifications.   |
| `WebUrl`            | Hostname shown in the console startup message. Does not change the bind address. Default: `localhost`. |
| `WebPort`           | Port the web dashboard listens on. Default: `6969`.                                   |

> **Security note:** Prefer setting `EncryptionKey` in the config file rather than on the command line to avoid it appearing in shell history.

---

## Running

```bash
python meshbot.py
```

Or pass arguments directly (command-line arguments override config file values):

```bash
python meshbot.py MyBot --Channel primary
python meshbot.py MyBot --Channel MyMesh --CaseSensitive
python meshbot.py MyBot --Channel MyMesh --ExcludeOOTB
python meshbot.py MyBot --Channel MyMesh --Verbose
python meshbot.py MyBot --BotDescription "A Meshtastic bot"
python meshbot.py MyBot --NodeRetentionDays 60
python meshbot.py MyBot --EncryptionKey mysecret
python meshbot.py MyBot --WebUrl 192.168.1.100 --WebPort 8080
python meshbot.py --Config path/to/my.config
```

Press **Ctrl+C** to stop.

---

## Built-in Commands

Commands are sent in the monitored channel or via DM, prefixed with `!`:

| Command           | Description                                                                         |
| ----------------- | ----------------------------------------------------------------------------------- |
| `!hello`          | Bot greets the sender.                                                              |
| `!ping`           | Bot replies with `Pong! 🏓`.                                                        |
| `!test`           | Bot replies with the hop count (`Hops: N 🐇`), or confirms a direct connection.     |
| `!last N CHANNEL` | Returns the last N messages from the specified channel as DMs (max 5).              |
| `!trace`          | Sends a traceroute to the requester and reports the route, SNR readings, and duration. |
| `!cmdList`        | Lists all registered commands.                                                      |

### Traceroute response format

```
Trace:
→ Bot → relay1 → You
← You → relay1 → Bot
2 relay(s)
SNR→: -10.0, -8.5 dB
SNR←: -9.0, -11.0 dB
Time: 3.2s
```

Direct connections are reported as `Direct connect! No relays 🎯`.

---

## Custom Commands

Add your own commands in `commands/user_commands.py`. Register them via `get_commands()` and they will be passed to the channel monitor at startup.

---

## Web Dashboard

A Flask web dashboard starts automatically and is accessible from any machine on the network. The URL is printed to the console on startup and included in the bot's welcome message.

```
http://localhost:6969
```

Use `--WebUrl` and `--WebPort` (or the config file equivalents) to change the address.

### Pages

| Page      | Path      | Description                                                  |
| --------- | --------- | ------------------------------------------------------------ |
| Dashboard | `/`       | Node panel (collapsible) and channel chat history.           |
| Nodes     | `/nodes`  | Full-page node table.                                        |
| Chat      | `/chat`   | Full-page chat with per-channel tabs and message send form.  |
| About     | `/about`  | Bot information: name, description, version, and links.      |

### Node table

The node table appears on both the Dashboard and Nodes pages. A toolbar above the table provides filtering and export.

**Filter:** Type any text into the filter input to instantly narrow the list by long name, short name, or device type. The panel header updates to show how many nodes are visible.

**Export:** Click the **↡ Export CSV** button to download the current (filtered or full) node list as `nodes.csv`.

### Node table columns

| Column    | Description                                                                              |
| --------- | ---------------------------------------------------------------------------------------- |
| ★         | Favourite toggle. Favourites float to the top of the list and are persisted to disk.     |
| Node Name | Long name with short name in parentheses. Hover the row to see the node ID.              |
| Role      | Node role as reported by the device.                                                     |
| Device    | Hardware model.                                                                          |
| Last Seen | Absolute last-seen time in browser local time.                                           |
| Position  | Pin icon linking to Google Maps when GPS coordinates are available.                      |
| Traceroute | **Trace** button to request a live traceroute from the bot to that node. Shows a spinner while in-flight, then an inline result card with route, SNR, and elapsed time. |

Favourites are persisted to `data/favorites.json`.

### Chat history display

- Timestamps are shown in browser local time (HH:MM:SS).
- Days are separated by a date line.
- Channels are selectable via tabs.

### Network Access

The server binds to `0.0.0.0` (all interfaces). Your OS firewall may block inbound connections on the configured port.

#### Windows

Add a firewall inbound rule (run in an **elevated/Admin PowerShell**):

```powershell
New-NetFirewallRule -DisplayName "MeshBot Web Dashboard" -Direction Inbound -Protocol TCP -LocalPort 6969 -Action Allow
```

To verify the rule exists:

```powershell
Get-NetFirewallRule | Where-Object DisplayName -like "*MeshBot*"
```

To remove the rule later:

```powershell
Remove-NetFirewallRule -DisplayName "MeshBot Web Dashboard"
```

#### Linux

Allow the port through `ufw` (if enabled):

```bash
sudo ufw allow 6969/tcp
sudo ufw reload
```

Or with `firewalld`:

```bash
sudo firewall-cmd --permanent --add-port=6969/tcp
sudo firewall-cmd --reload
```

---

## Project Structure

```
meshbot.py                      Entry point
meshbot.config                  Runtime configuration (git-ignored)
meshbot.config.example          Example configuration template
requirements.txt                Python dependencies
commands/
    user_commands.py            User-defined bot commands
common/
    app_arguments.py            CLI argument parsing
    chat_history.py             Chat history read/write
    constants.py                All shared constants
    encryption_helper.py        Encrypt/decrypt data files
    meshtastic_helper.py        Meshtastic utility helpers
    node_database.py            Node persistence
configuration/
    node_configuration.py       Node config loading
data/
    nodes.json                  Persisted node database
    favorites.json              Persisted favourite nodes
    <channel_name>.txt          Chat history per channel
messaging/
    bot_commands.py             Built-in command definitions
    bot_lifecycle_messenger.py  Welcome/check-in/signoff messages
    command_handler.py          Command dispatch logic
    command_register.py         Command registration
    monitors/
        base_monitor.py         Abstract base monitor
        channel_monitor.py      Channel message monitor
        dm_monitor.py           Direct message monitor
        node_monitor.py         Node announcement monitor
web/
    web_server.py               Flask web server
    static/
        app.js                  Shared JS module (nodes, channels, history)
        nodes.js                Page init for /nodes
        chat.js                 Page init for /chat
        style.css               Dashboard styles
    templates/
        partials/
            _header.html            Shared nav header partial (included by all pages)
        about.html              About page
        index.html              Dashboard page
        nodes.html              Nodes full-page view
        chat.html               Chat full-page view
```

---

## Data & Encryption

Node records are stored in `data/nodes.json`. Chat history is stored per-channel as `data/<channel_name>.txt`. Favourites are stored in `data/favorites.json`.

When an `EncryptionKey` is provided, all three files are encrypted using AES via the `cryptography` package. All instances sharing the same data files must use the same key.

---

## Release Notes

### v0.5.0 — 2026-03-15

- Added `--BotDescription` CLI argument and `bot_description` config key; displayed in the web header beneath the bot name.
- Bot name in the web header is now a hyperlink back to `/`.
- Extracted shared navigation header to `partials/_header.html`; all pages now include the same partial.
- Added `/about` page showing bot name, description, version, and repository link.
- Node table: added **Position** column with a Google Maps pin link when GPS coordinates are available.
- Node table: added **Traceroute** column; clicking **Trace** sends a live traceroute request from the bot to that node, shows a spinner while in-flight, and displays an inline result card with route, SNR readings, and elapsed time.
- Node table: added live **filter** input above the table; filters by long name, short name, or device type instantly. Panel header updates to show filtered vs. total count.
- Node table: added **Export CSV** button to download the current (filtered or unfiltered) node list as `nodes.csv`.
- Removed the **Last Seen Delta** column from the node table.
- Fixed `onclick` HTML-attribute escaping for the favourite toggle and channel tab buttons (node IDs containing `!` were breaking the attribute boundary).
- Fixed traceroute spinner: cell now updates in place rather than triggering a full table re-render.
- Fixed `bot_description` config file key being silently ignored (was never mapped to the argument parser).

### v0.4.0 — 2026-03-14

- Added `--WebUrl` and `--WebPort` CLI arguments (and config file equivalents) to configure the web dashboard address.
- Welcome message now includes the web dashboard URL.
- Trace response includes SNR readings (forward and return) and elapsed time.
- Fixed command matching to be correctly case-insensitive for mixed-case command names (e.g. `!cmdList`).
- Renamed `!list` command to `!cmdList`.

### v0.3.0 — 2026-03-14

- Multi-page web dashboard: `/` (dashboard), `/nodes` (full-page nodes), `/chat` (full-page chat with send form).
- Navigation bar across all pages with active-page indicator.
- Collapsible node panel on the dashboard.
- Send Message removed from dashboard; moved to dedicated `/chat` page.
- Chat history timestamps shown in browser local time (HH:MM:SS only); days separated by a date line.
- Node table: added Role and Device columns.
- Node table: added ★ favourite toggle column; favourites float to the top and are persisted to `data/favorites.json` (optionally encrypted).
- Node table: Node ID removed from column view; shown on row hover as a tooltip.
- Node panel header shows total node count and known-name count.

### v0.2.0 — 2026-03-14

- Added `!trace` command: sends a Meshtastic traceroute to the requester and formats the result with relay count, SNR readings, and elapsed time.
- Added `!last N CHANNEL` command: returns the last N messages from a channel's history as DMs (max 5).
- Added node monitor: tracks node announcements and persists records to `data/nodes.json`.
- Added optional AES encryption for node database and chat history via `--EncryptionKey`.
- Added `--NodeRetentionDays` argument to control stale-node pruning.
- Added verbose mode (`--Verbose`) with console output for received messages, dispatched commands, and sent notifications.
- Added stop messages on Ctrl+C before each monitor is halted.

### v0.1.0 — initial release

- Serial connection to a Meshtastic device.
- Channel monitoring with `!hello`, `!ping`, `!test` built-in commands.
- DM monitoring with `!cmdList` support.
- Periodic check-in messages and welcome/signoff lifecycle messages.
- Chat history logging to `data/<channel_name>.txt`.
- Flask web dashboard on port `6969` with node list, chat history, and message send.
- `commands/user_commands.py` extensibility point for custom commands.
- `meshbot.config` INI file support with CLI argument overrides.


---

## Features

- Monitors a configured channel and responds to bot commands
- Responds to direct messages (DMs)
- Tracks and persists node information with configurable retention
- Logs channel chat history to disk (with optional encryption)
- Optional command prefix case-sensitivity control
- Periodic check-in messages to the channel
- Web dashboard (Flask) for viewing nodes, chat history, and sending messages
- Extensible user-defined commands via `commands/user_commands.py`

---

## Requirements

- Python 3.14+
- A Meshtastic device connected via USB serial

### Python packages

Install dependencies with:

```bash
pip install -r requirements.txt
```

Dependencies: `cryptography`, `flask`, `meshtastic`

---

## Configuration

Copy `meshbot.config.example` to `meshbot.config` and edit it:

```ini
[meshbot]
bot_name          = MyBot
Channel           = MyChannel
CaseSensitive     = false
ExcludeOOTB       = false
NodeRetentionDays = 30
EncryptionKey     =
Verbose           = false
```

| Key                 | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| `bot_name`          | Display name of the bot. Used in messages and as the command prefix (`@BotName`).     |
| `Channel`           | Channel name to join on startup. Omit to be prompted at launch.                       |
| `CaseSensitive`     | When `true`, command prefix and names must match exact case.                          |
| `ExcludeOOTB`       | When `true`, built-in commands (`ping`, `test`, `hello`, `last`) are not registered.  |
| `NodeRetentionDays` | Days of inactivity before a node is removed from the local database. Default: `30`.   |
| `EncryptionKey`     | Passphrase to encrypt the node database and chat history. Leave blank for plain text. |
| `Verbose`           | When `true`, prints received messages, dispatched commands, and sent notifications.   |

> **Security note:** Prefer setting `EncryptionKey` in the config file rather than on the command line to avoid it appearing in shell history.

---

## Running

```bash
python meshbot.py
```

Or pass arguments directly (command-line arguments override config file values):

```bash
python meshbot.py MyBot --Channel primary
python meshbot.py MyBot --Channel MyMesh --CaseSensitive
python meshbot.py MyBot --Channel MyMesh --ExcludeOOTB
python meshbot.py MyBot --Channel MyMesh --Verbose
python meshbot.py MyBot --NodeRetentionDays 60
python meshbot.py MyBot --EncryptionKey mysecret
python meshbot.py --Config path/to/my.config
```

Press **Ctrl+C** to stop.

---

## Built-in Commands

Commands are sent in the monitored channel or via DM, prefixed with `!`:

| Command           | Description                                             |
| ----------------- | ------------------------------------------------------- |
| `!hello`          | Bot greets the sender.                                  |
| `!ping`           | Bot replies with `Pong! 🏓`.                            |
| `!test`           | Bot replies with the hop count (`Hops: N 🐇`).          |
| `!last N CHANNEL` | Returns the last N messages from the specified channel. |
| `!list`           | Lists all available commands.                           |

---

## Custom Commands

Add your own commands in `commands/user_commands.py`. Register them via `get_commands()` and they will be passed to the channel monitor at startup.

---

## Web Dashboard

A Flask web dashboard starts automatically on port `6969` and is accessible from any machine able to reach yours on the network.

```
http://<your-ip>:6969
```

The dashboard provides:

- Live node list with last-seen timestamps
- Channel chat history viewer
- Message send form

### Network Access

The server binds to `0.0.0.0` by default, meaning it accepts connections from any network interface. However, your OS firewall may block inbound connections on port `6969`.

---

#### Windows

Add a firewall inbound rule (run in an **elevated/Admin PowerShell**):

```powershell
New-NetFirewallRule -DisplayName "MeshBot Web Dashboard" -Direction Inbound -Protocol TCP -LocalPort 6969 -Action Allow
```

To verify the rule exists:

```powershell
Get-NetFirewallRule | Where-Object DisplayName -like "*MeshBot*"
```

To remove the rule later:

```powershell
Remove-NetFirewallRule -DisplayName "MeshBot Web Dashboard"
```

---

#### Linux

Allow the port through `ufw` (if enabled):

```bash
sudo ufw allow 6969/tcp
sudo ufw reload
```

Or with `firewalld`:

```bash
sudo firewall-cmd --permanent --add-port=6969/tcp
sudo firewall-cmd --reload
```

To check the current `ufw` status:

```bash
sudo ufw status
```

---

## Project Structure

```
meshbot.py                  Entry point
meshbot.config              Runtime configuration (git-ignored)
meshbot.config.example      Example configuration template
requirements.txt            Python dependencies
commands/
    user_commands.py        User-defined bot commands
common/
    app_arguments.py        CLI argument parsing
    chat_history.py         Chat history read/write
    constants.py            All shared constants
    encryption_helper.py    Encrypt/decrypt data files
    meshtastic_helper.py    Meshtastic utility helpers
    node_database.py        Node persistence
configuration/
    node_configuration.py   Node config loading
data/
    nodes.json              Persisted node database
messaging/
    bot_commands.py         Built-in command definitions
    bot_lifecycle_messenger.py  Welcome/check-in/signoff messages
    command_handler.py      Command dispatch logic
    command_register.py     Command registration
    monitors/
        base_monitor.py     Abstract base monitor
        channel_monitor.py  Channel message monitor
        dm_monitor.py       Direct message monitor
        node_monitor.py     Node announcement monitor
web/
    web_server.py           Flask web server
    static/                 CSS and JS assets
    templates/
        index.html          Dashboard HTML
```

---

## Data & Encryption

Node records are stored in `data/nodes.json`. Chat history is stored per-channel as `data/<channel_name>.txt`.

When an `EncryptionKey` is provided, both files are encrypted using AES via the `cryptography` package. All instances sharing the same data files must use the same key.
