# EMIT-O-VISION

**EMIT-O-VISION** gibt einen Live-Webcam-Feed als ASCII-Grafik direkt im Terminal wieder. Ein Python-Zwischenskript liest die Kamerabilder aus. Die Umwandlung in Zeichen und die Ausgabe per `EMIT` soll künftig ein **Forth**-Programm übernehmen.

> [!NOTE]
> **Projektstatus:** Frühe Entwicklungsphase. Bisher gibt es nur einen Python-Prototyp ([`webcam_ascii.py`](src/emit_o_vision/webcam_ascii.py)), der Erfassung *und* farbige ASCII-Ausgabe selbst erledigt. Den Forth-Teil und die Datenübergabe zwischen Python und Forth gibt es noch nicht.

---

## Geplante Architektur

Klassische Forth-Systeme haben keinen direkten Zugriff auf Webcams. Deshalb ist eine zweistufige Pipeline geplant:

```mermaid
flowchart LR
    A["Webcam"] -->|Rohbild| B["Python-Bridge (OpenCV)"]
    B -->|"Graustufen-Bytes (geplant: stdout-Pipe)"| C["Forth-Programm"]
    C -->|"Zeichenausgabe per EMIT"| D["Terminal"]
```

1. **Erfassung (Python):** Liest die Kamerabilder mit OpenCV aus, verkleinert sie auf Terminalgröße, wandelt sie in Graustufen (0–255) um und reicht die Helligkeitswerte weiter.
2. **Darstellung (Forth):** Liest die Helligkeitswerte ein, ordnet jedem Wert ein Zeichen aus einer Helligkeitsskala zu (z. B. `.:-=+*#%@`) und gibt es mit `EMIT` aus.

Wie die Daten übergeben werden (Pipe, Datei oder Socket) und in welchem Format, steht noch nicht fest.

---

## Voraussetzungen

- **Python 3.14** oder neuer (laut `pyproject.toml` bzw. `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** für Umgebung und Abhängigkeiten
- **opencv-python** (wird über `uv` automatisch installiert)
- **Ein Terminal mit ANSI- und TrueColor-Unterstützung**, z. B. Windows Terminal, und eine Schrift mit fester Zeichenbreite
- **Für den geplanten Forth-Teil:** [Gforth](https://gforth.org/) oder ein anderes Forth nach ANS-/Forth-2012-Standard. Installationsanleitungen und Downloads (auch für Windows) gibt es auf der Gforth-Website. Unter Debian/Ubuntu geht es auch mit `sudo apt install gforth`, unter macOS mit `brew install gforth`.

---

## Installation

```bash
git clone <REPOSITORY-URL>
cd EMIT-O-VISION
uv sync
```

---

## Verwendung (aktueller Python-Prototyp)

```bash
uv run python -m emit_o_vision.webcam_ascii
```

Der Prototyp öffnet die Standardkamera (Index `0`), rechnet jedes Bild auf 100 Zeichen Breite herunter und gibt es farbig als ASCII-Grafik aus. Mit `Strg + C` beendest du die Wiedergabe.

Einstellungen wie die Breite (`terminal_width`) und den Kamera-Index stellst du derzeit direkt im Quellcode ein. Kommandozeilenargumente gibt es noch nicht.

> [!WARNING]
> Der in `pyproject.toml` eingetragene Befehl `emit-o-vision` zeigt derzeit auf `emit_o_vision:main` in `__init__.py`. Dieser gibt nur einen Platzhaltertext aus und startet den Webcam-Stream **nicht**.

---

## Projektstruktur

```text
EMIT-O-VISION/
├── src/
│   └── emit_o_vision/
│       ├── __init__.py       # Paket-Einstiegspunkt (derzeit Platzhalter)
│       └── webcam_ascii.py   # Python-Prototyp: Webcam → farbige ASCII-Ausgabe
├── .gitignore
├── .python-version           # Python-Version für uv
├── pyproject.toml            # Projekt-Metadaten und Abhängigkeiten
├── uv.lock                   # Festgeschriebene Abhängigkeitsversionen
└── README.md
```

---

## Skizze: Helligkeit → Zeichen in Forth

Eine **ungetestete** Skizze, wie die Zuordnung in Standard-Forth aussehen könnte. Sie nutzt nur Wörter aus dem Core-Wortschatz (`S"`, `C@`, `EMIT`):

```forth
\ Helligkeitsskala von dunkel nach hell (10 Zeichen, beginnt mit Leerzeichen)
: CHARSET ( -- c-addr u )  S"  .:-=+*#%@" ;

\ Bildet einen Grauwert 0..255 auf einen Index 0..9 ab
: LUMINANCE>ASCII ( u8 -- char )
  10 * 256 /  CHARSET DROP + C@ ;

: RENDER-PIXEL ( u8 -- )  LUMINANCE>ASCII EMIT ;
```

---

## Tipps für eine gute Darstellung

- **Kleinere Schrift:** Je kleiner die Schrift im Terminal, desto mehr Zeichen passen hinein und desto feiner wird das Bild.
- **Seitenverhältnis:** Terminalzeichen sind etwa doppelt so hoch wie breit. Der Prototyp gleicht das aus, indem er die Höhe mit dem Faktor `0.55` multipliziert.
- **Flackern vermeiden:** Der Prototyp setzt vor jedem Bild den Cursor mit `\033[H` zurück nach oben links und überschreibt das alte Bild, statt das Terminal zu leeren.

---

## Lizenz

Noch keine Lizenz festgelegt.
