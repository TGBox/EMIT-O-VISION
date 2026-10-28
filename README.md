# EMIT-O-VISION

**EMIT-O-VISION** gibt einen Live-Webcam-Feed als ASCII-Grafik direkt im Terminal wieder. Ein Python-Zwischenskript liest die Kamerabilder aus und reicht sie als Graustufen-Bytes an ein **Forth**-Programm weiter. Das Forth-Programm wandelt jeden Pixel in ein Zeichen um und gibt es mit `EMIT` aus.

> [!NOTE]
> **Projektstatus:** Frühe Entwicklungsphase. Die Forth-Pipeline (`emit-o-vision-forth`) funktioniert. Daneben gibt es den ursprünglichen Python-Prototyp (`emit-o-vision`), der das Bild komplett in Python und farbig ausgibt.

---

## Architektur

```mermaid
flowchart LR
    A["Webcam"] -->|Rohbild| B["bridge.py (OpenCV)"]
    B -->|"Graustufen-Bytes über stdin"| C["emit_o_vision.fs (Gforth)"]
    C -->|"Zeichenausgabe per EMIT"| D["Terminal"]
```

1. **Erfassung ([`bridge.py`](src/emit_o_vision/bridge.py)):** Liest die Kamerabilder mit OpenCV, rechnet sie auf Terminalgröße herunter, wandelt sie in Graustufen (0–255) um und schreibt sie in die Standardeingabe des Forth-Prozesses. Gforth startet das Skript selbst als Unterprozess.
2. **Darstellung ([`emit_o_vision.fs`](src/emit_o_vision/emit_o_vision.fs)):** Liest die Bilder Byte für Byte ein, ordnet jedem Grauwert ein Zeichen der Helligkeitsskala `.:-=+*#%@` zu und gibt es per `EMIT` aus. Vor jedem Bild setzt es den Cursor mit ANSI-Codes zurück an den Anfang.

### Datenformat

| Abschnitt | Inhalt |
| --- | --- |
| Header (einmalig, 4 Bytes) | Breite und Höhe als vorzeichenlose 16-Bit-Zahlen, Little Endian |
| Frames (fortlaufend) | `Breite × Höhe` Bytes pro Bild, ein Grauwert pro Pixel, zeilenweise |

Wenn der Datenstrom endet, blendet das Forth-Programm den Cursor wieder ein und beendet sich.

> [!NOTE]
> Python startet Gforth direkt als Unterprozess, statt eine Shell-Pipe (`python … | gforth …`) zu verwenden. Windows PowerShell 5 behandelt Pipes zwischen Programmen als Text und würde die Binärdaten verfälschen.

---

## Voraussetzungen

- **Python 3.14** oder neuer (laut `pyproject.toml` bzw. `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** für Umgebung und Abhängigkeiten
- **opencv-python** (wird über `uv` automatisch installiert)
- **[Gforth](https://gforth.org/)**: Getestet mit Gforth 0.7.0 unter Windows. Downloads und Installationsanleitungen gibt es auf der Gforth-Website, unter Debian/Ubuntu geht auch `sudo apt install gforth`, unter macOS `brew install gforth`. Linux und macOS wurden bisher nicht getestet.
- **Ein Terminal mit ANSI-Unterstützung**, z. B. Windows Terminal, und eine Schrift mit fester Zeichenbreite. Für den farbigen Python-Prototyp braucht das Terminal zusätzlich TrueColor-Unterstützung.

Das Skript sucht `gforth` zuerst im `PATH` und danach in den Standard-Installationsordnern unter Windows (`C:\Program Files (x86)\gforth\` und `C:\Program Files\gforth\`). Liegt Gforth woanders, gib den Pfad mit `--gforth` an.

---

## Installation

```bash
git clone <REPOSITORY-URL>
cd EMIT-O-VISION
uv sync
```

---

## Verwendung

### Forth-Pipeline

```bash
uv run emit-o-vision-forth
```

Optionen:

| Option | Bedeutung | Standard |
| --- | --- | --- |
| `--width` | Breite des Bildes in Zeichen | `100` |
| `--camera` | Kamera-Index | `0` |
| `--gforth` | Pfad zu `gforth` | automatische Suche |

Beispiel:

```bash
uv run emit-o-vision-forth --width 140 --camera 1
```

### Python-Prototyp (farbig, ohne Forth)

```bash
uv run emit-o-vision
```

Hier stellst du Breite (`terminal_width`) und Kamera-Index noch direkt im Quellcode ein.

Beide Varianten beendest du mit `Strg + C`.

---

## Projektstruktur

```text
EMIT-O-VISION/
├── src/
│   └── emit_o_vision/
│       ├── __init__.py        # Paketdatei
│       ├── bridge.py          # Python-Zwischenskript: Webcam → Graustufen-Bytes → Gforth
│       ├── emit_o_vision.fs   # Forth-Renderer: Graustufen-Bytes → ASCII per EMIT
│       └── webcam_ascii.py    # Python-Prototyp: Webcam → farbige ASCII-Ausgabe
├── .gitignore
├── .python-version            # Python-Version für uv
├── pyproject.toml             # Projekt-Metadaten, Abhängigkeiten und Startbefehle
├── uv.lock                    # Festgeschriebene Abhängigkeitsversionen
└── README.md
```

---

## Helligkeitsskala anpassen

Die Zeichen für die Helligkeitsstufen stehen in [`emit_o_vision.fs`](src/emit_o_vision/emit_o_vision.fs). Die Skala darf beliebig lang sein, weil sich die Zuordnung nach ihrer Länge richtet:

```forth
\ Brightness ramp from dark to bright (first character is a space)
: charset ( -- c-addr u )  s"  .:-=+*#%@" ;

\ Maps a gray value 0..255 onto a character of the brightness ramp
: lum>char ( u8 -- char )  charset rot * 256 / + c@ ;
```

Auf einem hellen Terminal-Hintergrund drehst du die Reihenfolge der Zeichen einfach um.

---

## Tipps für eine gute Darstellung

- **Kleinere Schrift:** Je kleiner die Schrift im Terminal, desto größer kann `--width` sein und desto feiner wird das Bild.
- **Seitenverhältnis:** Terminalzeichen sind etwa doppelt so hoch wie breit. Beide Varianten gleichen das aus, indem sie die Höhe mit dem Faktor `0.55` multiplizieren.
- **Fenstergröße:** Ist das Terminal kleiner als das Bild, bricht die Ausgabe um und das Bild verrutscht. Dann das Fenster vergrößern oder `--width` verkleinern.

---

## Lizenz

Noch keine Lizenz festgelegt.
