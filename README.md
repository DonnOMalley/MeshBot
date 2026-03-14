# MeshBot

A configurable Meshtastic channel bot with a web dashboard. Monitors a Meshtastic mesh network channel via serial connection, responds to commands, tracks nodes, logs chat history, and exposes a local web UI for monitoring and sending messages.

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
