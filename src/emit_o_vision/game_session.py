"""Wolfenstein-3D Forth game session manager for EMIT-O-VISION.

Spawns Gforth running wolf3d.fs, captures real-time ASCII/ANSI frames,
and forwards user input keys (WASD, Fire, Doors) from the Qt GUI into Gforth.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from emit_o_vision.renderer import find_gforth, get_base_dir


def get_wolf3d_script() -> Path:
    """Locate wolf3d.fs in source tree or packaged bundle."""
    base = get_base_dir()
    for candidate in (
        base / "game" / "wolf3d.fs",
        base / "src" / "game" / "wolf3d.fs",
        base / "wolf3d.fs",
        Path(__file__).resolve().parent.parent / "game" / "wolf3d.fs",
    ):
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parent.parent / "game" / "wolf3d.fs"


class Wolf3DSession:
    """Interactive game process wrapper for the Forth 3D engine."""

    def __init__(
        self,
        on_frame: Callable[[str], None],
        on_exit: Optional[Callable[[], None]] = None,
        gforth_path: Optional[str] = None,
    ) -> None:
        self.on_frame = on_frame
        self.on_exit = on_exit
        self.gforth_path = find_gforth(gforth_path)
        self.script_path = get_wolf3d_script()

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Launch the Forth game process and start reading stdout frames."""
        if not self.gforth_path:
            raise FileNotFoundError("Gforth wurde nicht gefunden.")
        if not self.script_path.is_file():
            raise FileNotFoundError(f"Wolf3D-Skript nicht gefunden: {self.script_path}")

        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen(
            [self.gforth_path, self.script_path.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.script_path.parent,
            bufsize=0,
            creationflags=flags,
        )

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="Wolf3DReader", daemon=True
        )
        self._reader_thread.start()
        return True

    def _read_loop(self) -> None:
        buf = bytearray()
        stdout = self._proc.stdout if self._proc else None
        if stdout is None:
            return

        while self._running:
            try:
                chunk = stdout.read(1024)
            except (OSError, ValueError):
                break

            if not chunk:
                break

            buf.extend(chunk)

            # Each frame ends with Form Feed (\x0c)
            while b"\x0c" in buf:
                frame_bytes, buf = buf.split(b"\x0c", 1)
                frame_text = frame_bytes.decode("latin1", errors="replace").strip("\r\n")
                if frame_text and self.on_frame:
                    self.on_frame(frame_text)

        self._running = False
        if self.on_exit:
            self.on_exit()

    def send_key(self, char: str) -> None:
        """Send a single key command into Gforth's stdin."""
        if not self.is_running or self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(char.encode("ascii", errors="ignore"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def stop(self) -> None:
        """Signal exit and close the game process."""
        self._running = False
        if self._proc is not None:
            if self._proc.stdin:
                try:
                    self._proc.stdin.write(b"q")
                    self._proc.stdin.flush()
                    self._proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

