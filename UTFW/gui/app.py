"""
UTFW GUI Application Entry Point
=================================
Entry point for launching the UTFW GUI application.

This module initializes the Qt application and main window.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main():
    """Main entry point for the GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("UTFW Test Runner")
    app.setOrganizationName("UTFW")

    # Import main window here to keep GUI dependencies isolated
    from .main_window import MainWindow

    # Try to find default test root
    default_test_root = None
    cwd = Path.cwd()

    # Look for tests/ directory
    if (cwd / "tests").exists():
        default_test_root = cwd / "tests"
    elif (cwd / "SW_Universal-Test-Framework" / "tests").exists():
        default_test_root = cwd / "SW_Universal-Test-Framework" / "tests"
    elif cwd.name == "SW_Universal-Test-Framework" and (cwd / "tests").exists():
        default_test_root = cwd / "tests"

    # Create and show main window
    window = MainWindow(default_test_root)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
