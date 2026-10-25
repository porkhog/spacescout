"""End-to-end UI tests (run headless with QT_QPA_PLATFORM=offscreen)."""

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spacescout import safety  # noqa: E402
from spacescout.scanner import find_node  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyle("Fusion")
    yield a


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def write(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from spacescout.ui import controller, main_window

    monkeypatch.setattr(main_window.QSettings, "value", lambda self, key, default=None: default)
    monkeypatch.setattr(controller, "confirm", lambda *a, **k: True)
    infos = []
    monkeypatch.setattr(controller, "info", lambda *a, **k: infos.append(a))
    w = main_window.MainWindow()
    w.infos = infos
    w.resize(1200, 800)
    w.show()
    yield w
    w.close()


def scan(win, path):
    win.start_scan(str(path))
    for _ in range(200):
        if win._scan_thread is None:
            break
        wait(25)
    assert win.result is not None


def make(tmp_path):
    base = tmp_path / "data"
    write(base / "videos" / "a.mp4", 5000)
    write(base / "videos" / "b.mp4", 3000)
    write(base / "docs" / "c.pdf", 1000)
    write(base / "big.iso", 9000)
    return base


def test_scan_and_both_modes(win, tmp_path):
    base = make(tmp_path)
    scan(win, base)
    assert win.result.root.size == 18000
    assert win.stack.currentWidget() is win.simple
    win.mode_switch.set_index(1)
    win.set_mode(1)
    assert win.stack.currentWidget() is win.advanced
    model = win.advanced.tree_model
    root_idx = model.index(0, 0)
    assert model.rowCount(root_idx) == 3
    assert model.data(model.index(0, 0, root_idx)) == "big.iso"
    # sorting by name keeps a consistent tree
    model.sort(0, 0)
    names = [model.data(model.index(r, 0, root_idx)) for r in range(3)]
    assert names == sorted(names, key=str.casefold)
    # treemap lays something out
    win.advanced.treemap.repaint()
    assert len(win.advanced.treemap._items) > 3


def test_permanent_delete_updates_everything(win, tmp_path):
    base = make(tmp_path)
    scan(win, base)
    win.mode_switch.set_index(1)
    win.set_mode(1)
    node = find_node(win.result.root, str(base / "videos"))
    win.actions.delete([node], permanent=True)
    assert not (base / "videos").exists()
    assert win.result.root.size == 10000
    model = win.advanced.tree_model
    assert model.rowCount(model.index(0, 0)) == 2
    assert all(f.name not in ("a.mp4", "b.mp4") for f in win.result.analysis.top_files)
    assert win.result.analysis.cat_stats.get("videos", 0) == 0


def test_recycle_from_simple_mode(win, tmp_path, monkeypatch):
    from spacescout import fileops

    base = make(tmp_path)
    scan(win, base)
    recycled = []

    def fake_recycle(paths, progress=None, cancel=None, sizes=None):
        res = fileops.OpResult()
        for p in paths:
            recycled.append(p)
            fileops.remove_path(p)
            res.done.append(p)
            res.bytes_done += (sizes or {}).get(p, 0)
        return res

    monkeypatch.setattr(fileops, "recycle", fake_recycle)
    node = find_node(win.result.root, str(base / "big.iso"))
    win.actions.delete([node])
    assert recycled == [str(base / "big.iso")]
    assert win.result.pending_recycle == 9000
    assert win.result.root.size == 9000


def test_move_to_other_folder(win, tmp_path, monkeypatch):
    from spacescout.ui import controller

    base = make(tmp_path)
    dest = tmp_path / "otherdrive"
    scan(win, base)

    class FakeMoveDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def values(self):
            return str(dest), False, False

    monkeypatch.setattr(controller, "MoveDialog", FakeMoveDialog)
    monkeypatch.setattr(controller.QMessageBox, "exec", lambda self: 0)
    node = find_node(win.result.root, str(base / "docs"))
    win.actions.move([node])
    assert (dest / "docs" / "c.pdf").stat().st_size == 1000
    assert not (base / "docs").exists()
    assert win.result.root.size == 17000


def test_simple_mode_blocks_caution_paths(win, tmp_path, monkeypatch):
    from spacescout.ui import controller

    base = make(tmp_path)
    scan(win, base)
    monkeypatch.setattr(controller.safety, "worst",
                        lambda paths, **k: safety.Protection(safety.Level.CAUTION, "Programs live here."))
    node = find_node(win.result.root, str(base / "big.iso"))
    win.actions.delete([node], permanent=True)
    assert (base / "big.iso").exists()
    assert win.infos and "Simple mode" in win.infos[-1][1]


def test_critical_paths_blocked_in_advanced(win, tmp_path, monkeypatch):
    from spacescout.ui import controller

    base = make(tmp_path)
    scan(win, base)
    win.mode_switch.set_index(1)
    win.set_mode(1)
    monkeypatch.setattr(controller.safety, "worst",
                        lambda paths, **k: safety.Protection(safety.Level.CRITICAL, "Windows needs this."))
    node = find_node(win.result.root, str(base / "big.iso"))
    win.actions.delete([node], permanent=True)
    win.actions.move([node])
    assert (base / "big.iso").exists()


def test_theme_toggle(win, tmp_path):
    from spacescout.ui import theme

    before = theme.current()["name"]
    win.toggle_theme()
    assert theme.current()["name"] != before
    win.toggle_theme()
    assert theme.current()["name"] == before


def test_clicking_row_buttons_in_simple_mode(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from spacescout import fileops
    from spacescout.ui.simple_view import ItemRow

    base = make(tmp_path)
    scan(win, base)

    def fake_recycle(paths, progress=None, cancel=None, sizes=None):
        res = fileops.OpResult()
        for p in paths:
            fileops.remove_path(p)
            res.done.append(p)
        return res

    monkeypatch.setattr(fileops, "recycle", fake_recycle)
    rows = [win.simple.rows_host.itemAt(i).widget() for i in range(win.simple.rows_host.count())]
    rows = [r for r in rows if isinstance(r, ItemRow)]
    target = next(r for r in rows if r.node.name == "big.iso")
    delete_btn = next(b for b in target.findChildren(QPushButton) if b.text() == "Delete")
    delete_btn.click()
    wait(100)
    assert not (base / "big.iso").exists()
    names = [win.simple.rows_host.itemAt(i).widget().node.name for i in range(win.simple.rows_host.count())
             if isinstance(win.simple.rows_host.itemAt(i).widget(), ItemRow)]
    assert "big.iso" not in names
    # drill into a folder by clicking its row
    videos = next(r for r in rows if r.node.name == "videos")
    win.simple._row_activated(videos.node)
    assert win.simple.current.name == "videos"


def test_overview_includes_hidden_space(win, tmp_path):
    from spacescout.drives import DriveInfo

    base = make(tmp_path)
    scan(win, base)
    r = win.result
    r.is_drive = True
    r.drive = DriveInfo("X", "X", "", total=100_000, used=50_000, free=50_000)
    parts = dict(r.overview())
    assert parts["hidden"] == 50_000 - 18_000
    assert parts["videos"] == 8000


def test_treemap_hit_testing(app):
    from spacescout.scanner import Node, finalize
    from spacescout.ui.treemap import TreemapWidget

    root = Node("R", None, True)
    a = Node("a", root, True)
    root.children.append(a)
    for i in range(50):
        a.children.append(Node(f"f{i}.mp4", a, False, size=1000 + i))
    big = Node("big.iso", root, False, size=60_000)
    root.children.append(big)
    finalize(root)
    tm = TreemapWidget()
    tm.resize(600, 400)
    tm.set_root(root)
    tm.grab()  # forces layout + render
    assert tm._items
    for r, node, _d in tm._items[1:]:
        hit = tm.node_at(r.center())
        assert hit is node or node.is_dir  # a folder's centre is covered by one of its children
    from PySide6.QtCore import QPointF

    assert tm.node_at(QPointF(-5, -5)) is None
