"""Forth renderer bridge for EMIT-O-VISION.

Spawns Gforth running emit_o_vision.fs, streams binary frames into Gforth's stdin,
and reads rendered ASCII text frames from Gforth's stdout in real time.
"""

from __future__ import annotations

import queue
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def get_base_dir() -> Path:
    """Return base directory, supporting PyInstaller bundled environment."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_forth_script() -> Path:
    """Locate emit_o_vision.fs in source tree or packaged bundle."""
    base = get_base_dir()
    for candidate in (
        base / "emit_o_vision.fs",
        base / "emit_o_vision" / "emit_o_vision.fs",
        Path(__file__).with_name("emit_o_vision.fs"),
    ):
        if candidate.is_file():
            return candidate
    return Path(__file__).with_name("emit_o_vision.fs")


FORTH_SCRIPT = get_forth_script()

GFORTH_FALLBACKS = (
    Path(r"C:\Program Files (x86)\gforth\gforth.exe"),
    Path(r"C:\Program Files\gforth\gforth.exe"),
)


def find_gforth(explicit: Optional[str] = None) -> Optional[str]:
    """Find the Gforth executable in explicit arg, bundled directory, PATH, or standard installation dirs."""
    if explicit:
        return explicit

    # 1. Check bundled Gforth (for PyInstaller standalone builds)
    base = get_base_dir()
    bundled = base / "gforth" / "gforth.exe"
    if bundled.is_file():
        return str(bundled)

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        bundled_exe = exe_dir / "gforth" / "gforth.exe"
        if bundled_exe.is_file():
            return str(bundled_exe)

    # 2. Check PATH
    found = shutil.which("gforth")
    if found:
        return found

    # 3. Check standard Windows locations
    for candidate in GFORTH_FALLBACKS:
        if candidate.is_file():
            return str(candidate)
    return None


class ForthRenderer:
    """Manages an active Gforth renderer subprocess with bidirectional streaming."""

    def __init__(self, gforth_path: Optional[str] = None) -> None:
        path = find_gforth(gforth_path)
        if not path:
            raise FileNotFoundError(
                "Gforth wurde nicht gefunden. Bitte installieren oder mit --gforth angeben."
            )
        self.gforth_path = path

        forth_script = get_forth_script()
        if not forth_script.is_file():
            raise FileNotFoundError(f"Forth-Skript nicht gefunden: {forth_script}")

        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        self._proc: Optional[subprocess.Popen] = subprocess.Popen(
            [self.gforth_path, forth_script.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=forth_script.parent,
            bufsize=0,
            creationflags=flags,
        )

        self._frame_queue: queue.Queue[str] = queue.Queue(maxsize=4)
        self._latest_frame: Optional[str] = None
        self._lock = threading.Lock()
        self._running = True

        self._reader_thread = threading.Thread(
            target=self._read_stdout_loop, name="ForthStdoutReader", daemon=True
        )
        self._reader_thread.start()

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _read_stdout_loop(self) -> None:
        """Background loop reading ASCII frames from Gforth stdout."""
        buf = bytearray()
        stdout = self._proc.stdout if self._proc else None
        if stdout is None:
            return

        while self._running:
            try:
                chunk = stdout.read(4096)
            except (OSError, ValueError):
                break

            if not chunk:
                break

            buf.extend(chunk)

            # Frames are terminated by Form Feed (ASCII 12, \x0c)
            while b"\x0c" in buf:
                parts = buf.split(b"\x0c", 1)
                raw_frame = parts[0]
                buf = parts[1]

                cleaned = self._clean_ansi(raw_frame)
                if cleaned:
                    with self._lock:
                        self._latest_frame = cleaned
                    # Discard older frames if queue is full to avoid latency
                    try:
                        self._frame_queue.put_nowait(cleaned)
                    except queue.Full:
                        try:
                            self._frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self._frame_queue.put_nowait(cleaned)
                        except queue.Full:
                            pass

        # Flush remaining buffer on exit
        if buf:
            cleaned = self._clean_ansi(buf)
            if cleaned:
                with self._lock:
                    self._latest_frame = cleaned

    @staticmethod
    def _clean_ansi(raw_bytes: bytearray | bytes) -> str:
        """Strip terminal init/cleanup escape codes and decode ASCII frame."""
        cleaned = (
            raw_bytes.replace(b"\x1b[2J", b"")
            .replace(b"\x1b[?25l", b"")
            .replace(b"\x1b[?25h", b"")
            .replace(b"\x1b[H", b"")
            .decode("ascii", errors="replace")
            .strip("\r\n")
        )
        return cleaned

    def send_frame(self, frame_bgr_or_gray: np.ndarray, width: int, height: int) -> bool:
        """Resize frame, convert to grayscale, and write into Gforth's stdin."""
        if not self.is_alive or self._proc is None or self._proc.stdin is None:
            return False

        width = max(1, int(width))
        height = max(1, int(height))

        # Convert to grayscale if necessary
        if len(frame_bgr_or_gray.shape) == 3:
            gray = cv2.cvtColor(frame_bgr_or_gray, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame_bgr_or_gray

        resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
        raw_pixels = resized.tobytes()
        header = struct.pack("<HH", width, height)

        try:
            self._proc.stdin.write(header + raw_pixels)
            self._proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def get_latest_frame(self, timeout: float = 0.5) -> Optional[str]:
        """Fetch the most recent rendered ASCII frame."""
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                return self._latest_frame

    def close(self) -> None:
        """Gracefully terminate Gforth subprocess and cleanup threads."""
        self._running = False
        if self._proc is not None:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except OSError:
                    pass
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> ForthRenderer:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
