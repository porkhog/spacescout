"""Windows-only checks (run on the windows-latest CI runner)."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_list_drives_has_system_drive():
    from spacescout.drives import list_drives

    drives = list_drives()
    sys_drive = os.environ.get("SystemDrive", "C:").upper() + "\\"
    assert any(d.path.upper() == sys_drive for d in drives)
    for d in drives:
        assert d.total > 0 and d.free >= 0
        assert d.letter.endswith(":")


def test_known_folders_and_recycle_bin_query():
    from spacescout import fileops

    assert isinstance(fileops.downloads_folder(), str)
    size, count = fileops.recycle_bin_info()
    assert size >= 0 and count >= 0
    assert fileops.temp_folders()


def test_scanner_skips_junctions(tmp_path):
    from spacescout import fileops
    from spacescout.scanner import Scanner

    real = tmp_path / "real"
    real.mkdir()
    (real / "data.bin").write_bytes(b"x" * 5000)
    link = tmp_path / "link"
    assert fileops.make_junction(str(link), str(real))
    root = Scanner(str(tmp_path)).run()
    assert root.size == 5000  # counted once, not twice
    assert [c.name for c in root.children] == ["real"]


def test_move_with_link_left_behind(tmp_path):
    from spacescout import fileops

    src = tmp_path / "Game"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "big.pak").write_bytes(b"y" * 2000)
    dest = tmp_path / "Other drive"
    res = fileops.move_items([str(src)], str(dest), keep_structure=False, leave_link=True, force_copy=True)
    assert res.ok, res.failed
    assert (dest / "Game" / "sub" / "big.pak").stat().st_size == 2000
    # the old path still works through the junction
    assert (src / "sub" / "big.pak").read_bytes() == b"y" * 2000


def test_safety_on_this_machine():
    from spacescout.safety import Level, classify

    windir = os.environ.get("SystemRoot", r"C:\Windows")
    assert classify(windir).level == Level.CRITICAL
    assert classify(os.path.join(windir, "System32")).level == Level.CRITICAL
    assert classify(os.environ["USERPROFILE"]).level == Level.CRITICAL
