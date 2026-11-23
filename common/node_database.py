from __future__ import annotations
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from common.constants import (
    _NODE_DB_DIR,
    _NODE_DB_FILE,
    _NODE_DB_SALT_FILE,
    _NODE_DB_DEFAULT_RETENTION_DAYS,
    _NODE_DB_SAVE_INTERVAL_SECONDS,
    _NODE_DB_PRUNE_INTERVAL_SECONDS,
    _NODE_DB_MAX_CLOCK_SKEW_SECONDS,
    _NODE_KEY_LAST_HEARD,
    _NODE_KEY_HOPS_AWAY,
    _PACKET_KEY_POSITION,
    _PACKET_KEY_LATITUDE_I,
    _PACKET_KEY_LONGITUDE_I,
    _PACKET_KEY_USER,
    _USER_KEY_ID,
    _USER_KEY_LONG_NAME,
    _USER_KEY_SHORT_NAME,
    _USER_KEY_ROLE,
    _USER_KEY_HW_MODEL,
    _NODE_DB_LOADED,
    _NODE_DB_PRUNED,
    _NODE_DB_ADDED,
    _NODE_DB_UPDATED,
    _NODE_DB_NO_CHANGE,
    _NODE_DB_DECRYPTION_ERROR,
    _LATITUDE_SCALE,
    _LONGITUDE_SCALE,
)
from common.encryption_helper import EncryptionHelper
from meshtastic.mesh_interface import MeshInterface

_KEY_NODE_ID: str = "node_id"
_KEY_LONG_NAME: str = "long_name"
_KEY_SHORT_NAME: str = "short_name"
_KEY_LAST_SEEN: str = "last_seen"
_KEY_ROLE: str = "role"
_KEY_HARDWARE_MODEL: str = "hardware_model"
_KEY_LATITUDE: str = "latitude"
_KEY_LONGITUDE: str = "longitude"
_KEY_HOPS_AWAY: str = "hops_away"


class NodeRecord:
    """Holds identity and tracking information for a single Meshtastic network node."""

    # region Public Variables
    node_id: str
    long_name: str
    short_name: str
    last_seen: datetime
    role: str
    hardware_model: str
    latitude: Optional[float]
    longitude: Optional[float]
    hops_away: Optional[int]
    # endregion Public Variables

    # region Constructor
    def __init__(
        self,
        node_id: str,
        long_name: str,
        short_name: str,
        last_seen: datetime,
        role: str = "",
        hardware_model: str = "",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        hops_away: Optional[int] = None,
    ) -> None:
        """Initialises the node record with identity and tracking data.

        Args:
            node_id: The unique node identifier string (e.g. ``'!deadbeef'``).
            long_name: The human-readable long name of the node.
            short_name: The abbreviated short name of the node.
            last_seen: The UTC datetime when this node was last observed.
            role: The device role string (e.g. ``'CLIENT'``, ``'ROUTER'``). Empty string if unknown.
            hardware_model: The hardware model string (e.g. ``'TBEAM'``). Empty string if unknown.
            latitude: GPS latitude in decimal degrees, or None if unavailable.
            longitude: GPS longitude in decimal degrees, or None if unavailable.
            hops_away: Number of hops to reach this node, or None if unknown.
        """
        self.node_id = node_id
        self.long_name = long_name
        self.short_name = short_name
        self.last_seen = last_seen
        self.role = role
        self.hardware_model = hardware_model
        self.latitude = latitude
        self.longitude = longitude
        self.hops_away = hops_away
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
            _KEY_ROLE: self.role,
            _KEY_HARDWARE_MODEL: self.hardware_model,
            _KEY_LATITUDE: self.latitude,
            _KEY_LONGITUDE: self.longitude,
            _KEY_HOPS_AWAY: self.hops_away,
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
            role=data.get(_KEY_ROLE, ""),
            hardware_model=data.get(_KEY_HARDWARE_MODEL, ""),
            latitude=data.get(_KEY_LATITUDE),
            longitude=data.get(_KEY_LONGITUDE),
            hops_away=data.get(_KEY_HOPS_AWAY),
        )
    # endregion Public Functions


class NodeDatabase:
    """Maintains a persistent local registry of observed Meshtastic network nodes.

    A node stays in the database for as long as it keeps being heard: every
    packet received from it (text, position, telemetry, node info, ...) moves its
    ``last_seen`` forward. Nodes not heard for longer than the retention window
    are removed by :meth:`prune`.

    Changes are held in memory and written to disk by :meth:`maintain` at most
    once per save interval (and by :meth:`flush` on shutdown), so a busy mesh does
    not cause a full file rewrite for every packet. All public methods are
    thread-safe: packets arrive on the radio thread while the web server reads
    the node list from its own threads.

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
    _key: bytes | None
    _plain_text_upgrade: bool
    _lock: threading.RLock
    _dirty: bool
    _last_save_monotonic: float
    _last_prune_monotonic: float
    # endregion Protected Variables

    # region Constructor
    def __init__(
        self,
        data_dir: str = _NODE_DB_DIR,
        retention_days: int = _NODE_DB_DEFAULT_RETENTION_DAYS,
        passphrase: str | None = None,
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
        self._lock = threading.RLock()
        self._dirty = False
        self._last_save_monotonic = time.monotonic()
        self._last_prune_monotonic = time.monotonic()
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
                decrypted: str | None = EncryptionHelper.decrypt(content, self._key)
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
        """Writes the current in-memory database to disk, encrypting if a key is set.

        Writes to a temporary file first and renames it into place so a crash
        mid-write never leaves a truncated database behind.
        """
        with self._lock:
            os.makedirs(self._data_dir, exist_ok=True)
            records: list[dict] = [r.to_dict() for r in self._nodes.values()]
            content: str = json.dumps(records, indent=2, ensure_ascii=False)
            if self._key is not None:
                content = EncryptionHelper.encrypt(content, self._key)
            temp_path: str = self._file_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, self._file_path)
            self._dirty = False
            self._last_save_monotonic = time.monotonic()

    def _is_stale(self, last_seen: datetime, now: datetime) -> bool:
        """Returns True when ``last_seen`` is outside the retention window."""
        return now - last_seen > timedelta(days=self._retention_days)

    @staticmethod
    def _sanitize_heard_at(heard_at: datetime | None, now: datetime) -> datetime:
        """Returns a trustworthy "heard at" time, falling back to ``now``.

        Radio timestamps are used when present, but a radio without a valid
        clock can report times far in the past or future. Anything in the future
        is clamped to ``now``.
        """
        result: datetime = now
        if heard_at is not None and heard_at <= now:
            result = heard_at
        return result
    # endregion Protected Functions

    # region Public Properties
    @property
    def nodes(self) -> list[NodeRecord]:
        """Returns a snapshot list of all node records."""
        with self._lock:
            return list(self._nodes.values())
    # endregion Public Properties

    # region Public Functions
    @staticmethod
    def epoch_to_datetime(epoch_seconds: int | float | None, now: datetime | None = None) -> datetime | None:
        """Converts a radio epoch timestamp to a UTC datetime, rejecting bad clocks.

        Args:
            epoch_seconds: Seconds since the Unix epoch as reported by the radio
                           (``rxTime`` or ``lastHeard``). 0 or None means unknown.
            now: Reference "current time"; defaults to the system clock.

        Returns:
            The timestamp as a UTC datetime, or None when it is missing or more
            than the allowed clock skew in the future.
        """
        result: datetime | None = None
        reference: datetime = now if now is not None else datetime.now(tz=timezone.utc)
        if epoch_seconds:
            candidate: datetime = datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc)
            if (candidate - reference).total_seconds() <= _NODE_DB_MAX_CLOCK_SKEW_SECONDS:
                result = candidate
        return result

    def load_from_interface(self, iface: MeshInterface) -> None:
        """Syncs the database with the node table currently held by the interface.

        Uses the radio's own ``lastHeard`` time for each node rather than "now",
        so restarting or reconnecting does not make long-silent nodes look active.
        Nodes the radio has never heard (no ``lastHeard``) or has not heard within
        the retention window are not added, so pruned nodes do not come back.

        Args:
            iface: The active MeshInterface connection whose node table is read.
        """
        now: datetime = datetime.now(tz=timezone.utc)
        if iface.nodes:
            for node_data in list(iface.nodes.values()):
                user: dict = node_data.get(_PACKET_KEY_USER, {})
                node_id: str = user.get(_USER_KEY_ID, "")
                heard_at: datetime | None = NodeDatabase.epoch_to_datetime(node_data.get(_NODE_KEY_LAST_HEARD), now)
                position: dict = node_data.get(_PACKET_KEY_POSITION, {})
                lat_i: int | None = position.get(_PACKET_KEY_LATITUDE_I)
                lon_i: int | None = position.get(_PACKET_KEY_LONGITUDE_I)
                latitude: float | None = lat_i * _LATITUDE_SCALE if lat_i is not None else None
                longitude: float | None = lon_i * _LONGITUDE_SCALE if lon_i is not None else None
                hops_away: int | None = node_data.get(_NODE_KEY_HOPS_AWAY)
                known: bool = node_id in self._nodes
                recently_heard: bool = heard_at is not None and not self._is_stale(heard_at, now)
                if node_id and (known or recently_heard):
                    self.upsert(
                        node_id,
                        user.get(_USER_KEY_LONG_NAME, ""),
                        user.get(_USER_KEY_SHORT_NAME, ""),
                        user.get(_USER_KEY_ROLE, "") or "",
                        user.get(_USER_KEY_HW_MODEL, "") or "",
                        latitude,
                        longitude,
                        hops_away=hops_away,
                        heard_at=heard_at,
                        refresh_last_seen=heard_at is not None,
                    )
        bot_id: str = f"!{iface.myInfo.my_node_num:08x}" if iface.myInfo else ""
        if bot_id:
            # The bot's own radio is, by definition, alive right now.
            bot_node_info: dict = iface.getMyNodeInfo() or {}
            bot_user: dict = bot_node_info.get(_PACKET_KEY_USER, {})
            bot_pos: dict = bot_node_info.get(_PACKET_KEY_POSITION, {})
            bot_lat_i: int | None = bot_pos.get(_PACKET_KEY_LATITUDE_I)
            bot_lon_i: int | None = bot_pos.get(_PACKET_KEY_LONGITUDE_I)
            self.upsert(
                bot_id,
                iface.getLongName() or "",
                iface.getShortName() or "",
                bot_user.get(_USER_KEY_ROLE, "") or "",
                bot_user.get(_USER_KEY_HW_MODEL, "") or "",
                bot_lat_i * _LATITUDE_SCALE if bot_lat_i is not None else None,
                bot_lon_i * _LONGITUDE_SCALE if bot_lon_i is not None else None,
            )
        self.flush()
        print(_NODE_DB_LOADED.format(count=len(self._nodes)))

    def upsert(
        self,
        node_id: str,
        long_name: str = "",
        short_name: str = "",
        role: str = "",
        hardware_model: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        hops_away: int | None = None,
        heard_at: datetime | None = None,
        refresh_last_seen: bool = True,
    ) -> None:
        """Adds a new node or updates an existing one, marking it as heard.

        Empty identity fields and None position/hop values never overwrite data
        that is already stored, so packets that carry only part of a node's
        details (e.g. a position or a text message) are safe to pass in.
        ``last_seen`` only ever moves forward. Changes are saved to disk by
        :meth:`maintain` / :meth:`flush`, not immediately.

        Args:
            node_id: The unique node identifier string (e.g. ``'!deadbeef'``).
            long_name: The human-readable long name, or empty if not in the packet.
            short_name: The abbreviated short name, or empty if not in the packet.
            role: The device role string (e.g. ``'CLIENT'``), or empty if unknown.
            hardware_model: The hardware model string (e.g. ``'TBEAM'``), or empty if unknown.
            latitude: GPS latitude in decimal degrees, or None to leave unchanged.
            longitude: GPS longitude in decimal degrees, or None to leave unchanged.
            hops_away: Number of hops to reach this node, or None to leave unchanged.
            heard_at: When the node was heard (UTC). Defaults to now; future
                      times are clamped to now.
            refresh_last_seen: When False, identity/position are updated but
                               ``last_seen`` is left alone (used when the radio
                               cannot say when it last heard the node).
        """
        now: datetime = datetime.now(tz=timezone.utc)
        seen: datetime = NodeDatabase._sanitize_heard_at(heard_at, now)
        with self._lock:
            existing: NodeRecord | None = self._nodes.get(node_id)
            if existing is None:
                self._nodes[node_id] = NodeRecord(
                    node_id=node_id,
                    long_name=long_name,
                    short_name=short_name,
                    last_seen=seen,
                    role=role,
                    hardware_model=hardware_model,
                    latitude=latitude,
                    longitude=longitude,
                    hops_away=hops_away,
                )
                self._dirty = True
                if self._verbose:
                    print(_NODE_DB_ADDED.format(node_id=node_id, long_name=long_name, short_name=short_name))
            else:
                changed: bool = False
                if long_name and long_name != existing.long_name:
                    existing.long_name = long_name
                    changed = True
                if short_name and short_name != existing.short_name:
                    existing.short_name = short_name
                    changed = True
                if role and role != existing.role:
                    existing.role = role
                    changed = True
                if hardware_model and hardware_model != existing.hardware_model:
                    existing.hardware_model = hardware_model
                    changed = True
                if latitude is not None and latitude != existing.latitude:
                    existing.latitude = latitude
                    changed = True
                if longitude is not None and longitude != existing.longitude:
                    existing.longitude = longitude
                    changed = True
                if hops_away is not None and hops_away != existing.hops_away:
                    existing.hops_away = hops_away
                    changed = True
                if refresh_last_seen and seen > existing.last_seen:
                    existing.last_seen = seen
                    changed = True
                if changed:
                    self._dirty = True
                    if self._verbose:
                        print(_NODE_DB_UPDATED.format(
                            node_id=node_id,
                            long_name=existing.long_name,
                            short_name=existing.short_name,
                        ))
                elif self._verbose:
                    print(_NODE_DB_NO_CHANGE.format(node_id=node_id))

    def prune(self) -> None:
        """Removes nodes that have not been heard within the retention window.

        Prints a summary of how many nodes were removed and saves immediately
        when at least one node is removed.
        """
        now: datetime = datetime.now(tz=timezone.utc)
        with self._lock:
            stale: list[str] = [
                node_id
                for node_id, record in self._nodes.items()
                if self._is_stale(record.last_seen, now)
            ]
            for node_id in stale:
                del self._nodes[node_id]
            if stale:
                self._save()
            self._last_prune_monotonic = time.monotonic()
        print(_NODE_DB_PRUNED.format(count=len(stale), days=self._retention_days))

    def flush(self) -> None:
        """Writes pending changes to disk immediately (e.g. on shutdown)."""
        with self._lock:
            if self._dirty:
                self._save()

    def maintain(self) -> None:
        """Periodic housekeeping; call regularly from the main loop.

        Saves pending changes at most once per save interval and prunes stale
        nodes once per prune interval. Cheap to call often.
        """
        now_monotonic: float = time.monotonic()
        if now_monotonic - self._last_prune_monotonic >= _NODE_DB_PRUNE_INTERVAL_SECONDS:
            self.prune()
        with self._lock:
            if self._dirty and now_monotonic - self._last_save_monotonic >= _NODE_DB_SAVE_INTERVAL_SECONDS:
                self._save()
    # endregion Public Functions
