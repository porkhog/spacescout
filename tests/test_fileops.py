import os
import threading

import pytest

from spacescout import fileops


def write(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(size))


def test_delete_permanently(tmp_path):
    write(tmp_path / "a" / "b.bin", 100)
    write(tmp_path / "c.bin", 50)
    os.chmod(tmp_path / "c.bin", 0o444)  # read-only files still get removed
    res = fileops.delete_permanently([str(tmp_path / "a"), str(tmp_path / "c.bin")])
    assert res.ok
    assert not (tmp_path / "a").exists()
    assert not (tmp_path / "c.bin").exists()


@pytest.mark.parametrize("force_copy", [False, True])
def test_move_folder(tmp_path, force_copy):
    src = tmp_path / "src" / "Users" / "Bob" / "Videos"
    write(src / "one.mp4", 3000)
    write(src / "sub" / "two.mp4", 2000)
    dest = tmp_path / "dest"
    calls = []
    res = fileops.move_items([str(src)], str(dest), keep_structure=False,
                             progress=lambda d, t, _label: calls.append((d, t)), force_copy=force_copy)
    assert res.ok, res.failed
    assert not src.exists()
    assert (dest / "Videos" / "one.mp4").stat().st_size == 3000
    assert (dest / "Videos" / "sub" / "two.mp4").stat().st_size == 2000
    assert res.bytes_done == 5000
    assert calls[-1] == (5000, 5000)


def test_move_conflict_gets_unique_name(tmp_path):
    write(tmp_path / "a" / "file.txt", 10)
    write(tmp_path / "dest" / "file.txt", 5)
    res = fileops.move_items([str(tmp_path / "a" / "file.txt")], str(tmp_path / "dest"),
                             keep_structure=False, force_copy=True)
    assert res.ok
    assert (tmp_path / "dest" / "file (2).txt").stat().st_size == 10
    assert (tmp_path / "dest" / "file.txt").stat().st_size == 5


def test_move_cancel_keeps_source(tmp_path):
    src = tmp_path / "big"
    write(src / "x.bin", 3 * fileops.CHUNK)
    cancel = threading.Event()

    def progress(done, total, label):
        if done > 0:
            cancel.set()

    res = fileops.move_items([str(src)], str(tmp_path / "dest"), keep_structure=False,
                             progress=progress, cancel=cancel, force_copy=True)
    assert res.cancelled
    assert (src / "x.bin").stat().st_size == 3 * fileops.CHUNK  # original untouched
    assert not (tmp_path / "dest" / "big").exists()  # partial copy cleaned up


def test_target_for_keep_structure():
    t = fileops.target_for(os.path.join(os.sep, "home", "bob", "Videos"), os.path.join(os.sep, "mnt", "d", "Moved"), True)
    assert t == os.path.join(os.sep, "mnt", "d", "Moved", "home", "bob", "Videos")


def test_measure_and_clean_temp(tmp_path, monkeypatch):
    old = tmp_path / "old.tmp"
    new = tmp_path / "new.tmp"
    write(old, 100)
    write(new, 100)
    past = 1_000_000_000
    os.utime(old, (past, past))
    monkeypatch.setattr(fileops, "temp_folders", lambda: [str(tmp_path)])
    info = fileops.measure_temp(24)
    assert info.total == 200
    assert info.cleanable == 100
    assert info.items == [str(old)]
    res = fileops.clean_temp(info.items)
    assert res.bytes_done == 100
    assert not old.exists() and new.exists()


def test_path_size(tmp_path):
    write(tmp_path / "a" / "b", 10)
    write(tmp_path / "a" / "c" / "d", 20)
    assert fileops.path_size(str(tmp_path / "a")) == 30


def test_move_keep_structure(tmp_path):
    src = tmp_path / "Users" / "Bob" / "Videos" / "clip.mp4"
    write(src, 100)
    dest = tmp_path / "dest"
    res = fileops.move_items([str(src)], str(dest), keep_structure=True, force_copy=True)
    assert res.ok
    expected = fileops.target_for(str(src), str(dest), True)
    assert os.path.getsize(expected) == 100
    assert res.targets[str(src)] == expected
