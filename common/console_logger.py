"""Console logger that tees stdout/stderr to a timestamped log file and an in-memory ring buffer."""

from __future__ import annotations
import os
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from typing import TextIO

from common.constants import (
    _CONSOLE_BUFFER_LINES,
    _LOG_DIR,
    _LOG_FILENAME_FORMAT,
    _LOG_TIMESTAMP_FORMAT,
)


class _TeeStream:
    """Intercepts stream writes, forwarding each to the original stream, a log file,
    and an accumulated line buffer shared across all tee streams on the same logger.
    """

    # region Private Variables
    _original: TextIO
    _log: TextIO
    _shared_lines: deque
    _shared_seq_end: list
    _shared_lock: threading.Lock
    _stream_lock: threading.Lock
    _partial: str
    # endregion Private Variables

    # region Constructor
    def __init__(
        self,
        original: TextIO,
        log: TextIO,
        shared_lines: deque,
        shared_seq_end: list,
        shared_lock: threading.Lock,
    ) -> None:
        """Initialises the tee stream.

        Args:
            original: The original stream to forward writes to.
            log: The open log file to mirror writes to.
            shared_lines: The deque shared by all tee streams on this logger.
            shared_seq_end: A single-element list holding the current sequence counter.
            shared_lock: Lock protecting ``shared_lines`` and ``shared_seq_end``.
        """
        self._original = original
        self._log = log
        self._shared_lines = shared_lines
        self._shared_seq_end = shared_seq_end
        self._shared_lock = shared_lock
        self._stream_lock = threading.Lock()
        self._partial = ""
    # endregion Constructor

    # region Public Functions
    def write(self, text: str) -> int:
        """Forwards ``text`` to the original stream, the log file, and the line buffer.

        Args:
            text: The text to write.

        Returns:
            The number of characters written.
        """
        try:
            self._original.write(text)
            self._original.flush()
        except Exception:
            pass
        try:
            self._log.write(text)
            self._log.flush()
        except Exception:
            pass
        with self._stream_lock:
            combined: str = self._partial + text
            parts: list[str] = combined.split("\n")
            self._partial = parts[-1]
            complete_lines: list[str] = parts[:-1]
        with self._shared_lock:
            for line in complete_lines:
                self._shared_lines.append(line)
                self._shared_seq_end[0] += 1
        return len(text)

    def flush(self) -> None:
        """Flushes both the original stream and the log file."""
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._log.flush()
        except Exception:
            pass

    def fileno(self) -> int:
        """Returns the underlying file descriptor of the original stream.

        Returns:
            The file descriptor integer.
        """
        return self._original.fileno()

    def isatty(self) -> bool:
        """Returns False — this stream is not an interactive terminal.

        Returns:
            Always False.
        """
        return False
    # endregion Public Functions


class ConsoleLogger:
    """Tees sys.stdout and sys.stderr to a timestamped log file and an in-memory ring buffer.

    Installed by calling the constructor, which immediately replaces ``sys.stdout``
    and ``sys.stderr``. All subsequent console output is written to the original
    streams, persisted to ``<log_dir>/console_<timestamp>.log``, and stored in a
    circular buffer of the most recent ``_CONSOLE_BUFFER_LINES`` lines.

    The in-memory buffer is exposed via ``get_lines(after)`` for use by the web API.
    """

    # region Private Variables
    _lock: threading.Lock
    _lines: deque
    _seq_end: list
    _log_path: str
    _log_file: TextIO
    _tee_out: _TeeStream
    _tee_err: _TeeStream
    # endregion Private Variables

    # region Public Properties
    @property
    def log_path(self) -> str:
        """The absolute path to the current session's log file."""
        return self._log_path
    # endregion Public Properties

    # region Constructor
    def __init__(self, log_dir: str = _LOG_DIR) -> None:
        """Creates the log file, installs the tee streams, and activates logging.

        After this call ``sys.stdout`` and ``sys.stderr`` are replaced with tee
        wrappers that write to both the original streams and the log file.

        Args:
            log_dir: Directory in which to create the log file. Created if missing.
        """
        self._lock = threading.Lock()
        self._lines = deque(maxlen=_CONSOLE_BUFFER_LINES)
        self._seq_end = [0]
        os.makedirs(log_dir, exist_ok=True)
        timestamp: str = datetime.now(timezone.utc).strftime(_LOG_TIMESTAMP_FORMAT)
        filename: str = _LOG_FILENAME_FORMAT.format(timestamp=timestamp)
        self._log_path = os.path.join(log_dir, filename)
        self._log_file = open(self._log_path, "w", encoding="utf-8", buffering=1)
        orig_out: TextIO = sys.stdout
        orig_err: TextIO = sys.stderr
        self._tee_out = _TeeStream(orig_out, self._log_file, self._lines, self._seq_end, self._lock)
        self._tee_err = _TeeStream(orig_err, self._log_file, self._lines, self._seq_end, self._lock)
        sys.stdout = self._tee_out
        sys.stderr = self._tee_err
    # endregion Constructor

    # region Public Functions
    def get_lines(self, after: int = -1) -> tuple[list[str], int]:
        """Returns buffered console lines since a given sequence number.

        Args:
            after: Only return lines whose sequence number is greater than this value.
                   Pass ``-1`` (the default) to receive all buffered lines.

        Returns:
            A ``(lines, seq)`` tuple where ``lines`` is the requested slice of
            the ring buffer and ``seq`` is the current sequence end that the
            caller should pass as ``after`` on the next call.
        """
        with self._lock:
            seq_end: int = self._seq_end[0]
            all_lines: list[str] = list(self._lines)
        seq_start: int = seq_end - len(all_lines)
        if after < 0 or after < seq_start - 1:
            result: list[str] = all_lines
        else:
            offset: int = after - seq_start + 1
            result = all_lines[max(0, offset):]
        return result, seq_end
    # endregion Public Functions
