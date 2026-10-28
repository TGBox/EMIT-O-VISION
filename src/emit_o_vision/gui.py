"""PySide6 Fullscreen GUI for EMIT-O-VISION.

Features:
- Starts in fullscreen mode by default, maximizing available screen area,
  with easy toggle to windowed mode (Button, F11, Esc).
- ASCII output is centered horizontally and vertically in the app window.
- Dynamically scales the frame resolution to utilize maximum available screen space
  while preserving media aspect ratio.
- Compact top header bar with action buttons and live status information.
- Real-time rendering driven by the Forth backend (Gforth).
- Webcam feed toggle, file import dialog (image/video), and Drag & Drop file support.
- Playback controls: Pause/Resume, Speed (Normal/Max), Font Size (+/-), Snapshot export (.txt).
- All user-visible labels in German, variable names and comments in English.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRect, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from emit_o_vision.renderer import ForthRenderer
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
- Klicke oben auf [Kamera starten], um den Live-Webcamfeed zu aktivieren.
- Klicke auf [Datei laden...] oder ziehe ein Bild/Video direkt hierher.
- Vollbild umschalten mit [F11] oder [Esc] zum Verlassen.
- Schriftgroesse mit [A -] und [A +] anpassen."""


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

            if self._source is None or self._source.is_paused:
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
        return self._text

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
        painter.setPen(self._text_color)
        painter.setFont(self._font)

        fm = QFontMetrics(self._font)
        char_w = max(1, fm.horizontalAdvance("X"))
        char_h = max(1, fm.lineSpacing())

        lines = self._text.split("\n")
        num_lines = len(lines)
        max_cols = max((len(l) for l in lines), default=0)

        # Calculate pixel dimensions of the text block
        block_w = max_cols * char_w
        block_h = num_lines * char_h

        # Center horizontally and vertically within the canvas
        start_x = max(0, (self.width() - block_w) // 2)
        start_y = max(0, (self.height() - block_h) // 2)

        # Render line by line
        y = start_y + fm.ascent()
        for line in lines:
            painter.drawText(start_x, y, line)
            y += char_h


class MainWindow(QMainWindow):
    """Main application window with header toolbar and fullscreen support."""

    file_dropped = Signal(str)

    def __init__(self, gforth_path: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("EMIT-O-VISION Studio (Forth ASCII Video)")
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

        self.worker_thread.start()

        # Start directly in Fullscreen mode (as requested by user)
        self.showFullScreen()
        self._update_fullscreen_button_text()
        self.canvas._update_metrics()

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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            self._update_fullscreen_button_text()
            self.canvas._update_metrics()
            event.accept()
        elif event.key() == Qt.Key_Space:
            self._on_toggle_pause()
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
        active = self.worker.toggle_webcam()
        if active:
            self.btn_webcam.setText("Kamera stoppen")
        else:
            self.btn_webcam.setText("Kamera starten")
            self.canvas.set_ascii_text(WELCOME_BANNER)

    def _on_open_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Bild- oder Videodatei oeffnen",
            "",
            "Mediadateien (*.png *.jpg *.jpeg *.bmp *.webp *.mp4 *.avi *.mkv *.mov);;Bilder (*.png *.jpg *.jpeg *.bmp *.webp);;Videos (*.mp4 *.avi *.mkv *.mov);;Alle Dateien (*.*)",
        )
        if file_path:
            self._load_file(file_path)

    def _load_file(self, file_path: str) -> None:
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
        self.canvas.set_ascii_text(text)
        self.lbl_status.setText(f"Aufloesung: {cols}x{rows} | {fps:.1f} FPS")

    def _on_worker_status(self, msg: str) -> None:
        self.lbl_status.setText(msg)

    def _on_worker_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "EMIT-O-VISION Fehler", err_msg)

    def closeEvent(self, event) -> None:
        self.worker.stop()
        self.worker_thread.quit()
        self.worker_thread.wait(1500)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EMIT-O-VISION")

    window = MainWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
