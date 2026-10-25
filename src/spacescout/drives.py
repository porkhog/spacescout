"""List the drives on this PC with their used/free space."""

from __future__ import annotations

import os
import shutil
import string
from dataclasses import dataclass

from .utils import IS_WINDOWS

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


@dataclass
class DriveInfo:
    path: str  # e.g. "C:\\"
    label: str  # e.g. "Windows" (volume label)
    fstype: str
    total: int
    used: int
    free: int
    removable: bool = False

    @property
    def letter(self) -> str:
        if IS_WINDOWS and len(self.path) >= 2 and self.path[1] == ":":
            return self.path[:2]
        return self.path

    @property
    def title(self) -> str:
        if IS_WINDOWS:
            name = self.label or ("USB drive" if self.removable else "Local Disk")
            return f"{name} ({self.letter})"
        return self.label or self.path

    @property
    def used_fraction(self) -> float:
        return self.used / self.total if self.total else 0.0


def _volume_label(path: str) -> str:
    if not IS_WINDOWS:
        return ""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(path), buf, 261, None, None, None, fs, 261
        )
        return buf.value if ok else ""
    except Exception:
        return ""


def _is_removable(path: str) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(path)) == 2  # DRIVE_REMOVABLE
    except Exception:
        return False


_SKIP_FS = {"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "autofs", "efivarfs", ""}


def list_drives() -> list[DriveInfo]:
    drives: list[DriveInfo] = []
    seen: set[str] = set()

    candidates: list[tuple[str, str]] = []
    if psutil is not None:
        try:
            for p in psutil.disk_partitions(all=False):
                if "cdrom" in p.opts or p.fstype.lower() in _SKIP_FS:
                    continue
                if not IS_WINDOWS and (
                    p.mountpoint.startswith(("/snap", "/boot", "/var/lib", "/run", "/dev", "/proc", "/sys"))
                    or "/System/Volumes/" in p.mountpoint
                ):
                    continue
                candidates.append((p.mountpoint, p.fstype))
        except Exception:
            candidates = []
    if not candidates:
        if IS_WINDOWS:
            candidates = [(f"{c}:\\", "") for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
        else:
            candidates = [("/", "")]

    for mount, fstype in candidates:
        key = os.path.normcase(mount)
        if key in seen:
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        if usage.total == 0:
            continue
        seen.add(key)
        drives.append(
            DriveInfo(
                path=mount,
                label=_volume_label(mount) if IS_WINDOWS else (os.path.basename(mount.rstrip("/")) or mount),
                fstype=fstype,
                total=usage.total,
                used=usage.total - usage.free,
                free=usage.free,
                removable=_is_removable(mount),
            )
        )
    drives.sort(key=lambda d: d.path.lower())
    return drives


def drive_of(path: str) -> str:
    """Return the drive / mount point that contains `path`."""
    path = os.path.abspath(path)
    if IS_WINDOWS:
        drive, _ = os.path.splitdrive(path)
        return drive + "\\"
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def same_drive(a: str, b: str) -> bool:
    return os.path.normcase(drive_of(a)) == os.path.normcase(drive_of(b))


def usage_for(path: str) -> DriveInfo | None:
    root = drive_of(path)
    for d in list_drives():
        if os.path.normcase(d.path) == os.path.normcase(root):
            return d
    try:
        u = shutil.disk_usage(root)
        return DriveInfo(root, os.path.basename(root) or root, "", u.total, u.total - u.free, u.free)
    except OSError:
        return None
