from __future__ import annotations
import hashlib
import json
import logging
import os
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
    _TILE_MAX_ZOOM,
)
from common.encryption_helper import EncryptionHelper
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase
from configuration.node_configuration import NodeConfiguration
from messaging.command_register import CommandRegister
from web.tile_cache import TileCache

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
    _display_host: str
    _node_db: NodeDatabase
    _iface: MeshInterface
    _channel: channel_pb2.Channel
    _channel_name: str
    _data_dir: str
    _passphrase: str | None
    _fernet_key: bytes | None
    _favorites: set[str]
    _pending_web_traces: dict[str, tuple[dict, float]]
    _port: int
    _tile_cache: TileCache
    _web_dir: str
    _web_users: dict[str, WebUser]
    _chat_history: ChatHistory | None
    _console_logger: ConsoleLogger | None
    _dm_command_register: CommandRegister
    _app: Flask
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
        verbose: bool = False,
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
        self._pending_web_traces = {}
        self._chat_history = chat_history
        self._console_logger = console_logger
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
        self._web_users = {}
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self._register_routes()
    # endregion Constructor

    # region Public Functions
    def start(self) -> None:
        """Starts the web server on a daemon background thread."""
        print(_WEB_SERVER_STARTED.format(host=self._display_host, port=self._port))
        t = threading.Thread(
            target=self._app.run,
            kwargs={
                "host": _WEB_SERVER_HOST,
                "port": self._port,
                "threaded": True,
                "use_reloader": False,
            },
            daemon=True,
        )
        t.start()

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
            if self._channel_name != CHANNEL_NAME_PRIMARY:
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
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 503

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
