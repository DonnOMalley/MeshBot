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
- Multi-page web dashboard (Flask) with dashboard, nodes, chat, console, and about pages
- Node table: live hop count shown alongside last-seen time
- Node table: GPS position column with Google Maps link
- Node table: web-initiated traceroute with live spinner and always-visible left-anchored result popup
- Node table: live filter input (long name, short name, device type)
- Node table: CSV export button for downloading the current node list
- Node favourite/star system persisted to disk
- Web user identity: browser users receive a persistent fake Meshtastic node ID and can customise their display name
- Live bot console terminal in the web dashboard; all console output is also logged to `log/`
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
WebPort           = 7331
```

| Key                 | Description                                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| `bot_name`          | Display name of the bot. Used in messages and as the command prefix (`@BotName`).                      |
| `bot_description`   | Optional description shown in the web header beneath the bot name.                                     |
| `Channel`           | Channel name to join on startup. Omit to be prompted at launch.                                        |
| `CaseSensitive`     | When `true`, command prefix and names must match exact case.                                           |
| `ExcludeOOTB`       | When `true`, built-in commands (`ping`, `test`, `hello`, `last`) are not registered.                   |
| `NodeRetentionDays` | Days of inactivity before a node is removed from the local database. Default: `30`.                    |
| `EncryptionKey`     | Passphrase to encrypt the node database and chat history. Leave blank for plain text.                  |
| `Verbose`           | When `true`, prints received messages, dispatched commands, and sent notifications.                    |
| `WebUrl`            | Hostname shown in the console startup message. Does not change the bind address. Default: `localhost`. |
| `WebPort`           | Port the web dashboard listens on. Default: `7331`.                                                    |

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

| Command           | Description                                                                            |
| ----------------- | -------------------------------------------------------------------------------------- |
| `!hello`          | Bot greets the sender.                                                                 |
| `!ping`           | Bot replies with `Pong! 🏓`.                                                           |
| `!test`           | Bot replies with the hop count (`Hops: N 🐇`), or confirms a direct connection.        |
| `!last N CHANNEL` | Returns the last N messages from the specified channel as DMs (max 5).                 |
| `!trace`          | Sends a traceroute to the requester and reports the route, SNR readings, and duration. |
| `!web`            | Replies with the web dashboard URL so any mesh node can find the portal.               |
| `!cmdList`        | Lists all registered commands.                                                         |

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
http://localhost:7331
```

Use `--WebUrl` and `--WebPort` (or the config file equivalents) to change the address.

### Pages

| Page      | Path        | Description                                                                                             |
| --------- | ----------- | ------------------------------------------------------------------------------------------------------- |
| Dashboard | `/`         | Node panel (collapsible) and channel chat history.                                                      |
| Nodes     | `/nodes`    | Full-page node table.                                                                                   |
| Chat      | `/chat`     | Full-page chat with per-channel tabs and message send form.                                             |
| Console   | `/console`  | Live bot console terminal; mirrors all stdout/stderr output.                                            |
| Bot Test  | `/dm`       | Interactive direct-message session with the bot; includes quick-command buttons and a live chat window. |
| Settings  | `/settings` | Read-only view of the connected device's LoRa, device, owner, and channel configuration.                |
| About     | `/about`    | Bot information: name, description, version, and links.                                                 |

### Node table

The node table appears on both the Dashboard and Nodes pages. A toolbar above the table provides filtering and export.

**Filter:** Type any text into the filter input to instantly narrow the list by long name, short name, or device type. The panel header updates to show how many nodes are visible.

**Export:** Click the **↡ Export CSV** button to download the current (filtered or full) node list as `nodes.csv`.

### Node table columns

| Column     | Description                                                                                                                                                             |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ★          | Favourite toggle. Favourites float to the top of the list and are persisted to disk.                                                                                    |
| Node Name  | Long name with short name in parentheses. Hover the row to see the node ID.                                                                                             |
| Role       | Node role as reported by the device.                                                                                                                                    |
| Device     | Hardware model.                                                                                                                                                         |
| Last Seen  | Last-seen time in browser local time. Hop count shown in parentheses when known.                                                                                        |
| Position   | Pin icon linking to Google Maps when GPS coordinates are available.                                                                                                     |
| Traceroute | **Trace** button to request a live traceroute from the bot to that node. Shows a spinner while in-flight, then an inline result card with route, SNR, and elapsed time. |

Favourites are persisted to `data/favorites.json`.

### Bot Test (Direct Message)

The **Bot Test** page (`/dm`) lets you send direct messages to the bot from the browser without needing a physical Meshtastic device. A one-time identity setup associates your browser session with a fake Meshtastic node (the same identity used on the Chat page). Quick-command buttons for `!hello`, `!ping`, `!test`, `!last`, `!trace`, `!web`, and `!joke` let you test common commands with one click. Responses appear in a live conversation window that is not saved to the channel chat logs.

### Settings

The **Settings** page (`/settings`) displays a read-only view of the connected Meshtastic device's configuration:

- **LoRa Settings** — region, modem preset, and key radio parameters.
- **Device Settings** — device role, serial, GPS, debug, and power settings.
- **Owner** — the node's long name, short name, and hardware model.
- **Channels** — all configured channel slots with their name, role, and PSK status.

Each browser session is automatically assigned a persistent fake Meshtastic identity: a node ID derived from the session token, a long name (up to 20 characters), and a short name (2–4 alphanumeric characters, must start with `W`). Click **Edit** in the footer bar to customise your display name.

Outgoing messages are prefixed with `[SHORT]` on the mesh (e.g. `[WUSR] Hello mesh!`) so other nodes can identify the web sender. The web portal displays the message under the user's full display name.

### Chat history display

- Timestamps are shown in browser local time (HH:MM:SS).
- Days are separated by a date line.
- Channels are selectable via tabs.

### Network Access

The server binds to `0.0.0.0` (all interfaces). Your OS firewall may block inbound connections on the configured port.

#### Windows

Add a firewall inbound rule (run in an **elevated/Admin PowerShell**):

```powershell
New-NetFirewallRule -DisplayName "MeshBot Web Dashboard" -Direction Inbound -Protocol TCP -LocalPort 7331 -Action Allow
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
sudo ufw allow 7331/tcp
sudo ufw reload
```

Or with `firewalld`:

```bash
sudo firewall-cmd --permanent --add-port=7331/tcp
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
    console_logger.py           Console output tee (log file + web buffer)
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
log/
    console_<timestamp>.log     Console output log (one per session, git-ignored)
web/
    web_server.py               Flask web server
    static/
        app.js                  Shared JS module (nodes, channels, history)
        chat.js                 Page init for /chat
        console.js              Page init for /console (terminal polling)
        nodes.js                Page init for /nodes
        style.css               Dashboard styles
    templates/
        partials/
            _header.html            Shared nav header partial (included by all pages)
        about.html              About page
        chat.html               Chat full-page view
        console.html            Console terminal page
        index.html              Dashboard page
        nodes.html              Nodes full-page view
```

---

## Data & Encryption

Node records are stored in `data/nodes.json`. Chat history is stored per-channel as `data/<channel_name>.txt`. Favourites are stored in `data/favorites.json`.

When an `EncryptionKey` is provided, all three files are encrypted using AES via the `cryptography` package. All instances sharing the same data files must use the same key.

---

## Release Notes

### v0.7.0 — 2026-03-16

- All pages are now viewport-locked: the browser document never scrolls; only the content panels within each page scroll internally.
- The last panel on every page (node table, chat history, console terminal, DM conversation) fills the remaining viewport height, eliminating dead space at page bottom.
- The **About** page retains natural document scrolling so the long README can be read without restriction.
- Added **Settings** page (`/settings`) to the README documentation: shows LoRa, device, owner, and channel configuration from the connected device.
- Added **Bot Test** page (`/dm`) to the README documentation: interactive DM session with quick-command buttons for all built-in and user commands.
- `scrollbar-gutter: stable` added to primary scroll areas to prevent layout shift when a scrollbar appears or disappears.

### v0.6.0 — 2026-03-15

- Added live bot console terminal page (`/console`): polls every 2 s and renders new output in a 1980s-style green-on-black CRT terminal.
- All bot console output (stdout + stderr) is tee'd to a timestamped log file in `log/` at startup; one file is created per session.
- Added web user identity: each browser session is assigned a persistent fake Meshtastic node ID derived from the session token. Users can customise their long name (up to 20 chars) and short name (2–4 alphanumeric chars, must start with `W`).
- Messages sent from the web portal are prefixed with `[SHORT]` on the mesh and attributed to the user's full display name in the chat history viewer.
- Node table: hop count is now shown in parentheses alongside the last-seen time when reported by the device.
- Trace popup now opens to the left of the icon and is rendered globally (no longer clipped by table overflow or active filter state).

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
- Flask web dashboard on port `7331` with node list, chat history, and message send.
- `commands/user_commands.py` extensibility point for custom commands.
- `meshbot.config` INI file support with CLI argument overrides.
