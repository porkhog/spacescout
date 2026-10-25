import os

from spacescout.scanner import Scanner, analyze, collapse_selection, detach, find_node, is_attached, iter_files


def make_tree(base):
    files = {
        "videos/holiday.mp4": 5000,
        "videos/clip.mkv": 3000,
        "photos/a.jpg": 400,
        "photos/b.png": 600,
        "photos/2023/c.jpg": 1000,
        "docs/report.pdf": 200,
        "big.iso": 8000,
        "empty/.keep": 0,
        "notes.txt": 10,
    }
    for rel, size in files.items():
        path = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
    return files


def test_scan_totals(tmp_path):
    files = make_tree(tmp_path)
    root = Scanner(str(tmp_path), workers=4).run()
    assert root.size == sum(files.values())
    assert root.files == len(files)
    assert root.dirs == 5  # videos, photos, photos/2023, docs, empty
    # largest first
    sizes = [c.size for c in root.children]
    assert sizes == sorted(sizes, reverse=True)
    assert {c.name for c in root.children[:2]} == {"big.iso", "videos"}
    videos = find_node(root, os.path.join(tmp_path, "videos"))
    assert videos.size == 8000 and videos.files == 2
    assert find_node(root, os.path.join(tmp_path, "photos", "2023", "c.jpg")).size == 1000
    for n in root.children:
        assert root.children[n.idx] is n


def test_scan_progress_counters(tmp_path):
    files = make_tree(tmp_path)
    s = Scanner(str(tmp_path))
    s.run()
    assert s.files == len(files)
    assert s.bytes == sum(files.values())
    assert s.errors == 0


def test_cancel(tmp_path):
    make_tree(tmp_path)
    s = Scanner(str(tmp_path))
    s.cancel()
    root = s.run()
    assert root.size == 0


def test_analyze(tmp_path):
    make_tree(tmp_path)
    root = Scanner(str(tmp_path)).run()
    a = analyze(root, top_n=3)
    assert [f.name for f in a.top_files] == ["big.iso", "holiday.mp4", "clip.mkv"]
    assert a.cat_stats["videos"] == 8000
    assert a.cat_stats["pictures"] == 2000
    assert a.cat_stats["archives"] == 8000
    assert a.ext_stats[".jpg"] == [1400, 2]


def test_detach_updates_ancestors(tmp_path):
    make_tree(tmp_path)
    root = Scanner(str(tmp_path)).run()
    total = root.size
    c = find_node(root, os.path.join(tmp_path, "photos", "2023", "c.jpg"))
    photos = find_node(root, os.path.join(tmp_path, "photos"))
    detach(c)
    assert root.size == total - 1000
    assert photos.size == 1000
    assert photos.files == 2
    assert not is_attached(c, root)
    detach(photos)
    assert root.size == total - 2000
    assert all(root.children[i].idx == i for i in range(len(root.children)))


def test_collapse_selection(tmp_path):
    make_tree(tmp_path)
    root = Scanner(str(tmp_path)).run()
    photos = find_node(root, os.path.join(tmp_path, "photos"))
    a = find_node(root, os.path.join(tmp_path, "photos", "a.jpg"))
    iso = find_node(root, os.path.join(tmp_path, "big.iso"))
    assert set(map(id, collapse_selection([photos, a, iso, iso]))) == {id(photos), id(iso)}


def test_iter_files(tmp_path):
    files = make_tree(tmp_path)
    root = Scanner(str(tmp_path)).run()
    assert len(list(iter_files(root))) == len(files)


def test_node_path_roundtrip(tmp_path):
    make_tree(tmp_path)
    root = Scanner(str(tmp_path)).run()
    for f in iter_files(root):
        assert os.path.isfile(f.path)
