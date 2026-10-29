"""Wolfenstein-3D Forth game session manager for EMIT-O-VISION.

Spawns Gforth running wolf3d.fs, captures real-time ASCII/ANSI frames,
and forwards user input keys (WASD, Fire, Doors) from the Qt GUI into Gforth.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from emit_o_vision.renderer import find_gforth, get_base_dir

logger = logging.getLogger("emit_o_vision.wolf3d")


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
        self._stderr_thread: Optional[threading.Thread] = None
        self._frame_count = 0

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Launch the Forth game process and start reading stdout frames."""
        if not self.gforth_path:
            logger.error("Gforth-Pfad nicht gefunden.")
            raise FileNotFoundError("Gforth wurde nicht gefunden.")
        if not self.script_path.is_file():
            logger.error(f"Wolf3D-Skript nicht gefunden: {self.script_path}")
            raise FileNotFoundError(f"Wolf3D-Skript nicht gefunden: {self.script_path}")

        logger.info(f"Starte Wolf3D: {self.gforth_path} {self.script_path.name} in {self.script_path.parent}")

        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen(
            [self.gforth_path, self.script_path.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.script_path.parent,
            bufsize=0,
            creationflags=flags,
        )

        logger.info(f"Wolf3D-Prozess gestartet mit PID: {self._proc.pid}")

        self._running = True
        self._frame_count = 0
        self._reader_thread = threading.Thread(
            target=self._read_loop, name="Wolf3DReader", daemon=True
        )
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name="Wolf3DStderr", daemon=True
        )
        self._stderr_thread.start()
        return True

    def _stderr_loop(self) -> None:
        stderr = self._proc.stderr if self._proc else None
        if stderr is None:
            return
        while self._running:
            try:
                line = stderr.readline()
                if not line:
                    break
                text = line.decode("latin1", errors="replace").strip()
                if text:
                    logger.warning(f"[Gforth Stderr] {text}")
            except Exception:
                break

    def _read_loop(self) -> None:
        buf = bytearray()
        stdout = self._proc.stdout if self._proc else None
        if stdout is None:
            return

        logger.debug("Wolf3D Reader-Thread gestartet, warte auf Frames...")

        while self._running:
            try:
                chunk = stdout.read(1024)
            except (OSError, ValueError) as e:
                logger.debug(f"Wolf3D stdout read beendet: {e}")
                break

            if not chunk:
                logger.debug("Wolf3D stdout EOF erreicht.")
                break

            buf.extend(chunk)

            # Each frame ends with Form Feed (\x0c)
            while b"\x0c" in buf:
                frame_bytes, buf = buf.split(b"\x0c", 1)
                frame_text = frame_bytes.decode("latin1", errors="replace").strip("\r\n")
                if frame_text and self.on_frame:
                    self._frame_count += 1
                    if self._frame_count == 1:
                        logger.info("Erster Wolf3D-Frame erfolgreich empfangen.")
                    elif self._frame_count % 100 == 0:
                        logger.debug(f"Wolf3D-Frames gerendert: {self._frame_count}")
                    self.on_frame(frame_text)

        self._running = False
        logger.info(f"Wolf3D Reader-Thread beendet. Insgesamt {self._frame_count} Frames empfangen.")
        if self.on_exit:
            self.on_exit()

    def send_key(self, char: str) -> None:
        """Send a single key command into Gforth's stdin."""
        if not self.is_running or self._proc is None or self._proc.stdin is None:
            logger.warning(f"send_key('{char}') ignoriert: Prozess laeuft nicht (running={self._running})")
            return
        try:
            raw_bytes = char.encode("ascii", errors="ignore")
            logger.debug(f"[Wolf3D Input] Sende Taste: {char!r} (Bytes: {raw_bytes!r}) an Gforth Stdin")
            self._proc.stdin.write(raw_bytes)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error(f"[Wolf3D Input] Fehler beim Senden von Taste {char!r}: {e}")

    def stop(self) -> None:
        """Signal exit and close the game process."""
        logger.info("Wolf3D wird gestoppt...")
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
                ret = self._proc.wait(timeout=1.0)
                logger.info(f"Wolf3D-Prozess normal beendet mit Code {ret}")
            except subprocess.TimeoutExpired:
                logger.warning("Wolf3D-Prozess reagiert nicht, sende kill()...")
                self._proc.kill()
            self._proc = None

