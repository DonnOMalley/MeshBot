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
- Multi-page web dashboard (Flask) with dashboard, nodes, map, chat, console, and about pages
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
NoNodeInit        = false
NodeRetentionDays = 30
EncryptionKey     =
EventsPasscode    =
AdminUsername     =
AdminPassword     =
Verbose           = false
HideSecondaryChannels = false
WebUrl            = localhost
WebPort           = 7331
RangeTestRequests = 5
RangeTestDelay    = 1
```

| Key                     | Description                                                                                            |
| ----------------------- | ------------------------------------------------------------------------------------------------------ |
| `bot_name`              | Display name of the bot. Used in messages and as the command prefix (`@BotName`).                      |
| `bot_description`       | Optional description shown in the web header beneath the bot name.                                     |
| `Channel`               | Channel name to join on startup. Omit to be prompted at launch.                                        |
| `CaseSensitive`         | When `true`, command prefix and names must match exact case.                                           |
| `ExcludeOOTB`           | When `true`, built-in commands (`ping`, `test`, `hello`, `last`) are not registered.                   |
| `NoNodeInit`            | When `true`, skips node configuration on startup and shutdown. Default: `false`.                       |
| `NodeRetentionDays`     | Days of inactivity before a node is removed from the local database. Default: `30`.                    |
| `EncryptionKey`         | Passphrase to encrypt the node database and chat history. Leave blank for plain text.                  |
| `EventsPasscode`        | Passcode organizers enter on the Events page to publish, edit, approve or delete events. Blank turns editing and public submissions off. |
| `AdminUsername`         | Username for the admin login that opens the **Administration** menu (Console, Claude and Storage pages). |
| `AdminPassword`         | Password for the admin login. Separate from `EventsPasscode`. Leaving either admin key blank turns Administration off. |
| `Verbose`               | When `true`, prints received messages, dispatched commands, and sent notifications.                    |
| `HideSecondaryChannels` | When `true`, secondary channels are hidden from the web dashboard (chat, dashboard, settings pages).   |
| `WebUrl`                | Hostname shown in the console startup message. Does not change the bind address. Default: `localhost`. |
| `WebPort`               | Port the web dashboard listens on. Default: `7331`.                                                    |
| `RangeTestRequests`     | Number of messages sent by `!range`. Clamped 1–10. Default: `5`.                                       |
| `RangeTestDelay`        | Delay in minutes between `!range` messages. Clamped 1–10. Default: `1`.                                |

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
python meshbot.py MyBot --NoNodeInit
python meshbot.py MyBot --RangeTestRequests 3 --RangeTestDelay 2
python meshbot.py --Config path/to/my.config
```

### Hiding Secondary Channels

Set `HideSecondaryChannels = true` in your config file (or pass `--HideSecondaryChannels` on the command line) to hide all secondary channels from the web dashboard. When enabled, only the primary channel is shown in the Chat, Dashboard, and Settings pages. This is useful for deployments where you want to restrict web access to the main channel only.

Press **Ctrl+C** to stop.

---

## Built-in Commands

Commands are sent in the monitored channel or via DM, prefixed with `!`:

| Command           | Description                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| `!hello`          | Bot greets the sender.                                                                                              |
| `!ping`           | Bot replies with `Pong! 🏓`.                                                                                        |
| `!test`           | Bot replies with the hop count (`Hops: N 🐇`), or confirms a direct connection.                                     |
| `!last N CHANNEL` | Returns the last N messages from the specified channel as DMs (max 5).                                              |
| `!trace`          | Sends a traceroute to the requester and reports the route, SNR readings, and duration.                              |
| `!range`          | Sends a series of range-test messages. Count and delay are configured via `RangeTestRequests` and `RangeTestDelay`. |
| `!web`            | Replies with the web dashboard URL so any mesh node can find the portal.                                            |
| `!cmdList`        | Lists all registered commands.                                                                                      |

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

### Event commands

Mesh nodes can ask about the published events on the Events page. Replies are sent as DMs and always fit the mesh message size (counted in bytes, so emoji are safe). Times are shown in each event's own time zone.

| Command                | Reply                                                                                                                   |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `!event`               | One short message: the next event (or the one happening now) with its name, start time and place.                      |
| `!events`              | A numbered list of the next 5 events. A repeating event is listed once, at its next date.                              |
| `!eventinfo [N\|name]` | Full details of one event: time, repeat, place or link, description, website and contact. `N` is the number from `!events` (none = the next event); other text matches the event name. Long details are split into up to 5 numbered messages (`1/3 …`), 2 seconds apart. |

Only approved events are shown. The commands only read the event files; moving ended events to the history file is left to the dashboard.

---

## Web Dashboard

A Flask web dashboard starts automatically and is accessible from any machine on the network. The URL is printed to the console on startup and included in the bot's welcome message.

```
http://localhost:7331
```

Use `--WebUrl` and `--WebPort` (or the config file equivalents) to change the address.

### Pages

| Page      | Path        | Description                                                                                                                                |
| --------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Dashboard | `/`         | A full-width banner shows any event happening now (picture, click to open it). Joy leads the page: the affirmation in large type with the quote and joke beneath, and a Coming up rail of the next 3 events with pictures beside it (repeats included, each opening its details). On wide screens Joy is as tall as that rail, leaving the rest of the page to Mesh Chat and Today in History below. Section titles open their full pages. |
| Mesh      | `/mesh`     | Mesh dashboard: channel chat history, node counts (known, heard in the last hour / 24h, direct, on the map), the bot's own node, and a mini-map. The **Mesh** menu also holds Nodes, Map and Chat. |
| Nodes     | `/nodes`    | Full-page node table.                                                                                                                      |
| Map       | `/map`      | Interactive map of all positioned nodes. Includes sidebar filter, marker selection, and a bot-locate button when the bot is reporting GPS. |
| Chat      | `/chat`     | Full-page chat with per-channel tabs and message send form.                                                                                |
| Joy       | `/joy`      | A "Happening now" banner for each event in progress (its picture shown large, with Share photos / Details buttons); all the affirmations, a fresh set of quotes and jokes (↻ for more), and past events with their shared photo albums (the album link and photo thumbnails open the event straight into its photo viewer), plus a link to upcoming events. |
| History   | `/history`  | Today in History calendar: opens on today's date; pick another day to see its historical events.                                           |
| Events    | `/events`   | Community events calendar (calendar or agenda view); opens on today's events. Organizers add/edit events, visitors submit events for review, and anyone can upload photos while an event is happening. |
| Claude    | `/claude`   | Read-only list of the Claude Code sessions on this computer and their conversations. Admin only. |
| Storage   | `/storage`  | Sizes of the bot's `data/` and `log/` folders: overview, folder tree or file-type groups, and details for each. Admin only. |
| Console   | `/console`  | Live bot console terminal; mirrors all stdout/stderr output. Admin only.                                                                   |
| Bot Test  | `/dm`       | Interactive direct-message session with the bot; includes quick-command buttons and a live chat window.                                    |
| Settings  | `/settings` | Read-only view of the connected device's LoRa, device, owner, and channel configuration.                                                   |
| About     | `/about`    | General (bot info, release notes), Interaction (commands, dashboard guide, usage notes) and Configuration tabs.                            |

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

The **Bot Test** page (`/dm`) lets you send direct messages to the bot from the browser without needing a physical Meshtastic device. A one-time identity setup associates your browser session with a fake Meshtastic node (the same identity used on the Chat page). Quick-command buttons for `!hello`, `!ping`, `!test`, `!last`, `!trace`, `!web`, `!joke`, `!event`, `!events` and `!eventinfo` let you test common commands with one click. Responses appear in a live conversation window that is not saved to the channel chat logs.

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
- Web addresses (`http://`, `https://` or `www.`) in messages are clickable and open in a new tab.

### Events

The **Events** page (`/events`, next to History in the menu) lists community events on a month calendar or as an agenda; the chosen view is remembered per browser. Click a day to see its events and an event to see its details. Addresses open in maps, and websites, meeting links and links in the description are clickable; a phone number gets a call link and, if it accepts texts, a text link.

- The event form has: name, description, start and end (tick **All-day event** to pick dates only; the event then runs from midnight at the start of the first day to midnight after the last day, shows as "All day", lands on the same dates in every time zone, and is exported to calendars as an all-day entry), in-person address or online link, website, a picture, and organizer contact (name, Signal handle, phone, and whether the phone accepts texts). Events without a picture use a default image.
- While an event is happening (between its start and end), its details show **Take a photo** (opens the device camera) and **Upload photos** (pick files). Photos are resized in the browser to 1600 px with a 400 px thumbnail. Before resizing, the browser reads the original file's details (name, type, size, dimensions, modified time) and its EXIF tags (camera, lens, exposure, ISO, dates and so on) and saves them with the photo. **GPS location is never read or sent**, and the server drops any GPS tag it receives anyway.
- **Photo viewer:** clicking a photo in an event's details opens it large in a pop-up on top of the event, with a strip of all the event's photos underneath. Use the ‹ › buttons, the arrow keys, a swipe, or click any thumbnail in the strip to switch photos. **Full size ↗** opens the photo in its own tab. A **Photo details** panel shows who uploaded it and when, the stored copy's size, the original file's details, and every EXIF tag saved with it. Photos uploaded before v0.10.0 have no saved details.
- **Downloading photos (organizers only):** when signed in, the photo viewer shows **⬇ Download** to save the current photo at full size, and the event's Photos section shows **⬇ Download all (.zip)** to get every participant photo in one ZIP file. Both are hidden from visitors, and the server refuses the downloads unless you're signed in.
- **Repeats:** an event can repeat **Weekly**, **Every other week**, **Monthly** (same day of the month; the 31st skips shorter months) or **Yearly** (Feb 29 only in leap years), with an optional **Until** date. Each date appears on the calendar and agenda, keeps its local time across daylight saving (the event's time zone is stored), and counts as "Happening now" for photo uploads and the dashboard. Editing changes the whole series; to drop one date (say a holiday week), an organizer opens that date and uses **Delete this date only** — it disappears everywhere (calendar, dashboard, Joy page, photo uploads, `.ics` file) and can be brought back with **Restore** in the event's details. (Google's add-to-calendar link can't carry skipped dates; the `.ics` file does.) A repeating event moves to the history file only after its last date. Google Calendar and the `.ics` file get the full series; the Outlook links add the next date only.
- Share a single event with `/events?id=<event id>` (the **Copy link** button).
- Add `&photo=<photo id>` to open that event with the photo viewer already showing that photo (an unknown photo id starts at the newest). The Joy page's photo links use this.
- **Add to calendar** (on published events that haven't ended) offers Google Calendar, Outlook.com and Outlook for work or school (each opens that calendar's new-event page already filled in), plus an `.ics` file for Apple Calendar / iPhone and any other calendar app (`/events/<event id>/calendar.ics`). The calendar entry includes the description, meeting link or address, website and a link back to the event page.
- **Organizer passcode:** publishing, editing, approving and deleting events needs the passcode set as `EventsPasscode` in `meshbot.config`. Organizers click **Organizer sign-in** (or **Edit event**) and enter it once; they stay signed in until the browser closes or they sign out. Five wrong tries from one address lock it out for 15 minutes. The passcode is read from the config file on each check, so changing it takes effect right away (and signs everyone out). Viewing events and uploading photos during an event never need the passcode.
- **Visitor submissions:** visitors who are not signed in see **Submit an Event** instead of **New Event**. Their event is saved as *pending review* and stays hidden from everyone else (calendar, details, picture and photo uploads) until an organizer approves it. An address can submit 5 events per hour, and only events that have not ended yet can be submitted.
- **Reviewing:** signed-in organizers see a "⏳ N events waiting for review" bar, and days with pending events get an orange dot. Open a pending event to check it (use **Edit event** to fix anything), then **Approve & publish** or **Reject** (deletes it and its picture). Organizers' own events are published straight away. A submission nobody approves is deleted, with its picture, once its end time passes.
- With no `EventsPasscode` set, event editing and visitor submissions are both off.
- The dashboard is plain HTTP, so the passcode is sent unencrypted over the network; use HTTPS (e.g. a reverse proxy) if that matters.

### Menus and admin sign-in

The menu bar has **Dashboard**, **Mesh** (Dashboard, Nodes, Map, Chat), **Joy**, **History**, **Events** and **Administration**. A gear at its right end opens **Settings**, which holds the Settings, Bot Test and About pages. On a phone they all sit in the ☰ menu.

- **Administration** (Console, Claude and Storage pages) needs the admin login set as `AdminUsername` and `AdminPassword` in `meshbot.config`. When you're not signed in, clicking Administration opens a sign-in page (`/admin/login`), and opening `/console`, `/claude` or `/storage` directly goes there too. After signing in you're taken back to the page you asked for.
- Once you're signed in, Administration becomes a menu with Console, Claude, Storage and **Sign out**. You stay signed in until the browser closes or you sign out.
- Five wrong tries from one address lock sign-in for 15 minutes. The login is read from the config file on every request, so changing it takes effect right away and signs every admin out. With either key blank, Administration is off.
- The admin login is separate from `EventsPasscode`: signing in to one never opens the other.

### Claude Sessions

The **Claude** page (`/claude`, in the **Administration** menu) shows the Claude Code sessions stored on the computer running the bot, read from `~/.claude` of the user the bot runs as.

- **Sign-in:** needs the admin login (see [Menus and admin sign-in](#menus-and-admin-sign-in)).
- **All sessions summary** (top of the page): recorded cost, tokens in (new input plus cache writes), cache reads, tokens out, and the date range from the first session's start to the last activity. Totals cover every stored session, not just the filtered list, and include the tokens used by each session's subagents. Hover a token total for the exact count.
- **List:** every session, most recent first, with its title, folder, last activity, number of turns, tokens used and subagents. Sessions that are open right now are marked **● open** or **● working**. Filter by title, folder or first prompt, and by date with **From**/**To** (filled in automatically with the first and last day in the history; a session shows when any of its activity falls in the range; **All dates** goes back to the full range). The list refreshes every 30 seconds.
- **Conversation:** click a session to read your prompts, Claude's replies and a one-line summary of each tool call (hide them with **Show tool calls**). Tool *results* (command output, file contents) and Claude's thinking are never sent to the browser, since that is where secrets are most likely to appear. Very long sessions show their newest 1,500 entries.
- **Read-only:** the page cannot start, stop or message a session.
- Claude Code deletes old sessions after `cleanupPeriodDays` in `~/.claude/settings.json` (30 days by default), so they also disappear from this page.
- The session file format is internal to Claude Code and may change between versions; records the page does not recognise are skipped.
- Like the Events passcode, the admin password and the session text travel unencrypted over plain HTTP. Use HTTPS (e.g. a reverse proxy) before signing in over the internet.

### Storage

The **Storage** page (`/storage`, in the **Administration** menu) shows how much space the bot's own folders use: `data/` (node database, chat history, map tile cache, events and their photos, caches) and `log/` (console logs).

- **Sign-in:** needs the admin login (see [Menus and admin sign-in](#menus-and-admin-sign-in)).
- **Overview** (top of the page): total size, file and folder counts, the largest folder, each top folder's size, free disk space, the most recent change, and a **By file type** bar. Click a file type under the bar to open it.
- **Folders / File types** (left): switch between a folder tree (click ▸ to expand; each row has a bar showing its share of its parent) and file-type groups (Images, Data, Text & chat, Logs, Runtime, Other) with their extensions. The filter box narrows either list.
- **Details** (right): for a folder, its size, file-type mix, subfolders, its own files, and the largest and most recently changed files inside it; for a file type, its total and average size, its extensions, the folders it lives in (click one to open it) and its largest files. Known folders and files get a plain-English label (for example *Map tile cache*, *Node database*).
- **Read-only:** the page only reads names, sizes and dates. It never opens, downloads or deletes a file, and only folders inside `data/` and `log/` can be looked up. Symlinks are skipped. Results are cached for 15 seconds and the page refreshes every minute.

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
    today_in_history_api.py     Today in History cache
configuration/
    node_configuration.py       Node config loading
data/
    nodes.json                  Persisted node database
    favorites.json              Persisted favourite nodes
    <channel_name>.txt          Chat history per channel
    Events/
        events.json             Events that have not ended yet
        events_history.json     Events that have ended (moved here automatically;
                                unapproved submissions are deleted instead)
        images/<event id>/      Event picture and participant photos (+ thumbnails,
                                and <photo id>_exif.json with each photo's details)
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
tests/
    test_events.py              Event store + Events API tests
    test_event_commands.py      Mesh !event / !events / !eventinfo commands
    test_claude.py              Claude sessions reader + /claude page tests
    test_storage.py             Storage scanner + /storage page tests
    test_linkify_js.py          Clickable chat links (linkify in app.js, needs Node)
                                (run: .venv/bin/python -m unittest discover -s tests -t .)
log/
    console_<timestamp>.log     Console output log (one per session, git-ignored)
web/
    web_server.py               Flask web server
    event_store.py              Event storage (encrypted event JSON, plain images + EXIF)
    claude_sessions.py          Read-only reader for Claude Code sessions (~/.claude)
    storage_scanner.py          Read-only sizes of data/ and log/ for the Storage page
    static/
        app.js                  Shared JS module (nodes, channels, history)
        chat.js                 Page init for /chat
        claude.js               Claude page (/claude): sign-in, session list, conversation
        claude.css              Claude page styles
        console.js              Page init for /console (terminal polling)
        events.js               Events page (calendar, agenda, form, photo uploads)
        mesh.js                 Mesh dashboard (/mesh): node stats, bot node, mini-map
        nodes.js                Page init for /nodes
        storage.js              Storage page (/storage): overview, folder tree, file types, details
        storage.css             Storage page styles
        style.css               Dashboard styles
    templates/
        partials/
            _header.html            Shared nav header partial (included by all pages)
        about.html              About page
        chat.html               Chat full-page view
        console.html            Console terminal page
        events.html             Events page
        index.html              Dashboard page
        mesh.html               Mesh dashboard page
        nodes.html              Nodes full-page view
```

---

## Data & Encryption

Node records are stored in `data/nodes.json`. Chat history is stored per-channel as `data/<channel_name>.txt`. Favourites are stored in `data/favorites.json`.

Events are stored in `data/Events/`: `events.json` holds events that have not ended, and `events_history.json` holds past events. An event moves to the history file automatically once its end time passes (and back again if it is edited to end in the future). A visitor submission that was never approved is deleted at that point instead. Each event's picture and participant photos are stored under `data/Events/images/<event id>/`, named for their real type (`cover.jpg`, `<photo id>_thumb.png`, ...). Images are saved exactly as uploaded and are never encrypted, so they open directly in any image viewer and download as-is. Each participant photo's details (EXIF, never GPS) sit beside it in `<photo id>_exif.json` as plain JSON, also never encrypted.

When an `EncryptionKey` is provided, the node database, favourites, chat history and the two event files are encrypted using AES via the `cryptography` package. Event pictures, photos and photo EXIF are never encrypted. All instances sharing the same data files must use the same key.

---

## Release Notes

### v0.13.7 — 2026-11-27

- The **Settings** page's **Device Settings** panel now shows the connected node's **Firmware Version** as its first row. It comes from the device metadata the node sends when the bot connects, and shows "—" if the node didn't report one.

### v0.13.6 — 2026-11-27

- The **Events** page's **Agenda** view has a **Hide past events** checkbox next to the month selector. It is ticked each time the page opens, so the agenda shows only events still to come or happening now, with a note saying how many past events are hidden. Untick it to see that month's past events too, listed below the upcoming ones under a **Past events** heading.

### v0.13.5 — 2026-11-27

- The **Dashboard**'s Joy panel is about a third shorter, giving **Mesh Chat** and **Today in History** more room. **Coming up** now shows the next 3 events instead of 4, and on wide screens Joy is as tall as that list: its text is a bit smaller, and a long joke scrolls inside the panel rather than making it taller. When Joy and Coming up stack on narrower screens, Joy keeps its full height.

### v0.13.4 — 2026-11-27

- On the **Joy** page, **Open photo album →** under a past event now opens the event with its photo viewer already showing, starting at the newest photo, so you don't have to click a photo first. Clicking one of the card's photo thumbnails opens the viewer on that photo, and the **+N** tile opens it on the first photo not shown on the card. Closing the viewer leaves the event's details open. The event's title still just opens the event.
- Event links can now name a photo: `/events?id=<event id>&photo=<photo id>` opens the event and then that photo in the viewer. Links without `photo`, such as **Copy link**, work as before.

### v0.13.3 — 2026-11-27

- Photo EXIF details are no longer encrypted, even with an `EncryptionKey`. They are saved as plain `<photo id>_exif.json` beside each photo, like the photos themselves. The existing encrypted EXIF files were converted once by hand. Event pictures, photos and EXIF now have no encrypted form at all: the bot neither writes nor reads `.enc` files for them any more, so no leftover encrypted copies can build up when a picture is replaced or removed.
- The Storage page no longer has an **Encrypted** (`.enc`) file-type group, since the bot doesn't create `.enc` files any more.
- Event details, chat history, favourites and the node database are still encrypted when an `EncryptionKey` is set.
- The **Dashboard**'s chat panel is titled **Mesh Chat** (it said "Chat history"), matching the Mesh dashboard.

### v0.13.2 — 2026-11-27

- Links in chat are now clickable. Any `http://` or `https://` address, or a bare `www.` address, in a message on the **Dashboard**, the **Mesh** dashboard's Mesh Chat, the **Chat** page and the **Bot Test** page opens in a new tab. A full stop, comma or closing bracket straight after a link is not treated as part of it. Only web links are made clickable; the rest of the message is shown exactly as before.

### v0.13.1 — 2026-11-27

- Event pictures and participant photos are no longer encrypted, even with an `EncryptionKey`. They are saved exactly as uploaded (`cover.jpg`, `<photo id>_thumb.png`, ...), so they open straight from `data/Events/images/` in any image viewer and download as-is. Event details, chat history, the node database and photo EXIF stay encrypted. Existing encrypted images were converted once by hand; the bot does not read `.enc` images anymore.

### v0.13.0 — 2026-11-26

- New **Storage** page (`/storage`, under **Administration**): an overview of the bot's `data/` and `log/` folders (total size, largest folder, free disk space, last change, size by file type), a left panel that switches between a folder tree and file-type groups, and details for each folder or type (subfolders, file-type mix, largest and newest files). Read-only.

### v0.12.0 — 2026-11-26

- New mesh commands for events: `!event` (the next event in one message), `!events` (numbered list of the next 5) and `!eventinfo [N|name]` (full details, split into several messages when long).
- The About page's command reference now covers them, plus `!affirm`, `!tih` and `!tih_link`, which were missing. The Bot Test page has Event, Events and Event Info buttons.
- New **Settings** menu: a gear at the right end of the menu bar holds Settings, Bot Test and About.
- **Administration** now needs an admin login (`AdminUsername` and `AdminPassword` in `meshbot.config`): clicking it opens a sign-in page, and it holds Console, Claude and Sign out. The Console is admin-only now, and the admin login replaces `ClaudePasscode` for the Claude page.

### v0.11.1 — 2026-11-26

- The Claude page opens with an **All sessions** summary: recorded cost, tokens in, cache reads, tokens out, and the date range from the first session to the latest activity.
- Session token counts now include the work done by each session's subagents.

### v0.11.0 — 2026-11-26

**Claude sessions page**

- New **Claude** page (`/claude`, under **Administration**) lists the Claude Code sessions on this computer: title, folder, last activity, turns, tokens, and whether each one is open right now. Click one to read the conversation and its tool calls; tool output and thinking are never shown.
- Protected by its own passcode, `ClaudePasscode` in `meshbot.config`, separate from the Events passcode. With none set, the page is off.

### v0.10.3 — 2026-11-26

**Mobile layout fixes**

- **Event pop-ups** no longer slide under the phone's address bar. They leave a gap above the top edge, size themselves to the part of the screen you can actually see, and on phones the **×** close button is larger and stays pinned to the top while you scroll through a long event.
- **Mesh dashboard** on phones: Mesh Chat is no longer squeezed down to a single line. Panels now stack as Mesh Chat (most of the screen), Nodes, Map, then Bot Node details last. The desktop layout is unchanged.

### v0.10.2 — 2026-11-26

**Event photo downloads (organizers only)**

- Signed-in organizers get a **⬇ Download all (.zip)** button in an event's Photos section. It downloads every participant photo at full size in one ZIP (`<Event-Name>-photos.zip`), numbered in upload order and named for the uploader (`001-Sam-Smith-<photo id>.jpg`). The event's own picture isn't included.
- The photo viewer has a **⬇ Download** link beside **Full size ↗** that saves the photo being viewed as `<Event-Name>-001-Sam-Smith-<photo id>.jpg`.
- Both are hidden unless you're signed in with the organizer passcode, and appear or disappear straight away when you sign in or out. The server refuses `/events/<event id>/photos.zip` and `/events/<event id>/photos/<photo id>/download` with a 403 unless the session is signed in. Viewing photos is unchanged for everyone.

### v0.10.1 — 2026-11-26

- The **About** page is split into three tabs: **General** (about the bot and the release notes), **Interaction** (command reference, web dashboard guide and usage notes) and **Configuration** (configuration reference). The tab is kept in the address (`/about#interaction`), so links and reloads open the same tab; arrow keys move between tabs.
- Removed the one-time `.img` image rename from v0.9.1 now that all images use their real file type. Startup no longer scans the event image folders, and `.img` files are no longer read.
- Photo viewer fixes:
  - Large EXIF sets that were accepted on upload no longer vanish when read back. EXIF is stored as compact JSON and the size limit is applied to that stored form.
  - Flipping quickly between photos (A → B → A) no longer shows the details twice.
  - A failed details request (a brief server error, say) shows **Try again** instead of "No details were saved", and it isn't remembered for the rest of the visit.
  - EXIF is now read from PNGs that keep it after the image data, and Unicode UserComments from big-endian (Motorola) files decode correctly.
  - The keyboard focus ring now shows on the selected thumbnail in the photo strip.

### v0.10.0 — 2026-11-26

**Event photo viewer**

- Clicking a participant photo opens it large in a pop-up on top of the event details (no more new browser tab), with a carousel strip of all the event's photos underneath. Switch photos with the ‹ › buttons, the arrow keys, a swipe on phones, or by clicking any thumbnail. The strip keeps the current photo highlighted and in view. **Full size ↗** still opens the photo in its own tab. Escape or a click outside closes the viewer and leaves the event open.
- A **Photo details** panel lists the uploader and upload time, the stored copy's size, the original file's name, type, size, dimensions and modified time, and every EXIF tag from the original photo (camera and lens, exposure time, aperture, ISO, focal length, flash, dates and more) in readable form. On phones the panel sits under the photo.
- EXIF is read in the browser before the photo is resized (resizing removes all metadata) and saved beside the photo as `<photo id>_exif.json`, encrypted when an `EncryptionKey` is set. It loads from `/api/events/<event id>/photos/<photo id>/exif` only when a photo is opened, so event lists don't get heavier. Works for JPEG, PNG and WebP originals.
- **GPS location is never saved.** The browser never reads the GPS block, and the server drops any GPS tag it receives anyway. Photos uploaded before this version have no saved details.

### v0.9.1 — 2026-11-26

- Event pictures and participant photos are saved with their real file type, worked out from the image itself: `cover.jpg`, `<photo id>_thumb.png`, and so on, instead of `.img` for everything. Encrypted images end in `.enc` (`cover.jpg.enc`), so you can tell what each file is; without an `EncryptionKey` they open directly from disk.
- Images saved by older versions as `.img` are renamed automatically when the bot (or web reload) starts. Encrypted files are renamed, not re-encrypted. A file that can't be read with the current key keeps its `.img` name.
- Replacing a picture with one of a different type (JPEG to PNG, say) removes the old file.

### v0.9.0 — 2026-11-26

**Events, grown up**

- **Repeating events**: weekly, every other week, monthly or yearly, with an optional "Until" date. Repeats keep their local time across daylight saving; monthly on the 31st skips shorter months and Feb 29 only falls in leap years. Every date shows on the calendar, agenda, dashboard and Joy page, and a series moves to history only after its last date.
- **Delete a single date** of a repeating event ("Delete this date only"). Skipped dates disappear everywhere, including the `.ics` file, and can be restored from the event's details.
- **All-day events**: an "All-day event" checkbox switches to date-only inputs. All-day events show on the same dates in every time zone and export as true all-day entries.
- **Add to calendar** on event details: Google Calendar, Outlook.com and Outlook (work or school) open pre-filled; Apple Calendar and other apps download a standard `.ics` file from `/events/<id>/calendar.ics`. Repeating events export the full series to Google and `.ics`.
- **Live camera capture on desktop**: "Take a photo" opens a camera dialog with live preview, capture and camera switching on laptops and tablets. Phones and plain-HTTP pages keep the native camera button.
- Show/hide eye button on the organizer passcode box.
- History and Events pages open on today's date (a shared `/events?id=` link still opens that event).

**Joy page** (`/joy`)

- New page with an affirmation, a quote and a joke, each with its own 🎲 button for another one.
- **Past Events & Photos**: finished events (and repeating ones that have photos), newest first, with a thumbnail strip and photo count linking to the album.
- A **Happening now** banner leads the page while an event is on, with "Share photos" and "Details" buttons.

**Dashboard redesign**

- Joy is the headline: the affirmation in large serif type, then the quote and the joke.
- A **Coming up** rail beside Joy shows a picture card for each upcoming event date in the next 30 days (up to 8, repeats expanded).
- A full-width **Happening now** banner appears above everything while an event is on; events in progress show only there.
- Chat history and Today in History sit below as quieter reading panels; Today in History is now a year/event timeline.
- Panel titles link to their full pages; the Events panel gets a ↻ refresh button.
- Short laptop screens scroll instead of clipping; narrow screens stack.

**Mesh menu and `/mesh` dashboard**

- Nodes, Map and Chat are grouped under a new **Mesh** dropdown.
- New `/mesh` page with node counts, the bot's own node and the mini-map (moved off the main dashboard).

**Fixes**

- Events API returns every happening-now date and applies `limit` only to upcoming ones, so live events can't crowd out the dashboard rail.
- Recurrence labels come from one place on the server (`recurrence_label`).
- Mesh page Refresh re-fetches the bot's node info, so it recovers from an initial `/api/settings` failure.
- Camera dialog no longer leaks streams, cycles through real device IDs, has an accessible name, and doesn't restart in a loop when device listing fails.
- Fixed a `map.js` refresh recursion.

### v0.8.0 — 2026-11-24

**Events page** (`/events`)

- Month calendar or agenda view (your choice is remembered). Click a day to list its events, or an event to see its details: map links for addresses, meeting links, website, and organizer call/text/Signal links.
- Create, edit and delete events with a name, description, times, in-person address or online link, website, picture and organizer contact details. Events without a picture use a default image.
- While an event is happening, participants can take or upload photos. Images are resized in the browser, which also strips EXIF location data.
- Signed-in organizers can download one photo or all of an event's photos as a ZIP file.
- Events and images are stored in `data/Events/` and encrypted with the same `EncryptionKey` as the chat logs. Events move to the history file once they end.
- **Organizer passcode** (`EventsPasscode` in `meshbot.config`, applied without a restart) protects adding, editing and deleting. Wrong guesses are rate-limited, and changing the passcode signs everyone out.
- **Visitor submissions**: anyone can submit an upcoming event for review (5 per hour per address). Organizers see a review bar to approve or reject submissions. Unapproved submissions are deleted when they end.

**Dashboard and web UI**

- **Hot reload**: HTML/JS/CSS edits show up on a browser refresh. `reload_web.sh` (SIGUSR1) swaps in new web server code without restarting the radio or monitors; if the new code fails, the previous dashboard keeps serving.
- On phones the menu moves behind a ☰ hamburger button, with Administration pages under their own heading.
- The dashboard Joy panel gets a ↻ refresh button and lists events that are happening now.
- An Events panel sits beside Joy on the dashboard, backed by a new `/api/events/upcoming` endpoint.
- Today in History lists events newest year first.
- The History page panel stays full width on days with no events.

**Bot and nodes**

- The node list stays current from all mesh traffic, not just NodeInfo packets: any packet updates last-seen, position packets update location, and hop counts come from the packet.
- Restarts no longer stamp every remembered node as "seen now"; the radio's own last-heard time is used instead.
- Stale nodes are pruned hourly while running, not just at launch. The node file is saved at most once a minute (atomically) and flushed on shutdown.
- CLI flags accept lowercase (`--channel` as well as `--Channel`), and `meshbot.config` keys are case-insensitive with tolerant true/false parsing.
- The startup message names the joined channel. The check-in interval is now 7 days instead of 6 hours.
- The bot writes `data/meshbot.pid` so `reload_web.sh` only signals a bot that supports hot reload.
- Runtime logs, local config backups (`*.bak-*`) and editor swap files are kept out of git.

### v0.7.2 — 2026-03-30

- The hop limit applied to the node on startup is raised from 5 to 7.
- `!trace` catches traceroute send errors and logs them instead of crashing the command handler.
- Channel lookup falls back to the primary channel when no channel name is given.

### v0.7.1 — 2026-03-20

- Added `--HideSecondaryChannels` CLI/config option. When enabled, only the primary channel is shown in the Chat, Dashboard, and Settings pages of the web dashboard. Secondary channels are hidden from all web UI.

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
