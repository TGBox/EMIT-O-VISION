"""CLI runner for EMIT-O-VISION Forth pipeline.

Supports live webcams, video files, and static images.
Can output directly to the terminal or save rendered ASCII frames into a text file.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import cv2

from emit_o_vision.renderer import FORTH_SCRIPT, ForthRenderer, find_gforth
from emit_o_vision.sources import ImageSource, VideoSource, WebcamSource, open_media_file

CHAR_ASPECT = 0.55


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EMIT-O-VISION: Live-Webcam, Video- und Bildverarbeitung gerendert mit Forth."
    )
    parser.add_argument(
        "--input",
        "-i",
        help="Pfad zu einer Bild- oder Videodatei (optional; Standard: Webcam)",
    )
    parser.add_argument(
        "--camera",
        "-c",
        type=int,
        default=0,
        help="Kamera-Index (Standard: 0)",
    )
    parser.add_argument(
        "--width",
        "-w",
        type=int,
        default=100,
        help="Breite in Zeichen (Standard: 100)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Optionale Höhe in Zeichen (Standard: automatisch berechnet)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Pfad zu einer Textdatei zum Speichern des ASCII-Outputs (optional)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Bildrate begrenzen (Standard: Original-FPS der Quelle)",
    )
    parser.add_argument(
        "--gforth",
        help="Pfad zum Gforth-Executable (Standard: automatische Suche)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    gforth = find_gforth(args.gforth)
    if not gforth:
        print("Fehler: Gforth wurde nicht gefunden. Bitte installieren oder mit --gforth angeben.")
        return 1

    # Determine frame source
    if args.input:
        source_path = Path(args.input)
        if not source_path.is_file():
            print(f"Fehler: Datei nicht gefunden: {source_path}")
            return 1
        source = open_media_file(source_path, loop_video=False if args.output else True)
        if not source:
            print(f"Fehler: Nicht unterstütztes Format oder Datei konnte nicht geöffnet werden: {source_path}")
            return 1
    else:
        source = WebcamSource(camera_index=args.camera)
        if not source.is_opened:
            print(f"Fehler: Konnte Webcam mit Index {args.camera} nicht öffnen.")
            return 1

    target_fps = args.fps if args.fps is not None else source.fps
    frame_delay = 1.0 / max(1.0, target_fps) if target_fps > 0 else 0.0

    print(f"Quelle: {source.name} | Gforth: {gforth}")
    print(f"ASCII-Auflösung: {args.width} Spalten | FPS: {target_fps:.1f}")

    # Mode 1: Write clean ASCII to output text file
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Schreibe ASCII-Ausgabe in Datei: {out_path}")

        renderer = ForthRenderer(gforth_path=gforth)
        frame_count = 0
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                while True:
                    ok, frame = source.read()
                    if not ok or frame is None:
                        break

                    h, w = frame.shape[:2]
                    calc_h = args.height or max(1, int(args.width * (h / w) * CHAR_ASPECT))
                    renderer.send_frame(frame, width=args.width, height=calc_h)
                    rendered = renderer.get_latest_frame(timeout=2.0)
                    if rendered:
                        if frame_count > 0:
                            f.write("\n\x0c\n")  # Page break between frames
                        f.write(rendered)
                        frame_count += 1

                    if isinstance(source, ImageSource):
                        break
        finally:
            renderer.close()
            source.release()

        print(f"Fertig: {frame_count} Frame(s) in {out_path} gespeichert.")
        return 0

    # Mode 2: Real-time rendering directly to Terminal (stdout)
    # Using ForthRenderer to safely stream
    import subprocess
    import struct

    renderer_proc = subprocess.Popen(
        [gforth, FORTH_SCRIPT.name],
        stdin=subprocess.PIPE,
        cwd=FORTH_SCRIPT.parent,
    )

    try:
        while True:
            t0 = time.perf_counter()
            ok, frame = source.read()
            if not ok or frame is None:
                if isinstance(source, ImageSource):
                    # Keep image displayed until user interrupts
                    time.sleep(0.1)
                    continue
                break

            h, w = frame.shape[:2]
            calc_h = args.height or max(1, int(args.width * (h / w) * CHAR_ASPECT))

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, (args.width, calc_h), interpolation=cv2.INTER_AREA)

            header = struct.pack("<HH", args.width, calc_h)
            renderer_proc.stdin.write(header + resized.tobytes())
            renderer_proc.stdin.flush()

            if isinstance(source, ImageSource):
                # Static image: render once and wait
                time.sleep(0.2)
                continue

            dt = time.perf_counter() - t0
            sleep_time = frame_delay - dt
            if sleep_time > 0:
                time.sleep(sleep_time)

    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        source.release()
        if renderer_proc.stdin:
            try:
                renderer_proc.stdin.close()
            except OSError:
                pass
        try:
            renderer_proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            renderer_proc.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
