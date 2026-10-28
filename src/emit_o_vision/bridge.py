"""Python bridge: captures the webcam and streams grayscale frames to the Forth renderer.

Protocol on the renderer's stdin (see emit_o_vision.fs):
    header: width, height as two unsigned 16-bit little-endian integers
    frames: width * height bytes per frame (gray values 0..255, row-major)
"""

import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import cv2

FORTH_SCRIPT = Path(__file__).with_name("emit_o_vision.fs")

# Typical install locations of the Gforth Windows installer
GFORTH_FALLBACKS = (
    Path(r"C:\Program Files (x86)\gforth\gforth.exe"),
    Path(r"C:\Program Files\gforth\gforth.exe"),
)

# Terminal characters are roughly twice as tall as wide
CHAR_ASPECT = 0.55


def find_gforth(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("gforth")
    if found:
        return found
    for candidate in GFORTH_FALLBACKS:
        if candidate.is_file():
            return str(candidate)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Webcam als ASCII-Grafik im Terminal, gerendert von Forth."
    )
    parser.add_argument("--width", type=int, default=100, help="Breite in Zeichen (Standard: 100)")
    parser.add_argument("--camera", type=int, default=0, help="Kamera-Index (Standard: 0)")
    parser.add_argument("--gforth", help="Pfad zu gforth (Standard: PATH bzw. Installationsordner)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    gforth = find_gforth(args.gforth)
    if gforth is None:
        print("Fehler: gforth nicht gefunden. Bitte installieren oder mit --gforth angeben.")
        return 1

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Fehler: Konnte die Webcam {args.camera} nicht öffnen.")
        return 1

    ok, frame = cap.read()
    if not ok:
        print("Fehler beim Lesen des Kamera-Frames.")
        cap.release()
        return 1

    cam_height, cam_width = frame.shape[:2]
    width = args.width
    height = max(1, int(width * cam_height / cam_width * CHAR_ASPECT))

    # Relative script path + cwd avoids Windows-path issues in the Cygwin-based Gforth
    renderer = subprocess.Popen(
        [gforth, FORTH_SCRIPT.name], stdin=subprocess.PIPE, cwd=FORTH_SCRIPT.parent
    )

    try:
        renderer.stdin.write(struct.pack("<HH", width, height))
        while ok:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            renderer.stdin.write(cv2.resize(gray, (width, height)).tobytes())
            renderer.stdin.flush()
            ok, frame = cap.read()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        cap.release()
        try:
            renderer.stdin.close()
        except OSError:
            pass
        try:
            renderer.wait(timeout=2)
        except subprocess.TimeoutExpired:
            renderer.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())

