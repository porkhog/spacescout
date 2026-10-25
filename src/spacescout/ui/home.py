"""Start page (drive picker) and the scanning progress page."""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from ..drives import DriveInfo, list_drives
from ..utils import IS_WINDOWS, format_count, format_duration, format_size, is_admin
from . import theme
from .widgets import Card, ElidedLabel, UsageBar, button, drive_icon, label


def usage_color(frac: float) -> str:
    pal = theme.current()
    if frac >= 0.9:
        return pal["danger"]
    if frac >= 0.75:
        return pal["warning"]
    return pal["accent"]


class DriveCard(Card):
    scan = Signal(object)

    def __init__(self, drive: DriveInfo):
        super().__init__(hoverable=True, margins=(20, 18, 20, 18), spacing=12)
        self.drive = drive
        top = QHBoxLayout()
        top.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(drive_icon(drive.path).pixmap(QSize(36, 36)))
        top.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(drive.title, "h3"))
        kind = "Removable drive" if drive.removable else (drive.fstype or "Drive")
        col.addWidget(label(f"{kind} · {format_size(drive.total)}", "faint"))
        top.addLayout(col, 1)
        self.lay.addLayout(top)

        bar = UsageBar(10)
        bar.set_fraction(drive.used_fraction, usage_color(drive.used_fraction))
        bar.setToolTip(f"{drive.used_fraction * 100:.0f}% full")
        self.lay.addWidget(bar)

        row = QHBoxLayout()
        free = label(f"{format_size(drive.free)} free", None)
        free.setStyleSheet("font-weight: 600;")
        row.addWidget(free)
        row.addWidget(label(f"of {format_size(drive.total)}", "muted"))
        row.addStretch(1)
        btn = button("Scan", "primary")
        btn.clicked.connect(lambda: self.scan.emit(self.drive))
        row.addWidget(btn)
        self.lay.addLayout(row)
        self.clicked.connect(lambda: self.scan.emit(self.drive))


class HomePage(QWidget):
    scanDrive = Signal(object)
    scanFolder = Signal()
    restartAdmin = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(40, 34, 40, 34)
        self.lay.setSpacing(18)

        self.title = label("Which drive should we look at?", "h1")
        self.subtitle = label("SpaceScout shows you what's using space on your PC and helps you clean it up "
                              "or move it somewhere else.", "muted", wrap=True)
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.subtitle)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 6, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self.lay.addWidget(self.grid_host)

        actions = QHBoxLayout()
        folder_btn = button("Scan a specific folder…")
        folder_btn.clicked.connect(self.scanFolder.emit)
        refresh = button("Refresh drives", "ghost")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(folder_btn)
        actions.addWidget(refresh)
        actions.addStretch(1)
        self.lay.addLayout(actions)

        self.admin_banner = Card(margins=(16, 12, 16, 12))
        ab = QHBoxLayout()
        ab.addWidget(label("Some system folders can only be measured with administrator rights. "
                           "Without them, a few GB may show up as “hidden & protected”.", "muted", wrap=True), 1)
        admin_btn = button("Restart as administrator")
        admin_btn.clicked.connect(self.restartAdmin.emit)
        ab.addWidget(admin_btn)
        self.admin_banner.lay.addLayout(ab)
        self.admin_banner.setVisible(IS_WINDOWS and not is_admin())
        self.lay.addWidget(self.admin_banner)
        self.lay.addStretch(1)
        self._cards: list[DriveCard] = []
        self.refresh()

    def set_advanced(self, advanced: bool):
        if advanced:
            self.title.setText("Drives")
            self.subtitle.setText("Pick a drive or folder to analyse.")
        else:
            self.title.setText("Which drive should we look at?")
            self.subtitle.setText("SpaceScout shows you what's using space on your PC and helps you clean it up "
                                  "or move it somewhere else.")

    def refresh(self):
        for c in self._cards:
            self.grid.removeWidget(c)
            c.hide()
            c.deleteLater()
        self._cards = []
        drives = list_drives()
        cols = 3 if len(drives) > 4 else 2
        for i, d in enumerate(drives):
            card = DriveCard(d)
            card.scan.connect(self.scanDrive.emit)
            self.grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)


class ScanningPage(QWidget):
    cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = Card(margins=(32, 28, 32, 26), spacing=14)
        card.setMinimumWidth(560)
        card.setMaximumWidth(720)
        row.addWidget(card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

        self.title = label("Scanning…", "h2")
        self.hint = label("This usually takes under a minute. You can keep using your PC.", "muted", wrap=True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.files = self._stat(stats, "Files found")
        self.size = self._stat(stats, "Size counted")
        self.elapsed = self._stat(stats, "Time")
        stats.addStretch(1)
        self.current = ElidedLabel("", role="faint")
        btns = QHBoxLayout()
        btns.addStretch(1)
        stop = button("Stop scanning")
        stop.clicked.connect(self.cancel.emit)
        btns.addWidget(stop)
        for w in (self.title, self.hint, self.bar):
            card.lay.addWidget(w)
        card.lay.addLayout(stats)
        card.lay.addWidget(self.current)
        card.lay.addLayout(btns)
        self._expected = 0
        self._start = time.monotonic()

    def _stat(self, layout, caption: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(0)
        value = label("0", "h2")
        col.addWidget(value)
        col.addWidget(label(caption, "faint"))
        layout.addLayout(col)
        return value

    def start(self, title: str, expected_bytes: int):
        self.title.setText(f"Scanning {title}…")
        self._expected = expected_bytes
        self._start = time.monotonic()
        if expected_bytes > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)
        else:
            self.bar.setRange(0, 0)
        self.update_progress(0, 0, "")

    def update_progress(self, files: int, size: int, current: str):
        self.files.setText(format_count(files))
        self.size.setText(format_size(size))
        self.elapsed.setText(format_duration(time.monotonic() - self._start))
        self.current.setText(current)
        if self._expected > 0:
            self.bar.setValue(min(990, int(size / self._expected * 1000)))
