# EMIT-O-VISION Studio

## Problem Statement

Wie machen wir aus EMIT-O-VISION eine Vollbild-Bühne, auf der Webcam, Bilder und Videos per Klick durch den **Forth-Renderer** laufen – ohne dass Forth zur Deko wird?

## Recommended Direction

**Forth bleibt der Renderer, die GUI ist Bühne und Steuerung.** Eine PySide6-App startet im Vollbild (F11 / Button ⇄ Fenstermodus, `Esc` verlässt Vollbild). Sie besteht aus einer schmalen Kopfleiste und einer schwarzen Monospace-Fläche, die den Rest des Bildschirms füllt.

Python liefert Graustufen-Frames (Webcam, Video oder Bild) an `gforth`, liest dessen Ausgabe zurück, trennt die Frames am ANSI-Code `ESC[H` und zeigt jeweils den neuesten an. Spalten und Zeilen ergeben sich aus Flächen- und Schriftgröße, sodass das Bild immer exakt passt; der Schriftgrößen-Regler wird damit zum Auflösungsregler.

Damit sich Größe und Schrift im laufenden Betrieb ändern können, bekommt **jeder Frame** einen eigenen Header (Breite, Höhe). Der Forth-Code bleibt sonst gleich und funktioniert weiter auch direkt im Terminal.

## Key Assumptions to Validate

- [x] PySide6 hat Wheels für Python 3.14 → Erfolgreich installiert (PySide6 6.12.0)
- [ ] Qt zeigt ~40.000 Zeichen pro Frame mit ~30 fps flüssig an
- [x] Gforth-Ausgabe kommt pro Frame zuverlässig über die Pipe (dank `flush-file`)
- [ ] Rückstau: Ist die GUI langsamer als Forth, darf sich keine Verzögerung aufbauen → nur den jeweils neuesten Frame anzeigen, ältere verwerfen

## MVP Scope

**Kopfleiste (von links nach rechts):**
`Webcam an/aus` · `Datei öffnen…` · `⏯ Pause` · `Tempo: Original/Max` · `A− A+` · `Momentaufnahme speichern` · `Vollbild/Fenster` · `Beenden` · Statusanzeige (Quelle, Auflösung in Zeichen, fps)

**Funktionen:**

- Webcam-Feed ein-/ausschalten
- Bild oder Video per Dateidialog **oder Drag & Drop** laden
- Videos: Pause/Wiedergabe, umschaltbar zwischen Originalgeschwindigkeit und „so schnell wie möglich“
- Momentaufnahme des aktuellen ASCII-Bildes als `.txt` (ohne ANSI-Codes)
- Auflösung automatisch aus Fenster- und Schriftgröße
- Start im Vollbild, Fenstermodus umschaltbar
- Alle sichtbaren Texte auf Deutsch

**CLI (weiterhin ohne GUI nutzbar):**

- `emit-o-vision-forth --input datei` für Bild/Video statt Webcam
- `--output datei.txt` schreibt die ASCII-Frames als Klartext (Frames durch Seitenvorschub getrennt)

## Not Doing (and Why)

- **Farbe im Forth-Pfad** – Forth bekommt nur Graustufen; Farbe würde das Protokoll verdreifachen. Der farbige Python-Prototyp bleibt als eigener Befehl erhalten.
- **Echtes eingebettetes Terminal** – unter Windows fragil; ein Monospace-Textfeld sieht gleich aus und ist kontrollierbar.
- **Zeitleiste / Spulen in Videos** – Pause reicht für die erste Version.
- **Ton** – nicht Teil der ASCII-Idee.
- **Export ganzer Videos aus der GUI** – nur Momentaufnahmen; ganze Videos gehen über die CLI mit `--output`.
- **Kameraauswahl in der GUI** – Kamera-Index per Startoption `--camera`; ein Auswahlmenü erst, wenn es gebraucht wird.
- **Gespeicherte Einstellungen** – Schriftgröße etc. starten jedes Mal mit Standardwerten.
