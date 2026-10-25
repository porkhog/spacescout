"""Reusable widgets: cards, usage bars, segmented control, breadcrumbs, icons."""

from __future__ import annotations

import os

from PySide6.QtCore import QFileInfo, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAbstractFileIconProvider,
    QBrush,
    QColor,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def button(text: str, kind: str | None = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class Card(QFrame):
    clicked = Signal()

    def __init__(self, parent=None, hoverable: bool = False, margins=(18, 16, 18, 16), spacing=10):
        super().__init__(parent)
        self.setObjectName("card")
        if hoverable:
            self.setProperty("hoverable", True)
            self.setCursor(Qt.PointingHandCursor)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(spacing)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("divider")


class ElidedLabel(QLabel):
    """A label that elides long text (paths) instead of growing."""

    def __init__(self, text: str = "", mode=Qt.ElideMiddle, role: str | None = None):
        super().__init__()
        self._full = text
        self._mode = mode
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._update()

    def text_full(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update()

    def _update(self):
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, self._mode, max(10, self.width())))


class UsageBar(QWidget):
    """A rounded horizontal bar made of coloured segments.

    segments: list of (fraction 0..1, colour, tooltip). A colour of None draws a
    hatched "hidden" segment.
    """

    def __init__(self, height: int = 12, parent=None):
        super().__init__(parent)
        self._segments: list[tuple[float, str | None, str]] = []
        self._h = height
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def set_segments(self, segments):
        self._segments = [s for s in segments if s[0] > 0]
        self.update()

    def set_fraction(self, frac: float, color: str):
        self.set_segments([(max(0.0, min(1.0, frac)), color, "")])

    def sizeHint(self):
        return QSize(200, self._h)

    def _rects(self):
        w = self.width()
        x = 0.0
        out = []
        for frac, color, tip in self._segments:
            sw = frac * w
            out.append((QRectF(x, 0, sw, self._h), color, tip))
            x += sw
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        r = QRectF(0, 0, self.width(), self._h)
        clip = QPainterPath()
        clip.addRoundedRect(r, self._h / 2, self._h / 2)
        p.fillPath(clip, QColor(pal["track"]))
        p.setClipPath(clip)
        for rect, color, _tip in self._rects():
            if color is None:
                p.fillRect(rect, QColor(pal["faint"]).darker(150) if pal["name"] == "dark" else QColor(pal["faint"]).lighter(130))
                p.setPen(QPen(QColor(pal["track"]), 2))
                step = 6
                x0 = int(rect.left()) - self._h
                while x0 < rect.right():
                    p.drawLine(QPointF(x0, self._h), QPointF(x0 + self._h, 0))
                    x0 += step
            else:
                p.fillRect(rect, QColor(color))
            # separator between segments
            p.fillRect(QRectF(rect.right() - 1, 0, 1.5, self._h), QColor(pal["surface"]))
        p.end()

    def mouseMoveEvent(self, e):
        for rect, _c, tip in self._rects():
            if rect.contains(e.position()) and tip:
                self.setToolTip(tip)
                return
        self.setToolTip("")


class Dot(QWidget):
    def __init__(self, color: str, size: int = 10):
        super().__init__()
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self._color is None:
            p.setBrush(QBrush(QColor(theme.current()["faint"]), Qt.BDiagPattern))
            p.setPen(QPen(QColor(theme.current()["faint"]), 1))
        else:
            p.setBrush(QColor(self._color))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)
        p.end()


class SegmentedControl(QWidget):
    changed = Signal(int)

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def set_index(self, i: int):
        self.group.button(i).setChecked(True)

    def index(self) -> int:
        return self.group.checkedId()


class Breadcrumb(QWidget):
    """Clickable path segments: C:\\  >  Users  >  Bob"""

    navigate = Signal(object)  # emits the node

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)

    def set_node(self, node):
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        chain = [node, *node.ancestors()]
        chain.reverse()
        if len(chain) > 5:
            chain = [chain[0], None, *chain[-3:]]
        for i, n in enumerate(chain):
            if i:
                sep = label("›", "faint")
                sep.setContentsMargins(2, 0, 2, 0)
                self.lay.addWidget(sep)
            if n is None:
                self.lay.addWidget(label("…", "muted"))
                continue
            text = n.name if n.parent is not None else _root_title(n.name)
            b = button(text, "crumbCurrent" if n is node else "crumb")
            b.clicked.connect(lambda _=False, target=n: self.navigate.emit(target))
            self.lay.addWidget(b)
        self.lay.addStretch(1)


def _root_title(path: str) -> str:
    return path.rstrip("\\/") or path


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

_icon_provider: QFileIconProvider | None = None
_icon_cache: dict[str, QIcon] = {}


def icon_provider() -> QFileIconProvider:
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
        _icon_provider.setOptions(QAbstractFileIconProvider.DontUseCustomDirectoryIcons)
    return _icon_provider


def folder_icon() -> QIcon:
    if "folder" not in _icon_cache:
        _icon_cache["folder"] = icon_provider().icon(QAbstractFileIconProvider.Folder)
    return _icon_cache["folder"]


def file_icon() -> QIcon:
    if "file" not in _icon_cache:
        _icon_cache["file"] = icon_provider().icon(QAbstractFileIconProvider.File)
    return _icon_cache["file"]


def icon_for_path(path: str, is_dir: bool) -> QIcon:
    """Native icon for a specific file (cached by extension)."""
    if is_dir:
        return folder_icon()
    ext = os.path.splitext(path)[1].lower()
    if ext in (".exe", ".lnk", ".ico"):
        icon = icon_provider().icon(QFileInfo(path))
        return icon if not icon.isNull() else file_icon()
    key = "ext:" + ext
    if key not in _icon_cache:
        icon = icon_provider().icon(QFileInfo(path))
        _icon_cache[key] = icon if not icon.isNull() else file_icon()
    return _icon_cache[key]


def ext_icon(ext: str) -> QIcon:
    """Icon for a file type, looked up once per extension (fast enough for huge lists)."""
    key = "ext:" + ext
    if key not in _icon_cache:
        icon = icon_provider().icon(QFileInfo("file" + ext)) if ext else file_icon()
        _icon_cache[key] = icon if not icon.isNull() else file_icon()
    return _icon_cache[key]


def drive_icon(path: str) -> QIcon:
    icon = icon_provider().icon(QFileInfo(path))
    if icon.isNull():
        icon = icon_provider().icon(QAbstractFileIconProvider.Drive)
    return icon


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """The SpaceScout logo: a rounded tile with a mini treemap."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    outer = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(outer.topLeft(), outer.bottomRight())
    g.setColorAt(0, QColor("#1d2230"))
    g.setColorAt(1, QColor("#0e1016"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(outer, s * 0.22, s * 0.22)
    pad = s * 0.17
    gap = s * 0.045
    inner = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)
    r = s * 0.07
    w1 = inner.width() * 0.58
    blocks = [
        (QRectF(inner.left(), inner.top(), w1 - gap / 2, inner.height()), "#5b8cff"),
        (QRectF(inner.left() + w1 + gap / 2, inner.top(), inner.width() - w1 - gap / 2, inner.height() * 0.55 - gap / 2), "#f76b15"),
        (QRectF(inner.left() + w1 + gap / 2, inner.top() + inner.height() * 0.55 + gap / 2,
                (inner.width() - w1) * 0.5 - gap, inner.height() * 0.45 - gap / 2), "#30a46c"),
        (QRectF(inner.left() + w1 + (inner.width() - w1) * 0.5 + gap / 2 - gap / 2, inner.top() + inner.height() * 0.55 + gap / 2,
                (inner.width() - w1) * 0.5, inner.height() * 0.45 - gap / 2), "#e93d82"),
    ]
    for rect, color in blocks:
        p.setBrush(QColor(color))
        p.drawRoundedRect(rect, r, r)
    p.end()
    return pm


def app_icon() -> QIcon:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    png = os.path.join(here, "assets", "icon.png")
    if os.path.exists(png):
        return QIcon(png)
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(sz))
    return icon


# ---------------------------------------------------------------------------
# Delegates
# ---------------------------------------------------------------------------


class PercentBarDelegate(QStyledItemDelegate):
    """Draws a small bar + percentage. Model must return a float 0..100 for Qt.UserRole."""

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle

        pal = theme.current()
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else None
        option.text = ""
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        pct = index.data(Qt.UserRole) or 0.0
        r = option.rect.adjusted(6, 0, -6, 0)
        bar_w = max(30, r.width() - 52)
        bar = QRectF(r.left(), r.center().y() - 4, bar_w, 8)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pal["track"]))
        painter.drawRoundedRect(bar, 4, 4)
        if pct > 0:
            fill = QRectF(bar.left(), bar.top(), max(3.0, bar.width() * min(pct, 100) / 100), bar.height())
            painter.setBrush(QColor(pal["accent"]))
            painter.drawRoundedRect(fill, 4, 4)
        painter.setPen(QColor(pal["muted"]))
        text_rect = QRectF(bar.right() + 6, r.top(), r.right() - bar.right() - 6, r.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignRight, f"{pct:.1f}%")
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(max(s.width(), 140), s.height())


class ColorDotDelegate(QStyledItemDelegate):
    """Draws a coloured square (Qt.UserRole + 1 holds the colour) before the text."""

    def paint(self, painter, option, index):
        color = index.data(Qt.UserRole + 1)
        if color:
            option.rect.adjust(18, 0, 0, 0)
        super().paint(painter, option, index)
        if color:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            r = option.rect
            painter.drawRoundedRect(QRectF(r.left() - 14, r.center().y() - 5, 10, 10), 3, 3)
            painter.restore()
