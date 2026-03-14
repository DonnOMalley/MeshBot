from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Optional
from common.constants import (
    _NODE_DB_DIR,
    _NODE_DB_FILE,
    _NODE_DB_SALT_FILE,
    _NODE_DB_DEFAULT_RETENTION_DAYS,
    _NODE_DB_LOADED,
    _NODE_DB_PRUNED,
    _NODE_DB_ADDED,
    _NODE_DB_UPDATED,
    _NODE_DB_NO_CHANGE,
    _NODE_DB_DECRYPTION_ERROR,
)
from common.encryption_helper import EncryptionHelper
from meshtastic.mesh_interface import MeshInterface

_KEY_NODE_ID: str = "node_id"
_KEY_LONG_NAME: str = "long_name"
_KEY_SHORT_NAME: str = "short_name"
_KEY_LAST_SEEN: str = "last_seen"
_KEY_LAST_UPDATE_DELTA: str = "last_update_delta"

_DELTA_JUST_NOW: str = "just now"
_DELTA_FORMAT_MINUTES: str = "{n} minute"
_DELTA_FORMAT_HOURS: str = "{n} hour"
_DELTA_FORMAT_DAYS: str = "{n} day"
_DELTA_PLURAL_SUFFIX: str = "s"


def _format_last_seen_difference(seconds: float) -> str:
    """Returns a human-readable string describing a time duration.

    Args:
        seconds: The duration in seconds to format.

    Returns:
        A string such as ``'5 minutes'``, ``'2 hours'``, or ``'3 days'``.
        Returns ``'just now'`` for durations under 60 seconds.
    """
    if seconds < 60:
        return _DELTA_JUST_NOW
    minutes: int = int(seconds // 60)
    if minutes < 60:
        label = _DELTA_FORMAT_MINUTES.format(n=minutes)
        return label + (_DELTA_PLURAL_SUFFIX if minutes != 1 else "")
    hours: int = int(minutes // 60)
    if hours < 24:
        label = _DELTA_FORMAT_HOURS.format(n=hours)
        return label + (_DELTA_PLURAL_SUFFIX if hours != 1 else "")
    days: int = int(hours // 24)
    label = _DELTA_FORMAT_DAYS.format(n=days)
    return label + (_DELTA_PLURAL_SUFFIX if days != 1 else "")


class NodeRecord:
    """Holds identity and tracking information for a single Meshtastic network node."""

    # region Public Variables
    node_id: str
    long_name: str
    short_name: str
    last_seen: datetime
    last_update_delta: Optional[str]
    # endregion Public Variables

    # region Constructor
    def __init__(
        self,
        node_id: str,
        long_name: str,
        short_name: str,
        last_seen: datetime,
        last_update_delta: Optional[str] = None,
    ) -> None:
        """Initialises the node record with identity and tracking data.

        Args:
            node_id: The unique node identifier string (e.g. ``'!deadbeef'``).
            long_name: The human-readable long name of the node.
            short_name: The abbreviated short name of the node.
            last_seen: The UTC datetime when this node was last observed.
            last_update_delta: Human-readable description of the gap between the two
                               most recent observations, or None for a new record.
        """
        self.node_id = node_id
        self.long_name = long_name
        self.short_name = short_name
        self.last_seen = last_seen
        self.last_update_delta = last_update_delta
    # endregion Constructor

    # region Public Functions
    def to_dict(self) -> dict:
        """Serialises this record to a JSON-compatible dictionary.

        Returns:
            A dict with string values suitable for JSON serialisation.
        """
        return {
            _KEY_NODE_ID: self.node_id,
            _KEY_LONG_NAME: self.long_name,
            _KEY_SHORT_NAME: self.short_name,
            _KEY_LAST_SEEN: self.last_seen.isoformat(),
            _KEY_LAST_UPDATE_DELTA: self.last_update_delta,
        }

    @staticmethod
    def from_dict(data: dict) -> NodeRecord:
        """Deserialises a node record from a JSON-compatible dictionary.

        Args:
            data: A dict as produced by :meth:`to_dict`.

        Returns:
            A populated :class:`NodeRecord` instance.
        """
        last_seen: datetime = datetime.fromisoformat(data[_KEY_LAST_SEEN])
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        return NodeRecord(
            node_id=data[_KEY_NODE_ID],
            long_name=data.get(_KEY_LONG_NAME, ""),
            short_name=data.get(_KEY_SHORT_NAME, ""),
            last_seen=last_seen,
            last_update_delta=data.get(_KEY_LAST_UPDATE_DELTA),
        )
    # endregion Public Functions


class NodeDatabase:
    """Maintains a persistent local registry of observed Meshtastic network nodes.

    On construction the database is loaded from disk (or a new empty database is
    created). Changes are persisted immediately after every upsert or prune
    operation so the file always reflects current state.

    When a passphrase is supplied the JSON file is encrypted using Fernet
    (AES-128-CBC + HMAC-SHA256). A per-installation salt is stored in a separate
    file in the same directory and is generated automatically on the first run.
    """

    # region Protected Variables
    _data_dir: str
    _file_path: str
    _salt_path: str
    _retention_days: int
    _nodes: dict[str, NodeRecord]
    _verbose: bool
    _key: Optional[bytes]
    _plain_text_upgrade: bool
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        data_dir: str = _NODE_DB_DIR,
        retention_days: int = _NODE_DB_DEFAULT_RETENTION_DAYS,
        passphrase: Optional[str] = None,
        verbose: bool = False,
    ) -> None:
        """Initialises the node database, loading any existing records from disk.

        Creates the data directory and an empty database file if neither exists.
        When a passphrase is provided the database file is encrypted at rest.

        Args:
            data_dir: Path to the directory where the database file is stored.
                      Defaults to ``'data'`` relative to the working directory.
            retention_days: Number of days without activity before a node is
                            considered stale. Defaults to 30.
            passphrase: Optional passphrase used to encrypt and decrypt the
                        database file. When ``None``, data is stored as plain text.
            verbose: When True, prints a console line for every add, update, or
                     no-change result during upsert operations.
        """
        self._data_dir = data_dir
        self._file_path = os.path.join(data_dir, _NODE_DB_FILE)
        self._salt_path = os.path.join(data_dir, _NODE_DB_SALT_FILE)
        self._retention_days = retention_days
        self._verbose = verbose
        self._nodes = {}
        self._plain_text_upgrade = False
        os.makedirs(self._data_dir, exist_ok=True)
        self._key = EncryptionHelper.resolve_key(passphrase, self._salt_path)
        self._load()
        if self._plain_text_upgrade:
            self._save()
            self._plain_text_upgrade = False
    # endregion Constructor

    # region Protected Functions
    def _load(self) -> None:
        """Reads the database file from disk into memory.

        Creates the data directory and an empty file if they do not exist.
        Prints an error and starts with an empty database if decryption fails.
        Malformed records are silently skipped.
        """
        os.makedirs(self._data_dir, exist_ok=True)
        if not os.path.isfile(self._file_path):
            self._save()
        else:
            with open(self._file_path, "r", encoding="utf-8") as f:
                content: str = f.read()
            load_ok: bool = True
            if self._key is not None:
                decrypted: Optional[str] = EncryptionHelper.decrypt(content, self._key)
                if decrypted is None:
                    # Decryption failed — the file may be plain-text from a previous
                    # unencrypted run. Attempt to parse it as JSON; if that succeeds,
                    # load the records and immediately re-save them encrypted.
                    try:
                        json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        print(_NODE_DB_DECRYPTION_ERROR)
                        load_ok = False
                    if load_ok:
                        # Plain-text JSON parsed OK — re-encrypt on next save.
                        self._plain_text_upgrade = True
                else:
                    content = decrypted
            if load_ok:
                try:
                    raw: list[dict] = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    raw = []
                for item in raw:
                    try:
                        record: NodeRecord = NodeRecord.from_dict(item)
                        self._nodes[record.node_id] = record
                    except (KeyError, ValueError):
                        pass

    def _save(self) -> None:
        """Writes the current in-memory database to disk, encrypting if a key is set."""
        os.makedirs(self._data_dir, exist_ok=True)
        records: list[dict] = [r.to_dict() for r in self._nodes.values()]
        content: str = json.dumps(records, indent=2, ensure_ascii=False)
        if self._key is not None:
            content = EncryptionHelper.encrypt(content, self._key)
        with open(self._file_path, "w", encoding="utf-8") as f:
            f.write(content)
    # endregion Protected Functions

    # region Public Properties
    @property
    def nodes(self) -> list[NodeRecord]:
        """Returns all node records as a list."""
        return list(self._nodes.values())
    # endregion Public Properties

    # region Public Functions
    def load_from_interface(self, iface: MeshInterface) -> None:
        """Syncs the database with the node table currently held by the interface.

        Iterates all nodes known to the connected device and upserts each one.
        Prints a summary of how many nodes are now in the database.

        Args:
            iface: The active MeshInterface connection whose node table is read.
        """
        if iface.nodes:
            for node_data in iface.nodes.values():
                user: dict = node_data.get("user", {})
                node_id: str = user.get("id", "")
                long_name: str = user.get("longName", "")
                short_name: str = user.get("shortName", "")
                if node_id:
                    self.upsert(node_id, long_name, short_name)
        print(_NODE_DB_LOADED.format(count=len(self._nodes)))

    def upsert(self, node_id: str, long_name: str, short_name: str) -> None:
        """Adds a new node record or updates an existing one with fresh identity data.

        When a record already exists the gap between the previous and new
        ``last_seen`` timestamps is computed and stored as ``last_update_delta``.
        The database file is saved after every call.

        Args:
            node_id: The unique node identifier string (e.g. ``'!deadbeef'``).
            long_name: The human-readable long name of the node.
            short_name: The abbreviated short name of the node.
        """
        now: datetime = datetime.now(tz=timezone.utc)
        existing: Optional[NodeRecord] = self._nodes.get(node_id)

        if existing is None:
            record = NodeRecord(
                node_id=node_id,
                long_name=long_name,
                short_name=short_name,
                last_seen=now,
                last_update_delta=None,
            )
            self._nodes[node_id] = record
            self._save()
            if self._verbose:
                print(_NODE_DB_ADDED.format(node_id=node_id, long_name=long_name, short_name=short_name))
        else:
            identity_changed: bool = (
                existing.long_name != long_name or existing.short_name != short_name
            )
            delta_seconds: float = (now - existing.last_seen).total_seconds()
            if delta_seconds > 0 or identity_changed:
                delta_str: str = _format_last_seen_difference(delta_seconds)
                existing.long_name = long_name
                existing.short_name = short_name
                existing.last_update_delta = delta_str
                existing.last_seen = now
                self._save()
                if self._verbose:
                    print(_NODE_DB_UPDATED.format(
                        node_id=node_id,
                        long_name=long_name,
                        short_name=short_name,
                        delta=delta_str,
                    ))
            else:
                if self._verbose:
                    print(_NODE_DB_NO_CHANGE.format(node_id=node_id))

    def prune(self) -> None:
        """Removes nodes that have not been seen within the retention window.

        Prints a summary of how many nodes were removed. The database file is
        saved only when at least one node is removed.
        """
        cutoff: datetime = datetime.now(tz=timezone.utc)
        stale: list[str] = [
            node_id
            for node_id, record in self._nodes.items()
            if (cutoff - record.last_seen).days >= self._retention_days
        ]
        if stale:
            for node_id in stale:
                del self._nodes[node_id]
            self._save()
        print(_NODE_DB_PRUNED.format(count=len(stale), days=self._retention_days))
    # endregion Public Functions
