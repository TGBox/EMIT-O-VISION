"""Unified media frame sources for EMIT-O-VISION.

Provides a common interface for reading frames from:
  - Webcams (cv2.VideoCapture by index)
  - Video files (cv2.VideoCapture by file path, with optional looping)
  - Static images (cv2.imread by file path)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


class BaseSource(ABC):
    """Abstract base class for any visual frame source."""

    def __init__(self, name: str, is_live: bool = False, fps: float = 30.0) -> None:
        self.name = name
        self.is_live = is_live
        self._fps = max(1.0, float(fps)) if fps else 30.0
        self._is_paused = False

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def pause(self) -> None:
        self._is_paused = True

    def resume(self) -> None:
        self._is_paused = False

    def toggle_pause(self) -> bool:
        self._is_paused = not self._is_paused
        return self._is_paused

    @abstractmethod
    def read(self) -> Tuple[bool, np.ndarray | None]:
        """Read the next frame as BGR numpy array. Returns (success, frame)."""

    @abstractmethod
    def release(self) -> None:
        """Release underlying system or file resources."""


class WebcamSource(BaseSource):
    """Captures frames live from a connected camera."""

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__(name=f"Webcam (Kamera {camera_index})", is_live=True, fps=30.0)
        self.camera_index = camera_index
        # Try DirectShow first on Windows (best for virtual/phone cameras), then default backend
        self._cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(camera_index)

        if self._cap.isOpened():
            detected_fps = self._cap.get(cv2.CAP_PROP_FPS)
            if detected_fps and 1.0 <= detected_fps <= 120.0:
                self._fps = float(detected_fps)

    @property
    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> Tuple[bool, np.ndarray | None]:
        if not self.is_opened or self._is_paused:
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class VideoSource(BaseSource):
    """Streams frames from a video file, optionally looping at the end."""

    def __init__(self, path: str | Path, loop: bool = True) -> None:
        self.path = Path(path).resolve()
        self.loop = loop
        self._cap = cv2.VideoCapture(str(self.path))
        fps = 30.0
        if self._cap.isOpened():
            detected_fps = self._cap.get(cv2.CAP_PROP_FPS)
            if detected_fps and 1.0 <= detected_fps <= 120.0:
                fps = float(detected_fps)
        super().__init__(name=f"Video ({self.path.name})", is_live=False, fps=fps)

    @property
    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> Tuple[bool, np.ndarray | None]:
        if not self.is_opened or self._is_paused:
            return False, None

        ok, frame = self._cap.read()
        if not ok and self.loop and self._cap is not None:
            # Rewind to first frame
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        return ok, frame

    def restart(self) -> None:
        if self._cap is not None:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class ImageSource(BaseSource):
    """Provides a static image frame continuously or on demand."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        super().__init__(name=f"Bild ({self.path.name})", is_live=False, fps=10.0)
        self._frame = cv2.imread(str(self.path))

    @property
    def is_opened(self) -> bool:
        return self._frame is not None

    def read(self) -> Tuple[bool, np.ndarray | None]:
        if self._frame is None or self._is_paused:
            return False, None
        # Return a copy to prevent mutation
        return True, self._frame.copy()

    def release(self) -> None:
        self._frame = None


def is_image_file(path: str | Path) -> bool:
    """Check if file has a common image extension."""
    suffix = Path(path).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}


def is_video_file(path: str | Path) -> bool:
    """Check if file has a common video extension."""
    suffix = Path(path).suffix.lower()
    return suffix in {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"}


def open_media_file(path: str | Path, loop_video: bool = True) -> BaseSource | None:
    """Factory creating an ImageSource or VideoSource depending on file type."""
    p = Path(path)
    if not p.is_file():
        return None
    if is_image_file(p):
        src = ImageSource(p)
        return src if src.is_opened else None
    if is_video_file(p):
        src = VideoSource(p, loop=loop_video)
        return src if src.is_opened else None
    return None
