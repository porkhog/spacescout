"""Entry point:  python -m spacescout [folder-or-drive]"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spacescout", description="See what's filling your drives.")
    parser.add_argument("path", nargs="?", help="Drive or folder to scan right away (e.g. C:\\)")
    parser.add_argument("--advanced", action="store_true", help="Start in Advanced mode")
    parser.add_argument("--simple", action="store_true", help="Start in Simple mode")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        try:  # Use our own taskbar icon instead of Python's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SpaceScout.App")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui.main_window import ADVANCED, SIMPLE, MainWindow
    from .ui.widgets import app_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    win = MainWindow()
    if args.advanced or args.simple:
        mode = ADVANCED if args.advanced else SIMPLE
        win.mode_switch.set_index(mode)
        win.set_mode(mode)
    win.show()
    if args.path:
        win.start_scan(os.path.abspath(args.path))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
