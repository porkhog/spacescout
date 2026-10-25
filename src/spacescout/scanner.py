"""Fast multi-threaded disk scanner and the in-memory tree it produces.

The scanner is plain Python (no Qt) so it can be unit-tested and reused.
"""

from __future__ import annotations

import heapq
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from . import categories
from .utils import IS_WINDOWS


class Node:
    """One file or folder. Folders hold their children sorted by size (largest first)."""

    __slots__ = ("name", "parent", "children", "size", "mtime", "files", "dirs", "is_dir", "error", "idx")

    def __init__(self, name: str, parent: "Node | None", is_dir: bool, size: int = 0, mtime: float = 0.0):
        self.name = name
        self.parent = parent
        self.is_dir = is_dir
        self.children: list[Node] | None = [] if is_dir else None
        self.size = size
        self.mtime = mtime
        self.files = 0  # files inside (recursive), folders only
        self.dirs = 0  # sub-folders inside (recursive), folders only
        self.error = False  # True if the folder couldn't be read
        self.idx = 0  # position within parent.children (kept up to date for the tree view)

    # ---- helpers -------------------------------------------------------
    @property
    def path(self) -> str:
        parts = []
        node: Node | None = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        parts.reverse()
        return os.path.join(*parts)

    @property
    def ext(self) -> str:
        if self.is_dir:
            return ""
        dot = self.name.rfind(".")
        if dot <= 0:
            return ""
        return self.name[dot:].lower()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def root(self) -> "Node":
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def depth(self) -> int:
        return sum(1 for _ in self.ancestors())

    def __repr__(self) -> str:  # pragma: no cover
        kind = "dir" if self.is_dir else "file"
        return f"<Node {kind} {self.name!r} {self.size}>"


def is_drive_root(path: str) -> bool:
    path = os.path.abspath(path)
    return os.path.dirname(path) == path


_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
# OneDrive / cloud placeholders: listed with their full size but not stored on this disk.
_CLOUD_ONLY = 0x00400000 | 0x00040000 | 0x00001000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def _is_junction(entry: os.DirEntry) -> bool:
    """True for Windows junctions / mounted folders (never followed, to avoid double counting)."""
    fn = getattr(entry, "is_junction", None)
    try:
        if fn is not None:
            return fn()
        if IS_WINDOWS:  # Python < 3.12
            st = entry.stat(follow_symlinks=False)
            return getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT
    except OSError:
        return False
    return False


class Scanner:
    """Scans a folder tree on background worker thread(s).

    Progress counters (files, bytes, dirs, errors, current) can be read from
    another thread while `run()` is executing.
    """

    def __init__(self, root_path: str, workers: int | None = None):
        self.root_path = os.path.abspath(root_path)
        # One worker is fastest in CPython: extra threads mostly fight over the GIL.
        self.workers = max(1, workers or 1)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.files = 0
        self.dirs = 0
        self.bytes = 0
        self.errors = 0
        self.current = self.root_path
        self.started = 0.0
        self.elapsed = 0.0
        self._root_dev = None

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> Node:
        self.started = time.monotonic()
        root = Node(self.root_path, None, True)
        try:
            st = os.stat(self.root_path)
            root.mtime = st.st_mtime
            if not IS_WINDOWS:
                self._root_dev = st.st_dev
        except OSError:
            root.error = True

        work: queue.Queue = queue.Queue()
        work.put((root, self.root_path))
        share_below = self.workers

        def worker() -> None:
            while True:
                item = work.get()
                if item is None:
                    work.task_done()
                    return
                try:
                    # Work through this subtree locally; hand sub-folders to idle
                    # workers only when the shared queue is running low.
                    local = [item]
                    while local and not self._cancel.is_set():
                        node, path = local.pop()
                        for sub in self._scan_dir(node, path):
                            if work.qsize() < share_below:
                                work.put(sub)
                            else:
                                local.append(sub)
                finally:
                    work.task_done()

        threads = [threading.Thread(target=worker, daemon=True, name=f"scan-{i}") for i in range(self.workers)]
        for t in threads:
            t.start()
        work.join()
        for _ in threads:
            work.put(None)
        for t in threads:
            t.join()

        finalize(root)
        self.elapsed = time.monotonic() - self.started
        return root

    def _scan_dir(self, node: Node, path: str) -> list[tuple[Node, str]]:
        self.current = path
        files = dirs = errors = 0
        total = 0
        children = node.children
        subdirs: list[tuple[Node, str]] = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_symlink() or _is_junction(entry):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            if self._root_dev is not None and st.st_dev != self._root_dev:
                                continue  # another filesystem mounted inside (Linux/macOS)
                            child = Node(entry.name, node, True, 0, st.st_mtime)
                            children.append(child)
                            dirs += 1
                            subdirs.append((child, entry.path))
                        else:
                            st = entry.stat(follow_symlinks=False)
                            size = st.st_size
                            if IS_WINDOWS and getattr(st, "st_file_attributes", 0) & _CLOUD_ONLY:
                                size = 0
                            children.append(Node(entry.name, node, False, size, st.st_mtime))
                            files += 1
                            total += size
                    except OSError:
                        errors += 1
        except OSError:
            node.error = True
            errors += 1
        with self._lock:
            self.files += files
            self.dirs += dirs
            self.bytes += total
            self.errors += errors
        return subdirs


def finalize(root: Node) -> None:
    """Roll sizes/counts up the tree and sort every folder largest-first."""
    order: list[Node] = []
    stack = [root]
    while stack:
        n = stack.pop()
        order.append(n)
        stack.extend(c for c in n.children if c.is_dir)
    for n in reversed(order):
        size = files = dirs = 0
        mt = n.mtime
        for c in n.children:
            size += c.size
            if c.is_dir:
                files += c.files
                dirs += c.dirs + 1
            else:
                files += 1
            if c.mtime > mt:
                mt = c.mtime
        n.size, n.files, n.dirs, n.mtime = size, files, dirs, mt
        n.children.sort(key=_size_key, reverse=True)
        for i, c in enumerate(n.children):
            c.idx = i


def _size_key(n: Node) -> int:
    return n.size


def iter_files(node: Node):
    if not node.is_dir:
        yield node
        return
    stack = [node]
    while stack:
        n = stack.pop()
        for c in n.children:
            if c.is_dir:
                stack.append(c)
            else:
                yield c


# ---------------------------------------------------------------------------
# Analysis: category totals, extension totals and the biggest files.
# ---------------------------------------------------------------------------


@dataclass
class Analysis:
    top_files: list[Node] = field(default_factory=list)
    ext_stats: dict[str, list[int]] = field(default_factory=dict)  # ext -> [bytes, count]
    cat_stats: dict[str, int] = field(default_factory=dict)  # category key -> bytes


def _context_override(node: Node) -> str | None:
    """Category override inherited from the node's ancestors (outermost wins)."""
    chain = [node, *node.ancestors()]
    chain.reverse()
    found = None
    for i, n in enumerate(chain):
        if i == 0 or not n.is_dir:
            continue
        parent = chain[i - 1]
        ov = categories.folder_override(n.name, parent.parent is None and is_drive_root(parent.name))
        if ov and found is None:
            found = ov
    return found


def analyze(node: Node, top_n: int = 1000) -> Analysis:
    result = Analysis()
    ext_stats = result.ext_stats
    cat_stats = result.cat_stats
    heap: list[tuple[int, int, Node]] = []
    counter = 0

    start_override = _context_override(node) if node.parent is not None else None
    if (
        start_override is None
        and not node.is_dir
        and node.parent is not None
        and node.parent.parent is None
        and is_drive_root(node.parent.name)
    ):
        start_override = categories.root_file_override(node.name)
    root_is_drive = node.parent is None and is_drive_root(node.name)

    if not node.is_dir:
        stack: list[tuple[Node, str | None]] = []
        files_iter = [(node, start_override)]
    else:
        stack = [(node, start_override)]
        files_iter = []

    def add_file(f: Node, override: str | None) -> None:
        nonlocal counter
        ext = f.ext
        s = ext_stats.get(ext)
        if s is None:
            ext_stats[ext] = [f.size, 1]
        else:
            s[0] += f.size
            s[1] += 1
        cat = override or categories.category_for_ext(ext)
        cat_stats[cat] = cat_stats.get(cat, 0) + f.size
        counter += 1
        if top_n <= 0:
            return
        if len(heap) < top_n:
            heapq.heappush(heap, (f.size, counter, f))
        elif f.size > heap[0][0]:
            heapq.heapreplace(heap, (f.size, counter, f))

    for f, ov in files_iter:
        add_file(f, ov)

    while stack:
        n, override = stack.pop()
        at_root = root_is_drive and n is node
        for c in n.children:
            if c.is_dir:
                ov = override or categories.folder_override(c.name, at_root)
                stack.append((c, ov))
            else:
                ov = override or (categories.root_file_override(c.name) if at_root else None)
                add_file(c, ov)

    result.top_files = [item[2] for item in sorted(heap, key=lambda t: t[0], reverse=True)]
    return result


def detach(node: Node) -> None:
    """Remove a node from the tree and subtract its totals from all ancestors."""
    parent = node.parent
    if parent is None:
        return
    children = parent.children
    if node.idx < len(children) and children[node.idx] is node:
        pos = node.idx
    else:
        pos = next((i for i, c in enumerate(children) if c is node), -1)
        if pos < 0:
            return
    children.pop(pos)
    for i in range(pos, len(children)):
        children[i].idx = i
    files = node.files if node.is_dir else 1
    dirs = node.dirs + 1 if node.is_dir else 0
    for a in node.ancestors():
        a.size -= node.size
        a.files -= files
        a.dirs -= dirs
    node.parent = None


def is_attached(node: Node, root: Node) -> bool:
    n = node
    while n.parent is not None:
        n = n.parent
    return n is root


def collapse_selection(nodes: list[Node]) -> list[Node]:
    """Drop nodes that are inside another selected folder, and duplicates."""
    chosen = {id(n): n for n in nodes}
    out = []
    for n in chosen.values():
        if any(id(a) in chosen for a in n.ancestors()):
            continue
        out.append(n)
    return out


def find_node(root: Node, path: str) -> Node | None:
    """Locate a node by absolute path (case-insensitive on Windows)."""
    norm = os.path.normcase
    root_path = os.path.normpath(root.name)
    target = os.path.normpath(path)
    try:
        rel = os.path.relpath(target, root_path)
    except ValueError:
        return None
    if rel == ".":
        return root
    if rel.startswith(".."):
        return None
    node = root
    for part in rel.split(os.sep):
        part_n = norm(part)
        nxt = None
        for c in node.children or ():
            if norm(c.name) == part_n:
                nxt = c
                break
        if nxt is None:
            return None
        node = nxt
    return node
