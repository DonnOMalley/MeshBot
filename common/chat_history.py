from __future__ import annotations
import os
import re
import threading
from datetime import datetime, timezone
from typing import Optional
from common.constants import (
    _NODE_DB_DIR,
    _NODE_DB_SALT_FILE,
    _CHAT_HISTORY_FILE_FORMAT,
    _CHAT_HISTORY_LINE_FORMAT,
    _CHAT_HISTORY_TIMESTAMP_FORMAT,
)
from common.encryption_helper import EncryptionHelper

_UNSAFE_FILENAME_CHARS: re.Pattern = re.compile(r"[^a-z0-9_\-]")


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
    _key: Optional[bytes]
    # endregion Protected Variables

    # region Constructor
    def __init__(self, channel_name: str, data_dir: str = _NODE_DB_DIR, passphrase: Optional[str] = None) -> None:
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
    def read_last(channel_name: str, count: int, data_dir: str = _NODE_DB_DIR, passphrase: Optional[str] = None) -> list[str]:
        """Reads the last *count* messages from the channel log file.

        Decrypts each line when *passphrase* is provided. Lines that cannot be
        decrypted are silently skipped. Returns messages most-recent-first so
        the caller can display them from newest to oldest.

        Args:
            channel_name: Display name of the channel. Sanitised the same way as
                          in :meth:`__init__` so the file can be located correctly.
            count: Maximum number of messages to return.
            data_dir: Path to the directory containing the log files.
            passphrase: Optional passphrase used to decrypt each line. Must match
                        the passphrase supplied at write time.

        Returns:
            A list of plain-text message strings, most recent first. Empty when
            the file does not exist or contains no valid messages.
        """
        safe_name: str = _UNSAFE_FILENAME_CHARS.sub("_", channel_name.lower())
        filename: str = _CHAT_HISTORY_FILE_FORMAT.format(channel_name=safe_name)
        file_path: str = os.path.join(data_dir, filename)
        result: list[str] = []
        if os.path.isfile(file_path):
            key: Optional[bytes] = EncryptionHelper.resolve_key(passphrase, os.path.join(data_dir, _NODE_DB_SALT_FILE))
            with open(file_path, "r", encoding="utf-8") as f:
                raw_lines: list[str] = [line.rstrip("\n") for line in f if line.strip()]
            if key is not None:
                lines: list[str] = []
                for raw in raw_lines:
                    decrypted: Optional[str] = EncryptionHelper.decrypt(raw, key)
                    if decrypted is not None:
                        lines.extend([part for part in decrypted.split("\n") if part.strip()])
            else:
                lines = raw_lines
            tail: list[str] = lines[-count:] if len(lines) > count else lines
            result = list(reversed(tail))
        return result

    def append(self, sender: str, text: str) -> None:
        """Appends a single message line to the channel log file.

        The line format is ``[YYYY-MM-DD HH:MM:SS UTC] sender: text``.
        The file is opened, written, and closed on every call so no data is
        lost if the process is terminated unexpectedly.

        Args:
            sender: Display name (or node ID fallback) of the message sender.
            text: The plain-text content of the message.
        """
        timestamp: str = datetime.now(timezone.utc).strftime(_CHAT_HISTORY_TIMESTAMP_FORMAT)
        line: str = _CHAT_HISTORY_LINE_FORMAT.format(timestamp=timestamp, sender=sender, text=text)
        content: str
        if self._key is not None:
            content = EncryptionHelper.encrypt(line.rstrip("\n"), self._key) + "\n"
        else:
            content = line
        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(content)
    # endregion Public Functions
