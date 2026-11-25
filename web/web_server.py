from __future__ import annotations
import configparser
import hashlib
import hmac
import importlib
import json
import logging
import os
import random
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import cast

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, session
from google.protobuf.json_format import MessageToDict
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface
from pubsub import pub
from werkzeug.serving import BaseWSGIServer, make_server

from commands.user_commands import UserCommands
from common.chat_history import ChatHistory
from common.console_logger import ConsoleLogger
from common.constants import (
    CHANNEL_NAME_PRIMARY,
    _CHAT_HISTORY_BOT_SENDER,
    _DEFAULT_BOT_DESCRIPTION,
    _DM_RESPONSE_WAIT_SECS,
    _EXCLAMATION_PREFIX,
    _README_FILENAME,
    _EVENT_TRACEROUTE,
    _FAVORITES_FILE,
    _GITHUB_REPO_URL,
    _NODE_DB_DIR,
    _NODE_DB_SALT_FILE,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_FROM_ID,
    _PACKET_KEY_TO_ID,
    _PACKET_KEY_TRACEROUTE,
    _PACKET_KEY_TRACE_ROUTE,
    _PACKET_KEY_TRACE_ROUTE_BACK,
    _PACKET_KEY_TRACE_SNR_TOWARDS,
    _PACKET_KEY_TRACE_SNR_BACK,
    _PACKET_KEY_WEB_RESPONSES,
    _TRACE_HOP_LIMIT,
    _TRACE_LABEL_BOT,
    _TRACE_SNR_SCALE,
    _WEB_DASHBOARD_URL,
    _WEB_SERVER_DISPLAY_HOST,
    _WEB_SERVER_HOST,
    _WEB_SERVER_MAX_SEND_LENGTH,
    _WEB_SERVER_HISTORY_LIMIT,
    _WEB_SERVER_PORT,
    _WEB_SERVER_STARTED,
    _WEB_USER_LONG_NAME_DEFAULT,
    _WEB_USER_LONG_NAME_MAX_LEN,
    _WEB_USER_MESSAGE_PREFIX_FORMAT,
    _WEB_USER_NODE_ID_BYTE,
    _WEB_USER_SHORT_NAME_DEFAULT,
    _WEB_USER_SHORT_NAME_MAX_LEN,
    _WEB_USER_SHORT_NAME_PREFIX,
    _WEB_USER_ERR_LONG_NAME,
    _WEB_USER_ERR_SHORT_NAME,
)
from common.constants import (
    _RELOAD_STATE_SECRET_KEY,
    _RELOAD_STATE_WEB_USERS,
    _WEB_SERVER_STOP_TIMEOUT_SECONDS,
    _AFFIRM_CACHE_FILE,
    _JOKE_CACHE_FILE,
    _TILE_MAX_ZOOM,
    _TODAY_IN_HISTORY_FILE_FORMAT,
    _TODAY_IN_HISTORY_KEY_TEXT,
    _TODAY_IN_HISTORY_KEY_WIKIPEDIA,
    _TODAY_IN_HISTORY_KEY_YEAR,
    _TODAY_IN_HISTORY_SUBDIR,
    _ZEN_QUOTES_CACHE_FILE,
    _ZEN_QUOTES_KEY_AUTHOR,
    _ZEN_QUOTES_KEY_QUOTE,
)
from common.constants import (
    _CONFIG_SECTION,
    _DEFAULT_CONFIG_FILE,
    _EVENTS_AUTH_DISABLED,
    _EVENTS_AUTH_LOCKED,
    _EVENTS_AUTH_MAX_FAILURES,
    _EVENTS_AUTH_REQUIRED,
    _EVENTS_AUTH_WINDOW_SECONDS,
    _EVENTS_AUTH_WRONG,
    _EVENTS_PASSCODE_CONFIG_KEY,
    _EVENTS_SESSION_EDITOR_KEY,
    _EVENTS_NOT_APPROVED,
    _EVENTS_SUBMIT_DISABLED,
    _EVENTS_SUBMIT_ENDED,
    _EVENTS_SUBMIT_LIMITED,
    _EVENTS_SUBMIT_MAX_PER_WINDOW,
    _EVENTS_SUBMIT_WINDOW_SECONDS,
    _EVENTS_MAX_IMAGE_BYTES,
    _EVENTS_MAX_PHOTOS_PER_UPLOAD,
    _EVENTS_MAX_UPLOAD_BYTES,
    _EVENTS_STATUS_ACTIVE,
    _EVENTS_STATUS_PAST,
    _EVENTS_SUBDIR,
    _EVENTS_UPLOADER_MAX_LEN,
)
from common.encryption_helper import EncryptionHelper
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from configuration.node_configuration import NodeConfiguration
from messaging.command_register import CommandRegister
from web.tile_cache import TileCache
import web.event_store as _event_store_module

# Re-read the event store from disk whenever this module is (hot) reloaded.
importlib.reload(_event_store_module)
from web.event_store import EventStore, EventStoreError, build_ics, upcoming_occurrences  # noqa: E402  (after the reload on purpose)

_dm_response_tl: threading.local = threading.local()


class _CapturingIface:
    """Proxy around a real MeshInterface that captures sendText calls.

    Instead of transmitting messages over the mesh, each call to ``sendText``
    appends the message text to the per-request list stored in
    ``_dm_response_tl.responses``.  All other attribute access is forwarded
    transparently to the underlying real interface.
    """

    # region Protected Variables
    _real: MeshInterface
    # endregion Protected Variables

    # region Constructor
    def __init__(self, real_iface: MeshInterface) -> None:
        """Wraps a real MeshInterface for response capture.

        Args:
            real_iface: The underlying active MeshInterface to proxy.
        """
        self._real = real_iface
    # endregion Constructor

    # region Public Functions
    def sendText(self, text: str, **kwargs) -> None:
        """Captures the message text instead of transmitting over the mesh.

        Args:
            text: The message text that would have been sent.
            **kwargs: Ignored keyword arguments (destinationId, channelIndex, etc.).
        """
        if hasattr(_dm_response_tl, "responses"):
            _dm_response_tl.responses.append(str(text))

    def __getattr__(self, name: str) -> object:
        """Forwards all other attribute lookups to the real interface.

        Args:
            name: The attribute name to look up on the real interface.

        Returns:
            The attribute value from the underlying real interface.
        """
        return getattr(self._real, name)
    # endregion Public Functions


class WebUser:
    """Represents a web portal user with a fake Meshtastic-style identity.

    Each browser session is assigned a unique node ID derived from the session
    token, a default long name, and a default short name. Users may customise
    their long and short names within the constraints enforced by the server.
    """

    # region Private Variables
    _node_id: str
    _long_name: str
    _short_name: str
    # endregion Private Variables

    # region Public Properties
    @property
    def node_id(self) -> str:
        """The fake Meshtastic node ID assigned to this web user."""
        return self._node_id

    @property
    def long_name(self) -> str:
        """The display long name for this web user."""
        return self._long_name

    @property
    def short_name(self) -> str:
        """The short name (2–4 chars, must start with W) for this web user."""
        return self._short_name

    @property
    def display_name(self) -> str:
        """The full display name in the format 'Long Name (SHORT)'."""
        return f"{self._long_name} ({self._short_name})"
    # endregion Public Properties

    # region Constructor
    def __init__(self, session_id: str) -> None:
        """Initialises a new web user from a session ID.

        Args:
            session_id: The unique browser session token. Used to derive a
                        deterministic fake node ID.
        """
        hash_hex: str = hashlib.sha256(session_id.encode()).hexdigest()
        self._node_id = f"!{_WEB_USER_NODE_ID_BYTE}{hash_hex[2:8]}"
        self._long_name = _WEB_USER_LONG_NAME_DEFAULT
        self._short_name = _WEB_USER_SHORT_NAME_DEFAULT
    # endregion Constructor

    # region Public Functions
    def update(self, long_name: str, short_name: str) -> None:
        """Updates the user's long and short names.

        Args:
            long_name: The new long name (already validated by the caller).
            short_name: The new short name (already validated by the caller).
        """
        self._long_name = long_name
        self._short_name = short_name

    def to_dict(self) -> dict:
        """Serialises this web user to a JSON-friendly dict.

        Returns:
            A dict with ``node_id``, ``long_name``, ``short_name``, and ``display_name``.
        """
        return {
            "node_id": self._node_id,
            "long_name": self._long_name,
            "short_name": self._short_name,
            "display_name": self.display_name,
        }
    # endregion Public Functions


class WebServer:
    """Lightweight Flask web server running on a background daemon thread.

    Exposes REST API endpoints for the node list, channel chat history, and
    sending messages to the bot's active channel. Static assets and the
    single-page HTML template are served from the ``web/`` folder.
    """

    # region Protected Variables
    _bot_description: str
    _bot_name: str
    _capturing_iface: _CapturingIface
    _case_sensitive: bool
    _config: NodeConfiguration
    _verbose: bool = False
    _hide_secondary_channels: bool
    _display_host: str
    _node_db: NodeDatabase
    _iface: MeshInterface
    _channel: channel_pb2.Channel
    _channel_name: str
    _data_dir: str
    _passphrase: str | None
    _fernet_key: bytes | None
    _favorites: set[str]
    _event_store: EventStore
    _config_file: str
    _auth_failures: dict[str, list[float]]
    _submissions: dict[str, list[float]]
    _auth_lock: threading.Lock
    _pending_web_traces: dict[str, tuple[dict, float]]
    _port: int
    _tile_cache: TileCache
    _web_dir: str
    _web_users: dict[str, WebUser]
    _chat_history: ChatHistory | None
    _console_logger: ConsoleLogger | None
    _dm_command_register: CommandRegister
    _app: Flask
    _http_server: BaseWSGIServer | None
    _server_thread: threading.Thread | None
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        node_db: NodeDatabase,
        iface: MeshInterface,
        channel: channel_pb2.Channel,
        config: NodeConfiguration,
        bot_name: str,
        tile_cache: TileCache,
        bot_description: str = _DEFAULT_BOT_DESCRIPTION,
        case_sensitive: bool = False,
        data_dir: str = _NODE_DB_DIR,
        host: str = _WEB_SERVER_DISPLAY_HOST,
        passphrase: str | None = None,
        port: int = _WEB_SERVER_PORT,
        chat_history: ChatHistory | None = None,
        console_logger: ConsoleLogger | None = None,
        hide_secondary_channels: bool = False,
        verbose: bool = False,
        config_file: str = _DEFAULT_CONFIG_FILE,
    ) -> None:
        """Initialises the web server.

        Args:
            node_db: The node database used to serve the node list.
            iface: The active MeshInterface used to send messages.
            channel: The channel the bot is monitoring. Outgoing messages are
                     sent on this channel.
            config: The local node configuration used to build the DM command
                    register and identify the bot when constructing synthetic packets.
            bot_name: The runtime name of the bot, shown in the dashboard.
            tile_cache: The tile cache used to serve and refresh map tiles.
            bot_description: Short description shown alongside the bot name in the header.
            case_sensitive: When True the bot requires exact capitalisation for command names.
            data_dir: Directory containing chat history files. Defaults to the
                      shared ``data`` directory.
            host: Hostname displayed in the console startup message. Defaults to
                  'localhost'. This does not affect the network interface Flask
                  binds to; the server always listens on all interfaces.
            passphrase: Optional passphrase used to decrypt chat history files.
            port: Port number the web portal listens on. Defaults to
                  ``_WEB_SERVER_PORT``.
            chat_history: When provided, messages sent via the web dashboard are
                          appended to the log under the ``[BOT]`` sender label.
            console_logger: When provided, the ``/console`` page and ``/api/console``
                            endpoint serve live bot console output.
            hide_secondary_channels: When True, secondary channels are hidden from
                                     the chat, dashboard, and settings pages.
            config_file: The bot's config file. ``EventsPasscode`` is read from it
                         on each check, so changing it needs no restart.
        """
        self._bot_name = bot_name
        self._bot_description = bot_description
        self._case_sensitive = case_sensitive
        self._config = config
        self._verbose = verbose
        self._node_db = node_db
        self._iface = iface
        self._channel = channel
        self._tile_cache = tile_cache
        self._channel_name = channel.settings.name or CHANNEL_NAME_PRIMARY
        self._data_dir = data_dir
        self._display_host = host
        self._port = port
        self._passphrase = passphrase
        self._fernet_key = EncryptionHelper.resolve_key(
            passphrase, os.path.join(data_dir, _NODE_DB_SALT_FILE)
        ) if passphrase else None
        self._favorites = self._load_favorites()
        self._event_store = EventStore(os.path.join(data_dir, _EVENTS_SUBDIR), self._fernet_key)
        self._config_file = config_file
        self._auth_failures = {}
        self._submissions = {}
        self._auth_lock = threading.Lock()
        self._pending_web_traces = {}
        self._chat_history = chat_history
        self._console_logger = console_logger
        self._hide_secondary_channels = hide_secondary_channels
        pub.subscribe(self._on_web_traceroute_response, _EVENT_TRACEROUTE)

        self._capturing_iface = _CapturingIface(iface)
        
        self._dm_command_register = CommandRegister(
            iface=cast(MeshInterface, self._capturing_iface),
            config=config,
            channel=channel,
            passphrase=passphrase,
            chat_history=None,
            web_url=_WEB_DASHBOARD_URL.format(host=host, port=port),
            user_defined_commands=UserCommands(iface, config, channel, verbose=self._verbose).get_commands(),
        )
        
        #print("Command Register built with commands:", self._dm_command_register._commands.keys())

        _base = os.path.dirname(os.path.abspath(__file__))
        self._web_dir = _base
        self._app = Flask(
            __name__,
            template_folder=os.path.join(_base, "templates"),
            static_folder=os.path.join(_base, "static"),
        )
        self._app.secret_key = secrets.token_hex(32)
        # Pick up template edits on the next page load and stop browsers caching
        # static JS/CSS, so front-end changes need no reload at all.
        self._app.config["TEMPLATES_AUTO_RELOAD"] = True
        self._app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
        self._app.config["MAX_CONTENT_LENGTH"] = _EVENTS_MAX_UPLOAD_BYTES
        # Not sent on cross-site form posts, so other sites can't act as a signed-in organizer.
        self._app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        self._app.jinja_env.auto_reload = True
        self._http_server = None
        self._server_thread = None
        self._web_users = {}
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self._register_routes()
    # endregion Constructor

    # region Public Functions
    def start(self) -> None:
        """Starts the web server on a daemon background thread.

        Binds the port immediately, so a bind failure raises here (letting a
        hot reload fall back to the previous server). Can be called again
        after :meth:`stop`.
        """
        self._http_server = make_server(_WEB_SERVER_HOST, self._port, self._app, threaded=True)
        self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        self._server_thread.start()
        print(_WEB_SERVER_STARTED.format(host=self._display_host, port=self._port))

    def stop(self) -> None:
        """Stops serving requests and releases the port. Safe to call twice."""
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=_WEB_SERVER_STOP_TIMEOUT_SECONDS)
            self._server_thread = None

    def detach(self) -> None:
        """Unsubscribes from mesh events once this server is permanently replaced."""
        try:
            pub.unsubscribe(self._on_web_traceroute_response, _EVENT_TRACEROUTE)
        except Exception:
            pass

    def export_reload_state(self) -> dict:
        """Returns the in-memory state a reloaded server should inherit.

        Keeps browser sessions valid (same cookie signing key) and keeps each
        session's web-user names, so a reload is invisible to dashboard users.
        """
        return {
            _RELOAD_STATE_SECRET_KEY: self._app.secret_key,
            _RELOAD_STATE_WEB_USERS: {
                sid: (user.long_name, user.short_name) for sid, user in self._web_users.items()
            },
        }

    def import_reload_state(self, state: dict) -> None:
        """Adopts state exported by the server being replaced."""
        secret_key: object = state.get(_RELOAD_STATE_SECRET_KEY)
        if secret_key:
            self._app.secret_key = secret_key
        web_users: dict = state.get(_RELOAD_STATE_WEB_USERS, {}) or {}
        for sid, names in web_users.items():
            user: WebUser = WebUser(sid)
            user.update(names[0], names[1])
            self._web_users[sid] = user

    def update_iface(self, iface: MeshInterface, channel: channel_pb2.Channel) -> None:
        """Replaces the active interface and channel after a reconnect.

        Updates the interface and channel references used by all route handlers.
        Any in-flight traceroute requests from the previous session are discarded
        because they can never complete after a disconnect.

        Args:
            iface: The newly connected MeshInterface.
            channel: The channel resolved from the new interface.
        """
        self._iface = iface
        self._channel = channel
        self._channel_name = channel.settings.name or CHANNEL_NAME_PRIMARY
        self._pending_web_traces.clear()
        self._capturing_iface._real = iface
    # endregion Public Functions

    # region Protected Functions
    @staticmethod
    def _sort_events_newest_first(events: list[dict]) -> list[dict]:
        """Sorts Today in History events by year, most recent first.

        Years are numeric strings (negative for BC). Events with a missing or
        non-numeric year are placed at the end, keeping their original order.
        """
        def year_key(event: dict) -> tuple[int, int]:
            year_text: str = str(event.get("year", "")).strip()
            result: tuple[int, int] = (1, 0)
            if year_text.lstrip("-").isdigit():
                result = (0, -int(year_text))
            return result
        return sorted(events, key=year_key)

    @staticmethod
    def _read_cache_list(path: str) -> list:
        """Reads a JSON array cache file; an empty list if missing or unreadable."""
        result: list = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data: object = json.load(f)
                if isinstance(data, list):
                    result = data
            except Exception:
                pass
        return result

    def _read_random_cache_item(self, path: str) -> object | None:
        """Reads a JSON array from a cache file and returns a randomly selected element.

        Args:
            path: Absolute path to the JSON cache file.

        Returns:
            A randomly chosen element from the array, or None if the file does not
            exist, cannot be read, or is empty.
        """
        result: object | None = None
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data: object = json.load(f)
                if isinstance(data, list) and data:
                    result = random.choice(data)
            except Exception:
                pass
        return result

    def _label_node_num(self, num: int) -> str:
        """Resolves a node number to its short name, or falls back to the node ID string.

        Args:
            num: The integer node number to resolve.

        Returns:
            The node's short name if available, otherwise the hex node ID string.
        """
        nid: str = MeshtasticHelper.get_node_id_from_node_num(num)
        nodes: dict = self._iface.nodes or {}
        nd: dict | None = nodes.get(nid)
        sn: str = (nd or {}).get("user", {}).get("shortName", "")
        return sn if sn else nid

    def _on_web_traceroute_response(self, packet: dict, interface: MeshInterface) -> None:
        """Handles a traceroute response received via pubsub for a web-initiated trace.

        If the responding node has a pending web trace request, parses the packet
        and populates the result container so the polling endpoint can return it.

        Args:
            packet: The raw Meshtastic traceroute response packet.
            interface: The MeshInterface that received the packet (unused).
        """
        from_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        entry: tuple[dict, float] | None = self._pending_web_traces.get(from_id)
        if entry is not None:
            result, start_time = entry
            elapsed: float = time.time() - start_time
            result.update(self._parse_traceroute_packet(packet, from_id, elapsed))

    def _parse_traceroute_packet(self, packet: dict, node_id: str, elapsed: float) -> dict:
        """Parses a raw traceroute response packet into a structured dict for the web API.

        Resolves relay node numbers to short names where available, and scales
        raw SNR integer values to dB.

        Args:
            packet: The raw Meshtastic traceroute response packet.
            node_id: The target node ID string (e.g. ``'!deadbeef'``).
            elapsed: Elapsed time in seconds since the traceroute was sent.

        Returns:
            A status-``'ok'`` dict containing route labels, SNR readings, relay count,
            elapsed time, and a UTC ISO timestamp.
        """
        traceroute: dict = packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_TRACEROUTE, {})
        route_nums: list[int] = traceroute.get(_PACKET_KEY_TRACE_ROUTE, [])
        route_back_nums: list[int] = traceroute.get(_PACKET_KEY_TRACE_ROUTE_BACK, [])
        snr_towards_raw: list[int] = traceroute.get(_PACKET_KEY_TRACE_SNR_TOWARDS, [])
        snr_back_raw: list[int] = traceroute.get(_PACKET_KEY_TRACE_SNR_BACK, [])

        own_label: str = _TRACE_LABEL_BOT
        try:
            local_num: int = self._iface.localNode.nodeNum
            local_node_id: str = MeshtasticHelper.get_node_id_from_node_num(local_num)
            local_nd: dict | None = (self._iface.nodes or {}).get(local_node_id)
            sn: str = (local_nd or {}).get("user", {}).get("shortName", "")
            if sn:
                own_label = sn
        except AttributeError:
            pass

        nodes_d: dict = self._iface.nodes or {}
        target_nd: dict | None = nodes_d.get(node_id)
        target_label: str = (target_nd or {}).get("user", {}).get("shortName", "") or node_id
        route: list[str] = [own_label] + [self._label_node_num(n) for n in route_nums] + [target_label]
        route_back: list[str] = ([target_label] + [self._label_node_num(n) for n in route_back_nums] + [own_label]) if route_back_nums else []
        snr_towards: list[float] = [round(v / _TRACE_SNR_SCALE, 1) for v in snr_towards_raw]
        snr_back: list[float] = [round(v / _TRACE_SNR_SCALE, 1) for v in snr_back_raw]
        return {
            "status": "ok",
            "node_id": node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed": round(elapsed, 1),
            "direct": not route_nums and not route_back_nums,
            "route": route,
            "route_back": route_back,
            "snr_towards": snr_towards,
            "snr_back": snr_back,
            "relay_count": len(route_nums),
        }

    def _load_favorites(self) -> set[str]:
        """Loads the favourites list from disk, decrypting if a passphrase is configured.

        Returns:
            A set of node ID strings marked as favourites, or an empty set if the
            file does not exist or cannot be parsed.
        """
        path: str = os.path.join(self._data_dir, _FAVORITES_FILE)
        result: set[str] = set()
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                raw: str = f.read().strip()
            if self._fernet_key:
                raw = EncryptionHelper.decrypt(raw, self._fernet_key) or "[]"
            result = set(json.loads(raw))
        return result

    def _save_favorites(self) -> None:
        """Persists the current favourites set to disk, encrypting if a passphrase is configured."""
        path: str = os.path.join(self._data_dir, _FAVORITES_FILE)
        raw: str = json.dumps(sorted(self._favorites))
        if self._fernet_key:
            raw = EncryptionHelper.encrypt(raw, self._fernet_key)
        os.makedirs(self._data_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)

    def _get_or_create_web_user(self) -> WebUser:
        """Returns the WebUser for the current browser session, creating it if needed.

        A session ID is generated on first access and stored in the Flask session
        cookie. The corresponding WebUser object is kept in memory for the server's
        lifetime.

        Returns:
            The WebUser object associated with the current browser session.
        """
        if "web_session_id" not in session:
            session["web_session_id"] = secrets.token_hex(16)
        sid: str = session["web_session_id"]
        if sid not in self._web_users:
            self._web_users[sid] = WebUser(sid)
        return self._web_users[sid]

    def _validate_web_short_name(self, name: str) -> bool:
        """Returns True if the short name meets web-user constraints.

        Valid short names are 2–4 characters, start with 'W' (case-insensitive),
        and contain only alphanumeric characters.

        Args:
            name: The candidate short name.

        Returns:
            True if valid, False otherwise.
        """
        return (
            2 <= len(name) <= _WEB_USER_SHORT_NAME_MAX_LEN
            and name[0].upper() == _WEB_USER_SHORT_NAME_PREFIX
            and name.isalnum()
        )

    def _validate_web_long_name(self, name: str) -> bool:
        """Returns True if the long name meets web-user constraints.

        Valid long names are 1–20 characters.

        Args:
            name: The candidate long name.

        Returns:
            True if valid, False otherwise.
        """
        return 1 <= len(name) <= _WEB_USER_LONG_NAME_MAX_LEN

    def _events_passcode(self) -> str | None:
        """Reads ``EventsPasscode`` from the config file; None when unset or unreadable."""
        result: str | None = None
        parser: configparser.RawConfigParser = configparser.RawConfigParser()
        try:
            parser.read(self._config_file, encoding="utf-8")
            if parser.has_section(_CONFIG_SECTION):
                value: str = parser.get(_CONFIG_SECTION, _EVENTS_PASSCODE_CONFIG_KEY, fallback="").strip()
                result = value or None
        except (configparser.Error, OSError, UnicodeDecodeError):
            pass
        return result

    @staticmethod
    def _passcode_fingerprint(passcode: str) -> str:
        """Value kept in the session cookie; changes when the passcode changes."""
        return hashlib.sha256(("meshbot-events:" + passcode).encode("utf-8")).hexdigest()[:32]

    def _is_events_editor(self) -> bool:
        """True when this browser session signed in with the current passcode."""
        passcode: str | None = self._events_passcode()
        stored: str = str(session.get(_EVENTS_SESSION_EDITOR_KEY, ""))
        return passcode is not None and bool(stored) and hmac.compare_digest(stored, self._passcode_fingerprint(passcode))

    def _limit_wait_seconds(self, log: dict[str, list[float]], client: str, limit: int, window: float) -> float:
        """Seconds until *client* may act again under a sliding-window limit (0 = allowed now)."""
        now: float = time.time()
        with self._auth_lock:
            recent: list[float] = [t for t in log.get(client, []) if now - t < window]
            log[client] = recent
            result: float = 0.0
            if len(recent) >= limit:
                result = window - (now - recent[0])
        return result

    def _record_hit(self, log: dict[str, list[float]], client: str) -> None:
        with self._auth_lock:
            log.setdefault(client, []).append(time.time())

    def _auth_lockout_seconds(self, client: str) -> float:
        """Seconds until *client* may try the passcode again (0 when not locked out)."""
        return self._limit_wait_seconds(self._auth_failures, client, _EVENTS_AUTH_MAX_FAILURES, _EVENTS_AUTH_WINDOW_SECONDS)

    def _record_auth_failure(self, client: str) -> None:
        self._record_hit(self._auth_failures, client)

    def _visible_event(self, event_id: str) -> dict | None:
        """The event if it exists and this session may see it (approved, or an organizer).

        Raises:
            EventStoreError: When the event files cannot be read.
        """
        event: dict | None = self._event_store.get(event_id) if EventStore.is_valid_id(event_id) else None
        if event is not None and not EventStore.is_approved(event) and not self._is_events_editor():
            event = None
        return event

    def _events_auth_error(self):
        """The 403 returned when an organizer-only request is not signed in."""
        message: str = _EVENTS_AUTH_REQUIRED if self._events_passcode() else _EVENTS_AUTH_DISABLED
        return jsonify({"error": message, "auth_required": True}), 403

    def _read_upload(self, field: str) -> tuple[bytes | None, str | None]:
        """Reads one uploaded image from the current multipart request.

        Args:
            field: The form field name of the file.

        Returns:
            ``(data, error)``: ``data`` is None when no file was sent or it was
            rejected; ``error`` explains a rejection.
        """
        data: bytes | None = None
        error: str | None = None
        upload = request.files.get(field)
        if upload is not None and upload.filename is not None:
            raw: bytes = upload.read(_EVENTS_MAX_IMAGE_BYTES + 1)
            if not raw:
                pass
            elif len(raw) > _EVENTS_MAX_IMAGE_BYTES:
                error = f"Image is larger than {_EVENTS_MAX_IMAGE_BYTES // (1024 * 1024)} MB."
            elif EventStore.detect_image_type(raw) is None:
                error = "Only JPEG, PNG, GIF or WebP images are accepted."
            else:
                data = raw
        return data, error

    def _save_event_from_request(self, event_id: str | None, approved: bool = True):
        """Creates (event_id None) or updates an event from a multipart form post.

        The form carries the event fields plus optional ``image`` and
        ``image_thumb`` files and an optional ``remove_image`` flag.
        """
        clean, errors = EventStore.validate(request.form.to_dict())
        image, image_error = self._read_upload("image")
        thumb, thumb_error = self._read_upload("image_thumb")
        if image_error or thumb_error:
            errors["image"] = image_error or thumb_error
        if image is not None and thumb is None:
            thumb = image
        remove_image: bool = request.form.get("remove_image", "") in ("1", "true", "on")
        response = None
        if errors:
            response = (jsonify({"error": "Please fix the highlighted fields.", "fields": errors}), 400)
        else:
            try:
                event: dict | None
                if event_id is None:
                    event = self._event_store.create(clean, has_image=image is not None, approved=approved)
                elif image is not None:
                    event = self._event_store.update(event_id, clean, has_image=True)
                elif remove_image:
                    event = self._event_store.update(event_id, clean, has_image=False)
                else:
                    event = self._event_store.update(event_id, clean)
                if event is None:
                    response = (jsonify({"error": "Event not found."}), 404)
                else:
                    if image is not None and thumb is not None:
                        self._event_store.save_cover(event["id"], image, thumb)
                    elif remove_image:
                        self._event_store.remove_cover(event["id"])
                    response = (jsonify(event), 201 if event_id is None else 200)
            except EventStoreError as exc:
                response = (jsonify({"error": str(exc)}), 503)
        return response

    def _register_routes(self) -> None:
        """Registers all URL routes on the Flask application."""

        @self._app.route("/")
        def index():
            return render_template("index.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/nodes")
        def nodes():
            return render_template("nodes.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/map")
        def map_page():
            return render_template("map.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/chat")
        def chat():
            return render_template("chat.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/about")
        def about():
            return render_template(
                "about.html",
                bot_name=self._bot_name,
                bot_description=self._bot_description,
                github_url=_GITHUB_REPO_URL,
                case_sensitive=self._case_sensitive,
            )

        @self._app.route("/tiles/<int:z>/<int:x>/<int:y>.png")
        def serve_tile(z: int, x: int, y: int):
            tile_data: bytes | None = None
            if z < 0 or z > _TILE_MAX_ZOOM or x < 0 or y < 0:
                abort(400)
            else:
                tile_data = self._tile_cache.get_tile(z, x, y)
                if tile_data is None:
                    abort(404)
            return Response(tile_data, mimetype="image/png")

        @self._app.route("/images/<path:filename>")
        def serve_image(filename: str):
            return send_from_directory(os.path.join(self._web_dir, "images"), filename)

        @self._app.route("/api/readme")
        def api_readme():
            readme_path: str = os.path.normpath(os.path.join(self._web_dir, "..", _README_FILENAME))
            if not os.path.isfile(readme_path):
                abort(404)
            else:
                with open(readme_path, "r", encoding="utf-8") as f:
                    content: str = f.read()
                return content, 200, {"Content-Type": "text/plain; charset=utf-8"}

        @self._app.route("/api/release-notes")
        def api_release_notes():
            readme_path: str = os.path.normpath(os.path.join(self._web_dir, "..", _README_FILENAME))
            if not os.path.isfile(readme_path):
                abort(404)
            else:
                with open(readme_path, "r", encoding="utf-8") as f:
                    content: str = f.read()
                marker: str = "## Release Notes"
                idx: int = content.find(marker)
                if idx == -1:
                    abort(404)
                else:
                    release_notes: str = content[idx:]
                    return release_notes, 200, {"Content-Type": "text/plain; charset=utf-8"}

        @self._app.route("/api/nodes")
        def api_nodes():
            return jsonify([n.to_dict() for n in self._node_db.nodes])

        @self._app.route("/api/map-nodes")
        def api_map_nodes():
            all_nodes: list = self._node_db.nodes
            nodes_with_pos: list = [n for n in all_nodes if n.latitude is not None and n.longitude is not None]
            bot_node_id: str = ""
            try:
                my_info: dict = self._iface.getMyNodeInfo() or {}
                bot_node_id = my_info.get("user", {}).get("id", "")
            except Exception:
                pass
            return jsonify({
                "bot_node_id": bot_node_id,
                "nodes": [n.to_dict() for n in nodes_with_pos],
                "positioned_count": len(nodes_with_pos),
                "total_count": len(all_nodes),
            })

        @self._app.route("/api/today-in-history")
        def api_today_in_history():
            now: datetime = datetime.now(timezone.utc)
            try:
                req_month: int = int(request.args.get("month", 0))
                req_day: int = int(request.args.get("day", 0))
                local_month: int = req_month if 1 <= req_month <= 12 else now.month
                local_day: int = req_day if 1 <= req_day <= 31 else now.day
            except (ValueError, TypeError):
                local_month = now.month
                local_day = now.day
            path: str = os.path.join(
                self._data_dir,
                _TODAY_IN_HISTORY_SUBDIR,
                _TODAY_IN_HISTORY_FILE_FORMAT.format(month=local_month, day=local_day),
            )
            events: list[dict] = []
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw: object = json.load(f)
                    if isinstance(raw, list):
                        events = [
                            {
                                "year": str(e.get(_TODAY_IN_HISTORY_KEY_YEAR, "")),
                                "text": str(e.get(_TODAY_IN_HISTORY_KEY_TEXT, "")),
                                "wikipedia": str(e.get(_TODAY_IN_HISTORY_KEY_WIKIPEDIA, "")),
                            }
                            for e in raw
                            if isinstance(e, dict) and e.get(_TODAY_IN_HISTORY_KEY_TEXT)
                        ]
                except Exception:
                    pass
            events = WebServer._sort_events_newest_first(events)
            return jsonify({"events": events, "month": local_month, "day": local_day})

        @self._app.route("/joy")
        def joy_page():
            return render_template("joy.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/api/joy/lists")
        def api_joy_lists():
            # Joy page: every affirmation, plus a random handful of quotes and jokes.
            def count(name: str, default: int) -> int:
                try:
                    return max(1, min(50, int(request.args.get(name, default))))
                except (TypeError, ValueError):
                    return default

            def sample(filename: str, how_many: int | None) -> list:
                items: list = self._read_cache_list(os.path.join(self._data_dir, filename))
                if how_many is None or len(items) <= how_many:
                    return items
                return random.sample(items, how_many)

            affirmations: list[str] = [a for a in sample(_AFFIRM_CACHE_FILE, None) if isinstance(a, str) and a.strip()]
            quotes: list[dict] = []
            for raw in sample(_ZEN_QUOTES_CACHE_FILE, count("quotes", 10)):
                if isinstance(raw, dict) and str(raw.get(_ZEN_QUOTES_KEY_QUOTE, "")).strip():
                    quotes.append({
                        "quote": str(raw.get(_ZEN_QUOTES_KEY_QUOTE, "")).strip(),
                        "author": str(raw.get(_ZEN_QUOTES_KEY_AUTHOR, "")).strip(),
                    })
            jokes: list[str] = [j for j in sample(_JOKE_CACHE_FILE, count("jokes", 5)) if isinstance(j, str) and j.strip()]
            return jsonify({"affirmations": affirmations, "quotes": quotes, "jokes": jokes})

        @self._app.route("/api/joy")
        def api_joy():
            affirmation_raw: object = self._read_random_cache_item(
                os.path.join(self._data_dir, _AFFIRM_CACHE_FILE)
            )
            zen_raw: object = self._read_random_cache_item(
                os.path.join(self._data_dir, _ZEN_QUOTES_CACHE_FILE)
            )
            joke_raw: object = self._read_random_cache_item(
                os.path.join(self._data_dir, _JOKE_CACHE_FILE)
            )
            zen_quote: dict | None = None
            if isinstance(zen_raw, dict):
                q: str = str(zen_raw.get(_ZEN_QUOTES_KEY_QUOTE, ""))
                a: str = str(zen_raw.get(_ZEN_QUOTES_KEY_AUTHOR, ""))
                if q:
                    zen_quote = {"quote": q, "author": a}
            return jsonify({
                "affirmation": affirmation_raw if isinstance(affirmation_raw, str) else None,
                "zen_quote": zen_quote,
                "joke": joke_raw if isinstance(joke_raw, str) else None,
            })

        @self._app.route("/api/favorites", methods=["GET", "POST"])
        def api_favorites():
            if request.method == "POST":
                body = request.get_json(force=True, silent=True) or {}
                node_id: str = str(body.get("node_id", "")).strip()
                if not node_id:
                    abort(400)
                else:
                    if node_id in self._favorites:
                        self._favorites.discard(node_id)
                    else:
                        self._favorites.add(node_id)
                    self._save_favorites()
            return jsonify(sorted(self._favorites))

        @self._app.route("/api/channel")
        def api_channel():
            return jsonify({"name": self._channel_name, "index": self._channel.index})

        @self._app.route("/api/chat-channels")
        def api_chat_channels():
            result: list[dict] = [{"key": CHANNEL_NAME_PRIMARY, "label": "Primary", "can_send": False}]
            if not self._hide_secondary_channels and self._channel_name != CHANNEL_NAME_PRIMARY:
                result.append({"key": self._channel_name, "label": self._channel_name, "can_send": True})
            return jsonify(result)

        @self._app.route("/api/channels")
        def api_channels():
            result: list[str] = []
            if os.path.isdir(self._data_dir):
                for fname in sorted(os.listdir(self._data_dir)):
                    if fname.endswith(".txt"):
                        result.append(fname[:-4])
            return jsonify(result)

        @self._app.route("/api/history/<channel_name>")
        def api_history(channel_name: str):
            messages = ChatHistory.read_last(
                channel_name=channel_name,
                count=_WEB_SERVER_HISTORY_LIMIT,
                data_dir=self._data_dir,
                passphrase=self._passphrase,
            )
            return jsonify(list(reversed(messages)))

        @self._app.route("/console")
        def console():
            return render_template("console.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/api/console")
        def api_console():
            after_raw: str = request.args.get("after", "-1")
            after: int = int(after_raw) if after_raw.lstrip("-").isdigit() else -1
            if self._console_logger is not None:
                lines, seq = self._console_logger.get_lines(after=after)
            else:
                lines, seq = [], -1
            return jsonify({"lines": lines, "seq": seq})

        @self._app.route("/api/web-user", methods=["GET"])
        def api_web_user_get():
            web_user: WebUser = self._get_or_create_web_user()
            return jsonify(web_user.to_dict())

        @self._app.route("/api/web-user", methods=["POST"])
        def api_web_user_post():
            body = request.get_json(force=True, silent=True) or {}
            long_name: str = str(body.get("long_name", "")).strip()
            short_name: str = str(body.get("short_name", "")).strip().upper()
            web_user: WebUser = self._get_or_create_web_user()
            errors: dict = {}
            if not self._validate_web_long_name(long_name):
                errors["long_name"] = _WEB_USER_ERR_LONG_NAME.format(max=_WEB_USER_LONG_NAME_MAX_LEN)
            if not self._validate_web_short_name(short_name):
                errors["short_name"] = _WEB_USER_ERR_SHORT_NAME.format(
                    max=_WEB_USER_SHORT_NAME_MAX_LEN, prefix=_WEB_USER_SHORT_NAME_PREFIX
                )
            if errors:
                return jsonify({"error": "Validation failed", "fields": errors}), 400
            web_user.update(long_name, short_name)
            return jsonify(web_user.to_dict())

        @self._app.route("/api/send", methods=["POST"])
        def api_send():
            body = request.get_json(force=True, silent=True) or {}
            text: str = str(body.get("text", "")).strip()
            if not text or len(text) > _WEB_SERVER_MAX_SEND_LENGTH:
                abort(400)
            else:
                web_user: WebUser = self._get_or_create_web_user()
                mesh_text: str = _WEB_USER_MESSAGE_PREFIX_FORMAT.format(
                    short_name=web_user.short_name, text=text
                )
                self._iface.sendText(text=mesh_text, channelIndex=self._channel.index)
                if self._chat_history is not None:
                    self._chat_history.append(web_user.display_name, text)
            return jsonify({"ok": True})

        @self._app.route("/api/trace", methods=["POST"])
        def api_trace():
            trace_response: Response = jsonify({"status": "error", "message": "Unknown error"})
            body = request.get_json(force=True, silent=True) or {}
            node_id: str = str(body.get("node_id", "")).strip()
            if not node_id:
                abort(400)
            else:
                result: dict = {}
                start_time: float = time.time()
                self._pending_web_traces[node_id] = (result, start_time)
                try:
                    self._iface.sendTraceRoute(dest=node_id, hopLimit=_TRACE_HOP_LIMIT, channelIndex=self._channel.index)
                    trace_response = jsonify({"status": "pending", "node_id": node_id})
                except Exception as exc:
                    self._pending_web_traces.pop(node_id, None)
                    trace_response = jsonify({"status": "error", "node_id": node_id, "message": str(exc)})
            return trace_response

        @self._app.route("/api/trace/<string:node_id>")
        def api_trace_result(node_id: str):
            entry: tuple[dict, float] | None = self._pending_web_traces.get(node_id)
            if entry is None:
                trace_response = jsonify({"status": "not_found", "node_id": node_id})
            else:
                result, _ = entry
                if result:
                    self._pending_web_traces.pop(node_id, None)
                    trace_response = jsonify(result)
                else:
                    trace_response = jsonify({"status": "pending", "node_id": node_id})
            return trace_response

        @self._app.route("/settings")
        def settings_page():
            return render_template("settings.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/api/settings")
        def api_settings():
            try:
                local_node = self._iface.localNode
                lora: dict = MessageToDict(
                    local_node.localConfig.lora,
                    preserving_proto_field_name=True,
                    always_print_fields_with_no_presence=True,
                )
                device: dict = MessageToDict(
                    local_node.localConfig.device,
                    preserving_proto_field_name=True,
                    always_print_fields_with_no_presence=True,
                )
                channels: list = []
                for ch in (local_node.channels or []):
                    if not ch.role:
                        continue
                    channels.append({
                        "index": ch.index,
                        "name": ch.settings.name if ch.settings.name else ("Primary" if ch.index == 0 else f"Channel {ch.index}"),
                        "role": channel_pb2.Channel.Role.Name(ch.role),
                        "uplink_enabled": ch.settings.uplink_enabled,
                        "downlink_enabled": ch.settings.downlink_enabled,
                    })
                my_node: dict = self._iface.getMyNodeInfo() or {}
                user_data: dict = my_node.get("user", {})
                return jsonify({
                    "lora": lora,
                    "device": device,
                    "user": {
                        "node_id": user_data.get("id", ""),
                        "long_name": user_data.get("longName", ""),
                        "short_name": user_data.get("shortName", ""),
                        "hw_model": user_data.get("hwModel", ""),
                        "is_licensed": user_data.get("isLicensed", False),
                        "role": user_data.get("role", ""),
                    },
                    "channels": channels,
                    "monitored_channel": self._channel_name,
                    "hide_secondary_channels": self._hide_secondary_channels,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 503

        @self._app.route("/history")
        def history():
            return render_template("history.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/api/history-calendar")
        def api_history_calendar():
            try:
                month: int = int(request.args.get("month", datetime.now(timezone.utc).month))
            except (ValueError, TypeError):
                month = datetime.now(timezone.utc).month
            month = max(1, min(12, month))
            calendar_dir: str = os.path.join(self._data_dir, _TODAY_IN_HISTORY_SUBDIR)
            days_with_data: list[int] = []
            for day in range(1, 32):
                path: str = os.path.join(calendar_dir, _TODAY_IN_HISTORY_FILE_FORMAT.format(month=month, day=day))
                if os.path.isfile(path):
                    days_with_data.append(day)
            return jsonify({"month": month, "days_with_data": days_with_data})

        @self._app.route("/api/history-day")
        def api_history_day():
            try:
                month: int = int(request.args.get("month", 1))
                day: int = int(request.args.get("day", 1))
            except (ValueError, TypeError):
                return jsonify({"events": [], "month": 1, "day": 1})
            month = max(1, min(12, month))
            day = max(1, min(31, day))
            path: str = os.path.join(
                self._data_dir,
                _TODAY_IN_HISTORY_SUBDIR,
                _TODAY_IN_HISTORY_FILE_FORMAT.format(month=month, day=day),
            )
            events: list[dict] = []
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw: object = json.load(f)
                    if isinstance(raw, list):
                        events = [
                            {
                                "year": str(e.get(_TODAY_IN_HISTORY_KEY_YEAR, "")),
                                "text": str(e.get(_TODAY_IN_HISTORY_KEY_TEXT, "")),
                                "wikipedia": str(e.get(_TODAY_IN_HISTORY_KEY_WIKIPEDIA, "")),
                            }
                            for e in raw
                            if isinstance(e, dict) and e.get(_TODAY_IN_HISTORY_KEY_TEXT)
                        ]
                except Exception:
                    pass
            events = WebServer._sort_events_newest_first(events)
            return jsonify({"events": events, "month": month, "day": day})

        @self._app.route("/events")
        def events_page():
            return render_template("events.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.errorhandler(413)
        def too_large(_error):
            limit_mb: int = _EVENTS_MAX_UPLOAD_BYTES // (1024 * 1024)
            return jsonify({"error": f"Upload is too large (limit {limit_mb} MB per request)."}), 413

        @self._app.route("/api/events/auth", methods=["GET"])
        def api_events_auth_status():
            return jsonify({"enabled": self._events_passcode() is not None, "editor": self._is_events_editor()})

        @self._app.route("/api/events/auth", methods=["POST"])
        def api_events_sign_in():
            passcode: str | None = self._events_passcode()
            if passcode is None:
                return jsonify({"error": _EVENTS_AUTH_DISABLED}), 503
            client: str = request.remote_addr or "unknown"
            wait: float = self._auth_lockout_seconds(client)
            if wait > 0:
                minutes: int = max(1, int(wait // 60) + 1)
                return jsonify({"error": _EVENTS_AUTH_LOCKED.format(minutes=minutes)}), 429
            body: dict = request.get_json(force=True, silent=True) or {}
            attempt: str = str(body.get("passcode", "")).strip()
            if not hmac.compare_digest(attempt.encode("utf-8"), passcode.encode("utf-8")):
                self._record_auth_failure(client)
                return jsonify({"error": _EVENTS_AUTH_WRONG}), 401
            session[_EVENTS_SESSION_EDITOR_KEY] = self._passcode_fingerprint(passcode)
            return jsonify({"enabled": True, "editor": True})

        @self._app.route("/api/events/auth", methods=["DELETE"])
        def api_events_sign_out():
            session.pop(_EVENTS_SESSION_EDITOR_KEY, None)
            return jsonify({"enabled": self._events_passcode() is not None, "editor": False})

        @self._app.route("/api/events", methods=["GET"])
        def api_events_list():
            try:
                events: list[dict] = self._event_store.list_events()
                if not self._is_events_editor():
                    events = [e for e in events if EventStore.is_approved(e)]
                return jsonify({"events": events})
            except EventStoreError as exc:
                return jsonify({"error": str(exc), "events": []}), 503

        @self._app.route("/api/events/upcoming", methods=["GET"])
        def api_events_upcoming():
            # Dashboard agenda: published events happening now or in the next N days.
            try:
                days: int = max(1, min(365, int(request.args.get("days", 30))))
                limit: int = max(1, min(50, int(request.args.get("limit", 8))))
            except (TypeError, ValueError):
                days, limit = 30, 8
            try:
                events: list[dict] = [e for e in self._event_store.list_events() if EventStore.is_approved(e)]
            except EventStoreError as exc:
                return jsonify({"error": str(exc), "events": []}), 503
            return jsonify({"events": upcoming_occurrences(events, datetime.now(timezone.utc), days, limit), "days": days})

        @self._app.route("/api/events", methods=["POST"])
        def api_events_create():
            # Organizers publish directly; anyone else submits an event for review.
            if self._is_events_editor():
                return self._save_event_from_request(None)
            if self._events_passcode() is None:
                return jsonify({"error": _EVENTS_SUBMIT_DISABLED}), 403
            client: str = request.remote_addr or "unknown"
            wait: float = self._limit_wait_seconds(self._submissions, client, _EVENTS_SUBMIT_MAX_PER_WINDOW, _EVENTS_SUBMIT_WINDOW_SECONDS)
            if wait > 0:
                return jsonify({"error": _EVENTS_SUBMIT_LIMITED.format(minutes=max(1, int(wait // 60) + 1))}), 429
            # Only events with a date still to come (a repeat counts) may be submitted.
            submitted, submit_errors = EventStore.validate(request.form.to_dict())
            if not submit_errors and EventStore.status_of(submitted) == _EVENTS_STATUS_PAST:
                return jsonify({"error": _EVENTS_SUBMIT_ENDED, "fields": {"end": _EVENTS_SUBMIT_ENDED}}), 400
            body, status_code = self._save_event_from_request(None, approved=False)
            if status_code == 201:
                self._record_hit(self._submissions, client)
                event: dict = body.get_json()
                # Submitters only learn it was received; the event stays hidden until approved.
                body, status_code = jsonify({"pending": True, "name": event.get("name", "")}), 202
            return body, status_code

        @self._app.route("/api/events/<event_id>", methods=["GET"])
        def api_event_get(event_id: str):
            try:
                event: dict | None = self._visible_event(event_id)
            except EventStoreError as exc:
                return jsonify({"error": str(exc)}), 503
            if event is None:
                return jsonify({"error": "Event not found."}), 404
            return jsonify(event)

        @self._app.route("/api/events/<event_id>/approve", methods=["POST"])
        def api_event_approve(event_id: str):
            if not self._is_events_editor():
                return self._events_auth_error()
            try:
                event: dict | None = self._event_store.set_approved(event_id, True) if EventStore.is_valid_id(event_id) else None
            except EventStoreError as exc:
                return jsonify({"error": str(exc)}), 503
            if event is None:
                return jsonify({"error": "Event not found."}), 404
            return jsonify(event)

        @self._app.route("/api/events/<event_id>", methods=["PUT"])
        def api_event_update(event_id: str):
            if not self._is_events_editor():
                return self._events_auth_error()
            if not EventStore.is_valid_id(event_id):
                return jsonify({"error": "Event not found."}), 404
            return self._save_event_from_request(event_id)

        @self._app.route("/api/events/<event_id>", methods=["DELETE"])
        def api_event_delete(event_id: str):
            if not self._is_events_editor():
                return self._events_auth_error()
            try:
                found: bool = EventStore.is_valid_id(event_id) and self._event_store.delete(event_id)
            except EventStoreError as exc:
                return jsonify({"error": str(exc)}), 503
            if not found:
                return jsonify({"error": "Event not found."}), 404
            return jsonify({"ok": True})

        @self._app.route("/api/events/<event_id>/photos", methods=["POST"])
        def api_event_photos(event_id: str):
            try:
                event: dict | None = self._visible_event(event_id)
            except EventStoreError as exc:
                return jsonify({"error": str(exc)}), 503
            if event is None:
                return jsonify({"error": "Event not found."}), 404
            if not EventStore.is_approved(event):
                return jsonify({"error": _EVENTS_NOT_APPROVED}), 409
            if event.get("status") != _EVENTS_STATUS_ACTIVE:
                return jsonify({"error": "Photos can only be added while the event is happening."}), 409
            photos = request.files.getlist("photo")
            thumbs = request.files.getlist("thumb")
            if not photos:
                return jsonify({"error": "No photos were sent."}), 400
            if len(photos) > _EVENTS_MAX_PHOTOS_PER_UPLOAD:
                return jsonify({"error": f"Send at most {_EVENTS_MAX_PHOTOS_PER_UPLOAD} photos at a time."}), 400
            uploader: str = str(request.form.get("uploader", "")).strip()[:_EVENTS_UPLOADER_MAX_LEN]
            added: list[dict] = []
            rejected: int = 0
            for index, photo in enumerate(photos):
                full: bytes = photo.read(_EVENTS_MAX_IMAGE_BYTES + 1)
                thumb: bytes = thumbs[index].read(_EVENTS_MAX_IMAGE_BYTES + 1) if index < len(thumbs) else b""
                if not thumb or EventStore.detect_image_type(thumb) is None:
                    thumb = full
                if len(full) > _EVENTS_MAX_IMAGE_BYTES or EventStore.detect_image_type(full) is None:
                    rejected += 1
                    continue
                record: dict | None = self._event_store.add_photo(event_id, uploader, full, thumb)
                if record is not None:
                    added.append(record)
            status_code: int = 201 if added else 400
            return jsonify({"added": added, "rejected": rejected}), status_code

        @self._app.route("/events/<event_id>/calendar.ics")
        def event_calendar_file(event_id: str):
            try:
                event: dict | None = self._visible_event(event_id)
            except EventStoreError:
                event = None
            if event is None:
                abort(404)
            page_url: str = f"{request.host_url}events?id={event['id']}"
            safe_name: str = re.sub(r"[^A-Za-z0-9]+", "-", str(event.get("name", ""))).strip("-")[:60] or "event"
            response: Response = Response(build_ics(event, page_url), mimetype="text/calendar")
            response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}.ics"'
            response.headers["Cache-Control"] = "no-store"
            return response

        @self._app.route("/events/<event_id>/image/<name>")
        def event_image(event_id: str, name: str):
            try:
                visible: bool = self._visible_event(event_id) is not None
            except EventStoreError:
                visible = False
            if not visible:
                abort(404)
            data: bytes | None = self._event_store.read_image(event_id, name)
            mime: str | None = EventStore.detect_image_type(data) if data else None
            if data is None or mime is None:
                abort(404)
            response: Response = Response(data, mimetype=mime)
            response.headers["Cache-Control"] = "private, max-age=300"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        @self._app.route("/dm")
        def dm():
            return render_template("dm.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/api/dm", methods=["POST"])
        def api_dm():
            body: dict = request.get_json(force=True, silent=True) or {}
            text: str = str(body.get("text", "")).strip()
            if not text or len(text) > _WEB_SERVER_MAX_SEND_LENGTH:
                abort(400)
            web_user: WebUser = self._get_or_create_web_user()
            packet: dict = {
                _PACKET_KEY_FROM_ID: web_user.node_id,
                _PACKET_KEY_TO_ID: self._config.node_id,
                _PACKET_KEY_DECODED: {"text": text},
            }
            trimmed: str = text.strip()
            remainder: str = trimmed[len(_EXCLAMATION_PREFIX):].strip() if trimmed.startswith(_EXCLAMATION_PREFIX) else trimmed
            parts: list[str] = remainder.split(None, 1)
            command: str = parts[0] if parts else ""
            params: str = parts[1] if len(parts) > 1 else ""
            lookup: str = command if self._case_sensitive else command.lower()
            commands_dict: dict = self._dm_command_register._commands
            matched_key: str | None = next((k for k in commands_dict if k.lower() == lookup), None)
            responses: list[str] = []
            _dm_response_tl.responses = []
            try:
                if self._verbose:
                    print(f"Received DM command from web user {web_user.display_name}: '{text}' and matched key to: '{matched_key}")
                if matched_key is not None:
                    commands_dict[matched_key](web_user.node_id, params, packet)
                web_responses: list[str] = packet.get(_PACKET_KEY_DECODED, {}).get(_PACKET_KEY_WEB_RESPONSES, [])
                responses = web_responses if web_responses else list(_dm_response_tl.responses)
            finally:
                if hasattr(_dm_response_tl, "responses"):
                    del _dm_response_tl.responses
            response_text: str | None = "\n".join(responses) if responses else None
            if self._verbose:
                print(f"DM command response text: '{response_text}'")
            dm_response = jsonify({"ok": True, "response": response_text}) if response_text else jsonify({"ok": False, "response": f"Invalid Command Text: '{text}'"})
            return dm_response
