from __future__ import annotations
import logging
import os
import threading
from typing import Optional

from flask import Flask, abort, jsonify, render_template, request
from meshtastic import channel_pb2
from meshtastic.mesh_interface import MeshInterface

from common.chat_history import ChatHistory
from common.constants import (
    CHANNEL_NAME_PRIMARY,
    _NODE_DB_DIR,
    _WEB_SERVER_HOST,
    _WEB_SERVER_MAX_SEND_LENGTH,
    _WEB_SERVER_HISTORY_LIMIT,
    _WEB_SERVER_PORT,
    _WEB_SERVER_STARTED,
)
from common.node_database import NodeDatabase


class WebServer:
    """Lightweight Flask web server running on a background daemon thread.

    Exposes REST API endpoints for the node list, channel chat history, and
    sending messages to the bot's active channel. Static assets and the
    single-page HTML template are served from the ``web/`` folder.
    """

    # region Protected Variables
    _node_db: NodeDatabase
    _iface: MeshInterface
    _channel: channel_pb2.Channel
    _channel_name: str
    _data_dir: str
    _passphrase: Optional[str]
    _app: Flask
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        node_db: NodeDatabase,
        iface: MeshInterface,
        channel: channel_pb2.Channel,
        data_dir: str = _NODE_DB_DIR,
        passphrase: Optional[str] = None,
    ) -> None:
        """Initialises the web server.

        Args:
            node_db: The node database used to serve the node list.
            iface: The active MeshInterface used to send messages.
            channel: The channel the bot is monitoring. Outgoing messages are
                     sent on this channel.
            data_dir: Directory containing chat history files. Defaults to the
                      shared ``data`` directory.
            passphrase: Optional passphrase used to decrypt chat history files.
        """
        self._node_db = node_db
        self._iface = iface
        self._channel = channel
        self._channel_name = channel.settings.name or CHANNEL_NAME_PRIMARY
        self._data_dir = data_dir
        self._passphrase = passphrase

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
        print(_WEB_SERVER_STARTED.format(port=_WEB_SERVER_PORT))
        t = threading.Thread(
            target=self._app.run,
            kwargs={
                "host": _WEB_SERVER_HOST,
                "port": _WEB_SERVER_PORT,
                "threaded": True,
                "use_reloader": False,
            },
            daemon=True,
        )
        t.start()
    # endregion Public Functions

    # region Protected Functions
    def _register_routes(self) -> None:
        """Registers all URL routes on the Flask application."""

        @self._app.route("/")
        def index():
            return render_template("index.html")

        @self._app.route("/api/nodes")
        def api_nodes():
            return jsonify([n.to_dict() for n in self._node_db.nodes])

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
            self._iface.sendText(text=text, channelIndex=self._channel.index)
            return jsonify({"ok": True})
    # endregion Protected Functions
