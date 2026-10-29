"""PySide6 Fullscreen GUI for EMIT-O-VISION.

Features:
- Starts in fullscreen mode by default, maximizing available screen area,
  with easy toggle to windowed mode (Button, F11, Esc).
- ASCII output is centered horizontally and vertically in the app window.
- Supports full ANSI color rendering (e.g. for the 3D Wolfenstein engine).
- Dynamically scales the frame resolution to utilize maximum available screen space
  while preserving media aspect ratio.
- Compact top header bar with action buttons, camera selector dropdown, and live status information.
- Real-time rendering driven by the Forth backend (Gforth).
- Webcam feed toggle, camera device selection, file import dialog (image/video), and Drag & Drop file support.
- Built-in 3D Wolfenstein-style raycasting game powered by Forth (src/game/wolf3d.fs).
- Playback controls: Pause/Resume, Speed (Normal/Max), Font Size (+/-), Snapshot export (.txt).
- All user-visible labels in German, variable names and comments in English.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from emit_o_vision.game_session import Wolf3DSession
from emit_o_vision.logger import (
    clear_log_history,
    get_log_file_path,
    get_log_history,
    open_log_file,
    register_log_listener,
    setup_logging,
)
from emit_o_vision.renderer import ForthRenderer

logger = logging.getLogger("emit_o_vision.gui")


class LogSignalBridge(QObject):
    log_received = Signal(str)


log_bridge = LogSignalBridge()
register_log_listener(lambda line: log_bridge.log_received.emit(line))
from emit_o_vision.sources import (
    BaseSource,
    ImageSource,
    VideoSource,
    WebcamSource,
    is_image_file,
    is_video_file,
    open_media_file,
)

WELCOME_BANNER = """========================================================================
                   E M I T - O - V I S I O N
            ASCII-Video-Engine angetrieben durch Forth
========================================================================

Bereit zum Start!
- Waehle deine Kamera im Dropdown-Menue und klicke [Kamera starten].
- Klicke auf [Wolf3D Spiel], um den 3D-Retro-Shooter in Forth zu starten.
- Klicke auf [Datei laden...] oder ziehe ein Bild/Video direkt hierher.
- Vollbild umschalten mit [F11] oder [Esc] zum Verlassen.
- Schriftgroesse mit [A -] und [A +] anpassen."""

ANSI_ESC_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
ANSI_SPLIT_RE = re.compile(r"(\x1b\[[0-9;?]*[a-zA-Z])")


ANSI_COLOR_MAP: dict[int, QColor] = {
    0: QColor(220, 225, 230),   # Reset / Default
    30: QColor(0, 0, 0),        # Black
    31: QColor(205, 49, 49),    # Red
    32: QColor(13, 188, 121),   # Green
    33: QColor(229, 229, 16),   # Yellow
    34: QColor(36, 114, 200),   # Blue
    35: QColor(188, 63, 188),   # Magenta
    36: QColor(17, 168, 205),   # Cyan
    37: QColor(229, 229, 229),  # White
    90: QColor(102, 102, 102),  # Bright Black / Gray
    91: QColor(241, 76, 76),    # Bright Red
    92: QColor(35, 209, 139),   # Bright Green
    93: QColor(245, 245, 67),   # Bright Yellow
    94: QColor(59, 142, 234),   # Bright Blue
    95: QColor(214, 112, 214),  # Bright Magenta
    96: QColor(41, 184, 219),   # Bright Cyan
    97: QColor(255, 255, 255),  # Bright White
}


class RenderWorker(QObject):
    """Background worker driving media capture and Forth rendering without blocking the UI."""

    frame_rendered = Signal(str, float, int, int)  # ascii_text, fps, cols, rows
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, gforth_path: Optional[str] = None) -> None:
        super().__init__()
        self.gforth_path = gforth_path
        self._renderer: Optional[ForthRenderer] = None
        self._source: Optional[BaseSource] = None
        self._running = False
        self._paused = False
        self._max_speed = False

        self._canvas_w = 1280
        self._canvas_h = 720
        self._char_w = 8
        self._char_h = 16
        self._metrics_lock = threading.Lock()

        self._camera_index = 0

    def set_camera_index(self, index: int) -> None:
        self._camera_index = index

    def switch_camera(self, index: int) -> bool:
        """Switch active camera to a new index while running."""
        self._camera_index = index
        src = WebcamSource(camera_index=index)
        if not src.is_opened:
            self.error_occurred.emit(f"Konnte Kamera mit Index {index} nicht oeffnen.")
            return False
        self.set_source(src)
        return True

    def set_canvas_metrics(self, canvas_w: int, canvas_h: int, char_w: int, char_h: int) -> None:
        """Update available canvas area and font character dimensions."""
        with self._metrics_lock:
            self._canvas_w = max(100, canvas_w)
            self._canvas_h = max(50, canvas_h)
            self._char_w = max(1, char_w)
            self._char_h = max(1, char_h)

    def set_source(self, source: Optional[BaseSource]) -> None:
        if self._source is not None:
            self._source.release()
        self._source = source
        if source:
            self.status_changed.emit(f"Quelle aktiv: {source.name}")
        else:
            self.status_changed.emit("Keine aktive Quelle")

    def toggle_webcam(self) -> bool:
        """Toggle webcam source. Returns True if webcam is now active."""
        if isinstance(self._source, WebcamSource) and self._source.is_opened:
            self.set_source(None)
            return False
        src = WebcamSource(camera_index=self._camera_index)
        if not src.is_opened:
            self.error_occurred.emit(f"Konnte Webcam mit Index {self._camera_index} nicht oeffnen.")
            return False
        self.set_source(src)
        return True

    def pause(self) -> None:
        self._paused = True
        if self._source:
            self._source.pause()

    def resume(self) -> None:
        self._paused = False
        if self._source:
            self._source.resume()

    def toggle_pause(self) -> bool:
        if self._source is not None:
            self._paused = self._source.toggle_pause()
            return self._paused
        return False

    def toggle_speed(self) -> bool:
        self._max_speed = not self._max_speed
        return self._max_speed

    def start_loop(self) -> None:
        """Main rendering loop executed in background QThread."""
        try:
            self._renderer = ForthRenderer(gforth_path=self.gforth_path)
        except Exception as e:
            self.error_occurred.emit(f"Gforth-Initialisierungsfehler: {e}")
            return

        self._running = True
        fps_tracker_time = time.perf_counter()
        fps_frame_count = 0
        current_fps = 0.0

        while self._running:
            loop_start = time.perf_counter()

            if self._paused or self._source is None or self._source.is_paused:
                time.sleep(0.05)
                continue

            ok, frame = self._source.read()
            if not ok or frame is None:
                if isinstance(self._source, ImageSource):
                    time.sleep(0.05)
                    continue
                time.sleep(0.02)
                continue

            frame_h, frame_w = frame.shape[:2]
            with self._metrics_lock:
                cw = self._canvas_w
                ch = self._canvas_h
                char_w = self._char_w
                char_h = self._char_h

            # Maximize available screen space while preserving image aspect ratio
            max_cols = max(10, cw // char_w)
            max_rows = max(5, ch // char_h)
            aspect = frame_w / max(1, frame_h)

            # Fit to width first
            cols = max_cols
            rows = round(cols * (char_w / char_h) / aspect)

            # If height exceeds available canvas, fit to height instead
            if rows > max_rows:
                rows = max_rows
                cols = round(rows * aspect * (char_h / char_w))
                cols = min(cols, max_cols)

            cols = max(10, cols)
            rows = max(5, rows)

            success = self._renderer.send_frame(frame, width=cols, height=rows)
            if not success:
                time.sleep(0.02)
                continue

            rendered = self._renderer.get_latest_frame(timeout=0.2)
            if rendered:
                fps_frame_count += 1
                now = time.perf_counter()
                if now - fps_tracker_time >= 0.5:
                    current_fps = fps_frame_count / (now - fps_tracker_time)
                    fps_frame_count = 0
                    fps_tracker_time = now

                self.frame_rendered.emit(rendered, current_fps, cols, rows)

            # Image only needs periodic updates
            if isinstance(self._source, ImageSource):
                time.sleep(0.05)
                continue

            # Frame rate pacing
            if not self._max_speed:
                target_delay = 1.0 / max(1.0, self._source.fps)
                elapsed = time.perf_counter() - loop_start
                sleep_sec = target_delay - elapsed
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

        # Cleanup
        if self._source:
            self._source.release()
            self._source = None
        if self._renderer:
            self._renderer.close()
            self._renderer = None

    def stop(self) -> None:
        self._running = False


class AsciiCanvas(QWidget):
    """Monospace canvas widget that renders ASCII text centered and calculates grid dimensions."""

    metrics_changed = Signal(int, int, int, int)  # canvas_w, canvas_h, char_w, char_h

    def __init__(self, font_size: int = 10, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._font_size = font_size
        self._font = QFont("Consolas", self._font_size)
        self._font.setStyleHint(QFont.Monospace)
        self._font.setFixedPitch(True)
        self._font.setKerning(False)
        self._text: str = WELCOME_BANNER
        self._bg_color = QColor(10, 10, 14)
        self._text_color = QColor(220, 225, 230)
        self.setFocusPolicy(Qt.StrongFocus)

    @property
    def font_size(self) -> int:
        return self._font_size

    def set_font_size(self, size: int) -> None:
        self._font_size = max(5, min(48, size))
        self._font.setPointSize(self._font_size)
        self._update_metrics()
        self.update()

    def increase_font(self) -> None:
        self.set_font_size(self._font_size + 1)

    def decrease_font(self) -> None:
        self.set_font_size(self._font_size - 1)

    def set_ascii_text(self, text: str) -> None:
        self._text = text
        self.update()

    def get_ascii_text(self) -> str:
        # Return cleaned text without ANSI codes for snapshots
        return ANSI_ESC_RE.sub("", self._text).replace("\r", "")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_metrics()

    def _update_metrics(self) -> None:
        fm = QFontMetrics(self._font)
        char_w = max(1, fm.horizontalAdvance("X"))
        char_h = max(1, fm.lineSpacing())
        self.metrics_changed.emit(self.width(), self.height(), char_w, char_h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)
        painter.setFont(self._font)

        fm = QFontMetrics(self._font)
        char_w = max(1, fm.horizontalAdvance("X"))
        char_h = max(1, fm.lineSpacing())

        lines = self._text.replace("\r", "").split("\n")
        num_lines = len(lines)

        # Calculate max visible columns stripping ANSI escape sequences
        clean_lines = [ANSI_ESC_RE.sub("", line) for line in lines]
        max_cols = max((len(c) for c in clean_lines), default=0)

        # Calculate pixel dimensions of the text block
        block_w = max_cols * char_w
        block_h = num_lines * char_h

        # Center horizontally and vertically within the canvas
        start_x = max(0, (self.width() - block_w) // 2)
        start_y = max(0, (self.height() - block_h) // 2)

        # Render line by line, supporting ANSI colors.
        # Wichtig: Die Farbe gilt wie in einem echten Terminal ueber Zeilengrenzen
        # hinweg (Forth sendet Farbcodes nur bei Farbwechsel).
        cur_color = self._text_color
        y = start_y + fm.ascent()
        for raw_line, clean_line in zip(lines, clean_lines):
            if "\x1b[" not in raw_line:
                painter.setPen(cur_color)
                painter.drawText(start_x, y, clean_line)
            else:
                cur_x = start_x
                for part in ANSI_SPLIT_RE.split(raw_line):
                    if not part:
                        continue
                    if part.startswith("\x1b["):
                        if part.endswith("m"):
                            code_str = part[2:-1]
                            try:
                                code = int(code_str.split(";")[-1]) if code_str else 0
                                cur_color = ANSI_COLOR_MAP.get(code, self._text_color)
                            except ValueError:
                                pass
                        # Alle anderen Steuersequenzen ignorieren
                        continue
                    painter.setPen(cur_color)
                    painter.drawText(cur_x, y, part)
                    cur_x += len(part) * char_w

            y += char_h


class LogViewerDialog(QDialog):
    """Floating live diagnostic log viewer window."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EMIT-O-VISION - Diagnose & Live-Logbuch")
        self.resize(850, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #16161e;
                color: #c0caf5;
            }
            QPlainTextEdit {
                background-color: #0f0f14;
                color: #7aa2f7;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #2e2e3e;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton {
                background-color: #24283b;
                color: #ffffff;
                border: 1px solid #414868;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3b4261;
            }
            QLabel {
                color: #9aa5ce;
                font-size: 11px;
            }
            QCheckBox {
                color: #c0caf5;
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Log text area
        self.txt_log = QPlainTextEdit(self)
        self.txt_log.setReadOnly(True)
        layout.addWidget(self.txt_log, stretch=1)

        # Bottom toolbar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        self.chk_autoscroll = QCheckBox("Automatisch scrollen", self)
        self.chk_autoscroll.setChecked(True)
        bottom_bar.addWidget(self.chk_autoscroll)

        bottom_bar.addStretch(1)

        self.btn_open_file = QPushButton("Log-Datei öffnen", self)
        self.btn_open_file.clicked.connect(open_log_file)
        bottom_bar.addWidget(self.btn_open_file)

        self.btn_clear = QPushButton("Log leeren", self)
        self.btn_clear.clicked.connect(self._clear_logs)
        bottom_bar.addWidget(self.btn_clear)

        layout.addLayout(bottom_bar)

        # Status line with file path
        self.lbl_path = QLabel(f"Logdatei: {get_log_file_path()}", self)
        layout.addWidget(self.lbl_path)

        # Load existing history
        for line in get_log_history():
            self.txt_log.appendPlainText(line)
        self._scroll_to_bottom()

    def append_log_line(self, line: str) -> None:
        self.txt_log.appendPlainText(line)
        if self.chk_autoscroll.isChecked():
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        sb = self.txt_log.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _clear_logs(self) -> None:
        clear_log_history()
        self.txt_log.clear()


class MainWindow(QMainWindow):
    """Main application window with header toolbar, camera selection, and Wolf3D support."""

    file_dropped = Signal(str)
    game_frame_received = Signal(str)
    game_stats_received = Signal(dict)

    def __init__(self, gforth_path: Optional[str] = None) -> None:
        super().__init__()
        self.gforth_path = gforth_path
        self._game_session: Optional[Wolf3DSession] = None
        self._log_viewer: Optional[LogViewerDialog] = None

        self.setWindowTitle("EMIT-O-VISION Studio (Forth ASCII Video & 3D Game)")
        self.resize(1280, 800)

        # Central container
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Header bar ---
        header = QWidget(self)
        header.setFixedHeight(48)
        header.setStyleSheet("""
            QWidget {
                background-color: #1a1a24;
                color: #e0e0e0;
                border-bottom: 1px solid #2e2e3e;
            }
            QPushButton {
                background-color: #2b2b3d;
                color: #ffffff;
                border: 1px solid #41415a;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3d3d56;
                border-color: #606085;
            }
            QPushButton:pressed {
                background-color: #1f1f2e;
            }
            QComboBox {
                background-color: #2b2b3d;
                color: #ffffff;
                border: 1px solid #41415a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 170px;
            }
            QComboBox:hover {
                border-color: #606085;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a24;
                color: #ffffff;
                selection-background-color: #3d3d56;
            }
            QLabel {
                font-size: 12px;
                color: #a0a0b8;
            }
        """)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)

        # Action buttons
        self.btn_webcam = QPushButton("Kamera starten")
        self.btn_webcam.clicked.connect(self._on_toggle_webcam)
        header_layout.addWidget(self.btn_webcam)

        # Camera selector dropdown
        self.combo_camera = QComboBox(self)
        self.combo_camera.setToolTip("Kameraquelle auswaehlen")
        self._populate_cameras()
        self.combo_camera.currentIndexChanged.connect(self._on_camera_changed)
        header_layout.addWidget(self.combo_camera)

        # Wolf3D game button
        self.btn_wolf3d = QPushButton("Wolf3D Spiel")
        self.btn_wolf3d.setToolTip("3D Wolfenstein Raycaster starten (reines Forth)")
        self.btn_wolf3d.setStyleSheet("""
            QPushButton {
                background-color: #243d2b;
                border-color: #35583f;
            }
            QPushButton:hover {
                background-color: #31533b;
            }
        """)
        self.btn_wolf3d.clicked.connect(self._on_toggle_wolf3d)
        header_layout.addWidget(self.btn_wolf3d)

        self.btn_file = QPushButton("Datei laden...")
        self.btn_file.clicked.connect(self._on_open_file)
        header_layout.addWidget(self.btn_file)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self._on_toggle_pause)
        header_layout.addWidget(self.btn_pause)

        self.btn_speed = QPushButton("Tempo: Normal")
        self.btn_speed.clicked.connect(self._on_toggle_speed)
        header_layout.addWidget(self.btn_speed)

        self.btn_font_dec = QPushButton("A -")
        self.btn_font_dec.setToolTip("Schrift verkleinern (hoehere Aufloesung)")
        self.btn_font_dec.clicked.connect(self._on_decrease_font)
        header_layout.addWidget(self.btn_font_dec)

        self.btn_font_inc = QPushButton("A +")
        self.btn_font_inc.setToolTip("Schrift vergroessern (groebere Aufloesung)")
        self.btn_font_inc.clicked.connect(self._on_increase_font)
        header_layout.addWidget(self.btn_font_inc)

        self.btn_snapshot = QPushButton("Schnappschuss")
        self.btn_snapshot.setToolTip("Aktuelles ASCII-Bild als Textdatei speichern")
        self.btn_snapshot.clicked.connect(self._on_save_snapshot)
        header_layout.addWidget(self.btn_snapshot)

        self.btn_fullscreen = QPushButton("Fenstermodus [F11]")
        self.btn_fullscreen.setToolTip("Vollbild umschalten (F11)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        header_layout.addWidget(self.btn_fullscreen)

        header_layout.addStretch(1)

        # Live status info
        self.lbl_status = QLabel("Bereit")
        header_layout.addWidget(self.lbl_status)

        self.btn_quit = QPushButton("Beenden")
        self.btn_quit.setStyleSheet("""
            QPushButton {
                background-color: #4a2228;
                border-color: #6d333b;
            }
            QPushButton:hover {
                background-color: #632d36;
            }
        """)
        self.btn_quit.clicked.connect(self.close)
        header_layout.addWidget(self.btn_quit)

        self.btn_log = QPushButton("Logbuch [F12]")
        self.btn_log.setToolTip("Echtzeit-Logbuch & Diagnosefenster öffnen (F12)")
        self.btn_log.setStyleSheet("""
            QPushButton {
                background-color: #2e3440;
                border-color: #4c566a;
            }
            QPushButton:hover {
                background-color: #3b4252;
            }
        """)
        self.btn_log.clicked.connect(self._on_toggle_log_viewer)
        header_layout.addWidget(self.btn_log)

        # Header buttons shouldn't steal keyboard focus from the game / canvas
        for btn in (
            self.btn_webcam,
            self.btn_wolf3d,
            self.btn_file,
            self.btn_pause,
            self.btn_speed,
            self.btn_font_dec,
            self.btn_font_inc,
            self.btn_snapshot,
            self.btn_fullscreen,
            self.btn_quit,
            self.btn_log,
        ):
            btn.setFocusPolicy(Qt.NoFocus)

        self.combo_camera.setFocusPolicy(Qt.ClickFocus)

        main_layout.addWidget(header)

        # --- ASCII Monospace Canvas ---
        self.canvas = AsciiCanvas(font_size=10, parent=self)
        main_layout.addWidget(self.canvas, stretch=1)

        # --- Background Worker & Thread ---
        self.worker_thread = QThread(self)
        self.worker = RenderWorker(gforth_path=gforth_path)
        self.worker.moveToThread(self.worker_thread)

        self.canvas.metrics_changed.connect(self.worker.set_canvas_metrics, Qt.DirectConnection)
        self.worker.frame_rendered.connect(self._on_frame_rendered)
        self.worker.status_changed.connect(self._on_worker_status)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker_thread.started.connect(self.worker.start_loop)
        self.file_dropped.connect(self._on_file_dropped)
        self.game_frame_received.connect(self._on_game_frame)
        self.game_stats_received.connect(self._on_game_stats)

        # Sync initial selected camera
        initial_cam = self.combo_camera.currentData()
        if initial_cam is not None:
            self.worker.set_camera_index(int(initial_cam))

        self.worker_thread.start()

        # Install application event filter so game controls and global shortcuts
        # work reliably regardless of which widget currently has focus
        app_inst = QApplication.instance()
        if app_inst:
            app_inst.installEventFilter(self)

        # Start directly in Fullscreen mode (as requested by user)
        self.showFullScreen()
        self._update_fullscreen_button_text()
        self.canvas.setFocus()
        self.canvas._update_metrics()

        log_bridge.log_received.connect(self._on_log_line_received)

    def _on_toggle_log_viewer(self) -> None:
        """Toggle floating log viewer dialog."""
        if self._log_viewer is None:
            self._log_viewer = LogViewerDialog(self)
        if self._log_viewer.isVisible():
            self._log_viewer.hide()
        else:
            self._log_viewer.show()
            self._log_viewer.raise_()
            self._log_viewer.activateWindow()

    def _on_log_line_received(self, line: str) -> None:
        if self._log_viewer is not None:
            self._log_viewer.append_log_line(line)

    def _populate_cameras(self) -> None:
        """Scan and populate available video input devices in combo box."""
        self.combo_camera.clear()
        found_indices = set()
        try:
            from PySide6.QtMultimedia import QMediaDevices
            qt_devs = QMediaDevices.videoInputs()
            for i, dev in enumerate(qt_devs):
                name = dev.description() or f"Kamera {i}"
                self.combo_camera.addItem(f"{i}: {name}", i)
                found_indices.add(i)
        except Exception:
            pass

        # Also provide fallback choices for Camera 0, 1, 2 if not listed
        for idx in (0, 1, 2):
            if idx not in found_indices:
                self.combo_camera.addItem(f"Kamera {idx}", idx)

    def _on_camera_changed(self, index: int) -> None:
        cam_idx = self.combo_camera.currentData()
        if cam_idx is not None:
            selected_index = int(cam_idx)
            self.worker.set_camera_index(selected_index)
            # If camera is currently actively running, switch immediately
            if isinstance(self.worker._source, WebcamSource):
                self.worker.switch_camera(selected_index)

    def _on_toggle_wolf3d(self) -> None:
        """Toggle Wolf3D Forth game."""
        if self._game_session and self._game_session.is_running:
            self._stop_wolf3d()
        else:
            self._start_wolf3d()

    def _start_wolf3d(self) -> None:
        logger.info("Starte Wolf3D-Spielmodus...")
        # Stop webcam / video if active
        if isinstance(self.worker._source, WebcamSource):
            self.worker.set_source(None)
            self.btn_webcam.setText("Kamera starten")
        self.worker.pause()

        try:
            self._game_session = Wolf3DSession(
                on_frame=lambda frame: self.game_frame_received.emit(frame),
                on_exit=lambda: self.game_frame_received.emit(""),
                on_stats=lambda stats: self.game_stats_received.emit(stats),
                gforth_path=self.gforth_path,
            )
            self._game_session.start()
            self.btn_wolf3d.setText("Spiel beenden")
            self.btn_wolf3d.setStyleSheet("""
                QPushButton {
                    background-color: #4a2228;
                    border-color: #6d333b;
                }
                QPushButton:hover {
                    background-color: #632d36;
                }
            """)
            self.lbl_status.setText("Wolf3D aktiv | [WASD / Pfeile] Bewegen, [F / Enter] Feuer, [Leertaste] Tuer, [R] Neu, [Q] Ende")
            self.canvas.setFocus()
            logger.info("Wolf3D-Spiel erfolgreich gestartet. Tastaturfokus auf Canvas gesetzt.")
        except Exception as e:
            logger.error(f"Fehler beim Starten von Wolf3D: {e}", exc_info=True)
            QMessageBox.critical(self, "Wolf3D Fehler", f"Konnte Wolf3D nicht starten:\n{e}")
            self.worker.resume()

    def _stop_wolf3d(self) -> None:
        logger.info("Beende Wolf3D-Spielmodus...")
        if self._game_session:
            self._game_session.stop()
            self._game_session = None

        self.btn_wolf3d.setText("Wolf3D Spiel")
        self.btn_wolf3d.setStyleSheet("""
            QPushButton {
                background-color: #243d2b;
                border-color: #35583f;
            }
            QPushButton:hover {
                background-color: #31533b;
            }
        """)
        self.worker.resume()
        self.canvas.set_ascii_text(WELCOME_BANNER)
        self.canvas.setFocus()
        self.lbl_status.setText("Bereit")

    def _on_game_frame(self, frame_text: str) -> None:
        if frame_text:
            self.canvas.set_ascii_text(frame_text)
        elif self._game_session:
            # Game ended by process exit
            self._stop_wolf3d()

    def _on_game_stats(self, stats: dict) -> None:
        px = stats.get("px")
        py = stats.get("py")
        pa = stats.get("pa")
        k = stats.get("k")
        if px is not None and py is not None and pa is not None:
            tx = px >> 14
            ty = py >> 14
            deg = (pa * 360.0) / 64.0
            k_char = chr(k) if k and 32 <= k <= 126 else (str(k) if k else "-")
            self.lbl_status.setText(
                f"Wolf3D aktiv | Pos: Tile ({tx}, {ty}) [px={px}, py={py}] | "
                f"Winkel: {pa} ({deg:.1f}°) | Letzte Taste: {k_char!r}"
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.canvas._update_metrics()

    def toggle_fullscreen(self) -> None:
        """Toggle between Fullscreen and Windowed mode."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._update_fullscreen_button_text()
        self.canvas._update_metrics()

    def _update_fullscreen_button_text(self) -> None:
        if self.isFullScreen():
            self.btn_fullscreen.setText("Fenstermodus [F11]")
        else:
            self.btn_fullscreen.setText("Vollbild [F11]")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_key_press(event, watched=watched):
                return True
        return super().eventFilter(watched, event)

    def _handle_key_press(self, event: QKeyEvent, watched: Optional[QObject] = None) -> bool:
        key = event.key()
        text = event.text()
        text_lower = text.lower()
        in_game = bool(self._game_session and self._game_session.is_running)
        watched_name = type(watched).__name__ if watched else "None"

        logger.debug(f"[Tastatur] key={key} (hex={hex(key)}) text={text!r} watched={watched_name} in_game={in_game}")

        # Global toggle for log viewer (F12)
        if key == Qt.Key_F12:
            self._on_toggle_log_viewer()
            return True

        # Route keys to Wolf3D game if active
        if in_game and self._game_session:
            if key in (Qt.Key_W, Qt.Key_Up) or text_lower == "w":
                logger.info("[Wolf3D] Befehl: VORWAERTS ('w')")
                self._game_session.send_key("w")
                return True
            elif key in (Qt.Key_S, Qt.Key_Down) or text_lower == "s":
                logger.info("[Wolf3D] Befehl: RUECKWAERTS ('s')")
                self._game_session.send_key("s")
                return True
            elif key in (Qt.Key_A, Qt.Key_Left) or text_lower == "a":
                logger.info("[Wolf3D] Befehl: DREHUNG LINKS ('a')")
                self._game_session.send_key("a")
                return True
            elif key in (Qt.Key_D, Qt.Key_Right) or text_lower == "d":
                logger.info("[Wolf3D] Befehl: DREHUNG RECHTS ('d')")
                self._game_session.send_key("d")
                return True
            elif key in (Qt.Key_F, Qt.Key_Return, Qt.Key_Enter) or text_lower == "f":
                logger.info("[Wolf3D] Befehl: FEUER ('f')")
                self._game_session.send_key("f")
                return True
            elif key == Qt.Key_Space or text == " ":
                logger.info("[Wolf3D] Befehl: TUER (' ')")
                self._game_session.send_key(" ")
                return True
            elif key == Qt.Key_R or text_lower == "r":
                logger.info("[Wolf3D] Befehl: DUNGEON NEU ('r')")
                self._game_session.send_key("r")
                return True
            elif key == Qt.Key_Q or text_lower == "q":
                logger.info("[Wolf3D] Befehl: BEENDEN ('q')")
                self._stop_wolf3d()
                return True
            elif key == Qt.Key_F11:
                self.toggle_fullscreen()
                return True
            elif key == Qt.Key_Escape:
                if self.isFullScreen():
                    self.showNormal()
                    self._update_fullscreen_button_text()
                    self.canvas._update_metrics()
                else:
                    self._stop_wolf3d()
                return True
            # Consume other keys while in game to prevent toolbar navigation or button clicks
            return True

        # Normal key bindings when game is not active
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            return True
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            self._update_fullscreen_button_text()
            self.canvas._update_metrics()
            return True
        elif event.key() == Qt.Key_Space:
            if not isinstance(watched, QComboBox):
                self._on_toggle_pause()
                return True

        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._handle_key_press(event):
            event.accept()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(is_image_file(u.toLocalFile()) or is_video_file(u.toLocalFile()) for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        for u in urls:
            path = u.toLocalFile()
            if is_image_file(path) or is_video_file(path):
                self.file_dropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def _on_file_dropped(self, file_path: str) -> None:
        self._load_file(file_path)

    def _on_toggle_webcam(self) -> None:
        if self._game_session and self._game_session.is_running:
            self._stop_wolf3d()

        active = self.worker.toggle_webcam()
        if active:
            self.btn_webcam.setText("Kamera stoppen")
        else:
            self.btn_webcam.setText("Kamera starten")
            self.canvas.set_ascii_text(WELCOME_BANNER)

    def _on_open_file(self) -> None:
        if self._game_session and self._game_session.is_running:
            self._stop_wolf3d()

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Bild- oder Videodatei oeffnen",
            "",
            "Mediadateien (*.png *.jpg *.jpeg *.bmp *.webp *.mp4 *.avi *.mkv *.mov);;Bilder (*.png *.jpg *.jpeg *.bmp *.webp);;Videos (*.mp4 *.avi *.mkv *.mov);;Alle Dateien (*.*)",
        )
        if file_path:
            self._load_file(file_path)

    def _load_file(self, file_path: str) -> None:
        if self._game_session and self._game_session.is_running:
            self._stop_wolf3d()

        source = open_media_file(file_path, loop_video=True)
        if not source:
            QMessageBox.warning(
                self,
                "Dateifehler",
                f"Die Datei konnte nicht als Bild oder Video geladen werden:\n{file_path}",
            )
            return

        self.btn_webcam.setText("Kamera starten")
        self.btn_pause.setText("Pause")
        self.worker.set_source(source)

    def _on_toggle_pause(self) -> None:
        is_paused = self.worker.toggle_pause()
        self.btn_pause.setText("Weiter" if is_paused else "Pause")

    def _on_toggle_speed(self) -> None:
        is_max = self.worker.toggle_speed()
        self.btn_speed.setText("Tempo: Max" if is_max else "Tempo: Normal")

    def _on_decrease_font(self) -> None:
        self.canvas.decrease_font()

    def _on_increase_font(self) -> None:
        self.canvas.increase_font()

    def _on_save_snapshot(self) -> None:
        text = self.canvas.get_ascii_text()
        if not text or text == WELCOME_BANNER:
            QMessageBox.information(
                self,
                "Kein Bild vorhanden",
                "Es ist aktuell kein aktiver ASCII-Frame zum Speichern vorhanden.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Schnappschuss als Textdatei speichern",
            f"emit_o_vision_{int(time.time())}.txt",
            "Textdateien (*.txt);;Alle Dateien (*.*)",
        )
        if file_path:
            try:
                Path(file_path).write_text(text, encoding="utf-8")
                QMessageBox.information(
                    self,
                    "Gespeichert",
                    f"Schnappschuss erfolgreich gespeichert unter:\n{file_path}",
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Fehler beim Speichern", f"Fehler beim Schreiben der Datei:\n{e}"
                )

    def _on_frame_rendered(self, text: str, fps: float, cols: int, rows: int) -> None:
        if self._game_session and self._game_session.is_running:
            return
        self.canvas.set_ascii_text(text)
        self.lbl_status.setText(f"Aufloesung: {cols}x{rows} | {fps:.1f} FPS")

    def _on_worker_status(self, msg: str) -> None:
        if self._game_session and self._game_session.is_running:
            return
        self.lbl_status.setText(msg)

    def _on_worker_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "EMIT-O-VISION Fehler", err_msg)

    def closeEvent(self, event) -> None:
        try:
            app_inst = QApplication.instance()
            if app_inst:
                app_inst.removeEventFilter(self)
        except Exception:
            pass
        if self._game_session:
            self._game_session.stop()
            self._game_session = None
        self.worker.stop()
        self.worker_thread.quit()
        self.worker_thread.wait(1500)
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="EMIT-O-VISION ASCII Video Engine")
    parser.add_argument("--debug", "--log", action="store_true", help="Ausfuehrliches Logging aktivieren")
    parser.add_argument("--gforth", type=str, default=None, help="Expliziter Pfad zur Gforth-Executable")
    args, _ = parser.parse_known_args()

    setup_logging(debug=args.debug)

    app = QApplication(sys.argv)
    app.setApplicationName("EMIT-O-VISION")

    window = MainWindow(gforth_path=args.gforth)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
