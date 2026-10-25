"""Delete (to Recycle Bin or permanently), move to another drive, and cleanup helpers.

All long-running functions take an optional `progress(done, total, label)`
callback and a `cancel` threading.Event so the UI can show progress and stop.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .drives import same_drive
from .utils import IS_MAC, IS_WINDOWS, format_size, long_path

ProgressFn = Callable[[int, int, str], None]

CHUNK = 4 * 1024 * 1024


class Cancelled(Exception):
    pass


@dataclass
class OpResult:
    done: list[str] = field(default_factory=list)  # source paths that were handled
    failed: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    bytes_done: int = 0
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)
    targets: dict[str, str] = field(default_factory=dict)  # src -> dst (moves)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.cancelled


def _noop(*_a) -> None:
    pass


def path_size(path: str) -> int:
    """Total size of a file or folder (walks the folder)."""
    try:
        if not os.path.isdir(path) or os.path.islink(path):
            return os.lstat(path).st_size
    except OSError:
        return 0
    total = 0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


# ---------------------------------------------------------------------------
# Recycle Bin
# ---------------------------------------------------------------------------


def _win_recycle(path: str) -> str | None:
    """Send one path to the Recycle Bin. Returns an error message or None."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            _pack_ = 1
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400
    FOF_WANTNUKEWARNING = 0x4000  # warn instead of silently deleting if it won't fit in the bin

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"  # must be double-null terminated
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if op.fAnyOperationsAborted:
        return "Cancelled"
    if rc != 0:
        if os.path.exists(path):
            return f"Windows couldn't recycle it (code {rc:#x}). It may be open in another program."
    return None


def recycle(paths: list[str], progress: ProgressFn | None = None, cancel: threading.Event | None = None,
            sizes: dict[str, int] | None = None) -> OpResult:
    progress = progress or _noop
    res = OpResult()
    total = len(paths)
    for i, path in enumerate(paths):
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        progress(i, total, path)
        try:
            if IS_WINDOWS:
                err = _win_recycle(path)
            else:
                from send2trash import send2trash

                send2trash(path)
                err = None
        except Exception as exc:  # noqa: BLE001
            err = str(exc) or exc.__class__.__name__
        if err:
            res.failed.append((path, err))
        else:
            res.done.append(path)
            res.bytes_done += (sizes or {}).get(path, 0)
    progress(total, total, "")
    return res


# ---------------------------------------------------------------------------
# Permanent delete
# ---------------------------------------------------------------------------


def _make_writable_and_retry(func, path, _exc) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    func(path)


def _rmtree(path: str) -> None:
    lp = long_path(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(lp, onexc=_make_writable_and_retry)
    else:  # pragma: no cover
        shutil.rmtree(lp, onerror=_make_writable_and_retry)


def remove_path(path: str) -> None:
    """Permanently remove a file or folder (clears read-only flags)."""
    lp = long_path(path)
    if os.path.isdir(lp) and not os.path.islink(lp):
        _rmtree(path)
    else:
        try:
            os.remove(lp)
        except PermissionError:
            os.chmod(lp, stat.S_IWRITE | stat.S_IREAD)
            os.remove(lp)


def delete_permanently(paths: list[str], progress: ProgressFn | None = None,
                       cancel: threading.Event | None = None, sizes: dict[str, int] | None = None) -> OpResult:
    progress = progress or _noop
    res = OpResult()
    total = len(paths)
    for i, path in enumerate(paths):
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        progress(i, total, path)
        try:
            remove_path(path)
            res.done.append(path)
            res.bytes_done += (sizes or {}).get(path, 0)
        except OSError as exc:
            if os.path.exists(path):
                res.failed.append((path, _friendly_error(exc)))
            else:
                res.done.append(path)
    progress(total, total, "")
    return res


def _friendly_error(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "Access denied - it may be in use, or you need to run as administrator."
    if isinstance(exc, FileNotFoundError):
        return "It no longer exists."
    return exc.strerror or str(exc)


# ---------------------------------------------------------------------------
# Move to another drive
# ---------------------------------------------------------------------------


def unique_path(path: str) -> str:
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    if os.path.isdir(path):
        base, ext = path, ""
    n = 2
    while os.path.lexists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def target_for(src: str, dest_root: str, keep_structure: bool) -> str:
    """Where `src` should end up inside `dest_root`.

    keep_structure=True  ->  D:\\Moved\\Users\\Bob\\Videos   (mirrors the original location)
    keep_structure=False ->  D:\\Moved\\Videos
    """
    src = os.path.abspath(src)
    if keep_structure:
        drive, rest = os.path.splitdrive(src)
        rest = rest.lstrip("\\/")
        return os.path.join(dest_root, rest)
    return os.path.join(dest_root, os.path.basename(src.rstrip("\\/")))


class _Progress:
    def __init__(self, total: int, cb: ProgressFn, cancel: threading.Event | None):
        self.done = 0
        self.total = total
        self.cb = cb
        self.cancel = cancel
        self.label = ""
        self._last = 0.0

    def add(self, n: int) -> None:
        self.done += n
        now = time.monotonic()
        if now - self._last > 0.05:
            self._last = now
            self.cb(min(self.done, self.total), self.total, self.label)

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()


def _copy_file_with_progress(src: str, dst: str, prog: _Progress) -> None:
    prog.label = src
    prog.check()
    expected = os.path.getsize(long_path(src))
    with open(long_path(src), "rb") as fi, open(long_path(dst), "xb") as fo:
        while True:
            buf = fi.read(CHUNK)
            if not buf:
                break
            fo.write(buf)
            prog.add(len(buf))
            prog.check()
    try:
        shutil.copystat(long_path(src), long_path(dst))
    except OSError:
        pass
    if os.path.getsize(long_path(dst)) != expected:
        raise OSError(f"Copy of {src} is incomplete")


def make_junction(link: str, target: str) -> bool:
    """Create a Windows directory junction so the old path keeps working."""
    if not IS_WINDOWS:
        return False
    try:
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.returncode == 0
    except OSError:
        return False


def move_items(
    paths: list[str],
    dest_root: str,
    keep_structure: bool = True,
    leave_link: bool = False,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    sizes: dict[str, int] | None = None,
    force_copy: bool = False,
) -> OpResult:
    """Move files/folders into `dest_root`.

    Across drives every item is copied first, checked, and only then is the
    original removed - so a failure or cancel never loses data.
    """
    progress = progress or _noop
    sizes = dict(sizes or {})
    for p in paths:
        if p not in sizes:
            sizes[p] = path_size(p)
    prog = _Progress(sum(sizes.values()), progress, cancel)
    res = OpResult()

    for src in paths:
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        dst = unique_path(target_for(src, dest_root, keep_structure))
        is_dir = os.path.isdir(src) and not os.path.islink(src)
        prog.label = src
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        except OSError as exc:
            res.failed.append((src, f"Couldn't create the destination folder: {_friendly_error(exc)}"))
            continue

        # Same drive: a rename is instant and atomic.
        if not force_copy and same_drive(src, dest_root):
            try:
                os.rename(long_path(src), long_path(dst))
                prog.add(sizes[src])
                res.done.append(src)
                res.targets[src] = dst
                res.bytes_done += sizes[src]
                continue
            except OSError:
                pass  # fall back to copy

        try:
            if is_dir:
                shutil.copytree(
                    long_path(src),
                    long_path(dst),
                    symlinks=True,
                    copy_function=lambda s, d: _copy_file_with_progress(s, d, prog),
                )
            else:
                _copy_file_with_progress(src, dst, prog)
        except Cancelled:
            _discard(dst)
            res.cancelled = True
            break
        except (OSError, shutil.Error) as exc:
            _discard(dst)
            msg = _friendly_error(exc) if isinstance(exc, OSError) else _copytree_error(exc)
            res.failed.append((src, f"Nothing was moved - copying failed: {msg}"))
            continue

        # Copy is complete and verified; remove the original.
        try:
            remove_path(src)
        except OSError as exc:
            res.notes.append(
                f"{os.path.basename(src)} was copied to {dst}, but some original files couldn't be "
                f"removed ({_friendly_error(exc)}). Close any program using them and delete them manually."
            )
        res.done.append(src)
        res.targets[src] = dst
        res.bytes_done += sizes[src]

        if leave_link and is_dir and not os.path.exists(src):
            if make_junction(src, dst):
                res.notes.append(f"Left a link at {src} pointing to the new location.")
            else:
                res.notes.append(f"Couldn't create a link at {src}.")

    progress(prog.total, prog.total, "")
    return res


def _copytree_error(exc: shutil.Error) -> str:
    try:
        first = exc.args[0][0]
        return f"{first[0]}: {first[2]}"
    except Exception:  # noqa: BLE001
        return str(exc)


def _discard(path: str) -> None:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            _rmtree(path)
        elif os.path.lexists(path):
            remove_path(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Quick-cleanup helpers for Simple mode
# ---------------------------------------------------------------------------


def downloads_folder() -> str:
    if IS_WINDOWS:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")
            g = GUID()
            ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def temp_folders() -> list[str]:
    dirs = [tempfile.gettempdir()]
    if IS_WINDOWS:
        sys_temp = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")
        if os.access(sys_temp, os.W_OK):
            dirs.append(sys_temp)
    out = []
    for d in dirs:
        d = os.path.realpath(d)
        if d not in out and os.path.isdir(d):
            out.append(d)
    return out


@dataclass
class TempInfo:
    total: int = 0
    cleanable: int = 0
    items: list[str] = field(default_factory=list)


def _newest_mtime(path: str) -> float:
    try:
        newest = os.lstat(path).st_mtime
    except OSError:
        return time.time()
    if os.path.isdir(path) and not os.path.islink(path):
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    newest = max(newest, os.lstat(os.path.join(dirpath, f)).st_mtime)
                except OSError:
                    pass
    return newest


def measure_temp(min_age_hours: float = 24) -> TempInfo:
    """Size of temp folders and how much is older than `min_age_hours`."""
    info = TempInfo()
    cutoff = time.time() - min_age_hours * 3600
    for folder in temp_folders():
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            size = path_size(e.path)
            info.total += size
            if _newest_mtime(e.path) < cutoff:
                info.cleanable += size
                info.items.append(e.path)
    return info


def clean_temp(items: Iterable[str], progress: ProgressFn | None = None,
               cancel: threading.Event | None = None) -> OpResult:
    items = list(items)
    sizes = {p: path_size(p) for p in items}
    res = delete_permanently(items, progress, cancel, sizes)
    # Files in use are normal for temp folders - don't report them as errors.
    res.notes = [f"{len(res.failed)} items were in use and were skipped."] if res.failed else []
    res.failed = []
    return res


def _posix_trash_dir() -> str | None:
    if IS_MAC:
        return os.path.expanduser("~/.Trash")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "Trash")


def recycle_bin_info() -> tuple[int, int]:
    """(bytes, item count) in the Recycle Bin / Trash for all drives."""
    if IS_WINDOWS:
        try:
            import ctypes

            class SHQUERYRBINFO(ctypes.Structure):
                if ctypes.sizeof(ctypes.c_void_p) == 4:
                    _pack_ = 1
                _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]

            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
                return int(info.i64Size), int(info.i64NumItems)
        except Exception:
            pass
        return 0, 0
    trash = _posix_trash_dir()
    files_dir = os.path.join(trash, "files") if not IS_MAC else trash
    try:
        names = os.listdir(files_dir)
    except OSError:
        return 0, 0
    return path_size(files_dir), len(names)


def empty_recycle_bin() -> str | None:
    """Empty the Recycle Bin. Returns an error message or None."""
    if IS_WINDOWS:
        try:
            import ctypes

            SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
            hr = ctypes.windll.shell32.SHEmptyRecycleBinW(
                None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
            )
            hr &= 0xFFFFFFFF
            if hr not in (0, 0x8000FFFF):  # E_UNEXPECTED is returned when the bin is already empty
                return f"Windows reported error {hr:#x}"
            return None
        except Exception as exc:  # noqa: BLE001
            return str(exc)
    trash = _posix_trash_dir()
    subdirs = [trash] if IS_MAC else [os.path.join(trash, "files"), os.path.join(trash, "info")]
    for d in subdirs:
        try:
            for name in os.listdir(d):
                try:
                    remove_path(os.path.join(d, name))
                except OSError:
                    pass
        except OSError:
            pass
    return None


def describe_result(res: OpResult, verb: str) -> str:
    parts = []
    if res.done:
        parts.append(f"{verb} {len(res.done)} item{'s' if len(res.done) != 1 else ''}"
                     + (f" ({format_size(res.bytes_done)})" if res.bytes_done else "") + ".")
    if res.cancelled:
        parts.append("Stopped before finishing.")
    if res.failed:
        parts.append(f"{len(res.failed)} couldn't be processed.")
    return " ".join(parts) or "Nothing was changed."
