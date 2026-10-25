"""Qt item models over the scanned Node tree."""

from __future__ import annotations

import os

from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from .. import categories
from ..utils import format_count, format_date, format_size, percent
from . import widgets

SORT_KEYS = {
    0: lambda n: n.name.casefold(),
    1: lambda n: n.size,
    2: lambda n: n.size,
    3: lambda n: n.files if n.is_dir else 0,
    4: lambda n: n.dirs if n.is_dir else 0,
    5: lambda n: n.mtime,
}


class NodeTreeModel(QAbstractItemModel):
    HEADERS = ["Name", "Size", "% of folder", "Files", "Folders", "Modified"]

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self._root = root
        self._gen = 0  # sort generation; 0 = largest-first (how the scanner leaves it)
        self._sort_col = 1
        self._desc = True
        self._sorted: dict[int, int] = {}

    def set_root(self, root):
        self.beginResetModel()
        self._root = root
        self._gen = 0
        self._sort_col, self._desc = 1, True
        self._sorted.clear()
        self.endResetModel()

    def root_node(self):
        return self._root

    # ---- sorting (lazy, per folder) ---------------------------------------
    def _ensure_sorted(self, node):
        if self._gen == 0 or self._sorted.get(id(node)) == self._gen:
            return
        key = SORT_KEYS.get(self._sort_col, SORT_KEYS[1])
        node.children.sort(key=key, reverse=self._desc)
        for i, c in enumerate(node.children):
            c.idx = i
        self._sorted[id(node)] = self._gen

    def sort(self, column, order=Qt.DescendingOrder):
        if self._root is None:
            return
        desc = order == Qt.DescendingOrder
        if (column, desc) == (self._sort_col, self._desc):
            return
        self.layoutAboutToBeChanged.emit()
        old = self.persistentIndexList()
        pairs = [(i.internalPointer(), i.column()) for i in old]
        self._sort_col, self._desc = column, desc
        self._gen += 1
        self._sorted.clear()
        for n, _c in pairs:
            if n is not None and n.parent is not None:
                self._ensure_sorted(n.parent)
        new = [self.createIndex(n.idx if n.parent is not None else 0, c, n) for n, c in pairs]
        self.changePersistentIndexList(old, new)
        self.layoutChanged.emit()

    # ---- structure ----------------------------------------------------------
    def index(self, row, column, parent=QModelIndex()):
        if self._root is None:
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, self._root) if row == 0 else QModelIndex()
        pnode = parent.internalPointer()
        if not pnode.is_dir:
            return QModelIndex()
        self._ensure_sorted(pnode)
        if 0 <= row < len(pnode.children):
            return self.createIndex(row, column, pnode.children[row])
        return QModelIndex()

    def parent(self, index=QModelIndex()):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        p = node.parent
        if p is None:
            return QModelIndex()
        if p.parent is None:
            return self.createIndex(0, 0, p)
        return self.createIndex(p.idx, 0, p)

    def rowCount(self, parent=QModelIndex()):
        if self._root is None:
            return 0
        if not parent.isValid():
            return 1
        if parent.column() > 0:
            return 0
        node = parent.internalPointer()
        return len(node.children) if node.is_dir else 0

    def hasChildren(self, parent=QModelIndex()):
        if not parent.isValid():
            return self._root is not None
        node = parent.internalPointer()
        return node.is_dir and bool(node.children)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole and section in (1, 3, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return node.name if node.parent is not None else node.name
            if col == 1:
                return format_size(node.size)
            if col == 3:
                return format_count(node.files) if node.is_dir else ""
            if col == 4:
                return format_count(node.dirs) if node.is_dir else ""
            if col == 5:
                return format_date(node.mtime)
            return None
        if role == Qt.UserRole:
            if col == 2:
                return percent(node.size, node.parent.size) if node.parent is not None else 100.0
            return SORT_KEYS[col](node)
        if role == Qt.DecorationRole and col == 0:
            return widgets.folder_icon() if node.is_dir else widgets.ext_icon(node.ext)
        if role == Qt.ToolTipRole and col == 0:
            tip = node.path
            if node.error:
                tip += "\n(Some contents couldn't be read - try running as administrator)"
            return tip
        if role == Qt.TextAlignmentRole and col in (1, 3, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and col == 0 and node.error:
            from PySide6.QtGui import QColor

            from . import theme

            return QColor(theme.current()["warning"])
        return None

    def node(self, index):
        return index.internalPointer() if index.isValid() else None

    def index_for_node(self, node, column: int = 0) -> QModelIndex:
        if self._root is None or node is None:
            return QModelIndex()
        chain = [node, *node.ancestors()]
        chain.reverse()
        if chain[0] is not self._root:
            return QModelIndex()
        for n in chain[:-1]:
            self._ensure_sorted(n)
        if node.parent is None:
            return self.createIndex(0, column, node)
        return self.createIndex(node.idx, column, node)

    # ---- removal hooks (called by the ScanResult signals) -----------------
    def before_remove(self, node):
        parent = node.parent
        if parent is None:
            return
        self._ensure_sorted(parent)
        pidx = self.index_for_node(parent)
        self.beginRemoveRows(pidx, node.idx, node.idx)

    def after_remove(self, _node):
        self.endRemoveRows()


class FileListModel(QAbstractTableModel):
    """Flat list of files (used for 'Largest files')."""

    HEADERS = ["Name", "Size", "Type", "Modified", "Folder"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: list = []
        self._paths: dict[int, str] = {}

    def set_nodes(self, nodes):
        self.beginResetModel()
        self._nodes = list(nodes)
        self._paths = {}
        self.endResetModel()

    def nodes(self):
        return self._nodes

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._nodes)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole and section == 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def _folder(self, node):
        key = id(node)
        if key not in self._paths:
            self._paths[key] = node.parent.path if node.parent else ""
        return self._paths[key]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = self._nodes[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return node.name
            if col == 1:
                return format_size(node.size)
            if col == 2:
                return node.ext[1:].upper() if node.ext else ""
            if col == 3:
                return format_date(node.mtime)
            if col == 4:
                return self._folder(node)
        elif role == Qt.UserRole:
            return (node.name.casefold(), node.size, node.ext, node.mtime, self._folder(node).casefold())[col]
        elif role == Qt.DecorationRole and col == 0:
            return widgets.ext_icon(node.ext)
        elif role == Qt.ToolTipRole:
            return node.path
        elif role == Qt.TextAlignmentRole and col == 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def node(self, row):
        return self._nodes[row]


class FileFilterProxy(QSortFilterProxyModel):
    """Filter by '.ext' (exact extension) or by text in the name/folder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setSortRole(Qt.UserRole)

    def set_filter(self, text: str):
        self._text = text.strip().lower()
        self.invalidateFilter()

    def filter_text(self) -> str:
        return self._text

    def filterAcceptsRow(self, row, parent):
        if not self._text:
            return True
        node = self.sourceModel().node(row)
        terms = self._text.split()
        for t in terms:
            if t.startswith("."):
                if node.ext != t:
                    return False
            elif t not in node.name.lower() and t not in (node.parent.path.lower() if node.parent else ""):
                return False
        return True


class ExtensionModel(QAbstractTableModel):
    HEADERS = ["Type", "Category", "Size", "% of total", "Files"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, int, int]] = []
        self._total = 0

    def set_stats(self, ext_stats: dict, total: int):
        self.beginResetModel()
        self._rows = sorted(((e, s[0], s[1]) for e, s in ext_stats.items() if s[1] > 0), key=lambda r: r[1], reverse=True)
        self._total = total
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole and section in (2, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def ext_at(self, row) -> str:
        return self._rows[row][0]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        ext, size, count = self._rows[index.row()]
        col = index.column()
        cat = categories.get(categories.category_for_ext(ext))
        if role == Qt.DisplayRole:
            if col == 0:
                return ext if ext else "(no extension)"
            if col == 1:
                return cat.label
            if col == 2:
                return format_size(size)
            if col == 4:
                return format_count(count)
        elif role == Qt.UserRole:
            return (ext, cat.label, size, percent(size, self._total), count)[col]
        elif role == Qt.UserRole + 1 and col == 1:
            return cat.color
        elif role == Qt.TextAlignmentRole and col in (2, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


def node_kind(node) -> str:
    if node.is_dir:
        return "Folder"
    cat = categories.category_for_ext(node.ext)
    names = {
        "videos": "Video",
        "pictures": "Picture",
        "music": "Audio",
        "documents": "Document",
        "archives": "Archive / installer",
        "apps": "Program file",
    }
    if cat in names:
        return names[cat]
    return (node.ext[1:].upper() + " file") if node.ext else "File"


def short_folder(path: str, max_parts: int = 3) -> str:
    parts = path.replace("/", os.sep).split(os.sep)
    parts = [p for p in parts if p]
    if len(parts) <= max_parts:
        return path
    return "…" + os.sep + os.sep.join(parts[-max_parts:])
