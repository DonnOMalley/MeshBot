from __future__ import annotations
import os
import re
import threading
from datetime import datetime, timezone
from common.constants import (
    _NODE_DB_DIR,
    _NODE_DB_SALT_FILE,
    _CHAT_HISTORY_FILE_FORMAT,
    _CHAT_HISTORY_LINE_FORMAT,
    _CHAT_HISTORY_MSG_ID_TOKEN,
    _CHAT_HISTORY_REPLY_TOKEN,
    _CHAT_HISTORY_TIMESTAMP_FORMAT,
)
from common.encryption_helper import EncryptionHelper

_UNSAFE_FILENAME_CHARS: re.Pattern = re.compile(r"[^a-z0-9_\-]")
_LINE_PATTERN: re.Pattern = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\]"
    r"(?:\s+\[msg:(\d+)\])?"
    r"(?:\s+\[reply:(\d+)\])?"
    r"\s+(.+?):\s*(.*)$"
)


class ChatHistory:
    """Appends incoming channel messages to a persistent plain-text log file.

    One file is created per channel in the configured data directory. The
    filename is derived from the sanitised, lowercased channel name. Entries
    are written in chronological order with a UTC timestamp on each line.

    Thread-safe: :meth:`append` may be called from any thread concurrently.
    DMs are intentionally never passed to this class — they are not persisted.
    """

    # region Protected Variables
    _file_path: str
    _lock: threading.Lock
    _key: bytes | None
    # endregion Protected Variables

    # region Constructor
    def __init__(self, channel_name: str, data_dir: str = _NODE_DB_DIR, passphrase: str | None = None) -> None:
        """Initialises the chat history file for the given channel.

        Creates the data directory if it does not yet exist. The file itself
        is created (or opened for append) on the first call to :meth:`append`.

        Args:
            channel_name: Display name of the channel being logged. Used to
                          derive the filename after sanitisation.
            data_dir: Path to the directory where log files are stored.
                      Defaults to the shared ``data`` directory.
            passphrase: Optional passphrase used to encrypt each log line with
                        Fernet (AES-128-CBC + HMAC-SHA256). When provided, the
                        salt file shared with the node database is used so both
                        derive the same key. When ``None``, lines are stored as
                        plain text.
        """
        safe_name: str = _UNSAFE_FILENAME_CHARS.sub("_", channel_name.lower())
        filename: str = _CHAT_HISTORY_FILE_FORMAT.format(channel_name=safe_name)
        self._file_path = os.path.join(data_dir, filename)
        self._lock = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)
        self._key = EncryptionHelper.resolve_key(passphrase, os.path.join(data_dir, _NODE_DB_SALT_FILE))
    # endregion Constructor

    # region Public Functions
    @staticmethod
    def read_last(channel_name: str, count: int, data_dir: str = _NODE_DB_DIR, passphrase: str | None = None) -> list[dict]:
        """Reads the last *count* messages from the channel log file.

        Decrypts each line when *passphrase* is provided. Lines that cannot be
        decrypted are silently skipped. Returns messages most-recent-first so
        the caller can display them from newest to oldest. Each message is
        returned as a dict with ``timestamp``, ``sender``, ``text``, and
        ``reply_to`` keys. ``reply_to`` is a dict with ``sender`` and ``text``
        when the message is a reply to another message in the current window,
        or ``None`` otherwise.

        Args:
            channel_name: Display name of the channel. Sanitised the same way as
                          in :meth:`__init__` so the file can be located correctly.
            count: Maximum number of messages to return.
            data_dir: Path to the directory containing the log files.
            passphrase: Optional passphrase used to decrypt each line. Must match
                        the passphrase supplied at write time.

        Returns:
            A list of message dicts, most recent first. Empty when the file does
            not exist or contains no valid messages.
        """
        safe_name: str = _UNSAFE_FILENAME_CHARS.sub("_", channel_name.lower())
        filename: str = _CHAT_HISTORY_FILE_FORMAT.format(channel_name=safe_name)
        file_path: str = os.path.join(data_dir, filename)
        result: list[dict] = []
        if os.path.isfile(file_path):
            key: bytes | None = EncryptionHelper.resolve_key(passphrase, os.path.join(data_dir, _NODE_DB_SALT_FILE))
            with open(file_path, "r", encoding="utf-8") as f:
                raw_lines: list[str] = [line.rstrip("\n") for line in f if line.strip()]
            if key is not None:
                lines: list[str] = []
                for raw in raw_lines:
                    decrypted: str | None = EncryptionHelper.decrypt(raw, key)
                    if decrypted is not None:
                        lines.extend([part for part in decrypted.split("\n") if part.strip()])
            else:
                lines = raw_lines
            tail: list[str] = lines[-count:] if len(lines) > count else lines
            entries: list[dict] = []
            id_lookup: dict[int, dict] = {}
            for raw_line in tail:
                m: re.Match | None = _LINE_PATTERN.match(raw_line)
                if m:
                    timestamp: str
                    msg_id_str: str | None
                    reply_str: str | None
                    sender: str
                    text: str
                    timestamp, msg_id_str, reply_str, sender, text = m.groups()
                    msg_id: int | None = int(msg_id_str) if msg_id_str is not None else None
                    reply_id: int | None = int(reply_str) if reply_str is not None else None
                    if msg_id is not None:
                        id_lookup[msg_id] = {"sender": sender, "text": text}
                    entries.append({"timestamp": timestamp, "sender": sender, "text": text, "_reply_id": reply_id})
                elif entries:
                    entries[-1]["text"] = entries[-1]["text"] + "\n" + raw_line
            for entry in entries:
                resolved_reply_id: int | None = entry.pop("_reply_id")
                entry["reply_to"] = id_lookup.get(resolved_reply_id) if resolved_reply_id is not None else None
            result = list(reversed(entries))
        return result

    def append(self, sender: str, text: str, msg_id: int | None = None, reply_to_id: int | None = None) -> None:
        """Appends a single message line to the channel log file.

        The line format is ``[YYYY-MM-DD HH:MM:SS UTC] sender: text``. When
        *msg_id* is provided it is embedded as ``[msg:ID]`` before the sender
        so replies can be resolved during reads. When *reply_to_id* is provided
        it is embedded as ``[reply:ID]`` after the message ID token.
        The file is opened, written, and closed on every call so no data is
        lost if the process is terminated unexpectedly.

        Args:
            sender: Display name (or node ID fallback) of the message sender.
            text: The plain-text content of the message.
            msg_id: Optional Meshtastic packet ID for this message.
            reply_to_id: Optional Meshtastic packet ID of the message being replied to.
        """
        timestamp: str = datetime.now(timezone.utc).strftime(_CHAT_HISTORY_TIMESTAMP_FORMAT)
        msg_id_part: str = _CHAT_HISTORY_MSG_ID_TOKEN.format(msg_id=msg_id) if msg_id is not None else ""
        reply_part: str = _CHAT_HISTORY_REPLY_TOKEN.format(reply_to=reply_to_id) if reply_to_id is not None else ""
        sender_field: str = f"{msg_id_part}{reply_part}{sender}"
        line: str = _CHAT_HISTORY_LINE_FORMAT.format(timestamp=timestamp, sender=sender_field, text=text)
        content: str
        if self._key is not None:
            content = EncryptionHelper.encrypt(line.rstrip("\n"), self._key) + "\n"
        else:
            content = line
        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(content)
    # endregion Public Functions
