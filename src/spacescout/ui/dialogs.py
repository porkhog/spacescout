"""Dialogs: confirmations, progress, and the Move-to-drive picker."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..drives import DriveInfo, drive_of, list_drives
from ..utils import IS_WINDOWS, format_size
from . import theme
from .widgets import ElidedLabel, UsageBar, button, label


def confirm(parent, title: str, text: str, detail: str = "", ok_text: str = "OK", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setText(f"<b>{text}</b>")
    if detail:
        box.setInformativeText(detail)
    ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    ok.setProperty("kind", "danger" if danger else "primary")
    cancel = box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(cancel if danger else ok)
    box.exec()
    return box.clickedButton() is ok


def info(parent, title: str, text: str, detail: str = "", details_text: str = "", warning: bool = False) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning if warning else QMessageBox.Information)
    box.setText(f"<b>{text}</b>")
    if detail:
        box.setInformativeText(detail)
    if details_text:
        box.setDetailedText(details_text)
    box.addButton("OK", QMessageBox.AcceptRole).setProperty("kind", "primary")
    box.exec()


class OpThread(QThread):
    """Runs fn(progress, cancel) in the background."""

    progress = Signal(int, int, str)
    done = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.cancel_event = threading.Event()
        self.result = None

    def run(self):
        try:
            self.result = self._fn(lambda d, t, text: self.progress.emit(int(d), int(t), str(text)), self.cancel_event)
        except Exception as exc:  # noqa: BLE001
            self.result = exc
        self.done.emit(self.result)


class ProgressDialog(QDialog):
    def __init__(self, parent, title: str, bytes_mode: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._bytes_mode = bytes_mode
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        self.title = label(title, "h2")
        self.status = label("Starting…", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.detail = ElidedLabel("", role="faint")
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button("Stop")
        row.addWidget(self.cancel_btn)
        for w in (self.title, self.status, self.bar, self.detail):
            lay.addWidget(w)
        lay.addLayout(row)
        self._thread: OpThread | None = None

    def run(self, fn):
        """Run fn in a thread while showing this dialog. Returns fn's result."""
        self._thread = OpThread(fn, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.done.connect(lambda _r: self.accept())
        self.cancel_btn.clicked.connect(self._cancel)
        self._thread.start()
        self.exec()
        self._thread.wait()
        res = self._thread.result
        if isinstance(res, Exception):
            raise res
        return res

    def _cancel(self):
        if self._thread:
            self._thread.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.status.setText("Stopping safely…")

    def _on_progress(self, done: int, total: int, text: str):
        if total > 0:
            if self._bytes_mode:
                scale = max(1, total // 1_000_000)
                self.bar.setRange(0, total // scale)
                self.bar.setValue(done // scale)
                self.status.setText(f"{format_size(done)} of {format_size(total)}")
            else:
                self.bar.setRange(0, total)
                self.bar.setValue(done)
                self.status.setText(f"{done} of {total}")
        self.detail.setText(text)

    def reject(self):  # Esc / close button = stop
        self._cancel()


class DriveOption(QWidget):
    def __init__(self, drive: DriveInfo, needed: int):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self.radio = QRadioButton(drive.title)
        self.radio.setEnabled(drive.free > needed)
        lay.addWidget(self.radio, 2)
        col = QVBoxLayout()
        col.setSpacing(3)
        bar = UsageBar(6)
        pal = theme.current()
        frac = drive.used_fraction
        bar.set_fraction(frac, pal["danger"] if frac > 0.9 else pal["warning"] if frac > 0.75 else pal["accent"])
        col.addWidget(bar)
        free = label(f"{format_size(drive.free)} free", "faint" if drive.free > needed else "danger")
        if drive.free <= needed:
            free.setText(f"{format_size(drive.free)} free · not enough space")
        col.addWidget(free)
        lay.addLayout(col, 3)
        self.drive = drive


class MoveDialog(QDialog):
    """Pick where to move the selected items."""

    def __init__(self, parent, paths: list[str], total_size: int, advanced: bool, caution: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Move to another drive")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.paths = paths
        self.total = total_size
        src_drive = os.path.normcase(drive_of(paths[0]))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        what = os.path.basename(paths[0].rstrip("\\/")) if len(paths) == 1 else f"{len(paths)} items"
        lay.addWidget(label(f"Move {what}", "h2"))
        lay.addWidget(label(
            f"{format_size(total_size)} will be copied to the new location, checked, and only then removed "
            f"from here. If anything goes wrong, your originals stay where they are.", "muted", wrap=True))

        if caution:
            warn = label("⚠  " + caution, "warning", wrap=True)
            lay.addWidget(warn)

        lay.addWidget(label("Choose a drive", "h3"))
        self.group = QButtonGroup(self)
        self.options: list[DriveOption] = []
        others = [d for d in list_drives() if os.path.normcase(d.path) != src_drive]
        for d in others:
            opt = DriveOption(d, total_size)
            self.group.addButton(opt.radio)
            opt.radio.toggled.connect(lambda on, drive=d: on and self._pick_drive(drive))
            self.options.append(opt)
            lay.addWidget(opt)
        if not others:
            lay.addWidget(label("No other drives found. Plug in a USB/external drive, or pick a folder below.",
                                "muted", wrap=True))

        lay.addWidget(label("Destination folder", "h3"))
        row = QHBoxLayout()
        self.dest = QLineEdit()
        self.dest.setPlaceholderText("Pick a drive above, or browse…")
        self.dest.textChanged.connect(self._validate)
        browse = button("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.dest, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        self.keep = QCheckBox("Keep the original folder layout (e.g. …\\Users\\You\\Videos)")
        self.keep.setChecked(True)
        self.keep.setToolTip("Makes it easy to find things later: the moved items are placed in the same\n"
                             "folder structure they came from, inside the destination folder.")
        lay.addWidget(self.keep)

        self.link = QCheckBox("Leave a link behind so programs still find the folder (advanced)")
        has_dir = any(os.path.isdir(p) for p in paths)
        self.link.setVisible(advanced and IS_WINDOWS)
        self.link.setEnabled(has_dir)
        self.link.setToolTip("Creates a directory junction at the old location pointing to the new one.\n"
                             "Useful for moving games or app data. Only applies to folders.")
        lay.addWidget(self.link)

        self.error = label("", "danger", wrap=True)
        lay.addWidget(self.error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = button("Move", "primary")
        self.ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)

        for opt in self.options:
            if opt.radio.isEnabled():
                opt.radio.setChecked(True)
                break
        self._validate()

    def _pick_drive(self, drive: DriveInfo):
        src_letter = drive_of(self.paths[0]).rstrip("\\/:").split("/")[-1] or "drive"
        folder = f"Moved from {src_letter}" if IS_WINDOWS else "Moved by SpaceScout"
        self.dest.setText(os.path.join(drive.path, folder))

    def _browse(self):
        start = self.dest.text() or os.path.expanduser("~")
        while start and not os.path.isdir(start):
            parent = os.path.dirname(start)
            if parent == start:
                break
            start = parent
        d = QFileDialog.getExistingDirectory(self, "Choose destination folder", start)
        if d:
            self.dest.setText(os.path.normpath(d))
            self.group.setExclusive(False)
            for opt in self.options:
                opt.radio.setChecked(False)
            self.group.setExclusive(True)

    def _validate(self):
        dest = self.dest.text().strip()
        msg = ""
        if not dest:
            msg = " "
        else:
            nd = os.path.normcase(os.path.abspath(dest))
            for p in self.paths:
                np_ = os.path.normcase(os.path.abspath(p))
                if nd == np_ or nd.startswith(np_ + os.sep):
                    msg = "You can't move a folder into itself."
                    break
            if not msg:
                try:
                    import shutil

                    probe = dest
                    while not os.path.exists(probe):
                        parent = os.path.dirname(probe)
                        if parent == probe:
                            break
                        probe = parent
                    free = shutil.disk_usage(probe).free
                    if free <= self.total:
                        msg = f"Not enough space there ({format_size(free)} free, {format_size(self.total)} needed)."
                except OSError:
                    msg = "That location isn't available."
        self.error.setText(msg.strip())
        self.ok.setEnabled(not msg)

    def values(self):
        return self.dest.text().strip(), self.keep.isChecked(), self.link.isChecked() and self.link.isVisible()


class AboutDialog(QDialog):
    def __init__(self, parent, version: str):
        super().__init__(parent)
        self.setWindowTitle("About SpaceScout")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        from .widgets import app_icon_pixmap

        logo = QLabel()
        logo.setPixmap(app_icon_pixmap(64))
        lay.addWidget(logo)
        lay.addWidget(label("SpaceScout", "h1"))
        lay.addWidget(label(f"Version {version}", "muted"))
        lay.addWidget(label("See what's filling your drives, then clean up or move it.\n"
                            "Free and open source under the MIT License.", wrap=True))
        ok = button("Close", "primary")
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        lay.addSpacing(8)
        lay.addLayout(row)
