from __future__ import annotations
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, abort, jsonify, render_template, request
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface
from pubsub import pub

from common.chat_history import ChatHistory
from common.constants import (
    CHANNEL_NAME_PRIMARY,
    _DEFAULT_BOT_DESCRIPTION,
    _EVENT_TRACEROUTE,
    _FAVORITES_FILE,
    _GITHUB_REPO_URL,
    _NODE_DB_DIR,
    _NODE_DB_SALT_FILE,
    _PACKET_KEY_DECODED,
    _PACKET_KEY_TRACEROUTE,
    _PACKET_KEY_TRACE_ROUTE,
    _PACKET_KEY_TRACE_ROUTE_BACK,
    _PACKET_KEY_TRACE_SNR_TOWARDS,
    _PACKET_KEY_TRACE_SNR_BACK,
    _TRACE_HOP_LIMIT,
    _TRACE_LABEL_BOT,
    _TRACE_SNR_SCALE,
    _WEB_SERVER_DISPLAY_HOST,
    _WEB_SERVER_HOST,
    _WEB_SERVER_MAX_SEND_LENGTH,
    _WEB_SERVER_HISTORY_LIMIT,
    _WEB_SERVER_PORT,
    _WEB_SERVER_STARTED,
    _WEB_TRACE_TIMEOUT_SECONDS,
)
from common.encryption_helper import EncryptionHelper
from common.meshtastic_helper import MeshtasticHelper
from common.node_database import NodeDatabase


class WebServer:
    """Lightweight Flask web server running on a background daemon thread.

    Exposes REST API endpoints for the node list, channel chat history, and
    sending messages to the bot's active channel. Static assets and the
    single-page HTML template are served from the ``web/`` folder.
    """

    # region Protected Variables
    _bot_description: str
    _bot_name: str
    _display_host: str
    _node_db: NodeDatabase
    _iface: MeshInterface
    _channel: channel_pb2.Channel
    _channel_name: str
    _data_dir: str
    _passphrase: Optional[str]
    _fernet_key: Optional[bytes]
    _favorites: set[str]
    _pending_web_traces: dict[str, tuple[threading.Event, dict, float]]
    _port: int
    _app: Flask
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        node_db: NodeDatabase,
        iface: MeshInterface,
        channel: channel_pb2.Channel,
        bot_name: str,
        bot_description: str = _DEFAULT_BOT_DESCRIPTION,
        data_dir: str = _NODE_DB_DIR,
        host: str = _WEB_SERVER_DISPLAY_HOST,
        passphrase: Optional[str] = None,
        port: int = _WEB_SERVER_PORT,
    ) -> None:
        """Initialises the web server.

        Args:
            node_db: The node database used to serve the node list.
            iface: The active MeshInterface used to send messages.
            channel: The channel the bot is monitoring. Outgoing messages are
                     sent on this channel.
            bot_name: The runtime name of the bot, shown in the dashboard.
            bot_description: Short description shown alongside the bot name in the header.
            data_dir: Directory containing chat history files. Defaults to the
                      shared ``data`` directory.
            host: Hostname displayed in the console startup message. Defaults to
                  'localhost'. This does not affect the network interface Flask
                  binds to; the server always listens on all interfaces.
            passphrase: Optional passphrase used to decrypt chat history files.
            port: Port number the web portal listens on. Defaults to
                  ``_WEB_SERVER_PORT``.
        """
        self._bot_name = bot_name
        self._bot_description = bot_description
        self._node_db = node_db
        self._iface = iface
        self._channel = channel
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
        pub.subscribe(self._on_web_traceroute_response, _EVENT_TRACEROUTE)

        _base = os.path.dirname(os.path.abspath(__file__))
        self._app = Flask(
            __name__,
            template_folder=os.path.join(_base, "templates"),
            static_folder=os.path.join(_base, "static"),
        )
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

        If the responding node has a pending web trace request, parses the packet,
        populates the result container, and signals the waiting API thread.

        Args:
            packet: The raw Meshtastic traceroute response packet.
            interface: The MeshInterface that received the packet (unused).
        """
        from_id: str = MeshtasticHelper.get_node_id_from_packet(packet)
        entry: tuple[threading.Event, dict, float] | None = self._pending_web_traces.get(from_id)
        if entry is not None:
            event, result, start_time = entry
            elapsed: float = time.time() - start_time
            result.update(self._parse_traceroute_packet(packet, from_id, elapsed))
            event.set()

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
            local_info: dict = self._iface.localNode.nodeInfo or {}
            sn: str = local_info.get("user", {}).get("shortName", "")
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

    def _register_routes(self) -> None:
        """Registers all URL routes on the Flask application."""

        @self._app.route("/")
        def index():
            return render_template("index.html", bot_name=self._bot_name, bot_description=self._bot_description)

        @self._app.route("/nodes")
        def nodes():
            return render_template("nodes.html", bot_name=self._bot_name, bot_description=self._bot_description)

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
            )

        @self._app.route("/api/nodes")
        def api_nodes():
            return jsonify([n.to_dict() for n in self._node_db.nodes])

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

        @self._app.route("/api/send", methods=["POST"])
        def api_send():
            body = request.get_json(force=True, silent=True) or {}
            text: str = str(body.get("text", "")).strip()
            if not text or len(text) > _WEB_SERVER_MAX_SEND_LENGTH:
                abort(400)
            else:
                self._iface.sendText(text=text, channelIndex=self._channel.index)
            return jsonify({"ok": True})

        @self._app.route("/api/trace", methods=["POST"])
        def api_trace():
            body = request.get_json(force=True, silent=True) or {}
            node_id: str = str(body.get("node_id", "")).strip()
            if not node_id:
                abort(400)
            else:
                event: threading.Event = threading.Event()
                result: dict = {}
                start_time: float = time.time()
                self._pending_web_traces[node_id] = (event, result, start_time)
                try:
                    self._iface.sendTraceRoute(dest=node_id, hopLimit=_TRACE_HOP_LIMIT, channelIndex=self._channel.index)
                    signalled: bool = event.wait(timeout=_WEB_TRACE_TIMEOUT_SECONDS)
                finally:
                    self._pending_web_traces.pop(node_id, None)
                trace_response = jsonify({"status": "timeout", "node_id": node_id}) if not signalled else jsonify(result)
            return trace_response
    # endregion Protected Functions
