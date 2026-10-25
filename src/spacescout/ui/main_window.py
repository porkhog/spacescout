"""Main window: header with mode switch, page stack, scan orchestration."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..drives import DriveInfo, usage_for
from ..scanner import Scanner, analyze, is_drive_root
from ..utils import IS_WINDOWS, is_admin, restart_as_admin
from . import theme
from .advanced_view import AdvancedView
from .controller import Actions, ScanResult
from .dialogs import AboutDialog, info
from .home import HomePage, ScanningPage
from .simple_view import SimpleView
from .widgets import SegmentedControl, app_icon_pixmap, button, label

SIMPLE, ADVANCED = 0, 1


class ScanThread(QThread):
    done = Signal(object, object)  # root, analysis  (None, None if cancelled)

    def __init__(self, scanner: Scanner, parent=None):
        super().__init__(parent)
        self.scanner = scanner

    def run(self):
        root = self.scanner.run()
        if self.scanner.cancelled:
            self.done.emit(None, None)
            return
        self.done.emit(root, analyze(root))


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text: str, ms: int = 4500):
        p = theme.current()
        self.setStyleSheet(
            f"background: {p['text']}; color: {p['bg']}; border-radius: 10px; padding: 10px 18px; font-weight: 600;"
        )
        self.setText(text)
        self.setMaximumWidth(560)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def reposition(self):
        par = self.parentWidget()
        if par is None:
            return
        self.adjustSize()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        theme.set_theme(str(self.settings.value("theme", "dark")))
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 880)
        self.setMinimumSize(980, 640)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

        self.result: ScanResult | None = None
        self._scanner: Scanner | None = None
        self._scan_thread: ScanThread | None = None
        self._scan_target: tuple[str, DriveInfo | None] | None = None
        self.actions = Actions(self)

        central = QWidget()
        central.setObjectName("page")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.home = HomePage()
        self.home.scanDrive.connect(lambda d: self.start_scan(d.path, d))
        self.home.scanFolder.connect(self.pick_folder)
        self.home.restartAdmin.connect(self.restart_admin)
        self.scanning = ScanningPage()
        self.scanning.cancel.connect(self.cancel_scan)
        self.simple = SimpleView(self.actions)
        self.advanced = AdvancedView(self.actions)
        for v in (self.simple, self.advanced):
            v.back.connect(self.go_home)
            v.rescan.connect(self.rescan)
        for page in (self.home, self.scanning, self.simple, self.advanced):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.toast_label = Toast(central)
        self._poll = QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._poll_scan)

        try:
            mode = ADVANCED if int(self.settings.value("mode", SIMPLE)) == ADVANCED else SIMPLE
        except (TypeError, ValueError):
            mode = SIMPLE
        self.mode_switch.set_index(mode)
        self._apply_mode(mode)
        self.apply_theme()

    # ---- header ------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon_pixmap(64).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(logo)
        name = label(APP_NAME, "h3")
        name.setStyleSheet("font-size: 12.5pt; font-weight: 700;")
        lay.addWidget(name)
        if IS_WINDOWS and is_admin():
            lay.addWidget(label("Administrator", "pill"))
        lay.addStretch(1)
        self.mode_switch = SegmentedControl(["Simple", "Advanced"])
        self.mode_switch.setToolTip("Simple: friendly overview with safe cleanup\n"
                                    "Advanced: full tree, treemap, file types, permanent delete")
        self.mode_switch.changed.connect(self.set_mode)
        lay.addWidget(self.mode_switch)
        lay.addSpacing(6)
        self.theme_btn = button("", "ghost", "Switch light / dark theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        lay.addWidget(self.theme_btn)
        menu_btn = button("•••", "ghost", "More")
        menu = QMenu(menu_btn)
        menu.addAction("Scan a folder…", self.pick_folder)
        if IS_WINDOWS and not is_admin():
            menu.addAction("Restart as administrator", self.restart_admin)
        menu.addSeparator()
        menu.addAction(f"About {APP_NAME}", lambda: AboutDialog(self, __version__).exec())
        menu.addAction("Quit", self.close)
        menu_btn.setMenu(menu)
        menu_btn.setStyleSheet("QPushButton::menu-indicator { width: 0; image: none; }")
        lay.addWidget(menu_btn)
        return header

    # ---- modes & theme -----------------------------------------------------
    def is_advanced(self) -> bool:
        return self.mode_switch.index() == ADVANCED

    def set_mode(self, mode: int):
        self.settings.setValue("mode", mode)
        self._apply_mode(mode)

    def _apply_mode(self, mode: int):
        self.home.set_advanced(mode == ADVANCED)
        current = self.stack.currentWidget()
        if current in (self.simple, self.advanced) and self.result is not None:
            self.show_results()

    def apply_theme(self):
        QApplication.instance().setStyleSheet(theme.stylesheet())
        dark = theme.current()["name"] == "dark"
        self.theme_btn.setText("☀  Light" if dark else "☾  Dark")
        self.home.refresh()
        if self.result is not None:
            self.simple.refresh() if self.simple.result is self.result else None
            self.advanced.treemap.invalidate()

    def toggle_theme(self):
        name = "light" if theme.current()["name"] == "dark" else "dark"
        theme.set_theme(name)
        self.settings.setValue("theme", name)
        self.apply_theme()

    def toast(self, text: str):
        self.toast_label.show_text(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast_label.isVisible():
            self.toast_label.reposition()

    # ---- navigation ----------------------------------------------------------
    def go_home(self):
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def show_results(self):
        view = self.advanced if self.is_advanced() else self.simple
        if view.result is not self.result:
            view.set_result(self.result)
        else:
            view.refresh()
        self.stack.setCurrentWidget(view)

    def pick_folder(self):
        start = os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Choose a folder to scan", start)
        if path:
            self.start_scan(os.path.normpath(path))

    def restart_admin(self):
        if restart_as_admin():
            self.close()
        else:
            info(self, "Couldn't restart", "Windows didn't start SpaceScout as administrator.", warning=True)

    # ---- scanning ------------------------------------------------------------
    def start_scan(self, path: str, drive: DriveInfo | None = None):
        if self._scan_thread is not None:
            return
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            info(self, "Folder not found", f"{path} doesn't exist or isn't available.", warning=True)
            return
        if drive is None:
            drive = usage_for(path)
        self._scan_target = (path, drive)
        self._scanner = Scanner(path)
        self._scan_thread = ScanThread(self._scanner, self)
        self._scan_thread.done.connect(self._scan_done)
        title = drive.title if (drive and is_drive_root(path)) else (os.path.basename(path.rstrip("\\/")) or path)
        expected = drive.used if (drive and is_drive_root(path)) else 0
        self.scanning.start(title, expected)
        self.stack.setCurrentWidget(self.scanning)
        self._scan_thread.start()
        self._poll.start()

    def rescan(self):
        if self.result is not None:
            self.start_scan(self.result.root.name, self.result.drive if self.result.is_drive else None)

    def cancel_scan(self):
        if self._scanner is not None:
            self._scanner.cancel()

    def _poll_scan(self):
        s = self._scanner
        if s is not None:
            self.scanning.update_progress(s.files, s.bytes, s.current)

    def _scan_done(self, root, analysis):
        self._poll.stop()
        scanner = self._scanner
        thread = self._scan_thread
        self._scanner = None
        self._scan_thread = None
        if thread is not None:
            thread.wait()
        if root is None:
            if self.result is not None:
                self.show_results()
            else:
                self.go_home()
            return
        path, drive = self._scan_target
        if drive is not None:
            drive = usage_for(path) or drive
        self.result = ScanResult(root, analysis, drive, scanner.elapsed, scanner.errors)
        self.show_results()

    def closeEvent(self, e):
        self.cancel_scan()
        if self._scan_thread is not None:
            self._scan_thread.wait(3000)
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)
