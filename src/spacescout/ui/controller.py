"""Scan results shared by both modes, and the delete/move actions (with all the safety checks)."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from .. import categories, fileops, safety
from ..drives import DriveInfo, usage_for
from ..scanner import Analysis, Node, analyze, collapse_selection, detach, is_attached, is_drive_root
from ..utils import format_size, open_with_default_app, reveal_in_file_manager
from .dialogs import MoveDialog, ProgressDialog, confirm, info


class ScanResult(QObject):
    aboutToRemove = Signal(object)
    removed = Signal(object)
    changed = Signal()

    def __init__(self, root: Node, analysis: Analysis, drive: DriveInfo | None, elapsed: float, errors: int):
        super().__init__()
        self.root = root
        self.analysis = analysis
        self.drive = drive
        self.elapsed = elapsed
        self.errors = errors
        self.pending_recycle = 0  # bytes sent to the Recycle Bin during this session
        self.is_drive = is_drive_root(root.name)

    @property
    def title(self) -> str:
        if self.is_drive and self.drive:
            return self.drive.title
        return os.path.basename(self.root.name.rstrip("\\/")) or self.root.name

    def remove_nodes(self, nodes: list[Node]) -> None:
        nodes = [n for n in collapse_selection(nodes) if n is not self.root and is_attached(n, self.root)]
        if not nodes:
            return
        for n in nodes:
            sub = analyze(n, top_n=0)
            for ext, (size, count) in sub.ext_stats.items():
                s = self.analysis.ext_stats.get(ext)
                if s:
                    s[0] -= size
                    s[1] -= count
            for cat, size in sub.cat_stats.items():
                self.analysis.cat_stats[cat] = self.analysis.cat_stats.get(cat, 0) - size
            self.aboutToRemove.emit(n)
            detach(n)
            self.removed.emit(n)
        self.analysis.top_files = [f for f in self.analysis.top_files if is_attached(f, self.root)]

    def refresh_drive(self) -> None:
        d = usage_for(self.root.name)
        if d is not None:
            self.drive = d

    def overview(self) -> list[tuple[str, int]]:
        """(category key, bytes) for the overview bar, biggest first, incl. hidden space."""
        cats = dict(self.analysis.cat_stats)
        cats["recycle"] = cats.get("recycle", 0) + self.pending_recycle
        out = [(k, v) for k, v in cats.items() if v > 0]
        out.sort(key=lambda kv: kv[1], reverse=True)
        if self.is_drive and self.drive:
            hidden = self.drive.used - sum(v for _k, v in out)
            if hidden > self.drive.total * 0.002:
                out.append((categories.HIDDEN.key, hidden))
        return out


class Actions(QObject):
    """Delete / move / open actions used by both Simple and Advanced views."""

    def __init__(self, window):
        super().__init__(window)
        self.win = window

    @property
    def result(self) -> ScanResult | None:
        return self.win.result

    @property
    def advanced(self) -> bool:
        return self.win.is_advanced()

    # ---- helpers -------------------------------------------------------
    def _prepare(self, nodes) -> list[Node]:
        if self.result is None:
            return []
        nodes = [n for n in nodes if n is not None]
        return [n for n in collapse_selection(nodes) if n.parent is not None and is_attached(n, self.result.root)]

    def check_safety(self, paths: list[str], verb: str) -> bool:
        pr = safety.worst(paths)
        if pr.level == safety.Level.CRITICAL:
            info(self.win, f"Can't {verb} this", "This item is protected to keep your PC working.", pr.reason,
                 warning=True)
            return False
        if pr.level == safety.Level.CAUTION:
            if not self.advanced:
                info(self.win, "Protected in Simple mode",
                     "To keep your PC safe, Simple mode won't touch this.",
                     pr.reason + "\n\nIf you really know what you're doing, you can switch to Advanced mode.",
                     warning=True)
                return False
            return confirm(self.win, "Are you sure?", "This might break something.",
                           pr.reason, ok_text=f"{verb.capitalize()} anyway", danger=True)
        return True

    @staticmethod
    def _what(nodes: list[Node]) -> str:
        return f"“{nodes[0].name}”" if len(nodes) == 1 else f"{len(nodes)} items"

    def _report(self, res: fileops.OpResult, verb: str, extra: str = "") -> None:
        if res.failed:
            details = "\n".join(f"{p}\n    {why}" for p, why in res.failed[:50])
            info(self.win, "Some items couldn't be processed", fileops.describe_result(res, verb),
                 "\n".join(res.notes) or "Click 'Show Details' to see which ones and why.", details, warning=True)
        elif res.notes:
            info(self.win, "Done", fileops.describe_result(res, verb), "\n".join(res.notes))
        else:
            self.win.toast(fileops.describe_result(res, verb) + (" " + extra if extra else ""))

    def _apply(self, nodes_by_path: dict[str, Node], res: fileops.OpResult) -> None:
        done = [nodes_by_path[p] for p in res.done if p in nodes_by_path]
        self.result.remove_nodes(done)
        self.result.refresh_drive()
        self.result.changed.emit()

    # ---- actions -------------------------------------------------------
    def delete(self, nodes, permanent: bool = False) -> None:
        nodes = self._prepare(nodes)
        if not nodes:
            return
        by_path = {n.path: n for n in nodes}
        paths = list(by_path)
        if not self.check_safety(paths, "delete"):
            return
        total = sum(n.size for n in nodes)
        what = self._what(nodes)
        if permanent:
            if not confirm(self.win, "Delete permanently?", f"Permanently delete {what}?",
                           f"{format_size(total)} will be erased right away. This can't be undone.",
                           ok_text="Delete permanently", danger=True):
                return
            title, fn, verb = "Deleting…", fileops.delete_permanently, "Deleted"
        else:
            if not confirm(self.win, "Move to Recycle Bin?", f"Move {what} to the Recycle Bin?",
                           f"{format_size(total)}. You can restore it from the Recycle Bin if you change your mind. "
                           f"The space is freed when you empty the Recycle Bin.",
                           ok_text="Move to Recycle Bin"):
                return
            title, fn, verb = "Moving to Recycle Bin…", fileops.recycle, "Recycled"
        sizes = {p: by_path[p].size for p in paths}
        dlg = ProgressDialog(self.win, title)
        res = dlg.run(lambda prog, cancel: fn(paths, prog, cancel, sizes))
        if not permanent:
            self.result.pending_recycle += res.bytes_done
        self._apply(by_path, res)
        extra = "Empty the Recycle Bin to free the space." if not permanent and res.done else ""
        self._report(res, verb, extra)

    def move(self, nodes) -> None:
        nodes = self._prepare(nodes)
        if not nodes:
            return
        by_path = {n.path: n for n in nodes}
        paths = list(by_path)
        pr = safety.worst(paths)
        if pr.level == safety.Level.CRITICAL or (pr.level == safety.Level.CAUTION and not self.advanced):
            self.check_safety(paths, "move")
            return
        total = sum(n.size for n in nodes)
        dlg = MoveDialog(self.win, paths, total, self.advanced, caution=pr.reason if pr.level else "")
        if not dlg.exec():
            return
        dest, keep, link = dlg.values()
        sizes = {p: by_path[p].size for p in paths}
        prog_dlg = ProgressDialog(self.win, "Moving files…", bytes_mode=True)
        res = prog_dlg.run(lambda prog, cancel: fileops.move_items(paths, dest, keep, link, prog, cancel, sizes))
        self._apply(by_path, res)

        root_path = os.path.normcase(os.path.abspath(self.result.root.name))
        if os.path.normcase(os.path.abspath(dest)).startswith(root_path):
            res.notes.append("The destination is inside the scanned area - scan again to see updated totals.")
        if res.done and not res.failed:
            box = QMessageBox(self.win)
            box.setWindowTitle("Moved")
            box.setIcon(QMessageBox.Information)
            box.setText(f"<b>{fileops.describe_result(res, 'Moved')}</b>")
            box.setInformativeText(f"They're now in {dest}." + ("\n\n" + "\n".join(res.notes) if res.notes else ""))
            open_btn = box.addButton("Open destination", QMessageBox.ActionRole)
            box.addButton("OK", QMessageBox.AcceptRole).setProperty("kind", "primary")
            box.exec()
            if box.clickedButton() is open_btn:
                target = next(iter(res.targets.values()), dest)
                reveal_in_file_manager(target)
        else:
            self._report(res, "Moved")

    def reveal(self, node) -> None:
        if node is not None:
            reveal_in_file_manager(node.path)

    def open(self, node) -> None:
        if node is not None:
            open_with_default_app(node.path)

    def copy_paths(self, nodes) -> None:
        nodes = [n for n in nodes if n is not None]
        if nodes:
            QGuiApplication.clipboard().setText("\n".join(n.path for n in nodes))
            self.win.toast("Path copied" if len(nodes) == 1 else f"{len(nodes)} paths copied")

    def empty_recycle_bin(self) -> bool:
        size, count = fileops.recycle_bin_info()
        if not confirm(self.win, "Empty Recycle Bin?", "Permanently delete everything in the Recycle Bin?",
                       f"{count} items, {format_size(size)}. This can't be undone." if count else
                       "This can't be undone.", ok_text="Empty Recycle Bin", danger=True):
            return False
        err = fileops.empty_recycle_bin()
        if err:
            info(self.win, "Couldn't empty the Recycle Bin", err, warning=True)
            return False
        if self.result is not None:
            self.result.pending_recycle = 0
            bins = [c for c in self.result.root.children
                    if c.is_dir and c.name.lower() == "$recycle.bin"] if self.result.is_drive else []
            self.result.remove_nodes(bins)
            self.result.refresh_drive()
            self.result.changed.emit()
        self.win.toast(f"Recycle Bin emptied - {format_size(size)} freed." if size else "Recycle Bin emptied.")
        return True
