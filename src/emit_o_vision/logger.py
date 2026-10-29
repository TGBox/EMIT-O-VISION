"""Central logging subsystem for EMIT-O-VISION.

Provides file logging, console logging, in-memory log history,
and live signal broadcasting to GUI log viewer widgets.
"""

from __future__ import annotations

import logging
import os
import sys
from collections import deque
from pathlib import Path
from typing import Callable, Optional

LOG_FILE_NAME = "emit_o_vision.log"
_MAX_HISTORY_LINES = 1000

_history: deque[str] = deque(maxlen=_MAX_HISTORY_LINES)
_listeners: list[Callable[[str], None]] = []


class MemoryLogHandler(logging.Handler):
    """Custom logging handler that buffers log records and notifies live listeners."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _history.append(msg)
            for listener in list(_listeners):
                try:
                    listener(msg)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


def get_log_file_path() -> Path:
    """Return absolute path to the log file."""
    # Place log in working directory or alongside executable
    return Path.cwd() / LOG_FILE_NAME


def register_log_listener(callback: Callable[[str], None]) -> None:
    """Register a callback to receive new log lines in real time."""
    if callback not in _listeners:
        _listeners.append(callback)


def unregister_log_listener(callback: Callable[[str], None]) -> None:
    """Unregister a previously registered live log callback."""
    if callback in _listeners:
        _listeners.remove(callback)


def get_log_history() -> list[str]:
    """Return all currently buffered log lines."""
    return list(_history)


def clear_log_history() -> None:
    """Clear memory log history."""
    _history.clear()


_memory_handler: Optional[MemoryLogHandler] = None
_file_handler: Optional[logging.FileHandler] = None


def setup_logging(debug: bool = False, log_to_file: bool = True) -> logging.Logger:
    """Initialize root application logger with formatting and optional file output."""
    global _memory_handler, _file_handler

    logger = logging.getLogger("emit_o_vision")
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Memory handler for GUI viewer
    if _memory_handler is None:
        _memory_handler = MemoryLogHandler()
        _memory_handler.setFormatter(formatter)
        logger.addHandler(_memory_handler)

    # File handler
    if log_to_file and _file_handler is None:
        log_path = get_log_file_path()
        try:
            _file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            _file_handler.setFormatter(formatter)
            _file_handler.setLevel(logging.DEBUG)  # Always capture debug in file
            logger.addHandler(_file_handler)
        except OSError as e:
            sys.stderr.write(f"Could not initialize log file: {e}\n")

    # Console handler
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, (logging.FileHandler, MemoryLogHandler)) for h in logger.handlers)
    if not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    logger.info(f"EMIT-O-VISION Logger initialisiert (Level={logging.getLevelName(level)}, Datei={get_log_file_path()})")
    return logger


def open_log_file() -> bool:
    """Open the log file using the default system text viewer."""
    log_path = get_log_file_path()
    if not log_path.is_file():
        try:
            log_path.write_text("EMIT-O-VISION Logdatei initialisiert.\n", encoding="utf-8")
        except Exception:
            return False

    try:
        if sys.platform == "win32":
            os.startfile(str(log_path))
            return True
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(log_path)])
            return True
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(log_path)])
            return True
    except Exception:
        return False

