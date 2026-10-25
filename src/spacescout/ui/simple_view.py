"""Simple mode: a friendly overview, quick cleanups, and an easy file browser."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import categories, fileops, safety
from ..scanner import find_node, is_attached
from ..utils import format_count, format_date, format_duration, format_size, percent
from . import theme
from .models import node_kind, short_folder
from .widgets import Breadcrumb, Card, Dot, ElidedLabel, UsageBar, button, icon_for_path, label

ROW_LIMIT = 40


class _Worker(QThread):
    finished_value = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            value = self._fn()
        except Exception as exc:  # noqa: BLE001
            value = exc
        self.finished_value.emit(value)


class ItemRow(QWidget):
    """One file/folder line with size bar and Move/Delete buttons."""

    activated = Signal(object)
    moveRequested = Signal(object)
    deleteRequested = Signal(object)
    revealRequested = Signal(object)

    def __init__(self, node, parent_size: int, show_folder: bool = False):
        super().__init__()
        compact = show_folder
        self.node = node
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("row")
        self.setProperty("class", "row")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(node.path)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(icon_for_path(node.path, node.is_dir).pixmap(QSize(24, 24)))
        icon.setFixedWidth(26)
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        name = ElidedLabel(node.name, Qt.ElideMiddle)
        name.setStyleSheet("font-weight: 600;")
        col.addWidget(name)
        if show_folder:
            sub = short_folder(node.parent.path if node.parent else "")
        elif node.is_dir:
            sub = f"Folder · {format_count(node.files)} files"
            if node.error:
                sub += " · some contents hidden"
        else:
            sub = f"{node_kind(node)} · {format_date(node.mtime)[:10]}"
        col.addWidget(ElidedLabel(sub, Qt.ElideMiddle, role="faint"))
        lay.addLayout(col, 1)

        if not show_folder:
            bar_col = QVBoxLayout()
            bar_col.setSpacing(2)
            bar = UsageBar(6)
            bar.setFixedWidth(90)
            pct = percent(node.size, parent_size)
            color = categories.get(categories.category_for_ext(node.ext)).color if not node.is_dir else theme.current()["accent"]
            bar.set_fraction(pct / 100, color)
            bar_col.addWidget(bar)
            bar_col.addWidget(label(f"{pct:.1f}%", "faint"))
            lay.addLayout(bar_col)

        size = label(format_size(node.size))
        size.setStyleSheet("font-weight: 600;")
        size.setMinimumWidth(68)
        size.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(size)

        # Fixed-width action area so sizes and bars line up on every row.
        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        al.addStretch(1)
        actions.setFixedWidth(124 if compact else 186)
        prot = safety.classify(node.path)
        if prot.level != safety.Level.OK:
            lock = label("🔒 Protected", "lock")
            lock.setToolTip(prot.reason)
            al.addWidget(lock)
            self.setToolTip(f"{node.path}\n\nProtected: {prot.reason}")
        else:
            if not compact:
                show = button("Show", "small", "Show in File Explorer")
                show.clicked.connect(lambda: self.revealRequested.emit(self.node))
                al.addWidget(show)
            move = button("Move", "small", "Move to another drive")
            move.clicked.connect(lambda: self.moveRequested.emit(self.node))
            delete = button("Delete", "smallDanger", "Move to the Recycle Bin")
            delete.clicked.connect(lambda: self.deleteRequested.emit(self.node))
            al.addWidget(move)
            al.addWidget(delete)
        lay.addWidget(actions)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self.node)
        super().mouseReleaseEvent(e)


class CleanupCard(Card):
    def __init__(self, title: str, description: str, action_text: str, kind: str = "primary"):
        super().__init__(margins=(18, 16, 18, 16), spacing=6)
        self.lay.addWidget(label(title, "h3"))
        self.value = label("Checking…", "big")
        self.value.setStyleSheet("font-size: 18pt;")
        self.lay.addWidget(self.value)
        self.desc = label(description, "muted", wrap=True)
        self.desc.setMinimumHeight(36)
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lay.addWidget(self.desc, 1)
        row = QHBoxLayout()
        self.action = button(action_text, kind)
        self.action.setEnabled(False)
        row.addWidget(self.action)
        row.addStretch(1)
        self.lay.addLayout(row)


class SimpleView(QWidget):
    back = Signal()
    rescan = Signal()
    DL_TEXT = "Old installers and files you've already used often pile up here."

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.actions = actions
        self.result = None
        self.current = None
        self.limit = ROW_LIMIT
        self.cat_filter: str | None = None
        self._workers: list[_Worker] = []
        self._temp_items: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 22, 32, 32)
        lay.setSpacing(18)

        # Header
        head = QHBoxLayout()
        back = button("←  All drives", "ghost")
        back.clicked.connect(self.back.emit)
        head.addWidget(back)
        head.addStretch(1)
        again = button("Scan again")
        again.clicked.connect(self.rescan.emit)
        head.addWidget(again)
        lay.addLayout(head)
        self.title = label("", "h1")
        self.subtitle = label("", "muted")
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        lay.addLayout(tl)

        # Overview
        self.overview = Card(margins=(22, 20, 22, 20), spacing=12)
        ov_top = QHBoxLayout()
        self.free_big = label("", "big")
        ov_top.addWidget(self.free_big)
        self.free_sub = label("", "muted")
        ov_top.addWidget(self.free_sub, 0, Qt.AlignBottom)
        ov_top.addStretch(1)
        self.overview.lay.addLayout(ov_top)
        self.usage = UsageBar(18)
        self.overview.lay.addWidget(self.usage)
        self.legend_host = QWidget()
        self.legend = QGridLayout(self.legend_host)
        self.legend.setContentsMargins(0, 4, 0, 0)
        self.legend.setHorizontalSpacing(24)
        self.legend.setVerticalSpacing(8)
        self.overview.lay.addWidget(self.legend_host)
        lay.addWidget(self.overview)

        # Quick cleanup
        lay.addWidget(label("Quick wins", "h2"))
        clean_row = QHBoxLayout()
        clean_row.setSpacing(16)
        self.bin_card = CleanupCard("Recycle Bin", "Deleted files still use space until the bin is emptied.",
                                    "Empty Recycle Bin", "danger")
        self.bin_card.action.clicked.connect(self._empty_bin)
        self.temp_card = CleanupCard("Temporary files", "Leftovers from apps and installers. Only files older "
                                     "than a day are removed.", "Clean up")
        self.temp_card.action.clicked.connect(self._clean_temp)
        self.dl_card = CleanupCard("Downloads", self.DL_TEXT, "Review")
        self.dl_card.action.clicked.connect(self._review_downloads)
        for c in (self.bin_card, self.temp_card, self.dl_card):
            clean_row.addWidget(c, 1)
        lay.addLayout(clean_row)

        # Explore + largest files
        cols = QHBoxLayout()
        cols.setSpacing(16)
        self.explore = Card(margins=(14, 14, 14, 14), spacing=8)
        ex_head = QHBoxLayout()
        ex_head.addWidget(label("Explore", "h2"))
        ex_head.addStretch(1)
        self.up_btn = button("↑  Up", "ghost")
        self.up_btn.clicked.connect(self._go_up)
        ex_head.addWidget(self.up_btn)
        self.explore.lay.addLayout(ex_head)
        self.crumbs = Breadcrumb()
        self.crumbs.navigate.connect(self.navigate)
        self.explore.lay.addWidget(self.crumbs)
        self.rows_host = QVBoxLayout()
        self.rows_host.setSpacing(1)
        self.explore.lay.addLayout(self.rows_host)
        self.more_btn = button("Show more", "link")
        self.more_btn.clicked.connect(self._show_more)
        self.explore.lay.addWidget(self.more_btn, 0, Qt.AlignLeft)
        self.explore.lay.addStretch(1)
        cols.addWidget(self.explore, 3)

        self.largest = Card(margins=(14, 14, 14, 14), spacing=8)
        self.largest.lay.addWidget(label("Largest files", "h2"))
        self.chips_host = QHBoxLayout()
        self.chips_host.setSpacing(6)
        chip_wrap = QWidget()
        chip_wrap.setLayout(self.chips_host)
        self.largest.lay.addWidget(chip_wrap)
        self.largest.lay.addWidget(label("Click a file to see the folder it's in.", "faint"))
        self.big_rows = QVBoxLayout()
        self.big_rows.setSpacing(1)
        self.largest.lay.addLayout(self.big_rows)
        self.big_more = button("Show more", "link")
        self.big_more.clicked.connect(self._more_largest)
        self.largest.lay.addWidget(self.big_more, 0, Qt.AlignLeft)
        self.largest.lay.addStretch(1)
        self.big_limit = 12
        cols.addWidget(self.largest, 2)
        lay.addLayout(cols)
        lay.addStretch(1)

    # ---- data binding --------------------------------------------------
    def set_result(self, result):
        if self.result is not None:
            try:
                self.result.changed.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        self.result = result
        self.current = result.root
        self.cat_filter = None
        self.big_limit = 12
        self.limit = ROW_LIMIT
        self.scroll.verticalScrollBar().setValue(0)
        result.changed.connect(self.refresh)
        self.refresh()
        self._measure_cleanups()

    def refresh(self):
        r = self.result
        if r is None:
            return
        if self.current is None or not is_attached(self.current, r.root):
            self.current = r.root
        self.title.setText(r.title)
        sub = f"Scanned {format_count(r.root.files)} files in {format_duration(r.elapsed)}"
        if r.errors:
            sub += f" · {format_count(r.errors)} items couldn't be read"
        if not r.is_drive:
            sub = r.root.name + "  ·  " + sub
        self.subtitle.setText(sub)
        self._fill_overview()
        self._fill_explore()
        self._fill_largest()

    def _fill_overview(self):
        r = self.result
        d = r.drive
        if r.is_drive and d:
            self.free_big.setText(f"{format_size(d.free)} free")
            self.free_sub.setText(f"of {format_size(d.total)}  ·  {d.used_fraction * 100:.0f}% full")
            whole = d.total
        else:
            self.free_big.setText(format_size(r.root.size))
            self.free_sub.setText("used by this folder" + (f"  ·  {format_size(d.free)} free on the drive" if d else ""))
            whole = max(r.root.size, 1)
        parts = r.overview()
        segs = []
        for key, size in parts:
            cat = categories.get(key)
            color = None if key == categories.HIDDEN.key else cat.color
            segs.append((size / whole, color, f"{cat.label}: {format_size(size)}"))
        self.usage.set_segments(segs)

        while self.legend.count():
            w = self.legend.takeAt(0).widget()
            if w:
                w.deleteLater()
        cols = 4
        for i, (key, size) in enumerate(parts):
            cat = categories.get(key)
            item = QWidget()
            h = QHBoxLayout(item)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addWidget(Dot(None if key == categories.HIDDEN.key else cat.color, 11))
            h.addWidget(label(cat.label))
            h.addWidget(label(format_size(size), "muted"))
            h.addStretch(1)
            if key == categories.HIDDEN.key:
                item.setToolTip("Space used by files SpaceScout couldn't read, such as protected system files,\n"
                                "restore points, or other user accounts. Run as administrator to see more.")
            self.legend.addWidget(item, i // cols, i % cols)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                # hide + deleteLater (not setParent(None)): the row being cleared may be the one
                # whose button is still delivering its click.
                w.hide()
                w.deleteLater()

    def navigate(self, node):
        if node is None or not node.is_dir:
            return
        self.current = node
        self.limit = ROW_LIMIT
        self._fill_explore()

    def _go_up(self):
        if self.current is not None and self.current.parent is not None:
            self.navigate(self.current.parent)

    def _show_more(self):
        self.limit += ROW_LIMIT
        self._fill_explore()

    def _fill_explore(self):
        self._clear(self.rows_host)
        node = self.current
        self.crumbs.set_node(node)
        self.up_btn.setEnabled(node.parent is not None)
        kids = [c for c in node.children if c.size > 0] or node.children
        for c in kids[: self.limit]:
            row = ItemRow(c, node.size)
            row.activated.connect(self._row_activated)
            row.moveRequested.connect(lambda n: self.actions.move([n]))
            row.deleteRequested.connect(lambda n: self.actions.delete([n]))
            row.revealRequested.connect(self.actions.reveal)
            self.rows_host.addWidget(row)
        if not kids:
            self.rows_host.addWidget(label("This folder is empty.", "muted"))
        rest = kids[self.limit:]
        self.more_btn.setVisible(bool(rest))
        if rest:
            self.more_btn.setText(f"Show more ({len(rest)} more · {format_size(sum(c.size for c in rest))})")

    def _row_activated(self, node):
        if node.is_dir:
            self.navigate(node)
        else:
            self.actions.reveal(node)

    def _fill_largest(self):
        self._clear(self.chips_host)
        files = self.result.analysis.top_files
        present = []
        for f in files[:400]:
            k = categories.category_for_ext(f.ext)
            if k not in present:
                present.append(k)
        group = QButtonGroup(self.chips_host.parentWidget())
        group.setExclusive(True)
        for key in [None, *[k for k in categories.CATEGORIES if k in present]][:6]:
            chip = button("All" if key is None else categories.get(key).label.split(" ")[0], "chip")
            chip.setCheckable(True)
            chip.setChecked(key == self.cat_filter)
            chip.clicked.connect(lambda _=False, k=key: self._set_cat(k))
            group.addButton(chip)
            self.chips_host.addWidget(chip)
        self.chips_host.addStretch(1)

        self._clear(self.big_rows)
        shown = 0
        matching = [f for f in files if not self.cat_filter or categories.category_for_ext(f.ext) == self.cat_filter]
        for f in matching:
            row = ItemRow(f, 0, show_folder=True)
            row.activated.connect(lambda n: (self.navigate(n.parent), self.scroll.ensureWidgetVisible(self.explore)))
            row.moveRequested.connect(lambda n: self.actions.move([n]))
            row.deleteRequested.connect(lambda n: self.actions.delete([n]))
            row.revealRequested.connect(self.actions.reveal)
            self.big_rows.addWidget(row)
            shown += 1
            if shown >= self.big_limit:
                break
        if not shown:
            self.big_rows.addWidget(label("No files in this category.", "muted"))
        self.big_more.setVisible(len(matching) > shown)

    def _more_largest(self):
        self.big_limit += 12
        self._fill_largest()

    def _set_cat(self, key):
        self.cat_filter = key
        self.big_limit = 12
        self._fill_largest()

    # ---- quick cleanups ---------------------------------------------------
    def _run(self, fn, callback):
        w = _Worker(fn, self)
        w.finished_value.connect(callback)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _measure_cleanups(self):
        for c in (self.bin_card, self.temp_card, self.dl_card):
            c.value.setText("Checking…")
            c.action.setEnabled(False)
        self._run(fileops.recycle_bin_info, self._got_bin)
        self._run(lambda: fileops.measure_temp(24), self._got_temp)
        dl = fileops.downloads_folder()
        node = find_node(self.result.root, dl) if self.result else None
        if node is not None:
            QTimer.singleShot(0, lambda: self._got_downloads((dl, node.size)))
        else:
            self._run(lambda: (dl, fileops.path_size(dl) if os.path.isdir(dl) else -1), self._got_downloads)

    def _got_bin(self, value):
        if isinstance(value, Exception):
            value = (0, 0)
        size, count = value
        self.bin_card.value.setText(format_size(size) if count or size else "Empty")
        self.bin_card.action.setEnabled(bool(count or size))
        self.bin_card.desc.setText(f"{format_count(count)} deleted items are still using space." if count
                                   else "Nothing in the bin right now.")

    def _got_temp(self, value):
        if isinstance(value, Exception):
            self.temp_card.value.setText("—")
            return
        self._temp_items = value.items
        self.temp_card.value.setText(format_size(value.cleanable))
        self.temp_card.action.setEnabled(value.cleanable > 0)
        self.temp_card.action.setText(f"Clean up {format_size(value.cleanable)}" if value.cleanable else "Clean up")

    def _got_downloads(self, value):
        if isinstance(value, Exception):
            value = ("", -1)
        path, size = value
        self._downloads = path
        if size < 0:
            self.dl_card.value.setText("—")
            self.dl_card.desc.setText("Couldn't find your Downloads folder.")
            return
        self.dl_card.value.setText(format_size(size))
        self.dl_card.desc.setText(self.DL_TEXT)
        self.dl_card.action.setEnabled(True)

    def _empty_bin(self):
        if self.actions.empty_recycle_bin():
            self._run(fileops.recycle_bin_info, self._got_bin)

    def _clean_temp(self):
        from .dialogs import ProgressDialog, confirm

        items = list(self._temp_items)
        if not items:
            return
        if not confirm(self, "Clean up temporary files?", "Delete old temporary files?",
                       "Only files that haven't been touched for a day are removed. Files that are in use are "
                       "skipped automatically.", ok_text="Clean up"):
            return
        dlg = ProgressDialog(self, "Cleaning temporary files…")
        res = dlg.run(lambda prog, cancel: fileops.clean_temp(items, prog, cancel))
        if self.result is not None:
            nodes = [find_node(self.result.root, p) for p in res.done]
            self.result.remove_nodes([n for n in nodes if n is not None])
            self.result.refresh_drive()
            self.result.changed.emit()
        self.window().toast(f"Freed {format_size(res.bytes_done)} of temporary files."
                            + (" " + res.notes[0] if res.notes else ""))
        self.temp_card.value.setText("Checking…")
        self._run(lambda: fileops.measure_temp(24), self._got_temp)

    def _review_downloads(self):
        path = getattr(self, "_downloads", "")
        node = find_node(self.result.root, path) if (self.result and path) else None
        if node is not None and node.is_dir:
            self.navigate(node)
            self.scroll.ensureWidgetVisible(self.explore, 0, 0)
        elif path:
            from ..utils import reveal_in_file_manager

            reveal_in_file_manager(path)
