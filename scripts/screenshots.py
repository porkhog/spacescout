"""Render screenshots of SpaceScout (used for the README).

    python scripts/make_demo_tree.py demo
    python scripts/screenshots.py demo docs            # plain folder scan
    python scripts/screenshots.py demo docs --as-drive # dress the demo up as a Windows C: drive
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

GB = 1024**3


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def dress_as_windows(target: str) -> None:
    """Make a Linux demo run look like a Windows PC (screenshots only)."""
    from spacescout import drives, fileops, safety, scanner
    from spacescout.ui import dialogs, home

    drives.IS_WINDOWS = True
    demo = [
        drives.DriveInfo("C:\\", "Windows", "NTFS", 476 * GB, 433 * GB, 43 * GB),
        drives.DriveInfo("D:\\", "Games", "NTFS", 1863 * GB, 1210 * GB, 653 * GB),
        drives.DriveInfo("E:\\", "Backup", "exFAT", 931 * GB, 402 * GB, 529 * GB, removable=True),
    ]
    home.list_drives = lambda: demo
    dialogs.list_drives = lambda: demo
    orig_classify = safety.classify
    env = {"SystemRoot": r"C:\Windows", "USERPROFILE": r"C:\Users\Alex"}
    safety.classify = lambda path, **kw: orig_classify(path.replace("/", "\\"), windows=True, env=env)
    orig_root = scanner.is_drive_root
    scanner.is_drive_root = lambda p: p == "C:\\" or orig_root(p)
    fileops.recycle_bin_info = lambda: (int(1.8 * GB), 37)
    fileops.downloads_folder = lambda: "C:\\/Users/Alex/Downloads"
    fileops.temp_folders = lambda: [os.path.join(target, "Users", "Alex", "AppData", "Local", "Temp")]


def as_drive(win) -> None:
    from spacescout import drives
    from spacescout.scanner import analyze
    from spacescout.ui import controller

    r = win.result
    r.root.name = "C:\\"
    used = r.root.size + int(19.5 * GB)
    r.drive = drives.DriveInfo("C:\\", "Windows", "NTFS", 476 * GB, used, 476 * GB - used)
    r.is_drive = True
    controller.is_drive_root = lambda p: True
    r.analysis = analyze(r.root)
    win.simple.result = None
    win.advanced.result = None
    win.show_results()


def main(target: str, out_dir: str, fake_drive: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.abspath(target)
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    if fake_drive:
        dress_as_windows(target)
    from spacescout.ui import theme
    from spacescout.ui.main_window import ADVANCED, SIMPLE, MainWindow

    win = MainWindow()
    win.settings.clear()
    win.resize(1360, 900)
    win.show()

    def shot(name):
        wait(500)
        win.grab().save(os.path.join(out_dir, name))
        print("saved", name)

    for theme_name in ("dark", "light"):
        theme.set_theme(theme_name)
        win.apply_theme()
        win.mode_switch.set_index(SIMPLE)
        win.set_mode(SIMPLE)
        win.go_home()
        shot(f"home-{theme_name}.png")
        win.start_scan(target)
        while win._scan_thread is not None:
            wait(100)
        if fake_drive:
            as_drive(win)
        win.simple.scroll.verticalScrollBar().setValue(0)
        shot(f"simple-{theme_name}.png")
        win.simple.scroll.verticalScrollBar().setValue(10_000)
        shot(f"simple-bottom-{theme_name}.png")
        win.mode_switch.set_index(ADVANCED)
        win.set_mode(ADVANCED)
        shot(f"advanced-{theme_name}.png")
    win.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1] if len(args) > 1 else "docs", "--as-drive" in sys.argv)
