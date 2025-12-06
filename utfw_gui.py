#!/usr/bin/env python3
"""
UTFW GUI Launcher
=================
Launcher script for the UTFW graphical user interface.

Usage:
    python utfw_gui.py

This provides a graphical interface for discovering, viewing, and running
UTFW tests. It is completely optional and does not affect CLI usage.
"""

import sys

if __name__ == "__main__":
    try:
        from UTFW.gui.app import main
        sys.exit(main())
    except ImportError as e:
        print("ERROR: Failed to import GUI modules.")
        print(f"Details: {e}")
        print()
        print("The GUI requires PySide6. Install it with:")
        print("    pip install PySide6")
        sys.exit(1)
