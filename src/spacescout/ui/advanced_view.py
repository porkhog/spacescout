"""Advanced mode: WizTree-style tree, treemap, largest files and file types."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QSplitter,
    QTableView,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..scanner import is_attached
from ..utils import format_count, format_duration, format_size
from .models import ExtensionModel, FileFilterProxy, FileListModel, NodeTreeModel
from .treemap import TreemapWidget
from .widgets import ColorDotDelegate, ElidedLabel, PercentBarDelegate, button, label


class AdvancedView(QWidget):
    back = Signal()
    rescan = Signal()

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.actions = actions
        self.result = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- toolbar -----------------------------------------------------
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(16, 10, 16, 10)
        tb.setSpacing(8)
        back = button("←  Drives", "ghost")
        back.clicked.connect(self.back.emit)
        tb.addWidget(back)
        self.root_label = ElidedLabel("", Qt.ElideMiddle)
        self.root_label.setStyleSheet("font-weight: 600;")
        tb.addWidget(self.root_label, 1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter files:  name, or .mp4 .mkv")
        self.filter.setClearButtonEnabled(True)
        self.filter.setMinimumWidth(240)
        self.filter.textChanged.connect(self._filter_changed)
        tb.addWidget(self.filter)
        self.btn_open = button("Open", None, "Open with the default app (Enter)")
        self.btn_reveal = button("Show in folder", None, "Show in File Explorer")
        self.btn_copy = button("Copy path", None, "Copy full path (Ctrl+C)")
        self.btn_move = button("Move to…", None, "Move to another drive")
        self.btn_recycle = button("Recycle", "danger", "Send to the Recycle Bin (Del)")
        self.btn_delete = button("Delete", "danger", "Delete permanently (Shift+Del)")
        self.btn_rescan = button("Rescan", "ghost", "Scan again (F5)")
        for b in (self.btn_open, self.btn_reveal, self.btn_copy, self.btn_move, self.btn_recycle, self.btn_delete,
                  self.btn_rescan):
            tb.addWidget(b)
        self.btn_open.clicked.connect(lambda: self.actions.open(self._first()))
        self.btn_reveal.clicked.connect(lambda: self.actions.reveal(self._first()))
        self.btn_copy.clicked.connect(lambda: self.actions.copy_paths(self.selected_nodes()))
        self.btn_move.clicked.connect(lambda: self.actions.move(self.selected_nodes()))
        self.btn_recycle.clicked.connect(lambda: self.actions.delete(self.selected_nodes()))
        self.btn_delete.clicked.connect(lambda: self.actions.delete(self.selected_nodes(), permanent=True))
        self.btn_rescan.clicked.connect(self.rescan.emit)
        lay.addWidget(bar)

        # ---- main split ----------------------------------------------------
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Tree
        self.tree_model = NodeTreeModel()
        self.tree = QTreeView()
        self.tree.setModel(self.tree_model)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.DescendingOrder)
        self.tree.setItemDelegateForColumn(2, PercentBarDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda pos: self._menu_for(self.tree, pos))
        self.tree.doubleClicked.connect(self._tree_double)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 90), (2, 150), (3, 90), (4, 80), (5, 130)):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, w)
        self.tabs.addTab(self.tree, "Folders")

        # Largest files
        self.files_model = FileListModel()
        self.files_proxy = FileFilterProxy()
        self.files_proxy.setSourceModel(self.files_model)
        self.files = self._table(self.files_proxy)
        fh = self.files.horizontalHeader()
        fh.setSectionResizeMode(0, QHeaderView.Interactive)
        self.files.setColumnWidth(0, 300)
        self.files.setColumnWidth(1, 90)
        self.files.setColumnWidth(2, 70)
        self.files.setColumnWidth(3, 130)
        fh.setStretchLastSection(True)
        self.files.sortByColumn(1, Qt.DescendingOrder)
        self.tabs.addTab(self.files, "Largest files")

        # File types
        self.ext_model = ExtensionModel()
        self.ext_proxy = QSortFilterProxyModel()
        self.ext_proxy.setSourceModel(self.ext_model)
        self.ext_proxy.setSortRole(Qt.UserRole)
        self.exts = self._table(self.ext_proxy)
        self.exts.setSelectionMode(QAbstractItemView.SingleSelection)
        self.exts.setItemDelegateForColumn(1, ColorDotDelegate(self.exts))
        self.exts.setItemDelegateForColumn(3, PercentBarDelegate(self.exts))
        self.exts.setContextMenuPolicy(Qt.NoContextMenu)
        self.exts.doubleClicked.connect(self._ext_double)
        self.exts.setToolTip("Double-click a type to list its largest files")
        eh = self.exts.horizontalHeader()
        for col, w in ((0, 140), (1, 190), (2, 100), (3, 200), (4, 90)):
            self.exts.setColumnWidth(col, w)
        eh.setStretchLastSection(True)
        self.exts.sortByColumn(2, Qt.DescendingOrder)
        self.tabs.addTab(self.exts, "File types")
        self.tabs.currentChanged.connect(lambda _i: self._update_buttons())
        split.addWidget(self.tabs)

        # Treemap
        tm_host = QWidget()
        tm_lay = QVBoxLayout(tm_host)
        tm_lay.setContentsMargins(0, 0, 0, 0)
        tm_lay.setSpacing(0)
        tm_bar = QWidget()
        tm_bar.setObjectName("toolbar")
        tm_bar.setAttribute(Qt.WA_StyledBackground, True)
        tmb = QHBoxLayout(tm_bar)
        tmb.setContentsMargins(12, 6, 12, 6)
        self.tm_up = button("↑ Up", "ghost", "Show the parent folder")
        self.tm_up.clicked.connect(self._treemap_up)
        self.tm_top = button("Top", "ghost", "Show the whole scan")
        self.tm_top.clicked.connect(lambda: self._set_treemap_root(self.result.root) if self.result else None)
        tmb.addWidget(self.tm_up)
        tmb.addWidget(self.tm_top)
        self.tm_path = ElidedLabel("", role="muted")
        tmb.addWidget(self.tm_path, 1)
        self.tm_hover = ElidedLabel("", Qt.ElideMiddle, role="faint")
        tmb.addWidget(self.tm_hover, 1)
        tm_lay.addWidget(tm_bar)
        self.treemap = TreemapWidget()
        self.treemap.nodeClicked.connect(self._treemap_clicked)
        self.treemap.nodeActivated.connect(self._set_treemap_root)
        self.treemap.contextRequested.connect(self._treemap_menu)
        self.treemap.hovered.connect(self._treemap_hover)
        tm_lay.addWidget(self.treemap, 1)
        split.addWidget(tm_host)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([420, 340])
        lay.addWidget(split, 1)

        # ---- status line ---------------------------------------------------
        status = QWidget()
        status.setObjectName("statusline")
        status.setAttribute(Qt.WA_StyledBackground, True)
        sl = QHBoxLayout(status)
        sl.setContentsMargins(16, 6, 16, 6)
        self.status = label("", "faint")
        self.sel_status = label("", "faint")
        sl.addWidget(self.status)
        sl.addStretch(1)
        sl.addWidget(self.sel_status)
        lay.addWidget(status)

        self.tree.selectionModel().selectionChanged.connect(self._tree_selection)
        self.files.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())

        self._shortcut(QKeySequence.Delete, lambda: self.actions.delete(self.selected_nodes()))
        self._shortcut(QKeySequence("Shift+Delete"), lambda: self.actions.delete(self.selected_nodes(), True))
        self._shortcut(QKeySequence.Copy, lambda: self.actions.copy_paths(self.selected_nodes()))
        self._shortcut(QKeySequence("F5"), self.rescan.emit)
        self._shortcut(QKeySequence("Ctrl+F"), lambda: self.filter.setFocus())
        self._shortcut(QKeySequence("Return"), lambda: self.actions.open(self._first()))
        self._update_buttons()

    def _shortcut(self, seq, fn):
        act = QAction(self)
        act.setShortcut(seq)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        act.triggered.connect(fn)
        self.addAction(act)

    def _table(self, model) -> QTableView:
        t = QTableView()
        t.setModel(model)
        t.setSortingEnabled(True)
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(28)
        t.setShowGrid(False)
        t.setWordWrap(False)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(lambda pos, tv=t: self._menu_for(tv, pos))
        return t

    # ---- data binding ------------------------------------------------------
    def set_result(self, result):
        if self.result is not None:
            for sig, slot in ((self.result.aboutToRemove, self.tree_model.before_remove),
                              (self.result.removed, self.tree_model.after_remove),
                              (self.result.changed, self.refresh)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self.result = result
        result.aboutToRemove.connect(self.tree_model.before_remove)
        result.removed.connect(self.tree_model.after_remove)
        result.changed.connect(self.refresh)
        self.tree_model.set_root(result.root)
        self.tree.expand(self.tree_model.index(0, 0))
        self.tree.setCurrentIndex(self.tree_model.index(0, 0))
        self.treemap.set_root(result.root)
        self.refresh()

    def refresh(self):
        r = self.result
        if r is None:
            return
        self.root_label.setText(r.root.name)
        self.files_model.set_nodes(r.analysis.top_files)
        self.ext_model.set_stats(r.analysis.ext_stats, r.root.size)
        tm_root = self.treemap.root()
        if tm_root is None or not is_attached(tm_root, r.root):
            tm_root = r.root
        self.treemap.set_root(tm_root)
        self.treemap.invalidate()
        self.tree.viewport().update()
        status = (f"{format_size(r.root.size)} in {format_count(r.root.files)} files, "
                  f"{format_count(r.root.dirs)} folders · scanned in {format_duration(r.elapsed)}")
        if r.errors:
            status += f" · {format_count(r.errors)} unreadable"
        if r.drive:
            status += f" · {format_size(r.drive.free)} free of {format_size(r.drive.total)}"
        self.status.setText(status)
        self._update_tm_header()
        self._update_buttons()

    # ---- selection -------------------------------------------------------
    def selected_nodes(self) -> list:
        w = self.tabs.currentWidget()
        if w is self.tree:
            rows = self.tree.selectionModel().selectedRows(0)
            return [self.tree_model.node(i) for i in rows]
        if w is self.files:
            rows = self.files.selectionModel().selectedRows(0)
            return [self.files_model.node(self.files_proxy.mapToSource(i).row()) for i in rows]
        return []

    def _first(self):
        nodes = self.selected_nodes()
        return nodes[0] if nodes else None

    def _update_buttons(self):
        nodes = [n for n in self.selected_nodes() if n is not None]
        has = bool(nodes)
        not_root = has and all(n.parent is not None for n in nodes)
        for b in (self.btn_open, self.btn_reveal, self.btn_copy):
            b.setEnabled(has)
        for b in (self.btn_move, self.btn_recycle, self.btn_delete):
            b.setEnabled(not_root)
        if has:
            total = sum(n.size for n in nodes)
            self.sel_status.setText(f"{len(nodes)} selected · {format_size(total)}")
        else:
            self.sel_status.setText("")

    def _tree_selection(self, *_):
        self._update_buttons()
        node = self.tree_model.node(self.tree.currentIndex())
        if node is None:
            return
        target = node if node.is_dir else node.parent
        if target is not None and target is not self.treemap.root():
            self.treemap.set_root(target)
            self._update_tm_header()
        self.treemap.set_highlight(node if node is not self.treemap.root() else None)

    def select_node(self, node):
        idx = self.tree_model.index_for_node(node)
        if not idx.isValid():
            return
        self.tabs.setCurrentWidget(self.tree)
        p = idx.parent()
        while p.isValid():
            self.tree.expand(p)
            p = p.parent()
        self.tree.selectionModel().setCurrentIndex(
            idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.tree.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    def _tree_double(self, idx):
        node = self.tree_model.node(idx)
        if node is not None and not node.is_dir:
            self.actions.open(node)

    # ---- treemap ----------------------------------------------------------
    def _set_treemap_root(self, node):
        if node is None:
            return
        self.treemap.set_root(node)
        self.treemap.set_highlight(None)
        self._update_tm_header()

    def _treemap_up(self):
        r = self.treemap.root()
        if r is not None and r.parent is not None:
            self._set_treemap_root(r.parent)

    def _update_tm_header(self):
        r = self.treemap.root()
        if r is None:
            return
        self.tm_path.setText(f"{r.path}  ·  {format_size(r.size)}")
        self.tm_up.setEnabled(r.parent is not None)
        self.tm_top.setEnabled(r.parent is not None)

    def _treemap_clicked(self, node):
        root = self.treemap.root()
        self.select_node(node)
        # keep the treemap where it was when clicking inside it
        if root is not None and self.treemap.root() is not root:
            self.treemap.set_root(root)
            self._update_tm_header()
        self.treemap.set_highlight(node)

    def _treemap_hover(self, node):
        self.tm_hover.setText(f"{node.path}  —  {format_size(node.size)}" if node is not None else "")

    def _treemap_menu(self, node, global_pos):
        self.select_node(node)
        self._show_menu([node], global_pos, treemap_node=node)

    # ---- context menu -------------------------------------------------------
    def _menu_for(self, view, pos):
        nodes = self.selected_nodes()
        if not nodes:
            return
        self._show_menu(nodes, view.viewport().mapToGlobal(pos))

    def _show_menu(self, nodes, global_pos, treemap_node=None):
        nodes = [n for n in nodes if n is not None]
        if not nodes:
            return
        m = QMenu(self)
        first = nodes[0]
        not_root = all(n.parent is not None for n in nodes)
        m.addAction("Open", lambda: self.actions.open(first))
        m.addAction("Show in folder", lambda: self.actions.reveal(first))
        m.addAction("Copy path", lambda: self.actions.copy_paths(nodes))
        if first.is_dir:
            m.addAction("Show in treemap", lambda: self._set_treemap_root(first))
        m.addSeparator()
        a = m.addAction("Move to another drive…", lambda: self.actions.move(nodes))
        a.setEnabled(not_root)
        a = m.addAction("Send to Recycle Bin\tDel", lambda: self.actions.delete(nodes))
        a.setEnabled(not_root)
        a = m.addAction("Delete permanently\tShift+Del", lambda: self.actions.delete(nodes, permanent=True))
        a.setEnabled(not_root)
        m.exec(global_pos)

    # ---- filtering ---------------------------------------------------------
    def _filter_changed(self, text):
        self.files_proxy.set_filter(text)
        if text and self.tabs.currentWidget() is not self.files:
            self.tabs.setCurrentWidget(self.files)

    def _ext_double(self, idx):
        ext = self.ext_model.ext_at(self.ext_proxy.mapToSource(idx).row())
        if ext:
            self.filter.setText(ext)
            self.tabs.setCurrentWidget(self.files)
