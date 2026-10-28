import cv2
import sys

# ASCII-Zeichen von dunkel nach hell
ASCII_CHARS = " .:-=+*#%@"

def pixel_to_ascii(pixel_intensity):
    index = int(pixel_intensity / 255 * (len(ASCII_CHARS) - 1))
    return ASCII_CHARS[index]

def main():
    # Webcam öffnen (Standard-Kamera = 0)
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Fehler: Konnte die Webcam nicht öffnen.")
        return

    # Terminal-Größe für das ASCII-Bild festlegen
    terminal_width = 100

    print("\033[2J\033[H") # Terminal einmal komplett leeren
    print("Webcam-Stream gestartet! Drücke Strg+C zum Beenden.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Fehler beim Lesen des Kamera-Frames.")
                break

            # Seitenverhältnis der Kamera beibehalten (Faktor 0.55 gleicht die Texthöhe im Terminal aus)
            height, width, _ = frame.shape
            aspect_ratio = height / width
            terminal_height = int(terminal_width * aspect_ratio * 0.55)

            # Bild auf Terminal-Dimensionen verkleinern
            resized_gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (terminal_width, terminal_height))
            resized_color = cv2.resize(frame, (terminal_width, terminal_height))

            output_lines = []
            for y in range(terminal_height):
                line = ""
                for x in range(terminal_width):
                    # ASCII-Zeichen basierend auf Grauwert bestimmen
                    g_val = resized_gray[y, x]
                    char = pixel_to_ascii(g_val)
                    
                    # Original-Farbwerte (BGR in RGB umwandeln)
                    b, g, r = resized_color[y, x]
                    
                    # ANSI-TrueColor-Escape-Sequenz für die exakte Pixel-Farbe
                    color_code = f"\033[38;2;{r};{g};{b}m"
                    line += f"{color_code}{char}"
                
                output_lines.append(line)

            # Cursor nach oben links setzen (\033[H) und den Frame flackersfrei drüberschreiben
            sys.stdout.write("\033[H" + "\n".join(output_lines))
            sys.stdout.flush()

    except KeyboardInterrupt:
        print("\nStream beendet.")
    finally:
        cap.release()

if __name__ == "__main__":
    main()