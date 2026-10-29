"""Entrypoint script for PyInstaller standalone executable."""

import sys
from emit_o_vision.gui import main

if __name__ == "__main__":
    sys.exit(main())

