"""Squarified treemap, like WizTree / WinDirStat."""

from __future__ import annotations

import zlib

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import categories
from ..utils import format_size
from . import theme

MAX_ITEMS = 30000
HEADER_H = 16


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Lay out `values` (sorted largest first, summing to w*h) as near-square rectangles.

    Bruls, Huizing & van Wijk, "Squarified Treemaps" (2000).
    """
    rects: list[tuple[float, float, float, float]] = []
    n = len(values)
    i = 0
    while i < n:
        if w <= 0 or h <= 0:
            rects.extend((x, y, 0.0, 0.0) for _ in range(n - i))
            break
        short = min(w, h)
        row_sum = values[i]
        row_min = row_max = values[i]
        j = i + 1
        s2 = short * short

        def worst(rs, rmin, rmax, s2=s2):
            if rs <= 0 or rmin <= 0:
                return float("inf")
            return max(s2 * rmax / (rs * rs), (rs * rs) / (s2 * rmin))

        current = worst(row_sum, row_min, row_max)
        while j < n:
            v = values[j]
            ns = row_sum + v
            nw = worst(ns, min(row_min, v), max(row_max, v))
            if nw > current:
                break
            row_sum, row_min, row_max, current = ns, min(row_min, v), max(row_max, v), nw
            j += 1
        if w >= h:
            rw = row_sum / h if h else 0
            yy = y
            for k in range(i, j):
                rh = values[k] / rw if rw else 0
                rects.append((x, yy, rw, rh))
                yy += rh
            x += rw
            w -= rw
        else:
            rh = row_sum / w if w else 0
            xx = x
            for k in range(i, j):
                cw = values[k] / rh if rh else 0
                rects.append((xx, y, cw, rh))
                xx += cw
            y += rh
            h -= rh
        i = j
    return rects


def color_for_node(node) -> QColor:
    cat = categories.category_for_ext(node.ext)
    base = QColor(categories.get(cat).color)
    shift = zlib.crc32(node.ext.encode()) % 5
    factor = (88, 94, 100, 108, 116)[shift]
    return base.lighter(factor) if factor >= 100 else base.darker(int(10000 / factor))


class TreemapWidget(QWidget):
    nodeClicked = Signal(object)
    nodeActivated = Signal(object)  # double-click
    contextRequested = Signal(object, object)  # node, global QPoint
    hovered = Signal(object)  # node or None
    rootChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(120)
        self._root = None
        self._items: list[tuple[QRectF, object, int]] = []
        self._kids: list[list[int]] = []  # item index -> child item indices (for fast hit-testing)
        self._rect_by_id: dict[int, QRectF] = {}
        self._pixmap: QPixmap | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(140)
        self._resize_timer.timeout.connect(self.invalidate)
        self._dirty = True
        self._hover = None
        self._highlight = None
        self._font = QFont(self.font())
        self._font.setPointSizeF(8)

    # ---- public API --------------------------------------------------
    def set_root(self, node):
        if node is self._root and not self._dirty:
            return
        self._root = node
        self._hover = None
        self.invalidate()
        self.rootChanged.emit(node)

    def root(self):
        return self._root

    def set_highlight(self, node):
        self._highlight = node
        self.update()

    def invalidate(self):
        self._dirty = True
        self._pixmap = None
        self.update()

    # ---- layout --------------------------------------------------------
    def _layout(self):
        self._items = []
        self._kids = []
        self._rect_by_id = {}
        root = self._root
        if root is None:
            return
        rect = QRectF(0, 0, self.width(), self.height())
        stack = [(root, rect, 0, -1)]
        items = self._items
        kids_of = self._kids
        while stack and len(items) < MAX_ITEMS:
            node, r, depth, parent_i = stack.pop()
            my_i = len(items)
            items.append((r, node, depth))
            kids_of.append([])
            self._rect_by_id[id(node)] = r
            if parent_i >= 0:
                kids_of[parent_i].append(my_i)
            if not node.is_dir or not node.children:
                continue
            inner = r.adjusted(2, 2, -2, -2)
            if depth > 0 and inner.height() > 34 and inner.width() > 46:
                inner.setTop(inner.top() + HEADER_H - 2)
            if inner.width() < 4 or inner.height() < 4:
                continue
            total = node.size
            if total <= 0:
                continue
            area = inner.width() * inner.height()
            scale = area / total
            vals = []
            kids = []
            for c in node.children:
                v = c.size * scale
                if v < 2.0:  # too small to see; children are sorted, so stop here
                    break
                vals.append(v)
                kids.append(c)
            if not vals:
                continue
            # Leave unused area for the tiny items we skipped, so proportions stay true.
            used = sum(vals)
            if used < area:
                frac = used / area
                if inner.width() >= inner.height():
                    inner.setWidth(inner.width() * frac)
                else:
                    inner.setHeight(inner.height() * frac)
            rects = squarify(vals, inner.x(), inner.y(), inner.width(), inner.height())
            for c, (x, y, w, h) in zip(reversed(kids), reversed(rects), strict=True):
                if w >= 1 and h >= 1:
                    stack.append((c, QRectF(x, y, w, h), depth + 1, my_i))

    def _render(self):
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pal = theme.current()
        pm.fill(QColor(pal["treemap_bg"]))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        dark = pal["name"] == "dark"
        border = QColor(pal["treemap_bg"])
        for r, node, depth in self._items:
            if node.is_dir:
                if depth == 0:
                    continue
                shade = QColor("#2a3040") if dark else QColor("#c3c9d4")
                shade = shade.lighter(100 + min(depth, 6) * 6) if dark else shade.darker(100 + min(depth, 6) * 3)
                p.fillRect(r, shade)
                p.setPen(QPen(border, 1))
                p.drawRect(r.adjusted(0, 0, -1, -1))
                if r.height() > 34 and r.width() > 46:
                    p.setPen(QColor("#dfe4ee") if dark else QColor("#1f2430"))
                    text = f"{node.name}  {format_size(node.size)}"
                    tr = QRectF(r.left() + 4, r.top() + 1, r.width() - 8, HEADER_H - 2)
                    p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(text, Qt.ElideRight, int(tr.width())))
            else:
                base = color_for_node(node)
                if r.width() > 3 and r.height() > 3:
                    g = QLinearGradient(r.topLeft(), r.bottomRight())
                    g.setColorAt(0, base.lighter(128))
                    g.setColorAt(1, base.darker(135))
                    p.fillRect(r, g)
                else:
                    p.fillRect(r, base)
                if r.width() > 2 and r.height() > 2:
                    p.setPen(QPen(border, 1))
                    p.drawRect(r.adjusted(0, 0, -1, -1))
                if r.width() > 70 and r.height() > 30:
                    p.setPen(QColor(255, 255, 255, 225))
                    tr = r.adjusted(4, 2, -4, -2)
                    name = fm.elidedText(node.name, Qt.ElideMiddle, int(tr.width()))
                    p.drawText(tr, Qt.AlignTop | Qt.AlignLeft, name)
                    p.setPen(QColor(255, 255, 255, 170))
                    p.drawText(tr.adjusted(0, fm.height(), 0, 0), Qt.AlignTop | Qt.AlignLeft, format_size(node.size))
        p.end()
        self._pixmap = pm

    # ---- painting --------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        pal = theme.current()
        if self._root is None or self._root.size <= 0:
            p.fillRect(self.rect(), QColor(pal["surface"]))
            p.setPen(QColor(pal["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Nothing to show here")
            return
        if self._resize_timer.isActive() and self._pixmap is not None:
            p.drawPixmap(self.rect(), self._pixmap)
            return
        if self._dirty or self._pixmap is None:
            self._layout()
            self._render()
            self._dirty = False
        p.drawPixmap(0, 0, self._pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        for node, color, width in ((self._highlight, "#ffffff", 2.5), (self._hover, "#ffffff", 1.5)):
            if node is None:
                continue
            r = self._rect_of(node)
            if r is not None:
                p.setPen(QPen(QColor(color), width))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(1, 1, -1, -1))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Re-layout once resizing pauses; meanwhile the old picture is stretched.
        self._resize_timer.start()

    def _rect_of(self, node):
        return self._rect_by_id.get(id(node)) if node is not None else None

    def node_at(self, pos: QPointF):
        if not self._items or not self._items[0][0].contains(pos):
            return None
        i = 0
        while True:
            for c in self._kids[i]:
                if self._items[c][0].contains(pos):
                    i = c
                    break
            else:
                return self._items[i][1]

    # ---- mouse -----------------------------------------------------------
    def mouseMoveEvent(self, e):
        node = self.node_at(e.position())
        if node is not self._hover:
            self._hover = node
            self.hovered.emit(node)
            self.update()
            if node is not None:
                kind = "Folder" if node.is_dir else (node.ext[1:].upper() + " file" if node.ext else "File")
                QToolTip.showText(e.globalPosition().toPoint(),
                                  f"<b>{node.name}</b><br>{format_size(node.size)} · {kind}", self)

    def leaveEvent(self, _e):
        self._hover = None
        self.hovered.emit(None)
        self.update()

    def mousePressEvent(self, e):
        node = self.node_at(e.position())
        if node is None:
            return
        if e.button() == Qt.LeftButton:
            self.nodeClicked.emit(node)
        elif e.button() == Qt.RightButton:
            self.contextRequested.emit(node, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        node = self.node_at(e.position())
        if node is None:
            return
        target = node if node.is_dir else node.parent
        if target is not None and target is not self._root:
            self.nodeActivated.emit(target)
